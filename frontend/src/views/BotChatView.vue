<script setup lang="ts">
import { nextTick, onMounted, ref, computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { Back, Promotion, Close, ChatRound, CopyDocument, Download } from "@element-plus/icons-vue";
import { botChat, getBot, type BotResponse, type BotChatSource, type BotChatRagInfo } from "../api/bot";
import { DownloadFile } from "../api/vectorDb";
import { streamBotChat, type StreamCallbacks } from "../utils/stream";

import { marked } from 'marked';
import DOMPurify from 'dompurify';
import hljs from 'highlight.js';
import 'highlight.js/styles/github.css';

const renderer = new marked.Renderer();
renderer.code = ({ text, lang }) => {
  const validLang = lang && hljs.getLanguage(lang) ? lang : 'plaintext';
  const highlighted = hljs.highlight(text, { language: validLang }).value;
  return `<pre><code class="hljs ${validLang}">${highlighted}</code></pre>`;
};
marked.setOptions({ renderer, breaks: true, gfm: true });

const renderMarkdown = (content: string) => {
  let html = DOMPurify.sanitize(marked.parse(content) as string, { ADD_ATTR: ['data-cite-index'] });
  html = html.replace(/\[来源(\d+)\]/g, '<span class="cite-inline" data-cite-index="$1">来源$1</span>');
  return html;
};

type QuoteInfo = {
  content: string;
  role: 'user' | 'assistant';
};

type ToolCallRecord = {
  tool: string;
  args: Record<string, unknown>;
  result?: Record<string, unknown>;
  callId: string;
  latencyMs?: number;
  status: 'calling' | 'done' | 'error';
};

type LocalMessage = {
  role: "user" | "assistant";
  content: string;
  quote?: QuoteInfo;
  forbidden_topic_hit?: string;
  model_name?: string;
  rag_info?: BotChatRagInfo;
  sources?: BotChatSource[];
  grounded_ratio?: number;
  grounded_level?: string;
  isStreaming?: boolean;
  agentState?: string;
  agentStateLabel?: string;
  toolCalls?: ToolCallRecord[];
  trace?: Record<string, unknown>;
};

const route = useRoute();
const router = useRouter();
const botId = Number(route.params.id);
const bot = ref<BotResponse | null>(null);
const messages = ref<LocalMessage[]>([]);
const input = ref("");
const sending = ref(false);
const conversationId = ref<string | undefined>();
const messageAreaRef = ref<HTMLElement | null>(null);

const loadBot = async () => {
  try {
    bot.value = await getBot(botId);
    if (bot.value.greeting) {
      messages.value.push({ role: "assistant", content: bot.value.greeting });
    } else {
      messages.value.push({ role: "assistant", content: "你好，请直接告诉我你想查询的问题。" });
    }
  } catch (error: unknown) {
    ElMessage.error(error?.response?.data?.detail || "数字助理不存在或无权访问");
    router.push("/bots");
  }
};

const scrollToBottom = () => {
  nextTick(() => {
    if (messageAreaRef.value) {
      messageAreaRef.value.scrollTop = messageAreaRef.value.scrollHeight;
    }
  });
};

const quotedMessage = ref<QuoteInfo | null>(null);

const handleQuoteMessage = (content: string, role: 'user' | 'assistant') => {
  quotedMessage.value = { content, role };
  nextTick(() => {
    const textarea = document.querySelector('.ds-textarea textarea') as HTMLTextAreaElement;
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

const copiedIndex = ref<number | null>(null);
const handleCopyMessage = (content: string, index: number) => {
  navigator.clipboard.writeText(content);
  copiedIndex.value = index;
  setTimeout(() => { copiedIndex.value = null; }, 1500);
};

const activeCite = ref<{ source: BotChatSource; rect: DOMRect } | null>(null);

const handleCiteClick = (e: MouseEvent) => {
  const target = (e.target as HTMLElement).closest('.cite-inline') as HTMLElement | null;
  if (!target) return;
  const citeIndex = parseInt(target.dataset.citeIndex || '0', 10) - 1;
  const msgEl = target.closest('.ds-msg') as HTMLElement | null;
  if (!msgEl) return;
  const msgIndex = msgEl.dataset.msgIndex
    ? parseInt(msgEl.dataset.msgIndex, 10)
    : Array.from(msgEl.parentElement!.children).indexOf(msgEl);
  if (msgIndex < 0 || msgIndex >= messages.value.length) return;
  const msg = messages.value[msgIndex];
  if (!msg?.sources?.length) return;
  const source = msg.sources[citeIndex] || msg.sources[0];
  activeCite.value = { source, rect: target.getBoundingClientRect() };
};

const closeCitePopover = () => { activeCite.value = null; };

const citePopoverStyle = computed(() => {
  if (!activeCite.value) return {};
  const r = activeCite.value.rect;
  const top = Math.min(r.bottom + 8, window.innerHeight - 320);
  const left = Math.max(16, Math.min(r.left, window.innerWidth - 360));
  return { top: `${top}px`, left: `${left}px` };
});

const handleDownloadSource = async (src: BotChatSource) => {
  const docId = (src as Record<string, unknown>).document_id;
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

const getToolLabel = (tool: string) => {
  const labels: Record<string, string> = {
    knowledge_search: '知识库检索', database_query: '数据库查询',
    calculator: '计算器', datetime_info: '日期时间', topic_analysis: '话题分析',
  };
  return labels[tool] || tool;
};

const sendMessage = async () => {
  const content = input.value.trim();
  if (!content || sending.value) return;
  const pendingQuote = quotedMessage.value ? { ...quotedMessage.value } : undefined;
  quotedMessage.value = null;
  input.value = "";
  const userMsg: LocalMessage = { role: "user", content };
  if (pendingQuote) userMsg.quote = pendingQuote;
  messages.value.push(userMsg);

  const aiMsg: LocalMessage = {
    role: "assistant",
    content: "",
    isStreaming: true,
    agentState: "planning",
    agentStateLabel: "分析问题中...",
    toolCalls: [],
  };
  messages.value.push(aiMsg);
  sending.value = true;
  scrollToBottom();

  const msgIndex = messages.value.length - 1;
  const callbacks: StreamCallbacks = {
    onToken(token) {
      messages.value[msgIndex].content += token;
      scrollToBottom();
    },
    onStateChange(state, label) {
      messages.value[msgIndex].agentState = state;
      messages.value[msgIndex].agentStateLabel = label;
    },
    onToolCall(tool, args, callId) {
      if (!messages.value[msgIndex].toolCalls) messages.value[msgIndex].toolCalls = [];
      messages.value[msgIndex].toolCalls!.push({ tool, args, callId, status: 'calling' });
      scrollToBottom();
    },
    onToolResult(tool, result, callId, latencyMs) {
      const tc = messages.value[msgIndex].toolCalls?.find(t => t.callId === callId);
      if (tc) { tc.result = result; tc.latencyMs = latencyMs; tc.status = result?.error ? 'error' : 'done'; }
    },
    onSources(sources) {
      messages.value[msgIndex].sources = sources as SourceCitation[];
    },
    onMetadata(metadata) {
      messages.value[msgIndex].grounded_ratio = metadata.grounded_ratio;
      messages.value[msgIndex].grounded_level = metadata.grounded_level;
      messages.value[msgIndex].model_name = metadata.model_name;
      if (metadata.conversation_id) conversationId.value = metadata.conversation_id;
    },
    onConversation(info) {
      if (info.conversation_id) conversationId.value = String(info.conversation_id);
    },
    onTrace(trace) {
      messages.value[msgIndex].trace = trace;
    },
    onDone() {
      messages.value[msgIndex].isStreaming = false;
      messages.value[msgIndex].agentState = 'done';
      sending.value = false;
      scrollToBottom();
    },
    onError(message) {
      if (!messages.value[msgIndex].content) messages.value[msgIndex].content = message;
      messages.value[msgIndex].isStreaming = false;
      sending.value = false;
    },
  };

  try {
    await streamBotChat(botId, content, conversationId.value, true, callbacks);
  } catch (error: unknown) {
    if (!messages.value[msgIndex].content) {
      messages.value[msgIndex].content = error?.message || "发送失败，请检查助理模型配置和知识库权限。";
    }
    messages.value[msgIndex].isStreaming = false;
    sending.value = false;
    scrollToBottom();
  }
};

const handleKeydown = (event: KeyboardEvent) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
};

const expandedSources = ref<number[]>([]);
const expandedSourceItems = ref<Set<string>>(new Set());

const toggleSources = (index: number) => {
  const pos = expandedSources.value.indexOf(index);
  if (pos >= 0) expandedSources.value.splice(pos, 1);
  else expandedSources.value.push(index);
};

const toggleSourceItem = (msgIdx: number, srcIdx: number) => {
  const key = `${msgIdx}-${srcIdx}`;
  if (expandedSourceItems.value.has(key)) expandedSourceItems.value.delete(key);
  else expandedSourceItems.value.add(key);
};

const isSourceItemExpanded = (msgIdx: number, srcIdx: number) =>
  expandedSourceItems.value.has(`${msgIdx}-${srcIdx}`);

const formatPercent = (v?: number) => (v != null ? (v * 100).toFixed(1) + "%" : "--");

const getRetrievalLabel = (method?: string) => {
  if (method === "hybrid") return "混合检索";
  if (method === "bm25") return "BM25";
  return "向量检索";
};

const getLevelClass = (level?: string) => {
  if (level === "高") return "ds-level--high";
  if (level === "中") return "ds-level--mid";
  if (level === "低") return "ds-level--low";
  return "ds-level--weak";
};

onMounted(loadBot);
</script>

<template>
  <div class="ds-bot-page">
    <!-- 顶部栏 -->
    <div class="ds-topbar">
      <button class="ds-topbar-btn" @click="router.push('/bots')">
        <el-icon :size="18"><Back /></el-icon>
      </button>
      <template v-if="bot">
        <el-avatar :size="28" :src="bot.avatar" class="ds-topbar-avatar">
          {{ bot.name.slice(0, 1) }}
        </el-avatar>
        <div class="ds-topbar-info">
          <span class="ds-topbar-name">{{ bot.name }}</span>
          <span class="ds-topbar-desc">{{ bot.description || '数字助理' }}</span>
        </div>
      </template>
    </div>

    <!-- 消息区域 -->
    <div ref="messageAreaRef" class="ds-messages">
      <div class="ds-messages-inner">
        <div
          v-for="(message, index) in messages"
          :key="index"
          class="ds-msg"
          :class="{ 'ds-msg--user': message.role === 'user', 'ds-msg--ai': message.role === 'assistant' }"
          :data-msg-index="index"
        >
          <!-- 用户消息 -->
          <template v-if="message.role === 'user'">
            <div class="ds-msg-user-row">
              <div class="ds-msg-user-wrap">
                <div class="ds-msg-user-actions">
                  <button class="ds-action-btn" @click="handleQuoteMessage(message.content, 'user')" title="引用">
                    <el-icon :size="13"><ChatRound /></el-icon>
                  </button>
                  <button class="ds-action-btn" @click="handleCopyMessage(message.content, index)" :title="copiedIndex === index ? '已复制' : '复制'">
                    <el-icon :size="13"><CopyDocument /></el-icon>
                  </button>
                </div>
                <div class="ds-msg-user-bubble">
                  <div v-if="message.quote" class="ds-quote-card" :class="{ 'ds-quote-card--ai': message.quote.role === 'assistant' }">
                    <span class="ds-quote-card-role">{{ message.quote.role === 'assistant' ? 'AI' : '我' }}</span>
                    <span class="ds-quote-card-text">{{ truncateQuote(message.quote.content, 80) }}</span>
                  </div>
                  {{ message.content }}
                </div>
              </div>
            </div>
          </template>

          <!-- AI 消息 -->
          <template v-else>
            <div class="ds-msg-ai-row">
              <el-avatar :size="28" :src="bot?.avatar" class="ds-msg-avatar-el">
                {{ bot?.name?.slice(0, 1) || '助' }}
              </el-avatar>
              <div class="ds-msg-ai-body">
                <div
                  v-if="message.forbidden_topic_hit"
                  class="ds-forbidden-tip"
                >
                  命中禁止话题：{{ message.forbidden_topic_hit }}
                </div>

                <!-- Agent 工具调用过程 -->
                <div class="ds-agent-process" v-if="message.toolCalls && message.toolCalls.length > 0">
                  <div class="ds-agent-header">
                    <span>{{ message.agentStateLabel || 'Agent 推理过程' }}</span>
                  </div>
                  <div class="ds-agent-step" v-for="(tc, ti) in message.toolCalls" :key="ti"
                       :class="{ 'is-calling': tc.status === 'calling' }">
                    <span class="ds-step-icon">{{ tc.status === 'calling' ? '⏳' : tc.status === 'error' ? '❌' : '✅' }}</span>
                    <span class="ds-step-tool">{{ getToolLabel(tc.tool) }}</span>
                    <span v-if="tc.latencyMs" class="ds-step-time">{{ tc.latencyMs }}ms</span>
                    <span v-if="tc.result?.count" class="ds-step-result">{{ tc.result.count }} 条结果</span>
                  </div>
                </div>

                <!-- 流式打字指示器 -->
                <div class="ds-streaming" v-if="message.isStreaming && !message.content && (!message.toolCalls || message.toolCalls.length === 0)">
                  <span class="ds-dot"><span></span><span></span><span></span></span>
                  <span class="ds-streaming-label">{{ message.agentStateLabel || '思考中...' }}</span>
                </div>

                <div
                  v-if="message.content"
                  class="ds-msg-ai-text markdown-body"
                  v-html="renderMarkdown(message.content)"
                  @click="handleCiteClick"
                ></div>
                <span v-if="message.isStreaming && message.content" class="ds-typing-cursor"></span>

                <!-- 元数据小卡片 -->
                <div v-if="message.model_name || message.rag_info" class="ds-meta-card">
                  <div class="ds-meta-tags">
                    <span v-if="message.model_name" class="ds-meta-tag ds-meta-tag--model">{{ message.model_name }}</span>
                    <span v-if="message.grounded_level" class="ds-meta-tag" :class="getLevelClass(message.grounded_level)">依据{{ message.grounded_level }}</span>
                    <span v-if="message.grounded_ratio" class="ds-meta-tag ds-meta-tag--plain">匹配 {{ formatPercent(message.grounded_ratio) }}</span>
                    <span v-if="message.rag_info?.total_results" class="ds-meta-tag ds-meta-tag--plain">{{ message.rag_info.total_results }} 条片段</span>
                    <span v-if="message.sources?.length" class="ds-meta-tag ds-meta-tag--plain">{{ getRetrievalLabel(message.sources[0]?.retrieval_method) }}</span>
                  </div>

                  <!-- 可展开的引用来源 -->
                  <div v-if="message.sources?.length" class="ds-ref-panel">
                    <div class="ds-ref-header" @click="toggleSources(index)">
                      <span>参考来源 ({{ message.sources.length }})</span>
                      <span class="ds-ref-arrow" :class="{ open: expandedSources.includes(index) }">&#9662;</span>
                    </div>
                    <div v-show="expandedSources.includes(index)" class="ds-ref-list">
                      <div v-for="(src, si) in message.sources" :key="si" class="ds-ref-item">
                        <div class="ds-ref-main" @click="toggleSourceItem(index, si)">
                          <span class="ds-ref-label">{{ src.citation_label || `[${si + 1}]` }}</span>
                          <span class="ds-ref-file">{{ src.source }}</span>
                          <span class="ds-meta-tag ds-meta-tag--sm" :class="getLevelClass(src.confidence_label)">{{ src.confidence_label || '中' }}</span>
                          <button v-if="(src as Record<string, unknown>).document_id" class="ds-ref-download" @click.stop="handleDownloadSource(src)" title="下载文档">
                            <el-icon :size="12"><Download /></el-icon>
                          </button>
                          <span class="ds-ref-expand">{{ isSourceItemExpanded(index, si) ? '收起' : '展开' }}</span>
                        </div>
                        <template v-if="isSourceItemExpanded(index, si)">
                          <div class="ds-ref-detail">
                            <span v-if="src.vector_db_name" class="ds-meta-tag ds-meta-tag--sm ds-meta-tag--plain">{{ src.vector_db_name }}</span>
                            <span class="ds-meta-tag ds-meta-tag--sm ds-meta-tag--plain">{{ getRetrievalLabel(src.retrieval_method) }}</span>
                            <span class="ds-meta-tag ds-meta-tag--sm ds-meta-tag--plain">向量 {{ formatPercent(src.vector_score || src.similarity) }}</span>
                            <span class="ds-meta-tag ds-meta-tag--sm ds-meta-tag--plain">BM25 {{ formatPercent(src.bm25_score) }}</span>
                            <span class="ds-meta-tag ds-meta-tag--sm ds-meta-tag--plain">RRF {{ formatPercent(src.final_score) }}</span>
                          </div>
                          <div class="ds-ref-text">{{ src.content }}</div>
                        </template>
                      </div>
                    </div>
                  </div>
                </div>
                <div class="ds-msg-ai-actions">
                  <button class="ds-action-btn" @click="handleCopyMessage(message.content, index)" :title="copiedIndex === index ? '已复制' : '复制'">
                    <el-icon :size="13"><CopyDocument /></el-icon>
                    <span v-if="copiedIndex === index" class="ds-action-tip">已复制</span>
                  </button>
                  <button class="ds-action-btn" @click="handleQuoteMessage(message.content, 'assistant')" title="引用">
                    <el-icon :size="13"><ChatRound /></el-icon>
                  </button>
                </div>
              </div>
            </div>
          </template>
        </div>

        <!-- 加载中 -->
        <div v-if="sending" class="ds-msg ds-msg--ai">
          <div class="ds-msg-ai-row">
            <el-avatar :size="28" :src="bot?.avatar" class="ds-msg-avatar-el">
              {{ bot?.name?.slice(0, 1) || '助' }}
            </el-avatar>
            <div class="ds-msg-ai-body">
              <div class="ds-loading">
                <span class="ds-loading-dot"></span>
                <span class="ds-loading-dot"></span>
                <span class="ds-loading-dot"></span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 输入区域 -->
    <div class="ds-input-area">
      <div class="ds-input-box">
        <!-- 引用预览条 -->
        <div class="ds-quote-preview" v-if="quotedMessage">
          <div class="ds-quote-preview-body">
            <span class="ds-quote-preview-role">{{ quotedMessage.role === 'assistant' ? 'AI' : '我' }}</span>
            <span class="ds-quote-preview-text">{{ truncateQuote(quotedMessage.content) }}</span>
          </div>
          <button class="ds-quote-preview-close" @click="clearQuote">
            <el-icon :size="14"><Close /></el-icon>
          </button>
        </div>
        <el-input
          v-model="input"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 5 }"
          resize="none"
          placeholder="输入消息，Enter 发送，Shift+Enter 换行"
          @keydown="handleKeydown"
          class="ds-textarea"
        />
        <div class="ds-input-toolbar">
          <div></div>
          <button
            class="ds-send-btn"
            :class="{ active: input.trim() !== '' && !sending }"
            @click="sendMessage"
          >
            <el-icon :size="16"><Promotion /></el-icon>
          </button>
        </div>
      </div>
    </div>
    <!-- 引用来源弹窗 -->
    <div v-if="activeCite" class="ds-cite-overlay" @click.self="closeCitePopover">
      <div class="ds-cite-popover" :style="citePopoverStyle">
        <div class="ds-cite-popover-header">
          <span class="ds-cite-popover-file">{{ activeCite.source.source }}</span>
          <span class="ds-meta-tag ds-meta-tag--sm" :class="getLevelClass((activeCite.source as Record<string, unknown>).confidence_label)">{{ (activeCite.source as Record<string, unknown>).confidence_label || '中' }}</span>
        </div>
        <div class="ds-cite-popover-meta">
          <span v-if="activeCite.source.vector_db_name" class="ds-cite-popover-meta-tag">{{ activeCite.source.vector_db_name }}</span>
          <span class="ds-cite-popover-meta-tag">{{ getRetrievalLabel(activeCite.source.retrieval_method) }}</span>
        </div>
        <div class="ds-cite-popover-content">{{ activeCite.source.content }}</div>
        <div class="ds-cite-popover-actions">
          <button v-if="(activeCite.source as Record<string, unknown>).document_id" class="ds-cite-btn ds-cite-btn--primary" @click="handleDownloadSource(activeCite.source)">
            <el-icon :size="13"><Download /></el-icon>
            下载文档
          </button>
          <button class="ds-cite-btn" @click="closeCitePopover">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ds-bot-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 100px);
  background: #fafafa;
  overflow: hidden;
}

/* ===== 顶部栏 ===== */
.ds-topbar {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 48px;
  padding: 0 20px;
  border-bottom: 1px solid #f0f0f0;
  background: #fff;
  flex-shrink: 0;
}

.ds-topbar-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  background: none;
  border-radius: 6px;
  cursor: pointer;
  color: #666;
  transition: background 0.15s;
}

