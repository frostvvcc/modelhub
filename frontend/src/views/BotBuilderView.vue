<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, type FormInstance } from "element-plus";
import { Back, Plus, Close, Search, Connection } from "@element-plus/icons-vue";
import { createBot, getBot, updateBot, type BotCreate } from "../api/bot";
import { fetchOwnVectors } from "../api/vectorDb";
import { fetchOwnConfigs, getModelConfigs } from "../api/model";
import { useUserStore } from "../stores/user";

const router = useRouter();
const route = useRoute();
const userStore = useUserStore();
const editId = computed(() => Number(route.params.id) || 0);
const isEdit = computed(() => editId.value > 0);

const activeStep = ref(0);
const formRef = ref<FormInstance>();
const submitting = ref(false);
const loading = ref(false);
const newForbiddenTopic = ref("");
const vectorDbs = ref<Record<string, unknown>[]>([]);
const modelConfigs = ref<Record<string, unknown>[]>([]);

const form = ref<BotCreate>({
  name: "",
  description: "",
  avatar: "",
  system_prompt: "",
  greeting: "",
  forbidden_topics: [],
  model_config_id: undefined,
  vector_db_ids: [],
  organization_id: null,
});

const rules = {
  name: [{ required: true, message: "请填写助理名称", trigger: "blur" }],
  model_config_id: [{ required: true, message: "请选择模型配置", trigger: "change" }],
};

const availableOrganizations = computed(() => {
  const userRole = userStore.user?.role || 'student';
  if (userRole === 'student') return [];
  return userStore.userOrganizations.filter(o => !userStore.isVirtualOrganization(o));
});

const loadOptions = async () => {
  const [vectors, ownConfigs, publicConfigs] = await Promise.all([
    fetchOwnVectors(),
    fetchOwnConfigs().catch(() => []),
    getModelConfigs().catch(() => []),
  ]);
  vectorDbs.value = vectors || [];
  const merged = [...(ownConfigs || []), ...(publicConfigs || [])];
  modelConfigs.value = merged.filter((item, index, all) =>
    item?.id && all.findIndex(other => other?.id === item.id) === index
  );
};

const loadBot = async () => {
  if (!isEdit.value) return;
  const bot = await getBot(editId.value);
  form.value = {
    name: bot.name,
    description: bot.description || "",
    avatar: bot.avatar || "",
    system_prompt: bot.system_prompt || "",
    greeting: bot.greeting || "",
    forbidden_topics: bot.forbidden_topics || [],
    model_config_id: bot.model_config_id,
    vector_db_ids: bot.vector_db_ids || [],
    organization_id: bot.organization_id ?? null,
  };
};

const addForbiddenTopic = () => {
  const value = newForbiddenTopic.value.trim();
  if (!value) return;
  if (!form.value.forbidden_topics?.includes(value)) {
    form.value.forbidden_topics = [...(form.value.forbidden_topics || []), value];
  }
  newForbiddenTopic.value = "";
};

const removeForbiddenTopic = (topic: string) => {
  form.value.forbidden_topics = (form.value.forbidden_topics || []).filter(item => item !== topic);
};

const nextStep = async () => {
  if (activeStep.value === 0) {
    await formRef.value?.validateField(["name"]);
  }
  if (activeStep.value === 2) {
    await formRef.value?.validateField(["model_config_id"]);
  }
  activeStep.value = Math.min(2, activeStep.value + 1);
};

const prevStep = () => {
  activeStep.value = Math.max(0, activeStep.value - 1);
};

const submit = async () => {
  await formRef.value?.validate();
  submitting.value = true;
  try {
    const payload = { ...form.value };
    if (isEdit.value) {
      await updateBot(editId.value, payload);
      ElMessage.success("数字助理已更新");
    } else {
      await createBot(payload);
      ElMessage.success("数字助理已创建");
    }
    router.push("/bots");
  } catch (error: unknown) {
    ElMessage.error(error?.response?.data?.detail || "保存失败");
  } finally {
    submitting.value = false;
  }
};

onMounted(async () => {
  loading.value = true;
  try {
    await loadOptions();
    await loadBot();
  } catch (error: unknown) {
    ElMessage.error(error?.response?.data?.detail || "页面初始化失败");
  } finally {
    loading.value = false;
  }
});

