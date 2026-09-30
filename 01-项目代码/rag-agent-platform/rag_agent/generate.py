"""生成链路：提示模板 + 引用约束 + 低置信拒答 + 引用校验。"""
from __future__ import annotations

import re
from typing import Iterator

SYSTEM_PROMPT = """你是一个严谨的企业知识库问答助手，必须遵守以下规则：
1. 只依据【参考资料】回答问题，不要使用参考资料之外的信息，禁止编造；
2. 每个结论后面标注来源编号，例如 [1][2]；
3. 如果参考资料不足以回答，明确说明缺少什么信息，并提示用户补充产品型号、故障现象或文档名称；
4. 回答简洁、分点，优先给出可执行的步骤。"""

CITATION_RE = re.compile(r"\[(\d+)\]")


def source_label(item: dict) -> str:
    """生成来源标签：section_path 已含文档名时不重复拼接。"""
    title = item.get("title", "")
    section = item.get("section_path", "") or ""
    if not section:
        return title
    return section if section.startswith(title) else f"{title} > {section}"


def build_context_block(results: list[dict]) -> str:
    blocks = []
    for idx, item in enumerate(results, start=1):
        blocks.append(f"[{idx}] 来源：{source_label(item)}\n{item['text']}")
    return "\n\n".join(blocks)


def extract_citations(answer: str, max_index: int) -> tuple[list[int], list[int]]:
    """返回 (有效引用编号, 非法引用编号)。"""
    cited = [int(m) for m in CITATION_RE.findall(answer)]
    valid = sorted({c for c in cited if 1 <= c <= max_index})
    invalid = sorted({c for c in cited if not (1 <= c <= max_index)})
    return valid, invalid


class Generator:
    def __init__(self, cfg: dict, llm):
        self.cfg = cfg
        self.llm = llm
        gc = cfg["generation"]
        # 置信度指标：dense_score（向量余弦）| rerank_score | score（RRF 融合分）
        self.metric = gc.get("confidence_metric", "dense_score")
        self.min_score = gc.get("min_score", 0.0)
        self.max_contexts = gc.get("max_contexts", 5)
        self.refuse_text = gc.get("refuse_text", "现有资料不足，请补充信息。")

    def confidence(self, results: list[dict]) -> float:
        """用可解释的相似度作为置信度，而不是只看排名的 RRF 分。"""
        if not results:
            return 0.0
        top = results[0]
        return float(top.get(self.metric, top.get("score", 0.0)))

    def is_low_confidence(self, results: list[dict]) -> bool:
        """检索结果为空或置信度低于阈值 -> 低置信，直接拒答。"""
        if not results:
            return True
        return self.confidence(results) < self.min_score

    def _messages(self, question: str, results: list[dict]) -> list[dict]:
        contexts = build_context_block(results[: self.max_contexts])
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"【参考资料】\n{contexts}\n\n【问题】\n{question}\n\n"
                           "请基于参考资料回答，并标注来源编号。",
            },
        ]

    def answer(self, question: str, results: list[dict]) -> dict:
        if self.is_low_confidence(results):
            return {
                "answer": self.refuse_text,
                "refused": True,
                "citations": [],
                "invalid_citations": [],
            }
        text = self.llm.chat(self._messages(question, results))
        valid, invalid = extract_citations(text, len(results[: self.max_contexts]))
        return {
            "answer": text,
            "refused": False,
            "citations": valid,
            "invalid_citations": invalid,
        }

    def stream(self, question: str, results: list[dict]) -> Iterator[str]:
        if self.is_low_confidence(results):
            yield self.refuse_text
            return
        yield from self.llm.stream(self._messages(question, results))
