<script setup lang="ts">
import { onMounted, ref, computed, watch } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  ChatDotRound, Delete, Edit, Plus, Tickets, User, Search,
} from "@element-plus/icons-vue";
import { deleteBot, listBots, type BotResponse } from "../api/bot";
import { useUserStore } from "../stores/user";
import { getDepartments, type Organization } from "../api/organization";
import { listTeachingSpaces, getSpaceResources, listAllTeachingSpaces, type TeachingSpace } from "../api/teachingSpace";

const router = useRouter();
const userStore = useUserStore();
const bots = ref<BotResponse[]>([]);
const loading = ref(false);

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

const getVisibilityLabel = (bot: BotResponse) => {
  if (!bot.organization_id) return '私有';
  if (bot.org_name) return bot.org_name;
  const org = userStore.userOrganizations.find(o => o.id === bot.organization_id);
  return org?.name || '组织';
};

const getVisibilityType = (bot: BotResponse): 'success' | 'warning' | 'info' => {
  if (!bot.organization_id) return 'info';
  const org = userStore.userOrganizations.find(o => o.id === bot.organization_id);
  if (org?.type === 'school') return 'success';
  return 'warning';
};

const canManage = (bot: BotResponse) => {
  const role = userStore.user?.role;
  if (role === 'admin') return true;
  return bot.user_id === currentUserId.value;
};

const handleViewDetail = (bot: BotResponse) => {
  router.push({
    name: 'botDetail',
    params: { id: bot.id },
    state: { bot: JSON.parse(JSON.stringify(bot)) },
  });
};

const handleChat = (bot: BotResponse) => {
  router.push({
    path: '/chat',
    query: { bot_id: String(bot.id), model_config_id: bot.model_config_id ? String(bot.model_config_id) : undefined },
  });
};

const loadBots = async () => {
  loading.value = true;
  try {
    bots.value = await listBots();
    await loadTeachingSpaces();
    if (selectedSpaceId.value) await loadSpaceBots();
    await loadCollegeList();
    if (isAdmin.value) await loadAdminSpaces();
  }
  catch (error: any) { ElMessage.error(error?.response?.data?.detail || "数字助理列表加载失败"); }
  finally { loading.value = false; }
};

