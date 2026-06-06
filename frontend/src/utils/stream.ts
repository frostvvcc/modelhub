/**
 * SSE 流式对话工具
 *
 * 通过 fetch + ReadableStream 接收 SSE 事件，
 * 实现逐 token 渲染和 Agent 过程可视化。
 */

import { useUserStore } from '../stores/user'

import type { SourceCitation, TraceInfo, MemoryStats, ToolCallRecord } from '../types/chat'

export interface StateChangePayload {
  state: string
  label: string
  tool_count?: number
}

export interface DonePayload {
  content: string
  iterations?: number
  rag_result?: Record<string, unknown> | null
  state_machine?: Record<string, unknown>
  token_budget?: Record<string, unknown>
}

export interface SSEEvent {
  type: string
  data: Record<string, unknown>
}

export interface StreamCallbacks {
  onToken?: (content: string) => void
  onStateChange?: (state: string, label: string, meta?: StateChangePayload) => void
  onThinking?: (content: string, iteration?: number) => void
  onToolCall?: (tool: string, args: Record<string, unknown>, callId: string, iteration?: number) => void
  onToolResult?: (tool: string, result: Record<string, unknown>, callId: string, latencyMs: number) => void
  onSources?: (sources: SourceCitation[]) => void
  onMetadata?: (metadata: Record<string, unknown>) => void
  onMemory?: (stats: MemoryStats) => void
  onConversation?: (info: { conversation_id: number | string; conversation_name?: string }) => void
  onTrace?: (trace: TraceInfo) => void
  onError?: (message: string) => void
  onDone?: (data: DonePayload) => void
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

  let eventType = ''
  let eventData = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

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
  const d = event.data
  switch (event.type) {
    case 'token':
      callbacks.onToken?.(String(d.content ?? ''))
      break
    case 'state_change':
      callbacks.onStateChange?.(
        String(d.state ?? ''),
        String(d.label ?? ''),
        d as unknown as StateChangePayload,
      )
      break
    case 'thinking':
      callbacks.onThinking?.(String(d.content ?? ''), d.iteration as number | undefined)
      break
    case 'tool_call':
      callbacks.onToolCall?.(
        String(d.tool ?? ''),
        (d.args ?? {}) as Record<string, unknown>,
        String(d.call_id ?? ''),
        d.iteration as number | undefined,
      )
      break
    case 'tool_result':
      callbacks.onToolResult?.(
        String(d.tool ?? ''),
        (d.result ?? {}) as Record<string, unknown>,
        String(d.call_id ?? ''),
        Number(d.latency_ms ?? 0),
      )
      break
    case 'sources':
      callbacks.onSources?.(d as unknown as SourceCitation[])
      break
    case 'metadata':
      callbacks.onMetadata?.(d)
      break
    case 'memory':
      callbacks.onMemory?.(d as unknown as MemoryStats)
      break
    case 'conversation':
      callbacks.onConversation?.(d as unknown as { conversation_id: number | string; conversation_name?: string })
      break
    case 'trace':
      callbacks.onTrace?.(d as unknown as TraceInfo)
      break
    case 'done':
      callbacks.onDone?.(d as unknown as DonePayload)
      break
    case 'error':
      callbacks.onError?.(String(d.message ?? '未知错误'))
      break
  }
}
