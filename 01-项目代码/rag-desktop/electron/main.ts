/**
 * ============ 主进程（Main Process）============
 *
 * 主进程是 Electron 应用的"后台"：它拥有完整的 Node.js 能力，
 * 负责创建窗口、管理应用生命周期，以及——本项目里最重要的一件事——
 * 替界面去请求 Python 那边的 RAG 后端。
 *
 * 为什么不让界面自己发请求？见 README.md「为什么不让渲染层直接 fetch 后端」
 */
import { app, BrowserWindow, ipcMain } from 'electron'
import * as path from 'path'
import * as fs from 'fs'

// npm run dev 时会传入 --dev-server=http://127.0.0.1:5173
// 有它 = 开发模式（加载 Vite 开发服务器）；没有 = 生产模式（加载打包后的 HTML）
const devServerArg = process.argv.find((arg) => arg.startsWith('--dev-server='))
const DEV_SERVER_URL = devServerArg ? devServerArg.split('=')[1] : undefined

// 后端 RAG 服务地址（rag-agent-platform 里 python main.py serve 起的服务）
const API_BASE = process.env.RAG_API_BASE ?? 'http://127.0.0.1:8000'

/** 从命令行参数里取值，例如 --demo-question=xxx */
function argValue(prefix: string): string | undefined {
  const hit = process.argv.find((arg) => arg.startsWith(prefix))
  return hit ? hit.slice(prefix.length) : undefined
}

/** 演示模式下的日志（Windows 上 Electron 是 GUI 程序，控制台看不到输出） */
function log(message: string): void {
  try {
    fs.appendFileSync(path.join(process.cwd(), 'demo.log'), `${new Date().toISOString()} ${message}\n`)
  } catch {
    /* 记录日志失败不影响主流程 */
  }
}

// 自动演示/截图模式（用于生成演示材料）：
//   electron . --demo-question="问题" --demo-screenshot="输出.png"
const DEMO_QUESTION = argValue('--demo-question=')
const DEMO_SCREENSHOT = argValue('--demo-screenshot=')
log(`启动: argv=${JSON.stringify(process.argv)}`)
log(`DEMO_QUESTION=${DEMO_QUESTION ?? '(未设置)'} DEMO_SCREENSHOT=${DEMO_SCREENSHOT ?? '(未设置)'}`)

function createWindow(): void {
  const win = new BrowserWindow({
    width: 1040,
    height: 760,
    minWidth: 720,
    minHeight: 520,
    title: 'RAG 桌面助手',
    backgroundColor: '#f6f7f9',
    webPreferences: {
      // 预加载脚本：渲染进程与主进程之间唯一的"通道"
      preload: path.join(__dirname, 'preload.js'),
      // 下面两行是 Electron 的安全底线：
      contextIsolation: true, // 页面脚本与 preload 运行在隔离环境，不能互相篡改
      nodeIntegration: false, // 页面里拿不到 require / process，防止 XSS 后直接控制电脑
    },
  })

  if (DEV_SERVER_URL) {
    void win.loadURL(DEV_SERVER_URL)
    win.webContents.openDevTools({ mode: 'detach' }) // 开发时自动打开控制台，方便看日志
  } else {
    void win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'))
  }

  // 演示模式：加载完成后自动提问 -> 等答案生成完 -> 截图 -> 退出
  win.webContents.once('did-finish-load', async () => {
    log('页面加载完成')
    if (!DEMO_SCREENSHOT) return
    try {
      if (DEMO_QUESTION) {
        log('自动提问中…')
        win.webContents.send('demo:ask', DEMO_QUESTION)
        await new Promise((resolve) => setTimeout(resolve, 20000))
      }
      log('开始截图…')
      const image = await win.webContents.capturePage()
      fs.writeFileSync(DEMO_SCREENSHOT, image.toPNG())
      log(`截图已保存: ${DEMO_SCREENSHOT}`)
    } catch (error) {
      log(`截图失败: ${String(error)}`)
    } finally {
      app.quit()
    }
  })
}

/* ---------------- IPC 通道 1：健康检查 ---------------- */
ipcMain.handle('rag:health', async () => {
  try {
    const resp = await fetch(`${API_BASE}/health`)
    if (!resp.ok) return { ok: false, message: `HTTP ${resp.status}` }
    return { ok: true, data: await resp.json() }
  } catch (error) {
    return { ok: false, message: (error as Error).message }
  }
})

/* ---------------- IPC 通道 2：一次性问答（非流式） ---------------- */
ipcMain.handle('rag:ask', async (_event, question: string) => {
  try {
    const resp = await fetch(`${API_BASE}/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    })
    if (!resp.ok) return { ok: false, message: `HTTP ${resp.status}` }
    return { ok: true, data: await resp.json() }
  } catch (error) {
    return { ok: false, message: (error as Error).message }
  }
})

/* ---------------- IPC 通道 3：流式问答（SSE，边生成边显示）----------------
 * 后端返回的是 SSE 文本流，格式长这样：
 *     data: {"type":"contexts","contexts":[...]}
 *
 *     data: {"type":"token","content":"请先检查"}
 *
 *     data: [DONE]
 * 我们要做的就是把每一段解析出来，再通过事件推回界面。
 */
ipcMain.on('rag:ask-stream', async (event, question: string) => {
  const send = (payload: Record<string, unknown>) => event.sender.send('rag:stream-event', payload)

  try {
    const resp = await fetch(`${API_BASE}/query/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    })
    if (!resp.ok || !resp.body) {
      send({ type: 'error', message: `HTTP ${resp.status}` })
      return
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''

    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      // SSE 用空行分隔每个事件
      const chunks = buffer.split('\n\n')
      buffer = chunks.pop() ?? '' // 最后一段可能不完整，留到下一轮
      for (const chunk of chunks) {
        const dataLine = chunk.split('\n').find((line) => line.startsWith('data:'))
        if (!dataLine) continue
        const payload = dataLine.slice(5).trim()
        if (payload === '[DONE]') continue
        try {
          send(JSON.parse(payload) as Record<string, unknown>)
        } catch {
          // 无法解析的行直接跳过，不影响整体流程
        }
      }
    }
    send({ type: 'finished' })
  } catch (error) {
    send({ type: 'error', message: (error as Error).message })
  }
})

/* ---------------- 应用生命周期 ---------------- */
app.whenReady().then(() => {
  createWindow()
  // macOS 上点 Dock 图标时若没有窗口则重新创建
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
