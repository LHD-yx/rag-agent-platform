# rag-agent-platform

示例项目：企业知识库问答平台（RAG 检索 + 评测 + Agent 扩展）

> **第一次上手？按下面「快速开始」走一遍即可**；卡住了就跑 `python main.py doctor`，它会告诉你现在缺什么、下一步做什么。

> **Windows 上想双击就跑？** 到仓库根目录（项目代码在它下面的 `01-项目代码\` 里），按顺序双击：
> `1-环境自检.bat` → `2-重建索引.bat` → `3-启动后端服务.bat` → `4-启动桌面应用.bat` → `5-生成演示截图.bat`

> **文档导航**：完整说明、评测结果与复现命令看仓库根 `README.md`。

## 目标

用 240 篇文档跑通完整 RAG 检索链路，并产出一张**消融实验表**：
纯向量 / 纯 BM25 / 混合检索（RRF）各自的 hit@1、hit@3、MRR 与延迟。

## 快速开始

```bash
# 环境（二选一）：自建 venv，或直接用你已有的环境
python -m venv .venv && .venv\Scripts\activate        # Windows；Linux/macOS 用 source .venv/bin/activate
pip install -r requirements.txt

# 配置 API Key（也可以复制 .env.example 为 .env 再填）
# Windows PowerShell: $env:SILICONFLOW_API_KEY="你的key"
export SILICONFLOW_API_KEY=你的key

python main.py doctor           # 环境自检：依赖 / Key / 语料 / 索引 / 评测集
python main.py chunk            # 解析 + 清洗 + 切片
python main.py index            # 建 FAISS + BM25 索引
python main.py query "你的问题"   # 单条试检索
python main.py eval             # 跑评测 + 消融表
```

## 评测集格式

`data/eval/eval_set.jsonl`，每行一条：

```json
{"query": "问题文本", "gold_chunk_ids": ["docA-0-1"], "gold_doc_ids": ["docA"]}
```

两种标注任选其一：知道具体片段用 `gold_chunk_ids`，只知道在哪篇文档用 `gold_doc_ids`。

## 目录结构

```
rag-agent-platform/
├── main.py                  # 统一入口（chunk / index / query / ask / agent / eval / serve）
├── configs/config.yaml      # 所有参数（切片、召回、RRF、拒答阈值）
├── rag_agent/
│   ├── config.py            # 配置加载
│   ├── embedding.py         # API / 本地 双后端
│   ├── chunking.py          # 解析 + 清洗 + 标题层级切片
│   ├── build_index.py       # 建索引
│   ├── hybrid.py            # 双路召回 + RRF
│   ├── rerank.py            # 规则精排 / cross-encoder
│   ├── generate.py          # 生成 + 引用校验 + 拒答
│   ├── api.py               # FastAPI 同步 / SSE 接口
│   └── evaluate.py          # 指标 + 消融表
├── scripts/                 # 评测集构建、阈值校准、消融对照、失败归因
├── docs/                    # 评测集构建指南（格式 / 分布 / 构建步骤 / 标注规则）
└── data/
    ├── raw/                 # 原始文档（示例语料 240 篇）
    ├── eval/                # 评测集（161 条）
    └── results/             # 6 张评测报告
```

## 路线图

- [x] 解析 / 切片 / 双路召回 / RRF / 评测
- [x] 查询改写（词典归一化 + HyDE）
- [x] 精排（规则 + reranker API）
- [x] 生成链路（引用约束 + 拒答 + 引用校验）
- [x] FastAPI `/query`、`/query/stream`（SSE）+ 语义缓存
- [x] LangGraph 多步检索 Agent

## 完整命令一览

```bash
python main.py doctor            # 环境自检（卡住了先跑这个）
python main.py chunk             # 解析 + 清洗 + 切片
python main.py index             # 建索引
python main.py query "问题"       # 只检索（不花钱）
python main.py rewrite "问题"     # 看查询改写效果
python main.py ask "问题"         # 端到端问答
python main.py agent "问题"       # 多跳 Agent
python main.py eval              # 评测 + 消融表
python main.py serve             # 启动服务（默认 127.0.0.1:8000）
```

`main.py eval` 会输出 5 档配置的对比表（纯向量 / 纯 BM25 / 混合 RRF / +查询改写 / +精排），
写入 `data/results/ablation.md`。开启 HyDE 只需把 `configs/config.yaml` 里的
`rewrite.enable_hyde` 改为 `true`（会额外消耗 LLM 额度）。

## 评测集构建方法

评测集在 `data/eval/eval_set.jsonl`，每行一条，字段格式见上。四步构建：

```bash
# 1) 自动生成候选问题（LLM 为每个片段出题，gold 自动标注）
python scripts/gen_eval_candidates.py --limit 120 --per-chunk 1
python scripts/gen_eval_candidates.py --dry-run        # 只抽样、不调用 LLM

