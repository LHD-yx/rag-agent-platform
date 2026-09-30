"""检索评测：hit@1 / hit@3 / MRR / 平均延迟 + 拒答检出率，输出消融实验表。

对比 5 档配置，逐级验证每个模块的增益：
    纯向量 -> 纯 BM25 -> 混合(RRF) -> +查询改写 -> +精排

评测集里标记 unanswerable 的条目不计入 hit 指标，而是单独统计
"低置信检出率"——即这些答不了的问题有没有被正确识别出来（越低说明越容易编造）。

用法：
    1) 准备 data/eval/eval_set.jsonl（格式见 docs/评测集构建指南.md）
    2) python -m rag_agent.evaluate     （或 python main.py eval）
结果写入 data/results/ablation.md
"""
from __future__ import annotations

import json
import time

from .config import load_config, resolve
from .hybrid import HybridRetriever
from .llm import build_llm
from .rerank import Reranker
from .rewrite import QueryRewriter

EVAL_TOP_K = 20  # 评测候选范围，需 >= 3

# 名称 -> 检索模式
CONFIGS: dict[str, str] = {
    "纯向量": "dense",
    "纯 BM25": "bm25",
    "向量 + BM25 (RRF)": "hybrid",
    "混合 + 查询改写": "hybrid_rewrite",
    "混合 + 改写 + 精排": "hybrid_rewrite_rerank",
}


