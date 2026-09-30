/**
 * ============ 界面（渲染进程里的 React 组件）============
 *
 * 重要约束：这里**不能**直接读文件、不能 require、也不直接发 HTTP 请求，
 * 所有"越过边界"的动作都必须走 window.ragApi —— 这是 Electron 的安全设计。
 */
import { useEffect, useRef, useState } from 'react'

type Citation = {
  index: number
  source: string
  score: number
  snippet: string
}

type Message = {
  role: 'user' | 'assistant'
  text: string
  citations?: Citation[]
  pending?: boolean
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [backend, setBackend] = useState('正在检测后端…')
  const stopRef = useRef<null | (() => void)>(null)
  // 用 ref 记录"正在生成"：state 更新是异步的，光靠 busy 拦不住同一瞬间的重复提交
  const busyRef = useRef(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  // 页面打开时先问一句：Python 那边的服务起来了吗？
  useEffect(() => {
    window.ragApi.health().then((res) => {
      setBackend(
        res.ok
          ? `后端已连接（知识库片段 ${res.data?.chunks ?? '?'} 条）`
          : `后端未连接：${res.message}（请先运行 python main.py serve）`,
      )
    })
  }, [])

  // 有新消息时自动滚到底部
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  function sendQuestion(raw: string) {
    const question = raw.trim()
    if (!question || busyRef.current) return

    busyRef.current = true
    setInput('')
    setBusy(true)
    setMessages((prev) => [
      ...prev,
      { role: 'user', text: question },
      { role: 'assistant', text: '', pending: true },
    ])

    // 只更新最后一条消息的小工具函数
    const updateLast = (updater: (m: Message) => Message) => {
      setMessages((prev) =>
        prev.map((m, i) => (i === prev.length - 1 ? updater(m) : m)),
      )
    }

    // 【关键修复】开新流之前，先把上一条流的监听摘掉。
    // 以前这里只赋值、从不调用 stop，导致每问一次就多挂一个 IPC 监听，
    // 同一段 token 被重复追加——问第 3 次就重复 3 遍（"整整整机机机…"）。
    stopRef.current?.()

    let unsubscribe: (() => void) | null = null
    const finish = () => {
      unsubscribe?.()
      if (stopRef.current === unsubscribe) stopRef.current = null
      busyRef.current = false
      setBusy(false)
    }

    unsubscribe = window.ragApi.askStream(question, (event) => {
      if (event.type === 'contexts') {
        updateLast((m) => ({ ...m, citations: event.contexts as Citation[] }))
      } else if (event.type === 'token') {
        updateLast((m) => ({ ...m, text: m.text + String(event.content ?? '') }))
      } else if (event.type === 'done') {
        updateLast((m) => ({ ...m, pending: false }))
        finish()
      } else if (event.type === 'finished') {
        updateLast((m) => ({ ...m, pending: false }))
        finish()
      } else if (event.type === 'error') {
        updateLast((m) => ({
          ...m,
          text: `出错了：${event.message}`,
          pending: false,
        }))
        finish()
      }
    })
    stopRef.current = unsubscribe
  }

  function handleSend() {
    sendQuestion(input)
  }

  // 演示模式：主进程让界面自动提问（用于生成演示截图）
  useEffect(() => {
    const off = window.ragApi.onDemoAsk?.((question) => sendQuestion(question))
    // 卸载时取消订阅：StrictMode 在开发模式会把 effect 跑两遍，
    // 不清理的话演示模式会重复提问，答案就重复显示了
    return () => off?.()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 关窗口时把还挂着的流式监听摘干净
  useEffect(() => {
    return () => {
      stopRef.current?.()
      stopRef.current = null
    }
  }, [])

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>RAG 桌面助手</h1>
          <p className="sub">Electron + React + TypeScript + Vite · 对接自建 FastAPI RAG 服务</p>
        </div>
        <span className={`status ${backend.startsWith('后端已连接') ? 'ok' : 'bad'}`}>
          {backend}
        </span>
      </header>

      <main className="messages">
        {messages.length === 0 && (
          <div className="empty">
            <p>输入一个问题试试，例如：</p>
            <ul>
              <li>电视无法开机怎么办？</li>
              <li>整机保修期是多久？</li>
            </ul>
            <p className="tip">回答会流式显示，并附带检索到的来源片段。</p>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={`bubble ${m.role}`}>
            <div className="role">{m.role === 'user' ? '我' : '助手'}</div>
            <div className="text">
              {m.text || (m.pending ? <span className="dots">正在检索并生成…</span> : '')}
            </div>

            {m.citations && m.citations.length > 0 && (
              <div className="citations">
                <div className="citations-title">引用来源</div>
                {m.citations.map((c) => (
                  <div key={c.index} className="citation">
                    <span className="idx">[{c.index}]</span>
                    <span className="src">{c.source}</span>
                    <span className="score">score {Number(c.score).toFixed(3)}</span>
                    <div className="snippet">{c.snippet}…</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </main>

      <footer className="composer">
        <input
          value={input}
          placeholder="输入问题，按 Enter 发送"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleSend()
          }}
          disabled={busy}
        />
        <button onClick={handleSend} disabled={busy || !input.trim()}>
          {busy ? '生成中…' : '发送'}
        </button>
      </footer>
    </div>
  )
}
