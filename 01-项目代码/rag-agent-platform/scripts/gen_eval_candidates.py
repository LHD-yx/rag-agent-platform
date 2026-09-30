"""从切片批量生成评测集候选问题（LLM 生成 + gold 自动标注）。

思路：从已切片片段里分层抽样，让 LLM 为每个片段生成"能由该片段回答"的问题，
并自动把该片段 id 填成 gold。你只需要人工筛选和改写，不用从零写 100 条。

用法：
    python scripts/gen_eval_candidates.py --limit 120 --per-chunk 1
    python scripts/gen_eval_candidates.py --dry-run          # 只抽样，不调用 LLM
    python scripts/gen_eval_candidates.py --limit 50 --seed 7
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rag_agent.config import load_config, resolve  # noqa: E402
from rag_agent.generate import source_label  # noqa: E402
from rag_agent.llm import build_llm  # noqa: E402

PROMPT = """下面是一段企业文档片段。请模仿真实用户，生成 {n} 个不同的、且能由这段内容回答的问题。

要求：
1. 像用户自然提问，不要照抄原文标题；
2. 不要出现"根据上述材料""文中提到"这类措辞；
3. 每个问题只问一件事；
4. 如果片段里出现了具体型号或产品名（例如 X3-65、SB-300），问题里必须明确带上它，
   禁止使用"这款产品""该设备""本产品"这类指代不清的说法——否则问题会有多个正确文档；
5. 每行一个问题，不要编号、不要解释。

文档片段（来源：{source}）：
{text}"""


def load_chunks(cfg: dict) -> list[dict]:
    path = resolve(cfg, "paths.chunks_file")
    if not path.exists():
        raise SystemExit("没有切片数据，请先运行 python main.py chunk")
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def sample_chunks(chunks: list[dict], limit: int, seed: int) -> list[dict]:
    """按文档分层轮询抽样，避免候选问题集中在同一篇文档。"""
    groups: dict[str, list[dict]] = {}
    for chunk in chunks:
        groups.setdefault(chunk["doc_id"], []).append(chunk)

    rng = random.Random(seed)
    for items in groups.values():
        rng.shuffle(items)

    picked: list[dict] = []
    doc_ids = sorted(groups)
    while len(picked) < limit and doc_ids:
        for doc_id in list(doc_ids):
            if groups[doc_id]:
                picked.append(groups[doc_id].pop())
            else:
                doc_ids.remove(doc_id)
            if len(picked) >= limit:
                break
    return picked


def generate_questions(llm, chunk: dict, n: int) -> list[str]:
    prompt = PROMPT.format(n=n, source=source_label(chunk), text=chunk["text"][:800])
    text = llm.chat([{"role": "user", "content": prompt}], temperature=0.6)
    questions = [
        line.strip().lstrip("0123456789.、) ").strip()
        for line in text.splitlines()
        if line.strip()
    ]
    return [q for q in questions if 4 <= len(q) <= 60][:n]


def main() -> None:
    parser = argparse.ArgumentParser(description="生成评测集候选问题")
    parser.add_argument("--limit", type=int, default=120, help="抽样的片段数")
    parser.add_argument("--per-chunk", type=int, default=1, help="每个片段生成几个问题")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true", help="只抽样，不调用 LLM")
    parser.add_argument("--out-dir", default="data/eval")
    args = parser.parse_args()

    cfg = load_config()
    chunks = load_chunks(cfg)
    picked = sample_chunks(chunks, args.limit, args.seed)
    print(f"切片总数: {len(chunks)}，抽样: {len(picked)}，覆盖文档数: "
          f"{len({c['doc_id'] for c in picked})}")

    if args.dry_run:
        for chunk in picked[:5]:
            print(f"  · {chunk['chunk_id']}  {source_label(chunk)}")
        print("\n--dry-run 结束（未调用 LLM）")
        return

    llm = build_llm(cfg)
    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    candidates: list[dict] = []
    for i, chunk in enumerate(picked, start=1):
        try:
            questions = generate_questions(llm, chunk, args.per_chunk)
        except Exception as exc:  # 单条失败不影响整体
            print(f"  [{i}/{len(picked)}] 失败: {exc}")
            continue
        for query in questions:
            candidates.append(
                {
                    "query": query,
                    "gold_chunk_ids": [chunk["chunk_id"]],
                    "gold_doc_ids": [chunk["doc_id"]],
                    "category": "自动生成",
                    "auto": True,
                }
            )
        print(f"  [{i}/{len(picked)}] {source_label(chunk)} -> {len(questions)} 条")

    jsonl_path = out_dir / "candidates.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for item in candidates:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    review_lines = [
        "# 候选评测集复核清单",
        "",
        f"共 {len(candidates)} 条。逐条判断：问题是否像真实用户提问、是否能由该片段回答。",
        "保留的条目复制到 `data/eval/eval_set.jsonl`，并把 `category` 改成真实类别。",
        "",
        "| # | 问题 | 来源 | 片段预览 | 保留? |",
        "|---|---|---|---|---|",
    ]
    by_chunk = {c["chunk_id"]: c for c in picked}
    for idx, item in enumerate(candidates, start=1):
        chunk = by_chunk.get(item["gold_chunk_ids"][0], {})
        snippet = chunk.get("text", "")[:40].replace("\n", " ")
        review_lines.append(
            f"| {idx} | {item['query']} | {source_label(chunk)} | {snippet}… |  |"
        )
    (out_dir / "candidates_review.md").write_text("\n".join(review_lines), encoding="utf-8")

    print(f"\n候选评测集: {jsonl_path}")
    print(f"人工复核清单: {out_dir / 'candidates_review.md'}")
    print("下一步：筛选改写后写入 data/eval/eval_set.jsonl，再跑 python scripts/check_eval_set.py")


if __name__ == "__main__":
    main()
