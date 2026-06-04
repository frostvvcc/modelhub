<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage, ElDialog } from 'element-plus';
import { Back, View, Hide, Edit } from '@element-plus/icons-vue';
import { updateConfig, getModelConfig } from '../api/model';
import { getModelInfos } from '../api/model';
import { ModelConfig, ModelInfo } from '../types/model_config';
import { useUserStore } from '../stores/user';

const route = useRoute();
const router = useRouter();
const userStore = useUserStore();
const configId = ref(Number(route.params.id));
const modelConfig = ref<ModelConfig | null>();
const baseModels = ref<ModelInfo[]>([]);
const loading = ref(false);
const dialogVisible = ref(false);

const canManage = computed(() => {
  if (!modelConfig.value) return false;
  const role = userStore.user?.role;
  if (role === 'admin') return true;
  return modelConfig.value.user_id === Number(userStore.user?.id);
});

const baseModelName = computed(() => {
  if (!modelConfig.value) return '未知模型';
  return baseModels.value.find(m => m.id === modelConfig.value?.base_model_id)?.model_name || '未知模型';
});

const authorName = computed(() => {
  if (!modelConfig.value) return '';
  const c = modelConfig.value as Record<string, unknown>;
  return c.author || c.author_name || `用户 #${modelConfig.value.user_id}`;
});

const providerColor = computed(() => {
  const name = (baseModelName.value || '').toLowerCase();
  if (name.includes('qwen') || name.includes('通义')) return { bg: '#fff7ed', border: '#fed7aa', text: '#c2410c' };
  if (name.includes('deepseek')) return { bg: '#f0fdf4', border: '#bbf7d0', text: '#15803d' };
  if (name.includes('gpt') || name.includes('openai')) return { bg: '#f0f9ff', border: '#bae6fd', text: '#0369a1' };
  if (name.includes('claude') || name.includes('anthropic')) return { bg: '#faf5ff', border: '#e9d5ff', text: '#7e22ce' };
  return { bg: '#f8fafc', border: '#e2e8f0', text: '#475569' };
});

const customColors = computed(() => [
  { color: '#e0e7ff', percentage: 20 },
  { color: '#a5b4fc', percentage: 40 },
  { color: '#818cf8', percentage: 60 },
  { color: '#6366f1', percentage: 80 },
  { color: '#4f46e5', percentage: 100 }
]);

const form = ref({
  name: '',
  describe: '',
  base_model_id: null as number | null,
  temperature: 0.7,
  top_p: 0.7,
  prompt: '',
  prompt_variables: '{}',
  knowledge_context_template: '',
  citation_template: '',
  refusal_strategy: '',
  max_context_chars: 6000,
  answer_with_citations: true,
  is_private: false
});

const formRules = {
  name: [{ required: true, message: '请输入配置名称', trigger: 'blur' }],
  base_model_id: [{ required: true, message: '请选择基础模型', trigger: 'change' }],
};

const handleEdit = () => {
  if (modelConfig.value) {
    form.value = {
      name: modelConfig.value.name,
      describe: modelConfig.value.describe || '',
      base_model_id: modelConfig.value.base_model_id,
      temperature: Number(modelConfig.value.temperature),
      top_p: Number(modelConfig.value.top_p),
      prompt: modelConfig.value.prompt || '',
      prompt_variables: modelConfig.value.prompt_variables || '{}',
      knowledge_context_template: modelConfig.value.knowledge_context_template || '',
      citation_template: modelConfig.value.citation_template || '',
      refusal_strategy: modelConfig.value.refusal_strategy || '',
      max_context_chars: modelConfig.value.max_context_chars || 6000,
      answer_with_citations: modelConfig.value.answer_with_citations ?? true,
      is_private: modelConfig.value.is_private
    };
  }
  dialogVisible.value = true;
};

const handleCancel = () => {
  dialogVisible.value = false;
};

