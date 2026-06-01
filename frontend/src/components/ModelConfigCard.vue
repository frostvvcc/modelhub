<script setup lang="ts">
import { computed } from 'vue';
import { ElTag, ElButton } from 'element-plus';
import { ModelConfig } from '../types/model_config';
import { useRouter } from 'vue-router';
import { Delete, Setting, View, Promotion, DocumentRemove } from '@element-plus/icons-vue';
import { useUserStore } from '../stores/user';

interface ModelConfigCardProps {
  config: ModelConfig;
  baseModelName?: string;
  showActions?: boolean;
}

const props = withDefaults(defineProps<ModelConfigCardProps>(), {
  showActions: true
});

const userStore = useUserStore();
const canManage = computed(() => {
  const role = userStore.user?.role;
  if (role === 'admin') return true;
  return props.config.user_id === Number(userStore.user?.id);
});

const router = useRouter();
const emit = defineEmits(['delete', 'toggle-publish']);

const providerColor = computed(() => {
  const name = (props.baseModelName || '').toLowerCase();
  if (name.includes('qwen') || name.includes('通义')) return { bg: '#fff7ed', border: '#fed7aa', text: '#c2410c' };
  if (name.includes('deepseek')) return { bg: '#f0fdf4', border: '#bbf7d0', text: '#15803d' };
  if (name.includes('gpt') || name.includes('openai')) return { bg: '#f0f9ff', border: '#bae6fd', text: '#0369a1' };
  if (name.includes('claude') || name.includes('anthropic')) return { bg: '#faf5ff', border: '#e9d5ff', text: '#7e22ce' };
  if (name.includes('llama') || name.includes('meta')) return { bg: '#eff6ff', border: '#bfdbfe', text: '#1d4ed8' };
  if (name.includes('gemini') || name.includes('google')) return { bg: '#fefce8', border: '#fde68a', text: '#a16207' };
  return { bg: '#f8fafc', border: '#e2e8f0', text: '#475569' };
});

const authorName = computed(() => {
  const c = props.config as any;
  return c.author_name || c.author || `用户 #${c.user_id}`;
});

const handleViewDetail = () => {
  router.push({
    name: 'configDetail',
    params: { id: props.config.id },
    state: { config: JSON.parse(JSON.stringify(props.config)) }
  });
};

const handleDelete = () => {
  emit('delete', props.config.id);
};

const handleTogglePublish = () => {
  emit('toggle-publish', props.config);
};
</script>

<template>
  <div class="mc-card" @click="handleViewDetail">
    <!-- 第一行: 名称 + 状态标签 -->
    <div class="mc-head">
      <div class="mc-title">
        <span class="mc-icon">
          <el-icon><Setting /></el-icon>
        </span>
        <h3>{{ config.name }}</h3>
      </div>
      <ElTag size="small" :type="config.is_private ? 'info' : 'success'" effect="plain">
        {{ config.is_private ? '草稿' : '已发布' }}
      </ElTag>
    </div>

    <!-- 第二行: 模型标签 + 参数（合并一行） -->
    <div class="mc-info">
      <span
        v-if="baseModelName"
        class="provider-tag"
        :style="{ background: providerColor.bg, color: providerColor.text, borderColor: providerColor.border }"
      >{{ baseModelName }}</span>
      <span class="param-chip">T:{{ config.temperature }}</span>
      <span class="param-chip">P:{{ config.top_p }}</span>
    </div>

    <!-- 第三行: 描述 -->
    <div class="mc-body">
      <p>{{ config.describe || '暂无描述' }}</p>
    </div>

    <!-- 底部: meta + 操作按钮 -->
    <div class="mc-foot" @click.stop>
      <div class="mc-meta">
        <span class="mc-author">{{ authorName }}</span>
        <span class="mc-sep">&middot;</span>
        <span class="mc-date">{{ new Date(config.updated_at).toLocaleDateString() }}</span>
      </div>
      <div class="mc-actions" v-if="showActions">
        <ElButton size="small" type="primary" plain :icon="View" @click="handleViewDetail">详情</ElButton>
        <el-tooltip v-if="canManage && config.is_private" content="发布" placement="top">
          <ElButton size="small" type="success" plain :icon="Promotion" circle @click="handleTogglePublish" />
        </el-tooltip>
        <el-tooltip v-if="canManage && !config.is_private" content="退回草稿" placement="top">
          <ElButton size="small" type="warning" plain :icon="DocumentRemove" circle @click="handleTogglePublish" />
        </el-tooltip>
        <el-tooltip v-if="canManage" content="删除" placement="top">
          <ElButton size="small" type="danger" plain :icon="Delete" circle @click="handleDelete" />
        </el-tooltip>
      </div>
    </div>
  </div>
</template>

<style scoped>
.mc-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px;
  border: 1px solid #e8ecf2;
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s, transform 0.15s;
}

.mc-card:hover {
  border-color: #c7d2fe;
  box-shadow: 0 4px 16px rgba(79, 70, 229, 0.06);
  transform: translateY(-2px);
}

/* 第一行：名称 + 状态 */
.mc-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.mc-title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
}

.mc-title h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mc-icon {
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #4f46e5;
  background: #eef2ff;
  font-size: 14px;
}

/* 第二行：模型 + 参数 */
.mc-info {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.provider-tag {
  padding: 2px 8px;
  border-radius: 5px;
  font-size: 11px;
  font-weight: 500;
  border: 1px solid;
  white-space: nowrap;
}

.param-chip {
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
  background: #f1f5f9;
  color: #475569;
  font-family: 'SF Mono', 'Menlo', monospace;
}

/* 第三行：描述 */
.mc-body {
  flex: 1;
  min-height: 20px;
}

.mc-body p {
  margin: 0;
  color: #64748b;
  font-size: 12.5px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 底部 */
.mc-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  border-top: 1px solid #f1f5f9;
  padding-top: 10px;
  margin-top: auto;
}

.mc-meta {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #94a3b8;
  min-width: 0;
}

.mc-author {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 72px;
}

.mc-sep { color: #cbd5e1; }
.mc-date { white-space: nowrap; }

.mc-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}
</style>
