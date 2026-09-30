"""统计人工标注结果：答案正确率、引用正确率、拒答恰当率。

用法：
    python scripts/score_answers.py
    python scripts/score_answers.py --file data/results/annotation_sheet.csv
输出：
    终端打印 + data/results/answer_quality.md
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rag_agent.config import load_config  # noqa: E402

COL_ANSWER = "人工_答案正确性"
COL_CITE = "人工_引用正确"
COL_REFUSE = "人工_拒答恰当"
COL_CATEGORY = "分类"
COL_QUESTION = "问题"

# 归一化：把各种写法映射成标准值
ANSWER_MAP = {
    "正确": "正确", "完全正确": "正确", "对": "正确", "√": "正确", "yes": "正确",
    "部分正确": "部分正确", "部分": "部分正确", "半对": "部分正确",
    "错误": "错误", "错": "错误", "×": "错误", "x": "错误",
    "误拒": "误拒", "误拒（待核）": "误拒",
}
CITE_MAP = {
    "是": "是", "正确": "是", "对": "是", "√": "是",
    "部分": "部分", "部分正确": "部分",
    "否": "否", "错误": "否", "×": "否", "x": "否",
}
REFUSE_MAP = {
    "恰当": "恰当", "正确": "恰当", "是": "恰当",
    "缺失": "缺失", "缺失（硬答）": "缺失", "硬答": "缺失", "否": "缺失",
}


def norm(value: str, mapping: dict[str, str]) -> str:
    # 先去掉首尾空白和中文标点：在 Excel 里手填时容易多打一个「、」或「，」
    cleaned = (value or "").strip().strip("、，,。;； ")
    return mapping.get(cleaned.lower(), mapping.get(cleaned, ""))


def read_rows(path) -> tuple[list[dict], str]:
    """读标注表，自动兼容 Excel 另存后的编码。

    gen_answers.py 写出来的是 UTF-8 with BOM；但中文版 Excel 编辑后另存，
    默认会存成 GBK/ANSI，直接按 utf-8 读会抛 UnicodeDecodeError。
    这里依次尝试 utf-8-sig → gbk → gb18030。
    """
    for enc in ("utf-8-sig", "gbk", "gb18030"):
        try:
            with open(path, encoding=enc, newline="") as f:
                return list(csv.DictReader(f)), enc
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"读不了标注表（试过 utf-8 / gbk / gb18030）：{path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="统计答案质量标注")
    parser.add_argument("--file", default="data/results/annotation_sheet.csv")
    args = parser.parse_args()

    path = ROOT / args.file
    if not path.exists():
        raise SystemExit(f"标注表不存在：{path}（先运行 python scripts/gen_answers.py）")

    rows, used_enc = read_rows(path)
    print(f"（标注表编码：{used_enc}，共 {len(rows)} 行）")

    answer_stats: dict[str, int] = defaultdict(int)
    cite_stats: dict[str, int] = defaultdict(int)
    refuse_stats: dict[str, int] = defaultdict(int)
    by_category: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    unlabeled = 0

    for row in rows:
        category = (row.get(COL_CATEGORY) or "未分类").strip()
        answer = norm(row.get(COL_ANSWER, ""), ANSWER_MAP)
        cite = norm(row.get(COL_CITE, ""), CITE_MAP)
        refuse = norm(row.get(COL_REFUSE, ""), REFUSE_MAP)

        if not answer and not refuse:
            unlabeled += 1
            continue

        if answer:
            answer_stats[answer] += 1
            by_category[category][f"答案={answer}"] += 1
            by_category[category]["计"] += 1
        if cite:
            cite_stats[cite] += 1
        if refuse:
            refuse_stats[refuse] += 1

    total_answer = sum(answer_stats.values())
    total_cite = sum(cite_stats.values())
    total_refuse = sum(refuse_stats.values())

    def rate(part: int, whole: int) -> str:
        return f"{part / whole:.1%} ({part}/{whole})" if whole else "-"

    lines = [
        "# 答案质量评测报告",
        "",
        f"- 标注总条数: {len(rows)}（已标注 {len(rows) - unlabeled} / 未标注 {unlabeled}）",
        "",
        "## 总体指标",
        "",
        "| 指标 | 数值 |",
        "|---|---|",
        f"| 完全正确率 | {rate(answer_stats['正确'], total_answer)} |",
        f"| 部分正确率 | {rate(answer_stats['部分正确'], total_answer)} |",
        f"| 错误率 | {rate(answer_stats['错误'], total_answer)} |",
        f"| 误拒率（该答没答） | {rate(answer_stats['误拒'], total_answer)} |",
        f"| 引用正确率（是 / 含部分） | {rate(cite_stats['是'], total_cite)}"
        f"　部分 {cite_stats['部分']}　错误 {cite_stats['否']} |",
        f"| 拒答恰当率 | {rate(refuse_stats['恰当'], total_refuse)} |",
        "",
    ]

    if by_category:
        lines += [
            "## 分类明细",
            "",
            "| 分类 | 条数 | 完全正确 | 部分正确 | 错误 | 误拒 |",
            "|---|---|---|---|---|---|",
        ]
        for category, stats in sorted(by_category.items()):
            lines.append(
                f"| {category} | {stats['计']} | {stats['答案=正确']} | "
                f"{stats['答案=部分正确']} | {stats['答案=错误']} | {stats['答案=误拒']} |"
            )
        lines.append("")

    # 结论建议
    lines += ["## 结论与调参建议", ""]
    if not total_answer:
        lines.append("- 还没有有效标注，请先填写 `人工_答案正确性` 列。")
    else:
        wrong = answer_stats["错误"] / total_answer
        miss = answer_stats["误拒"] / total_answer
        if wrong > 0.15:
            lines.append(f"- 错误率 {wrong:.1%} 偏高：优先检查提示模板是否约束住了「只依据检索内容」"
                         "，以及引用校验是否生效。")
        if miss > 0.15:
            current = load_config()["generation"].get("min_score", 0.55)
            lines.append(
                f"- 误拒率 {miss:.1%} 偏高：调低 `generation.min_score`（当前 {current}），"
                "改完用 `python scripts/calibrate_threshold.py` 重新校准，别凭感觉调。"
            )
        if miss < 0.05 and refuse_stats["缺失"] > refuse_stats["恰当"]:
            lines.append("- 误拒很少但拒答类容易硬答：调高 `generation.min_score`。")
    if total_cite and cite_stats["否"] > total_cite * 0.2:
        lines.append("- 引用错误偏多：检查是否强制标注来源编号，以及引用校验逻辑是否开启。")
    if unlabeled:
        lines.append(f"- 还有 {unlabeled} 条未标注（未纳入统计）。")

    report = "\n".join(lines)
    out_path = ROOT / "data/results/answer_quality.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")

    print(report)
    print(f"\n已写入: {out_path}")


if __name__ == "__main__":
    main()
