<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import { useRouter } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import { Plus, Refresh, Search } from '@element-plus/icons-vue';
import { listTeachingSpaces, createTeachingSpace, deleteTeachingSpace, type TeachingSpace } from '../api/teachingSpace';
import { useUserStore } from '../stores/user';

const router = useRouter();
const userStore = useUserStore();

const spaces = ref<TeachingSpace[]>([]);
const loading = ref(false);
const dialogVisible = ref(false);
const searchQuery = ref('');

const form = ref({
  name: '',
  description: '',
});

const isTeacher = computed(() => {
  const role = userStore.user?.role;
  return role === 'teacher' || role === 'admin';
});

const filteredSpaces = computed(() => {
  if (!searchQuery.value.trim()) return spaces.value;
  const q = searchQuery.value.trim().toLowerCase();
  return spaces.value.filter(s =>
    s.name.toLowerCase().includes(q) ||
    (s.space_code || '').toLowerCase().includes(q) ||
    (s.description || '').toLowerCase().includes(q) ||
    (s.teacher_name || '').toLowerCase().includes(q)
  );
});

const loadSpaces = async () => {
  loading.value = true;
  try {
    spaces.value = await listTeachingSpaces();
  } catch (error: unknown) {
    ElMessage.error(error?.response?.data?.message || '加载教学空间失败');
  } finally {
    loading.value = false;
  }
};

const handleCreate = () => {
  form.value = { name: '', description: '' };
  dialogVisible.value = true;
};

const submitForm = async () => {
  if (!form.value.name.trim()) {
    ElMessage.warning('请输入空间名称');
    return;
  }
  loading.value = true;
  try {
    await createTeachingSpace(form.value.name, form.value.description || undefined);
    ElMessage.success('创建成功');
    dialogVisible.value = false;
    await loadSpaces();
  } catch (error: unknown) {
    ElMessage.error(error?.response?.data?.message || '创建失败');
  } finally {
    loading.value = false;
  }
};

const handleEnter = (space: TeachingSpace) => {
  router.push(`/teaching-space/${space.id}`);
};

const handleDelete = async (space: TeachingSpace) => {
  try {
    await ElMessageBox.confirm(
      `确定删除教学空间「${space.name}」吗？删除后不可恢复。`,
      '删除教学空间',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    );
    await deleteTeachingSpace(space.id);
    ElMessage.success('已删除');
    await loadSpaces();
  } catch (error: unknown) {
    if (error !== 'cancel') {
      ElMessage.error(error?.response?.data?.message || '删除失败');
    }
  }
};

const spaceColors = ['#6366f1', '#8b5cf6', '#06b6d4', '#10b981', '#f59e0b', '#ec4899'];
const getSpaceColor = (index: number) => spaceColors[index % spaceColors.length];

onMounted(() => {
  loadSpaces();
});
</script>

