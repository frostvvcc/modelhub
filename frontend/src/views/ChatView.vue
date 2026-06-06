<!-- src/views/ChatView.vue -->
<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick, computed, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElInput, ElIcon, ElSlider, ElDrawer } from 'element-plus';
import { Promotion, DocumentCopy, ArrowDown, ArrowUp, UploadFilled, Close, Plus, Setting, CopyDocument, ChatRound, ArrowLeft } from '@element-plus/icons-vue';
import type { ChatMessage, QuoteInfo } from '../types/chat';
import { getMessages, rechat, setChatHistory } from '../api/chat';
import { getCurrentTime, getCurrentStatus } from '../utils/common';
import { fetchOwnConfigs, getModelConfig, getModelConfigs } from '../api/model';
import { fetchOwnVectors, DownloadFile } from '../api/vectorDb';
import { Refresh, FolderOpened, Download } from '@element-plus/icons-vue';
import { useUserStore } from '../stores/user';
import type { VectorDbBase } from '../types/vectorDb';
import { getBot } from '../api/bot';
import { useChatStore } from '../stores/chat';
import { storeToRefs } from 'pinia';

import { marked } from 'marked';
import DOMPurify from 'dompurify';
import hljs from 'highlight.js';
import 'highlight.js/styles/github.css';

const renderer = new marked.Renderer();

renderer.code = ({ text, lang }) => {
  const validLang = lang && hljs.getLanguage(lang) ? lang : 'plaintext';
  const highlighted = hljs.highlight(text, { language: validLang }).value;
  return `<pre class="code-block"><div class="code-header"><span class="code-lang">${validLang}</span><button class="code-copy-btn" onclick="navigator.clipboard.writeText(this.closest('pre').querySelector('code').textContent)">复制</button></div><code class="hljs ${validLang}">${highlighted}</code></pre>`;
};

marked.setOptions({
  renderer,
  breaks: true,
  gfm: true
});
const route = useRoute();
const router = useRouter();
const userStore = useUserStore();
const chatStore = useChatStore();
const { messages, conversationId, modelConfigId, configName, conversationInfo, botId, currentBot, botConversationId, useAgentMode, isGenerating, isBotMode, renderKey } = storeToRefs(chatStore);
const { stopGenerating } = chatStore;

const greetingTime = ref(getCurrentStatus());
const allConfigs = ref<Record<string, unknown>[]>([]);
const isConversationLocked = computed(() => !!conversationId.value);

// 设置面板
const settingsDrawerVisible = ref(false);

const loadAllConfigs = async () => {
  const configs: Record<string, unknown>[] = [];
  try { configs.push(...await fetchOwnConfigs()); } catch {}
  try { configs.push(...await getModelConfigs()); } catch {}
  allConfigs.value = configs.filter((config, index, all) =>
    config?.id && all.findIndex(item => item?.id === config.id) === index
  );
};

const handleConfigChange = (id: number) => {
  if (isConversationLocked.value) return;
  modelConfigId.value = String(id);
  const selected = allConfigs.value.find(c => c.id === id);
  if (selected) configName.value = selected.name;
};

const currentConfigName = computed(() => {
  if (configName.value) return configName.value;
  const found = allConfigs.value.find(c => String(c.id) === modelConfigId.value);
  return found?.name || '未选择模型';
});

// 知识库选择
const allKnowledgeBases = ref<VectorDbBase[]>([]);
const selectedKbIds = ref<number[]>([]);
const kbPanelOpen = ref(false);
const expandedScope = ref<string | null>(null);

const scopeGroupLabels: Record<string, string> = { shared: '组织共享', private: '私有' };
const getKbVisibilityLabel = (kb: VectorDbBase) => {
  if (!kb.organization_id) return '私有';
  if (kb.org_name) return kb.org_name;
  return '组织';
};
const kbGrouped = computed(() => {
  const groups: Record<string, VectorDbBase[]> = {};
  for (const kb of allKnowledgeBases.value) {
    const key = kb.organization_id ? 'shared' : 'private';
    if (!groups[key]) groups[key] = [];
    groups[key].push(kb);
  }
  return groups;
});
const toggleScope = (scope: string) => {
  expandedScope.value = expandedScope.value === scope ? null : scope;
};
const toggleKb = (id: number) => {
  const idx = selectedKbIds.value.indexOf(id);
  if (idx !== -1) selectedKbIds.value.splice(idx, 1);
  else selectedKbIds.value.push(id);
};
const selectedKbNames = computed(() =>
  allKnowledgeBases.value.filter(kb => selectedKbIds.value.includes(kb.id)).map(kb => kb.name)
);

const loadKnowledgeBases = async () => {
  try {
    allKnowledgeBases.value = await fetchOwnVectors();
  } catch (e) {
    console.error('加载知识库列表失败:', e);
  }
};

const userInput = ref('');
const selectedFiles = ref<File[]>([]);
const fileInputRef = ref<HTMLInputElement | null>(null);
const hasInput = computed(() => userInput.value.trim() !== '' || selectedFiles.value.length > 0);
const messageAreaRef = ref<HTMLElement | null>(null);

const expandedRetrieval = ref<Record<number, boolean>>({});
const toggleRetrieval = (index: number) => {
  expandedRetrieval.value[index] = !expandedRetrieval.value[index];
};
const expandedStepDetail = ref<Record<string, boolean>>({});
const toggleStepDetail = (msgIndex: number, stepIndex: number) => {
  const key = `${msgIndex}-${stepIndex}`;
  expandedStepDetail.value[key] = !expandedStepDetail.value[key];
};
const expandedSources = ref<number[]>([]);
const expandedSourceContents = ref<string[]>([]);
const toggleSources = (index: number) => {
  const i = expandedSources.value.indexOf(index);
  if (i !== -1) expandedSources.value.splice(i, 1);
  else expandedSources.value.push(index);
};
const getSourceKey = (messageIndex: number, sourceIndex: number) => `${messageIndex}-${sourceIndex}`;
const toggleSourceContent = (messageIndex: number, sourceIndex: number) => {
  const key = getSourceKey(messageIndex, sourceIndex);
  const i = expandedSourceContents.value.indexOf(key);
  if (i !== -1) expandedSourceContents.value.splice(i, 1);
  else expandedSourceContents.value.push(key);
};
const isSourceContentExpanded = (messageIndex: number, sourceIndex: number) =>
  expandedSourceContents.value.includes(getSourceKey(messageIndex, sourceIndex));

// trace 面板
const expandedTraces = ref<number[]>([]);
const toggleTrace = (index: number) => {
  const i = expandedTraces.value.indexOf(index);
  if (i !== -1) expandedTraces.value.splice(i, 1);
  else expandedTraces.value.push(index);
};