// ===== 知识库选择器 Dialog =====
const kbPickerVisible = ref(false);
const kbSearch = ref('');
const kbActiveTab = ref('private');
const kbTempSelected = ref<number[]>([]);

const kbScopeOrder = ['school', 'college', 'private'] as const;
const kbScopeLabels: Record<string, string> = {
  school: '学校级',
  college: '学院/部门级',
  private: '私有',
};

const schoolOrgId = computed(() => userStore.currentSchool?.id || null);

const kbGrouped = computed(() => {
  const groups: Record<string, Record<string, unknown>[]> = {};
  const keyword = kbSearch.value.trim().toLowerCase();
  for (const db of vectorDbs.value) {
    if (keyword && !(db.name || '').toLowerCase().includes(keyword) && !(db.describe || '').toLowerCase().includes(keyword)) continue;
    let scope: string;
    if (!db.organization_id) {
      scope = 'private';
    } else if (db.organization_id === schoolOrgId.value) {
      scope = 'school';
    } else {
      scope = 'college';
    }
    if (!groups[scope]) groups[scope] = [];
    groups[scope].push(db);
  }
  return groups;
});

const kbCurrentItems = computed(() => kbGrouped.value[kbActiveTab.value] || []);
const kbCountByScope = (scope: string) => kbGrouped.value[scope]?.length || 0;

const isKbAllSelected = computed(() => {
  const items = kbCurrentItems.value;
  return items.length > 0 && items.every(db => kbTempSelected.value.includes(db.id));
});

const isKbIndeterminate = computed(() => {
  const items = kbCurrentItems.value;
  const selectedCount = items.filter(db => kbTempSelected.value.includes(db.id)).length;
  return selectedCount > 0 && selectedCount < items.length;
});

const toggleKbSelectAll = (checked: boolean) => {
  const ids = kbCurrentItems.value.map(db => db.id);
  if (checked) {
    const set = new Set([...kbTempSelected.value, ...ids]);
    kbTempSelected.value = Array.from(set);
  } else {
    kbTempSelected.value = kbTempSelected.value.filter(id => !ids.includes(id));
  }
};

const openKbPicker = () => {
  kbTempSelected.value = [...(form.value.vector_db_ids || [])];
  kbSearch.value = '';
  kbActiveTab.value = 'private';
  kbPickerVisible.value = true;
};

const confirmKbPicker = () => {
  // 当 Bot 有 organization_id 时，检查是否绑定了私有知识库并提示
  if (form.value.organization_id && kbTempSelected.value.length > 0) {
    const restrictedKbs = vectorDbs.value.filter(db => {
      if (!kbTempSelected.value.includes(db.id)) return false;
      return !db.organization_id; // 私有知识库
    });
    if (restrictedKbs.length > 0) {
      const names = restrictedKbs.map(db => db.name).join('、');
      ElMessage.warning({
        message: `提示：知识库「${names}」为私有，绑定后其他用户可通过助理间接检索其中内容。`,
        duration: 6000,
        showClose: true,
      });
    }
  }
  form.value.vector_db_ids = [...kbTempSelected.value];
  kbPickerVisible.value = false;
};

const removeSelectedKb = (id: number) => {
  form.value.vector_db_ids = (form.value.vector_db_ids || []).filter(v => v !== id);
};

const getKbName = (id: number) => {
  const db = vectorDbs.value.find(v => v.id === id);
  return db?.name || `知识库 #${id}`;
};
</script>

