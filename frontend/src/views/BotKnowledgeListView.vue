<script setup lang="ts">
import { ref, onMounted, computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { Back, Connection, User } from "@element-plus/icons-vue";
import { getBot, type BotResponse } from "../api/bot";
import { getVectorDb } from "../api/vectorDb";
import { useUserStore } from "../stores/user";

const route = useRoute();
const router = useRouter();
const userStore = useUserStore();
const botId = ref(Number(route.params.id));
const bot = ref<BotResponse | null>(null);
const knowledgeBases = ref<any[]>([]);
const loading = ref(false);

const getKbVisibilityLabel = (kb: any) => {
  if (!kb.organization_id) return '私有';
  if (kb.org_name) return kb.org_name;
  const org = userStore.userOrganizations.find((o: any) => o.id === kb.organization_id);
  return org?.name || '组织';
};

const getKbVisibilityType = (kb: any): 'success' | 'warning' | 'info' => {
  if (!kb.organization_id) return 'info';
  const org = userStore.userOrganizations.find((o: any) => o.id === kb.organization_id);
  if (org?.type === 'school') return 'success';
  return 'warning';
};

const formatDate = (dateString: string) => {
  if (!dateString) return '-';
  const date = new Date(dateString);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
};

const navigateToKb = (id: number) => {
  router.push(`/database/${id}`);
};

const goBack = () => {
  router.push(`/bots/${botId.value}`);
};

onMounted(async () => {
  loading.value = true;
  try {
    bot.value = await getBot(botId.value);
    if (bot.value?.vector_db_ids?.length) {
      const results = await Promise.allSettled(
        bot.value.vector_db_ids.map(id => getVectorDb(id))
      );
      knowledgeBases.value = results
        .filter((r): r is PromiseFulfilledResult<any> => r.status === 'fulfilled' && r.value)
        .map(r => r.value);
    }
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || "加载失败");
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
        <div class="kb-page">

          <div class="kb-header">
            <div class="kb-header-left">
              <button class="kb-back" @click="goBack">
                <el-icon :size="16"><Back /></el-icon>
              </button>
              <div>
                <h2 class="kb-title">关联知识库</h2>
                <span class="kb-subtitle" v-if="bot">{{ bot.name }} · 共 {{ knowledgeBases.length }} 个知识库</span>
              </div>
            </div>
          </div>

          <div v-if="knowledgeBases.length" class="kb-grid">
            <div
              v-for="kb in knowledgeBases"
              :key="kb.id"
              class="kb-item"
              @click="navigateToKb(kb.id)"
            >
              <div class="kb-head">
                <div class="kb-icon">
                  <el-icon :size="16"><Connection /></el-icon>
                </div>
                <div class="kb-info">
                  <span class="kb-name">{{ kb.name }}</span>
                  <span class="kb-creator">
                    <el-icon :size="11"><User /></el-icon>
                    {{ kb.creator_name || '未知' }}
                  </span>
                </div>
                <el-tag
                  size="small"
                  :type="getKbVisibilityType(kb)"
                  effect="plain"
                  class="kb-tag"
                >{{ getKbVisibilityLabel(kb) }}</el-tag>
              </div>
              <p class="kb-desc">{{ kb.describe || '暂无描述' }}</p>
              <span class="kb-date">{{ formatDate(kb.update_at || kb.updated_at || kb.create_at) }} 更新</span>
            </div>
          </div>

          <div v-else-if="!loading" class="kb-empty">
            <el-icon :size="36" color="#cbd5e1"><Connection /></el-icon>
            <span>该助理未关联任何知识库</span>
          </div>

        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.kb-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.kb-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 20px;
  background: #fff;
  border: 1px solid #e6ebf2;
  border-radius: 10px;
}

.kb-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.kb-back {
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
.kb-back:hover { border-color: #a7f3d0; color: #059669; background: #ecfdf5; }

.kb-title {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 650;
  color: #1e293b;
}

.kb-subtitle {
  font-size: 12.5px;
  color: #94a3b8;
}

.kb-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}

.kb-item {
  background: #fff;
  border: 1px solid #e8ecf2;
  border-radius: 10px;
  padding: 16px;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s, transform 0.15s;
}

.kb-item:hover {
  border-color: #a7f3d0;
  box-shadow: 0 3px 12px rgba(5, 150, 105, 0.08);
  transform: translateY(-1px);
}

.kb-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.kb-icon {
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

.kb-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.kb-name {
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kb-creator {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 12px;
  color: #94a3b8;
}

.kb-tag {
  flex-shrink: 0;
}

.kb-desc {
  margin: 0;
  font-size: 13px;
  color: #64748b;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.kb-date {
  display: block;
  margin-top: 10px;
  font-size: 12px;
  color: #94a3b8;
}

.kb-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 60px 0;
  color: #94a3b8;
  font-size: 14px;
}

@media (max-width: 860px) {
  .kb-grid { grid-template-columns: 1fr; }
}
</style>