// 实时计时器
const elapsedNow = ref(Date.now());
let _elapsedTimer: ReturnType<typeof setInterval> | null = null;
const startElapsedTimer = () => {
  if (_elapsedTimer) return;
  _elapsedTimer = setInterval(() => { elapsedNow.value = Date.now(); }, 1000);
};
const stopElapsedTimer = () => {
  if (_elapsedTimer) { clearInterval(_elapsedTimer); _elapsedTimer = null; }
};
watch(isGenerating, (v) => { if (v) startElapsedTimer(); else stopElapsedTimer(); }, { immediate: true });
const formatElapsed = (startTime: number | undefined, isDone: boolean, trace?: { total_latency_ms?: number }) => {
  if (isDone && trace?.total_latency_ms) {
    const s = Math.round(trace.total_latency_ms / 1000);
    return s >= 60 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`;
  }
  if (!startTime) return '';
  const s = Math.max(0, Math.round((elapsedNow.value - startTime) / 1000));
  return s >= 60 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`;
};
const formatTokens = (msg: ChatMessage) => {
  if (msg.trace?.total_tokens) return `${msg.trace.total_tokens} tokens`;
  if (msg.streamTokenCount) return `~${msg.streamTokenCount} tokens`;
  return '';
};

const noModelConfigMessage = '当前没有可用的模型配置，请先到"模型配置"页面创建配置，或运行后端初始化脚本生成默认配置。';

const getRequestErrorMessage = (error: unknown) => {
  if (typeof error === 'string') return error;
  const data = error?.response?.data;
  if (typeof data?.message === 'string' && data.message.trim()) return data.message;
  if (typeof data?.detail === 'string' && data.detail.trim()) return data.detail;
  if (typeof error?.message === 'string' && error.message.trim()) return error.message;
  return '请求失败，请稍后再试';
};

const appendAssistantMessage = (content: string) => {
  messages.value.push({ content, role: 'assistant', create_at: getCurrentTime() } as ChatMessage);
  scrollToBottom();
};

const openFilePicker = () => { fileInputRef.value?.click(); };

const handleFileSelected = (event: Event) => {
  const input = event.target as HTMLInputElement;
  const files = Array.from(input.files || []);
  const existingKeys = new Set(selectedFiles.value.map(file => `${file.name}-${file.size}-${file.lastModified}`));
  files.forEach(file => {
    const key = `${file.name}-${file.size}-${file.lastModified}`;
    if (!existingKeys.has(key)) { selectedFiles.value.push(file); existingKeys.add(key); }
  });
  input.value = '';
};

const removeSelectedFile = (index: number) => { selectedFiles.value.splice(index, 1); };

const formatFileSize = (size: number) => {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
};

const getRetrievalMethodLabel = (method?: string) => {
  const labels: Record<string, string> = { vector: '语义检索', bm25: '关键词检索', hybrid: '混合检索' };
  return method ? labels[method] || method : '检索';
};

const formatPercent = (value?: number) => `${(((value || 0) * 100)).toFixed(1)}%`;

const getConfidenceClass = (label?: string) => {
  if (label === '高') return 'confidence-high';
  if (label === '中') return 'confidence-medium';
  if (label === '低') return 'confidence-low';
  return 'confidence-weak';
};

const getToolLabel = (tool: string) => {
  const labels: Record<string, string> = {
    knowledge_search: '知识库检索',
    database_query: '数据库查询',
    calculator: '计算器',
    datetime_info: '日期时间',
    topic_analysis: '话题分析',
  };
  return labels[tool] || tool;
};

const getStateIcon = (state?: string) => {
  const icons: Record<string, string> = {
    planning: '🔍', tool_calling: '🔧', reflecting: '💭', responding: '✍️', done: '✅', error: '❌',
  };
  return icons[state || ''] || '⏳';
};

const findAvailableModelConfig = async () => {
  const configs: Record<string, unknown>[] = [];
  try { configs.push(...await fetchOwnConfigs()); } catch {}
  try { configs.push(...await getModelConfigs()); } catch {}
  const uniqueConfigs = configs.filter((config, index, all) =>
    config?.id && all.findIndex(item => item?.id === config.id) === index
  );
  return uniqueConfigs[0] || null;
};

const ensureModelConfig = async (showMessage = true) => {
  if (modelConfigId.value && Number(modelConfigId.value) > 0) return true;
  const config = await findAvailableModelConfig();
  if (config) { modelConfigId.value = String(config.id); configName.value = config.name || configName.value; return true; }
  if (showMessage) appendAssistantMessage(noModelConfigMessage);
  return false;
};

const sendMessage = async (query: string) => {
  query = query.trim();
  if (!query && selectedFiles.value.length === 0) return;

  if (!isBotMode.value) {
    if (!(await ensureModelConfig())) return;
  }

  const pendingQuote = quotedMessage.value ? { ...quotedMessage.value } : undefined;
  quotedMessage.value = null;
  userInput.value = '';
  const filesToSend = [...selectedFiles.value];
  selectedFiles.value = [];

  const routerReplace = (q: Record<string, string>) => {
    router.replace({ path: '/chat', query: { ...route.query, ...q } });
  };

  await chatStore.sendMessage(
    query,
    filesToSend,
    selectedKbIds.value,
    userStore.currentOrganization?.id,
    pendingQuote,
    routerReplace,
  );
  scrollToBottom();
};

const handleRegenerate = async (index: number) => {
  const reg_content = messages.value[index].content;
  if (reg_content.includes('正在') || isGenerating.value) return;
  if (reg_content === '请求失败，请稍后再试') {
    messages.value.pop();
    const last_query = messages.value[index - 1].content;
    messages.value.pop();
    await sendMessage(last_query);
    return;
  }
  const formData = new FormData();
  formData.append('conversation_id', conversationId.value);
  try { const response = await rechat(formData); messages.value[index] = response; } catch {}
};

const copiedIndex = ref<number | null>(null);
const handleCopyMessage = (content: string, index?: number) => {
  navigator.clipboard.writeText(content);
  if (index !== undefined) {
    copiedIndex.value = index;
    setTimeout(() => { copiedIndex.value = null; }, 1500);
  }
};

const quotedMessage = ref<QuoteInfo | null>(null);

const handleQuoteMessage = (content: string, role: 'user' | 'assistant') => {
  quotedMessage.value = { content, role };
  nextTick(() => {
    const textarea = document.querySelector('.chat-textarea textarea') as HTMLTextAreaElement;
    if (textarea) textarea.focus();
  });
};

const clearQuote = () => {
  quotedMessage.value = null;
};

const truncateQuote = (text: string, max = 60) => {
  const single = text.replace(/\n/g, ' ');
  return single.length > max ? single.slice(0, max) + '…' : single;
};

const renderMarkdown = (content: string) => {
  // 触发响应式更新
  void renderKey.value;
  if (!content) return '';
  let html = DOMPurify.sanitize(marked.parse(content) as string, { ADD_ATTR: ['data-cite-index'] });
  html = html.replace(/\[来源(\d+)\]/g, '<span class="cite-inline" data-cite-index="$1">来源$1</span>');
  return html;
};

import type { SourceCitation } from '../types/chat';
const activeCite = ref<{ source: SourceCitation; rect: DOMRect; citedText: string } | null>(null);

const extractCitedText = (citeSpan: HTMLElement): string => {
  const parent = citeSpan.parentElement;
  if (!parent) return '';
  const text = parent.textContent || '';
  const allCites = Array.from(parent.querySelectorAll('.cite-inline'));
  const myIdx = allCites.indexOf(citeSpan);
  const parts = text.split(/来源\d+/);
  const before = (myIdx >= 0 && myIdx < parts.length) ? parts[myIdx].trim() : '';
  const after = (myIdx + 1 < parts.length) ? parts[myIdx + 1].trim() : '';
  return [before, after].filter(Boolean).join(' ') || text.replace(/来源\d+/g, '').trim();
};

const handleCiteClick = (e: MouseEvent) => {
  const target = (e.target as HTMLElement).closest('.cite-inline') as HTMLElement | null;
  if (!target) return;
  const citeIndex = parseInt(target.dataset.citeIndex || '0', 10) - 1;
  const msgEl = target.closest('.msg') as HTMLElement | null;
  if (!msgEl) return;
  const msgIndex = msgEl.dataset.msgIndex
    ? parseInt(msgEl.dataset.msgIndex, 10)
    : Array.from(msgEl.parentElement!.children).indexOf(msgEl);
  if (msgIndex < 0 || msgIndex >= messages.value.length) return;
  const msg = messages.value[msgIndex];
  if (!msg?.sources?.length) return;
  const source = msg.sources[citeIndex] || msg.sources[0];
  const citedText = extractCitedText(target);
  activeCite.value = { source, rect: target.getBoundingClientRect(), citedText };
};

const closeCitePopover = () => { activeCite.value = null; };

const escapeHtml = (text: string) =>
  text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const highlightedContent = computed(() => {
  if (!activeCite.value) return '';
  const raw = activeCite.value.source.content || '';
  const safe = escapeHtml(raw);
  const cited = activeCite.value.citedText || '';
  if (!cited || cited.length < 2) return safe;

  const cleanCited = cited.replace(/[\s，。、；：！？""''（）\[\]【】\n\r]/g, '');
  const ngrams = new Set<string>();
  for (let len = 3; len <= 4; len++) {
    for (let i = 0; i <= cleanCited.length - len; i++) {
      ngrams.add(cleanCited.slice(i, i + len));
    }
  }
  if (!ngrams.size) return safe;

  const breaks: number[] = [0];
  for (let i = 0; i < raw.length; i++) {
    if ('。！？\n'.includes(raw[i]) && i + 1 < raw.length) breaks.push(i + 1);
  }
  breaks.push(raw.length);

  const regions: { start: number; end: number; score: number }[] = [];
  for (let i = 0; i < breaks.length - 1; i++) {
    const s = breaks[i], e = breaks[i + 1];
    if (!raw.slice(s, e).trim()) continue;
    const clean = raw.slice(s, e).replace(/[\s，。、；：！？""''（）\[\]【】]/g, '');
    let score = 0;
    for (const ng of ngrams) { if (clean.includes(ng)) score++; }
    regions.push({ start: s, end: e, score });
  }
  if (!regions.length) return safe;

  let bestIdx = -1, bestLen = 0, bestScore = 0;
  for (let ws = 1; ws <= Math.min(3, regions.length); ws++) {
    for (let i = 0; i <= regions.length - ws; i++) {
      let total = 0;
      for (let j = i; j < i + ws; j++) total += regions[j].score;
      if (total > bestScore) { bestScore = total; bestIdx = i; bestLen = ws; }
    }
  }
  if (bestScore === 0) return safe;

  const hlStart = regions[bestIdx].start;
  const hlEnd = regions[bestIdx + bestLen - 1].end;
  return escapeHtml(raw.slice(0, hlStart))
    + '<mark class="cite-hl">' + escapeHtml(raw.slice(hlStart, hlEnd)) + '</mark>'
    + escapeHtml(raw.slice(hlEnd));
});

const citePopoverStyle = computed(() => {
  if (!activeCite.value) return {};
  const r = activeCite.value.rect;
  const top = Math.min(r.bottom + 8, window.innerHeight - 320);
  const left = Math.max(16, Math.min(r.left, window.innerWidth - 360));
  return { top: `${top}px`, left: `${left}px` };
});

const handleDownloadSource = async (src: SourceCitation) => {
  const docId = src.document_id;
  if (!docId) return;
  try {
    const response = await DownloadFile(Number(docId));
    const disposition = response.headers['content-disposition'] || '';
    const match = disposition.match(/filename\*?=(?:UTF-8''|"?)([^";]+)/i);
    const filename = match ? decodeURIComponent(match[1]) : src.source || 'document';
    const url = window.URL.createObjectURL(new Blob([response.data]));
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    window.URL.revokeObjectURL(url);
  } catch {}
};

