"""精排：规则精排 + 模型精排（API）。

规则精排（零成本）：关键词重合度 + 来源权威性 + 长度合理性；
模型精排（效果好）：调用 bge-reranker-v2-m3 这类 cross-encoder 打分。

评测时可以切换 method 做对比，对比表随评测报告一起产出。
"""
from __future__ import annotations

from collections import Counter

from .build_index import tokenize


def _keyword_overlap(query_tokens: Counter, text: str) -> float:
    if not query_tokens:
        return 0.0
    doc_tokens = Counter(tokenize(text))
    hit = sum(min(count, doc_tokens.get(token, 0)) for token, count in query_tokens.items())
    return hit / sum(query_tokens.values())


def _length_score(text: str, low: int = 80, high: int = 900) -> float:
    length = len(text)
    if low <= length <= high:
        return 1.0
    if length < low:
        return length / low
    return max(0.5, high / length)


def rule_score(query: str, chunk: dict, rule_cfg: dict) -> float:
    query_tokens = Counter(tokenize(query))
    keyword = _keyword_overlap(query_tokens, chunk["text"])
    source = rule_cfg["source_weights"].get(chunk.get("source_type", ""), 0.8)
    length = _length_score(chunk["text"])
    return (
        rule_cfg["keyword_weight"] * keyword
        + rule_cfg["source_weight"] * source
        + rule_cfg["length_weight"] * length
    )


def rerank_rule(query: str, results: list[dict], cfg: dict, top_k: int) -> list[dict]:
    rule_cfg = cfg["rerank"]["rule"]
    # 先归一化检索分（RRF 分数值很小，直接和规则分相加没有意义）
    base_scores = [float(item.get("score", 0.0)) for item in results]
    base_max = max(base_scores) or 1.0
    w_retrieval = rule_cfg.get("retrieval_weight", 0.65)
    w_rule = rule_cfg.get("rule_weight", 0.35)

    scored = []
    for item in results:
        enriched = dict(item)
        rule = rule_score(query, item, rule_cfg)
        base = float(item.get("score", 0.0)) / base_max
        enriched["rule_score"] = rule
        # 融合：保留检索排序信息，规则只做修正，避免把正确结果挤下去
        enriched["rerank_score"] = w_retrieval * base + w_rule * rule
        scored.append(enriched)
    scored.sort(key=lambda x: x["rerank_score"], reverse=True)
    return scored[:top_k]


def rerank_api(query: str, results: list[dict], cfg: dict, top_k: int) -> list[dict]:
    """调用 OpenAI 风格之外的 rerank 接口（以 SiliconFlow 为例）。"""
    import os

    import requests

    api_cfg = cfg["rerank"]["api"]
    api_key = os.environ.get(api_cfg["api_key_env"])
    if not api_key:
        raise RuntimeError(f"未找到环境变量 {api_cfg['api_key_env']}，无法调用 rerank 接口")

    resp = requests.post(
        api_cfg["url"],
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": api_cfg["model"],
            "query": query,
            "documents": [r["text"] for r in results],
            "top_n": top_k,
        },
        timeout=30,
    )
    resp.raise_for_status()

    reranked: list[dict] = []
    for item in resp.json().get("results", []):
        enriched = dict(results[item["index"]])
        enriched["rerank_score"] = float(item.get("relevance_score", 0.0))
        reranked.append(enriched)
    return reranked[:top_k]


class Reranker:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.method = cfg["rerank"].get("method", "rule")
        self.top_k = cfg["rerank"].get("top_k", 5)

    def rerank(self, query: str, results: list[dict],
               top_k: int | None = None) -> list[dict]:
        k = top_k or self.top_k
        if not results or self.method == "none":
            return results[:k]
        if self.method == "api":
            return rerank_api(query, results, self.cfg, k)
        return rerank_rule(query, results, self.cfg, k)
