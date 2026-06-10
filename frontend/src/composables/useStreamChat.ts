import { ref, nextTick } from 'vue'
import type { ChatMessage, QuoteInfo, ToolCallRecord } from '../types/chat'
import type { StreamCallbacks } from '../utils/stream'
import { streamChat, streamBotChat } from '../utils/stream'
import { rechat } from '../api/chat'
import { getCurrentTime } from '../utils/common'

export function useStreamChat() {
  const isGenerating = ref(false)
  const abortController = ref<AbortController | null>(null)

  const stopGenerating = (messages: ChatMessage[]) => {
    if (abortController.value) {
      abortController.value.abort()
      abortController.value = null
    }
    isGenerating.value = false
    const lastMsg = messages[messages.length - 1]
    if (lastMsg && lastMsg.isStreaming) {
      lastMsg.isStreaming = false
    }
  }

  const createStreamCallbacks = (
    messages: ChatMessage[],
    msgIndex: number,
    opts: {
      triggerRender: () => void
      scrollToBottom: () => void
      onConversationUpdate?: (id: string, name?: string) => void
    },
  ): StreamCallbacks => ({
    onToken(content) {
      messages[msgIndex].content += content
      opts.triggerRender()
      opts.scrollToBottom()
    },
    onContentReset() {
      messages[msgIndex].content = ''
      messages[msgIndex].sources = undefined
      opts.triggerRender()
    },
    onStateChange(state, label) {
      messages[msgIndex].agentState = state
      messages[msgIndex].agentStateLabel = label
    },
    onThinking(content) {
      messages[msgIndex].thinkingContent = (messages[msgIndex].thinkingContent || '') + content
    },
    onToolCall(tool, args, callId) {
      if (!messages[msgIndex].toolCalls) messages[msgIndex].toolCalls = []
      messages[msgIndex].toolCalls!.push({ tool, args, callId, status: 'calling' })
      if (tool === 'knowledge_search') {
        if (!messages[msgIndex].retrievalProcess) messages[msgIndex].retrievalProcess = []
        messages[msgIndex].retrievalProcess!.push({
          step: 'query_rewrite',
          original_query: String((args as Record<string, unknown>).query || ''),
          retrieval_query: String((args as Record<string, unknown>).query || ''),
          is_reformulated: false,
        })
        opts.triggerRender()
      }
      opts.scrollToBottom()
    },
    onToolResult(tool, result, callId, latencyMs) {
      const tc = messages[msgIndex].toolCalls?.find(t => t.callId === callId)
      if (tc) {
        tc.result = result
        tc.latencyMs = latencyMs
        tc.status = result?.error ? 'error' : 'done'
      }
      if (tool === 'knowledge_search' && result) {
        if (!messages[msgIndex].retrievalProcess) messages[msgIndex].retrievalProcess = []
        const r = result as Record<string, unknown>
        messages[msgIndex].retrievalProcess!.push({
          step: 'retrieval_complete',
          total_results: r.count ?? r.total_results ?? 0,
          avg_similarity: r.avg_similarity ?? 0,
          used_knowledge_base: (r.count ?? r.total_results ?? 0) > 0,
          vector_db_ids: (r.vector_db_ids ?? []) as number[],
          retrieval_layers: (r.retrieval_layers ?? []) as string[],
          fallback_used: false,
        })
        opts.triggerRender()
      }
    },
    onSources(sources) {
      messages[msgIndex].sources = sources
    },
    onMetadata(metadata) {
      messages[msgIndex].grounded_ratio = metadata.grounded_ratio
      messages[msgIndex].grounded_level = metadata.grounded_level
      if (metadata.conversation_id) {
        opts.onConversationUpdate?.(String(metadata.conversation_id), metadata.conversation_name)
      }
    },
    onMemory(stats) {
      messages[msgIndex].memoryStats = stats
    },
    onConversation(info) {
      if (info.conversation_id) {
        opts.onConversationUpdate?.(String(info.conversation_id), info.conversation_name)
      }
    },
    onRetrievalInfo(info) {
      if (!messages[msgIndex].retrievalProcess) messages[msgIndex].retrievalProcess = []
      messages[msgIndex].retrievalProcess!.push(info as any)
      opts.triggerRender()
    },
    onTrace(trace) {
      messages[msgIndex].trace = trace
    },
    onDone() {
      messages[msgIndex].isStreaming = false
      messages[msgIndex].agentState = 'done'
      messages[msgIndex].agentStateLabel = '完成'
      isGenerating.value = false
      opts.triggerRender()
      opts.scrollToBottom()
    },
    onError(message) {
      if (!messages[msgIndex].content) {
        messages[msgIndex].content = message
      }
      messages[msgIndex].isStreaming = false
      messages[msgIndex].agentState = 'error'
      isGenerating.value = false
    },
  })

  const createEmptyAiMessage = (): ChatMessage => ({
    content: '',
    role: 'assistant',
    create_at: getCurrentTime(),
    isStreaming: true,
    agentState: 'planning',
    agentStateLabel: '分析问题中...',
    toolCalls: [],
  } as ChatMessage)

  const handleRegenerate = async (
    messages: ChatMessage[],
    index: number,
    conversationId: string,
    sendMessageFn: (query: string) => Promise<void>,
  ) => {
    const content = messages[index].content
    if (content.includes('正在') || isGenerating.value) return
    if (content === '请求失败，请稍后再试') {
      messages.pop()
      const lastQuery = messages[index - 1].content
      messages.pop()
      await sendMessageFn(lastQuery)
      return
    }
    const formData = new FormData()
    formData.append('conversation_id', conversationId)
    try {
      const response = await rechat(formData)
      messages[index] = response
    } catch {}
  }

  return {
    isGenerating,
    abortController,
    stopGenerating,
    createStreamCallbacks,
    createEmptyAiMessage,
    handleRegenerate,
  }
}
