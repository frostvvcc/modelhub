<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { Search, Plus, Refresh, QuestionFilled } from '@element-plus/icons-vue';
import { ElMessage } from 'element-plus';
import VectorDbCard from '@/components/VectorDbCard.vue';
import type { VectorDbBase } from '../types/vectorDb';
import { createVectorDb, fetchOwnVectors } from '../api/vectorDb';
import type { ModelInfo } from '../types/model_config';
import { getEmbeddingModelInfos } from '../api/model';
import { useUserStore } from '../stores/user';
import { getUserOrganizations, getDepartments, type Organization } from '../api/organization';
import { listTeachingSpaces, getSpaceResources, listAllTeachingSpaces, type TeachingSpace } from '../api/teachingSpace';

const route = useRoute();
const router = useRouter();
const userStore = useUserStore();

const baseModels = ref<ModelInfo[]>([]);
const allVectorDBs = ref<VectorDbBase[]>([]);
const organizations = ref<Organization[]>([]);

const dialogVisible = ref(false);
const loading = ref(false);
const searchQuery = ref('');

const form = ref({
  id: null,
  name: '',
  describe: '',
  embedding_id: null,
  document_similarity: 0.5,
  organization_id: null as number | null,
});
const formRules = {
  name: [{ required: true, message: '请输入知识库名称', trigger: 'blur' }],
};

// ===== 角色判断 =====
const isStudent = computed(() => userStore.user?.role === 'student');
const isTeacher = computed(() => userStore.user?.role === 'teacher');
const isAdmin = computed(() => userStore.user?.role === 'admin');
const currentUserId = computed(() => Number(userStore.user?.id));

const userCollegeId = computed(() => {
  const orgs = userStore.userOrganizations;
  const college = orgs.find(o => o.type === 'college');
  return college?.id || null;
});

// ===== 筛选 =====
const selectedCreator = ref('');
const sortBy = ref<'updated' | 'created' | 'name'>('updated');

const creatorOptions = computed(() => {
  const names = new Set<string>();
  for (const db of allVectorDBs.value) {
    if ((db as any).creator_name) names.add((db as any).creator_name);
  }
  return Array.from(names).sort();
});

const filteredVectorDBs = computed(() => {
  let list = [...allVectorDBs.value];
  const keyword = searchQuery.value.trim().toLowerCase();
  if (keyword) {
    list = list.filter(db =>
      (db.name || '').toLowerCase().includes(keyword) ||
      (db.describe || '').toLowerCase().includes(keyword)
    );
  }
  if (selectedCreator.value) {
    list = list.filter(db => (db as any).creator_name === selectedCreator.value);
  }
  list.sort((a, b) => {
    if (sortBy.value === 'name') return (a.name || '').localeCompare(b.name || '');
    const fa = sortBy.value === 'created' ? a.created_at : a.updated_at;
    const fb = sortBy.value === 'created' ? b.created_at : b.updated_at;
    return new Date(fb || 0).getTime() - new Date(fa || 0).getTime();
  });
  return list;
});

const hasData = computed(() => allVectorDBs.value.length > 0);
const isFiltering = computed(() => !!searchQuery.value.trim() || !!selectedCreator.value);

// ===== Tab 定义 =====
interface TabDef { key: string; label: string; }

const tabs = computed<TabDef[]>(() => {
  if (isAdmin.value) return [
    { key: 'public', label: '学校公开' },
    { key: 'allColleges', label: '所有学院公开' },
    { key: 'private', label: '所有私有' },
    { key: 'allSpaces', label: '所有教学空间' },
    { key: 'mine', label: '我创建的' },
  ];
  if (isTeacher.value) return [
    { key: 'public', label: '学校公开' },
    { key: 'college', label: '所在学院公开' },
    { key: 'mine', label: '我创建的' },
  ];
  return [
    { key: 'public', label: '学校公开' },
    { key: 'college', label: '所在学院公开' },
    { key: 'space', label: '教学空间' },
  ];
});

const activeTab = ref('public');