const handleSave = async () => {
  loading.value = true;
  try {
    const updated_config = await updateConfig({
      id: configId.value,
      ...form.value
    });
    modelConfig.value = updated_config;
    ElMessage.success('配置更新成功');
    dialogVisible.value = false;
  } catch (error) {
    ElMessage.error('配置更新失败');
  } finally {
    loading.value = false;
  }
};

onMounted(async () => {
  loading.value = true;
  try {
    baseModels.value = await getModelInfos();
    if (history.state?.config) {
      modelConfig.value = history.state.config;
    }
    if (!modelConfig.value && configId.value > 0) {
      modelConfig.value = await getModelConfig(configId.value);
    }
    if (!modelConfig.value) {
      ElMessage.error('模型配置不存在');
      router.go(-1);
    }
  } catch (error) {
    ElMessage.error('加载配置详情失败');
  } finally {
    loading.value = false;
  }
});

const isVisible = ref(false);
const toggleVisibility = () => { isVisible.value = !isVisible.value; };
const goBack = () => router.go(-1);
</script>

<template>
  <div class="page-container">
    <div class="content-section">
      <div v-loading="loading">
        <div v-if="modelConfig" class="cd-page">

          <!-- ===== Header ===== -->
          <div class="cd-header">
            <div class="cd-header-left">
              <button class="cd-back" @click="goBack">
                <el-icon :size="16"><Back /></el-icon>
              </button>
              <div class="cd-header-info">
                <div class="cd-title-row">
                  <h2 class="cd-title">{{ modelConfig.name }}</h2>
                  <el-tag
                    :type="modelConfig.is_private ? 'info' : 'success'"
                    size="small"
                    effect="plain"
                  >{{ modelConfig.is_private ? '草稿' : '已发布' }}</el-tag>
                </div>
                <div class="cd-meta-row">
                  <span
                    class="cd-model-tag"
                    :style="{ background: providerColor.bg, color: providerColor.text, borderColor: providerColor.border }"
                  >{{ baseModelName }}</span>
                  <span class="cd-meta-sep">&middot;</span>
                  <span class="cd-meta-text">{{ authorName }}</span>
                  <span class="cd-meta-sep">&middot;</span>
                  <span class="cd-meta-text">{{ new Date(modelConfig.updated_at).toLocaleDateString() }} 更新</span>
                </div>
              </div>
            </div>
            <el-button v-if="canManage" type="primary" size="default" :icon="Edit" @click="handleEdit">编辑配置</el-button>
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
                  <span class="cd-label">配置名称</span>
                  <span class="cd-value">{{ modelConfig.name }}</span>
                </div>
                <div class="cd-field">
                  <span class="cd-label">基础模型</span>
                  <span class="cd-value cd-value-highlight">{{ baseModelName }}</span>
                </div>
                <div class="cd-field">
                  <span class="cd-label">可见性</span>
                  <span class="cd-value">
                    <el-tag :type="modelConfig.is_private ? 'warning' : 'success'" size="small" effect="plain">
                      {{ modelConfig.is_private ? '私有（草稿）' : '公开（已发布）' }}
                    </el-tag>
                  </span>
                </div>
                <div class="cd-field">
                  <span class="cd-label">创建者</span>
                  <span class="cd-value">{{ authorName }}</span>
                </div>
                <div class="cd-field">
                  <span class="cd-label">
                    Share ID
                    <el-icon class="cd-eye-btn" @click="toggleVisibility">
                      <View v-if="isVisible" /><Hide v-else />
                    </el-icon>
                  </span>
                  <span class="cd-value cd-mono" v-if="isVisible">{{ modelConfig.share_id }}</span>
                  <span class="cd-value cd-mono" v-else>***********</span>
                </div>
                <div class="cd-field cd-field-full">
                  <span class="cd-label">描述</span>
                  <span class="cd-value">{{ modelConfig.describe || '暂无描述' }}</span>
                </div>
              </div>
            </div>

            <!-- 右列：模型参数 + 引用与 RAG -->
            <div class="cd-col-right">
              <div class="cd-card">
                <div class="cd-card-head">
                  <span class="cd-accent" style="background:#f59e0b"></span>
                  <h3 class="cd-card-title">模型参数</h3>
                </div>
                <div class="cd-params">
                  <div class="cd-param">
                    <div class="cd-param-row">
                      <span class="cd-param-label">Temperature</span>
                      <span class="cd-param-num">{{ modelConfig.temperature }}</span>
                    </div>
                    <ElProgress :percentage="Number(modelConfig.temperature) * 100" :color="customColors" :show-text="false" :stroke-width="6" />
                  </div>
                  <div class="cd-param">
                    <div class="cd-param-row">
                      <span class="cd-param-label">Top P</span>
                      <span class="cd-param-num">{{ modelConfig.top_p }}</span>
                    </div>
                    <ElProgress :percentage="Number(modelConfig.top_p) * 100" :color="customColors" :show-text="false" :stroke-width="6" />
                  </div>
                </div>
              </div>

              <div class="cd-card">
                <div class="cd-card-head">
                  <span class="cd-accent" style="background:#10b981"></span>
                  <h3 class="cd-card-title">引用与 RAG</h3>
                </div>
                <div class="cd-kv-list">
                  <div class="cd-kv">
                    <span class="cd-kv-label">上下文长度</span>
                    <span class="cd-kv-value">{{ modelConfig.max_context_chars || 6000 }} 字符</span>
                  </div>
                  <div class="cd-kv">
                    <span class="cd-kv-label">正文引用</span>
                    <el-tag :type="modelConfig.answer_with_citations !== false ? 'success' : 'info'" size="small" effect="plain">
                      {{ modelConfig.answer_with_citations !== false ? '开启' : '关闭' }}
                    </el-tag>
                  </div>
                  <div class="cd-kv">
                    <span class="cd-kv-label">引用格式</span>
                    <span class="cd-kv-value cd-mono">{{ modelConfig.citation_template || '未设置' }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- ===== 系统提示词 ===== -->
          <div class="cd-card">
            <div class="cd-card-head">
              <span class="cd-accent" style="background:#8b5cf6"></span>
              <h3 class="cd-card-title">系统提示词</h3>
            </div>
            <pre class="cd-prompt-text">{{ modelConfig.prompt || '未设置' }}</pre>
          </div>

          <!-- ===== Prompt 编排 ===== -->
          <div class="cd-card" v-if="modelConfig.knowledge_context_template || modelConfig.refusal_strategy">
            <div class="cd-card-head">
              <span class="cd-accent" style="background:#ec4899"></span>
              <h3 class="cd-card-title">Prompt 编排</h3>
            </div>
            <div class="cd-grid-2-equal">
              <div class="cd-prompt-block" v-if="modelConfig.knowledge_context_template">
                <span class="cd-block-label">上下文模板</span>
                <pre class="cd-block-code">{{ modelConfig.knowledge_context_template }}</pre>
              </div>
              <div class="cd-prompt-block" v-if="modelConfig.refusal_strategy">
                <span class="cd-block-label">拒答策略</span>
                <pre class="cd-block-code">{{ modelConfig.refusal_strategy }}</pre>
              </div>
            </div>
          </div>

        </div>
      </div>
    </div>

    <!-- ===== 编辑对话框 ===== -->
    <ElDialog v-model="dialogVisible" title="编辑模型配置" width="50%" :before-close="handleCancel" style="font-size: larger;">
      <ElForm :model="form" :rules="formRules" label-width="120px" class="cd-edit-form">
        <ElFormItem label="配置名称" prop="name">
          <ElInput v-model="form.name" placeholder="请输入配置名称" />
        </ElFormItem>
        <ElFormItem label="描述">
          <ElInput v-model="form.describe" placeholder="请输入描述" />
        </ElFormItem>
        <ElFormItem label="基础模型" prop="base_model_id">
          <ElSelect v-model="form.base_model_id" placeholder="请选择基础模型" style="width: 100%">
            <ElOption v-for="model in baseModels" :key="model.id" :label="model.model_name" :value="model.id" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="温度">
          <ElSlider v-model="form.temperature" :min="0" :max="1" :step="0.1" show-input />
        </ElFormItem>
        <ElFormItem label="Top P">
          <ElSlider v-model="form.top_p" :min="0" :max="1" :step="0.1" show-input />
        </ElFormItem>
        <ElFormItem label="系统提示词">
          <ElInput v-model="form.prompt" type="textarea" :rows="4" placeholder="请输入系统提示词..." />
        </ElFormItem>
        <div class="cd-edit-orchestration">
          <div class="cd-edit-orchestration-title">Prompt 编排</div>
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
            <ElInput v-model="form.refusal_strategy" type="textarea" :rows="2" placeholder="资料不足时的处理策略" />
          </ElFormItem>
          <div class="cd-edit-grid">
            <ElFormItem label="上下文长度">
              <ElInputNumber v-model="form.max_context_chars" :min="1000" :max="30000" :step="500" controls-position="right" style="width: 100%" />
            </ElFormItem>
            <ElFormItem label="正文引用">
              <ElSwitch v-model="form.answer_with_citations" active-text="开启" inactive-text="关闭" />
            </ElFormItem>
          </div>
        </div>
        <ElFormItem label="可见性">
          <ElRadioGroup v-model="form.is_private">
            <ElRadio :label="false">公开</ElRadio>
            <ElRadio :label="true">私有</ElRadio>
          </ElRadioGroup>
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="handleCancel">取消</ElButton>
        <ElButton type="primary" @click="handleSave" :loading="loading">保存</ElButton>
      </template>
    </ElDialog>
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

.cd-model-tag {
  padding: 1px 8px;
  border-radius: 5px;
  font-size: 11.5px;
  font-weight: 500;
  border: 1px solid;
  white-space: nowrap;
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
.cd-mono { font-family: 'SF Mono', 'Menlo', 'Consolas', monospace; font-size: 12.5px; }

.cd-eye-btn {
  cursor: pointer;
  color: #94a3b8;
  transition: color 0.15s;
}
.cd-eye-btn:hover { color: #6366f1; }

/* ===== 模型参数 ===== */
.cd-params {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.cd-param-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.cd-param-label { font-size: 13px; color: #475569; }
.cd-param-num { font-size: 13px; font-weight: 600; color: #1e293b; font-family: 'SF Mono', 'Menlo', monospace; }

/* ===== 引用与 RAG ===== */
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

/* ===== Prompt 编排 ===== */
.cd-grid-2-equal {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.cd-prompt-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.cd-block-label {
  font-size: 12px;
  color: #94a3b8;
  font-weight: 500;
}

.cd-block-code {
  margin: 0;
  font-size: 12.5px;
  color: #475569;
  background: #f8fafc;
  padding: 10px 12px;
  border-radius: 6px;
  border: 1px solid #f1f5f9;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
  font-family: 'SF Mono', 'Menlo', 'Consolas', monospace;
}

/* ===== 编辑对话框 ===== */
.cd-edit-form { font-size: 1.1em; }
.cd-edit-form :deep(.el-form-item__label) { font-size: 1.1em; font-weight: 500; }
.cd-edit-form :deep(.el-input__inner),
.cd-edit-form :deep(.el-textarea__inner),
.cd-edit-form :deep(.el-radio__label) { font-size: 1.1em; }

.cd-edit-orchestration {
  border: 1px solid #e6ebf2;
  border-radius: 8px;
  padding: 14px 14px 2px;
  margin-bottom: 18px;
  background: #f8fafc;
}

.cd-edit-orchestration-title {
  font-size: 0.92rem;
  font-weight: 600;
  color: #334155;
  margin-bottom: 12px;
}

.cd-edit-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(180px, 0.4fr);
  gap: 12px;
}

/* ===== 响应式 ===== */
@media (max-width: 860px) {
  .cd-grid-2 { grid-template-columns: 1fr; }
  .cd-grid-2-equal { grid-template-columns: 1fr; }
  .cd-fields { grid-template-columns: 1fr; }
  .cd-header { flex-direction: column; align-items: flex-start; }
}

@media (max-width: 640px) {
  .cd-edit-grid { grid-template-columns: 1fr; }
}
</style>