<template>
  <div class="page-container">
    <div class="content-section">
      <!-- Header -->
      <div class="page-header">
        <div>
          <div class="title-row">
            <h2>教学空间</h2>
            <span v-if="isTeacher && spaces.length > 0" class="space-count">{{ spaces.length }} 个空间</span>
          </div>
          <p class="subtitle">{{ isTeacher ? '管理您的教学空间，发布知识库与助理给学生' : '查看您所在专业的教学空间资源' }}</p>
        </div>
        <div class="header-actions">
          <el-button v-if="isTeacher" type="primary" :icon="Plus" @click="handleCreate">创建空间</el-button>
          <el-button :icon="Refresh" @click="loadSpaces">刷新</el-button>
        </div>
      </div>

      <!-- Search (when there are spaces) -->
      <div v-if="spaces.length > 0" class="filter-bar">
        <div class="filter-search">
          <el-icon class="filter-search-icon" :size="15"><Search /></el-icon>
          <input v-model="searchQuery" class="filter-search-input" :placeholder="isTeacher ? '搜索空间编号、名称或描述...' : '搜索空间编号、名称或教师...'" />
        </div>
      </div>

      <!-- Content -->
      <div v-loading="loading" class="space-body">
        <el-empty v-if="!loading && spaces.length === 0" :description="isTeacher ? '暂无教学空间，点击上方按钮创建' : '暂无可访问的教学空间'">
          <el-button v-if="isTeacher" type="primary" :icon="Plus" @click="handleCreate">创建第一个空间</el-button>
        </el-empty>

        <el-empty v-if="!loading && spaces.length > 0 && filteredSpaces.length === 0" description="没有匹配的空间" :image-size="60" />

        <!-- Teacher Cards -->
        <div v-if="isTeacher && filteredSpaces.length > 0" class="space-grid">
          <div v-for="(space, idx) in filteredSpaces" :key="space.id" class="space-card" @click="handleEnter(space)">
            <div class="space-card-accent" :style="{ background: getSpaceColor(idx) }"></div>
            <div class="space-card-content">
              <div class="space-card-head">
                <div class="space-icon" :style="{ background: getSpaceColor(idx) + '18', color: getSpaceColor(idx) }">
                  {{ space.name[0] }}
                </div>
                <div class="space-head-info">
                  <span v-if="space.space_code" class="space-code">{{ space.space_code }}</span>
                  <div class="space-name">{{ space.name }}</div>
                  <el-tag size="small" :type="space.status === 'active' ? 'success' : 'info'" effect="plain">
                    {{ space.status === 'active' ? '启用' : '停用' }}
                  </el-tag>
                </div>
              </div>
              <p class="space-desc">{{ space.description || '暂无描述' }}</p>
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
                <span class="enter-hint">进入空间</span>
                <el-button type="danger" size="small" plain @click.stop="handleDelete(space)">删除</el-button>
              </div>
            </div>
          </div>
        </div>

        <!-- Student Cards -->
        <div v-if="!isTeacher && filteredSpaces.length > 0" class="space-grid">
          <div v-for="(space, idx) in filteredSpaces" :key="space.id" class="space-card space-card--student" @click="handleEnter(space)">
            <div class="space-card-accent" :style="{ background: getSpaceColor(idx) }"></div>
            <div class="space-card-content">
              <div class="space-card-head">
                <div class="space-icon" :style="{ background: getSpaceColor(idx) + '18', color: getSpaceColor(idx) }">
                  {{ space.name[0] }}
                </div>
                <div class="space-head-info">
                  <span v-if="space.space_code" class="space-code">{{ space.space_code }}</span>
                  <div class="space-name">{{ space.name }}</div>
                </div>
              </div>
              <p class="space-desc">{{ space.description || '暂无描述' }}</p>
              <div class="space-card-foot">
                <div class="teacher-info">
                  <span class="teacher-avatar" :style="{ background: getSpaceColor(idx) + '20', color: getSpaceColor(idx) }">{{ (space.teacher_name || '?')[0] }}</span>
                  <span class="teacher-name">{{ space.teacher_name || '未知教师' }}</span>
                </div>
                <span class="enter-hint">查看资源</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Create Dialog -->
    <el-dialog v-model="dialogVisible" title="创建教学空间" width="480px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="空间名称" required>
          <el-input v-model="form.name" placeholder="请输入教学空间名称" maxlength="50" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="请输入描述（可选）" maxlength="200" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitForm" :loading="loading">创建</el-button>
      </template>
    </el-dialog>
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

/* ===== Title row ===== */
.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.space-count {
  font-size: 12px;
  font-weight: 600;
  color: #6366f1;
  background: #eef2ff;
  padding: 2px 10px;
  border-radius: 10px;
  line-height: 1.5;
  white-space: nowrap;
}

/* ===== Filter ===== */
.filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}

.filter-search {
  display: flex;
  align-items: center;
  flex: 1;
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

/* ===== Content ===== */
.space-body {
  min-height: 200px;
}

.space-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 14px;
}

/* ===== Card ===== */
.space-card {
  display: flex;
  border: 1.5px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;
  overflow: hidden;
  cursor: pointer;
  transition: all 0.2s ease;
}

.space-card:hover {
  border-color: #c7d2fe;
  background: #faf8ff;
  box-shadow: 0 4px 16px rgba(99, 102, 241, 0.08);
  transform: translateY(-2px);
}

.space-card-accent {
  width: 4px;
  flex-shrink: 0;
}

.space-card-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 16px;
  min-width: 0;
}

.space-card-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.space-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 700;
  flex-shrink: 0;
}

.space-head-info {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
}

.space-code {
  font-size: 11.5px;
  font-weight: 700;
  color: #6366f1;
  background: #eef2ff;
  padding: 1px 6px;
  border-radius: 3px;
  flex-shrink: 0;
}

.space-name {
  font-size: 14.5px;
  font-weight: 600;
  color: #111827;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.space-desc {
  margin: 0;
  font-size: 12.5px;
  color: #6b7280;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* Metrics */
.space-card-metrics {
  display: flex;
  align-items: center;
  padding: 8px 0;
  border-top: 1px solid #f1f5f9;
  border-bottom: 1px solid #f1f5f9;
}

.metric {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
}

.metric + .metric {
  border-left: 1px solid #f1f5f9;
}

.metric-val {
  font-size: 14px;
  font-weight: 700;
  color: #1e293b;
}

.metric-key {
  font-size: 11px;
  color: #94a3b8;
}

/* Footer */
.space-card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: auto;
}

.teacher-info {
  display: flex;
  align-items: center;
  gap: 6px;
}

.teacher-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  font-size: 11px;
  font-weight: 700;
  flex-shrink: 0;
}

.teacher-name {
  font-size: 12.5px;
  color: #64748b;
}

.enter-hint {
  font-size: 13px;
  font-weight: 500;
  color: #818cf8;
  transition: color 0.15s;
}

.space-card:hover .enter-hint { color: #6366f1; }

/* ===== Responsive ===== */
@media (max-width: 768px) {
  .page-header { flex-direction: column; }
  .header-actions { width: 100%; }
  .filter-search { max-width: none; }
}

@media (max-width: 640px) {
  .space-grid { grid-template-columns: 1fr; }
}
</style>