// ===== 分组逻辑 =====
const schoolOrgId = computed(() => userStore.currentSchool?.id || userStore.user?.school_id || null);

const isSchoolLevel = (db: VectorDbBase) => {
  if (!db.organization_id) return false;
  return db.organization_id === schoolOrgId.value;
};

const isCollegeLevel = (db: VectorDbBase) => {
  if (!db.organization_id) return false;
  if (db.organization_id === schoolOrgId.value) return false;
  return true;
};

const scopeGrouped = computed(() => {
  const groups: Record<string, VectorDbBase[]> = { public: [], college: [], allColleges: [], private: [], mine: [] };
  for (const db of filteredVectorDBs.value) {
    if (!db.organization_id) {
      groups.private.push(db);
    } else if (isSchoolLevel(db)) {
      groups.public.push(db);
    } else if (isCollegeLevel(db)) {
      groups.allColleges.push(db);
      if (userCollegeId.value && db.organization_id === userCollegeId.value) {
        groups.college.push(db);
      }
    }
    if ((db as any).user_id === currentUserId.value) {
      groups.mine.push(db);
    }
  }
  return groups;
});

// ===== 教学空间（学生视角）=====
const teachingSpaces = ref<TeachingSpace[]>([]);
const selectedSpaceId = ref<number | undefined>(undefined);
const spaceVectorDbs = ref<VectorDbBase[]>([]);
const loadingSpace = ref(false);

const loadTeachingSpaces = async () => {
  if (!isStudent.value) return;
  try {
    teachingSpaces.value = await listTeachingSpaces();
    if (teachingSpaces.value.length > 0 && !selectedSpaceId.value) {
      selectedSpaceId.value = teachingSpaces.value[0].id;
    }
  } catch {}
};

const loadSpaceResources = async () => {
  if (!selectedSpaceId.value) { spaceVectorDbs.value = []; return; }
  loadingSpace.value = true;
  try {
    const res = await getSpaceResources(selectedSpaceId.value);
    spaceVectorDbs.value = res.vector_dbs || [];
  } catch { spaceVectorDbs.value = []; }
  finally { loadingSpace.value = false; }
};

watch(selectedSpaceId, () => { loadSpaceResources(); });

// ===== 管理员学院筛选 =====
const collegeList = ref<Organization[]>([]);
const adminCollegeFilter = ref<number | ''>('');

const loadCollegeList = async () => {
  if (!isAdmin.value) return;
  const schoolId = userStore.currentSchool?.id;
  if (!schoolId) return;
  try {
    collegeList.value = await getDepartments(schoolId);
  } catch {}
};

// ===== 管理员教学空间 tab =====
const adminSpaces = ref<TeachingSpace[]>([]);
const adminSpaceCollegeFilter = ref<number | ''>('');
const loadingAdminSpaces = ref(false);

const loadAdminSpaces = async () => {
  if (!isAdmin.value) return;
  loadingAdminSpaces.value = true;
  try {
    const orgId = adminSpaceCollegeFilter.value || undefined;
    adminSpaces.value = await listAllTeachingSpaces(orgId);
  } catch { adminSpaces.value = []; }
  finally { loadingAdminSpaces.value = false; }
};

watch(adminSpaceCollegeFilter, () => { loadAdminSpaces(); });

// ===== Tab 内容 =====
const countByTab = (key: string) => {
  if (key === 'space') return spaceVectorDbs.value.length;
  if (key === 'allSpaces') return adminSpaces.value.length;
  if (key === 'allColleges') {
    const items = scopeGrouped.value.allColleges || [];
    if (adminCollegeFilter.value) {
      return items.filter(db => (db as any).organization_id === adminCollegeFilter.value).length;
    }
    return items.length;
  }
  return scopeGrouped.value[key]?.length || 0;
};

