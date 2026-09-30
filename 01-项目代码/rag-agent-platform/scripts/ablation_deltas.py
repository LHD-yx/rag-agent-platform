"""改前 / 改后对照：证明每个模块的增益到底来自哪一处改动。

为什么需要这个脚本：
    对外介绍里常引用「等权 RRF 0.436 → 加权 RRF 0.456」这类数字，
    但如果仓库里没有产出这张表的脚本，这些数字就无法复现。
    本脚本用同一批评测集，把「改前的配置」重新跑一遍，产出
    data/results/ablation_deltas.md，让每个数字都能当场复现。

一次只改一个变量（真消融），其余配置保持不变：
    A. RRF 等权（向量:关键词 = 1:1）        → 加权 3:1
    B. BM25 取 top-20（与向量同宽）          → 取 top-8
    C. 规则精排完全覆盖检索分（权重 0 / 1）  → 融合 0.85 / 0.15

用法：python scripts/ablation_deltas.py
输出：data/results/ablation_deltas.md
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rag_agent.config import load_config, resolve  # noqa: E402
from rag_agent.evaluate import EvalRunner, evaluate_config, load_eval_set  # noqa: E402


def patched(cfg: dict, **overrides) -> dict:
    """按 "retrieval.dense_weight=1.0" 这样的路径深拷贝并覆盖配置。"""
    new = copy.deepcopy(cfg)
    for key_path, value in overrides.items():
        node = new
        keys = key_path.split(".")
        for key in keys[:-1]:
            node = node[key]
        node[keys[-1]] = value
    return new


# (对比组标题, 评测模式, 改前说明, 改前覆盖, 改后说明, 改后覆盖)
GROUPS: list[tuple[str, str, str, dict, str, dict]] = [
    (
        "A. RRF 融合权重",
        "hybrid",
        "改前：等权融合（向量:关键词 = 1:1）",
        {"retrieval.dense_weight": 1.0, "retrieval.bm25_weight": 1.0},
        "改后：加权融合（向量:关键词 = 3:1）",
        {},
    ),
    (
        "B. BM25 召回条数",
        "hybrid",
        "改前：BM25 取 top-20（与向量同宽，噪声更多）",
        {"retrieval.bm25_top_k": 20},
        "改后：BM25 取 top-8",
        {},
    ),
    (
        "C. 规则精排是否保留检索分",
        "hybrid_rewrite_rerank",
        "改前：规则分完全覆盖检索分（retrieval_weight=0, rule_weight=1）",
        {"rerank.rule.retrieval_weight": 0.0, "rerank.rule.rule_weight": 1.0},
        "改后：检索分 0.85 + 规则分 0.15 融合",
        {},
    ),
]


def main() -> None:
    cfg = load_config()
    eval_set = load_eval_set(resolve(cfg, "paths.eval_file"))
    min_score = cfg["generation"].get("min_score", 0.0)
    metric = cfg["generation"].get("confidence_metric", "dense_score")

    lines = [
        "# 改前 / 改后对照表（单变量消融）",
        "",
        f"- 评测集：{len(eval_set)} 条（与 `ablation.md` 同一批）",
        f"- 置信度指标：`{metric}`　拒答阈值：{min_score}",
        "- 每个对比组只改一个变量，其余配置与 `configs/config.yaml` 完全一致",
        "- 复现命令：`python scripts/ablation_deltas.py`",
        "",
        "> 数字波动：embedding 服务端的数值不是逐位确定的，同一配置重跑，"
        "hit@1 会有 ±1 条问题（约 ±0.007）的波动，延迟受网络影响更明显。"
        "比较增益时看的是量级，不是小数点后第三位。",
        "",
    ]

    for title, mode, before_desc, before_patch, after_desc, after_patch in GROUPS:
        print(f"\n=== {title}（模式: {mode}）===")
        rows = []
        for desc, patch in ((before_desc, before_patch), (after_desc, after_patch)):
            runner = EvalRunner(patched(cfg, **patch))
            row = evaluate_config(runner, eval_set, desc, mode, min_score, metric)
            rows.append(row)
            print(f"{desc}: hit@1={row['hit@1']:.3f} hit@3={row['hit@3']:.3f} "
                  f"MRR={row['MRR']:.3f} 延迟={row['平均延迟(ms)']:.0f}ms")

        before, after = rows
        delta1 = after["hit@1"] - before["hit@1"]
        delta3 = after["hit@3"] - before["hit@3"]
        delta_mrr = after["MRR"] - before["MRR"]

        lines += [
            f"## {title}",
            "",
            f"评测模式：`{mode}`　改动：{before_desc.split('：')[1]} → {after_desc.split('：')[1]}",
            "",
            "| 配置 | hit@1 | hit@3 | MRR | 平均延迟(ms) |",
            "|---|---|---|---|---|",
        ]
        for row in rows:
            lines.append(
                f"| {row['config']} | {row['hit@1']:.3f} | {row['hit@3']:.3f} | "
                f"{row['MRR']:.3f} | {row['平均延迟(ms)']:.0f} |"
            )
        lines += [
            f"| **差值** | **{delta1:+.3f}** | **{delta3:+.3f}** | "
            f"**{delta_mrr:+.3f}** | — |",
            "",
        ]

    out = ROOT / "data/results/ablation_deltas.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n已写入: {out}")


if __name__ == "__main__":
    main()