# 2) 人工筛选改写，写入 data/eval/eval_set.jsonl（格式参考 eval_set.example.jsonl）
#    这一步是必要的：问题要像真实用户会问的，而且确实能被该片段回答

# 3) 手工补「多跳组合」和「拒答类」——这两类自动生成很难产出
#    拒答类标 "unanswerable": true，用来验证系统不会编造

# 4) 校验 + 出消融表
python scripts/check_eval_set.py
python main.py eval
```

验收口径：条数 ≥ 100（本项目 161 条）、拒答类 10~15 条、单个文档来源的问题占比 < 15%、无重复问题。

字段规范、建议分布、详细步骤与验收清单见 [docs/评测集构建指南.md](docs/评测集构建指南.md)。

## 答案质量评测

检索指标只看"有没有检索到"，答案质量必须人工标：

```bash
# 1) 跑一遍端到端问答，生成标注表（要全量跑，不要加 --limit：
#    12 条拒答样本都在评测集末尾 150~161 行，只跑前 N 条会一条都取不到）
python scripts/gen_answers.py

# 2) 用 Excel 打开 data/results/annotation_sheet.csv，填 3 列：
#    人工_答案正确性：正确 / 部分正确 / 错误（系统误拒的情况已自动预填）
#    人工_引用正确  ：是 / 部分 / 否
#    人工_拒答恰当  ：恰当 / 缺失（仅拒答类条目）

# 3) 统计成报告
python scripts/score_answers.py
```

输出 `data/results/answer_quality.md`：完全正确率、部分正确率、错误率、误拒率、
引用正确率、拒答恰当率，按问题类别拆分，并给出调参建议（例如误拒率高就下调阈值）。

## 复现全部数字

仓库里每个数字都有对应的产出文件和复现命令，可随时复现核对：

| 数字 | 产出文件 | 复现命令 | 花费 |
|---|---|---|---|
| 5 档消融表（hit@1 / hit@3 / MRR / 延迟 / 拒答检出率） | `data/results/ablation.md` | `python main.py eval` | 只用 embedding |
| 拒答阈值校准（precision / recall 权衡） | `data/results/threshold_calibration.md` | `python scripts/calibrate_threshold.py` | 只用 embedding |
| 改前 / 改后单变量对照（每个增益来自哪处改动） | `data/results/ablation_deltas.md` | `python scripts/ablation_deltas.py` | 只用 embedding |
| 切片段数对照（`min_chars` 30 → 12） | `data/results/chunking_delta.md` | `python scripts/chunking_delta.py` | 免费（纯本地） |
| 失败归因诊断（错在哪一类，不只是多少分） | `data/results/diagnose_retrieval.md` | `python scripts/diagnose_retrieval.py` | 只用 embedding |
| 语料分格式统计（md 6.5 片/篇 vs pdf 1.4 片/篇） | `data/chunks/chunk_report.txt` | `python main.py chunk` | 免费（纯本地） |

> **数字波动**：embedding 服务端的数值不是逐位确定的，同一配置重跑，hit@1 会有 ±1 条问题
> （约 ±0.007）的波动，延迟受网络影响更大。比较增益时看量级即可，小数点后第三位不作参考。

> **延迟口径**：消融表里的"平均延迟"是评测循环内单条查询的平均检索耗时（含 embedding 网络往返，
> 不含冷启动与 LLM 生成）。端到端含冷启动的实测看 `python main.py ask` 输出的 `timings_ms`
> （本项目实测约 0.8s 检索 + 2.7s 生成）。两者口径不同，引用时请标明是哪一种。

## 接口示例

```bash
# 同步
curl -X POST http://127.0.0.1:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "设备无法开机怎么办"}'

# 流式（SSE）：先返回 contexts，再逐 token 返回答案
curl -N -X POST http://127.0.0.1:8000/query/stream \
  -H "Content-Type: application/json" \
  -d '{"question": "设备无法开机怎么办"}'
```

## 关键设计说明

| 设计点 | 为什么这么做 |
|---|---|
| 标题路径写入 embed_text | 片段脱离上下文后语义不清，加标题前缀显著提升召回 |
| RRF 而不是加权求和 | BM25 分数量纲与余弦不可比，RRF 只用排名，鲁棒且免调参 |
| 多查询 RRF 合并 | HyDE 与原始查询各自召回，再统一融合，避免单路偏置 |
| 拒答阈值基于向量相似度 | 检索不到就没有可信答案，宁可拒答也不编造；用 RRF 分做阈值会失效（其分数恒为 1/(k+rank)，与相关性无关） |
| 引用校验 | 生成后校验 `[n]` 是否落在检索结果范围内，防幻觉引用 |
| 两级缓存 | 精确命中零成本；语义缓存的 embedding 开销用阈值控制 |
| Agent 拆解 + 充分性判断 | 多跳问题单轮检索必然漏召回，显式拆解并判断是否补充检索 |