const currentTabItems = computed(() => {
  if (activeTab.value === 'space') return spaceVectorDbs.value;
  if (activeTab.value === 'allColleges') {
    const items = scopeGrouped.value.allColleges || [];
    if (adminCollegeFilter.value) {
      return items.filter(db => (db as any).organization_id === adminCollegeFilter.value);
    }
    return items;
  }
  return scopeGrouped.value[activeTab.value] || [];
});

// 分页
const currentPage = ref(1);
const pageSize = 12;
const pagedItems = computed(() => {
  const start = (currentPage.value - 1) * pageSize;
  return currentTabItems.value.slice(start, start + pageSize);
});

watch(activeTab, () => { currentPage.value = 1; adminCollegeFilter.value = ''; });
watch([searchQuery, selectedCreator, sortBy, adminCollegeFilter], () => { currentPage.value = 1; });

// ===== 数据加载 =====
const loadData = async () => {
  loading.value = true;
  try {
    let orgId = userStore.currentOrganization?.id || undefined;
    if (orgId && userStore.isVirtualOrganization(userStore.currentOrganization)) orgId = undefined;
    allVectorDBs.value = await fetchOwnVectors(orgId);
    await loadTeachingSpaces();
    if (selectedSpaceId.value) await loadSpaceResources();
    await loadCollegeList();
    if (isAdmin.value) await loadAdminSpaces();
  } catch {
    ElMessage.error('加载知识库失败');
  } finally {
    loading.value = false;
  }
};

watch(() => userStore.currentOrganization?.id, () => { loadData(); });

// ===== 表单相关 =====
const initForm = () => {
  form.value = { id: null, name: '', describe: '', embedding_id: null, document_similarity: 0.5, organization_id: null };
};

const loadOrganizations = async () => {
  if (userStore.userOrganizations.length > 0) {
    organizations.value = userStore.userOrganizations;
  } else {
    try { organizations.value = await getUserOrganizations(Number(userStore.user?.id)); } catch {}
  }
};

const availableOrganizations = computed(() => {
  const userRole = userStore.user?.role || 'student';
  if (userRole === 'student') return [];
  return userStore.userOrganizations.filter(o => !userStore.isVirtualOrganization(o));
});

const submitForm = async () => {
  loading.value = true;
  try {
    await createVectorDb(form.value);
    ElMessage.success('创建成功');
    dialogVisible.value = false;
    loadData();
  } catch (error: any) {
    ElMessage.error(error.response?.data?.message || '创建失败');
  } finally {
    loading.value = false;
  }
};

const handleCreate = () => { initForm(); dialogVisible.value = true; };

onMounted(async () => {
  baseModels.value = await getEmbeddingModelInfos();
  await loadOrganizations();
  loadData();
  if (route.query.action === 'create') {
    handleCreate();
  }
});
</script>

