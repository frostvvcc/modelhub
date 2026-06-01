<script setup lang="ts">
import { computed } from 'vue';
import { Connection, Link, User } from '@element-plus/icons-vue';
import { useRouter } from 'vue-router';
import { testConnect } from '../api/vectorDb';
import { ElMessage } from 'element-plus';
import { useUserStore } from '../stores/user';

interface VectorDbCardProps {
  created_at: string;
  describe: string;
  id: number;
  name: string;
  updated_at: string;
  user_id?: number;
  creator_name?: string;
  organization_id?: number | null;
  org_name?: string | null;
}

const props = defineProps<VectorDbCardProps>();
const router = useRouter();
const userStore = useUserStore();

const visibilityLabel = computed(() => {
  if (!props.organization_id) return '私有';
  if (props.org_name) return props.org_name;
  const org = userStore.userOrganizations.find(o => o.id === props.organization_id);
  return org?.name || '组织';
});

const visibilityType = computed<'success' | 'warning' | 'info'>(() => {
  if (!props.organization_id) return 'info';
  const org = userStore.userOrganizations.find(o => o.id === props.organization_id);
  if (org?.type === 'school') return 'success';
  return 'warning';
});

const canManage = computed(() => {
  const role = userStore.user?.role;
  if (role === 'admin') return true;
  if (role === 'teacher') {
    return props.user_id === Number(userStore.user?.id);
  }
  return props.user_id === Number(userStore.user?.id);
});

const navigateToDetail = (id: number) => {
  router.push(`/database/${id}`);
};

const HandletestConnect = async (id: number) => {
  const res = await testConnect(id);
  if (res) ElMessage.success('连接成功');
  else ElMessage.error('连接失败');
};

const formatDate = (dateString: string) => {
  if (!dateString) return '-';
  const date = new Date(dateString);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
};
</script>

<template>
  <div class="unified-card clickable-card" @click="navigateToDetail(id)">
    <div class="card-head">
      <div class="card-title">
        <el-icon class="db-icon"><Connection /></el-icon>
        <h3>{{ name }}</h3>
      </div>
      <span class="card-creator">
        <el-icon :size="12"><User /></el-icon>
        {{ creator_name || '未知' }}
      </span>
    </div>

    <div class="card-tags">
      <el-tag size="small" :type="visibilityType" effect="plain">{{ visibilityLabel }}</el-tag>
    </div>

    <div class="card-body">
      <p>{{ describe }}</p>
    </div>

    <div class="card-foot">
      <div class="card-meta">{{ formatDate(updated_at) }} 更新</div>
      <div class="card-actions" v-if="canManage">
        <el-button plain size="small" :icon="Link" @click.stop="HandletestConnect(id)">测试连接</el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.db-icon {
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  background: #ecfdf5;
  color: #059669;
  border-radius: 8px;
  font-size: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.card-creator {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #94a3b8;
  flex-shrink: 0;
  white-space: nowrap;
}

.card-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.clickable-card {
  cursor: pointer;
}
</style>
