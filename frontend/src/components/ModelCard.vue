<script setup lang="ts">
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import { View } from '@element-plus/icons-vue';

interface ModelCardProps {
  id: number;
  name: string;
  author: string;
  isFeatured: boolean;
  describe: string;
  base_model_name: string;
  provider_name?: string | null;
  update_at: string;
}

const props = withDefaults(defineProps<ModelCardProps>(), {
  isFeatured: false,
});

const router = useRouter();

const handleClick = () => {
  router.push({ name: 'configDetail', params: { id: props.id } });
};

const providerColor = computed(() => {
  const name = (props.provider_name || props.base_model_name || '').toLowerCase();
  if (name.includes('qwen') || name.includes('通义')) return { bg: '#fff7ed', border: '#fed7aa', text: '#c2410c', accent: '#ea580c' };
  if (name.includes('deepseek')) return { bg: '#f0fdf4', border: '#bbf7d0', text: '#15803d', accent: '#16a34a' };
  if (name.includes('gpt') || name.includes('openai')) return { bg: '#f0f9ff', border: '#bae6fd', text: '#0369a1', accent: '#0284c7' };
  if (name.includes('claude') || name.includes('anthropic')) return { bg: '#faf5ff', border: '#e9d5ff', text: '#7e22ce', accent: '#9333ea' };
  if (name.includes('llama') || name.includes('meta')) return { bg: '#eff6ff', border: '#bfdbfe', text: '#1d4ed8', accent: '#2563eb' };
  if (name.includes('gemini') || name.includes('google')) return { bg: '#fefce8', border: '#fde68a', text: '#a16207', accent: '#ca8a04' };
  return { bg: '#f8fafc', border: '#e2e8f0', text: '#475569', accent: '#64748b' };
});

const modelInitial = computed(() => {
  return props.name.charAt(0).toUpperCase();
});
</script>

<template>
  <div class="mp-card" @click="handleClick">
    <div class="mp-card-top">
      <div class="mp-card-icon" :style="{ background: providerColor.accent }">
        {{ modelInitial }}
      </div>
      <div class="mp-card-info">
        <h3 class="mp-card-name">{{ name }}</h3>
        <span class="mp-card-author">{{ author }}</span>
      </div>
    </div>

    <p class="mp-card-desc">{{ describe || '暂无描述' }}</p>

    <div class="mp-card-bottom">
      <span
        class="mp-card-tag"
        :style="{ background: providerColor.bg, color: providerColor.text, borderColor: providerColor.border }"
      >{{ base_model_name }}</span>
      <button class="mp-card-btn" @click.stop="handleClick">
        <el-icon :size="14"><View /></el-icon>
        详情
      </button>
    </div>
  </div>
</template>

<style scoped>
.mp-card {
  border: 1px solid #e8ecf2;
  border-radius: 10px;
  padding: 14px 16px;
  background: #fff;
  display: flex;
  flex-direction: column;
  cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s, transform 0.2s;
  min-height: 140px;
}

.mp-card:hover {
  border-color: #93c5fd;
  box-shadow: 0 8px 24px rgba(37, 99, 235, 0.08);
  transform: translateY(-3px);
}

.mp-card-top {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.mp-card-icon {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 0.95rem;
  font-weight: 700;
  flex-shrink: 0;
}

.mp-card-info {
  min-width: 0;
  flex: 1;
}

.mp-card-name {
  margin: 0;
  font-size: 0.88rem;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: 1.3;
}

.mp-card-author {
  font-size: 0.74rem;
  color: #94a3b8;
  line-height: 1.3;
}

.mp-card-desc {
  margin: 0 0 auto;
  padding-bottom: 10px;
  color: #64748b;
  font-size: 0.8rem;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.mp-card-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  border-top: 1px solid #f1f5f9;
  padding-top: 10px;
}

.mp-card-tag {
  padding: 2px 8px;
  border-radius: 5px;
  font-size: 0.7rem;
  font-weight: 500;
  border: 1px solid;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 60%;
}

.mp-card-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 5px 12px;
  border: none;
  border-radius: 6px;
  background: #2563eb;
  color: #fff;
  font-size: 0.75rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s;
  white-space: nowrap;
  flex-shrink: 0;
}

.mp-card-btn:hover {
  background: #1d4ed8;
}
</style>
