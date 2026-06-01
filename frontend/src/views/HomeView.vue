<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, ChatDotRound, FolderAdd, Service } from '@element-plus/icons-vue'
import { listBots, type BotResponse } from '../api/bot'
import { getConversations } from '../api/chat'
import { fetchOwnVectors } from '../api/vectorDb'
import { useUserStore } from '../stores/user'
import { getCurrentStatus, getFormatTimeString } from '../utils/common'
import type { Conversation } from '../types/chat'

const router = useRouter()
const userStore = useUserStore()

const isStudent = computed(() => userStore.user?.role === 'student')
const isTeacherOrAdmin = computed(() => !isStudent.value)

const greetingTime = ref('')
const loading = ref(false)

const bots = ref<BotResponse[]>([])
const conversations = ref<Conversation[]>([])
const vectorDbs = ref<any[]>([])
const orgDisplay = computed(() => {
  const org = userStore.currentOrganization
  if (!org) return ''
  return org.name || ''
})

const botColors = ['#6366f1', '#f59e0b', '#10b981', '#ec4899', '#8b5cf6', '#06b6d4', '#f97316', '#14b8a6']

const quickActions = computed(() => {
  const actions = [
    { label: '新建对话', desc: '开始智能问答', color: '#6366f1', route: '/intro', icon: ChatDotRound },
  ]
  if (isTeacherOrAdmin.value) {
    actions.push(
      { label: '创建知识库', desc: '上传文档资料', color: '#16a34a', route: '/database?action=create', icon: FolderAdd },
      { label: '创建助理', desc: '构建专属Bot', color: '#8b5cf6', route: '/bots/create', icon: Service },
    )
  } else {
    actions.push(
      { label: '浏览知识库', desc: '查看文档资料', color: '#16a34a', route: '/database', icon: FolderAdd },
    )
  }
  return actions
})

const recentConversations = computed(() => {
  return [...conversations.value]
    .sort((a, b) => new Date(b.update_at).getTime() - new Date(a.update_at).getTime())
    .slice(0, 4)
})

const displayBots = computed(() => bots.value.slice(0, 3))

const displayVectorDbs = computed(() => {
  return [...vectorDbs.value]
    .sort((a: any, b: any) => new Date(b.update_at || b.create_at).getTime() - new Date(a.update_at || a.create_at).getTime())
    .slice(0, 3)
})

interface ActivityItem {
  type: string
  title: string
  creator: string
  target: string
  time: string
  rawTime: string
  routeTo: string
}

const activityFeed = computed<ActivityItem[]>(() => {
  const items: ActivityItem[] = []

  vectorDbs.value.forEach((db: any) => {
    const t = db.updated_at || db.created_at || db.update_at || db.create_at
    if (t) {
      items.push({
        type: 'kb',
        title: (db.created_at || db.create_at) === (db.updated_at || db.update_at) ? '创建了知识库' : '更新了知识库',
        creator: db.creator_name || '未知用户',
        target: db.name,
        time: formatRelativeTime(t),
        rawTime: t,
        routeTo: `/database/${db.id}`,
      })
    }
  })

  bots.value.forEach((bot: BotResponse) => {
    const t = bot.updated_at || bot.created_at
    if (t) {
      items.push({
        type: 'bot',
        title: bot.created_at === bot.updated_at ? '新增数字助理' : '更新了助理',
        creator: bot.creator_name || '未知用户',
        target: bot.name,
        time: formatRelativeTime(t),
        rawTime: t,
        routeTo: isStudent.value ? `/chat?bot_id=${bot.id}` : `/bots/${bot.id}`,
      })
    }
  })

  return items
    .sort((a, b) => new Date(b.rawTime).getTime() - new Date(a.rawTime).getTime())
    .slice(0, 4)
})

