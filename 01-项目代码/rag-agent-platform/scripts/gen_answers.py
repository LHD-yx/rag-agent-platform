"""跑一遍端到端问答，产出人工标注表（答案质量评测用）。

检索指标（hit@1/hit@3）只看"有没有检索到"，
答案质量看的是"答得对不对、引用对不对、该拒答时拒没拒"——这部分必须人工标。

用法：
    python scripts/gen_answers.py                # 全量（推荐）
    python scripts/gen_answers.py --limit 30     # 只跑前 30 条（注意：12 条拒答样本都在末尾 150~161 行，
                                                 #   小批量会把「拒答恰当」这一列全跑空，只适合快速冒烟）

输出：
    data/results/answers.jsonl          完整记录（答案、上下文、置信度、耗时）
    data/results/annotation_sheet.csv   人工标注表（Excel 可直接打开填写，含 UTF-8 BOM）
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rag_agent.config import load_config, resolve  # noqa: E402
from rag_agent.evaluate import load_eval_set  # noqa: E402
from rag_agent.pipeline import RagPipeline  # noqa: E402

CSV_HEADER = [
    "序号", "分类", "问题", "系统是否拒答", "置信度",
    "系统回答", "引用编号", "引用是否合法",
    "参考片段1", "参考片段2", "参考片段3",
    "人工_答案正确性", "人工_引用正确", "人工_拒答恰当", "人工_备注",
]


def flatten(text: str, limit: int = 300) -> str:
    """去掉换行，避免 Excel 单元格错行。"""
    return " ".join(text.split())[:limit]


def prefill_annotation(item: dict, result: dict) -> tuple[str, str]:
    """能自动判的部分先填好，减少人工工作量。

    返回 (人工_答案正确性, 人工_拒答恰当)
    """
    unanswerable = bool(item.get("unanswerable"))
    refused = bool(result["refused"])
    if refused and unanswerable:
        return "误拒（待核）", "恰当"
    if refused and not unanswerable:
        return "误拒", ""
    if not refused and unanswerable:
        return "", "缺失（硬答）"
    return "", ""


def main() -> None:
    parser = argparse.ArgumentParser(description="生成答案质量人工标注表")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条，0 表示全部")
    parser.add_argument("--out-dir", default="data/results")
    args = parser.parse_args()

    cfg = load_config()
    eval_set = load_eval_set(resolve(cfg, "paths.eval_file"))
    if args.limit:
        eval_set = eval_set[: args.limit]

    pipeline = RagPipeline(cfg)
    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[list[str]] = []
    records: list[dict] = []

    for idx, item in enumerate(eval_set, start=1):
        question = item["query"]
        result = pipeline.answer(question, use_cache=False)
        contexts = result["contexts"][:3]

        answer_correct, refusal_ok = prefill_annotation(item, result)
        rows.append([
            str(idx),
            item.get("category", "未分类"),
            question,
            "是" if result["refused"] else "否",
            f"{result['confidence']:.3f}",
            flatten(result["answer"]),
            ",".join(f"[{c}]" for c in result["citations"]),
            "否" if result["invalid_citations"] else "是",
            flatten(contexts[0]["text"], 120) if len(contexts) > 0 else "",
            flatten(contexts[1]["text"], 120) if len(contexts) > 1 else "",
            flatten(contexts[2]["text"], 120) if len(contexts) > 2 else "",
            answer_correct,
            "",
            refusal_ok,
            "",
        ])
        records.append(
            {
                "id": idx,
                "question": question,
                "category": item.get("category", "未分类"),
                "unanswerable": bool(item.get("unanswerable")),
                **{k: result[k] for k in
                   ("answer", "refused", "citations", "invalid_citations", "confidence", "timings")},
                "contexts": [
                    {
                        "source": c.get("source", ""),
                        "score": c.get("score", 0.0),
                        "dense_score": c.get("dense_score", 0.0),
                        "snippet": c["text"][:200],
                    }
                    for c in result["contexts"]
                ],
            }
        )
        print(f"  [{idx}/{len(eval_set)}] 拒答={result['refused']} "
              f"置信度={result['confidence']:.3f}  {question[:32]}")

    jsonl_path = out_dir / "answers.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    csv_path = out_dir / "annotation_sheet.csv"
    # utf-8-sig 保证 Excel 打开中文不乱码
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        writer.writerows(rows)

    print(f"\n完整记录: {jsonl_path}")
    print(f"人工标注表: {csv_path}")
    print("\n填写说明：")
    print("  人工_答案正确性：可回答条目填 正确 / 部分正确 / 错误（已自动预填 误拒 的情况请核对）")
    print("  人工_引用正确  ：填 是 / 部分 / 否（没有引用则留空）")
    print("  人工_拒答恰当  ：拒答类条目填 恰当 / 缺失")
    print("  填完运行：python scripts/score_answers.py")
    print()
    print("  提示：用 Excel 编辑这张表后另存，中文版 Excel 默认会存成 GBK；")
    print("        score_answers.py 已兼容 GBK 与 UTF-8，另存时选「CSV UTF-8」更稳妥。")


if __name__ == "__main__":
    main()
