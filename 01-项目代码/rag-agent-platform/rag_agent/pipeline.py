"""端到端流水线：查询改写 -> 混合检索 -> 精排 -> 生成（含拒答与引用校验）。

用法：python -m rag_agent.pipeline "设备无法开机怎么办"
"""
from __future__ import annotations

import time
from typing import Iterator

from .cache import AnswerCache
from .config import load_config
from .generate import Generator, source_label
from .hybrid import HybridRetriever
from .llm import build_llm
from .rerank import Reranker
from .rewrite import QueryRewriter


class RagPipeline:
    def __init__(self, cfg: dict | None = None, llm=None, enable_cache: bool | None = None):
        self.cfg = cfg or load_config()
        self.retriever = HybridRetriever(self.cfg)
        self.llm = llm if llm is not None else build_llm(self.cfg)
        self.rewriter = QueryRewriter(self.cfg, llm=self.llm)
        self.reranker = Reranker(self.cfg)
        self.generator = Generator(self.cfg, self.llm)
        use_cache = self.cfg["cache"].get("enable", True) if enable_cache is None else enable_cache
        self.cache = AnswerCache(
            {**self.cfg, "cache": {**self.cfg["cache"], "enable": use_cache}},
            embedder=self.retriever.embedder,
        )

    # --- 检索 ---------------------------------------------------------
    def _multi_query_candidates(self, queries: list[str]) -> list[dict]:
        """多路查询各自做「向量+BM25 融合」，再跨查询做一次 RRF 合并。"""
        ranked_lists: list[list[tuple[int, float]]] = []
        dense_scores: dict[int, float] = {}
        for query in queries:
            dense = self.retriever.dense_search(query)
            for idx, score in dense:
                dense_scores[idx] = max(dense_scores.get(idx, -1.0), score)
            ranked_lists.append(
                self.retriever.rrf_fuse(
                    [dense, self.retriever.bm25_search(query)],
                    weights=[self.retriever.dense_weight, self.retriever.bm25_weight],
                )
            )
        merged = (
            self.retriever.rrf_fuse(ranked_lists)
            if len(ranked_lists) > 1
            else ranked_lists[0]
        )
        candidates = []
        for doc_idx, score in merged[: self.retriever.dense_top_k]:
            item = dict(self.retriever.chunks[doc_idx])
            item["score"] = score
            # 向量余弦相似度：用于置信度判断（RRF 分只反映排名，不能当阈值用）
            item["dense_score"] = dense_scores.get(doc_idx, 0.0)
            candidates.append(item)
        return candidates

    def retrieve(self, question: str) -> dict:
        """检索 + 精排，返回结果与各阶段耗时。"""
        timings: dict[str, float] = {}

        start = time.perf_counter()
        queries = self.rewriter.expand(question)
        timings["改写"] = (time.perf_counter() - start) * 1000

        start = time.perf_counter()
        candidates = self._multi_query_candidates(queries)
        timings["召回"] = (time.perf_counter() - start) * 1000

        start = time.perf_counter()
        results = self.reranker.rerank(queries[0], candidates)
        timings["精排"] = (time.perf_counter() - start) * 1000

        return {"question": question, "queries": queries, "results": results, "timings": timings}

    # --- 问答 ---------------------------------------------------------
    def answer(self, question: str, use_cache: bool = True) -> dict:
        if use_cache:
            cached = self.cache.get(question)
            if cached is not None:
                return {**cached, "cached": True}

        prepared = self.retrieve(question)
        start = time.perf_counter()
        generated = self.generator.answer(question, prepared["results"])
        timings = {**prepared["timings"], "生成": (time.perf_counter() - start) * 1000}

        payload = {
            **generated,
            "question": question,
            "queries": prepared["queries"],
            "contexts": prepared["results"],
            "confidence": self.generator.confidence(prepared["results"]),
            "timings": timings,
            "cached": False,
        }
        if use_cache and not payload["refused"]:
            self.cache.set(question, {k: v for k, v in payload.items() if k != "timings"})
        return payload

    def stream(self, question: str) -> Iterator[dict]:
        """流式产出事件：contexts -> token... -> done（供 SSE 使用）。"""
        prepared = self.retrieve(question)
        results = prepared["results"]
        yield {
            "type": "contexts",
            "question": question,
            "queries": prepared["queries"],
            "timings": prepared["timings"],
            "contexts": [
                {
                    "index": i,
                    "title": item.get("title", ""),
                    "source": source_label(item),
                    "score": item.get("score", 0.0),
                    "snippet": item["text"][:120],
                }
                for i, item in enumerate(results, start=1)
            ],
        }

        start = time.perf_counter()
        buffer: list[str] = []
        for token in self.generator.stream(question, results):
            buffer.append(token)
            yield {"type": "token", "content": token}

        from .generate import extract_citations

        text = "".join(buffer)
        valid, invalid = extract_citations(text, len(results))
        yield {
            "type": "done",
            "answer": text,
            "citations": valid,
            "invalid_citations": invalid,
            "generate_ms": (time.perf_counter() - start) * 1000,
        }


def main(question: str) -> None:
    pipeline = RagPipeline()
    result = pipeline.answer(question)
    print(f"问题: {result['question']}")
    print(f"改写: {result['queries'][:1]}")
    print(f"回答: {result['answer']}\n")
    print(f"引用: {result['citations']} 非法引用: {result['invalid_citations']}")
    print(f"各阶段耗时(ms): { {k: round(v) for k, v in result['timings'].items()} }")


if __name__ == "__main__":
    import sys

    main(sys.argv[1] if len(sys.argv) > 1 else "设备无法开机怎么办")