const handleDelete = async (bot: BotResponse) => {
  try {
    await ElMessageBox.confirm(`确定删除「${bot.name}」吗？`, "删除数字助理", { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" });
    await deleteBot(bot.id);
    ElMessage.success("已删除数字助理");
    await loadBots();
  } catch (error: any) {
    if (error !== "cancel") ElMessage.error(error?.response?.data?.detail || "删除失败");
  }
};

// ===== 筛选 =====
const searchQuery = ref('');
const selectedCreator = ref('');
const sortBy = ref<'updated' | 'created' | 'name'>('updated');

const creatorOptions = computed(() => {
  const names = new Set<string>();
  for (const bot of bots.value) { if (bot.creator_name) names.add(bot.creator_name); }
  return Array.from(names).sort();
});

const filteredBots = computed(() => {
  let list = [...bots.value];
  const keyword = searchQuery.value.trim().toLowerCase();
  if (keyword) {
    list = list.filter(b =>
      (b.name || '').toLowerCase().includes(keyword) ||
      (b.description || '').toLowerCase().includes(keyword) ||
      (b.greeting || '').toLowerCase().includes(keyword)
    );
  }
  if (selectedCreator.value) list = list.filter(b => b.creator_name === selectedCreator.value);
  list.sort((a, b) => {
    if (sortBy.value === 'name') return (a.name || '').localeCompare(b.name || '');
    const field = sortBy.value === 'created' ? 'created_at' : 'updated_at';
    return new Date(b[field] || 0).getTime() - new Date(a[field] || 0).getTime();
  });
  return list;
});

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

const groupedBots = computed(() => {
  const groups: Record<string, BotResponse[]> = { public: [], college: [], allColleges: [], private: [], mine: [] };
  for (const bot of filteredBots.value) {
    if (!bot.organization_id) {
      groups.private.push(bot);
    } else if (bot.organization_id === schoolOrgId.value) {
      groups.public.push(bot);
    } else {
      groups.allColleges.push(bot);
      if (userCollegeId.value && bot.organization_id === userCollegeId.value) {
        groups.college.push(bot);
      }
    }
    if (bot.user_id === currentUserId.value) {
      groups.mine.push(bot);
    }
  }
  return groups;
});

// ===== 教学空间（学生视角）=====
const teachingSpaces = ref<TeachingSpace[]>([]);
const selectedSpaceId = ref<number | undefined>(undefined);
const spaceBots = ref<BotResponse[]>([]);
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

const loadSpaceBots = async () => {
  if (!selectedSpaceId.value) { spaceBots.value = []; return; }
  loadingSpace.value = true;
  try {
    const res = await getSpaceResources(selectedSpaceId.value);
    spaceBots.value = res.bots || [];
  } catch { spaceBots.value = []; }
  finally { loadingSpace.value = false; }
};

watch(selectedSpaceId, () => { loadSpaceBots(); });

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
  if (key === 'space') return spaceBots.value.length;
  if (key === 'allSpaces') return adminSpaces.value.length;
  if (key === 'allColleges') {
    const items = groupedBots.value.allColleges || [];
    if (adminCollegeFilter.value) {
      return items.filter(b => b.organization_id === adminCollegeFilter.value).length;
    }
    return items.length;
  }
  return groupedBots.value[key]?.length || 0;
};

const currentTabItems = computed(() => {
  if (activeTab.value === 'space') return spaceBots.value;
  if (activeTab.value === 'allColleges') {
    const items = groupedBots.value.allColleges || [];
    if (adminCollegeFilter.value) {
      return items.filter(b => b.organization_id === adminCollegeFilter.value);
    }
    return items;
  }
  return groupedBots.value[activeTab.value] || [];
});

const hasOriginalBots = computed(() => bots.value.length > 0);
const isFiltering = computed(() => !!searchQuery.value.trim() || !!selectedCreator.value);

// 分页
const currentPage = ref(1);
const pageSize = 12;
const pagedItems = computed(() => {
  const start = (currentPage.value - 1) * pageSize;
  return currentTabItems.value.slice(start, start + pageSize);
});

watch(activeTab, () => { currentPage.value = 1; adminCollegeFilter.value = ''; });
watch([searchQuery, selectedCreator, sortBy, adminCollegeFilter], () => { currentPage.value = 1; });

onMounted(async () => {
  await loadBots();
});
</script>

<template>
  <div class="page-container">
    <div class="content-section">
      <!-- 标题 -->
      <div class="page-header">
        <div>
          <h2>{{ isStudent ? '数字助理' : '数字助理工厂' }}</h2>
          <p class="subtitle">{{ isStudent ? '选择一个助理开始对话' : '创建可复用的专属问答助理，绑定模型配置、知识库和安全边界' }}</p>
        </div>
        <el-button v-if="!isStudent" type="primary" :icon="Plus" @click="router.push('/bots/create')">创建助理</el-button>
      </div>

      <!-- 筛选栏 -->
      <div class="filter-bar" v-if="!loading">
        <div class="filter-search">
          <el-icon class="filter-search-icon" :size="15"><Search /></el-icon>
          <input v-model="searchQuery" class="filter-search-input" placeholder="搜索助理名称或描述..." />
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

      <!-- 教学空间筛选（学生） -->
      <div v-if="activeTab === 'space' && teachingSpaces.length > 0" class="org-filter-bar">
        <span class="org-filter-label">选择教学空间：</span>
        <el-select v-model="selectedSpaceId" placeholder="选择空间" size="default" class="org-filter-select" style="width: 280px">
          <el-option v-for="sp in teachingSpaces" :key="sp.id" :label="`${sp.name}（${sp.teacher_name}）`" :value="sp.id" />
        </el-select>
      </div>

      <!-- 内容区 -->
      <div v-loading="loading || loadingSpace || loadingAdminSpaces" class="bot-body">
        <el-empty v-if="!loading && !hasOriginalBots && activeTab !== 'allSpaces'" :description="isStudent ? '暂无可用的数字助理' : '暂无数字助理'">
          <el-button v-if="!isStudent" type="primary" :icon="Plus" @click="router.push('/bots/create')">创建第一个助理</el-button>
        </el-empty>

        <!-- 管理员教学空间 tab：显示空间卡片 -->
        <template v-if="activeTab === 'allSpaces'">
          <div v-if="adminSpaces.length > 0" class="bot-grid">
            <div
              v-for="space in adminSpaces"
              :key="space.id"
              class="space-card"
              @click="router.push(isAdmin ? `/admin/teaching-space/${space.id}` : `/teaching-space/${space.id}`)"
            >
              <div class="space-card-header">
                <span class="space-card-name">{{ space.name }}</span>
                <el-tag size="small" type="info" effect="plain">{{ space.space_code || '#' + space.id }}</el-tag>
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

        <!-- 常规助理卡片 -->
        <template v-else-if="hasOriginalBots">
          <el-empty v-if="!loading && pagedItems.length === 0 && isFiltering" description="没有匹配的助理，试试其他关键词" :image-size="80" />
          <el-empty v-else-if="!loading && pagedItems.length === 0 && !isFiltering" description="该分类暂无助理" :image-size="80" />

          <!-- ===== 助理卡片（统一布局） ===== -->
          <div v-if="pagedItems.length > 0" class="bot-grid">
            <div v-for="bot in pagedItems" :key="bot.id" class="bot-card" @click="handleViewDetail(bot)">
              <div class="bot-main">
                <el-avatar :size="38" :src="bot.avatar">{{ bot.name.slice(0, 1) }}</el-avatar>
                <div class="bot-title">
                  <div class="bot-name">{{ bot.name }}</div>
                  <el-tag size="small" :type="getVisibilityType(bot)" effect="plain">{{ getVisibilityLabel(bot) }}</el-tag>
                </div>
              </div>
              <p class="bot-desc">{{ bot.description || (isStudent ? "智能问答助理" : "未填写描述") }}</p>
              <div class="bot-meta">
                <span><el-icon><User /></el-icon>{{ bot.creator_name || (isStudent ? '未知' : `用户 #${bot.user_id}`) }}</span>
                <template v-if="!isStudent">
                  <span><el-icon><Tickets /></el-icon>{{ bot.vector_db_ids.length }} 个知识库</span>
                  <span>{{ bot.model_config_id ? "已绑定模型" : "未绑定模型" }}</span>
                </template>
              </div>
              <div v-if="!isStudent && bot.forbidden_topics.length > 0" class="topic-list">
                <el-tag v-for="topic in bot.forbidden_topics.slice(0, 4)" :key="topic" size="small" type="danger" effect="plain">{{ topic }}</el-tag>
              </div>
              <div class="bot-actions">
                <el-button type="primary" size="small" :icon="ChatDotRound" @click.stop="handleChat(bot)">对话</el-button>
                <el-button v-if="!isStudent && canManage(bot)" size="small" :icon="Edit" @click.stop="router.push(`/bots/${bot.id}/edit`)">编辑</el-button>
                <el-button v-if="!isStudent && canManage(bot)" size="small" type="danger" plain :icon="Delete" @click.stop="handleDelete(bot)">删除</el-button>
              </div>
            </div>
          </div>
        </template>
      </div>

      <!-- 分页 -->
      <div class="bot-pagination" v-if="activeTab !== 'allSpaces' && currentTabItems.length > pageSize">
        <el-pagination v-model:current-page="currentPage" :page-size="pageSize" :total="currentTabItems.length" layout="prev, pager, next" small />
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 20px; }

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