function formatRelativeTime(timeStr: string): string {
  const now = new Date()
  const t = new Date(timeStr)
  const diffMs = now.getTime() - t.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin}分钟前`
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24) return `${diffHour}小时前`
  const diffDay = Math.floor(diffHour / 24)
  if (diffDay < 7) return `${diffDay}天前`
  return getFormatTimeString(timeStr)
}

function getDbVisibilityLabel(db: any): string {
  if (!db.organization_id) return '私有'
  if (db.org_name) return db.org_name
  return '组织'
}

function getDbVisibilityType(db: any): string {
  if (!db.organization_id) return 'info'
  return 'success'
}

const handleBotChat = (bot: BotResponse) => {
  router.push({ path: '/chat', query: { bot_id: String(bot.id), model_config_id: bot.model_config_id ? String(bot.model_config_id) : undefined } })
}

const handleContinueChat = (conv: Conversation) => {
  router.push({ path: '/chat', query: { conversation_id: String(conv.id), model_config_id: String(conv.model_config_id) } })
}

onMounted(async () => {
  greetingTime.value = getCurrentStatus()
  loading.value = true

  const promises: Promise<void>[] = [
    listBots().then(r => { bots.value = r }).catch(() => { bots.value = [] }),
    getConversations().then(r => { conversations.value = r }).catch(() => { conversations.value = [] }),
    fetchOwnVectors().then(r => { vectorDbs.value = r }).catch(() => { vectorDbs.value = [] }),
  ]

  await Promise.all(promises)
  loading.value = false
})
</script>

<template>
  <div class="home-page" v-loading="loading">

    <!-- Hero -->
    <div class="hero">
      <div class="hero-bg">
        <div class="hero-circle hero-circle-1"></div>
        <div class="hero-circle hero-circle-2"></div>
        <div class="hero-circle hero-circle-3"></div>
      </div>
      <div class="hero-content">
        <h1 class="hero-title">{{ greetingTime }}好，{{ userStore.user?.name }}</h1>
        <p class="hero-desc">
          <span v-if="orgDisplay">{{ orgDisplay }}</span>
          <span v-if="orgDisplay"> · </span>
          选择助理或继续上次对话
        </p>
      </div>
    </div>

    <!-- 顶部三卡片：平台动态 / 最近对话 / 快速开始 -->
    <div class="tile-row-3">
      <!-- 平台动态 -->
      <div class="card">
        <div class="card-header">
          <div class="card-title-wrap">
            <span class="card-accent" style="background:#f59e0b"></span>
            <h3 class="card-title">平台动态</h3>
          </div>
        </div>
        <div class="activity-timeline" v-if="activityFeed.length > 0">
          <div v-for="(item, i) in activityFeed" :key="i" class="activity-item">
            <div class="activity-dot"></div>
            <div class="activity-body">
              <div class="activity-main">
                <span class="activity-creator">{{ item.creator }}</span>
                <span class="activity-action">{{ item.title }}</span>
              </div>
              <div class="activity-target-row">
                <span class="activity-target">"{{ item.target }}"</span>
                <button class="activity-link" @click="router.push(item.routeTo)">查看<el-icon :size="10"><ArrowRight /></el-icon></button>
              </div>
              <span class="activity-time">{{ item.time }}</span>
            </div>
          </div>
        </div>
        <div class="empty-hint" v-else><p>暂无最近动态</p></div>
      </div>

      <!-- 最近对话 -->
      <div class="card">
        <div class="card-header">
          <div class="card-title-wrap">
            <span class="card-accent" style="background:#6366f1"></span>
            <h3 class="card-title">最近对话</h3>
          </div>
          <button class="link-btn" @click="router.push('/history')">全部<el-icon :size="11" class="link-arrow"><ArrowRight /></el-icon></button>
        </div>
        <div class="conv-list" v-if="recentConversations.length > 0">
          <div
            v-for="conv in recentConversations"
            :key="conv.id"
            class="conv-item"
            @click="handleContinueChat(conv)"
          >
            <span class="conv-name">{{ conv.name }}</span>
            <div class="conv-right">
              <span class="conv-time">{{ formatRelativeTime(conv.update_at) }}</span>
              <el-icon :size="12" class="conv-arrow"><ArrowRight /></el-icon>
            </div>
          </div>
        </div>
        <div class="empty-hint" v-else>
          <p>还没有对话记录</p>
          <button class="link-btn" @click="router.push('/intro')">开始第一次对话</button>
        </div>
      </div>

      <!-- 快速开始 -->
      <div class="card">
        <div class="card-header">
          <div class="card-title-wrap">
            <span class="card-accent" style="background:#10b981"></span>
            <h3 class="card-title">快速开始</h3>
          </div>
        </div>
        <div class="quick-actions">
          <div
            v-for="(action, i) in quickActions"
            :key="i"
            class="action-item"
            @click="router.push(action.route)"
          >
            <span class="action-dot" :style="{ background: action.color }"></span>
            <div class="action-text">
              <span class="action-label">{{ action.label }}</span>
              <span class="action-desc">{{ action.desc }}</span>
            </div>
            <el-icon :size="13" class="action-arrow"><ArrowRight /></el-icon>
          </div>
        </div>
      </div>
    </div>

    <!-- 推荐助理 -->
    <div class="section-header" v-if="displayBots.length > 0">
      <div class="section-title-wrap">
        <span class="card-accent" style="background:#8b5cf6"></span>
        <span class="section-label">推荐助理</span>
      </div>
      <button class="link-btn" @click="router.push('/bots')">查看全部<el-icon :size="11" class="link-arrow"><ArrowRight /></el-icon></button>
    </div>
    <div class="tile-row-3" v-if="displayBots.length > 0">
      <div
        v-for="(bot, i) in displayBots"
        :key="bot.id"
        class="bot-card"
        @click="handleBotChat(bot)"
      >
        <div class="bot-color-bar" :style="{ background: botColors[i % botColors.length] }"></div>
        <div class="bot-body">
          <span class="bot-name">{{ bot.name }}</span>
          <span class="bot-desc">{{ bot.description || '智能问答助理' }}</span>
          <span class="bot-action">开始对话 <el-icon :size="11"><ArrowRight /></el-icon></span>
        </div>
      </div>
    </div>

    <!-- 知识库 -->
    <div class="section-header">
      <div class="section-title-wrap">
        <span class="card-accent" style="background:#10b981"></span>
        <span class="section-label">知识库</span>
      </div>
      <button class="link-btn" @click="router.push('/database')">查看全部<el-icon :size="11" class="link-arrow"><ArrowRight /></el-icon></button>
    </div>
    <div class="tile-row-3" v-if="displayVectorDbs.length > 0">
      <div v-for="db in displayVectorDbs" :key="db.id" class="kb-card" @click="router.push(`/database/${db.id}`)">
        <span class="kb-name">{{ db.name }}</span>
        <span class="kb-desc">{{ db.describe || '暂无描述' }}</span>
        <div class="kb-footer">
          <el-tag :type="getDbVisibilityType(db)" size="small" effect="plain">{{ getDbVisibilityLabel(db) }}</el-tag>
          <span class="kb-doc-count">{{ db.document_count || 0 }} 篇文档</span>
        </div>
      </div>
    </div>
    <div class="tile-row-3" v-else>
      <div class="card empty-card">
        <div class="empty-hint">
          <p>还没有知识库</p>
          <button class="link-btn" @click="router.push('/database')">去创建一个</button>
        </div>
      </div>
    </div>

  </div>
</template>

<style scoped>
.home-page {
  max-width: 1200px;
  margin: 0 auto;
  padding-bottom: 32px;
  min-height: 400px;
}

/* ===== Hero ===== */
.hero {
  position: relative;
  border-radius: 14px;
  overflow: hidden;
  padding: 28px 32px 24px;
  margin-bottom: 16px;
  background: linear-gradient(135deg, #1e3a5f 0%, #2563eb 50%, #7c3aed 100%);
}
.hero-bg { position: absolute; inset: 0; overflow: hidden; pointer-events: none; }
.hero-circle { position: absolute; border-radius: 50%; opacity: 0.1; background: #fff; }
.hero-circle-1 { width: 220px; height: 220px; top: -60px; right: -30px; }
.hero-circle-2 { width: 140px; height: 140px; bottom: -50px; left: 8%; }
.hero-circle-3 { width: 80px; height: 80px; top: 20%; right: 28%; opacity: 0.06; }
.hero-content { position: relative; z-index: 1; }
.hero-title { margin: 0 0 6px; font-size: 1.5rem; font-weight: 700; color: #fff; }
.hero-desc { margin: 0; font-size: 0.88rem; color: rgba(255,255,255,0.68); }

/* ===== 3列 Tile 网格 ===== */
.tile-row-3 {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  margin-bottom: 14px;
}

/* ===== 通用卡片 ===== */
.card {
  background: #fff;
  border: 1px solid #e6ebf2;
  border-radius: 10px;
  padding: 16px 18px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.card-title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}

.card-accent {
  display: inline-block;
  width: 3px;
  height: 14px;
  border-radius: 2px;
  flex-shrink: 0;
}

.card-title {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: #1e293b;
}

.link-btn {
  border: none;
  background: none;
  color: #6366f1;
  font-size: 12px;
  cursor: pointer;
  padding: 0;
  display: inline-flex;
  align-items: center;
  gap: 2px;
  transition: color 0.15s;
}
.link-btn:hover { color: #4f46e5; text-decoration: underline; }
.link-arrow { margin-top: 1px; }

/* ===== Section 标题行 ===== */
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  padding: 0 2px;
}

.section-title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}

.section-label {
  font-size: 13.5px;
  font-weight: 600;
  color: #1e293b;
}

/* ===== 平台动态 ===== */
.activity-timeline {
  position: relative;
  padding-left: 14px;
}

.activity-timeline::before {
  content: '';
  position: absolute;
  left: 3px;
  top: 4px;
  bottom: 4px;
  width: 1px;
  background: #e5e7eb;
}

.activity-item {
  position: relative;
  padding-bottom: 14px;
}
.activity-item:last-child { padding-bottom: 0; }

.activity-dot {
  position: absolute;
  left: -14px;
  top: 4px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #f59e0b;
  border: 2px solid #fff;
  box-shadow: 0 0 0 1px #e5e7eb;
  z-index: 1;
}

.activity-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.activity-main {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.activity-creator {
  font-size: 12.5px;
  font-weight: 600;
  color: #334155;
}

.activity-action {
  font-size: 12.5px;
  color: #64748b;
}

.activity-target-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.activity-target {
  font-size: 12px;
  color: #475569;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.activity-link {
  border: none;
  background: none;
  color: #6366f1;
  font-size: 11.5px;
  cursor: pointer;
  padding: 0;
  display: inline-flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
  transition: color 0.15s;
}
.activity-link:hover { color: #4f46e5; text-decoration: underline; }

.activity-time {
  font-size: 11px;
  color: #94a3b8;
}

/* ===== 最近对话 ===== */
.conv-list {
  display: flex;
  flex-direction: column;
}

.conv-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 4px;
  cursor: pointer;
  border-bottom: 1px dashed #edf0f5;
  border-radius: 4px;
  transition: background 0.15s;
}
.conv-item:last-child { border-bottom: none; }
.conv-item:hover { background: #f8f9fb; }

.conv-name {
  font-size: 13px;
  font-weight: 500;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
  flex: 1;
}

.conv-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  margin-left: 10px;
}

.conv-time {
  font-size: 11px;
  color: #94a3b8;
  white-space: nowrap;
}

.conv-arrow { color: #cbd5e1; transition: color 0.15s; }
.conv-item:hover .conv-arrow { color: #6366f1; }

/* ===== 快速开始 ===== */
.quick-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.action-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid #edf0f5;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}
.action-item:hover {
  border-color: #c7d2fe;
  transform: translateX(3px);
  box-shadow: 0 2px 8px rgba(99,102,241,0.05);
}

.action-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.action-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  flex: 1;
  min-width: 0;
}

.action-label {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
}

.action-desc {
  font-size: 11.5px;
  color: #94a3b8;
}

.action-arrow { color: #cbd5e1; flex-shrink: 0; transition: color 0.15s; }
.action-item:hover .action-arrow { color: #6366f1; }

/* ===== Bot 卡片 ===== */
.bot-card {
  border: 1px solid #e6ebf2;
  border-radius: 10px;
  overflow: hidden;
  cursor: pointer;
  transition: all 0.2s;
  background: #fff;
}
.bot-card:hover {
  border-color: #c7d2fe;
  transform: translateY(-3px);
  box-shadow: 0 4px 16px rgba(99,102,241,0.08);
}

.bot-color-bar {
  height: 5px;
  width: 100%;
}

.bot-body {
  padding: 14px 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.bot-name {
  font-size: 13.5px;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bot-desc {
  font-size: 12px;
  color: #94a3b8;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.5;
  min-height: 36px;
}

.bot-action {
  font-size: 12px;
  color: #6366f1;
  display: flex;
  align-items: center;
  gap: 3px;
  margin-top: 4px;
  font-weight: 500;
}

/* ===== 知识库卡片 ===== */
.kb-card {
  background: #fff;
  border: 1px solid #e6ebf2;
  border-radius: 10px;
  padding: 14px 16px;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.kb-card:hover {
  border-color: #c7d2fe;
  transform: translateY(-2px);
  box-shadow: 0 3px 12px rgba(99,102,241,0.06);
}

.kb-name {
  font-size: 13.5px;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kb-desc {
  font-size: 12px;
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kb-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 2px;
}

.kb-doc-count {
  font-size: 11.5px;
  color: #94a3b8;
}

/* ===== 空状态 ===== */
.empty-hint {
  text-align: center;
  padding: 18px 0 6px;
}
.empty-hint p {
  margin: 0 0 6px;
  font-size: 12.5px;
  color: #94a3b8;
}

.empty-card {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 80px;
}

/* ===== 响应式 ===== */
@media (max-width: 1024px) {
  .tile-row-3 { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 768px) {
  .tile-row-3 { grid-template-columns: 1fr; }
  .hero { padding: 24px 20px 20px; }
  .hero-title { font-size: 1.3rem; }
}
</style>
