<script setup lang="ts">
import { ref, onMounted, computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { Back, Edit, Delete, ChatDotRound, Connection, User } from "@element-plus/icons-vue";
import { getBot, deleteBot, type BotResponse } from "../api/bot";
import { getVectorDb } from "../api/vectorDb";
import { useUserStore } from "../stores/user";

const route = useRoute();
const router = useRouter();
const userStore = useUserStore();
const botId = ref(Number(route.params.id));
const bot = ref<BotResponse | null>(null);
const loading = ref(false);
const knowledgeBases = ref<Record<string, unknown>[]>([]);
const displayedKbs = computed(() => knowledgeBases.value.slice(0, 3));
const hasMoreKbs = computed(() => knowledgeBases.value.length > 3);

const currentUserId = computed(() => Number(userStore.user?.id));
const canManage = computed(() => {
  if (!bot.value) return false;
  const role = userStore.user?.role;
  if (role === "admin") return true;
  return bot.value.user_id === currentUserId.value;
});

const getVisibilityLabel = (b: BotResponse) => {
  if (!b.organization_id) return '私有';
  if (b.org_name) return b.org_name;
  const org = userStore.userOrganizations.find(o => o.id === b.organization_id);
  return org?.name || '组织';
};

const getVisibilityType = (b: BotResponse): 'success' | 'warning' | 'info' => {
  if (!b.organization_id) return 'info';
  const org = userStore.userOrganizations.find(o => o.id === b.organization_id);
  if (org?.type === 'school') return 'success';
  return 'warning';
};

const handleChat = () => {
  if (!bot.value) return;
  router.push({
    path: "/chat",
    query: {
      bot_id: String(bot.value.id),
      model_config_id: bot.value.model_config_id ? String(bot.value.model_config_id) : undefined,
    },
  });
};

const handleEdit = () => {
  if (!bot.value) return;
  router.push(`/bots/${bot.value.id}/edit`);
};

const handleDelete = async () => {
  if (!bot.value) return;
  try {
    await ElMessageBox.confirm(
      `确定删除「${bot.value.name}」吗？删除后不可恢复。`,
      "删除数字助理",
      { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" }
    );
    await deleteBot(bot.value.id);
    ElMessage.success("已删除");
    router.push("/bots");
  } catch (error: unknown) {
    if (error !== "cancel") ElMessage.error(error?.response?.data?.detail || "删除失败");
  }
};

const goBack = () => router.push('/bots');

const getKbVisibilityLabel = (kb: Record<string, unknown>) => {
  if (!kb.organization_id) return '私有';
  if (kb.org_name) return kb.org_name;
  const org = userStore.userOrganizations.find((o: Record<string, unknown>) => o.id === kb.organization_id);
  return org?.name || '组织';
};

const getKbVisibilityType = (kb: Record<string, unknown>): 'success' | 'warning' | 'info' => {
  if (!kb.organization_id) return 'info';
  const org = userStore.userOrganizations.find((o: Record<string, unknown>) => o.id === kb.organization_id);
  if (org?.type === 'school') return 'success';
  return 'warning';
};

const formatDate = (dateString: string) => {
  if (!dateString) return '-';
  const date = new Date(dateString);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
};

const fetchKnowledgeBases = async (ids: number[]) => {
  if (!ids.length) return;
  const results = await Promise.allSettled(ids.map(id => getVectorDb(id)));
  knowledgeBases.value = results
    .filter((r): r is PromiseFulfilledResult<Record<string, unknown>> => r.status === 'fulfilled' && r.value)
    .map(r => r.value);
};

const navigateToKb = (id: number) => {
  router.push(`/database/${id}`);
};

const viewAllKbs = () => {
  if (!bot.value) return;
  router.push(`/bots/${bot.value.id}/knowledge`);
};

onMounted(async () => {
  loading.value = true;
  try {
    if (history.state?.bot) {
      bot.value = history.state.bot;
    }
    if (!bot.value && botId.value > 0) {
      bot.value = await getBot(botId.value);
    }
    if (!bot.value) {
      ElMessage.error("数字助理不存在");
      router.go(-1);
    }
    if (bot.value?.vector_db_ids?.length) {
      await fetchKnowledgeBases(bot.value.vector_db_ids);
    }
  } catch (error: unknown) {
    ElMessage.error(error?.response?.data?.detail || "加载详情失败");
    router.go(-1);
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div class="page-container">
    <div class="content-section">
      <div v-loading="loading">
        <div v-if="bot" class="cd-page">

          <!-- ===== Header ===== -->
          <div class="cd-header">
            <div class="cd-header-left">
              <button class="cd-back" @click="goBack">
                <el-icon :size="16"><Back /></el-icon>
              </button>
              <div class="cd-header-info">
                <div class="cd-title-row">
                  <h2 class="cd-title">{{ bot.name }}</h2>
                  <el-tag
                    :type="getVisibilityType(bot)"
                    size="small"
                    effect="plain"
                  >{{ getVisibilityLabel(bot) }}</el-tag>
                </div>
                <div class="cd-meta-row">
                  <span class="cd-meta-text">{{ bot.creator_name || `用户 #${bot.user_id}` }}</span>
                  <span class="cd-meta-sep">&middot;</span>
                  <span class="cd-meta-text">{{ bot.updated_at ? new Date(bot.updated_at).toLocaleDateString() + ' 更新' : '' }}</span>
                </div>
              </div>
            </div>
            <div class="cd-header-actions">
              <el-button type="primary" size="default" :icon="ChatDotRound" @click="handleChat">试用对话</el-button>
              <el-button v-if="canManage" size="default" :icon="Edit" @click="handleEdit">编辑</el-button>
              <el-button v-if="canManage" type="danger" size="default" plain :icon="Delete" @click="handleDelete">删除</el-button>
            </div>
          </div>

          <!-- ===== 两栏区域 ===== -->
          <div class="cd-grid-2">
            <!-- 左列：基本信息 -->
            <div class="cd-card">
              <div class="cd-card-head">
                <span class="cd-accent" style="background:#6366f1"></span>
                <h3 class="cd-card-title">基本信息</h3>
              </div>
              <div class="cd-fields">
                <div class="cd-field">
                  <span class="cd-label">助理名称</span>
                  <span class="cd-value">{{ bot.name }}</span>
                </div>
                <div class="cd-field">
                  <span class="cd-label">可见范围</span>
                  <span class="cd-value">
                    <el-tag :type="getVisibilityType(bot)" size="small" effect="plain">
                      {{ getVisibilityLabel(bot) }}
                    </el-tag>
                  </span>
                </div>
                <div class="cd-field">
                  <span class="cd-label">创建者</span>
                  <span class="cd-value">{{ bot.creator_name || `用户 #${bot.user_id}` }}</span>
                </div>
                <div class="cd-field" v-if="bot.organization_id">
                  <span class="cd-label">所属组织</span>
                  <span class="cd-value">{{ getVisibilityLabel(bot) }}</span>
                </div>
                <div class="cd-field">
                  <span class="cd-label">模型配置</span>
                  <span class="cd-value cd-value-highlight">
                    {{ bot.model_config_id ? `配置 #${bot.model_config_id}` : "未绑定" }}
                  </span>
                </div>
                <div class="cd-field cd-field-full">
                  <span class="cd-label">描述</span>
                  <span class="cd-value">{{ bot.description || "暂无描述" }}</span>
                </div>
              </div>
            </div>

            <!-- 右列：禁止话题 + 时间信息 -->
            <div class="cd-col-right">
              <div class="cd-card" v-if="bot.forbidden_topics && bot.forbidden_topics.length > 0">
                <div class="cd-card-head">
                  <span class="cd-accent" style="background:#ef4444"></span>
                  <h3 class="cd-card-title">禁止话题</h3>
                </div>
                <div class="cd-tags">
                  <el-tag
                    v-for="topic in bot.forbidden_topics"
                    :key="topic"
                    type="danger"
                    effect="plain"
                    class="cd-topic-tag"
                  >{{ topic }}</el-tag>
                </div>
              </div>

              <div class="cd-card">
                <div class="cd-card-head">
                  <span class="cd-accent" style="background:#10b981"></span>
                  <h3 class="cd-card-title">时间信息</h3>
                </div>
                <div class="cd-kv-list">
                  <div class="cd-kv">
                    <span class="cd-kv-label">创建时间</span>
                    <span class="cd-kv-value">{{ bot.created_at ? new Date(bot.created_at).toLocaleString() : "-" }}</span>
                  </div>
                  <div class="cd-kv">
                    <span class="cd-kv-label">最后更新</span>
                    <span class="cd-kv-value">{{ bot.updated_at ? new Date(bot.updated_at).toLocaleString() : "-" }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- ===== 关联知识库 ===== -->
          <div class="cd-card">
            <div class="cd-card-head">
              <span class="cd-accent" style="background:#059669"></span>
              <h3 class="cd-card-title">关联知识库</h3>
              <span class="cd-card-count" v-if="knowledgeBases.length">{{ knowledgeBases.length }} 个</span>
              <a v-if="hasMoreKbs" class="cd-view-all" @click="viewAllKbs">查看全部 &rarr;</a>
            </div>
            <div v-if="knowledgeBases.length" class="cd-kb-grid">
              <div
                v-for="kb in displayedKbs"
                :key="kb.id"
                class="cd-kb-item"
                @click="navigateToKb(kb.id)"
              >
                <div class="cd-kb-head">
                  <div class="cd-kb-icon">
                    <el-icon :size="16"><Connection /></el-icon>
                  </div>
                  <div class="cd-kb-info">
                    <span class="cd-kb-name">{{ kb.name }}</span>
                    <span class="cd-kb-creator">
                      <el-icon :size="11"><User /></el-icon>
                      {{ kb.creator_name || '未知' }}
                    </span>
                  </div>
                  <el-tag
                    size="small"
                    :type="getKbVisibilityType(kb)"
                    effect="plain"
                    class="cd-kb-tag"
                  >{{ getKbVisibilityLabel(kb) }}</el-tag>
                </div>
                <p class="cd-kb-desc">{{ kb.describe || '暂无描述' }}</p>
                <span class="cd-kb-date">{{ formatDate(kb.update_at || kb.updated_at || kb.create_at) }} 更新</span>
              </div>
            </div>
            <div v-else class="cd-kb-empty">
              <el-icon :size="28" color="#cbd5e1"><Connection /></el-icon>
              <span>未关联知识库</span>
            </div>
          </div>

          <!-- ===== 系统提示词 ===== -->
          <div class="cd-card">
            <div class="cd-card-head">
              <span class="cd-accent" style="background:#8b5cf6"></span>
              <h3 class="cd-card-title">系统提示词</h3>
            </div>
            <pre class="cd-prompt-text">{{ bot.system_prompt || "未设置" }}</pre>
          </div>

          <!-- ===== 开场白 ===== -->
          <div class="cd-card">
            <div class="cd-card-head">
              <span class="cd-accent" style="background:#f59e0b"></span>
              <h3 class="cd-card-title">开场白</h3>
            </div>
            <pre class="cd-prompt-text cd-prompt-greeting">{{ bot.greeting || "未设置" }}</pre>
          </div>

        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ===== Page ===== */
.cd-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* ===== Header ===== */
.cd-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 20px;
  background: #fff;
  border: 1px solid #e6ebf2;
  border-radius: 10px;
}

.cd-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  flex: 1;
}

.cd-back {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 8px;
  border: 1px solid #e6ebf2;
  background: #f8fafc;
  color: #64748b;
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.15s;
}
.cd-back:hover { border-color: #c7d2fe; color: #4f46e5; background: #eef2ff; }

.cd-header-info { min-width: 0; flex: 1; }

.cd-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.cd-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 4px;
}

.cd-title {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 650;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cd-meta-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.cd-meta-sep { color: #cbd5e1; font-size: 12px; }
.cd-meta-text { font-size: 12.5px; color: #94a3b8; white-space: nowrap; }

/* ===== 两栏网格 ===== */
.cd-grid-2 {
  display: grid;
  grid-template-columns: 3fr 2fr;
  gap: 14px;
}

.cd-col-right {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* ===== 通用卡片 ===== */
.cd-card {
  background: #fff;
  border: 1px solid #e6ebf2;
  border-radius: 10px;
  padding: 16px 18px;
}

.cd-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
}

.cd-accent {
  display: inline-block;
  width: 3px;
  height: 14px;
  border-radius: 2px;
  flex-shrink: 0;
}

.cd-card-title {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: #1e293b;
}

/* ===== 基本信息 fields ===== */
.cd-fields {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px 24px;
}

.cd-field-full { grid-column: 1 / -1; }

.cd-label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #94a3b8;
  margin-bottom: 4px;
}

.cd-value {
  font-size: 13.5px;
  color: #1e293b;
  word-break: break-word;
}

.cd-value-highlight { color: #4f46e5; font-weight: 600; }

/* ===== 禁止话题 ===== */
.cd-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.cd-topic-tag {
  font-size: 12.5px;
}

/* ===== 时间信息 KV ===== */
.cd-kv-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.cd-kv {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.cd-kv-label { font-size: 13px; color: #64748b; }
.cd-kv-value { font-size: 13px; color: #1e293b; font-weight: 500; text-align: right; }

/* ===== 关联知识库 ===== */
.cd-card-count {
  font-size: 12px;
  color: #94a3b8;
  font-weight: 400;
}

.cd-view-all {
  margin-left: auto;
  font-size: 13px;
  color: #059669;
  cursor: pointer;
  font-weight: 500;
  white-space: nowrap;
  transition: color 0.15s;
}
.cd-view-all:hover { color: #047857; }

.cd-kb-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.cd-kb-item {
  border: 1px solid #e8ecf2;
  border-radius: 8px;
  padding: 14px;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s, transform 0.15s;
}

.cd-kb-item:hover {
  border-color: #a7f3d0;
  box-shadow: 0 3px 12px rgba(5, 150, 105, 0.08);
  transform: translateY(-1px);
}

.cd-kb-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.cd-kb-icon {
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  background: #ecfdf5;
  color: #059669;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.cd-kb-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.cd-kb-name {
  font-size: 13.5px;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cd-kb-creator {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 11.5px;
  color: #94a3b8;
}

.cd-kb-tag {
  flex-shrink: 0;
}

.cd-kb-desc {
  margin: 0;
  font-size: 12.5px;
  color: #64748b;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.cd-kb-date {
  display: block;
  margin-top: 8px;
  font-size: 11.5px;
  color: #94a3b8;
}

.cd-kb-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 28px 0;
  color: #94a3b8;
  font-size: 13px;
}

/* ===== 提示词 ===== */
.cd-prompt-text {
  margin: 0;
  font-size: 13px;
  color: #334155;
  background: #f8fafc;
  padding: 14px 16px;
  border-radius: 8px;
  border-left: 3px solid #8b5cf6;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.65;
  font-family: inherit;
}

.cd-prompt-greeting {
  border-left-color: #f59e0b;
}

/* ===== 响应式 ===== */
@media (max-width: 860px) {
  .cd-grid-2 { grid-template-columns: 1fr; }
  .cd-fields { grid-template-columns: 1fr; }
  .cd-kb-grid { grid-template-columns: 1fr; }
  .cd-header { flex-direction: column; align-items: flex-start; }
  .cd-header-actions { width: 100%; justify-content: flex-end; }
}
</style>
