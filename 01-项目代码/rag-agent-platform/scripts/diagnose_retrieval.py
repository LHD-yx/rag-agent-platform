"""诊断检索失败案例：命中的是正确答案、同族文档、还是完全跑偏？

用途：评测表告诉你"多少分"，这个脚本告诉你"错在哪"，
     便于判断该改切片、改召回还是改问题质量。

与 `evaluate.py` 共用同一条检索链路（EvalRunner.ranked_chunks），
所以这里的分类结果和消融表里的分数是同一套配置算出来的——
早期版本这里用的是"未加权 RRF + BM25 top-20"，和线上配置不一致，
诊断出来的比例不能代表线上表现，已废弃。

用法：
    python scripts/diagnose_retrieval.py                       # 默认生产链路
    python scripts/diagnose_retrieval.py --mode hybrid          # 只看混合检索
    python scripts/diagnose_retrieval.py --mode dense --show 10
输出：终端打印 + data/results/diagnose_retrieval.md
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rag_agent.config import load_config, resolve  # noqa: E402
from rag_agent.evaluate import EvalRunner, load_eval_set  # noqa: E402

# 生产链路：归一化 -> 双路召回 -> RRF 融合 -> 规则精排
DEFAULT_MODE = "hybrid_rewrite_rerank"

MODE_LABELS = {
    "dense": "纯向量",
    "bm25": "纯 BM25",
    "hybrid": "向量 + BM25 (RRF)",
    "hybrid_rewrite": "混合 + 查询改写",
    "hybrid_rewrite_rerank": "混合 + 改写 + 精排（生产链路）",
}


def split_title(title: str) -> tuple[str, str]:
    """把文档标题拆成（型号, 文档类型）。

    语料里的标题形如 "X3-55 用户手册"、"P1-Air 安装与调试指南"，
    第一段是型号，剩下的是文档类型。拆开之后才能区分两种混淆：
    「同一个型号找错了文档」和「找对了文档类型但型号错了」——
    这两种的修法完全不同（前者要调切片/片段定位，后者要加型号过滤）。
    """
    parts = str(title).split()
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    return str(title), ""


def main() -> None:
    parser = argparse.ArgumentParser(description="诊断检索失败案例")
    parser.add_argument("--mode", default=DEFAULT_MODE,
                        choices=sorted(MODE_LABELS), help="检索模式，默认生产链路")
    parser.add_argument("--show", type=int, default=8, help="打印几个失败案例")
    args = parser.parse_args()

    cfg = load_config()
    eval_set = load_eval_set(resolve(cfg, "paths.eval_file"))
    runner = EvalRunner(cfg)
    chunk_by_id = {c["chunk_id"]: c for c in runner.retriever.chunks}
    title_of_doc = {c["doc_id"]: c["title"] for c in runner.retriever.chunks}

    stats = Counter()
    failures: list[tuple[str, str, str]] = []

    for item in eval_set:
        if item.get("unanswerable"):
            continue
        query = item["query"]
        gold_chunks = set(item.get("gold_chunk_ids") or [])
        gold_docs = set(item.get("gold_doc_ids") or [])

        ranked = runner.ranked_chunks(query, args.mode)
        top = ranked[0] if ranked else None
        if top is None:
            stats["无结果"] += 1
            continue

        if top["chunk_id"] in gold_chunks or top["doc_id"] in gold_docs:
            stats["命中正确文档"] += 1
            continue

        gold_title = next((title_of_doc.get(d, "?") for d in gold_docs), "?")
        got_model, got_type = split_title(top.get("title", ""))
        gold_model, gold_type = split_title(gold_title)

        if gold_model and got_model == gold_model:
            kind = "型号相同、文档不同"
        elif gold_type and got_type == gold_type:
            kind = "文档类型相同、型号不同"
        else:
            kind = "完全跑偏"
        stats[kind] += 1
        failures.append((kind, query, f"{top.get('title', '?')} > {top.get('section_path', '')[:26]}"))

    total = sum(stats.values()) or 1
    label = MODE_LABELS.get(args.mode, args.mode)
    wrong = total - stats["命中正确文档"]

    failure_stats = [(n, c) for n, c in stats.most_common() if n != "命中正确文档"]
    lines = [
        "# 检索失败归因诊断",
        "",
        f"- 检索模式：`{args.mode}`（{label}）",
        f"- 可回答题目：{total} 条，其中 top-1 命中 {stats['命中正确文档']} 条、"
        f"未命中 {wrong} 条",
        "- 口径与 `ablation.md` 一致（同一个 `EvalRunner.ranked_chunks`）",
        "",
        "未命中的部分再按原因拆开（分母是全部可回答题目 / 未命中题目）：",
        "",
        "| 归因 | 条数 | 占全部题目 | 占未命中题目 |",
        "|---|---|---|---|",
    ]
    for name, count in failure_stats:
        lines.append(
            f"| {name} | {count} | {count / total:.1%} | "
            f"{(count / wrong if wrong else 0):.1%} |"
        )

    if failures:
        lines += ["", f"## 失败案例（共 {len(failures)} 条，列出前 {min(args.show, len(failures))} 条）", ""]
        for kind, query, got in failures[: args.show]:
            lines.append(f"- **[{kind}]** {query}")
            lines.append(f"  - 实际命中：{got}")

    out = ROOT / "data/results/diagnose_retrieval.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")

    print(f"诊断配置: {args.mode}（{label}）　可回答题目: {total} 条\n")
    for name, count in stats.most_common():
        print(f"  {name}: {count} ({count / total:.1%})")
    if failures:
        print(f"\n失败案例示例（共 {len(failures)} 条）:")
        for kind, query, got in failures[: args.show]:
            print(f"  [{kind}] {query}")
            print(f"        实际命中 -> {got}")
    print(f"\n已写入: {out}")


if __name__ == "__main__":
    main()
