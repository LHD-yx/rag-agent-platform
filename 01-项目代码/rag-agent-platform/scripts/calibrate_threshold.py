"""拒答阈值校准：在「检出率」与「误拒率」之间找平衡点。

原理：
    对每条问题取检索结果的最高向量相似度（dense_score）作为置信度。
    - 可回答的问题：置信度 < 阈值 → 被误拒（该答没答）
    - 拒答类问题  ：置信度 < 阈值 → 成功检出（该拒就拒）
    扫描多个阈值，输出对照表，选「误拒率可接受、检出率最高」的那一档。

口径（重要，别改）：
    置信度 = **生产链路 top-1 片段的 dense_score**，即
        查询归一化 -> FAISS 向量 + BM25 双路召回 -> RRF 融合 -> 规则精排
    之后排在第一位的那个片段的向量余弦相似度。

    这与下面两处完全同源，因此两张表的数字可以直接互相引用：
        1) rag_agent/generate.py::Generator.confidence（线上拒答判断）
        2) data/results/ablation.md 最后一行「混合 + 改写 + 精排」

    历史坑：早期版本用的是「单查询向量检索 top-1」，比生产链路少一次精排，
    同一个阈值下检出率偏低（0.55 档 75% vs 83.3%），导致校准表和消融表
    对不上。本脚本已统一为生产口径，改回去会重新引入这个矛盾。

用法：python scripts/calibrate_threshold.py
输出：data/results/threshold_calibration.md
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rag_agent.config import load_config, resolve  # noqa: E402
from rag_agent.evaluate import EvalRunner, load_eval_set  # noqa: E402

# 与消融表最后一行完全相同的检索链路，保证两张表口径一致
CONFIDENCE_MODE = "hybrid_rewrite_rerank"

# 扫描网格：覆盖「几乎不拒答」到「几乎全拒答」，两端都留着才能看出权衡曲线
THRESHOLDS = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]

# 选阈值规则：先把「该答没答」压住，再在满足前提的档位里取检出率最高的
MAX_FALSE_REJECT = 0.05


def main() -> None:
    cfg = load_config()
    eval_set = load_eval_set(resolve(cfg, "paths.eval_file"))
    runner = EvalRunner(cfg)
    metric = cfg["generation"].get("confidence_metric", "dense_score")
    current = cfg["generation"].get("min_score", 0.0)

    answerable_scores: list[float] = []
    refuse_scores: list[float] = []

    for item in eval_set:
        chunks = runner.ranked_chunks(item["query"], CONFIDENCE_MODE)
        score = float(chunks[0].get(metric, chunks[0].get("score", 0.0))) if chunks else 0.0
        (refuse_scores if item.get("unanswerable") else answerable_scores).append(score)

    answerable_scores.sort()
    refuse_scores.sort()
    mid_a = answerable_scores[len(answerable_scores) // 2]
    mid_r = refuse_scores[len(refuse_scores) // 2]

    lines = [
        "# 拒答阈值校准表",
        "",
        f"- 置信度口径：生产链路 top-1 片段的 `{metric}`"
        "（归一化 → FAISS+BM25 双路召回 → RRF 融合 → 规则精排）",
        "- 与 `ablation.md` 最后一行「混合 + 改写 + 精排」同源，"
        "也与线上 `Generator.confidence` 一致",
        f"- 可回答题目: {len(answerable_scores)} 条（置信度中位数 {mid_a:.3f}）",
        f"- 拒答类题目: {len(refuse_scores)} 条（置信度中位数 {mid_r:.3f}）",
        f"- 当前 `configs/config.yaml` 里的 `generation.min_score` = {current}",
        "",
        "| 阈值 | 拒答检出率 | 误拒率 | 说明 |",
        "|---|---|---|---|",
    ]

    print(f"可回答 {len(answerable_scores)} 条 / 拒答类 {len(refuse_scores)} 条")
    print(f"置信度口径: {metric}（生产链路 top-1）\n")
    print("| 阈值 | 拒答检出率 | 误拒率 |")
    print("|---|---|---|")

    # 先算出全表，再决定推荐档位——避免"每刷新一次最好成绩就标一次推荐"
    rows: list[tuple[float, float, float]] = []
    for threshold in THRESHOLDS:
        detected = sum(1 for s in refuse_scores if s < threshold)
        false_reject = sum(1 for s in answerable_scores if s < threshold)
        detect_rate = detected / len(refuse_scores) if refuse_scores else 0.0
        reject_rate = false_reject / len(answerable_scores) if answerable_scores else 0.0
        rows.append((threshold, detect_rate, reject_rate))

    # 选阈值：满足「误拒率 ≤ MAX_FALSE_REJECT」，在其中取检出率最高的一档
    eligible = [r for r in rows if r[2] <= MAX_FALSE_REJECT]
    best_row = max(eligible, key=lambda r: r[1]) if eligible else None
    best, best_detect = (best_row[0], best_row[1]) if best_row else (None, 0.0)

    for threshold, detect_rate, reject_rate in rows:
        notes = []
        if best_row is not None and abs(threshold - best) < 1e-9:
            notes.append(f"← 推荐（误拒 ≤{MAX_FALSE_REJECT:.0%} 前提下检出率最高）")
        if abs(threshold - current) < 1e-9:
            notes.append("当前配置")

        note = " ".join(notes)
        print(f"| {threshold:.2f} | {detect_rate:.1%} | {reject_rate:.1%} | {note} |")
        lines.append(f"| {threshold:.2f} | {detect_rate:.1%} | {reject_rate:.1%} | {note} |")

    lines += [
        "",
        "## 怎么用",
        "",
        "1. 把 `configs/config.yaml` 里的 `generation.min_score` 设为上表的推荐值"
        f"{f'（本次为 {best:.2f}）' if best else '（本次未找到满足条件的阈值，建议先补充拒答样本）'}；",
        "2. 重跑 `python main.py eval`，确认「拒答检出率」上升且「可回答条目」没有明显损失；",
        "3. 这张表与消融表引用的是同一个阈值口径；早期版本用「单查询向量 top-1」算过一版"
        "（0.55 档 75%），已废弃。",
    ]

    out = ROOT / "data/results/threshold_calibration.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n已写入: {out}")
    if best:
        print(f"推荐阈值: {best:.2f}（检出率 {best_detect:.1%}）")


if __name__ == "__main__":
    main()
