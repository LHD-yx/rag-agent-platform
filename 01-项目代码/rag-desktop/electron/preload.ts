/**
 * ============ 预加载脚本（Preload）============
 *
 * 它运行在渲染进程里，但拥有受限的 Node 能力。
 * 它的唯一职责是"开一扇小窗"：把主进程的能力，用最小、最明确的接口暴露给界面。
 *
 * 关键点（高频问题）：
 *   1. 只能用 contextBridge 暴露函数，不能把 ipcRenderer 整个丢给页面；
 *   2. 暴露的接口越窄越安全——页面只能做我们允许它做的事。
 */
import { contextBridge, ipcRenderer, IpcRendererEvent } from 'electron'

/** 主进程推回来的流式事件 */
export interface RagStreamEvent {
  type: 'contexts' | 'token' | 'done' | 'finished' | 'error' | string
  [key: string]: unknown
}

/** 当前挂着的流式监听：同一时刻只允许有一个，防止 token 被重复追加 */
let activeStreamListener: ((event: IpcRendererEvent, payload: RagStreamEvent) => void) | null = null

const api = {
  /** 后端是否在线 */
  health: () => ipcRenderer.invoke('rag:health'),

  /** 一次性问答（非流式），返回完整结果 */
  ask: (question: string) => ipcRenderer.invoke('rag:ask', question),

  /**
   * 流式问答：每收到一段就回调一次 onEvent，返回一个"取消订阅"的函数。
   * 用法：const stop = window.ragApi.askStream('问题', (e) => console.log(e))
   */
  askStream: (question: string, onEvent: (event: RagStreamEvent) => void) => {
    // 保险：万一上一次的监听没被摘干净，先摘掉再挂新的。
    // 否则每问一次就多挂一个监听，界面会把同一段 token 重复追加（问第 3 次就重复 3 遍）。
    if (activeStreamListener) {
      ipcRenderer.removeListener('rag:stream-event', activeStreamListener)
      activeStreamListener = null
    }
    const listener = (_event: IpcRendererEvent, payload: RagStreamEvent) => onEvent(payload)
    activeStreamListener = listener
    ipcRenderer.on('rag:stream-event', listener)
    ipcRenderer.send('rag:ask-stream', question)
    return () => {
      ipcRenderer.removeListener('rag:stream-event', listener)
      if (activeStreamListener === listener) activeStreamListener = null
    }
  },

  /** 演示模式：主进程要求界面自动提一个问题（截图用） */
  onDemoAsk: (callback: (question: string) => void) => {
    // 同样返回"取消订阅"函数：StrictMode 下 effect 会跑两遍，不清理会重复提问
    const listener = (_event: IpcRendererEvent, question: string) => callback(question)
    ipcRenderer.on('demo:ask', listener)
    return () => ipcRenderer.removeListener('demo:ask', listener)
  },
}

// 把上面的接口挂到页面里的 window.ragApi 上
contextBridge.exposeInMainWorld('ragApi', api)