<template>
  <div class="page-container">
    <div class="content-section">
      <!-- 标题 + 操作 -->
      <div class="page-header">
        <div>
          <h2>知识库</h2>
          <p class="subtitle">管理知识库、文档和检索资料</p>
        </div>
        <div class="header-actions">
          <el-button type="primary" :icon="Plus" @click="handleCreate">新建知识库</el-button>
          <el-button :icon="Refresh" @click="loadData">刷新</el-button>
        </div>
      </div>

      <!-- 筛选栏 -->
      <div class="filter-bar" v-if="!loading">
        <div class="filter-search">
          <el-icon class="filter-search-icon" :size="15"><Search /></el-icon>
          <input v-model="searchQuery" class="filter-search-input" placeholder="搜索知识库名称或描述..." />
        </div>
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
      <div class="tab-row">
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

      <!-- 管理员学院筛选（所有学院公开 tab） -->
      <div v-if="activeTab === 'allColleges' && collegeList.length > 0" class="org-filter-bar">
        <span class="org-filter-label">筛选学院：</span>
        <el-select v-model="adminCollegeFilter" placeholder="全部学院" clearable size="default" class="org-filter-select">
          <el-option v-for="col in collegeList" :key="col.id" :label="col.name" :value="col.id" />
        </el-select>
      </div>

      <!-- 管理员教学空间学院筛选 -->
      <div v-if="activeTab === 'allSpaces'" class="org-filter-bar">
        <span class="org-filter-label">筛选学院：</span>
        <el-select v-model="adminSpaceCollegeFilter" placeholder="全部学院" clearable size="default" class="org-filter-select">
          <el-option v-for="col in collegeList" :key="col.id" :label="col.name" :value="col.id" />
        </el-select>
      </div>

      <!-- 教���空间筛选（学生） -->
      <div v-if="activeTab === 'space' && teachingSpaces.length > 0" class="org-filter-bar">
        <span class="org-filter-label">选择教学空间：</span>
        <el-select v-model="selectedSpaceId" placeholder="选择空间" size="default" class="org-filter-select" style="width: 280px">
          <el-option v-for="sp in teachingSpaces" :key="sp.id" :label="`${sp.name}（${sp.teacher_name}）`" :value="sp.id" />
        </el-select>
      </div>

      <!-- 内容区 -->
      <div v-loading="loading || loadingSpace || loadingAdminSpaces" class="kb-body">
        <!-- 管理员教学空间 tab：显示空间卡片 -->
        <template v-if="activeTab === 'allSpaces'">
          <div v-if="adminSpaces.length > 0" class="kb-grid">
            <div
              v-for="space in adminSpaces"
              :key="space.id"
              class="space-card"
              @click="router.push(isAdmin ? `/admin/teaching-space/${space.id}` : `/teaching-space/${space.id}`)"
            >
              <div class="space-card-header">
                <span class="space-card-name">{{ space.name }}</span>
                <el-tag size="small" type="info" effect="plain">#{{ space.id }}</el-tag>
              </div>
              <div class="space-card-meta">
                <span>教师：{{ space.teacher_name || '未知' }}</span>
                <span v-if="space.teacher_college_name">学院：{{ space.teacher_college_name }}</span>
              </div>
              <div class="space-card-stats">
                <el-tag size="small" effect="plain">{{ space.major_count || 0 }} 个专业</el-tag>
                <el-tag size="small" effect="plain">{{ space.resource_count || 0 }} 个资源</el-tag>
              </div>
            </div>
          </div>
          <el-empty v-else description="暂无教学空间" :image-size="80" />
        </template>

        <!-- 常规知识库卡片 -->
        <template v-else>
          <div v-if="pagedItems.length > 0" class="kb-grid">
            <VectorDbCard v-for="db in pagedItems" :key="db.id" v-bind="db" />
          </div>
          <el-empty v-if="!loading && hasData && pagedItems.length === 0 && isFiltering" description="没有匹配的知识库，试试其他关键词" :image-size="80" />
          <el-empty v-else-if="!loading && pagedItems.length === 0 && !isFiltering" description="该分类暂无知识库" :image-size="80" />
        </template>
      </div>

      <!-- 分页（非教���空间 tab） -->
      <div class="kb-pagination" v-if="activeTab !== 'allSpaces' && currentTabItems.length > pageSize">
        <el-pagination
          v-model:current-page="currentPage"
          :page-size="pageSize"
          :total="currentTabItems.length"
          layout="prev, pager, next"
          small
        />
      </div>
    </div>

    <!-- 新建对话框 -->
    <ElDialog v-model="dialogVisible" title="新建知识库" width="50%" style="font-size: larger;">
      <ElForm :model="form" :rules="formRules" label-width="120px" ref="formRef" class="dialog-form">
        <ElFormItem label="知识库名称" prop="name">
          <ElInput v-model="form.name" placeholder="请输入知识库名称" />
        </ElFormItem>
        <ElFormItem label="描述" prop="describe">
          <ElInput v-model="form.describe" placeholder="请输入描述" />
        </ElFormItem>
        <ElFormItem prop="embedding_id">
          <template #label>
            <span>嵌入模型</span>
            <el-tooltip content="嵌入模型决定了文本如何被转换为向量进行语义检索。不同模型支持不同语言和理解能力，推荐使用默认模型。" placement="top">
              <el-icon class="help-icon"><QuestionFilled /></el-icon>
            </el-tooltip>
          </template>
          <ElSelect v-model="form.embedding_id" placeholder="请选择嵌入模型" style="width: 100%">
            <ElOption v-for="model in baseModels" :key="model.id" :label="model.model_name" :value="model.id" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem>
          <template #label>
            <span>相似度</span>
            <el-tooltip content="检索时只返回相似度高于此阈值的结果。值越高结果越精确但可能遗漏，值越低结果越多但可能不相关。建议 0.5~0.7。" placement="top">
              <el-icon class="help-icon"><QuestionFilled /></el-icon>
            </el-tooltip>
          </template>
          <ElSlider v-model="form.document_similarity" :min="0" :max="1" :step="0.1" show-input />
        </ElFormItem>
        <ElFormItem>
          <template #label>
            <span>可见范围</span>
            <el-tooltip placement="top">
              <template #content>
                <div style="max-width:260px">
                  <b>私有</b>：仅自己可见和使用<br/>
                  <b>选择组织</b>：该组织成员可见
                </div>
              </template>
              <el-icon class="help-icon"><QuestionFilled /></el-icon>
            </el-tooltip>
          </template>
          <ElSelect v-model="form.organization_id" placeholder="私有（仅自己可见）" clearable style="width: 100%">
            <ElOption :value="null" label="私有（仅自己可见）" />
            <ElOption v-for="org in availableOrganizations" :key="org.id" :label="org.name" :value="org.id" />
          </ElSelect>
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
.tab-row {
  display: flex;
  align-items: center;
  margin-bottom: 16px;
  border-bottom: 1px solid #e6ebf2;
}

