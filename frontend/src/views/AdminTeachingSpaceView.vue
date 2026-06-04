<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage } from 'element-plus';
import { Search, Refresh } from '@element-plus/icons-vue';
import { listAllTeachingSpaces, type TeachingSpace } from '../api/teachingSpace';
import { getDepartments } from '../api/organization';
import { useUserStore } from '../stores/user';

const router = useRouter();
const userStore = useUserStore();

const spaces = ref<TeachingSpace[]>([]);
const allColleges = ref<{ id: number; name: string; code: string }[]>([]);
const loading = ref(false);
const searchQuery = ref('');
const activeCollege = ref('all');
const sortBy = ref<'name' | 'members' | 'resources'>('members');

const loadSpaces = async () => {
  loading.value = true;
  try {
    spaces.value = await listAllTeachingSpaces();
  } catch (error: unknown) {
    ElMessage.error(error?.response?.data?.message || '加载教学空间失败');
  } finally {
    loading.value = false;
  }
};

const loadColleges = async () => {
  const schoolId = userStore.user?.school_id;
  if (!schoolId) return;
  try {
    allColleges.value = await getDepartments(schoolId);
  } catch {
    // fallback: do nothing
  }
};

const collegeSpaceCount = computed(() => {
  const map = new Map<number, number>();
  for (const s of spaces.value) {
    if (s.teacher_college_id) {
      map.set(s.teacher_college_id, (map.get(s.teacher_college_id) || 0) + 1);
    }
  }
  return map;
});

const filteredSpaces = computed(() => {
  let list = spaces.value;

  if (activeCollege.value !== 'all') {
    const collegeId = Number(activeCollege.value);
    list = list.filter(s => s.teacher_college_id === collegeId);
  }

  if (searchQuery.value.trim()) {
    const q = searchQuery.value.trim().toLowerCase();
    list = list.filter(s =>
      (s.space_code || '').toLowerCase().includes(q) ||
      s.name.toLowerCase().includes(q) ||
      (s.teacher_name || '').toLowerCase().includes(q)
    );
  }

  list = [...list].sort((a, b) => {
    if (sortBy.value === 'name') return a.name.localeCompare(b.name);
    if (sortBy.value === 'members') return (b.member_count ?? 0) - (a.member_count ?? 0);
    return (b.resource_count ?? 0) - (a.resource_count ?? 0);
  });

  return list;
});

const handleDetail = (space: TeachingSpace) => {
  router.push(`/admin/teaching-space/${space.id}`);
};

onMounted(() => {
  loadSpaces();
  loadColleges();
});
</script>

<template>
  <div class="page-container">
    <div class="content-section">
      <!-- Header -->
      <div class="page-header">
        <div>
          <h2>空间管理</h2>
          <p class="subtitle">共 {{ spaces.length }} 个教学空间，分布在 {{ allColleges.length }} 个学院</p>
        </div>
        <el-button :icon="Refresh" @click="loadSpaces">刷新</el-button>
      </div>

      <!-- Filter Bar -->
      <div class="filter-bar">
        <div class="filter-search">
          <el-icon class="filter-search-icon" :size="15"><Search /></el-icon>
          <input v-model="searchQuery" class="filter-search-input" placeholder="搜索空间名称、编号或教师..." />
        </div>
        <el-select v-model="activeCollege" class="filter-select filter-select-college" size="default" placeholder="筛选学院">
          <el-option label="全部学院" value="all" />
          <el-option
            v-for="col in allColleges"
            :key="col.id"
            :label="`${col.name} (${collegeSpaceCount.get(col.id) || 0})`"
            :value="String(col.id)"
          />
        </el-select>
        <el-select v-model="sortBy" class="filter-select" size="default">
          <el-option label="按学生数排序" value="members" />
          <el-option label="按资源数排序" value="resources" />
          <el-option label="按名称排序" value="name" />
        </el-select>
      </div>

      <!-- Content -->
      <div v-loading="loading" class="space-body">
        <el-empty v-if="!loading && filteredSpaces.length === 0" description="无匹配的教学空间" :image-size="80" />

        <div v-if="filteredSpaces.length > 0" class="space-grid">
          <div
            v-for="space in filteredSpaces"
            :key="space.id"
            class="space-card"
            @click="handleDetail(space)"
          >
            <div class="space-card-top">
              <div class="space-card-title">
                <span class="space-id">{{ space.space_code || '#' + space.id }}</span>
                <span class="space-name">{{ space.name }}</span>
                <el-tag size="small" :type="space.status === 'active' ? 'success' : 'info'" effect="plain">
                  {{ space.status === 'active' ? '启用' : '停用' }}
                </el-tag>
              </div>
              <div class="space-card-teacher">
                <span class="teacher-avatar">{{ (space.teacher_name || '?')[0] }}</span>
                <span class="teacher-name">{{ space.teacher_name || '未知' }}</span>
                <el-tag v-if="space.teacher_college_name" size="small" effect="plain" class="college-tag">{{ space.teacher_college_name }}</el-tag>
              </div>
            </div>
            <div class="space-card-metrics">
              <div class="metric">
                <span class="metric-val">{{ space.major_count ?? 0 }}</span>
                <span class="metric-key">专业</span>
              </div>
              <div class="metric">
                <span class="metric-val">{{ space.member_count ?? 0 }}</span>
                <span class="metric-key">学生</span>
              </div>
              <div class="metric">
                <span class="metric-val">{{ space.resource_count ?? 0 }}</span>
                <span class="metric-key">资源</span>
              </div>
            </div>
            <div class="space-card-foot">
              <span class="detail-hint">查看详情</span>
            </div>
          </div>
        </div>
      </div>
    </div>
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

