"""切片段数对照：证明 `min_chars` 这一个参数带来的片段变化。

背景：素材里写「`min_chars` 30 → 12（短章节被整段丢弃）｜1180 片段 → 1302 片段」。
这个数字不需要调用 embedding 接口就能复现——切片是纯本地过程，本脚本
用同一个语料分别按 min_chars=30 和当前配置跑一遍，把结果写进
data/results/chunking_delta.md。

用法：python scripts/chunking_delta.py
输出：data/results/chunking_delta.md
"""
from __future__ import annotations

import contextlib
import copy
import io
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rag_agent.chunking import build_chunks  # noqa: E402
from rag_agent.config import load_config  # noqa: E402

TMP_DIR = ROOT / "data/results/.tmp_chunking"


def count_chunks(cfg: dict, min_chars: int) -> int:
    variant = copy.deepcopy(cfg)
    variant["chunking"]["min_chars"] = min_chars
    # 写到临时目录，绝不覆盖 data/chunks/chunks.jsonl 里的正式切片
    variant["paths"]["chunks_file"] = f"data/results/.tmp_chunking/chunks_min{min_chars}.jsonl"
    with contextlib.redirect_stdout(io.StringIO()):
        chunks = build_chunks(variant)
    return len(chunks)


def main() -> None:
    cfg = load_config()
    current = cfg["chunking"]["min_chars"]
    assert current == 12, f"当前 min_chars={current}，与文档里写的 12 不一致，请先确认"

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    try:
        old_count = count_chunks(cfg, 30)
        new_count = count_chunks(cfg, current)
    finally:
        shutil.rmtree(TMP_DIR, ignore_errors=True)

    lines = [
        "# 切片参数对照表（min_chars）",
        "",
        "同一份语料、同一套解析与切片逻辑，只改 `min_chars` 一个参数。",
        "",
        "| min_chars | 片段总数 | 说明 |",
        "|---|---|---|",
        f"| 30 | {old_count} | 改前：\"现象描述\"\"可能原因\"这类一两行的短章节被整段丢弃 |",
        f"| {current} | {new_count} | 改后：短章节保留，正好是用户提问的答案所在 |",
        f"| **差值** | **{new_count - old_count:+d}** | — |",
        "",
        "复现命令：`python scripts/chunking_delta.py`（纯本地过程，不消耗接口额度）",
        "",
        "> 为什么这个参数重要：故障类问题的答案经常就藏在一两行的短章节里"
        "（例如\"彩色噪点/间歇黑屏\"），阈值设成 30 会把它们直接丢掉，"
        "表现为\"这类问题怎么都检索不到\"，很难从现象反推到切片参数。",
    ]

    out = ROOT / "data/results/chunking_delta.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"min_chars=30 -> {old_count} 片段")
    print(f"min_chars={current} -> {new_count} 片段")
    print(f"已写入: {out}")


if __name__ == "__main__":
    main()