<template>
  <div class="page-container bot-builder-view" v-loading="loading">
    <div class="detail-header">
      <el-button :icon="Back" text @click="router.push('/bots')">返回</el-button>
      <div>
        <h2>{{ isEdit ? "编辑数字助理" : "创建数字助理" }}</h2>
        <p class="subtitle" style="margin:2px 0 0">三步完成基础信息、人设 Prompt、知识库与模型绑定。</p>
      </div>
    </div>

    <el-steps :active="activeStep" align-center class="steps">
      <el-step title="基础信息" description="名称、描述、可见范围" />
      <el-step title="人设与安全" description="Prompt、开场白、禁止话题" />
      <el-step title="能力配置" description="模型配置、知识库" />
    </el-steps>

    <el-form ref="formRef" :model="form" :rules="rules" label-width="112px" class="builder-form">
      <section v-show="activeStep === 0" class="step-panel">
        <el-form-item label="助理名称" prop="name">
          <el-input v-model="form.name" maxlength="100" show-word-limit placeholder="例如：毕业设计答疑助理" />
        </el-form-item>
        <el-form-item label="助理描述">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="说明这个助理适合回答哪些问题" />
        </el-form-item>
        <el-form-item label="可见范围">
          <el-select v-model="form.organization_id" placeholder="私有（仅自己可见）" clearable style="width: 100%">
            <el-option :value="null" label="私有（仅自己可见）" />
            <el-option v-for="org in availableOrganizations" :key="org.id" :label="org.name" :value="org.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="头像链接">
          <el-input v-model="form.avatar" placeholder="可选，填写图片 URL" />
        </el-form-item>
      </section>

      <section v-show="activeStep === 1" class="step-panel">
        <el-form-item label="系统 Prompt">
          <el-input
            v-model="form.system_prompt"
            type="textarea"
            :rows="7"
            placeholder="定义助理角色、回答边界、引用规则。例如：你是山东科技大学毕业设计答疑助理，回答必须优先依据知识库来源。"
          />
        </el-form-item>
        <el-form-item label="开场白">
          <el-input v-model="form.greeting" maxlength="500" show-word-limit placeholder="例如：你好，我可以帮你查询毕业设计相关要求。" />
        </el-form-item>
        <el-form-item label="禁止话题">
          <div class="topic-editor">
            <div class="topic-input">
              <el-input
                v-model="newForbiddenTopic"
                placeholder="输入关键词，回车添加"
                @keyup.enter="addForbiddenTopic"
              />
              <el-button :icon="Plus" @click="addForbiddenTopic">添加</el-button>
            </div>
            <div class="topic-list">
              <el-tag
                v-for="topic in form.forbidden_topics"
                :key="topic"
                type="danger"
                effect="plain"
              >
                {{ topic }}
                <el-icon class="topic-remove" @click="removeForbiddenTopic(topic)"><Close /></el-icon>
              </el-tag>
            </div>
          </div>
        </el-form-item>
      </section>

      <section v-show="activeStep === 2" class="step-panel">
        <el-form-item label="模型配置" prop="model_config_id">
          <el-select v-model="form.model_config_id" placeholder="选择一个模型配置" filterable style="width: 100%">
            <el-option v-for="config in modelConfigs" :key="config.id" :label="config.name" :value="config.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="关联知识库">
          <div class="kb-picker-area">
            <el-button @click="openKbPicker">选择知识库</el-button>
            <span class="kb-picker-hint" v-if="!form.vector_db_ids?.length">不选则仅使用模型通用能力</span>
            <div class="kb-selected-tags" v-if="form.vector_db_ids?.length">
              <el-tag
                v-for="id in form.vector_db_ids"
                :key="id"
                closable
                @close="removeSelectedKb(id)"
              >{{ getKbName(id) }}</el-tag>
            </div>
          </div>
        </el-form-item>
      </section>
    </el-form>

    <div class="step-actions">
      <el-button v-if="activeStep > 0" @click="prevStep">上一步</el-button>
      <el-button v-if="activeStep < 2" type="primary" @click="nextStep">下一步</el-button>
      <el-button v-else type="primary" :loading="submitting" @click="submit">
        {{ isEdit ? "保存修改" : "创建助理" }}
      </el-button>
    </div>

    <!-- 知识库选择器 Dialog -->
    <el-dialog v-model="kbPickerVisible" title="选择关联知识库" width="640px" :close-on-click-modal="false">
      <div class="kb-dialog-content">
        <!-- 搜索 -->
        <div class="kb-dialog-search">
          <el-icon class="kb-dialog-search-icon" :size="15"><Search /></el-icon>
          <input v-model="kbSearch" class="kb-dialog-search-input" placeholder="搜索知识库名称或描述..." />
        </div>

        <!-- Tab -->
        <div class="kb-dialog-tabs">
          <button
            v-for="scope in kbScopeOrder"
            :key="scope"
            class="kb-dialog-tab"
            :class="{ active: kbActiveTab === scope }"
            @click="kbActiveTab = scope"
          >
            {{ kbScopeLabels[scope] }}
            <span class="kb-dialog-tab-badge">{{ kbCountByScope(scope) }}</span>
          </button>
        </div>

        <!-- 全选 -->
        <div class="kb-dialog-selectall" v-if="kbCurrentItems.length > 0">
          <el-checkbox
            :model-value="isKbAllSelected"
            :indeterminate="isKbIndeterminate"
            @change="toggleKbSelectAll"
          >全选当前分组（{{ kbCurrentItems.length }} 个）</el-checkbox>
        </div>

        <!-- 列表 -->
        <div class="kb-dialog-list">
          <el-empty v-if="kbCurrentItems.length === 0" description="该分类暂无知识库" :image-size="60" />
          <label
            v-for="db in kbCurrentItems"
            :key="db.id"
            class="kb-dialog-item"
            :class="{ selected: kbTempSelected.includes(db.id) }"
          >
            <el-checkbox v-model="kbTempSelected" :value="db.id" />
            <div class="kb-dialog-item-info">
              <div class="kb-dialog-item-name">
                <el-icon class="kb-dialog-item-icon"><Connection /></el-icon>
                {{ db.name }}
              </div>
              <div class="kb-dialog-item-desc" v-if="db.describe">{{ db.describe }}</div>
              <div class="kb-dialog-item-meta">
                <span v-if="db.creator_name">{{ db.creator_name }}</span>
              </div>
            </div>
          </label>
        </div>
      </div>
      <template #footer>
        <span class="kb-dialog-footer-info">已选 {{ kbTempSelected.length }} 个知识库</span>
        <el-button @click="kbPickerVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmKbPicker">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.bot-builder-view {
  max-width: 860px;
  padding: 24px;
}

