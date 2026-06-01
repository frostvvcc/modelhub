<!-- src/views/ChatHistoryView.vue -->
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import type { Conversation } from '../types/chat';
import { getModelConfig } from '../api/model';
import { getConversations, deleteConversation } from '../api/chat';
import { getFormatTimeString } from '../utils/common';
import { ElMessage, ElMessageBox } from 'element-plus';
import { Search, Clock, ChatDotRound, Delete, ChatLineSquare, Refresh } from '@element-plus/icons-vue';

const router = useRouter();

const searchQuery = ref('');
const selectedDateRange = ref('all');
const loading = ref(false);
const detailVisible = ref(false);
const detailData = ref<Conversation>({
  id: 0, name: '', messages: [], model_config_id: 0,
  chat_history: 10, create_at: '', update_at: '', type: 0
});

const histories = ref<Conversation[]>([]);
const selectedIds = ref<Set<number>>(new Set());

const filteredHistories = computed(() => {
  let filtered = histories.value.filter(history => {
    const matchesSearch = !searchQuery.value ||
      history.name.toLowerCase().includes(searchQuery.value.toLowerCase());
    let matchesDate = true;
    if (selectedDateRange.value !== 'all') {
      const date = new Date(history.update_at);
      const now = new Date();
      const diffDays = Math.floor((now.getTime() - date.getTime()) / (1000 * 60 * 60 * 24));
      const range = parseInt(selectedDateRange.value);
      matchesDate = range === 0 ? diffDays === 0 : diffDays < range;
    }
    return matchesSearch && matchesDate;
  });
  return filtered.sort((a, b) => new Date(b.update_at).getTime() - new Date(a.update_at).getTime());
});

const isAllSelected = computed(() =>
  filteredHistories.value.length > 0 && filteredHistories.value.every(h => selectedIds.value.has(h.id))
);

const toggleSelect = (id: number, e: Event) => {
  e.stopPropagation();
  if (selectedIds.value.has(id)) selectedIds.value.delete(id);
  else selectedIds.value.add(id);
};

const toggleSelectAll = () => {
  if (isAllSelected.value) {
    selectedIds.value.clear();
  } else {
    filteredHistories.value.forEach(h => selectedIds.value.add(h.id));
  }
};

const modelName = ref('');

const showDetail = async (history: Conversation) => {
  detailData.value = history;
  detailVisible.value = true;
  const model_config = await getModelConfig(history.model_config_id);
  modelName.value = model_config?.name || '未知模型配置';
};

const continueChat = async (history: Conversation) => {
  const model_config = await getModelConfig(history.model_config_id);
  modelName.value = model_config?.name || '未知模型配置';
  router.push({
    path: '/chat',
    query: { conversation_id: history.id, config_name: modelName.value, model_config_id: history.model_config_id }
  });
};