const loadDate = async () => {
  if (botId.value > 0) {
    try {
      const bot = await getBot(botId.value);
      currentBot.value = bot;
      if (bot.model_config_id) modelConfigId.value = String(bot.model_config_id);
      if (bot.vector_db_ids?.length > 0) selectedKbIds.value = [...bot.vector_db_ids];
      if (bot.greeting) messages.value.push({ content: bot.greeting, role: 'assistant', create_at: getCurrentTime() } as ChatMessage);
    } catch { currentBot.value = null; }
  }
  await Promise.all([loadAllConfigs(), loadKnowledgeBases()]);
  if (!configName.value && modelConfigId.value && Number(modelConfigId.value) > 0) {
    const config = await getModelConfig(Number(modelConfigId.value));
    if (config && config.name) configName.value = config.name;
  } else if (!isBotMode.value) {
    await ensureModelConfig(false);
  }
  if (conversationId.value) {
    const formData = new FormData();
    formData.append('conversation_id', conversationId.value);
    const conversaton = (await getMessages(formData));
    conversationInfo.value = conversaton.conversation_info;
    const ori_messages = conversaton.history;
    messages.value = ori_messages.messages
      .sort((a: ChatMessage, b: ChatMessage) => new Date(a.create_at).getTime() - new Date(b.create_at).getTime())
      .map((msg: ChatMessage) => {
        // 从历史 metadata 中恢复检索思考过程
        if (msg.role === 'assistant' && msg.toolCalls && !msg.retrievalProcess) {
          const ksTool = (msg.toolCalls as any[]).find((t: any) => t.tool === 'knowledge_search');
          if (ksTool) {
            msg.retrievalProcess = [];
            msg.retrievalProcess.push({
              step: 'query_rewrite',
              original_query: String(ksTool.args?.query || ''),
              retrieval_query: String(ksTool.args?.query || ''),
              is_reformulated: false,
            });
            if (ksTool.result) {
              msg.retrievalProcess.push({
                step: 'retrieval_complete',
                total_results: ksTool.result.count ?? 0,
                avg_similarity: ksTool.result.avg_similarity ?? 0,
                used_knowledge_base: (ksTool.result.count ?? 0) > 0,
                vector_db_ids: ksTool.result.queried_vector_db_ids ?? ksTool.result.vector_db_ids ?? [],
                retrieval_layers: [],
                fallback_used: false,
              });
            }
          }
        }
        return msg;
      });
    if (isBotMode.value) botConversationId.value = conversationId.value;
  }
  scrollToBottom();
};

const handleChatHistoryChange = (val: number) => {
  const v = typeof val === 'object' ? val?.target?.value : val;
  setChatHistory(conversationId.value, v).then(() => {
    conversationInfo.value.chat_history = Number(v);
  });
};

const handleClickOutsideKb = (e: MouseEvent) => {
  const wrap = document.querySelector('.kb-trigger-wrap');
  if (kbPanelOpen.value && wrap && !wrap.contains(e.target as Node)) {
    kbPanelOpen.value = false;
  }
};
onMounted(() => {
  const routeConvId = route.query.conversation_id as string || '';
  const routeBotId = route.query.bot_id ? Number(route.query.bot_id) : 0;
  const storeMatchesRoute = chatStore.conversationId === routeConvId && chatStore.botId === routeBotId && (chatStore.messages.length > 0 || chatStore.isGenerating);
  if (!storeMatchesRoute) {
    chatStore.reset();
    botId.value = routeBotId;
    conversationId.value = routeConvId;
    modelConfigId.value = route.query.model_config_id as string || '';
    configName.value = route.query.config_name as string || '';
    loadDate();
  } else {
    loadAllConfigs();
    loadKnowledgeBases();
    scrollToBottom();
  }
  document.addEventListener('click', handleClickOutsideKb);
});
onUnmounted(() => {
  document.removeEventListener('click', handleClickOutsideKb);
  stopElapsedTimer();
});

watch(renderKey, () => { scrollToBottom(); });

const scrollToBottom = () => {
  nextTick(() => { if (messageAreaRef.value) messageAreaRef.value.scrollTop = messageAreaRef.value.scrollHeight; });
};
</script>

