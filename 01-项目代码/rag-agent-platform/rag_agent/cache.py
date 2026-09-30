"""答案缓存：精确匹配（零成本）+ 可选语义相似匹配。

精确匹配用 LRU，命中即为零成本；
语义缓存需要对 query 做 embedding（约 +50~150ms），换更高命中率，
所以默认阈值可调、也可关闭（similarity_threshold: 0）。
"""
from __future__ import annotations

from collections import OrderedDict


class AnswerCache:
    def __init__(self, cfg: dict, embedder=None):
        cc = cfg.get("cache", {})
        self.enable = cc.get("enable", True)
        self.size = cc.get("size", 256)
        self.threshold = cc.get("similarity_threshold", 0.0)
        self.embedder = embedder
        self._exact: OrderedDict[str, dict] = OrderedDict()
        self._semantic: list[tuple[object, dict]] = []
        self.hits = {"exact": 0, "semantic": 0, "miss": 0}

    @staticmethod
    def _key(query: str) -> str:
        return " ".join(query.strip().lower().split())

    def get(self, query: str) -> dict | None:
        if not self.enable:
            return None
        key = self._key(query)
        if key in self._exact:
            self.hits["exact"] += 1
            self._exact.move_to_end(key)
            return self._exact[key]

        if self.threshold > 0 and self.embedder is not None and self._semantic:
            import numpy as np

            vector = self.embedder.encode([query], show_progress=False)[0]
            best_score, best_payload = 0.0, None
            for vec, payload in self._semantic:
                score = float(np.dot(vector, vec))
                if score > best_score:
                    best_score, best_payload = score, payload
            if best_payload is not None and best_score >= self.threshold:
                self.hits["semantic"] += 1
                return best_payload

        self.hits["miss"] += 1
        return None

    def set(self, query: str, payload: dict) -> None:
        if not self.enable:
            return
        key = self._key(query)
        self._exact[key] = payload
        self._exact.move_to_end(key)
        while len(self._exact) > self.size:
            self._exact.popitem(last=False)

        if self.threshold > 0 and self.embedder is not None:
            vector = self.embedder.encode([query], show_progress=False)[0]
            self._semantic = [(v, p) for v, p in self._semantic if p is not payload]
            self._semantic.append((vector, payload))
            if len(self._semantic) > self.size:
                self._semantic.pop(0)

    def stats(self) -> dict:
        total = sum(self.hits.values())
        hit = self.hits["exact"] + self.hits["semantic"]
        return {
            **self.hits,
            "命中率": round(hit / total, 3) if total else 0.0,
            "缓存条数": len(self._exact),
        }
