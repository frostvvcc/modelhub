<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue';
import { Search, Plus, Refresh } from '@element-plus/icons-vue';
import { ModelConfig, ModelInfo } from '../types/model_config';
import type { ModelConfigForm } from '../types/model_config';
import { getModelInfos, createConfig, fetchOwnConfigs, updateConfig, deleteModelConfig } from '../api/model';
import ModelConfigCard from '@/components/ModelConfigCard.vue';
import { confirmAction } from '../utils/confirm';
import { useUserStore } from '@/stores/user';

const userStore = useUserStore();
const isAdmin = computed(() => {
  const role = userStore.user?.role;
  return role === 'admin';
});

const baseModels = ref<ModelInfo[]>([]);
const allConfigs = ref<ModelConfig[]>([]);
const loading = ref(false);
const dialogVisible = ref(false);

// ===== 筛选 =====
const searchQuery = ref('');
const selectedBaseModel = ref('');
const selectedCreator = ref('');
const sortBy = ref<'updated' | 'created' | 'name'>('updated');

const baseModelOptions = computed(() => {
  const names = new Set<string>();
  for (const config of allConfigs.value) {
    const model = baseModels.value.find(m => m.id === config.base_model_id);
    if (model) names.add(model.model_name);
  }
  return Array.from(names).sort();
});

const creatorOptions = computed(() => {
  const names = new Set<string>();
  for (const config of allConfigs.value) {
    if ((config as any).author_name) names.add((config as any).author_name);
  }
  return Array.from(names).sort();
});

const filteredConfigs = computed(() => {
  let list = [...allConfigs.value];
  const keyword = searchQuery.value.trim().toLowerCase();
  if (keyword) {
    list = list.filter(c =>
      (c.name || '').toLowerCase().includes(keyword) ||
      (c.describe || '').toLowerCase().includes(keyword)
    );
  }
  if (selectedBaseModel.value) {
    const modelId = baseModels.value.find(m => m.model_name === selectedBaseModel.value)?.id;
    if (modelId) list = list.filter(c => c.base_model_id === modelId);
  }
  if (selectedCreator.value) {
    list = list.filter(c => (c as any).author_name === selectedCreator.value);
  }
  list.sort((a, b) => {
    if (sortBy.value === 'name') return (a.name || '').localeCompare(b.name || '');
    const fa = sortBy.value === 'created' ? a.created_at : a.updated_at;
    const fb = sortBy.value === 'created' ? b.created_at : b.updated_at;
    return new Date(fb || 0).getTime() - new Date(fa || 0).getTime();
  });
  return list;
});

const hasData = computed(() => allConfigs.value.length > 0);
const isFiltering = computed(() => !!searchQuery.value.trim() || !!selectedBaseModel.value || !!selectedCreator.value);

// ===== Tab =====
const activeTab = ref('all');
const tabs = computed(() => {
  const base = [{ key: 'all', label: '全部' }];
  if (isAdmin.value) {
    base.push({ key: 'published', label: '已发布' }, { key: 'draft', label: '草稿' });
  }
  return base;
});

const groupedConfigs = computed(() => {
  const groups: Record<string, ModelConfig[]> = {
    all: filteredConfigs.value,
    published: filteredConfigs.value.filter(c => !c.is_private),
    draft: filteredConfigs.value.filter(c => c.is_private),
  };
  return groups;
});

const countByTab = (key: string) => groupedConfigs.value[key]?.length || 0;
const currentTabItems = computed(() => groupedConfigs.value[activeTab.value] || []);

// 分页
const currentPage = ref(1);
const pageSize = 12;
const pagedItems = computed(() => {
  const start = (currentPage.value - 1) * pageSize;
  return currentTabItems.value.slice(start, start + pageSize);
});

watch(activeTab, () => { currentPage.value = 1; });
watch([searchQuery, selectedBaseModel, selectedCreator, sortBy], () => { currentPage.value = 1; });

// ===== 数据加载 =====
const loadData = async () => {
  loading.value = true;
  try {
    allConfigs.value = await fetchOwnConfigs();
  } catch (error) {
    console.error('加载数据失败:', error);
  } finally {
    loading.value = false;
  }
};

