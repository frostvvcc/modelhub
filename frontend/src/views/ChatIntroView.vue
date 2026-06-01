<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { ArrowRight, ChatDotRound, Tickets, Clock } from '@element-plus/icons-vue';
import { listBots, type BotResponse } from '../api/bot';
import { getConversations } from '../api/chat';
import { getModelConfig } from '../api/model';
import { useUserStore } from '../stores/user';
import { getCurrentStatus } from '../utils/common';
import type { Conversation } from '../types/chat';

const router = useRouter();
const userStore = useUserStore();

const currentTime = ref('');
const bots = ref<BotResponse[]>([]);
const conversations = ref<Conversation[]>([]);
const configNames = ref<Record<number, string>>({});
const loading = ref(false);

const recentConversations = computed(() => {
  return [...conversations.value]
    .sort((a, b) => new Date(b.update_at).getTime() - new Date(a.update_at).getTime())
    .slice(0, 6);
});

const hasRecentConversations = computed(() => recentConversations.value.length > 0);

function formatRelativeTime(timeStr: string): string {
  const now = new Date();
  const t = new Date(timeStr);
  const diffMs = now.getTime() - t.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return '刚刚';
  if (diffMin < 60) return `${diffMin}分钟前`;
  const diffHour = Math.floor(diffMin / 60);
  if (diffHour < 24) return `${diffHour}小时前`;
  const diffDay = Math.floor(diffHour / 24);
  if (diffDay < 7) return `${diffDay}天前`;
  return t.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
}

function getConfigName(modelConfigId: number): string {
  return configNames.value[modelConfigId] || '';
}

const handleBotChat = (bot: BotResponse) => {
  router.push({
    path: '/chat',
    query: {
      bot_id: String(bot.id),
      model_config_id: bot.model_config_id ? String(bot.model_config_id) : undefined,
    }
  });
};

const handleContinueChat = (conv: Conversation) => {
  router.push({
    path: '/chat',
    query: {
      conversation_id: String(conv.id),
      model_config_id: String(conv.model_config_id),
      config_name: getConfigName(conv.model_config_id),
    }
  });
};

const loadConfigNames = async () => {
  const ids = new Set<number>();
  for (const conv of conversations.value) {
    if (conv.model_config_id) ids.add(conv.model_config_id);
  }
  const results: Record<number, string> = {};
  await Promise.all(
    Array.from(ids).map(async (id) => {
      try {
        const config = await getModelConfig(id, { silent: true });
        if (config?.name) results[id] = config.name;
      } catch {}
    })
  );
  configNames.value = results;
};

onMounted(async () => {
  currentTime.value = getCurrentStatus();
  loading.value = true;
  await Promise.all([
    listBots().then(r => { bots.value = r; }).catch(() => { bots.value = []; }),
    getConversations().then(r => { conversations.value = r; }).catch(() => { conversations.value = []; }),
  ]);
  await loadConfigNames();
  loading.value = false;
});
</script>

<template>
  <div class="intro-page" v-loading="loading">
    <!-- Greeting -->
    <div class="intro-hero">
      <h1 class="intro-greeting">{{ currentTime }}好，{{ userStore.user?.name }}</h1>
      <p class="intro-subtitle">继续上次对话，或选择助理开始新的对话</p>
    </div>

    <!-- 继续对话 -->
    <div class="section" v-if="hasRecentConversations">
      <div class="section-header">
        <h2 class="section-title">继续对话</h2>
        <button class="section-link" @click="router.push('/history')">
          查看全部历史
          <el-icon :size="12"><ArrowRight /></el-icon>
        </button>
      </div>
      <div class="conv-grid">
        <div
          v-for="conv in recentConversations"
          :key="conv.id"
          class="conv-card"
          @click="handleContinueChat(conv)"
        >
          <div class="conv-card-body">
            <span class="conv-card-name">{{ conv.name }}</span>
            <span class="conv-card-model" v-if="getConfigName(conv.model_config_id)">{{ getConfigName(conv.model_config_id) }}</span>
          </div>
          <div class="conv-card-footer">
            <span class="conv-card-time">
              <el-icon :size="11"><Clock /></el-icon>
              {{ formatRelativeTime(conv.update_at) }}
            </span>
            <span class="conv-card-action">继续 <el-icon :size="11"><ArrowRight /></el-icon></span>
          </div>
        </div>
      </div>
    </div>

    <!-- 新建对话 -->
    <div class="section">
      <div class="section-header">
        <h2 class="section-title">新建对话</h2>
      </div>
      <p class="section-desc" v-if="bots.length > 0">选择一个数字助理开始</p>

      <div class="bot-grid" v-if="bots.length > 0">
        <div
          v-for="bot in bots"
          :key="bot.id"
          class="bot-card"
          @click="handleBotChat(bot)"
        >
          <div class="bot-card-top">
            <el-avatar :size="36" :src="bot.avatar" class="bot-avatar">
              {{ bot.name.slice(0, 1) }}
            </el-avatar>
            <div class="bot-card-info">
              <span class="bot-card-name">{{ bot.name }}</span>
              <span class="bot-card-desc">{{ bot.description || '智能问答助理' }}</span>
            </div>
          </div>
          <div class="bot-card-bottom">
            <span class="bot-card-meta">
              <el-icon :size="12"><Tickets /></el-icon>
              {{ bot.vector_db_ids.length }} 个知识库
            </span>
            <el-icon class="bot-card-arrow" :size="15"><ChatDotRound /></el-icon>
          </div>
        </div>
      </div>

      <p class="empty-hint" v-if="!loading && bots.length === 0">
        暂无可用的数字助理，请联系管理员或老师创建。
      </p>
    </div>
  </div>
