/**
 * 给 TypeScript 补上"window.ragApi 长什么样"的类型声明。
 * 没有这个文件，TS 会报错：Property 'ragApi' does not exist on type 'Window'。
 */
export {}

export interface RagStreamEvent {
  type: string
  [key: string]: unknown
}

declare global {
  interface Window {
    ragApi: {
      health: () => Promise<{ ok: boolean; data?: any; message?: string }>
      ask: (question: string) => Promise<{ ok: boolean; data?: any; message?: string }>
      askStream: (
        question: string,
        onEvent: (event: RagStreamEvent) => void,
      ) => () => void
      onDemoAsk?: (callback: (question: string) => void) => (() => void) | void
    }
  }
}