// ===== 表单 =====
const form = ref<ModelConfigForm>({
  id: null,
  name: '',
  describe: '',
  base_model_id: null,
  temperature: 0.7,
  top_p: 0.7,
  prompt: '',
  prompt_variables: '{}',
  knowledge_context_template: '【知识库上下文】\n{context_blocks}\n\n请严格依据以上上下文回答，引用事实时在句末标注来源编号。',
  citation_template: '[来源{index}]',
  refusal_strategy: '如果知识库资料不足以回答，请明确说明"当前知识库依据不足"，不要编造具体政策、日期、流程或数字。',
  max_context_chars: 6000,
  answer_with_citations: true,
  is_private: false
});

const formRules = {
  name: [{ required: true, message: '请输入配置名称', trigger: 'blur' }],
  base_model_id: [{ required: true, message: '请选择基础模型', trigger: 'change' }],
};

const initForm = () => {
  form.value = {
    id: null, name: '', describe: '', base_model_id: null,
    temperature: 0.7, top_p: 0.7, prompt: '',
    prompt_variables: '{}',
    knowledge_context_template: '【知识库上下文】\n{context_blocks}\n\n请严格依据以上上下文回答，引用事实时在句末标注来源编号。',
    citation_template: '[来源{index}]',
    refusal_strategy: '如果知识库资料不足以回答，请明确说明"当前知识库依据不足"，不要编造具体政策、日期、流程或数字。',
    max_context_chars: 6000, answer_with_citations: true,
    is_private: false
  };
};

const handleCreate = () => { initForm(); dialogVisible.value = true; };

const submitForm = async () => {
  loading.value = true;
  try {
    form.value.max_context_chars = Number(form.value.max_context_chars || 6000);
    if (form.value.id) {
      await updateConfig(form.value);
    } else {
      await createConfig(form.value);
    }
    dialogVisible.value = false;
    loadData();
  } catch (error) {
    console.error('保存失败:', error);
  } finally {
    loading.value = false;
  }
};

const handleDelete = async (id: number) => {
  try {
    await confirmAction('确定要删除此配置吗？');
    await deleteModelConfig(id);
    loadData();
  } catch (error) {
    console.error('删除失败:', error);
  }
};

const handleTogglePublish = async (config: ModelConfig) => {
  try {
    const newPrivate = !config.is_private;
    const msg = newPrivate ? '确定将此配置退回草稿？数字助理将无法继续引用。' : '确定发布此配置？发布后可被数字助理引用。';
    await confirmAction(msg);
    await updateConfig({ id: config.id, is_private: newPrivate });
    loadData();
  } catch (error) {
    console.error('操作失败:', error);
  }
};

const getBaseModelName = (config: ModelConfig) => {
  return baseModels.value.find(m => m.id === config.base_model_id)?.model_name;
};

onMounted(async () => {
  baseModels.value = await getModelInfos();
  loadData();
});
</script>

