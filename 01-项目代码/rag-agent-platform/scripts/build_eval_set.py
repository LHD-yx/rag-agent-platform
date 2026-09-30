"""把「自动生成的候选问题」+「手工补充的题目」整理成最终评测集。

为什么要这一步：
    自动出题覆盖面广，但很难产出「拒答类」和「多跳类」；
    这两类恰恰最能体现系统能力（会不会编造、能不能多步检索）。
    所以本脚本 = 自动候选（清洗 + 分类）+ 手工题目（按关键词定位答案出处）。

用法：
    python scripts/build_eval_set.py                 # 生成 data/eval/eval_set.jsonl
    python scripts/build_eval_set.py --auto-limit 120
    python scripts/build_eval_set.py --dry-run       # 只看统计，不写文件
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------- 手工题目
# keywords 用于在切片里定位答案出处（gold）；多跳题目给 2 组关键词，命中不同文档
MANUAL_ITEMS: list[dict] = [
    # ---- 事实查找 ----
    {"q": "整机保修期是多久", "cat": "事实查找", "kw": ["整机保修 12 个月"]},
    {"q": "屏幕和主板保修多长时间", "cat": "事实查找", "kw": ["主要部件保修 24 个月"]},
    {"q": "X3-55 的待机功耗是多少", "cat": "事实查找", "kw": ["待机功耗"]},
    {"q": "上门安装服务覆盖哪些地区", "cat": "事实查找", "kw": ["乡镇地区按距离收取上门费"]},
    {"q": "延保服务可以延长多长时间", "cat": "事实查找", "kw": ["延长 12 或 24 个月"]},
    {"q": "保外维修的上门费是多少", "cat": "事实查找", "kw": ["保外上门费 80 元"]},
    {"q": "保修期内换机后保修期怎么算", "cat": "事实查找", "kw": ["重新计算 12 个月"]},
    {"q": "全国服务网点覆盖多少个城市", "cat": "事实查找", "kw": ["286 个地级市"]},
    {"q": "客服热线的服务时间是几点到几点", "cat": "事实查找", "kw": ["09:00"]},
    # ---- 操作指引 ----
    {"q": "如何恢复出厂设置", "cat": "操作指引", "kw": ["恢复出厂设置"]},
    {"q": "怎么连接无线网络", "cat": "操作指引", "kw": ["2.4GHz"]},
    {"q": "固件升级失败怎么用 U 盘离线升级", "cat": "操作指引", "kw": ["FAT32"]},
    {"q": "如何开启儿童模式", "cat": "操作指引", "kw": ["儿童模式"]},
    {"q": "屏幕应该怎么清洁", "cat": "操作指引", "kw": ["超细纤维布"]},
    {"q": "出风口和散热孔要怎么维护", "cat": "操作指引", "kw": ["散热孔"]},
    {"q": "新机首次开机要做哪些设置", "cat": "操作指引", "kw": ["首次开机"]},
    # ---- 故障排查 ----
    {"q": "电视指示灯不亮怎么办", "cat": "故障排查", "kw": ["指示灯不亮"]},
    {"q": "遥控器怎么检查是不是坏了", "cat": "故障排查", "kw": ["手机摄像头"]},
    {"q": "HDMI 显示无信号怎么排查", "cat": "故障排查", "kw": ["确认输入源"]},
    {"q": "画面出现彩色噪点是什么原因", "cat": "故障排查", "kw": ["彩色噪点"]},
    {"q": "WiFi 连不上该怎么处理", "cat": "故障排查", "kw": ["重启路由器"]},
    {"q": "系统频繁卡顿、自动重启怎么办", "cat": "故障排查", "kw": ["清理后台"]},
    {"q": "蓝牙设备连不上怎么配对", "cat": "故障排查", "kw": ["配对模式"]},
    {"q": "投屏失败提示找不到设备怎么办", "cat": "故障排查", "kw": ["同一网络"]},
    # ---- 对比选择 ----
    {"q": "X3 系列和 A5 系列有什么区别", "cat": "对比选择", "kw": ["旗舰 4K", "家用主流"]},
    {"q": "SB-200 和 SB-300 回音壁差在哪", "cat": "对比选择", "kw": ["SB-200"]},
    {"q": "商用 C7 系列和家用系列有什么不同", "cat": "对比选择", "kw": ["商用精简系统"]},
    {"q": "智能盒子和电视内置系统该怎么选", "cat": "对比选择", "kw": ["老电视升级"]},
    # ---- 政策类 ----
    {"q": "七天无理由退货需要满足什么条件", "cat": "政策类", "kw": ["七天无理由退货"]},
    {"q": "延保服务覆盖人为损坏吗", "cat": "政策类", "kw": ["不含人为损坏"]},
    {"q": "升级保修后上门费还要收吗", "cat": "政策类", "kw": ["延保期内免上门费"]},
    {"q": "投诉处理分几个级别", "cat": "政策类", "kw": ["二级"]},
    {"q": "整机停产之后备件还能供应多久", "cat": "政策类", "kw": ["5 年的备件供应"]},
    # ---- 多跳组合（需要跨文档）----
    {"q": "X3-65 的电源板如果坏了保修多久", "cat": "多跳组合", "multi": True,
     "kw": ["X3-65", "主要部件保修 24 个月"]},
    {"q": "屏幕出现竖线在保修期内怎么处理", "cat": "多跳组合", "multi": True,
     "kw": ["竖线", "整机保修 12 个月"]},
    {"q": "回音壁连上了但没声音怎么排查", "cat": "多跳组合", "multi": True,
     "kw": ["回音壁", "音频输出"]},
    {"q": "恢复出厂设置会清除账号吗", "cat": "多跳组合", "multi": True,
     "kw": ["恢复出厂设置", "清除账号"]},
    {"q": "延保期内维修还要收检测费吗", "cat": "多跳组合", "multi": True,
     "kw": ["延保期内维修免上门费", "检测费"]},
    {"q": "在高温环境下使用会不会影响保修", "cat": "多跳组合", "multi": True,
     "kw": ["工作温度", "不属于保修"]},
    {"q": "投屏失败该怎么排查，和路由器有关吗", "cat": "多跳组合", "multi": True,
     "kw": ["投屏", "重启路由器"]},
    {"q": "恢复出厂设置前需要先做什么准备", "cat": "多跳组合", "multi": True,
     "kw": ["恢复出厂设置", "备份账号信息"]},
    {"q": "X3-75 安装时需要注意什么安全问题", "cat": "多跳组合", "multi": True,
     "kw": ["X3-75", "两人协作抬装"]},
    # ---- 口语化（考验查询改写）----
    {"q": "电视开不了机咋整", "cat": "口语化", "kw": ["无法开机"]},
    {"q": "遥控器没反应咋办", "cat": "口语化", "kw": ["遥控器失灵"]},
    {"q": "盒子连不上网", "cat": "口语化", "kw": ["无法连接无线网络"]},
    {"q": "屏幕咋擦才不伤", "cat": "口语化", "kw": ["清洁"]},
    {"q": "保修多久啊", "cat": "口语化", "kw": ["保修 12 个月"]},
    {"q": "上门修要花多少钱", "cat": "口语化", "kw": ["上门费"]},
    {"q": "延保是啥意思", "cat": "口语化", "kw": ["延保"]},
    {"q": "画面有点糊咋回事", "cat": "口语化", "kw": ["画面"]},
    # ---- 拒答类（语料里没有答案，用于验证不编造）----
    {"q": "竞品电视的价格是多少", "cat": "拒答", "refuse": True},
    {"q": "星澜公司的股票代码是多少", "cat": "拒答", "refuse": True},
    {"q": "星澜的 CEO 是谁", "cat": "拒答", "refuse": True},
    {"q": "星澜去年营收多少", "cat": "拒答", "refuse": True},
    {"q": "明天上海的天气怎么样", "cat": "拒答", "refuse": True},
    {"q": "帮我写一封辞职信", "cat": "拒答", "refuse": True},
    {"q": "帮我推荐一部好看的电影", "cat": "拒答", "refuse": True},
    {"q": "1234 乘以 5678 等于多少", "cat": "拒答", "refuse": True},
    {"q": "iPhone 最新款多少钱", "cat": "拒答", "refuse": True},
    {"q": "今天有什么科技新闻", "cat": "拒答", "refuse": True},
    {"q": "星澜电视在海外市场占有率多少", "cat": "拒答", "refuse": True},
    {"q": "隔壁品牌的客服电话是多少", "cat": "拒答", "refuse": True},
]

# 分类映射：根据片段所属文档/章节判断类别
CATEGORY_RULES: list[tuple[str, str]] = [
    ("排查", "故障排查"),
    ("故障", "故障排查"),
    ("规格", "事实查找"),
    ("能效", "事实查找"),
    ("包装", "事实查找"),
    ("配件", "事实查找"),
    ("保修", "政策类"),
    ("退换", "政策类"),
    ("维修", "政策类"),
    ("延保", "政策类"),
    ("服务", "政策类"),
    ("上门", "政策类"),
    ("对比", "对比选择"),
    ("选型", "对比选择"),
    ("常见问题", "常见问题"),
    ("问题", "常见问题"),
    ("手册", "操作指引"),
    ("指南", "操作指引"),
    ("维护", "操作指引"),
]


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"文件不存在: {path}")
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def guess_category(chunk: dict) -> str:
    text = f"{chunk.get('title', '')}{chunk.get('section_path', '')}"
    for key, category in CATEGORY_RULES:
        if key in text:
            return category
    return "其他"


# 型号正则：用于判断问题是否指代明确
MODEL_RE = re.compile(r"X3-\d+|A5-\d+|C7-\d+|P1-(?:Air|Standard|Pro)|S1(?:-Pro)?|SB-\d+")


def make_specific(query: str, chunk: dict) -> tuple[str, bool]:
    """把指代不清的问题补上具体型号，让问题有唯一答案。

    背景：语料里有 21 个高度相似的型号文档，若问题只说"这款产品/清洁屏幕"，
    检索命中"另一个包含相同内容的文档"就会被判错——这是问题本身有歧义，不是检索坏了。
    这里从答案出处里提取型号补进问题（例如 -> "P1-Standard 清洁屏幕需要断电吗"）。
    """
    if MODEL_RE.search(query):
        return query, False
    source = f"{chunk.get('section_path', '')} {chunk.get('text', '')[:120]}"
    match = MODEL_RE.search(source)
    if not match:
        return query, False
    return f"{match.group(0)} {query}", True


def clean_question(q: str) -> str:
    q = q.strip()
    q = re.sub(r"^[0-9]+[.、)]\s*", "", q)
    q = q.strip(" -—·。？?")
    return q + ("？" if not q.endswith(("？", "?", "。")) else "")


def locate_gold(chunks: list[dict], keywords: list[str], want: int = 1) -> list[dict]:
    """按关键词定位答案出处，尽量命中不同文档。"""
    hits: list[dict] = []
    used_docs: set[str] = set()
    for kw in keywords:
        for chunk in chunks:
            if kw not in chunk["text"] and kw not in chunk.get("section_path", ""):
                continue
            if chunk["doc_id"] in used_docs:
                continue
            hits.append(chunk)
            used_docs.add(chunk["doc_id"])
            break
        if len(hits) >= want:
            break
    return hits


def main() -> None:
    parser = argparse.ArgumentParser(description="整理最终评测集")
    parser.add_argument("--auto-limit", type=int, default=100, help="自动候选最多取多少条")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    chunks = load_jsonl(ROOT / "data/chunks/chunks.jsonl")
    chunk_by_id = {c["chunk_id"]: c for c in chunks}

    candidates_path = ROOT / "data/eval/candidates.jsonl"
    auto_items: list[dict] = []
    normalized = 0
    if candidates_path.exists():
        seen: set[str] = set()
        for item in load_jsonl(candidates_path):
            q = clean_question(item.get("query", ""))
            if not (6 <= len(q) <= 45) or q in seen:
                continue
            gold_id = (item.get("gold_chunk_ids") or [None])[0]
            chunk = chunk_by_id.get(gold_id)
            if chunk is None:
                continue
            q, made_specific = make_specific(q, chunk)
            normalized += 1 if made_specific else 0
            seen.add(q)
            auto_items.append({
                "query": q,
                "gold_chunk_ids": [gold_id],
                "gold_doc_ids": [chunk["doc_id"]],
                "category": guess_category(chunk),
            })
            if len(auto_items) >= args.auto_limit:
                break

    manual_items: list[dict] = []
    missing: list[str] = []
    for spec in MANUAL_ITEMS:
        if spec.get("refuse"):
            manual_items.append({
                "query": spec["q"], "category": spec["cat"], "unanswerable": True,
            })
            continue
        want = 2 if spec.get("multi") else 1
        hits = locate_gold(chunks, spec["kw"], want=want)
        if not hits:
            missing.append(f"{spec['q']}（关键词：{spec['kw']}）")
            continue
        entry = {
            "query": spec["q"],
            "gold_chunk_ids": [h["chunk_id"] for h in hits],
            "gold_doc_ids": [h["doc_id"] for h in hits],
            "category": spec["cat"],
        }
        if spec.get("multi"):
            entry["multi_hop"] = True
        manual_items.append(entry)

    eval_set = auto_items + manual_items
    stats = Counter(item["category"] for item in eval_set)
    refuse = sum(1 for item in eval_set if item.get("unanswerable"))
    multihop = sum(1 for item in eval_set if item.get("multi_hop"))

    print(f"自动候选: {len(auto_items)} 条（其中 {normalized} 条补上了具体型号，消除歧义）")
    print(f"手工题目: {len(manual_items)} 条（拒答 {refuse} / 多跳 {multihop}）")
    print(f"合计    : {len(eval_set)} 条")
    print("\n分类分布:")
    for name, count in stats.most_common():
        print(f"  {name}: {count}")
    if missing:
        print(f"\n未找到答案出处（已跳过 {len(missing)} 条）:")
        for m in missing[:8]:
            print("  -", m)

    if args.dry_run:
        print("\n--dry-run：未写入文件")
        return

    out_path = ROOT / "data/eval/eval_set.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for item in eval_set:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"\n已写入: {out_path}")
    print("下一步：python scripts/check_eval_set.py  →  python main.py eval")


if __name__ == "__main__":
    main()
