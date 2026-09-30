# rag-desktop

对接自建 RAG 服务的桌面对话客户端：输入问题 → 后端流式返回 → 答案逐字显示，并展示引用来源。

> 客户端本身不含模型能力——检索与大模型都在后端 `rag-agent-platform`（FastAPI）里。

## 快速开始

**前置：先把后端跑起来**（另开一个终端）

```powershell
cd ../rag-agent-platform
python main.py serve        # 起在 http://127.0.0.1:8000，这个窗口别关
```

再启动桌面端：

```powershell
npm install                 # 只做一次
npm run dev                 # 编译主进程 + 起 Vite + 打开 Electron
```

**成功的样子**：弹出窗口，标题 `RAG 桌面助手`，右上角绿色标签"后端已连接（知识库片段 1302 条）"；
在底部输入 `电视无法开机怎么办` 回车，答案会**逐字出现**，下方渲染引用来源卡片。

右上角若是红色"后端未连接"，说明后端的 `serve` 没起来。

## 脚本

| 命令 | 作用 |
|---|---|
| `npm run dev` | 开发模式（Vite 热更新 + Electron） |
| `npm run build` | 编译主进程（tsc）+ 打包渲染层（Vite）→ `dist-electron/`、`dist/` |
| `npm start` | 用生产构建启动（不依赖 Vite dev server） |
| `npm run dist` | 打 Windows 安装包（需先 `npm install -D electron-builder`，产物在 `release/`） |

## 目录结构

| 文件 | 作用 |
|---|---|
| `electron/main.ts` | 主进程：开窗口、请求后端、解析 SSE、IPC 通道 |
| `electron/preload.ts` | 预加载：用 `contextBridge` 把最小接口暴露成 `window.ragApi` |
| `src/App.tsx` | 渲染层：React 组件（消息列表、流式增量渲染、引用卡片） |
| `src/styles.css` | 样式（配色、间距、圆角） |
| `src/main.tsx` | React 入口 |
| `vite.config.ts` | Vite 配置（开发端口 5173；`base: './'` 保证打包后 `file://` 能加载资源） |

## 进程模型与安全边界

Electron 分三层，权限依次收窄：

| 角色 | 文件 | 能力 |
|---|---|---|
| 主进程 | `electron/main.ts` | 完整 Node 能力：开窗口、发网络请求 |
| 渲染进程 | `src/App.tsx` | 只有界面与交互，没有系统权限 |
| 预加载 | `electron/preload.ts` | 中间层：把受控能力暴露给界面 |

两个关键配置（在 `main.ts`）：

- `contextIsolation: true` —— 页面脚本与 preload 隔离，互相无法篡改；
- `nodeIntegration: false` —— 页面里拿不到 `require` / `process`。

界面不做任何越权操作，只通过 `window.ragApi` 申请能力；这样即使页面被注入脚本，也拿不到文件系统与系统 API。

## 一次提问的数据流

```
输入框回车
  → App.tsx 调 window.ragApi.askStream(问题, 回调)     （preload 暴露的最小接口）
  → ipcRenderer.send('rag:ask-stream', 问题)
  → main.ts: ipcMain.on('rag:ask-stream') → fetch 后端 /query/stream
  → 后端以 SSE 逐段返回：data: {"type":"contexts",...} / {"type":"token","content":"请"} / [DONE]
  → main.ts 用 TextDecoder 解析，按空行切事件 → event.sender.send('rag:stream-event', 数据)
  → preload 回调触发 → App.tsx 把 token 追加到当前消息（所以是逐字显示）
  → 收到 done → 去掉"生成中"，渲染引用来源卡片
```

两种 IPC 用法：

| 用法 | 场景 |
|---|---|
| `invoke` / `handle` | 一问一答，能拿到返回值（健康检查、非流式问答） |
| `send` / `on` | 持续推送，没有返回值（流式 token） |

**两个实现要点**：

- SSE 的最后一段可能不完整（粘包），每轮要把不完整部分留在缓冲区，等下一批数据拼上再解析；
- 流式监听要在本轮结束时取消订阅，否则问第 N 次会把同一段 token 追加 N 次。

## 为什么不让渲染层直接 fetch 后端

技术上可行（Chrome 里就能这么写），但把请求放在主进程有三个好处：

1. 后端地址与鉴权集中管理，换环境只改一处；
2. 不受渲染层的跨域与安全策略限制；
3. 以后要加本地能力（读文件、托盘、自动更新）不用重构通信层。

## 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 右上角红色"后端未连接" | 后端 `serve` 没起 | 到 `rag-agent-platform` 执行 `python main.py serve` |
| 窗口一片空白 | Vite 还没就绪 | 等几秒；看终端有没有 `ready in xxx ms` |
| 打包后白屏 | 资源路径写成绝对路径，`file://` 下失效 | 保持 `vite.config.ts` 里的 `base: './'` |
| 答案逐字重复好几遍 | 流式监听没解绑 | 已在 `App.tsx` 修：开新流前先取消上一个订阅 |
| `npm run dist` 提示找不到 electron-builder | 打包工具没装 | `npm install -D electron-builder` |
| 提问后没有反应 | 后端报错或模型额度用尽 | 看后端那个终端的日志 |