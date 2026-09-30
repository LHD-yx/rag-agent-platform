"""Embedding 后端：API（默认，CPU 友好）或本地模型。

没有 GPU 时推荐 API：SiliconFlow 的 BAAI/bge-m3 有免费额度，
接口与 OpenAI embeddings 兼容；换 base_url + 模型名即可切到
阿里云百炼、智谱等其它服务。
"""
from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np


def normalize(arr: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return arr / norms


class ApiEmbedder:
    """OpenAI 兼容的 embeddings 接口。"""

    def __init__(self, model: str, base_url: str, api_key_env: str, batch_size: int = 32):
        import os

        from openai import OpenAI

        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(
                f"未找到环境变量 {api_key_env}。请先设置 API Key，"
                "或把 configs/config.yaml 里的 provider 改成 local。"
            )
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.batch_size = batch_size

    def encode(self, texts: Sequence[str], batch_size: int | None = None,
               show_progress: bool = False) -> np.ndarray:
        texts = list(texts)
        batch = batch_size or self.batch_size
        vectors: list[list[float]] = []
        iterator: Iterable[int] = range(0, len(texts), batch)
        if show_progress:
            from tqdm import tqdm

            iterator = tqdm(iterator, desc="embedding")
        for start in iterator:
            chunk = texts[start:start + batch]
            resp = self.client.embeddings.create(model=self.model, input=chunk)
            vectors.extend(item.embedding for item in resp.data)
        return normalize(np.asarray(vectors, dtype="float32"))


class LocalEmbedder:
    """本地 sentence-transformers（离线可用，CPU 较慢）。"""

    def __init__(self, model: str, batch_size: int = 8, device: str = "cpu"):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model, device=device)
        self.batch_size = batch_size

    def encode(self, texts: Sequence[str], batch_size: int | None = None,
               show_progress: bool = False) -> np.ndarray:
        arr = self.model.encode(
            list(texts),
            batch_size=batch_size or self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=show_progress,
        )
        return np.asarray(arr, dtype="float32")


def build_embedder(cfg: dict):
    """按配置创建 embedding 后端。"""
    ec = cfg["embedding"]
    if ec.get("provider", "api") == "local":
        return LocalEmbedder(model=ec["model"], batch_size=ec.get("batch_size", 8))
    return ApiEmbedder(
        model=ec["model"],
        base_url=ec["base_url"],
        api_key_env=ec["api_key_env"],
        batch_size=ec.get("batch_size", 32),
    )