.steps {
  margin-bottom: 28px;
}

.builder-form {
  max-width: 760px;
}

.step-panel {
  padding: 8px 0;
}

.topic-editor {
  width: 100%;
}

.topic-input {
  display: flex;
  gap: 8px;
}

.topic-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  min-height: 34px;
  margin-top: 10px;
}

.topic-remove {
  margin-left: 5px;
  cursor: pointer;
}

.step-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 24px;
}

/* ===== 知识库选择器触发区 ===== */
.kb-picker-area {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.kb-picker-hint {
  font-size: 12px;
  color: #94a3b8;
}

.kb-selected-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

/* ===== 知识库 Dialog ===== */
.kb-dialog-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.kb-dialog-search {
  display: flex;
  align-items: center;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 0 12px;
  height: 36px;
  transition: border-color 0.15s;
}

.kb-dialog-search:focus-within {
  border-color: #a5b4fc;
}

.kb-dialog-search-icon {
  color: #94a3b8;
  flex-shrink: 0;
}

.kb-dialog-search-input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 13px;
  padding: 0 8px;
  color: #1e293b;
  height: 100%;
}

.kb-dialog-search-input::placeholder {
  color: #94a3b8;
}

.kb-dialog-tabs {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid #e6ebf2;
}

.kb-dialog-tab {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 7px 14px;
  border: none;
  background: transparent;
  color: #64748b;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  transition: all 0.15s;
}

.kb-dialog-tab:hover {
  color: #4f46e5;
  background: #f8f7ff;
}

.kb-dialog-tab.active {
  color: #4f46e5;
  border-bottom-color: #4f46e5;
  font-weight: 600;
}

.kb-dialog-tab-badge {
  padding: 1px 6px;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 600;
  background: #f1f5f9;
  color: #64748b;
}

.kb-dialog-tab.active .kb-dialog-tab-badge {
  background: #e0e7ff;
  color: #4338ca;
}

.kb-dialog-selectall {
  padding: 4px 0;
  font-size: 13px;
}

.kb-dialog-list {
  max-height: 320px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.kb-dialog-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid #f0f0f0;
  cursor: pointer;
  transition: all 0.15s;
}

.kb-dialog-item:hover {
  background: #f8fafc;
  border-color: #e2e8f0;
}

.kb-dialog-item.selected {
  background: #f5f3ff;
  border-color: #c7d2fe;
}

.kb-dialog-item-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.kb-dialog-item-name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13.5px;
  font-weight: 500;
  color: #1f2937;
}

.kb-dialog-item-icon {
  color: #059669;
  font-size: 14px;
}

.kb-dialog-item-desc {
  font-size: 12px;
  color: #6b7280;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kb-dialog-item-meta {
  font-size: 11.5px;
  color: #94a3b8;
}

:deep(.kb-dialog-footer-info) {
  float: left;
  line-height: 32px;
  font-size: 13px;
  color: #64748b;
}
</style>
