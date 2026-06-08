import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ChatMessage, Conversation, ToolCallRecord, SourceCitation, TraceInfo, MemoryStats } from '../types/chat'
import { streamBotChat, type StreamCallbacks } from '../utils/stream'
import { getCurrentTime } from '../utils/common'
import type { BotResponse } from '../api/bot'

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const conversationId = ref('')
  const modelConfigId = ref('')
  const configName = ref('')
  const conversationInfo = ref<Conversation>({
    id: 0, name: '', model_config_id: 0, messages: [],
    chat_history: 10, create_at: '', type: 0, update_at: '',
  })

  const botId = ref(0)
  const currentBot = ref<BotResponse | null>(null)
  const botConversationId = ref<string | undefined>()
  const useAgentMode = ref(true)

  const isGenerating = ref(false)
  const abortController = ref<AbortController | null>(null)

  let renderTimer: ReturnType<typeof setTimeout> | null = null
  const renderKey = ref(0)
  const triggerRender = () => {
    if (renderTimer) return
    renderTimer = setTimeout(() => {
      renderKey.value++
      renderTimer = null
    }, 50)
  }

  const isBotMode = computed(() => botId.value > 0 && !!currentBot.value)

  const stopGenerating = () => {
    if (abortController.value) {
      abortController.value.abort()
      abortController.value = null
    }
    isGenerating.value = false
    const lastMsg = messages.value[messages.value.length - 1]
    if (lastMsg && lastMsg.isStreaming) {
      lastMsg.isStreaming = false
    }
  }

  const appendUserMessage = (content: string, quote?: { content: string; role: string }) => {
    const msg: ChatMessage = {
      content,
      role: 'user',
      create_at: getCurrentTime(),
    } as ChatMessage
    if (quote) (msg as Record<string, unknown>).quote = quote
    messages.value.push(msg)
    renderKey.value++
  }

  const appendAssistantPlaceholder = (): number => {
    const msg: ChatMessage = {
      content: '',
      role: 'assistant',
      create_at: getCurrentTime(),
      isStreaming: true,
      streamStartTime: Date.now(),
      streamTokenCount: 0,
      agentState: 'planning',
      agentStateLabel: '分析问题中...',
      toolCalls: [],
    } as ChatMessage
    messages.value.push(msg)
    renderKey.value++
    return messages.value.length - 1
  }

  const buildCallbacks = (msgIndex: number, routerReplace?: (query: Record<string, string>) => void): StreamCallbacks => ({
    onToken(content) {
      messages.value[msgIndex].content += content
      messages.value[msgIndex].streamTokenCount = (messages.value[msgIndex].streamTokenCount || 0) + Math.ceil(content.length / 1.5)
      triggerRender()
    },
    onStateChange(state, label) {
      messages.value[msgIndex].agentState = state
      messages.value[msgIndex].agentStateLabel = label
    },
    onThinking(content) {
      messages.value[msgIndex].thinkingContent = (messages.value[msgIndex].thinkingContent || '') + content
      messages.value[msgIndex].streamTokenCount = (messages.value[msgIndex].streamTokenCount || 0) + Math.ceil(content.length / 1.5)
      triggerRender()
    },
    onToolCall(tool, args, callId) {
      if (!messages.value[msgIndex].toolCalls) messages.value[msgIndex].toolCalls = []
      messages.value[msgIndex].toolCalls!.push({ tool, args, callId, status: 'calling' } as ToolCallRecord)
      if (tool === 'knowledge_search') {
        if (!messages.value[msgIndex].retrievalProcess) messages.value[msgIndex].retrievalProcess = []
        messages.value[msgIndex].retrievalProcess!.push({
          step: 'query_rewrite',
          original_query: String((args as Record<string, unknown>).query || ''),
          retrieval_query: String((args as Record<string, unknown>).query || ''),
          is_reformulated: false,
        })
        triggerRender()
      }
    },
    onToolResult(tool, result, callId, latencyMs) {
      const tc = messages.value[msgIndex].toolCalls?.find(t => t.callId === callId)
      if (tc) {
        tc.result = result
        tc.latencyMs = latencyMs
        tc.status = result?.error ? 'error' : 'done'
      }
      const resultStr = JSON.stringify(result || '')
      messages.value[msgIndex].streamTokenCount = (messages.value[msgIndex].streamTokenCount || 0) + Math.ceil(resultStr.length / 1.5)
      if (tool === 'knowledge_search' && result) {
        if (!messages.value[msgIndex].retrievalProcess) messages.value[msgIndex].retrievalProcess = []
        const r = result as Record<string, unknown>
        const hasResultDbs = (r.has_result_db_ids ?? []) as number[]
        const queriedDbs = (r.queried_vector_db_ids ?? r.vector_db_ids ?? []) as number[]
        messages.value[msgIndex].retrievalProcess!.push({
          step: 'retrieval_complete',
          total_results: (r.count ?? r.total_results ?? 0) as number,
          total_found: (r.total_found ?? r.count ?? 0) as number,
          avg_similarity: (r.avg_similarity ?? 0) as number,
          used_knowledge_base: ((r.count ?? r.total_results ?? 0) as number) > 0,
          vector_db_ids: hasResultDbs.length > 0 ? hasResultDbs : queriedDbs,
          queried_db_count: queriedDbs.length,
          retrieval_layers: (r.retrieval_layers ?? []) as string[],
          fallback_used: false,
        })
        triggerRender()
      }
    },
    onSources(sources) {
      messages.value[msgIndex].sources = sources
    },
    onMetadata(metadata) {
      messages.value[msgIndex].grounded_ratio = metadata.grounded_ratio as number | undefined
      messages.value[msgIndex].grounded_level = metadata.grounded_level as string | undefined
      if (metadata.conversation_id) {
        conversationId.value = String(metadata.conversation_id)
        conversationInfo.value.id = metadata.conversation_id as number
        if (metadata.conversation_name) conversationInfo.value.name = metadata.conversation_name as string
        routerReplace?.({
          conversation_id: conversationId.value,
          model_config_id: modelConfigId.value,
          config_name: configName.value,
        })
      }
    },
    onMemory(stats) {
      messages.value[msgIndex].memoryStats = stats
    },
    onConversation(info) {
      if (info.conversation_id) {
        conversationId.value = String(info.conversation_id)
        conversationInfo.value.id = Number(info.conversation_id)
        if (info.conversation_name) conversationInfo.value.name = info.conversation_name
        if (isBotMode.value) botConversationId.value = conversationId.value
        routerReplace?.({
          conversation_id: conversationId.value,
          model_config_id: modelConfigId.value,
          config_name: configName.value,
        })
      }
    },
    onRetrievalInfo(info) {
      if (!messages.value[msgIndex].retrievalProcess) messages.value[msgIndex].retrievalProcess = []
      messages.value[msgIndex].retrievalProcess!.push(info as any)
      triggerRender()
    },
    onTrace(trace) {
      messages.value[msgIndex].trace = trace
    },
    onTokenUsage(usage) {
      const apiCount = usage.completion_tokens || 0
      const current = messages.value[msgIndex].streamTokenCount || 0
      if (apiCount > current) {
        messages.value[msgIndex].streamTokenCount = apiCount
      }
      triggerRender()
    },
    onDone() {
      messages.value[msgIndex].isStreaming = false
      messages.value[msgIndex].agentState = 'done'
      messages.value[msgIndex].agentStateLabel = '完成'
      isGenerating.value = false
      renderKey.value++
      setTimeout(() => { renderKey.value++ }, 100)
    },
    onError(message) {
      if (!messages.value[msgIndex].content) {
        messages.value[msgIndex].content = message
      }
      messages.value[msgIndex].isStreaming = false
      messages.value[msgIndex].agentState = 'error'
      isGenerating.value = false
    },
  })

  const sendMessage = async (
    query: string,
    files: File[],
    quote?: { content: string; role: string },
    routerReplace?: (query: Record<string, string>) => void,
  ) => {
    if (query.trim() === '' && files.length === 0) return
    if (query.trim() === '' && files.length > 0) query = '请总结并回答我上传的附件内容。'

    const attachmentText = files.length ? `\n\n附件：${files.map(f => f.name).join('、')}` : ''
    appendUserMessage(`${query}${attachmentText}`, quote ?? undefined)

    const msgIndex = appendAssistantPlaceholder()
    isGenerating.value = true
    abortController.value = new AbortController()

    const callbacks = buildCallbacks(msgIndex, routerReplace)

    try {
      if (!currentBot.value) {
        callbacks.onError?.('未选择数字助理，请先选择一个 Bot')
        isGenerating.value = false
        return
      }

      const formData = new FormData()
      formData.append('message', query)
      formData.append('use_agent', String(useAgentMode.value))
      if (botConversationId.value) formData.append('conversation_id', botConversationId.value)
      files.forEach(file => formData.append('files', file))

      await streamBotChat(
        currentBot.value.id,
        formData,
        callbacks,
        abortController.value.signal,
      )
      if (conversationId.value) botConversationId.value = conversationId.value
    } catch (e: unknown) {
      if ((e as Error).name === 'AbortError') return
      const errMsg = typeof e === 'string' ? e : (e as Error)?.message || '请求失败，请稍后再试'
      messages.value[msgIndex].content = errMsg
      messages.value[msgIndex].isStreaming = false
      isGenerating.value = false
    }
  }

  const reset = () => {
    stopGenerating()
    messages.value = []
    conversationId.value = ''
    modelConfigId.value = ''
    configName.value = ''
    botId.value = 0
    currentBot.value = null
    botConversationId.value = undefined
    conversationInfo.value = {
      id: 0, name: '', model_config_id: 0, messages: [],
      chat_history: 10, create_at: '', type: 0, update_at: '',
    }
  }

  return {
    messages,
    conversationId,
    modelConfigId,
    configName,
    conversationInfo,
    botId,
    currentBot,
    botConversationId,
    useAgentMode,
    isGenerating,
    isBotMode,
    renderKey,
    stopGenerating,
    sendMessage,
    reset,
    appendAssistantPlaceholder,
    triggerRender,
  }
})
