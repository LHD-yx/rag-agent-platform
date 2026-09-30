"""多步检索 Agent：问题拆解 -> 多轮检索 -> 充分性判断 -> 生成。

单轮 RAG 的短板是多跳问题（"A 型号的 X 部件兼容哪些 B 型号"），
需要先拆成子问题分别检索，再合并证据生成答案。

两种实现：
    MultiHopAgent        不依赖额外框架，纯 Python 循环（默认可用）
    build_langgraph_agent 用 LangGraph 编排同样的节点（可以讲）

用法：python -m rag_agent.agent "A 型号的电源模块兼容哪些型号"
"""
from __future__ import annotations

from typing import Iterator, TypedDict

from .config import load_config
from .llm import build_llm
from .pipeline import RagPipeline

DECOMPOSE_PROMPT = """把下面的问题拆成 1~3 个可以独立检索的子问题。
要求：只输出子问题，每行一个，不要编号，不要解释。
如果问题本身不需要拆分，就原样输出一遍。

问题：{question}"""

SUFFICIENCY_PROMPT = """下面是为回答问题检索到的资料片段：

{snippets}

问题：{question}

这些资料是否足以回答问题？只回答"足够"或"不足"，不要解释。"""

REFINE_PROMPT = """为了回答下面的问题，现有资料还不够。请提出一个新的、更具体的检索查询。
只输出这个查询语句本身。

问题：{question}
已知信息：{snippets}"""


class AgentState(TypedDict, total=False):
    question: str
    sub_queries: list[str]
    results: list[dict]
    round: int
    sufficient: bool
    answer: dict


class MultiHopAgent:
    def __init__(self, cfg: dict | None = None, llm=None):
        self.cfg = cfg or load_config()
        self.pipeline = RagPipeline(self.cfg, llm=llm)
        self.llm = self.pipeline.llm
        self.max_rounds = self.cfg["agent"].get("max_rounds", 2)
        self.sub_query_top_k = self.cfg["agent"].get("sub_query_top_k", 5)

    # --- 节点 1：拆解 -------------------------------------------------
    def decompose(self, question: str) -> list[str]:
        text = self.llm.chat([{"role": "user", "content": DECOMPOSE_PROMPT.format(question=question)}])
        sub_queries = [line.strip(" -•\t") for line in text.splitlines() if line.strip()]
        return sub_queries or [question]

    # --- 节点 2：检索 -------------------------------------------------
    def retrieve_multi(self, sub_queries: list[str]) -> list[dict]:
        merged: dict[str, dict] = {}
        for query in sub_queries:
            for item in self.pipeline.retriever.retrieve(query, top_k=self.sub_query_top_k):
                key = item["chunk_id"]
                if key not in merged or item["score"] > merged[key]["score"]:
                    merged[key] = item
        results = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
        return self.pipeline.reranker.rerank(sub_queries[0], results)

    # --- 节点 3：充分性判断 -------------------------------------------
    def is_sufficient(self, question: str, results: list[dict]) -> bool:
        snippets = "\n\n".join(f"[{i}] {r['text'][:200]}" for i, r in enumerate(results, 1))
        verdict = self.llm.chat(
            [{"role": "user", "content": SUFFICIENCY_PROMPT.format(question=question, snippets=snippets)}],
            temperature=0.0,
        )
        return "足够" in verdict and "不足" not in verdict

    def refine_query(self, question: str, results: list[dict]) -> str:
        snippets = "\n".join(r["text"][:120] for r in results[:3])
        return self.llm.chat(
            [{"role": "user", "content": REFINE_PROMPT.format(question=question, snippets=snippets)}]
        ).strip()

    # --- 主循环 -------------------------------------------------------
    def run(self, question: str) -> dict:
        trace: list[dict] = []

        sub_queries = self.decompose(question)
        trace.append({"step": "decompose", "sub_queries": sub_queries})

        results = self.retrieve_multi(sub_queries)
        trace.append({"step": "retrieve", "round": 1, "count": len(results)})

        round_no = 1
        while round_no < self.max_rounds and not self.is_sufficient(question, results):
            new_query = self.refine_query(question, results)
            trace.append({"step": "refine", "round": round_no, "new_query": new_query})
            extra = self.retrieve_multi([new_query])
            merged = {r["chunk_id"]: r for r in results}
            for item in extra:
                merged.setdefault(item["chunk_id"], item)
            results = sorted(merged.values(), key=lambda x: x["score"], reverse=True)[: self.pipeline.generator.max_contexts]
            round_no += 1
            trace.append({"step": "retrieve", "round": round_no, "count": len(results)})

        answer = self.pipeline.generator.answer(question, results)
        return {"question": question, "trace": trace, "answer": answer, "contexts": results}


def build_langgraph_agent(cfg: dict | None = None):
    """用 LangGraph 编排同样的流程（需要 pip install langgraph）。"""
    try:
        from langgraph.graph import END, StateGraph
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("未安装 langgraph：pip install langgraph") from exc

    agent = MultiHopAgent(cfg)

    def node_decompose(state: AgentState) -> AgentState:
        return {"sub_queries": agent.decompose(state["question"]), "round": 1}

    def node_retrieve(state: AgentState) -> AgentState:
        if state.get("round", 1) == 1:
            results = agent.retrieve_multi(state["sub_queries"])
        else:
            new_query = agent.refine_query(state["question"], state["results"])
            extra = agent.retrieve_multi([new_query])
            merged = {r["chunk_id"]: r for r in state["results"]}
            for item in extra:
                merged.setdefault(item["chunk_id"], item)
            results = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
        return {"results": results}

    def node_judge(state: AgentState) -> AgentState:
        return {"sufficient": agent.is_sufficient(state["question"], state["results"])}

    def node_generate(state: AgentState) -> AgentState:
        return {"answer": agent.pipeline.generator.answer(state["question"], state["results"])}

    def route_after_judge(state: AgentState) -> str:
        if state["sufficient"] or state.get("round", 1) >= agent.max_rounds:
            return "generate"
        return "retrieve"

    graph = StateGraph(AgentState)
    graph.add_node("decompose", node_decompose)
    graph.add_node("retrieve", node_retrieve)
    graph.add_node("judge", node_judge)
    graph.add_node("generate", node_generate)
    graph.set_entry_point("decompose")
    graph.add_edge("decompose", "retrieve")
    graph.add_edge("retrieve", "judge")
    graph.add_conditional_edges("judge", route_after_judge,
                                {"retrieve": "retrieve", "generate": "generate"})
    graph.add_edge("generate", END)
    return graph.compile()


def main(question: str) -> None:
    agent = MultiHopAgent()
    result = agent.run(question)
    for step in result["trace"]:
        print("·", step)
    print("\n回答:", result["answer"]["answer"])


if __name__ == "__main__":
    import sys

    main(sys.argv[1] if len(sys.argv) > 1 else "示例多跳问题")