.ds-topbar-btn:hover {
  background: #f5f5f5;
}

.ds-topbar-avatar {
  flex-shrink: 0;
}

.ds-topbar-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.ds-topbar-name {
  font-size: 14px;
  font-weight: 500;
  color: #1a1a1a;
  line-height: 1.2;
}

.ds-topbar-desc {
  font-size: 12px;
  color: #999;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: min(500px, 50vw);
  line-height: 1.2;
}

/* ===== 消息区域 ===== */
.ds-messages {
  flex: 1;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: #e0e0e0 transparent;
}

.ds-messages::-webkit-scrollbar {
  width: 4px;
}

.ds-messages::-webkit-scrollbar-thumb {
  background: #e0e0e0;
  border-radius: 2px;
}

.ds-messages-inner {
  max-width: 800px;
  margin: 0 auto;
  padding: 24px 20px 16px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

/* ===== 消息通用 ===== */
.ds-msg {
  animation: msgFadeIn 0.2s ease-out;
}

@keyframes msgFadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ===== 用户消息 ===== */
.ds-msg-user-row {
  display: flex;
  justify-content: flex-end;
}

.ds-msg-user-wrap {
  display: flex;
  align-items: flex-end;
  gap: 6px;
  max-width: 80%;
}

.ds-msg-user-actions {
  display: flex;
  gap: 2px;
  opacity: 0;
  transition: opacity 0.15s;
  flex-shrink: 0;
  padding-bottom: 4px;
}
.ds-msg-user-row:hover .ds-msg-user-actions { opacity: 1; }

.ds-msg-user-bubble {
  max-width: 100%;
  padding: 10px 16px;
  background: #f4f4f5;
  border-radius: 18px 18px 4px 18px;
  color: #1a1a1a;
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
  white-space: pre-wrap;
}

/* ===== AI 消息 ===== */
.ds-msg-ai-row {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.ds-msg-avatar-el {
  flex-shrink: 0;
  margin-top: 2px;
  font-size: 12px;
}

.ds-msg-ai-body {
  flex: 1;
  min-width: 0;
}

.ds-msg-ai-text {
  color: #1a1a1a;
  font-size: 14px;
  line-height: 1.7;
  word-break: break-word;
}

.ds-forbidden-tip {
  padding: 6px 12px;
  background: #fff8e6;
  border: 1px solid #ffe58f;
  border-radius: 6px;
  font-size: 12px;
  color: #ad6800;
  margin-bottom: 8px;
}

/* ===== 加载动画 ===== */
.ds-loading {
  display: flex;
  gap: 4px;
  padding: 8px 0;
}

.ds-loading-dot {
  width: 6px;
  height: 6px;
  background: #ccc;
  border-radius: 50%;
  animation: dotBounce 1.4s ease-in-out infinite;
}

.ds-loading-dot:nth-child(1) { animation-delay: 0s; }
.ds-loading-dot:nth-child(2) { animation-delay: 0.16s; }
.ds-loading-dot:nth-child(3) { animation-delay: 0.32s; }

@keyframes dotBounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

/* ===== Action Buttons ===== */
.ds-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  height: 28px;
  padding: 0 6px;
  min-width: 28px;
  border: none;
  background: transparent;
  border-radius: 6px;
  cursor: pointer;
  color: #999;
  transition: all 0.15s;
}
.ds-action-btn:hover { background: #f5f5f5; color: #1a1a1a; }
.ds-action-tip { font-size: 11px; color: #52c41a; font-weight: 500; }

.ds-msg-ai-actions {
  display: flex;
  gap: 2px;
  margin-top: 6px;
  opacity: 0;
  transition: opacity 0.15s;
}
.ds-msg-ai-row:hover .ds-msg-ai-actions { opacity: 1; }

/* ===== Quote Card (in message bubble) ===== */
.ds-quote-card {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 8px 10px;
  margin-bottom: 8px;
  background: rgba(0, 0, 0, 0.03);
  border-left: 3px solid #d0d0d0;
  border-radius: 0 8px 8px 0;
  font-size: 12px;
  line-height: 1.5;
  color: #666;
}
.ds-quote-card--ai { border-left-color: #1a1a1a; }
.ds-quote-card-role {
  flex-shrink: 0;
  font-weight: 600;
  color: #1a1a1a;
  font-size: 11px;
  padding: 1px 6px;
  background: #f0f0f0;
  border-radius: 4px;
  line-height: 1.4;
}
.ds-quote-card-text { color: #666; word-break: break-word; }

/* ===== Quote Preview Bar (above input) ===== */
.ds-quote-preview {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 14px;
  background: #fafafa;
  border-bottom: 1px solid #f0f0f0;
}
.ds-quote-preview-body {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1;
}
.ds-quote-preview-role {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 600;
  color: #1a1a1a;
  padding: 1px 6px;
  background: #f0f0f0;
  border-radius: 4px;
}
.ds-quote-preview-text {
  font-size: 12px;
  color: #999;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}
.ds-quote-preview-close {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: none;
  background: transparent;
  border-radius: 50%;
  cursor: pointer;
  color: #999;
  transition: all 0.12s;
}
.ds-quote-preview-close:hover { background: #f0f0f0; color: #333; }

/* ===== 输入区域 ===== */
.ds-input-area {
  flex-shrink: 0;
  padding: 12px 20px 20px;
  display: flex;
  justify-content: center;
  background: linear-gradient(to top, #fafafa 80%, transparent);
}

.ds-input-box {
  max-width: 800px;
  width: 100%;
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 16px;
  overflow: hidden;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.ds-input-box:focus-within {
  border-color: #d0d0d0;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}

:deep(.ds-textarea .el-textarea__inner) {
  border: none !important;
  box-shadow: none !important;
  padding: 12px 16px;
  font-size: 14px;
  line-height: 1.5;
  resize: none;
  background: transparent;
  min-height: 40px;
  max-height: 160px;
  color: #1a1a1a;
}

:deep(.ds-textarea .el-textarea__inner::placeholder) {
  color: #bbb;
}

.ds-input-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px 8px;
}

.ds-send-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  background: #e0e0e0;
  border-radius: 8px;
  cursor: pointer;
  color: #fff;
  transition: all 0.2s;
}

.ds-send-btn.active {
  background: #1a1a1a;
}

.ds-send-btn.active:hover {
  background: #333;
}

/* ===== Markdown 样式 ===== */
.markdown-body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  font-size: 14px;
  line-height: 1.7;
  word-wrap: break-word;
}

.markdown-body :deep(h1) {
  font-size: 1.4em;
  font-weight: 600;
  margin: 16px 0 8px;
  padding-bottom: 4px;
  border-bottom: 1px solid #f0f0f0;
}

.markdown-body :deep(h2) {
  font-size: 1.25em;
  font-weight: 600;
  margin: 14px 0 6px;
  padding-bottom: 4px;
  border-bottom: 1px solid #f0f0f0;
}

.markdown-body :deep(h3) {
  font-size: 1.1em;
  font-weight: 600;
  margin: 12px 0 4px;
}

.markdown-body :deep(p) {
  margin: 0 0 12px;
}

.markdown-body :deep(p:last-child) {
  margin-bottom: 0;
}

.markdown-body :deep(a) {
  color: #4080ff;
  text-decoration: none;
}

.markdown-body :deep(a:hover) {
  text-decoration: underline;
}

.markdown-body :deep(code) {
  padding: 2px 5px;
  font-size: 13px;
  background: #f5f5f5;
  border-radius: 4px;
  font-family: "SF Mono", "Monaco", "Menlo", "Consolas", monospace;
}

.markdown-body :deep(pre) {
  padding: 14px 16px;
  overflow-x: auto;
  font-size: 13px;
  line-height: 1.5;
  background: #f8f8f8;
  border-radius: 8px;
  margin: 12px 0;
  border: 1px solid #f0f0f0;
}

.markdown-body :deep(pre code) {
  padding: 0;
  font-size: 13px;
  background: transparent;
  border: none;
  white-space: pre;
  word-wrap: normal;
}

.markdown-body :deep(blockquote) {
  padding: 0 14px;
  color: #666;
  border-left: 3px solid #e0e0e0;
  margin: 8px 0 12px;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  padding-left: 1.5em;
  margin: 0 0 12px;
}

.markdown-body :deep(li) {
  margin-bottom: 4px;
}

.markdown-body :deep(table) {
  border-spacing: 0;
  border-collapse: collapse;
  display: block;
  width: 100%;
  overflow: auto;
  margin: 12px 0;
  font-size: 13px;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  padding: 8px 12px;
  border: 1px solid #eee;
}

.markdown-body :deep(th) {
  font-weight: 600;
  background: #fafafa;
}

.markdown-body :deep(tr:nth-child(2n)) {
  background: #fafafa;
}

.markdown-body :deep(img) {
  max-width: 100%;
  border-radius: 4px;
}

/* ===== 元数据小卡片 ===== */
.ds-meta-card {
  margin-top: 8px;
  padding: 8px 10px;
  background: #f8f9fb;
  border: 1px solid #eef0f4;
  border-radius: 8px;
}

.ds-meta-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.ds-meta-tag {
  display: inline-flex;
  align-items: center;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 50vw;
  font-weight: 500;
  line-height: 1.5;
  white-space: nowrap;
}

.ds-meta-tag--model {
  background: #eef2ff;
  color: #4f46e5;
}

.ds-meta-tag--plain {
  background: #f1f5f9;
  color: #64748b;
}

.ds-meta-tag--sm {
  font-size: 10px;
  padding: 1px 6px;
}

.ds-level--high { background: #dcfce7; color: #166534; }
.ds-level--mid { background: #fef9c3; color: #854d0e; }
.ds-level--low { background: #fee2e2; color: #991b1b; }
.ds-level--weak { background: #f1f5f9; color: #94a3b8; }

/* ===== 引用来源面板 ===== */
.ds-ref-panel {
  margin-top: 8px;
  border: 1px solid #eef0f4;
  border-radius: 6px;
  overflow: hidden;
}

.ds-ref-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 5px 10px;
  font-size: 11px;
  color: #64748b;
  cursor: pointer;
  background: #fff;
  user-select: none;
}

.ds-ref-header:hover {
  background: #f8fafc;
}

.ds-ref-arrow {
  font-size: 10px;
  transition: transform 0.2s;
  color: #94a3b8;
}

.ds-ref-arrow.open {
  transform: rotate(180deg);
}

.ds-ref-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 4px 6px 6px;
}

.ds-ref-item {
  padding: 6px 8px;
  background: #fff;
  border: 1px solid #f1f5f9;
  border-radius: 6px;
}

.ds-ref-main {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}

.ds-ref-label {
  font-weight: 600;
  color: #6366f1;
  font-size: 11px;
  flex-shrink: 0;
}

.ds-ref-file {
  color: #334155;
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 180px;
}

.ds-ref-expand {
  margin-left: auto;
  font-size: 10px;
  color: #6366f1;
  cursor: pointer;
  flex-shrink: 0;
  font-weight: 500;
}

.ds-ref-detail {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed #f1f5f9;
}

.ds-ref-text {
  font-size: 11px;
  color: #64748b;
  line-height: 1.5;
  margin-top: 6px;
  padding: 6px 8px;
  background: #f8fafc;
  border-radius: 4px;
  max-height: 120px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

/* ===== Inline Citation Tag ===== */
.markdown-body :deep(.cite-inline) {
  display: inline-flex;
  align-items: center;
  padding: 1px 7px;
  margin: 0 1px;
  background: #f0f0f0;
  color: #1a1a1a;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  vertical-align: baseline;
  line-height: 1.4;
}
.markdown-body :deep(.cite-inline:hover) {
  background: #e0e0e0;
  color: #000;
}

/* ===== Ref Download Button ===== */
.ds-ref-download {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: none;
  background: transparent;
  border-radius: 4px;
  cursor: pointer;
  color: #999;
  transition: all 0.12s;
  flex-shrink: 0;
}
.ds-ref-download:hover { background: #f0f0f0; color: #1a1a1a; }

/* ===== Citation Popover (Teleported) ===== */
.ds-cite-overlay {
  position: fixed;
  inset: 0;
  z-index: 2000;
  background: rgba(0,0,0,0.08);
}
.ds-cite-popover {
  position: fixed;
  width: 340px;
  max-height: 300px;
  background: #fff;
  border: 1px solid #e8e8e8;
  border-radius: 12px;
  box-shadow: 0 8px 30px rgba(0,0,0,0.12);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: dsCiteIn 0.15s ease-out;
}
@keyframes dsCiteIn {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}
.ds-cite-popover-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 14px 8px;
}
.ds-cite-popover-file {
  font-size: 13px;
  font-weight: 600;
  color: #1a1a1a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}
.ds-cite-popover-meta {
  display: flex;
  gap: 4px;
  padding: 0 14px 8px;
  flex-wrap: wrap;
}
.ds-cite-popover-meta-tag {
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 4px;
  background: #f5f5f5;
  color: #666;
}
.ds-cite-popover-content {
  flex: 1;
  min-height: 0;
  padding: 0 14px 10px;
  font-size: 12px;
  color: #666;
  line-height: 1.6;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 140px;
}
.ds-cite-popover-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
  padding: 8px 14px 12px;
  border-top: 1px solid #f0f0f0;
}
.ds-cite-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 14px;
  font-size: 12px;
  font-weight: 500;
  border: 1px solid #e8e8e8;
  border-radius: 8px;
  background: #fff;
  color: #666;
  cursor: pointer;
  transition: all 0.12s;
}
.ds-cite-btn:hover { background: #fafafa; border-color: #d0d0d0; }
.ds-cite-btn--primary {
  background: #1a1a1a;
  color: #fff;
  border-color: #1a1a1a;
}
.ds-cite-btn--primary:hover { background: #333; border-color: #333; }

/* ===== Agent Process ===== */
.ds-agent-process {
  margin-bottom: 10px;
  padding: 8px 10px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 8px;
}
.ds-agent-header { font-size: 12px; font-weight: 600; color: #166534; margin-bottom: 6px; }
.ds-agent-step { display: flex; align-items: center; gap: 6px; padding: 4px 8px; background: #fff; border-radius: 6px; margin-bottom: 4px; font-size: 12px; }
.ds-agent-step.is-calling { background: #fffbeb; }
.ds-step-icon { font-size: 12px; }
.ds-step-tool { font-weight: 600; color: #1e293b; }
.ds-step-time { color: #94a3b8; margin-left: auto; font-size: 11px; }
.ds-step-result { color: #059669; font-size: 11px; }

/* ===== Streaming ===== */
.ds-streaming { display: flex; align-items: center; gap: 8px; padding: 4px 0; }
.ds-streaming-label { font-size: 13px; color: #94a3b8; }
.ds-dot { display: inline-flex; gap: 3px; }
.ds-dot span { width: 5px; height: 5px; border-radius: 50%; background: #94a3b8; animation: dsBounce 1.4s infinite ease-in-out both; }
.ds-dot span:nth-child(1) { animation-delay: -0.32s; }
.ds-dot span:nth-child(2) { animation-delay: -0.16s; }
@keyframes dsBounce { 0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; } 40% { transform: scale(1); opacity: 1; } }
.ds-typing-cursor { display: inline-block; width: 2px; height: 14px; background: #1a1a1a; animation: dsBlink 0.8s step-end infinite; vertical-align: text-bottom; }
@keyframes dsBlink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }

/* ===== 响应式 ===== */
@media (max-width: 768px) {
  .ds-messages-inner {
    padding: 16px 12px;
  }

  .ds-msg-user-bubble {
    max-width: 90%;
  }

  .ds-input-area {
    padding: 8px 12px 12px;
  }

  .ds-msg-user-actions, .ds-msg-ai-actions { opacity: 1; }
  .ds-cite-popover { width: calc(100vw - 32px); left: 16px !important; }
}
</style>