/* ===== 内容区 ===== */
.bot-body { min-height: 200px; }
.bot-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.bot-pagination { display: flex; justify-content: center; margin-top: 16px; }

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

/* ===== 助理卡片 ===== */
.bot-card { display: flex; flex-direction: column; gap: 10px; padding: 14px; border: 1px solid #e6ebf2; border-radius: 8px; background: #fff; box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04); cursor: pointer; transition: all 0.2s ease; }
.bot-card:hover { border-color: #c7d2fe; box-shadow: 0 4px 16px rgba(99, 102, 241, 0.08); transform: translateY(-2px); }
.bot-main { display: flex; align-items: center; gap: 10px; }
.bot-title { min-width: 0; }
.bot-name { margin-bottom: 3px; color: #1f2937; font-size: 14px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bot-desc { margin: 0; color: #4b5563; font-size: 12.5px; line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.bot-meta, .topic-list { display: flex; flex-wrap: wrap; gap: 8px; }
.bot-meta span { display: inline-flex; align-items: center; gap: 4px; color: #6b7280; font-size: 12px; }
.bot-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: auto; }

/* ===== 响应式 ===== */
@media (max-width: 1024px) { .bot-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 640px) {
  .bot-grid { grid-template-columns: 1fr; }
  .filter-bar { flex-direction: column; align-items: stretch; }
  .filter-search { max-width: 100%; }
  .filter-select { width: 100%; }
  .org-filter-bar { flex-direction: column; align-items: stretch; }
  .org-filter-select { width: 100%; }
}
</style>