const handleDelete = async (history: Conversation) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除对话「${history.name}」吗？删除后不可恢复。`,
      '删除确认',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    );
    await deleteConversation(history.id);
    histories.value = histories.value.filter(h => h.id !== history.id);
    selectedIds.value.delete(history.id);
    ElMessage.success('对话已删除');
    if (detailVisible.value && detailData.value.id === history.id) {
      detailVisible.value = false;
    }
  } catch {}
};

const handleBatchDelete = async () => {
  if (selectedIds.value.size === 0) return;
  try {
    await ElMessageBox.confirm(
      `确定要删除选中的 ${selectedIds.value.size} 个对话吗？删除后不可恢复。`,
      '批量删除确认',
      { confirmButtonText: '全部删除', cancelButtonText: '取消', type: 'warning' }
    );
    const ids = [...selectedIds.value];
    await Promise.all(ids.map(id => deleteConversation(id)));
    histories.value = histories.value.filter(h => !ids.includes(h.id));
    selectedIds.value.clear();
    ElMessage.success(`已删除 ${ids.length} 个对话`);
  } catch {}
};

const loadData = async () => {
  loading.value = true;
  try {
    histories.value = await getConversations();
    histories.value.forEach(history => {
      if (history.messages) {
        history.messages.sort((a, b) =>
          new Date(a.create_at).getTime() - new Date(b.create_at).getTime()
        );
      }
    });
    selectedIds.value.clear();
  } catch {
    ElMessage.error('获取对话历史失败');
  } finally {
    loading.value = false;
  }
};

const getLastMessage = (history: Conversation) => {
  if (!history.messages || history.messages.length === 0) return '暂无消息';
  const last = history.messages[history.messages.length - 1];
  const text = last.content.replace(/\n/g, ' ').trim();
  return text.length > 60 ? text.slice(0, 60) + '...' : text;
};

const truncateContent = (content: string, maxLen = 80) => {
  const text = content.replace(/\n/g, ' ').trim();
  return text.length > maxLen ? text.slice(0, maxLen) + '...' : text;
};

onMounted(loadData);
</script>

<template>
  <div class="page-container">
    <div class="content-section">
      <h2>对话历史</h2>
      <p class="subtitle">查看和管理您的历史对话记录</p>

      <!-- 工具栏：搜索 + 筛选 + 操作 合并为一行 -->
      <div class="toolbar">
        <div class="toolbar-left">
          <el-input
            v-model="searchQuery"
            placeholder="搜索对话..."
            clearable
            :prefix-icon="Search"
            class="toolbar-search"
          />
          <el-select v-model="selectedDateRange" class="toolbar-date">
            <el-option label="全部时间" value="all" />
            <el-option label="今天" value="0" />
            <el-option label="最近7天" value="7" />
            <el-option label="最近30天" value="30" />
          </el-select>
        </div>
        <div class="toolbar-right">
          <el-button :icon="Refresh" @click="loadData" />
          <transition name="fade">
            <el-button
              v-if="selectedIds.size > 0"
              type="danger"
              :icon="Delete"
              @click="handleBatchDelete"
            >
              删除 ({{ selectedIds.size }})
            </el-button>
          </transition>
        </div>
      </div>

      <!-- 全选栏 -->
      <div class="select-bar" v-if="filteredHistories.length > 0">
        <label class="select-all" @click="toggleSelectAll">
          <span class="checkbox" :class="{ checked: isAllSelected }">
            <svg v-if="isAllSelected" viewBox="0 0 12 12" fill="none"><path d="M2.5 6L5 8.5L9.5 3.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </span>
          <span>{{ isAllSelected ? '取消全选' : '全选' }}</span>
        </label>
        <span class="select-bar-count">共 {{ filteredHistories.length }} 个对话</span>
      </div>

      <!-- 对话列表 -->
      <div v-loading="loading" class="history-list">
        <el-empty
          v-if="!loading && filteredHistories.length === 0"
          :description="histories.length === 0 ? '暂无对话记录，快去开启一个新对话吧' : '没有匹配的对话记录'"
        />

        <div
          v-for="history in filteredHistories"
          :key="history.id"
          class="history-card"
          :class="{ selected: selectedIds.has(history.id) }"
          @click="showDetail(history)"
        >
          <span
            class="card-checkbox"
            :class="{ checked: selectedIds.has(history.id) }"
            @click="toggleSelect(history.id, $event)"
          >
            <svg v-if="selectedIds.has(history.id)" viewBox="0 0 12 12" fill="none"><path d="M2.5 6L5 8.5L9.5 3.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </span>
          <div class="card-content">
            <div class="card-head">
              <div class="card-title">
                <el-icon :size="16" color="#6366f1"><ChatLineSquare /></el-icon>
                <h3>{{ history.name }}</h3>
              </div>
              <div class="card-meta-inline">
                <span class="meta-count-pill">{{ history.count || history.messages.length }} 条</span>
              </div>
            </div>
            <p class="card-preview">{{ getLastMessage(history) }}</p>
            <div class="card-foot">
              <span class="meta-time">
                <el-icon :size="13"><Clock /></el-icon>
                {{ getFormatTimeString(history.update_at) }}
              </span>
              <div class="card-actions">
                <el-button size="small" text type="primary" @click.stop="continueChat(history)">继续对话</el-button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 详情弹窗 -->
      <el-dialog v-model="detailVisible" :title="detailData.name" width="60%" destroy-on-close>
        <div class="dialog-meta">
          <span><el-icon :size="14"><Clock /></el-icon> {{ getFormatTimeString(detailData.update_at) }}</span>
          <span><el-icon :size="14"><ChatDotRound /></el-icon> {{ detailData.count || detailData.messages.length }} 条消息</span>
          <span class="model-tag">{{ modelName }}</span>
        </div>
        <div class="dialog-messages">
          <div
            v-for="(message, idx) in detailData.messages"
            :key="idx"
            class="message-bubble"
            :class="message.role === 'user' ? 'bubble-user' : 'bubble-assistant'"
          >
            <div class="bubble-role">{{ message.role === 'user' ? '用户' : 'AI' }}</div>
            <div class="bubble-content">{{ truncateContent(message.content, 200) }}</div>
          </div>
          <div v-if="detailData.messages.length === 0" class="no-messages">暂无消息记录</div>
        </div>
        <template #footer>
          <div class="dialog-footer">
            <el-button type="danger" text :icon="Delete" @click="handleDelete(detailData)">删除对话</el-button>
            <div>
              <el-button @click="detailVisible = false">关闭</el-button>
              <el-button type="primary" @click="continueChat(detailData)">继续对话</el-button>
            </div>
          </div>
        </template>
      </el-dialog>
    </div>
  </div>
</template>

<style scoped>
/* ── 工具栏 ── */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
}
.toolbar-search {
  width: 240px;
  flex-shrink: 0;
}
.toolbar-date {
  width: 130px;
  flex-shrink: 0;
}
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

/* ── 全选栏 ── */
.select-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 4px;
  margin-bottom: 8px;
  font-size: 13px;
  color: #64748b;
}
.select-all {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  user-select: none;
  font-weight: 500;
}
.select-all:hover { color: #6366f1; }
.select-bar-count { font-size: 12px; color: #94a3b8; }

/* ── 自定义 Checkbox ── */
.checkbox,
.card-checkbox {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border: 1.5px solid #cbd5e1;
  border-radius: 5px;
  background: #fff;
  color: #fff;
  transition: all 0.15s;
  flex-shrink: 0;
  cursor: pointer;
}
.checkbox svg,
.card-checkbox svg {
  width: 12px;
  height: 12px;
}
.checkbox.checked,
.card-checkbox.checked {
  background: #6366f1;
  border-color: #6366f1;
}

/* ── 对话列表 ── */
.history-list {
  min-height: 200px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* ── 对话卡片 ── */
.history-card {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  border: 1.5px solid #eef0f4;
  border-radius: 12px;
  padding: 14px 16px;
  background: #fff;
  cursor: pointer;
  transition: all 0.15s;
}
.history-card:hover {
  border-color: #c7d2fe;
  box-shadow: 0 2px 12px rgba(99, 102, 241, 0.06);
}
.history-card.selected {
  border-color: #a5b4fc;
  background: #faf9ff;
}
.history-card .card-checkbox {
  margin-top: 2px;
}

.card-content {
  flex: 1;
  min-width: 0;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
  flex: 1;
}
.card-title h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-meta-inline {
  flex-shrink: 0;
}
.meta-count-pill {
  font-size: 11px;
  color: #6366f1;
  background: #eef2ff;
  padding: 2px 8px;
  border-radius: 50vw;
  font-weight: 500;
}

.card-preview {
  margin: 0 0 8px;
  color: #64748b;
  font-size: 13px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.meta-time {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #94a3b8;
}

.card-actions {
  flex-shrink: 0;
}

/* ── Fade 动画 ── */
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

/* ── 详情弹窗 ── */
.dialog-meta {
  display: flex;
  align-items: center;
  gap: 20px;
  padding-bottom: 14px;
  margin-bottom: 16px;
  border-bottom: 1px solid #f1f5f9;
  font-size: 0.85rem;
  color: #64748b;
}
.dialog-meta span {
  display: flex;
  align-items: center;
  gap: 4px;
}
.model-tag {
  background: #eef2ff;
  color: #6366f1;
  padding: 2px 10px;
  border-radius: 4px;
  font-size: 0.8rem;
}

.dialog-messages {
  max-height: 400px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 4px 0;
}

.message-bubble {
  padding: 12px 16px;
  border-radius: 12px;
  max-width: 85%;
  font-size: 0.9rem;
  line-height: 1.6;
  word-break: break-word;
}
.bubble-user {
  background: #eef2ff;
  color: #312e81;
  align-self: flex-end;
  border-bottom-right-radius: 4px;
}
.bubble-assistant {
  background: #f8fafc;
  color: #334155;
  align-self: flex-start;
  border-bottom-left-radius: 4px;
  border: 1px solid #e8ecf2;
}
.bubble-role {
  font-size: 0.75rem;
  font-weight: 600;
  color: #94a3b8;
  margin-bottom: 4px;
}
.bubble-user .bubble-role {
  color: #818cf8;
  text-align: right;
}
.no-messages {
  text-align: center;
  color: #94a3b8;
  padding: 40px 0;
}

.dialog-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

/* ── 响应式 ── */
@media (max-width: 768px) {
  .toolbar {
    flex-direction: column;
    align-items: stretch;
  }
  .toolbar-left {
    flex-direction: column;
  }
  .toolbar-search,
  .toolbar-date {
    width: 100%;
  }
  .card-foot {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
  .dialog-meta {
    flex-wrap: wrap;
    gap: 12px;
  }
}
</style>
