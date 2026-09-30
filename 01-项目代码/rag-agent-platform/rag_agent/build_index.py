"""构建 FAISS 向量索引与 BM25 关键词索引。

用法：python -m rag_agent.build_index
"""
from __future__ import annotations

import json
import pickle

import faiss
import jieba
from rank_bm25 import BM25Okapi

from .config import ROOT, load_config, resolve
from .embedding import build_embedder
from .faiss_io import save_faiss_index

_JIEBA_READY = False


def _ensure_jieba() -> None:
    """把 jieba 词典缓存放到项目内目录。

    默认会写到系统临时目录，在受限环境（容器/沙箱/无临时目录）下会报错；
    指定项目内 .cache 目录后就稳定了。
    """
    global _JIEBA_READY
    if _JIEBA_READY:
        return
    cache_dir = ROOT / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    jieba.dt.tmp_dir = str(cache_dir)
    _JIEBA_READY = True


def load_chunks(path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def tokenize(text: str) -> list[str]:
    """中文分词。建议后续加载产品/型号自定义词典：jieba.load_userdict(...)"""
    _ensure_jieba()
    return [token for token in jieba.lcut(text) if token.strip()]


def build_index(cfg: dict | None = None) -> None:
    cfg = cfg or load_config()
    chunks = load_chunks(resolve(cfg, "paths.chunks_file"))
    if not chunks:
        raise SystemExit("没有切片数据，请先运行 python -m rag_agent.chunking")

    embedder = build_embedder(cfg)
    vectors = embedder.encode([c["embed_text"] for c in chunks], show_progress=True)

    index = faiss.IndexFlatIP(vectors.shape[1])  # 向量已归一化，内积即余弦相似度
    index.add(vectors)

    out_dir = resolve(cfg, "paths.index_dir")
    out_dir.mkdir(parents=True, exist_ok=True)
    save_faiss_index(index, out_dir / "dense.faiss")

    bm25 = BM25Okapi([tokenize(c["text"]) for c in chunks])
    with open(out_dir / "bm25.pkl", "wb") as f:
        pickle.dump({"bm25": bm25, "chunks": chunks}, f)

    print(f"索引已写入 {out_dir}")
    print(f"片段数: {len(chunks)}，向量维度: {vectors.shape[1]}")


if __name__ == "__main__":
    build_index()
