"""环境自检：一条命令告诉你现在卡在哪、下一步该做什么。

用法：
    python main.py doctor             # 完整自检（含一次真实的 embedding 调用）
    python main.py doctor --skip-api  # 不联网，只检查本地环境与数据
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

from .config import ROOT, load_config, resolve

REQUIRED_PACKAGES = {
    "yaml": "pyyaml",
    "numpy": "numpy",
    "faiss": "faiss-cpu",
    "rank_bm25": "rank-bm25",
    "jieba": "jieba",
    "fitz": "pymupdf",
    "docx": "python-docx",
    "openai": "openai",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
}


def _line(ok: bool | None, text: str) -> None:
    marker = "OK  " if ok else ("!!  " if ok is None else "X   ")
    print(f"[{marker}] {text}")


def check_python() -> bool:
    version = sys.version_info
    ok = version >= (3, 10)
    _line(ok, f"Python 版本 {version.major}.{version.minor}.{version.micro}"
              + ("" if ok else "  -> 需要 3.10 及以上，请升级 Python"))
    return ok


def check_packages() -> bool:
    missing = []
    for module, package in REQUIRED_PACKAGES.items():
        if importlib.util.find_spec(module) is None:
            missing.append(package)
    if missing:
        _line(False, "缺少依赖: " + ", ".join(missing))
        print("        解决: pip install -r requirements.txt")
        return False
    _line(True, f"依赖齐全（检查了 {len(REQUIRED_PACKAGES)} 个包）")
    return True


def check_api(cfg: dict, skip_api: bool) -> bool:
    env_name = cfg["embedding"]["api_key_env"]
    env_file = ROOT / ".env"
    has_env_file = env_file.exists()
    has_key = bool(os.environ.get(env_name))

    if not has_key:
        _line(False, f"未读到 API Key（环境变量 {env_name} 为空）")
        print("        检查: 项目根目录是否有 .env 文件（" +
              ("已存在" if has_env_file else "不存在") + "）")
        print("        解决: 复制 .env.example 为 .env，填入 SILICONFLOW_API_KEY=sk-xxx")
        return False
    _line(True, f"API Key 已配置（{env_name}）")

    if skip_api:
        _line(None, "已跳过联网测试（--skip-api）")
        return True

    try:
        from .embedding import build_embedder

        vector = build_embedder(cfg).encode(["连接测试"], show_progress=False)
        _line(True, f"embedding 接口连通，向量维度 {vector.shape[1]}")
        return True
    except Exception as exc:  # noqa: BLE001
        _line(False, f"embedding 调用失败: {type(exc).__name__}: {exc}")
        print("        若提示 401/403：Key 错误或未完成实名认证")
        print("        若提示超时：检查网络或代理")
        print("        若提示模型不存在：核对 configs/config.yaml 里的 embedding.model")
        return False


def check_data(cfg: dict) -> bool:
    raw_dir = resolve(cfg, "paths.raw_dir")
    files = [p for p in raw_dir.rglob("*") if p.suffix.lower() in
             {".pdf", ".docx", ".doc", ".md", ".markdown", ".txt"}]
    if not files:
        _line(False, f"data/raw 里没有文档（目录: {raw_dir}）")
        print("        解决: 放 20~50 篇 PDF / Word / Markdown 进去")
        return False
    _line(True, f"原始文档 {len(files)} 篇")

    chunks_path = resolve(cfg, "paths.chunks_file")
    if not chunks_path.exists():
        _line(False, "还没有切片文件  -> 下一步运行: python main.py chunk")
        return False
    count = sum(1 for line in open(chunks_path, encoding="utf-8") if line.strip())
    _line(True, f"切片文件已存在，共 {count} 个片段")

    index_dir = resolve(cfg, "paths.index_dir")
    if not (index_dir / "dense.faiss").exists() or not (index_dir / "bm25.pkl").exists():
        _line(False, "还没有索引文件  -> 下一步运行: python main.py index")
        return False
    _line(True, "向量索引与 BM25 索引已就绪")
    return True


def check_eval(cfg: dict) -> bool:
    eval_path = resolve(cfg, "paths.eval_file")
    if not eval_path.exists():
        _line(None, "还没有评测集  -> 运行: python scripts/gen_eval_candidates.py --limit 120")
        return False
    count = sum(1 for line in open(eval_path, encoding="utf-8") if line.strip())
    ok = count >= 100
    _line(ok, f"评测集 {count} 条" + ("" if ok else "  -> 建议补到 100 条以上"))
    return ok


def main(skip_api: bool = False) -> None:
    print("=" * 56)
    print("RAG 项目环境自检")
    print("=" * 56)

    cfg = load_config()
    print(f"项目目录: {ROOT}\n")

    results = [
        ("Python", check_python()),
        ("依赖", check_packages()),
        ("API", check_api(cfg, skip_api)),
        ("数据", check_data(cfg)),
    ]
    check_eval(cfg)

    print("\n" + "=" * 56)
    if all(ok for _, ok in results):
        print("自检通过。可以运行: python main.py ask \"你的问题\"")
    else:
        print("自检未全部通过，按上面每个 [X] 后面的提示处理后重新运行本命令。")
    print("=" * 56)


if __name__ == "__main__":
    main()