<template>
  <div class="chat-page">
    <!-- Chat Header -->
    <div class="chat-header">
      <div class="chat-header-left">
        <button class="header-back-btn" @click="router.push('/intro')" title="返回">
          <el-icon :size="15"><ArrowLeft /></el-icon>
        </button>
        <div class="header-info">
          <span class="header-name" v-if="isBotMode && currentBot">{{ currentBot.name }}</span>
          <span class="header-name" v-else-if="conversationInfo.name">{{ conversationInfo.name }}</span>
          <span class="header-name" v-else>新对话</span>
          <div class="header-tags">
            <span class="header-model-tag">{{ currentConfigName }}</span>
            <span v-if="useAgentMode" class="header-agent-tag">Agent</span>
            <span v-if="selectedKbIds.length > 0 && !isBotMode" class="header-kb-tag">
              <el-icon :size="10"><FolderOpened /></el-icon>
              {{ selectedKbIds.length }} 个知识库
            </span>
          </div>
        </div>
      </div>
      <div class="chat-header-right">
        <button class="header-icon-btn" @click="settingsDrawerVisible = true" title="对话设置">
          <el-icon :size="15"><Setting /></el-icon>
        </button>
        <button v-if="isConversationLocked" class="header-icon-btn" @click="router.push('/intro')" title="新对话">
          <el-icon :size="15"><Plus /></el-icon>
        </button>
      </div>
    </div>

    <!-- 消息区域 -->
    <div ref="messageAreaRef" class="chat-messages" :class="{ 'is-empty': messages.length === 0 }">
      <!-- 空状态 -->
      <div v-if="messages.length === 0" class="chat-empty">
        <template v-if="isBotMode && currentBot">
          <el-avatar :size="56" :src="currentBot.avatar" class="intro-bot-avatar">
            {{ currentBot.name.slice(0, 1) }}
          </el-avatar>
          <h1 class="intro-greeting">{{ currentBot.name }}</h1>
          <p class="intro-subtitle">{{ currentBot.description || '有什么可以帮您的？' }}</p>
        </template>
        <template v-else>
          <div class="intro-logo">
            <img src="/ModelHub.png" alt="ModelHub" />
          </div>
          <h1 class="intro-greeting">{{ greetingTime }}好，{{ userStore.user?.name }}</h1>
          <p class="intro-subtitle">有什么可以帮您的？</p>
        </template>
      </div>

      <div v-else class="chat-messages-inner">
        <div
          v-for="(message, index) in messages"
          :key="`${message.create_at}-${index}`"
          class="msg"
          :class="[message.role]"
          :data-msg-index="index"
        >
          <!-- 用户消息 -->
          <template v-if="message.role === 'user'">
            <div class="msg-user-row">
              <div class="msg-user-wrap">
                <div class="msg-user-actions">
                  <button class="action-btn" @click="handleQuoteMessage(message.content, 'user')" title="引用">
                    <el-icon :size="13"><ChatRound /></el-icon>
                  </button>
                  <button class="action-btn" @click="handleCopyMessage(message.content, index)" :title="copiedIndex === index ? '已复制' : '复制'">
                    <el-icon :size="13"><CopyDocument /></el-icon>
                  </button>
                </div>
                <div class="msg-user-bubble">
                  <div v-if="message.quote" class="quote-card" :class="{ 'quote-card--ai': message.quote.role === 'assistant' }">
                    <span class="quote-card-role">{{ message.quote.role === 'assistant' ? 'AI' : '我' }}</span>
                    <span class="quote-card-text">{{ truncateQuote(message.quote.content, 80) }}</span>
                  </div>
                  {{ message.content }}
                </div>
              </div>
            </div>
          </template>

          <!-- AI 消息 -->
          <template v-else-if="message.role === 'assistant'">
            <div class="msg-ai-row">
              <div class="msg-ai-avatar">
                <el-avatar v-if="isBotMode && currentBot" :size="30" :src="currentBot.avatar">{{ currentBot.name.slice(0, 1) }}</el-avatar>
                <div v-else class="ai-default-avatar">
                  <img src="/ModelHub.png" alt="AI" />
                </div>
              </div>
              <div class="msg-ai-body">
                <div class="msg-ai-bubble">
                  <div v-if="(message as Record<string, unknown>).forbidden_topic_hit" class="msg-forbidden-tip">
                    命中禁止话题：{{ (message as Record<string, unknown>).forbidden_topic_hit }}
                  </div>

                  <!-- Agent 思考过程（仅在没有检索过程时显示，避免重复） -->
                  <div class="agent-process" v-if="message.toolCalls && message.toolCalls.length > 0 && !(message.retrievalProcess && message.retrievalProcess.length > 0)">
                    <div class="agent-process-header">
                      <span class="agent-process-icon">{{ getStateIcon(message.agentState) }}</span>
                      <span class="agent-process-label">{{ message.agentStateLabel || 'Agent 推理过程' }}</span>
                      <span class="thinking-stats">
                        <span class="thinking-stat-item thinking-timer" :class="{ 'is-live': message.isStreaming }">
                          ⏱ {{ formatElapsed(message.streamStartTime, !message.isStreaming, message.trace) }}
                        </span>
                        <span class="thinking-stat-item thinking-tokens" v-if="formatTokens(message as ChatMessage)">
                          · {{ formatTokens(message as ChatMessage) }}
                        </span>
                      </span>
                    </div>
                    <div class="agent-steps">
                      <div class="agent-step" v-for="(tc, ti) in message.toolCalls" :key="ti"
                           :class="{ 'is-calling': tc.status === 'calling', 'is-error': tc.status === 'error' }">
                        <div class="agent-step-header">
                          <span class="agent-step-icon">{{ tc.status === 'calling' ? '⏳' : tc.status === 'error' ? '❌' : '✅' }}</span>
                          <span class="agent-step-tool">{{ getToolLabel(tc.tool) }}</span>
                          <span v-if="tc.latencyMs" class="agent-step-time">{{ tc.latencyMs }}ms</span>
                        </div>
                        <div class="agent-step-args" v-if="tc.args">
                          <code>{{ JSON.stringify(tc.args).slice(0, 120) }}</code>
                        </div>
                        <div class="agent-step-result" v-if="tc.result && tc.status === 'done'">
                          <span v-if="tc.result.found === false" class="result-empty">未找到结果</span>
                          <span v-else-if="tc.result.count" class="result-found">找到 {{ tc.result.count }} 条结果</span>
                          <span v-else-if="tc.result.result !== undefined" class="result-value">= {{ tc.result.result }}</span>
                          <span v-else class="result-ok">执行成功</span>
                        </div>
                      </div>
                    </div>
                  </div>

                  <!-- 统一检索思考过程（合并 Agent tool call 信息） -->
                  <div class="retrieval-process" v-if="message.retrievalProcess && message.retrievalProcess.length > 0">
                    <div class="retrieval-process-header" @click="toggleRetrieval(index)">
                      <span class="retrieval-process-icon">🔍</span>
                      <span class="retrieval-process-label">思考过程</span>
                      <span class="thinking-stats">
                        <span class="thinking-stat-item thinking-timer" :class="{ 'is-live': message.isStreaming }">
                          ⏱ {{ formatElapsed(message.streamStartTime, !message.isStreaming, message.trace) }}
                        </span>
                        <span class="thinking-stat-item thinking-tokens" v-if="formatTokens(message as ChatMessage)">
                          · {{ formatTokens(message as ChatMessage) }}
                        </span>
                      </span>
                      <el-icon :size="12" class="retrieval-toggle">
                        <ArrowDown v-if="!expandedRetrieval[index]" />
                        <ArrowUp v-else />
                      </el-icon>
                    </div>
                    <div class="retrieval-steps" v-show="expandedRetrieval[index] ?? true">
                      <!-- 理解问题 -->
                      <template v-for="(step, si) in message.retrievalProcess" :key="si">
                        <div class="retrieval-step" v-if="step.step === 'query_rewrite'">
                          <span class="step-icon">💬</span>
                          <div class="step-body">
                            <span class="step-title">理解问题</span>
                            <span class="step-detail" v-if="step.is_reformulated">
                              追问补全为：「{{ step.retrieval_query }}」
                            </span>
                            <span class="step-detail" v-else>
                              检索查询：「{{ step.original_query }}」
                            </span>
                          </div>
                        </div>
                        <!-- 知识库检索 + 可展开详情 -->
                        <div class="retrieval-step" v-if="step.step === 'retrieval_complete'">
                          <span class="step-icon">{{ step.used_knowledge_base ? '📚' : '📭' }}</span>
                          <div class="step-body">
                            <div class="step-title-row">
                              <span class="step-title">知识库检索</span>
                              <span class="step-time" v-if="message.toolCalls?.find(t => t.tool === 'knowledge_search')?.latencyMs">
                                {{ (message.toolCalls!.find(t => t.tool === 'knowledge_search')!.latencyMs! / 1000).toFixed(1) }}s
                              </span>
                            </div>
                            <span class="step-detail" v-if="step.used_knowledge_base">
                              从 {{ (step.vector_db_ids as number[] || []).length }} 个知识库中检索到 {{ step.total_found || step.total_results }} 条内容，
                              精选 {{ step.total_results }} 条，
                              平均相似度 {{ ((step.avg_similarity as number || 0) * 100).toFixed(0) }}%
                            </span>
                            <span class="step-detail" v-else>未匹配到相关知识库内容</span>
                            <!-- 查看详情按钮 + 来源分数明细 -->
                            <div v-if="step.used_knowledge_base && message.toolCalls?.find(t => t.tool === 'knowledge_search')?.result?.sources">
                              <button class="detail-toggle" @click.stop="toggleStepDetail(index, si)">
                                {{ expandedStepDetail[`${index}-${si}`] ? '收起详情' : '查看详情' }}
                                <el-icon :size="10"><ArrowDown v-if="!expandedStepDetail[`${index}-${si}`]" /><ArrowUp v-else /></el-icon>
                              </button>
                              <div class="step-sources-detail" v-if="expandedStepDetail[`${index}-${si}`]">
                                <div class="source-score-row" v-for="(src, srcIdx) in (message.toolCalls!.find(t => t.tool === 'knowledge_search')!.result as Record<string,unknown>).sources as any[]" :key="srcIdx">
                                  <span class="source-rank">#{{ src.index || srcIdx + 1 }}</span>
                                  <span class="source-name">{{ (src.source || '').replace(/^[0-9a-f]{32}_/, '') }}</span>
                                  <div class="source-scores">
                                    <span class="score-tag score-vector">语义 {{ ((src.vector_score || 0) * 100).toFixed(0) }}%</span>
                                    <span class="score-tag score-bm25">关键词 {{ ((src.bm25_score || 0) * 100).toFixed(0) }}%</span>
                                    <span class="score-tag score-sim">相似度 {{ ((src.similarity || 0) * 100).toFixed(0) }}%</span>
                                  </div>
                                </div>
                              </div>
                            </div>
                          </div>
                        </div>
                      </template>
                      <!-- 精排筛选 -->
                      <div class="retrieval-step" v-if="message.sources && message.sources.length > 0 && message.sources.some(s => s.retrieval_method?.includes('cross_encoder'))">
                        <span class="step-icon">🎯</span>
                        <div class="step-body">
                          <span class="step-title">精排筛选</span>
                          <span class="step-detail">Cross-Encoder 深度语义精排，筛选出 {{ message.sources.length }} 条最相关结果</span>
                        </div>
                      </div>
                      <!-- 生成回答 -->
                      <div class="retrieval-step" v-if="message.content || message.isStreaming">
                        <span class="step-icon">✍️</span>
                        <div class="step-body">
                          <div class="step-title-row">
                            <span class="step-title">{{ message.isStreaming ? '正在生成回答...' : '生成回答' }}</span>
                            <span class="step-badge" v-if="message.grounded_level" :class="'confidence-' + ({高:'high',中:'medium',低:'low',不足:'weak'}[message.grounded_level] || 'low')">
                              可信度：{{ message.grounded_level }}
                            </span>
                          </div>
                          <span class="step-detail" v-if="formatTokens(message as ChatMessage)">
                            {{ formatTokens(message as ChatMessage) }}
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>

                  <!-- 流式打字指示器 -->
                  <div class="streaming-indicator" v-if="message.isStreaming && !message.content && (!message.toolCalls || message.toolCalls.length === 0) && (!message.retrievalProcess || message.retrievalProcess.length === 0)">
                    <span class="dot-typing">
                      <span></span><span></span><span></span>
                    </span>
                    <span class="streaming-label">{{ message.agentStateLabel || '思考中...' }}</span>
                    <span class="streaming-timer" v-if="message.streamStartTime">{{ formatElapsed(message.streamStartTime, false) }}</span>
                  </div>

                  <!-- Markdown 内容（流式渲染） -->
                  <div class="markdown-body" v-if="message.content" v-html="renderMarkdown(message.content)" @click="handleCiteClick"></div>

                  <!-- 流式光标 -->
                  <span v-if="message.isStreaming && message.content" class="typing-cursor"></span>

                  <!-- 来源和追踪信息已整合到思考过程面板中 -->
                </div>
                <!-- 消息操作 -->
                <div class="msg-ai-actions" v-if="!message.isStreaming">
                  <button class="action-btn" @click="handleCopyMessage(message.content, index)" :title="copiedIndex === index ? '已复制' : '复制'">
                    <el-icon :size="13"><CopyDocument /></el-icon>
                    <span v-if="copiedIndex === index" class="action-tip">已复制</span>
                  </button>
                  <button class="action-btn" @click="handleQuoteMessage(message.content, 'assistant')" title="引用">
                    <el-icon :size="13"><ChatRound /></el-icon>
                  </button>
                  <button class="action-btn" @click="handleRegenerate(index)" title="重新生成">
                    <el-icon :size="13"><Refresh /></el-icon>
                  </button>
                </div>
              </div>
            </div>
          </template>

          <!-- 系统消息 -->
          <template v-else>
            <div class="msg-system">{{ message.content }}</div>
          </template>
        </div>
      </div>
    </div>

    <!-- 底部输入区 -->
    <div class="chat-footer">
      <div class="chat-input-container">
        <div class="chat-input-box">
          <!-- 引用预览条 -->
          <div class="quote-preview" v-if="quotedMessage">
            <div class="quote-preview-body">
              <span class="quote-preview-role">{{ quotedMessage.role === 'assistant' ? 'AI' : '我' }}</span>
              <span class="quote-preview-text">{{ truncateQuote(quotedMessage.content) }}</span>
            </div>
            <button class="quote-preview-close" @click="clearQuote">
              <el-icon :size="14"><Close /></el-icon>
            </button>
          </div>
          <input ref="fileInputRef" type="file" class="sr-only" multiple
            accept=".pdf,.doc,.docx,.txt,.md,.csv,.xlsx,.xls,.pptx,.ppt,.png,.jpg,.jpeg,.gif,.bmp,.tiff,.tif,.webp,.zip,.tar,.gz,.tgz"
            @change="handleFileSelected" />
          <!-- 已选文件 -->
          <div class="file-chips" v-if="selectedFiles.length > 0">
            <div class="file-chip" v-for="(file, i) in selectedFiles" :key="`${file.name}-${file.size}-${i}`">
              <span class="file-chip-name">{{ file.name }}</span>
              <span class="file-chip-size">{{ formatFileSize(file.size) }}</span>
              <el-icon class="file-chip-x" @click="removeSelectedFile(i)"><Close /></el-icon>
            </div>
          </div>
          <!-- 输入框 -->
          <ElInput
            v-model="userInput"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 6 }"
            placeholder="输入你的问题..."
            @keydown.enter.exact.prevent="sendMessage(userInput)"
            resize="none"
            class="chat-textarea"
            :disabled="isGenerating"
          />
          <!-- 底部工具栏 -->
          <div class="chat-input-toolbar">
            <div class="toolbar-left">
              <button class="toolbar-btn" @click="openFilePicker" title="上传文件">
                <el-icon :size="16"><UploadFilled /></el-icon>
              </button>
            </div>
            <div class="toolbar-right">
              <button v-if="isGenerating" class="stop-btn" @click="stopGenerating" title="停止生成">
                <span class="stop-icon"></span>
              </button>
              <button v-else class="send-btn" :class="{ active: hasInput }" @click="sendMessage(userInput)">
                <el-icon :size="18"><Promotion /></el-icon>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 设置抽屉 -->
    <ElDrawer
      v-model="settingsDrawerVisible"
      title="对话设置"
      direction="rtl"
      size="320px"
    >
      <div class="settings-content">
        <!-- Agent 模式切换 -->
        <div class="settings-section">
          <label class="settings-label">Agent 模式</label>
          <div class="settings-toggle-row">
            <div
              class="settings-toggle"
              :class="{ active: useAgentMode }"
              @click="useAgentMode = !useAgentMode"
            >
              <span class="toggle-track"><span class="toggle-thumb"></span></span>
              <span class="toggle-label">{{ useAgentMode ? '已启用 — 智能工具调用' : '已关闭 — 直接回答' }}</span>
            </div>
          </div>
          <p class="settings-hint">启用后 AI 会自动判断并调用工具（知识库检索、计算器等），展示推理过程</p>
        </div>

        <!-- 模型选择 -->
        <div class="settings-section" v-if="!isBotMode">
          <label class="settings-label">模型配置</label>
          <div class="settings-model-list">
            <div
              v-for="config in allConfigs"
              :key="config.id"
              class="settings-model-item"
              :class="{ active: String(config.id) === modelConfigId, disabled: isConversationLocked }"
              @click="handleConfigChange(config.id)"
            >
              <span class="settings-model-name">{{ config.name }}</span>
            </div>
          </div>
          <p v-if="isConversationLocked" class="settings-hint">对话进行中无法切换模型</p>
        </div>

        <!-- 知识库选择 -->
        <div class="settings-section" v-if="!isBotMode && allKnowledgeBases.length > 0">
          <label class="settings-label">知识库 ({{ selectedKbIds.length }})</label>
          <div class="settings-kb-list">
            <div
              v-for="kb in allKnowledgeBases"
              :key="kb.id"
              class="settings-kb-item"
              :class="{ active: selectedKbIds.includes(kb.id) }"
              @click="toggleKb(kb.id)"
            >
              <span class="settings-kb-name">{{ kb.name }}</span>
              <span class="settings-kb-scope">{{ getKbVisibilityLabel(kb) }}</span>
            </div>
          </div>
        </div>

        <!-- 上下文窗口 -->
        <div class="settings-section">
          <label class="settings-label">上下文窗口</label>
          <div class="settings-slider-row">
            <el-slider
              v-model="conversationInfo.chat_history"
              :min="1" :max="10" :step="1"
              :show-tooltip="true"
              class="settings-slider"
              @change="handleChatHistoryChange"
            />
            <span class="settings-slider-val">{{ conversationInfo.chat_history }}</span>
          </div>
          <p class="settings-hint">控制对话时发送给模型的历史消息数量</p>
        </div>
      </div>
    </ElDrawer>

    <!-- 引用来源弹窗 -->
    <div v-if="activeCite" class="cite-overlay" @click.self="closeCitePopover">
      <div class="cite-popover" :style="citePopoverStyle">
        <div class="cite-popover-header">
          <span class="cite-popover-file">{{ activeCite.source.source }}</span>
          <span class="cite-popover-tag" :class="getConfidenceClass(activeCite.source.confidence_label)">{{ activeCite.source.confidence_label || '中' }}</span>
        </div>
        <div class="cite-popover-meta">
          <span v-if="activeCite.source.vector_db_name" class="cite-popover-meta-tag">{{ activeCite.source.vector_db_name }}</span>
          <span class="cite-popover-meta-tag">{{ getRetrievalMethodLabel(activeCite.source.retrieval_method) }}</span>
        </div>
        <div class="cite-popover-content" v-html="highlightedContent"></div>
        <div class="cite-popover-actions">
          <button v-if="activeCite.source.document_id" class="cite-popover-btn cite-popover-btn--primary" @click="handleDownloadSource(activeCite.source)">
            <el-icon :size="13"><Download /></el-icon>
            下载文档
          </button>
          <button class="cite-popover-btn" @click="closeCitePopover">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ===== Page Layout ===== */
