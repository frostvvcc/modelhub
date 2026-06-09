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
  onThinking?: (content: string) => void
  onToolCall?: (tool: string, args: Record<string, unknown>, callId: string) => void
  onToolResult?: (tool: string, result: Record<string, unknown>, callId: string, latencyMs: number) => void
  onSources?: (sources: SourceCitation[]) => void
  onMetadata?: (metadata: Record<string, unknown>) => void
  onMemory?: (stats: MemoryStats) => void
  onConversation?: (info: { conversation_id: number | string; conversation_name?: string }) => void
  onRetrievalInfo?: (info: Record<string, unknown>) => void
  onAttachmentContents?: (contents: { filename: string; content: string; truncated: boolean; total_chars: number }[]) => void
  onTrace?: (trace: TraceInfo) => void
  onTokenUsage?: (usage: { total_tokens: number; prompt_tokens: number; completion_tokens: number }) => void
  onGroundingUpdate?: (data: { grounded_ratio: number; grounded_level: string; total_claims: number; supported_count: number }) => void
  onVerification?: (data: { grounded_ratio: number; total_claims?: number; supported_count?: number; crag_triggered?: boolean }) => void
  onOrchestratorPlan?: (data: { agents: string[]; reasoning: string }) => void
  onSubAgentDone?: (data: { agent: string; source_count?: number }) => void
  onWarning?: (message: string) => void
  onError?: (message: string) => void
  onDone?: (data: DonePayload) => void
}

function getBaseUrl(): string {
  return import.meta.env.VITE_API_BASE_URL || '/api'
}

/**
 * 发起 Bot 流式对话请求（FormData，支持文件上传）
 */
export async function streamBotChat(
  botId: number,
  formData: FormData,
  callbacks: StreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const userStore = useUserStore()
  const token = userStore.getToken()
  const baseUrl = getBaseUrl()

  const response = await fetch(`${baseUrl}/bots/${botId}/chat/stream`, {
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
 * 处理 SSE 流 — Frame-Budget-Aware Batching
 *
 * 在每一帧（16.6ms）内尽量多处理 SSE 事件，
 * 快超出帧预算时让出主线程给渲染管线，避免 UI 冻结。
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
  let normallyDone = false

  const FRAME_BUDGET_MS = 12 // 留 4.6ms 给 Layout + Paint

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) {
        normallyDone = true
        break
      }

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      const frameStart = performance.now()

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

        // 帧预算耗尽 → 让出主线程给渲染
        if (performance.now() - frameStart > FRAME_BUDGET_MS) {
          await new Promise<void>((r) => requestAnimationFrame(() => r()))
        }
      }
    }
  } catch (err) {
    callbacks.onError?.(err instanceof Error ? err.message : '连接异常断开')
  } finally {
    reader.releaseLock()
    if (!normallyDone) {
      callbacks.onError?.('连接异常断开')
    }
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
      callbacks.onThinking?.(String(d.content ?? ''))
      break
    case 'tool_call':
      callbacks.onToolCall?.(
        String(d.tool ?? ''),
        (d.args ?? {}) as Record<string, unknown>,
        String(d.call_id ?? ''),
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
    case 'retrieval_info':
      callbacks.onRetrievalInfo?.(d)
      break
    case 'attachment_contents':
      callbacks.onAttachmentContents?.(d as any)
      break
    case 'trace':
      callbacks.onTrace?.(d as unknown as TraceInfo)
      break
    case 'token_usage':
      callbacks.onTokenUsage?.(d as unknown as { total_tokens: number; prompt_tokens: number; completion_tokens: number })
      break
    case 'grounding_update':
      callbacks.onGroundingUpdate?.(d as any)
      break
    case 'verification':
      callbacks.onVerification?.(d as any)
      break
    case 'orchestrator_plan':
      callbacks.onOrchestratorPlan?.(d as any)
      break
    case 'sub_agent_done':
      callbacks.onSubAgentDone?.(d as any)
      break
    case 'warning':
      callbacks.onWarning?.(String(d.message ?? ''))
      break
    case 'done':
      callbacks.onDone?.(d as unknown as DonePayload)
      break
    case 'error':
      callbacks.onError?.(String(d.message ?? '未知错误'))
      break
  }
}
