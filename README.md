# 企业知识库 RAG 问答系统

> 不止"能答"，还要"可度量"。一套带完整评测体系的检索增强生成（RAG）系统，外加一个基于它的桌面对话客户端。

语料是 240 篇虚构品牌「星澜」的产品文档（脚本生成，不含任何真实数据），可直接复现全部结论。

## 仓库结构

- `01-项目代码/rag-agent-platform/` —— 后端：RAG 检索 + 评测体系 + Agent
- `01-项目代码/rag-desktop/` —— 桌面端：Electron + React + TypeScript
- 根目录的 5 个 `.bat` —— 双击即用的快捷入口，顺序：
  `1-环境自检` → `2-重建索引` → `3-启动后端服务` → `4-启动桌面应用` → `5-生成演示截图`
- 根目录的 `README.md`（本文件）—— 项目介绍与评测结果

## 这个仓库解决什么

大多数 RAG Demo 停在"能跑通"，但真实业务关心的是：召回够不够准？答案有没有编造？换个切片参数是变好还是变坏？
本项目在完整检索链路上建立了一套**可复现的评测体系**，并用评测结论反过来修正检索设计。

| 能力 | 实现 |
|---|---|
| 解析与切片 | PDF / Word / Markdown / TXT 统一解析，标题层级切片（512/128），片段拼接标题路径作为上下文 |
| 混合检索 | FAISS 向量（BGE-M3）+ BM25 双路召回，加权 RRF 融合 |
| 查询改写 | 词典式型号归一化 + HyDE 假设文档检索（可开关对比） |
| 精排 | 规则精排（检索分 0.85 + 规则分 0.15）与 cross-encoder 可切换 |
| 幻觉控制 | 引用约束提示 + 引用合法性校验 + 基于向量相似度的低置信拒答 |
| 服务 | FastAPI 同步接口 + SSE 流式接口、并发限流、两级缓存（精确 + 语义） |
| Agent | LangGraph 多跳检索：拆解 → 多查询检索 → 充分性判断 → 生成 |
| 评测体系 | 161 条评测集、5 档消融、拒答阈值校准、改前改后单变量对照、失败归因诊断 |

## 目录结构

```
01-项目代码/rag-agent-platform/  # 后端：RAG 检索平台（Python）
├── rag_agent/                 #   核心代码：切片 / 召回 / 融合 / 精排 / 生成 / 服务 / Agent
├── scripts/                   #   评测集构建、阈值校准、消融对照、失败归因
├── configs/config.yaml        #   所有参数（切片、召回权重、拒答阈值）
├── data/raw/                  #   240 篇示例语料（虚构品牌「星澜」）
├── data/eval/                 #   161 条评测集
├── data/results/              #   ★ 评测报告（下面几张表就是在这里产出的）
└── docs/                      #   评测集构建指南

01-项目代码/rag-desktop/         # 前端：Electron + React 桌面对话客户端
├── electron/main.ts           #   主进程：请求后端 + 解析 SSE + IPC 通道
├── electron/preload.ts        #   预加载：contextBridge 暴露最小接口
└── src/                       #   渲染层：React + TypeScript + Vite
```

## 评测结果

评测集 161 条（可回答 149 / 拒答 12），切片 `chunk_size=512` / `overlap=128`。

**5 档消融**（产出：`rag-agent-platform/data/results/ablation.md`）

| 配置 | hit@1 | hit@3 | MRR | 平均延迟(ms) | 拒答检出率 |
|---|---|---|---|---|---|
| 纯向量 | **0.510** | **0.664** | **0.607** | 122 | 75.0% |
| 纯 BM25 | 0.302 | 0.416 | 0.401 | 6 | 25.0% |
| 向量 + BM25 (RRF) | 0.456 | 0.638 | 0.572 | 116 | 83.3% |
| 混合 + 查询改写 | 0.436 | 0.631 | 0.557 | 112 | 83.3% |
| 混合 + 改写 + 精排 | 0.443 | 0.631 | 0.557 | 134 | 83.3% |

**一个反直觉的结论**：这套语料上**纯向量的 hit@1（0.510）高于混合检索（0.456）**。
语料里有 21 个型号、内容高度相似，关键词召回容易命中"另一个型号的同类文档"，反而引入噪声。
但混合检索在拒答上更稳（检出率 83.3% vs 75%），价值体现在置信度可靠性上。
结论：**"混合检索一定更好"是误区，必须用自己的评测集验证。**

**拒答阈值校准**（产出：`data/results/threshold_calibration.md`）

| 阈值 | 拒答检出率 | 误拒率 |
|---|---|---|
| 0.40 | 0.0% | 0.0% |
| 0.50 | 66.7% | 0.7% |
| **0.55** | **83.3%** | **2.0%** |
| 0.60 | 91.7% | 6.7% |

按"误拒率 ≤5% 前提下检出率最高"选出 0.55。

**改前 / 改后单变量对照**（产出：`data/results/ablation_deltas.md`）

| 改动 | 改前 | 改后 |
|---|---|---|
| 等权 RRF → 加权 3:1 | hit@1 0.436 | hit@1 0.456 |
| 规则精排覆盖检索分 → 融合 0.85/0.15 | hit@1 0.315 | hit@1 0.443 |
| BM25 召回 top-20 → top-8 | hit@1 0.456 | 无差异（仅噪声与延迟略降） |
| 拒答阈值 0.38 → 0.55 | 检出率 0% | 检出率 83.3% |
| `min_chars` 30 → 12 | 1180 片段 | 1302 片段 |