.chat-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 56px);
  overflow: hidden;
  margin: -1.25rem -1.5rem;
  padding: 0;
  background: #f9fafb;
}

/* ===== Chat Header ===== */
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  border-bottom: 1px solid #e8ecf2;
  background: #fff;
  flex-shrink: 0;
  height: 48px;
}
.chat-header-left { display: flex; align-items: center; gap: 10px; min-width: 0; }
.header-back-btn {
  display: flex; align-items: center; justify-content: center;
  width: 32px; height: 32px; border: none; background: transparent;
  border-radius: 8px; cursor: pointer; color: #64748b; transition: all 0.15s; flex-shrink: 0;
}
.header-back-btn:hover { background: #f1f5f9; color: #6366f1; }
.header-info { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.header-name { font-size: 14px; font-weight: 600; color: #1e293b; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; line-height: 1.3; }
.header-tags { display: flex; align-items: center; gap: 6px; }
.header-model-tag { font-size: 11px; color: #6366f1; background: #eef2ff; padding: 1px 8px; border-radius: 4px; font-weight: 500; line-height: 1.5; }
.header-agent-tag { font-size: 11px; color: #059669; background: #ecfdf5; padding: 1px 8px; border-radius: 4px; font-weight: 600; line-height: 1.5; }
.header-kb-tag { display: inline-flex; align-items: center; gap: 3px; font-size: 11px; color: #64748b; line-height: 1.5; }
.chat-header-right { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
.header-icon-btn {
  display: flex; align-items: center; justify-content: center;
  width: 32px; height: 32px; border: none; background: transparent;
  border-radius: 8px; cursor: pointer; color: #94a3b8; transition: all 0.15s;
}
.header-icon-btn:hover { background: #f1f5f9; color: #6366f1; }

/* ===== Message Area ===== */
.chat-messages { flex: 1; overflow-y: auto; min-height: 0; scrollbar-width: thin; scrollbar-color: #e2e8f0 transparent; }
.chat-messages.is-empty { overflow: hidden; }
.chat-messages::-webkit-scrollbar { width: 5px; }
.chat-messages::-webkit-scrollbar-thumb { background: #e2e8f0; border-radius: 50vw; }
.chat-messages-inner { max-width: 720px; margin: 0 auto; padding: 28px 24px; display: flex; flex-direction: column; gap: 28px; }

/* ===== Empty State ===== */
.chat-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; padding: 40px 20px; }
.intro-logo { width: 56px; height: 56px; margin-bottom: 20px; background: linear-gradient(135deg, #6366f1 0%, #818cf8 100%); border-radius: 16px; display: flex; align-items: center; justify-content: center; box-shadow: 0 6px 20px rgba(99,102,241,0.2); }
.intro-logo img { width: 32px; height: 32px; object-fit: contain; filter: brightness(0) invert(1); }
.intro-bot-avatar { margin-bottom: 16px; font-size: 20px; font-weight: 600; }
.intro-greeting { font-size: 24px; font-weight: 700; color: #1e293b; margin: 0 0 6px; }
.intro-subtitle { font-size: 15px; color: #94a3b8; margin: 0 0 28px; }

/* ===== User Message ===== */
.msg-user-row { display: flex; justify-content: flex-end; }
.msg-user-wrap { display: flex; align-items: flex-end; gap: 6px; max-width: 70%; }
.msg-user-actions { display: flex; gap: 2px; opacity: 0; transition: opacity 0.15s; flex-shrink: 0; padding-bottom: 4px; }
.msg-user-row:hover .msg-user-actions { opacity: 1; }
.msg-user-bubble { width: max-content; max-width: 100%; padding: 12px 18px; background: linear-gradient(135deg, #6366f1, #818cf8); border: none; border-radius: 20px 20px 4px 20px; font-size: 14px; line-height: 1.6; color: #fff; word-break: break-word; white-space: pre-wrap; box-shadow: 0 2px 8px rgba(99,102,241,0.2); }

/* ===== AI Message ===== */
.msg-ai-row { display: flex; gap: 12px; align-items: flex-start; }
.msg-ai-avatar { flex-shrink: 0; padding-top: 2px; }
.ai-default-avatar { width: 32px; height: 32px; background: linear-gradient(135deg, #6366f1, #818cf8); border-radius: 50%; display: flex; align-items: center; justify-content: center; box-shadow: 0 2px 8px rgba(99,102,241,0.2); }
.ai-default-avatar img { width: 18px; height: 18px; object-fit: contain; filter: brightness(0) invert(1); }
.msg-ai-body { min-width: 0; max-width: 85%; }
.msg-ai-bubble { width: fit-content; max-width: 100%; background: #fff; border: 1px solid #e8ecf2; border-radius: 4px 20px 20px 20px; padding: 16px 20px; font-size: 14px; line-height: 1.7; color: #334155; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
.msg-forbidden-tip { padding: 8px 12px; background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; font-size: 12px; color: #92400e; margin-bottom: 10px; }
.msg-ai-actions { display: flex; gap: 2px; margin-top: 6px; opacity: 0; transition: opacity 0.15s; }
.msg-ai-row:hover .msg-ai-actions { opacity: 1; }
.action-btn { display: inline-flex; align-items: center; justify-content: center; gap: 4px; height: 28px; padding: 0 6px; min-width: 28px; border: none; background: transparent; border-radius: 6px; cursor: pointer; color: #94a3b8; transition: all 0.15s; position: relative; }
.action-btn:hover { background: #f1f5f9; color: #6366f1; }
.action-tip { font-size: 11px; color: #10b981; font-weight: 500; }
.msg-system { text-align: center; font-size: 12px; color: #94a3b8; padding: 8px 0; }

/* ===== Retrieval Process Thinking ===== */
.retrieval-process {
  margin-bottom: 12px;
  padding: 12px 14px;
  background: linear-gradient(135deg, #eff6ff 0%, #f0f4ff 100%);
  border: 1px solid #bfdbfe;
  border-radius: 10px;
}
.retrieval-process-header {
  display: flex; align-items: center; gap: 6px; cursor: pointer; user-select: none;
}
.retrieval-process-icon { font-size: 14px; }
.retrieval-process-label { font-size: 12px; font-weight: 600; color: #1e40af; }
.thinking-stats {
  display: flex; align-items: center; gap: 2px; margin-left: auto; margin-right: 4px;
}
.thinking-stat-item {
  font-size: 11px; color: #64748b; font-variant-numeric: tabular-nums;
}
.thinking-timer.is-live { color: #2563eb; font-weight: 500; }
.thinking-tokens { color: #8b5cf6; }
.streaming-timer { font-size: 12px; color: #94a3b8; margin-left: auto; font-variant-numeric: tabular-nums; }
.retrieval-toggle { color: #93a3b8; transition: transform 0.2s; }
.retrieval-steps {
  display: flex; flex-direction: column; gap: 2px; margin-top: 10px;
  padding-left: 4px; border-left: 2px solid #bfdbfe;
}
.retrieval-step {
  display: flex; align-items: flex-start; gap: 8px; padding: 4px 0 4px 10px;
  animation: fadeSlideIn 0.3s ease;
}
.retrieval-step .step-icon { font-size: 13px; flex-shrink: 0; margin-top: 1px; }
.retrieval-step .step-body { display: flex; flex-direction: column; gap: 2px; }
.retrieval-step .step-title { font-size: 12px; font-weight: 600; color: #334155; }
.retrieval-step .step-detail { font-size: 11px; color: #64748b; line-height: 1.4; }
@keyframes fadeSlideIn {
  from { opacity: 0; transform: translateX(-6px); }
  to { opacity: 1; transform: translateX(0); }
}

.retrieval-process-time { font-size: 11px; color: #94a3b8; margin-right: 4px; }
.step-title-row { display: flex; align-items: center; gap: 8px; }
.step-time { font-size: 10px; color: #94a3b8; }
.step-badge {
  font-size: 10px; padding: 1px 6px; border-radius: 4px; font-weight: 500;
}
.step-badge.confidence-high { background: #dcfce7; color: #166534; }
.step-badge.confidence-medium { background: #fef3c7; color: #92400e; }
.step-badge.confidence-low { background: #fee2e2; color: #991b1b; }
.step-badge.confidence-weak { background: #f1f5f9; color: #64748b; }
.detail-toggle {
  display: inline-flex; align-items: center; gap: 3px;
  font-size: 11px; color: #3b82f6; cursor: pointer;
  background: none; border: none; padding: 2px 0; margin-top: 4px;
}
.detail-toggle:hover { color: #1d4ed8; }
.step-sources-detail {
  margin-top: 6px; padding: 8px 10px;
  background: #f8fafc; border-radius: 6px; border: 1px solid #e2e8f0;
}
.source-score-row {
  display: flex; align-items: center; gap: 8px; padding: 4px 0;
  border-bottom: 1px solid #f1f5f9; font-size: 11px;
}
.source-score-row:last-child { border-bottom: none; }
.source-rank { color: #64748b; font-weight: 600; min-width: 20px; }
.source-name { flex: 1; color: #334155; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 200px; }
.source-scores { display: flex; gap: 4px; flex-shrink: 0; }
.score-tag {
  font-size: 10px; padding: 1px 5px; border-radius: 3px; font-weight: 500;
}
.score-vector { background: #ede9fe; color: #5b21b6; }
.score-bm25 { background: #dbeafe; color: #1e40af; }
.score-sim { background: #d1fae5; color: #065f46; }

/* ===== Agent Process Visualization ===== */
.agent-process {
  margin-bottom: 12px;
  padding: 10px 12px;
  background: linear-gradient(135deg, #f0fdf4 0%, #ecfdf5 100%);
  border: 1px solid #bbf7d0;
  border-radius: 10px;
}
.agent-process-header { display: flex; align-items: center; gap: 6px; margin-bottom: 8px; }
.agent-process-icon { font-size: 14px; }
.agent-process-label { font-size: 12px; font-weight: 600; color: #166534; }
.agent-steps { display: flex; flex-direction: column; gap: 6px; }
.agent-step {
  padding: 8px 10px;
  background: #fff;
  border: 1px solid #dcfce7;
  border-radius: 8px;
  transition: all 0.2s;
}
.agent-step.is-calling { border-color: #fde68a; background: #fffbeb; }
.agent-step.is-error { border-color: #fecaca; background: #fef2f2; }
.agent-step-header { display: flex; align-items: center; gap: 6px; }
.agent-step-icon { font-size: 12px; }
.agent-step-tool { font-size: 12px; font-weight: 600; color: #1e293b; }
.agent-step-time { font-size: 11px; color: #94a3b8; margin-left: auto; }
.agent-step-args { margin-top: 4px; }
.agent-step-args code { font-size: 11px; color: #64748b; background: #f8fafc; padding: 2px 6px; border-radius: 4px; word-break: break-all; }
.agent-step-result { margin-top: 4px; font-size: 11px; }
.result-found { color: #059669; font-weight: 500; }
.result-empty { color: #94a3b8; }
.result-value { color: #6366f1; font-weight: 600; font-family: monospace; }
.result-ok { color: #059669; }

/* ===== Streaming Indicator ===== */
.streaming-indicator { display: flex; align-items: center; gap: 8px; padding: 4px 0; }
.streaming-label { font-size: 13px; color: #94a3b8; }
.dot-typing { display: inline-flex; gap: 3px; align-items: center; }
.dot-typing span {
  width: 6px; height: 6px; border-radius: 50%; background: #94a3b8;
  animation: dotBounce 1.4s infinite ease-in-out both;
}
.dot-typing span:nth-child(1) { animation-delay: -0.32s; }
.dot-typing span:nth-child(2) { animation-delay: -0.16s; }
@keyframes dotBounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

/* ===== Typing Cursor ===== */
.typing-cursor {
  display: inline-block;
  width: 2px;
  height: 16px;
  background: #6366f1;
  margin-left: 1px;
  vertical-align: text-bottom;
  animation: blink 0.8s step-end infinite;
}
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }

/* ===== Code Block ===== */
.markdown-body :deep(.code-block) { position: relative; margin: 12px 0; }
.markdown-body :deep(.code-header) { display: flex; justify-content: space-between; align-items: center; padding: 6px 16px; background: #1a2332; border-radius: 10px 10px 0 0; }
.markdown-body :deep(.code-lang) { font-size: 11px; color: #94a3b8; text-transform: uppercase; }
.markdown-body :deep(.code-copy-btn) { font-size: 11px; color: #94a3b8; background: none; border: 1px solid #334155; border-radius: 4px; padding: 2px 8px; cursor: pointer; transition: all 0.15s; }
.markdown-body :deep(.code-copy-btn:hover) { color: #e2e8f0; border-color: #64748b; }
.markdown-body :deep(.code-block code) { display: block; }
.markdown-body :deep(.code-block + pre), .markdown-body :deep(pre:has(.code-header)) { border-radius: 0 0 10px 10px; margin-top: 0; }

/* ===== Trace Panel ===== */
.trace-panel { margin-top: 12px; border: 1px solid #e6ebf2; border-radius: 10px; overflow: hidden; }
.trace-header { display: flex; align-items: center; gap: 6px; padding: 8px 12px; background: #faf5ff; cursor: pointer; font-size: 12px; color: #7c3aed; user-select: none; transition: background 0.12s; }
.trace-header:hover { background: #f3e8ff; }
.trace-icon { font-size: 13px; }
.trace-stats { font-size: 11px; color: #a78bfa; margin-left: 4px; }
.trace-list { padding: 8px; display: flex; flex-direction: column; gap: 4px; }
.trace-span { display: flex; align-items: center; gap: 6px; padding: 6px 8px; border-radius: 6px; background: #fafafa; font-size: 12px; }
.trace-span.is-error { background: #fef2f2; }
.trace-span-type { padding: 2px 6px; border-radius: 4px; font-weight: 600; font-size: 10px; text-transform: uppercase; }
.trace-span-type.type-llm_call, .trace-span-type.type-llm_stream { background: #eef2ff; color: #4f46e5; }
.trace-span-type.type-tool_call { background: #ecfdf5; color: #059669; }
.trace-span-name { color: #475569; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.trace-span-time { color: #94a3b8; flex-shrink: 0; }
.trace-span-tokens { color: #a78bfa; flex-shrink: 0; }

/* ===== Reference Panel ===== */
.ref-panel { margin-top: 12px; border: 1px solid #e6ebf2; border-radius: 10px; overflow: hidden; }
.ref-header { display: flex; align-items: center; gap: 6px; padding: 8px 12px; background: #f8fafc; cursor: pointer; font-size: 12px; color: #64748b; user-select: none; transition: background 0.12s; }
.ref-header:hover { background: #f1f5f9; }
.ref-arrow { transition: transform 0.2s ease; margin-left: auto; color: #94a3b8; }
.ref-arrow.open { transform: rotate(180deg); }
.ref-list { padding: 8px; display: flex; flex-direction: column; gap: 6px; }
.ref-item { padding: 8px 10px; border: 1px solid #f1f5f9; border-radius: 8px; background: #fff; transition: border-color 0.12s; }
.ref-item:hover { border-color: #e2e8f0; }
.ref-item-main { display: flex; align-items: center; gap: 6px; }
.ref-label { font-weight: 600; color: #6366f1; font-size: 12px; }
.ref-file { color: #334155; font-size: 12px; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
.ref-tag { font-size: 11px; padding: 2px 8px; border-radius: 50vw; font-weight: 500; flex-shrink: 0; }
.ref-tag.confidence-high { background: #dcfce7; color: #166534; }
.ref-tag.confidence-medium { background: #fef9c3; color: #854d0e; }
.ref-tag.confidence-low { background: #fee2e2; color: #991b1b; }
.ref-tag.confidence-weak { background: #f1f5f9; color: #94a3b8; }
.ref-detail { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; padding-top: 6px; border-top: 1px dashed #f1f5f9; }
.ref-tag-plain { font-size: 11px; padding: 2px 7px; border-radius: 4px; background: #f8fafc; color: #64748b; }
.ref-text { font-size: 12px; color: #64748b; line-height: 1.5; margin-top: 6px; padding: 8px; background: #f8fafc; border-radius: 6px; max-height: 160px; overflow-y: auto; white-space: pre-wrap; }
.ref-toggle { margin-top: 4px; border: none; background: none; color: #6366f1; font-size: 11px; cursor: pointer; padding: 0; font-weight: 500; }
.ref-toggle:hover { opacity: 0.7; }

/* ===== Quote ===== */
.quote-card { display: flex; align-items: flex-start; gap: 6px; padding: 8px 10px; margin-bottom: 8px; background: rgba(255, 255, 255, 0.15); border-left: 3px solid rgba(255,255,255,0.5); border-radius: 0 8px 8px 0; font-size: 12px; line-height: 1.5; color: rgba(255,255,255,0.85); }
.quote-card--ai { border-left-color: #6366f1; }
.quote-card-role { flex-shrink: 0; font-weight: 600; color: #6366f1; font-size: 11px; padding: 1px 6px; background: #eef2ff; border-radius: 4px; line-height: 1.4; }
.quote-card-text { color: #64748b; word-break: break-word; }
.quote-preview { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 14px; background: #f8f9ff; border-bottom: 1px solid #eef2ff; }
.quote-preview-body { display: flex; align-items: center; gap: 6px; min-width: 0; flex: 1; }
.quote-preview-role { flex-shrink: 0; font-size: 11px; font-weight: 600; color: #6366f1; padding: 1px 6px; background: #eef2ff; border-radius: 4px; }
.quote-preview-text { font-size: 12px; color: #64748b; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.quote-preview-close { flex-shrink: 0; display: flex; align-items: center; justify-content: center; width: 22px; height: 22px; border: none; background: transparent; border-radius: 50%; cursor: pointer; color: #94a3b8; transition: all 0.12s; }
.quote-preview-close:hover { background: #e2e8f0; color: #475569; }

/* ===== Footer Input ===== */
.chat-footer { flex-shrink: 0; padding: 12px 24px 20px; display: flex; justify-content: center; background: linear-gradient(to top, #f9fafb 60%, transparent); }
.chat-input-container { max-width: 720px; width: 100%; }
.chat-input-box { background: #fff; border: 1.5px solid #d4d4d8; border-radius: 20px; overflow: hidden; transition: border-color 0.2s, box-shadow 0.2s; box-shadow: 0 2px 12px rgba(0,0,0,0.06); }
.chat-input-box:focus-within { border-color: #818cf8; box-shadow: 0 0 0 3px rgba(99,102,241,0.1), 0 2px 12px rgba(0,0,0,0.06); }
.sr-only { display: none; }
.file-chips { display: flex; gap: 6px; flex-wrap: wrap; padding: 10px 14px 0; }
.file-chip { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; background: #f5f3ff; border: 1px solid #e9e5ff; border-radius: 6px; font-size: 12px; color: #4338ca; max-width: 200px; }
.file-chip-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-chip-size { color: #94a3b8; flex-shrink: 0; font-size: 11px; }
.file-chip-x { cursor: pointer; color: #94a3b8; flex-shrink: 0; font-size: 12px; }
.file-chip-x:hover { color: #ef4444; }
:deep(.chat-textarea .el-textarea__inner) { border: none !important; box-shadow: none !important; padding: 12px 16px 8px; font-size: 14px; line-height: 1.5; resize: none; background: transparent; min-height: 22px; max-height: 150px; color: #1e293b; font-family: inherit; }
:deep(.chat-textarea .el-textarea__inner::placeholder) { color: #94a3b8; }
.chat-input-toolbar { display: flex; align-items: center; justify-content: space-between; padding: 4px 8px 8px 12px; }
.toolbar-left { display: flex; align-items: center; gap: 2px; }
.toolbar-right { display: flex; align-items: center; }
.toolbar-btn { display: flex; align-items: center; justify-content: center; width: 32px; height: 32px; border: none; background: transparent; border-radius: 8px; cursor: pointer; color: #94a3b8; transition: all 0.12s; }
.toolbar-btn:hover { background: #f1f5f9; color: #6366f1; }
.send-btn { display: flex; align-items: center; justify-content: center; width: 36px; height: 36px; border: none; background: #e2e8f0; border-radius: 50%; cursor: pointer; color: #94a3b8; transition: all 0.2s; }
.send-btn.active { background: linear-gradient(135deg, #6366f1, #818cf8); color: #fff; box-shadow: 0 2px 10px rgba(99,102,241,0.3); transform: scale(1.05); }
.send-btn.active:hover { background: linear-gradient(135deg, #4f46e5, #6366f1); box-shadow: 0 4px 14px rgba(99,102,241,0.4); }
.stop-btn { display: flex; align-items: center; justify-content: center; width: 36px; height: 36px; border: none; background: #fee2e2; border-radius: 10px; cursor: pointer; transition: all 0.15s; }
.stop-btn:hover { background: #fecaca; }
.stop-icon { width: 12px; height: 12px; background: #ef4444; border-radius: 2px; }

/* ===== Settings ===== */
.settings-content { display: flex; flex-direction: column; gap: 24px; }
.settings-section { display: flex; flex-direction: column; gap: 8px; }
.settings-label { font-size: 13px; font-weight: 600; color: #1e293b; }
.settings-hint { margin: 0; font-size: 12px; color: #94a3b8; }
.settings-toggle-row { display: flex; }
.settings-toggle { display: flex; align-items: center; gap: 10px; cursor: pointer; user-select: none; }
.toggle-track { position: relative; width: 36px; height: 20px; background: #e2e8f0; border-radius: 50vw; transition: background 0.2s; flex-shrink: 0; }
.settings-toggle.active .toggle-track { background: #6366f1; }
.toggle-thumb { position: absolute; top: 2px; left: 2px; width: 16px; height: 16px; background: #fff; border-radius: 50%; transition: transform 0.2s; box-shadow: 0 1px 3px rgba(0,0,0,0.15); }
.settings-toggle.active .toggle-thumb { transform: translateX(16px); }
.toggle-label { font-size: 12px; color: #475569; }
.settings-model-list { display: flex; flex-direction: column; gap: 4px; }
.settings-model-item { padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 8px; font-size: 13px; color: #475569; cursor: pointer; transition: all 0.12s; }
.settings-model-item:hover { border-color: #a5b4fc; background: #f5f3ff; }
.settings-model-item.active { border-color: #6366f1; background: #eef2ff; color: #4338ca; font-weight: 500; }
.settings-model-item.disabled { opacity: 0.5; pointer-events: none; }
.settings-model-name { display: block; }
.settings-kb-list { display: flex; flex-direction: column; gap: 4px; max-height: 200px; overflow-y: auto; }
.settings-kb-item { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 8px; font-size: 13px; cursor: pointer; transition: all 0.12s; }
.settings-kb-item:hover { border-color: #a5b4fc; }
.settings-kb-item.active { border-color: #6366f1; background: #eef2ff; }
.settings-kb-name { color: #334155; }
.settings-kb-item.active .settings-kb-name { color: #4338ca; font-weight: 500; }
.settings-kb-scope { font-size: 11px; color: #94a3b8; }
.settings-slider-row { display: flex; align-items: center; gap: 12px; }
.settings-slider { flex: 1; }
:deep(.settings-slider .el-slider__runway) { height: 4px; background: #e2e8f0; border-radius: 50vw; }
:deep(.settings-slider .el-slider__bar) { height: 4px; background: #6366f1; border-radius: 50vw; }
:deep(.settings-slider .el-slider__button) { width: 14px; height: 14px; border: 2px solid #6366f1; background: #fff; }
.settings-slider-val { font-size: 13px; font-weight: 600; color: #6366f1; min-width: 20px; text-align: center; }

/* ===== Markdown ===== */
.markdown-body { font-size: 14px; line-height: 1.7; word-wrap: break-word; color: #334155; }
.markdown-body :deep(h1) { font-size: 1.35em; font-weight: 700; margin: 20px 0 10px; color: #1e293b; }
.markdown-body :deep(h2) { font-size: 1.2em; font-weight: 600; margin: 18px 0 8px; color: #1e293b; }
.markdown-body :deep(h3) { font-size: 1.08em; font-weight: 600; margin: 14px 0 6px; color: #334155; }
.markdown-body :deep(p) { margin: 0 0 12px; }
.markdown-body :deep(p:last-child) { margin-bottom: 0; }
.markdown-body :deep(a) { color: #6366f1; text-decoration: none; font-weight: 500; }
.markdown-body :deep(a:hover) { text-decoration: underline; }
.markdown-body :deep(code) { padding: 2px 6px; font-size: 12.5px; background: #f1f5f9; color: #e11d48; border-radius: 4px; font-family: Menlo, "Roboto Mono", "Courier New", monospace; }
.markdown-body :deep(pre) { padding: 16px; overflow-x: auto; font-size: 13px; line-height: 1.6; background: #1e293b; color: #e2e8f0; border-radius: 10px; margin: 12px 0; border: none; }
.markdown-body :deep(pre code) { padding: 0; font-size: 13px; background: transparent; border: none; white-space: pre; color: inherit; }
.markdown-body :deep(blockquote) { padding: 8px 16px; color: #64748b; border-left: 3px solid #6366f1; background: #f8fafc; border-radius: 0 8px 8px 0; margin: 10px 0 14px; }
.markdown-body :deep(ul), .markdown-body :deep(ol) { padding-left: 1.4em; margin: 0 0 12px; }
.markdown-body :deep(li) { margin-bottom: 3px; }
.markdown-body :deep(table) { border-spacing: 0; border-collapse: collapse; display: block; width: 100%; overflow: auto; margin: 14px 0; font-size: 13px; border-radius: 8px; overflow: hidden; }
.markdown-body :deep(th), .markdown-body :deep(td) { padding: 8px 12px; border: 1px solid #e2e8f0; }
.markdown-body :deep(th) { font-weight: 600; background: #f8fafc; color: #334155; }
.markdown-body :deep(tr:nth-child(2n)) { background: #fafbfc; }
.markdown-body :deep(img) { max-width: 100%; border-radius: 8px; }
.markdown-body :deep(hr) { border: none; border-top: 1px solid #e2e8f0; margin: 16px 0; }
.markdown-body :deep(.cite-inline) { display: inline-flex; align-items: center; padding: 1px 7px; margin: 0 1px; background: #eef2ff; color: #4f46e5; border-radius: 4px; font-size: 12px; font-weight: 600; cursor: pointer; transition: all 0.15s; vertical-align: baseline; line-height: 1.4; }
.markdown-body :deep(.cite-inline:hover) { background: #c7d2fe; color: #3730a3; }

/* ===== Ref Download ===== */
.ref-download { display: inline-flex; align-items: center; justify-content: center; width: 24px; height: 24px; border: none; background: transparent; border-radius: 4px; cursor: pointer; color: #94a3b8; transition: all 0.12s; flex-shrink: 0; margin-left: auto; }
.ref-download:hover { background: #eef2ff; color: #6366f1; }

/* ===== Citation Popover ===== */
.cite-overlay { position: fixed; inset: 0; z-index: 2000; background: rgba(0,0,0,0.08); }
.cite-popover { position: fixed; width: 340px; max-height: 300px; background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; box-shadow: 0 8px 30px rgba(0,0,0,0.12); display: flex; flex-direction: column; overflow: hidden; animation: popIn 0.15s ease-out; }
@keyframes popIn { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: translateY(0); } }
.cite-popover-header { display: flex; align-items: center; gap: 8px; padding: 12px 14px 8px; }
.cite-popover-file { font-size: 13px; font-weight: 600; color: #1e293b; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; }
.cite-popover-tag { font-size: 11px; padding: 2px 8px; border-radius: 50vw; font-weight: 500; flex-shrink: 0; }
.cite-popover-meta { display: flex; gap: 4px; padding: 0 14px 8px; flex-wrap: wrap; }
.cite-popover-meta-tag { font-size: 11px; padding: 2px 7px; border-radius: 4px; background: #f1f5f9; color: #64748b; }
.cite-popover-content { flex: 1; min-height: 0; padding: 0 14px 10px; font-size: 12px; color: #64748b; line-height: 1.6; overflow-y: auto; white-space: pre-wrap; word-break: break-word; max-height: 140px; }
.cite-popover-content :deep(.cite-hl) { background: #fef08a; color: #854d0e; padding: 2px 4px; border-radius: 3px; line-height: 1.8; }
.cite-popover-actions { display: flex; justify-content: flex-end; gap: 6px; padding: 8px 14px 12px; border-top: 1px solid #f1f5f9; }
.cite-popover-btn { display: inline-flex; align-items: center; gap: 4px; padding: 6px 14px; font-size: 12px; font-weight: 500; border: 1px solid #e2e8f0; border-radius: 8px; background: #fff; color: #475569; cursor: pointer; transition: all 0.12s; }
.cite-popover-btn:hover { background: #f8fafc; border-color: #cbd5e1; }
.cite-popover-btn--primary { background: #6366f1; color: #fff; border-color: #6366f1; }
.cite-popover-btn--primary:hover { background: #4f46e5; border-color: #4f46e5; }

/* ===== Responsive ===== */
@media (max-width: 768px) {
  .chat-page { margin: -1.25rem -1rem; height: calc(100vh - 56px); }
  .chat-header { padding: 0 10px; }
  .chat-messages-inner { padding: 16px 12px; gap: 20px; }
  .msg-user-wrap { max-width: 85%; }
  .msg-ai-body { max-width: 90%; }
  .msg-ai-avatar { display: none; }
  .chat-footer { padding: 8px 12px 12px; }
  .chat-input-box { border-radius: 14px; }
  .header-kb-tag { display: none; }
  .intro-greeting { font-size: 20px; }
  .intro-logo { width: 48px; height: 48px; border-radius: 14px; }
  .msg-user-actions, .msg-ai-actions { opacity: 1; }
  .cite-popover { width: calc(100vw - 32px); left: 16px !important; }
}
</style>