.tab-list {
  display: flex;
  gap: 4px;
}

.tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border: none;
  background: transparent;
  color: #64748b;
  font-size: 13.5px;
  font-weight: 500;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  transition: all 0.15s;
}

.tab-btn:hover {
  color: #4f46e5;
  background: #f8f7ff;
}

.tab-btn.active {
  color: #4f46e5;
  border-bottom-color: #4f46e5;
  font-weight: 600;
}

.tab-badge {
  padding: 1px 7px;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 600;
  background: #f1f5f9;
  color: #64748b;
}

.tab-btn.active .tab-badge {
  background: #e0e7ff;
  color: #4338ca;
}

/* ===== 卡片区 ===== */
.kb-body { min-height: 200px; }

.kb-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}

.kb-pagination {
  display: flex;
  justify-content: center;
  margin-top: 16px;
}

/* ===== 组织筛选栏 ===== */
.org-filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
}
.org-filter-label {
  font-size: 13px;
  color: #64748b;
  white-space: nowrap;
}
.org-filter-select { width: 200px; }

/* ===== 教学空间卡片 ===== */
.space-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px;
  border: 1.5px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
  transition: all 0.2s ease;
}
.space-card:hover {
  border-color: #c7d2fe;
  background: #faf8ff;
  box-shadow: 0 4px 16px rgba(99, 102, 241, 0.08);
  transform: translateY(-2px);
}
.space-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.space-card-name {
  font-size: 14px;
  font-weight: 600;
  color: #111827;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.space-card-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12.5px;
  color: #6b7280;
}
.space-card-stats {
  display: flex;
  gap: 6px;
  margin-top: 4px;
}

/* ===== 帮助图标 ===== */
.help-icon {
  margin-left: 4px;
  font-size: 14px;
  color: #a0aec0;
  cursor: help;
  vertical-align: middle;
}
.help-icon:hover { color: #6366f1; }

/* ===== 响应式 ===== */
@media (max-width: 768px) {
  .page-header { flex-direction: column; }
}

@media (max-width: 640px) {
  .filter-bar { flex-direction: column; align-items: stretch; }
  .filter-search { max-width: 100%; }
  .filter-select { width: 100%; }
  .org-filter-bar { flex-direction: column; align-items: stretch; }
  .org-filter-select { width: 100%; }
}
</style>