**答案质量**（产出：`data/results/answer_quality.md`）

检索指标只能说明"有没有检索到"，答得对不对必须人工标。161 条全量标注后：

| 指标 | 数值 |
|---|---|
| 完全正确率 | **89.9%**（134/149） |
| 部分正确率 | 1.3%（2/149） |
| 错误率 | 6.7%（10/149） |
| 误拒率（该答没答） | **2.0%**（3/149） |
| 引用正确率 | **80.3%**（118/147，部分 16、错误 13） |
| 拒答恰当率 | **83.3%**（10/12） |

**另一个同样重要的发现**：147 条有引用的答案里，**29 条（19.7%）引用有瑕疵**——16 条是"个别编号引错片段、
或用了只有页眉没有正文的片段凑数"，13 条是"引用完全对不上"（集中在模型软拒答的那些题）。
也就是说**"答案里标了 `[n]`"并不等于"引用可溯源"**：引用合法性校验只能拦住编号越界，
拦不住"引错片段"——后者只有人工标注能发现。

## 关键设计决策

| 设计 | 为什么这么做 |
|---|---|
| 标题路径写进 `embed_text` | 片段脱离上下文后语义模糊（"请先检查电源线"不知道是哪台设备），拼上"文档名 > 章节路径"后召回明显更稳；BM25 仍用原文，避免噪声 |
| 用 RRF 而不是分数加权求和 | BM25 分数无上界、余弦相似度在 0~1，量纲不可比；RRF 只用排名信息，鲁棒且免调参 |
| 拒答阈值用向量余弦相似度，不用 RRF 分 | RRF 分只反映排名、恒为 `1/(k+rank)`，拿它当阈值等于永远不触发（实测 12 条拒答样本一条都没检出） |
| 生成后校验引用编号 | 强制标注 `[n]` 并校验是否落在本次检索结果范围内，防止编造来源 |
| 两级缓存 | 精确匹配零成本；语义缓存用向量相似度 ≥0.95 命中，可按需开关 |
| 切片 `min_chars` 不能设太大 | "现象描述""可能原因"这类一两行的短章节往往正是答案所在，设成 30 会被整段丢掉 |

## 快速开始

环境要求：Python 3.10+，Node.js 18+（只跑后端的话不需要 Node）。**不需要 GPU**——向量化与大模型生成都走云端 API。

```bash
cd 01-项目代码/rag-agent-platform
pip install -r requirements.txt

# 复制 .env.example 为 .env，填入 SILICONFLOW_API_KEY（硅基流动有免费额度）
python main.py doctor         # 环境自检：依赖 / Key / 语料 / 索引 / 评测集
python main.py chunk          # 解析 + 切片（纯本地，免费）
python main.py index          # 建 FAISS + BM25 索引（调用 embedding 接口）
python main.py query "X3-65 的刷新率"     # 只检索，不花钱
python main.py ask "电视无法开机怎么办"     # 端到端问答
python main.py serve          # 起服务：http://127.0.0.1:8000/docs
```

桌面端（**先启动上面的后端服务**）：

```bash
cd 01-项目代码/rag-desktop
npm install
npm run dev
```

## 复现所有数字

| 数字 | 产出文件 | 命令 | 花费 |
|---|---|---|---|
| 5 档消融 | `data/results/ablation.md` | `python main.py eval` | 仅 embedding |
| 阈值校准 | `data/results/threshold_calibration.md` | `python scripts/calibrate_threshold.py` | 仅 embedding |
| 改前改后对照 | `data/results/ablation_deltas.md` | `python scripts/ablation_deltas.py` | 仅 embedding |
| 失败归因 | `data/results/diagnose_retrieval.md` | `python scripts/diagnose_retrieval.py` | 仅 embedding |
| 切片对照 | `data/results/chunking_delta.md` | `python scripts/chunking_delta.py` | 免费 |
| 语料分格式统计 | `data/chunks/chunk_report.txt` | `python main.py chunk` | 免费 |
| 答案质量 | `data/results/answer_quality.md` | `python scripts/gen_answers.py` → 人工标注 → `python scripts/score_answers.py` | embedding + 生成 |

三点口径说明：

- **延迟**：消融表里的是评测循环内单条查询的平均检索耗时（含 embedding 网络往返，不含冷启动与 LLM 生成）；端到端含冷启动实测约 0.8s 检索 + 2.7s 生成（见 `python main.py ask` 输出的 `timings_ms`）。
- **波动**：embedding 服务端数值不是逐位确定的，同一配置重跑 hit@1 会有 ±1 条问题（约 ±0.007）的波动，延迟受网络影响更明显。
- **答案质量**：这一张必须人工标注（`data/results/annotation_sheet.csv` 填 3 列）。判定标准是"答案有没有被给出的参考片段支撑"，不去比对模型外的标准答案——否则会把"我心里的正确答案"带进指标。

## 说明

- 语料由 `scripts/gen_demo_corpus.py` 生成，品牌与型号均为虚构，不含真实企业数据。
- `.env` 已被 `.gitignore` 排除，请不要把 API Key 提交上来。
- 索引与切片明细（`data/index`、`data/chunks/*.jsonl`）不入库，克隆后按上面的命令重建即可；`data/results` 下的评测报告入库，方便直接对照。