/* ===== Filter Bar ===== */
.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.filter-search {
  display: flex;
  align-items: center;
  flex: 1;
  min-width: 180px;
  max-width: 360px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 0 12px;
  height: 36px;
  transition: border-color 0.15s;
}

.filter-search:focus-within { border-color: #a5b4fc; }
.filter-search-icon { color: #94a3b8; flex-shrink: 0; }

.filter-search-input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 13px;
  padding: 0 8px;
  color: #1e293b;
  height: 100%;
}

.filter-search-input::placeholder { color: #94a3b8; }
.filter-select { width: 150px; }
.filter-select-college { width: 180px; }
:deep(.filter-select .el-input__wrapper) { height: 36px; border-radius: 8px; font-size: 13px; }

/* ===== Content ===== */
.space-body {
  min-height: 200px;
}

.space-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}

/* ===== Space Card ===== */
.space-card {
  display: flex;
  flex-direction: column;
  padding: 16px;
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

.space-card-top {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 14px;
}

.space-card-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.space-name {
  flex: 1;
  min-width: 0;
  font-size: 14.5px;
  font-weight: 600;
  color: #111827;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.space-card-teacher {
  display: flex;
  align-items: center;
  gap: 8px;
}

.teacher-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #e0e7ff;
  color: #4338ca;
  font-size: 11px;
  font-weight: 700;
  flex-shrink: 0;
}

.teacher-name {
  font-size: 12.5px;
  color: #64748b;
  font-weight: 500;
}

.college-tag {
  font-size: 11px !important;
  border-radius: 4px !important;
}

/* Metrics */
.space-card-metrics {
  display: flex;
  align-items: center;
  gap: 0;
  padding: 10px 0;
  border-top: 1px solid #f1f5f9;
  border-bottom: 1px solid #f1f5f9;
  margin-bottom: 10px;
}

.metric {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.metric + .metric {
  border-left: 1px solid #f1f5f9;
}

.metric-val {
  font-size: 15px;
  font-weight: 700;
  color: #1e293b;
}

.metric-key {
  font-size: 11px;
  color: #94a3b8;
  font-weight: 500;
}

/* Footer */
.space-card-foot {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  margin-top: auto;
}

.space-id {
  font-size: 13px;
  color: #6366f1;
  font-weight: 700;
  background: #eef2ff;
  padding: 2px 8px;
  border-radius: 4px;
  flex-shrink: 0;
}

.detail-hint {
  font-size: 12.5px;
  font-weight: 500;
  color: #818cf8;
  transition: color 0.15s;
}

.space-card:hover .detail-hint { color: #6366f1; }

/* ===== Responsive ===== */
@media (max-width: 1024px) {
  .space-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 768px) {
  .page-header { flex-direction: column; }
  .space-grid { grid-template-columns: 1fr; }
  .filter-bar { flex-direction: column; align-items: stretch; }
  .filter-search { max-width: none; }
}
</style>