<template>
  <div class="page-container">
    <div class="content-section">
      <!-- 标题 + 操作 -->
      <div class="page-header">
        <div>
          <h2>模型配置管理</h2>
          <p class="subtitle">管理模型参数预设，发布后可供数字助理引用</p>
        </div>
        <div class="header-actions">
          <el-button v-if="isAdmin" type="primary" :icon="Plus" @click="handleCreate">新建配置</el-button>
          <el-button :icon="Refresh" @click="loadData">刷新</el-button>
        </div>
      </div>

      <!-- 筛选栏 -->
      <div class="filter-bar" v-if="!loading && hasData">
        <div class="filter-search">
          <el-icon class="filter-search-icon" :size="15"><Search /></el-icon>
          <input v-model="searchQuery" class="filter-search-input" placeholder="搜索配置名称或描述..." />
        </div>
        <el-select v-model="selectedBaseModel" placeholder="基础模型" clearable class="filter-select" size="default">
          <el-option v-for="name in baseModelOptions" :key="name" :label="name" :value="name" />
        </el-select>
        <el-select v-model="selectedCreator" placeholder="创建者" clearable class="filter-select" size="default">
          <el-option v-for="name in creatorOptions" :key="name" :label="name" :value="name" />
        </el-select>
        <el-select v-model="sortBy" class="filter-select" size="default">
          <el-option label="最近更新" value="updated" />
          <el-option label="最近创建" value="created" />
          <el-option label="名称排序" value="name" />
        </el-select>
      </div>

      <!-- Tab 行 -->
      <div class="tab-row" v-if="hasData">
        <div class="tab-list">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            class="tab-btn"
            :class="{ active: activeTab === tab.key }"
            @click="activeTab = tab.key"
          >
            {{ tab.label }}
            <span class="tab-badge">{{ countByTab(tab.key) }}</span>
          </button>
        </div>
      </div>

      <!-- 卡片网格 -->
      <div v-loading="loading" class="config-body">
        <div v-if="pagedItems.length > 0" class="config-grid">
          <ModelConfigCard
            v-for="config in pagedItems"
            :key="config.id"
            :config="config"
            :base-model-name="getBaseModelName(config)"
            @delete="handleDelete"
            @toggle-publish="handleTogglePublish"
          />
        </div>
        <el-empty v-if="!loading && hasData && pagedItems.length === 0 && isFiltering" description="没有匹配的配置，试试其他关键词" :image-size="80" />
        <el-empty v-else-if="!loading && pagedItems.length === 0 && !isFiltering" description="该分类暂无配置" :image-size="80" />
      </div>

      <!-- 分页 -->
      <div class="config-pagination" v-if="currentTabItems.length > pageSize">
        <el-pagination
          v-model:current-page="currentPage"
          :page-size="pageSize"
          :total="currentTabItems.length"
          layout="prev, pager, next"
          small
        />
      </div>
    </div>

    <!-- 配置表单对话框 -->
    <ElDialog
      v-model="dialogVisible"
      :title="form.id ? '编辑配置' : '新建配置'"
      width="50%"
      style="font-size: larger;"
    >
      <ElForm
        :model="form"
        :rules="formRules"
        label-width="120px"
        ref="formRef"
        class="dialog-form"
      >
        <ElFormItem label="配置名称" prop="name">
          <ElInput v-model="form.name" placeholder="请输入配置名称" />
        </ElFormItem>
        <ElFormItem label="描述" prop="describe">
          <ElInput v-model="form.describe" placeholder="请输入描述" />
        </ElFormItem>
        <ElFormItem label="基础模型" prop="base_model_id">
          <ElSelect v-model="form.base_model_id" placeholder="请选择基础模型" style="width: 100%">
            <ElOption v-for="model in baseModels" :key="model.id" :label="model.model_name" :value="model.id">
              <div class="model-option">
                <span>{{ model.model_name }}</span>
                <span class="model-describe">{{ model.describe }}</span>
              </div>
            </ElOption>
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="温度">
          <ElSlider v-model="form.temperature" :min="0" :max="1" :step="0.1" show-input />
        </ElFormItem>
        <ElFormItem label="Top P">
          <ElSlider v-model="form.top_p" :min="0" :max="1" :step="0.1" show-input />
        </ElFormItem>
        <ElFormItem label="系统提示词">
          <ElInput v-model="form.prompt" type="textarea" :rows="4" placeholder="支持变量：{user_question}、{current_date}、{source_count}、{citation_labels}" />
        </ElFormItem>
        <div class="prompt-orchestration">
          <div class="prompt-title">Prompt 编排</div>
          <ElFormItem label="模板变量">
            <ElInput v-model="form.prompt_variables" type="textarea" :rows="2" placeholder='例如 {"role":"教务助手","tone":"严谨"}' />
          </ElFormItem>
          <ElFormItem label="上下文模板">
            <ElInput v-model="form.knowledge_context_template" type="textarea" :rows="3" placeholder="必须包含 {context_blocks}" />
          </ElFormItem>
          <ElFormItem label="引用格式">
            <ElInput v-model="form.citation_template" placeholder="例如 [来源{index}]" />
          </ElFormItem>
          <ElFormItem label="拒答策略">
            <ElInput v-model="form.refusal_strategy" type="textarea" :rows="2" placeholder="资料不足、禁止回答或低置信度时的处理策略" />
          </ElFormItem>
          <div class="prompt-grid">
            <ElFormItem label="上下文长度">
              <ElInputNumber v-model="form.max_context_chars" :min="1000" :max="30000" :step="500" controls-position="right" style="width: 100%" />
            </ElFormItem>
            <ElFormItem label="正文引用">
              <ElSwitch v-model="form.answer_with_citations" active-text="开启" inactive-text="关闭" />
            </ElFormItem>
          </div>
        </div>
        <ElFormItem label="发布方式">
          <ElRadioGroup v-model="form.is_private">
            <ElRadio :label="false">直接发布</ElRadio>
            <ElRadio :label="true">存为草稿</ElRadio>
          </ElRadioGroup>
          <div class="publish-hint">
            <small v-if="!form.is_private">发布后可被数字助理引用</small>
            <small v-else>草稿仅管理员可见，不会出现在数字助理的模型选择中</small>
          </div>
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="dialogVisible = false">取消</ElButton>
        <ElButton type="primary" @click="submitForm" :loading="loading">保存</ElButton>
      </template>
    </ElDialog>
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

