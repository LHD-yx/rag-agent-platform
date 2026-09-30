"""双路召回（向量 + BM25）与 RRF 融合。

用法：python -m rag_agent.hybrid "你的问题"
"""
from __future__ import annotations

import pickle
import time

import numpy as np

from .build_index import tokenize
from .config import load_config, resolve
from .embedding import build_embedder
from .faiss_io import load_faiss_index


class HybridRetriever:
    """FAISS 向量召回 + BM25 关键词召回，RRF 融合排序。"""

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or load_config()
        rc = self.cfg["retrieval"]
        self.dense_top_k = rc["dense_top_k"]
        self.bm25_top_k = rc["bm25_top_k"]
        self.rrf_k = rc["rrf_k"]
        self.dense_weight = rc.get("dense_weight", 1.0)
        self.bm25_weight = rc.get("bm25_weight", 1.0)
        self.final_top_k = rc["final_top_k"]

        index_dir = resolve(self.cfg, "paths.index_dir")
        self.index = load_faiss_index(index_dir / "dense.faiss")
        with open(index_dir / "bm25.pkl", "rb") as f:
            payload = pickle.load(f)
        self.bm25 = payload["bm25"]
        self.chunks: list[dict] = payload["chunks"]
        self.embedder = build_embedder(self.cfg)

    # --- 单路召回 -----------------------------------------------------
    def dense_search(self, query: str, top_k: int | None = None) -> list[tuple[int, float]]:
        qv = self.embedder.encode([query], show_progress=False).astype("float32")
        scores, indices = self.index.search(qv, top_k or self.dense_top_k)
        return [(int(i), float(s)) for i, s in zip(indices[0], scores[0]) if i >= 0]

    def bm25_search(self, query: str, top_k: int | None = None) -> list[tuple[int, float]]:
        scores = self.bm25.get_scores(tokenize(query))
        order = np.argsort(scores)[::-1][: top_k or self.bm25_top_k]
        return [(int(i), float(scores[i])) for i in order]

    # --- 融合 ---------------------------------------------------------
    def rrf_fuse(self, ranked_lists: list[list[tuple[int, float]]],
                 weights: list[float] | None = None) -> list[tuple[int, float]]:
        """Reciprocal Rank Fusion：只用排名，避免两路分数量纲不同。

        score = sum(w / (k + rank))，rank 从 1 开始。
        weights 用于给不同召回路径加权——等权融合会稀释强信号。
        """
        fused: dict[int, float] = {}
        for i, ranked in enumerate(ranked_lists):
            weight = 1.0 if weights is None else weights[i]
            for rank, (doc_idx, _score) in enumerate(ranked, start=1):
                fused[doc_idx] = fused.get(doc_idx, 0.0) + weight / (self.rrf_k + rank)
        return sorted(fused.items(), key=lambda kv: kv[1], reverse=True)

    def retrieve(self, query: str, top_k: int | None = None) -> list[dict]:
        fused = self.rrf_fuse(
            [self.dense_search(query), self.bm25_search(query)],
            weights=[self.dense_weight, self.bm25_weight],
        )
        results: list[dict] = []
        for doc_idx, score in fused[: top_k or self.final_top_k]:
            item = dict(self.chunks[doc_idx])
            item["score"] = score
            results.append(item)
        return results


def main(query: str, top_k: int = 5) -> None:
    retriever = HybridRetriever()
    start = time.perf_counter()
    results = retriever.retrieve(query, top_k=top_k)
    elapsed = (time.perf_counter() - start) * 1000

    for i, item in enumerate(results, start=1):
        snippet = item["text"][:120].replace("\n", " ")
        print(f"[{i}] score={item['score']:.4f} doc={item['doc_id']} "
              f"section={item['section_path']}\n    {snippet}...")
    print(f"\n检索耗时: {elapsed:.0f} ms")


if __name__ == "__main__":
    import sys

    question = sys.argv[1] if len(sys.argv) > 1 else "示例问题"
    main(question)
