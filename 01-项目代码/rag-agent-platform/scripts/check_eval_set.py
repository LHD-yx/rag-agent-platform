"""校验评测集：格式、gold 有效性、重复、分布。

用法：python scripts/check_eval_set.py [--file data/eval/eval_set.jsonl]
有任何错误时返回码为 1，方便接进 CI。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rag_agent.config import load_config, resolve  # noqa: E402

MIN_ITEMS = 100


def load_jsonl(path: Path) -> tuple[list[dict], list[str]]:
    items, errors = [], []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError as exc:
            errors.append(f"第 {lineno} 行 JSON 解析失败: {exc}")
    return items, errors


def main() -> None:
    parser = argparse.ArgumentParser(description="校验评测集")
    parser.add_argument("--file", default="data/eval/eval_set.jsonl")
    args = parser.parse_args()

    cfg = load_config()
    path = ROOT / args.file
    if not path.exists():
        raise SystemExit(f"评测集不存在: {path}")

    items, errors = load_jsonl(path)
    warnings: list[str] = []

    # 切片表：用于校验 gold 是否真实存在
    chunk_ids: set[str] = set()
    doc_ids: set[str] = set()
    chunks_path = resolve(cfg, "paths.chunks_file")
    if chunks_path.exists():
        with open(chunks_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    chunk = json.loads(line)
                    chunk_ids.add(chunk["chunk_id"])
                    doc_ids.add(chunk["doc_id"])
    else:
        warnings.append("未找到切片文件，跳过 gold 有效性校验（先跑 python main.py chunk）")

    seen_queries: dict[str, int] = {}
    categories: Counter[str] = Counter()
    gold_doc_counter: Counter[str] = Counter()
    unanswerable = 0
    multi_hop = 0

    for idx, item in enumerate(items, start=1):
        query = (item.get("query") or "").strip()
        if not query:
            errors.append(f"第 {idx} 条: 缺少 query")
            continue
        if len(query) < 4:
            warnings.append(f"第 {idx} 条: 问题过短（{len(query)} 字）")
        if len(query) > 60:
            warnings.append(f"第 {idx} 条: 问题过长（{len(query)} 字），建议拆分")

        normalized = "".join(query.lower().split())
        if normalized in seen_queries:
            errors.append(f"第 {idx} 条: 与第 {seen_queries[normalized]} 条重复")
        else:
            seen_queries[normalized] = idx

        categories[item.get("category", "未分类")] += 1
        if item.get("multi_hop"):
            multi_hop += 1
        if item.get("unanswerable"):
            unanswerable += 1
            if item.get("gold_chunk_ids") or item.get("gold_doc_ids"):
                warnings.append(f"第 {idx} 条: 标记为拒答类却标了 gold")
            continue

        gold_chunks = item.get("gold_chunk_ids") or []
        gold_docs = item.get("gold_doc_ids") or []
        if not gold_chunks and not gold_docs:
            errors.append(f"第 {idx} 条: 既没有 gold_chunk_ids 也没有 gold_doc_ids")
        if chunk_ids:
            for cid in gold_chunks:
                if cid not in chunk_ids:
                    errors.append(f"第 {idx} 条: gold_chunk_id「{cid}」在切片中不存在")
            for did in gold_docs:
                if did not in doc_ids:
                    errors.append(f"第 {idx} 条: gold_doc_id「{did}」在切片中不存在")
        for did in gold_docs or [c.split("-")[0] for c in gold_chunks]:
            gold_doc_counter[did] += 1

    print(f"评测集: {path}")
    print(f"总条数: {len(items)}  (可回答 {len(items) - unanswerable} / 拒答类 {unanswerable})")
    print(f"多跳类: {multi_hop}")
    if items:
        print("分类分布:")
        for name, count in categories.most_common():
            print(f"  - {name}: {count} ({count / len(items):.1%})")
        top_doc, top_count = gold_doc_counter.most_common(1)[0] if gold_doc_counter else ("-", 0)
        print(f"单个文档占比最高: {top_doc} {top_count} 条 "
              f"({top_count / max(len(items), 1):.1%})")
        if top_count / max(len(items), 1) > 0.15:
            warnings.append(
                f"单个文档「{top_doc}」占了 {top_count} 条（{top_count / len(items):.1%}），"
                "建议不超过 15%，否则评测集会偏斜"
            )

    print(f"\n错误 {len(errors)} 条")
    for err in errors[:20]:
        print("  [错误]", err)
    print(f"警告 {len(warnings)} 条")
    for warn in warnings[:10]:
        print("  [警告]", warn)

    print("\n建议:")
    if len(items) < MIN_ITEMS:
        print(f"  - 条数不足 {MIN_ITEMS}，建议先补到 {MIN_ITEMS} 条以上")
    if unanswerable < 10:
        print(f"  - 拒答类只有 {unanswerable} 条，建议 10~15 条（用于验证不编造）")
    if multi_hop < 8:
        print(f"  - 多跳类只有 {multi_hop} 条，建议至少 8 条（用于验证 Agent）")
    if not errors:
        print("  - 格式与 gold 校验通过")

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