.header-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

/* ===== 筛选栏 ===== */
.filter-bar { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
.filter-search { display: flex; align-items: center; flex: 1; min-width: 180px; max-width: 320px; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 0 12px; height: 34px; transition: border-color 0.15s; }
.filter-search:focus-within { border-color: #a5b4fc; }
.filter-search-icon { color: #94a3b8; flex-shrink: 0; }
.filter-search-input { flex: 1; border: none; outline: none; background: transparent; font-size: 13px; padding: 0 8px; color: #1e293b; height: 100%; }
.filter-search-input::placeholder { color: #94a3b8; }
.filter-select { width: 120px; }
:deep(.filter-select .el-input__wrapper) { height: 34px; border-radius: 8px; font-size: 13px; }

/* ===== Tab 行 ===== */
.tab-row { display: flex; align-items: center; margin-bottom: 16px; border-bottom: 1px solid #e6ebf2; }
.tab-list { display: flex; gap: 4px; }
.tab-btn { display: inline-flex; align-items: center; gap: 6px; padding: 8px 16px; border: none; background: transparent; color: #64748b; font-size: 13.5px; font-weight: 500; cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -1px; transition: all 0.15s; }
.tab-btn:hover { color: #4f46e5; background: #f8f7ff; }
.tab-btn.active { color: #4f46e5; border-bottom-color: #4f46e5; font-weight: 600; }
.tab-badge { padding: 1px 7px; border-radius: 8px; font-size: 11px; font-weight: 600; background: #f1f5f9; color: #64748b; }
.tab-btn.active .tab-badge { background: #e0e7ff; color: #4338ca; }

/* ===== 卡片区 ===== */
.config-body { min-height: 200px; }

.config-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

@media (max-width: 960px) {
  .config-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 600px) {
  .config-grid { grid-template-columns: 1fr; }
}

.config-pagination { display: flex; justify-content: center; margin-top: 16px; }

/* ===== 对话框 ===== */
.model-option { display: flex; justify-content: space-between; width: 100%; }
.model-describe { color: #999; font-size: 0.8em; }

.prompt-orchestration { border: 1px solid #e6ebf2; border-radius: 8px; padding: 14px 14px 2px; margin-bottom: 18px; background: #f8fafc; }
.prompt-title { font-size: 0.92rem; font-weight: 600; color: #334155; margin-bottom: 12px; }
.prompt-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(180px, 0.4fr); gap: 12px; }

.publish-hint { margin-top: 4px; }
.publish-hint small { color: #94a3b8; font-size: 12px; }

.dialog-form { font-size: 1.1em; }
.dialog-form :deep(.el-form-item__label) { font-size: 1.1em; font-weight: 500; }
.dialog-form :deep(.el-input__inner),
.dialog-form :deep(.el-textarea__inner),
.dialog-form :deep(.el-radio__label) { font-size: 1.1em; }

/* ===== 响应式 ===== */
@media (max-width: 768px) {
  .page-header { flex-direction: column; }
  .prompt-grid { grid-template-columns: 1fr; }
}

@media (max-width: 640px) {
  .filter-bar { flex-direction: column; align-items: stretch; }
  .filter-search { max-width: 100%; }
  .filter-select { width: 100%; }
}
</style>