def load_eval_set(path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class EvalRunner:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.retriever = HybridRetriever(cfg)
        # 只有开启 HyDE 才需要 LLM；否则整个评测不消耗任何 token
        llm = build_llm(cfg) if cfg["rewrite"].get("enable_hyde") else None
        self.rewriter = QueryRewriter(cfg, llm=llm)
        self.reranker = Reranker(cfg)

    def _hybrid_ranked(self, query: str, top_k: int = EVAL_TOP_K):
        """返回 (RRF 排序结果, 向量相似度表)。"""
        r = self.retriever
        dense = r.dense_search(query, top_k)
        fused = r.rrf_fuse(
            [dense, r.bm25_search(query, top_k)],
            weights=[r.dense_weight, r.bm25_weight],
        )
        return fused, {i: s for i, s in dense}

    def _multi_query_candidates(self, queries: list[str]) -> list[dict]:
        ranked_lists: list[list[tuple[int, float]]] = []
        dense_scores: dict[int, float] = {}
        for query in queries:
            ranked, dense_map = self._hybrid_ranked(query)
            ranked_lists.append(ranked)
            for idx, score in dense_map.items():
                dense_scores[idx] = max(dense_scores.get(idx, -1.0), score)
        merged = (
            self.retriever.rrf_fuse(ranked_lists)
            if len(ranked_lists) > 1
            else ranked_lists[0]
        )
        candidates = []
        for idx, score in merged[:EVAL_TOP_K]:
            item = dict(self.retriever.chunks[idx])
            item["score"] = score
            item["dense_score"] = dense_scores.get(idx, 0.0)
            candidates.append(item)
        return candidates

    def ranked_chunks(self, query: str, mode: str) -> list[dict]:
        """返回排序后的候选片段，带 score 与 dense_score（用于置信度判断）。"""
        r = self.retriever
        if mode == "dense":
            return [
                {**r.chunks[i], "score": score, "dense_score": score}
                for i, score in r.dense_search(query, EVAL_TOP_K)
            ]
        if mode == "bm25":
            # 纯 BM25 没有向量相似度，置信度只能用 BM25 分数（量纲不同，仅供参考）
            return [
                {**r.chunks[i], "score": score}
                for i, score in r.bm25_search(query, EVAL_TOP_K)
            ]
        if mode == "hybrid":
            fused, dense_map = self._hybrid_ranked(query)
            return [
                {**r.chunks[i], "score": score, "dense_score": dense_map.get(i, 0.0)}
                for i, score in fused
            ]

        candidates = self._multi_query_candidates(self.rewriter.expand(query))
        if mode == "hybrid_rewrite_rerank":
            candidates = self.reranker.rerank(
                self.rewriter.normalize(query), candidates, top_k=EVAL_TOP_K
            )
        return candidates


def first_hit_rank(chunks: list[dict], gold_chunks: set[str], gold_docs: set[str]) -> int | None:
    for rank, chunk in enumerate(chunks, start=1):
        if chunk["chunk_id"] in gold_chunks or chunk["doc_id"] in gold_docs:
            return rank
    return None


def evaluate_config(runner: EvalRunner, eval_set: list[dict], name: str,
                    mode: str, min_score: float, metric: str = "dense_score") -> dict:
    ranks: list[int | None] = []
    latencies: list[float] = []
    detected = 0
    unanswerable_count = 0

    for item in eval_set:
        start = time.perf_counter()
        chunks = runner.ranked_chunks(item["query"], mode)
        latencies.append((time.perf_counter() - start) * 1000)
        top_score = chunks[0].get(metric, chunks[0].get("score", 0.0)) if chunks else 0.0

        if item.get("unanswerable"):
            unanswerable_count += 1
            if top_score < min_score:
                detected += 1
            continue

        gold_chunks = set(item.get("gold_chunk_ids") or [])
        gold_docs = set(item.get("gold_doc_ids") or [])
        ranks.append(first_hit_rank(chunks, gold_chunks, gold_docs))

    total = len(ranks) or 1
    return {
        "config": name,
        "hit@1": sum(1 for r in ranks if r == 1) / total,
        "hit@3": sum(1 for r in ranks if r is not None and r <= 3) / total,
        "MRR": sum((1.0 / r) if r else 0.0 for r in ranks) / total,
        "平均延迟(ms)": sum(latencies) / max(len(latencies), 1),
        "拒答检出率": detected / unanswerable_count if unanswerable_count else None,
        "拒答样本数": unanswerable_count,
        "可回答样本数": len(ranks),
    }


def to_markdown(rows: list[dict], note: str = "") -> str:
    header = "| 配置 | hit@1 | hit@3 | MRR | 平均延迟(ms) |\n|---|---|---|---|---|\n"
    body = "".join(
        f"| {r['config']} | {r['hit@1']:.3f} | {r['hit@3']:.3f} | "
        f"{r['MRR']:.3f} | {r['平均延迟(ms)']:.0f} |\n"
        for r in rows
    )
    table = (note + "\n\n" if note else "") + header + body

    if any(r["拒答检出率"] is not None for r in rows):
        table += (
            "\n**拒答类低置信检出率**（越高越好，说明答不了的问题没有被硬答）\n\n"
            "| 配置 | 检出率 | 拒答样本数 |\n|---|---|---|\n"
        )
        for r in rows:
            rate = r["拒答检出率"]
            value = f"{rate:.1%}" if rate is not None else "-"
            table += f"| {r['config']} | {value} | {r['拒答样本数']} |\n"
    return table


def main() -> None:
    cfg = load_config()
    eval_set = load_eval_set(resolve(cfg, "paths.eval_file"))
    runner = EvalRunner(cfg)
    min_score = cfg["generation"].get("min_score", 0.0)
    metric = cfg["generation"].get("confidence_metric", "dense_score")

    rows = [
        evaluate_config(runner, eval_set, name, mode, min_score, metric)
        for name, mode in CONFIGS.items()
    ]

    hyde = "开启" if cfg["rewrite"].get("enable_hyde") else "关闭"
    note = (
        f"评测条数: {len(eval_set)}"
        f"（可回答 {rows[0]['可回答样本数']} / 拒答类 {rows[0]['拒答样本数']}）\n"
        f"切片: chunk_size={cfg['chunking']['max_chars']}, overlap={cfg['chunking']['overlap']}\n"
        f"召回: dense_top_k={cfg['retrieval']['dense_top_k']}, "
        f"bm25_top_k={cfg['retrieval']['bm25_top_k']}, rrf_k={cfg['retrieval']['rrf_k']}\n"
        f"HyDE: {hyde}　精排方式: {cfg['rerank']['method']}\n"
        f"置信度指标: {metric}，拒答阈值: {min_score}\n"
        f"延迟口径: 评测循环内单条查询的平均检索耗时（含 embedding 网络往返，"
        f"不含冷启动与 LLM 生成）；端到端（含冷启动）看 `python main.py ask` 的 timings_ms\n"
        f"拒答口径: 各档配置自身 top-1 片段的 {metric} 与阈值比较"
        f"（纯 BM25 档没有向量相似度，只能用 BM25 分数近似，仅作参考）\n"
        f"最后一行「混合 + 改写 + 精排」= 生产链路，与 "
        f"scripts/calibrate_threshold.py 同口径"
    )
    table = to_markdown(rows, note)

    result_dir = resolve(cfg, "paths.result_dir")
    result_dir.mkdir(parents=True, exist_ok=True)
    out_path = result_dir / "ablation.md"
    out_path.write_text(table, encoding="utf-8")

    print(table)
    print(f"已写入: {out_path}")


if __name__ == "__main__":
    main()
