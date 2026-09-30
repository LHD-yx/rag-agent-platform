r"""FAISS 索引读写封装：绕开 Windows 中文路径打不开的问题。

背景（真实排障记录）：
    faiss.write_index / faiss.read_index 内部走的是 C++ 的 FileIOReader(const char*)，
    在 Windows 上按窄字符（ANSI）处理路径。项目路径里一旦出现中文，
    比如 D:\项目\rag-agent-platform，faiss 就会报：

        RuntimeError: Error in __cdecl faiss::FileIOReader::FileIOReader(const char *)
        ... could not open ...\data\index\dense.faiss for reading: No such file or directory

    但文件其实好好地在那儿——纯粹是路径编码问题，和索引本身无关。

做法：
    先用 Python 的文件接口（Windows 上走 Unicode API，中文路径没问题）把字节读出来，
    再用 faiss.serialize_index / deserialize_index 做转换。
    实测 1302 个向量 / 1024 维的索引往返无损。

这样即使把项目放在「D:\我的项目\」这种中文目录下也能正常跑。
"""
from __future__ import annotations

from pathlib import Path

import faiss
import numpy as np


def save_faiss_index(index, path) -> None:
    """把 FAISS 索引写到 path（路径可以含中文）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = faiss.serialize_index(index)
    with open(path, "wb") as f:
        f.write(data.tobytes())


def load_faiss_index(path):
    """从 path 读回 FAISS 索引（路径可以含中文）。"""
    path = Path(path)
    with open(path, "rb") as f:
        raw = f.read()
    # frombuffer 拿到的是只读视图，deserialize 需要可写数组，所以 copy 一份
    return faiss.deserialize_index(np.frombuffer(raw, dtype="uint8").copy())