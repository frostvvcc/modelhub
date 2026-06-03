import { ref, computed } from 'vue'
import type { VectorDbBase } from '../types/vectorDb'
import { fetchOwnVectors } from '../api/vectorDb'

export function useKnowledgeBase() {
  const allKnowledgeBases = ref<VectorDbBase[]>([])
  const selectedKbIds = ref<number[]>([])
  const kbPanelOpen = ref(false)
  const expandedScope = ref<string | null>(null)

  const scopeGroupLabels: Record<string, string> = { shared: '组织共享', private: '私有' }

  const getKbVisibilityLabel = (kb: VectorDbBase) => {
    if (!kb.organization_id) return '私有'
    if (kb.org_name) return kb.org_name
    return '组织'
  }

  const kbGrouped = computed(() => {
    const groups: Record<string, VectorDbBase[]> = {}
    for (const kb of allKnowledgeBases.value) {
      const key = kb.organization_id ? 'shared' : 'private'
      if (!groups[key]) groups[key] = []
      groups[key].push(kb)
    }
    return groups
  })

  const toggleScope = (scope: string) => {
    expandedScope.value = expandedScope.value === scope ? null : scope
  }

  const toggleKb = (id: number) => {
    const idx = selectedKbIds.value.indexOf(id)
    if (idx !== -1) selectedKbIds.value.splice(idx, 1)
    else selectedKbIds.value.push(id)
  }

  const selectedKbNames = computed(() =>
    allKnowledgeBases.value.filter(kb => selectedKbIds.value.includes(kb.id)).map(kb => kb.name),
  )

  const loadKnowledgeBases = async () => {
    try {
      allKnowledgeBases.value = await fetchOwnVectors()
    } catch (e) {
      console.error('加载知识库列表失败:', e)
    }
  }

  return {
    allKnowledgeBases,
    selectedKbIds,
    kbPanelOpen,
    expandedScope,
    scopeGroupLabels,
    getKbVisibilityLabel,
    kbGrouped,
    toggleScope,
    toggleKb,
    selectedKbNames,
    loadKnowledgeBases,
  }
}

export function useFileUpload() {
  const selectedFiles = ref<File[]>([])
  const fileInputRef = ref<HTMLInputElement | null>(null)

  const hasFiles = computed(() => selectedFiles.value.length > 0)

  const openFilePicker = () => { fileInputRef.value?.click() }

  const handleFileSelected = (event: Event) => {
    const input = event.target as HTMLInputElement
    const files = Array.from(input.files || [])
    const existingKeys = new Set(
      selectedFiles.value.map(file => `${file.name}-${file.size}-${file.lastModified}`),
    )
    files.forEach(file => {
      const key = `${file.name}-${file.size}-${file.lastModified}`
      if (!existingKeys.has(key)) {
        selectedFiles.value.push(file)
        existingKeys.add(key)
      }
    })
    input.value = ''
  }

  const removeSelectedFile = (index: number) => { selectedFiles.value.splice(index, 1) }

  const formatFileSize = (size: number) => {
    if (size < 1024) return `${size} B`
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
    return `${(size / 1024 / 1024).toFixed(1)} MB`
  }

  return {
    selectedFiles,
    fileInputRef,
    hasFiles,
    openFilePicker,
    handleFileSelected,
    removeSelectedFile,
    formatFileSize,
  }
}

export function useChatUI() {
  const expandedSources = ref<number[]>([])
  const expandedSourceContents = ref<string[]>([])
  const expandedTraces = ref<number[]>([])
  const copiedIndex = ref<number | null>(null)

  const toggleSources = (index: number) => {
    const i = expandedSources.value.indexOf(index)
    if (i !== -1) expandedSources.value.splice(i, 1)
    else expandedSources.value.push(index)
  }

  const getSourceKey = (messageIndex: number, sourceIndex: number) => `${messageIndex}-${sourceIndex}`

  const toggleSourceContent = (messageIndex: number, sourceIndex: number) => {
    const key = getSourceKey(messageIndex, sourceIndex)
    const i = expandedSourceContents.value.indexOf(key)
    if (i !== -1) expandedSourceContents.value.splice(i, 1)
    else expandedSourceContents.value.push(key)
  }

  const isSourceContentExpanded = (messageIndex: number, sourceIndex: number) =>
    expandedSourceContents.value.includes(getSourceKey(messageIndex, sourceIndex))

  const toggleTrace = (index: number) => {
    const i = expandedTraces.value.indexOf(index)
    if (i !== -1) expandedTraces.value.splice(i, 1)
    else expandedTraces.value.push(index)
  }

  const handleCopyMessage = (content: string, index?: number) => {
    navigator.clipboard.writeText(content)
    if (index !== undefined) {
      copiedIndex.value = index
      setTimeout(() => { copiedIndex.value = null }, 1500)
    }
  }

  const getRetrievalMethodLabel = (method?: string) => {
    const labels: Record<string, string> = { vector: '语义检索', bm25: '关键词检索', hybrid: '混合检索' }
    return method ? labels[method] || method : '检索'
  }

  const formatPercent = (value?: number) => `${(((value || 0) * 100)).toFixed(1)}%`

  const getConfidenceClass = (label?: string) => {
    if (label === '高') return 'confidence-high'
    if (label === '中') return 'confidence-medium'
    if (label === '低') return 'confidence-low'
    return 'confidence-weak'
  }

  const getToolLabel = (tool: string) => {
    const labels: Record<string, string> = {
      knowledge_search: '知识库检索',
      database_query: '数据库查询',
      calculator: '计算器',
      datetime_info: '日期时间',
      topic_analysis: '话题分析',
    }
    return labels[tool] || tool
  }

  const getStateIcon = (state?: string) => {
    const icons: Record<string, string> = {
      planning: '🔍', tool_calling: '🔧', reflecting: '💭', responding: '✍️', done: '✅', error: '❌',
    }
    return icons[state || ''] || '⏳'
  }

  return {
    expandedSources,
    expandedSourceContents,
    expandedTraces,
    copiedIndex,
    toggleSources,
    toggleSourceContent,
    isSourceContentExpanded,
    toggleTrace,
    handleCopyMessage,
    getRetrievalMethodLabel,
    formatPercent,
    getConfidenceClass,
    getToolLabel,
    getStateIcon,
  }
}