</template>

<style scoped>
.intro-page {
  max-width: 960px;
  margin: 0 auto;
  padding: 0 0 40px;
  min-height: 300px;
}

/* ===== Hero ===== */
.intro-hero {
  padding: 8px 0 24px;
}
.intro-greeting {
  font-size: 22px;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 4px;
}
.intro-subtitle {
  font-size: 14px;
  color: #94a3b8;
  margin: 0;
}

/* ===== Section ===== */
.section {
  margin-bottom: 28px;
}
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.section-title {
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
  margin: 0;
}
.section-link {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  border: none;
  background: none;
  color: #6366f1;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  padding: 0;
  transition: color 0.15s;
}
.section-link:hover { color: #4f46e5; text-decoration: underline; }
.section-desc {
  font-size: 13px;
  color: #94a3b8;
  margin: 0 0 12px;
}

/* ===== Conversation Grid ===== */
.conv-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}
.conv-card {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 14px 16px;
  border: 1px solid #e6ebf2;
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
  transition: all 0.15s;
  min-height: 72px;
}
.conv-card:hover {
  border-color: #c7d2fe;
  background: #fafaff;
  box-shadow: 0 2px 10px rgba(99,102,241,0.06);
}
.conv-card-body {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin-bottom: 8px;
}
.conv-card-name {
  font-size: 13.5px;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.conv-card-model {
  font-size: 11.5px;
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.conv-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.conv-card-time {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 11.5px;
  color: #94a3b8;
}
.conv-card-action {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 12px;
  font-weight: 500;
  color: #6366f1;
  opacity: 0;
  transition: opacity 0.15s;
}
.conv-card:hover .conv-card-action { opacity: 1; }

/* ===== Bot Grid ===== */
.bot-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 10px;
}
.bot-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 16px;
  border: 1.5px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
  transition: all 0.15s;
}
.bot-card:hover {
  border-color: #c7d2fe;
  background: #fafaff;
  box-shadow: 0 3px 12px rgba(99,102,241,0.07);
  transform: translateY(-1px);
}
.bot-card-top {
  display: flex;
  align-items: center;
  gap: 10px;
}
.bot-avatar {
  flex-shrink: 0;
  font-size: 13px;
  font-weight: 600;
}
.bot-card-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.bot-card-name {
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
  line-height: 1.3;
}
.bot-card-desc {
  font-size: 12px;
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-top: 1px;
}
.bot-card-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.bot-card-meta {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11.5px;
  color: #94a3b8;
}
.bot-card-arrow {
  color: #cbd5e1;
  transition: color 0.15s;
}
.bot-card:hover .bot-card-arrow { color: #6366f1; }

/* ===== Empty ===== */
.empty-hint {
  font-size: 13px;
  color: #94a3b8;
  text-align: center;
  padding: 20px 0;
}

/* ===== Responsive ===== */
@media (max-width: 960px) {
  .conv-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 768px) {
  .intro-page { padding: 0 0 24px; }
  .intro-greeting { font-size: 20px; }
  .conv-grid { grid-template-columns: 1fr; }
  .bot-grid { grid-template-columns: 1fr; }
}
</style>
