/**
 * SSE 流式对话工具
 *
 * 通过 fetch + ReadableStream 接收 SSE 事件，
 * 实现逐 token 渲染和 Agent 过程可视化。
 */

import { useUserStore } from '../stores/user'

export interface SSEEvent {
  type: string
  data: any
}

export interface StreamCallbacks {
  onToken?: (content: string) => void
  onStateChange?: (state: string, label: string, meta?: any) => void
  onThinking?: (content: string) => void
  onToolCall?: (tool: string, args: any, callId: string) => void
  onToolResult?: (tool: string, result: any, callId: string, latencyMs: number) => void
  onSources?: (sources: any[]) => void
  onMetadata?: (metadata: any) => void
  onMemory?: (stats: any) => void
  onConversation?: (info: { conversation_id: number | string; conversation_name?: string }) => void
  onTrace?: (trace: any) => void
  onError?: (message: string) => void
  onDone?: (data: any) => void
}

function getBaseUrl(): string {
  return import.meta.env.VITE_API_BASE_URL || '/api'
}

/**
 * 发起流式对话请求
 */
export async function streamChat(
  formData: FormData,
  callbacks: StreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const userStore = useUserStore()
  const token = userStore.getToken()
  const baseUrl = getBaseUrl()

  const response = await fetch(`${baseUrl}/chat/stream`, {
    method: 'POST',
    headers: {
      Authorization: token ? `Bearer ${token}` : '',
    },
    body: formData,
    signal,
  })

  if (!response.ok) {
    const text = await response.text()
    callbacks.onError?.(text || `HTTP ${response.status}`)
    return
  }

  await processSSEStream(response, callbacks)
}

/**
 * 发起 Bot 流式对话请求
 */
export async function streamBotChat(
  botId: number,
  message: string,
  conversationId?: string,
  useAgent: boolean = true,
  callbacks?: StreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const userStore = useUserStore()
  const token = userStore.getToken()
  const baseUrl = getBaseUrl()

  const response = await fetch(`${baseUrl}/bots/${botId}/chat/stream`, {
    method: 'POST',
    headers: {
      Authorization: token ? `Bearer ${token}` : '',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      message,
      conversation_id: conversationId,
      use_agent: useAgent,
    }),
    signal,
  })

  if (!response.ok) {
    const text = await response.text()
    callbacks?.onError?.(text || `HTTP ${response.status}`)
    return
  }

  await processSSEStream(response, callbacks || {})
}

/**
 * 处理 SSE 流
 */
async function processSSEStream(
  response: Response,
  callbacks: StreamCallbacks,
): Promise<void> {
  const reader = response.body?.getReader()
  if (!reader) {
    callbacks.onError?.('无法读取响应流')
    return
  }

  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      let eventType = ''
      let eventData = ''

      for (const line of lines) {
        if (line.startsWith('event: ')) {
          eventType = line.slice(7).trim()
        } else if (line.startsWith('data: ')) {
          eventData = line.slice(6)
        } else if (line === '' && eventType && eventData) {
          try {
            const data = JSON.parse(eventData)
            dispatchEvent({ type: eventType, data }, callbacks)
          } catch {
            // 忽略解析错误
          }
          eventType = ''
          eventData = ''
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

function dispatchEvent(event: SSEEvent, callbacks: StreamCallbacks): void {
  switch (event.type) {
    case 'token':
      callbacks.onToken?.(event.data.content || '')
      break
    case 'state_change':
      callbacks.onStateChange?.(event.data.state, event.data.label, event.data)
      break
    case 'thinking':
      callbacks.onThinking?.(event.data.content || '')
      break
    case 'tool_call':
      callbacks.onToolCall?.(event.data.tool, event.data.args, event.data.call_id)
      break
    case 'tool_result':
      callbacks.onToolResult?.(event.data.tool, event.data.result, event.data.call_id, event.data.latency_ms || 0)
      break
    case 'sources':
      callbacks.onSources?.(event.data)
      break
    case 'metadata':
      callbacks.onMetadata?.(event.data)
      break
    case 'memory':
      callbacks.onMemory?.(event.data)
      break
    case 'conversation':
      callbacks.onConversation?.(event.data)
      break
    case 'trace':
      callbacks.onTrace?.(event.data)
      break
    case 'done':
      callbacks.onDone?.(event.data)
      break
    case 'error':
      callbacks.onError?.(event.data.message || '未知错误')
      break
  }
}
