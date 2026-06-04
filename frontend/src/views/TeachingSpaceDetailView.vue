<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ElMessage, ElMessageBox } from 'element-plus';
import { Back, Edit, Plus, Search, Delete } from '@element-plus/icons-vue';
import {
  getTeachingSpace,
  updateTeachingSpace,
  getSpaceMajors,
  bindMajor,
  unbindMajor,
  getSpaceResources,
  publishResource,
  unpublishResource,
  getSpaceStudents,
  addSpaceStudent,
  removeSpaceStudent,
  type TeachingSpace,
  type SpaceMajor,
  type SpaceResources,
} from '../api/teachingSpace';
import { getMajors, getGradeDistribution, type Organization, type GradeDistribution } from '../api/organization';
import { fetchMyCreatedVectors } from '../api/vectorDb';
import { listOwnBots, type BotResponse } from '../api/bot';
import { useUserStore } from '../stores/user';

const route = useRoute();
const router = useRouter();
const userStore = useUserStore();

const spaceId = ref(Number(route.params.id));
const space = ref<TeachingSpace | null>(null);
const majors = ref<SpaceMajor[]>([]);
const resources = ref<SpaceResources>({ vector_dbs: [], bots: [] });
const students = ref<Record<string, unknown>[]>([]);
const loading = ref(false);
const studentSearch = ref('');

// Edit space
const editDialogVisible = ref(false);
const editForm = ref({ name: '', description: '' });

// Bind major
const bindMajorDialogVisible = ref(false);
const collegeMajors = ref<Organization[]>([]);
const selectedMajor = ref<number | null>(null);
const selectedEnrollmentYear = ref<number | null>(null);
const majorGrades = ref<GradeDistribution[]>([]);
const loadingGrades = ref(false);
const bindLoading = ref(false);

// Student year filter
const studentYearFilter = ref<number | ''>('');

// Publish resource
const publishDialogVisible = ref(false);
const ownVectors = ref<Record<string, unknown>[]>([]);
const ownBots = ref<BotResponse[]>([]);
const selectedVectorDbs = ref<number[]>([]);
const selectedBots = ref<number[]>([]);
const publishLoading = ref(false);

// Add student
const addStudentDialogVisible = ref(false);
const addStudentId = ref('');
const addStudentLoading = ref(false);

// Resource display tab
const displayResourceTab = ref<'vector_db' | 'bot'>('vector_db');

const isTeacher = computed(() => {
  const role = userStore.user?.role;
  return role === 'teacher' || role === 'admin';
});

const isAdminRoute = computed(() => route.path.startsWith('/admin/'));
const backPath = computed(() => isAdminRoute.value ? '/admin/teaching-space' : '/teaching-space');

const goBack = () => router.push(backPath.value);

const studentYears = computed(() => {
  const years = new Set<number>();
  students.value.forEach(s => { if (s.enrollment_year) years.add(s.enrollment_year); });
  return Array.from(years).sort((a, b) => b - a);
});

const filteredStudents = computed(() => {
  let list = students.value;
  if (studentYearFilter.value !== '') {
    list = list.filter(s => s.enrollment_year === studentYearFilter.value);
  }
  if (studentSearch.value.trim()) {
    const q = studentSearch.value.trim().toLowerCase();
    list = list.filter(s =>
      (s.name || '').toLowerCase().includes(q) ||
      (s.user_name || '').toLowerCase().includes(q) ||
      (s.student_id || '').toLowerCase().includes(q) ||
      (s.major_name || '').toLowerCase().includes(q)
    );
  }
  return list;
});

// ===== Load data =====
const loadSpace = async () => {
  try {
    space.value = await getTeachingSpace(spaceId.value);
  } catch (error: unknown) {
    ElMessage.error('加载空间信息失败');
    router.push(backPath.value);
  }
};

const loadMajors = async () => {
  try {
    majors.value = await getSpaceMajors(spaceId.value);
  } catch {
    majors.value = [];
  }
};

const loadResources = async () => {
  try {
    resources.value = await getSpaceResources(spaceId.value);
  } catch {
    resources.value = { vector_dbs: [], bots: [] };
  }
};

const loadStudents = async () => {
  try {
    students.value = await getSpaceStudents(spaceId.value);
  } catch (error: unknown) {
    console.error('加载学生列表失败:', error);
    students.value = [];
  }
};

const loadAll = async () => {
  loading.value = true;
  await Promise.all([loadSpace(), loadMajors(), loadResources(), loadStudents()]);
  loading.value = false;
};

// ===== Edit space =====
const openEditDialog = () => {
  if (!space.value) return;
  editForm.value = {
    name: space.value.name,
    description: space.value.description || '',
  };
  editDialogVisible.value = true;
};

const submitEdit = async () => {
  if (!editForm.value.name.trim()) {
    ElMessage.warning('名称不能为空');
    return;
  }
  try {
    await updateTeachingSpace(spaceId.value, {
      name: editForm.value.name,
      description: editForm.value.description,
    });
    ElMessage.success('更新成功');
    editDialogVisible.value = false;
    await loadSpace();
  } catch (error: unknown) {
    ElMessage.error(error?.response?.data?.message || '更新失败');
  }
};

// ===== Bind major =====
const openBindMajorDialog = async () => {
  selectedMajor.value = null;
  selectedEnrollmentYear.value = null;
  majorGrades.value = [];
  collegeMajors.value = [];
  bindMajorDialogVisible.value = true;

  try {
    const collegeId = space.value?.teacher_college_id;
    if (collegeId) {
      collegeMajors.value = await getMajors(collegeId);
    }
  } catch {
    collegeMajors.value = [];
    ElMessage.error('加载专业列表失败');
  }
};

const onMajorChange = async (majorId: number | null) => {
  selectedEnrollmentYear.value = null;
  majorGrades.value = [];
  if (!majorId) return;
  loadingGrades.value = true;
  try {
    majorGrades.value = await getGradeDistribution(majorId);
  } catch {
    majorGrades.value = [];
  } finally {
    loadingGrades.value = false;
  }
};

watch(selectedMajor, (val) => onMajorChange(val));

const submitBindMajor = async () => {
  if (!selectedMajor.value) {
    ElMessage.warning('请选择专业');
    return;
  }
  bindLoading.value = true;
  try {
    await bindMajor(spaceId.value, selectedMajor.value, selectedEnrollmentYear.value);
    ElMessage.success('绑定成功');
    bindMajorDialogVisible.value = false;
    await Promise.all([loadMajors(), loadStudents()]);
  } catch (error: unknown) {
    ElMessage.error(error?.response?.data?.message || '绑定失败');
  } finally {
    bindLoading.value = false;
  }
};

const handleUnbindMajor = async (major: SpaceMajor) => {
  const yearLabel = major.enrollment_year ? `${major.enrollment_year}级` : '全部年级';
  const displayName = `${major.major_name || `专业 #${major.major_id}`}（${yearLabel}）`;
  try {
    await ElMessageBox.confirm(
      `确定解绑「${displayName}」吗？`,
      '解绑专业',
      { type: 'warning', confirmButtonText: '解绑', cancelButtonText: '取消' }
    );
    await unbindMajor(spaceId.value, major.major_id, major.enrollment_year);
    ElMessage.success('已解绑');
    await Promise.all([loadMajors(), loadStudents()]);
  } catch (error: unknown) {
    if (error !== 'cancel') {
      ElMessage.error(error?.response?.data?.message || '解绑失败');
    }
  }
};

// ===== Publish resource =====
const openPublishDialog = async () => {
  selectedVectorDbs.value = [];
  selectedBots.value = [];
  publishDialogVisible.value = true;
  publishLoading.value = true;
  try {
    const [vectors, bots] = await Promise.all([
      fetchMyCreatedVectors(),
      listOwnBots(),
    ]);
    ownVectors.value = vectors || [];
    ownBots.value = bots || [];
  } catch {
    ElMessage.error('加载资源列表失败');
  } finally {
    publishLoading.value = false;
  }
};

const isVdbPublished = (id: number) => resources.value.vector_dbs.some((r: Record<string, unknown>) => r.id === id);
const isBotPublished = (id: number) => resources.value.bots.some((r: Record<string, unknown>) => r.id === id);

const totalSelected = computed(() => selectedVectorDbs.value.length + selectedBots.value.length);

const submitPublish = async () => {
  if (totalSelected.value === 0) {
    ElMessage.warning('请选择要发布的资源');
    return;
  }
  publishLoading.value = true;
  try {
    for (const resId of selectedVectorDbs.value) {
      await publishResource(spaceId.value, 'vector_db', resId);
    }
    for (const resId of selectedBots.value) {
      await publishResource(spaceId.value, 'bot', resId);
    }
    ElMessage.success('发布成功');
    publishDialogVisible.value = false;
    await loadResources();
  } catch (error: unknown) {
    ElMessage.error(error?.response?.data?.message || '发布失败');
  } finally {
    publishLoading.value = false;
  }
};

const handleUnpublish = async (type: 'vector_db' | 'bot', resource: Record<string, unknown>) => {
  try {
    await ElMessageBox.confirm(
      `确定取消发布「${resource.name}」吗？`,
      '取消发布',
      { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' }
    );
    await unpublishResource(spaceId.value, type, resource.id);
    ElMessage.success('已取消发布');
    await loadResources();
  } catch (error: unknown) {
    if (error !== 'cancel') {
      ElMessage.error(error?.response?.data?.message || '操作失败');
    }
  }
};

// ===== Add/Remove student =====
const openAddStudentDialog = () => {
  addStudentId.value = '';
  addStudentDialogVisible.value = true;
};

const submitAddStudent = async () => {
  const sid = parseInt(addStudentId.value);
  if (!sid || isNaN(sid)) {
    ElMessage.warning('请输入有效的学生用户ID');
    return;
  }
  addStudentLoading.value = true;
  try {
    await addSpaceStudent(spaceId.value, sid);
    ElMessage.success('添加成功');
    addStudentDialogVisible.value = false;
    await loadStudents();
  } catch (error: unknown) {
    ElMessage.error(error?.response?.data?.message || '添加失败');
  } finally {
    addStudentLoading.value = false;
  }
};

const handleRemoveStudent = async (stu: Record<string, unknown>) => {
  try {
    await ElMessageBox.confirm(
      `确定将学生「${stu.name || stu.student_id}」从空间中移除吗？`,
      '移除学生',
      { type: 'warning', confirmButtonText: '移除', cancelButtonText: '取消' }
    );
    await removeSpaceStudent(spaceId.value, stu.id);
    ElMessage.success('已移除');
    await loadStudents();
  } catch (error: unknown) {
    if (error !== 'cancel') {
      ElMessage.error(error?.response?.data?.message || '移除失败');
    }
  }
};

onMounted(() => {
  loadAll();
});
</script>

<template>
  <div class="page-container">
    <div class="content-section">
      <div v-loading="loading">
        <div v-if="space" class="detail-page">

          <!-- ===== Header ===== -->
          <div class="detail-top">
            <div class="detail-top-left">
              <button class="back-btn" @click="goBack">
                <el-icon :size="16"><Back /></el-icon>
              </button>
              <div class="detail-info">
                <div class="detail-title-row">
                  <span v-if="space.space_code" class="detail-code">{{ space.space_code }}</span>
                  <h2 class="detail-title">{{ space.name }}</h2>
                  <el-tag size="small" :type="space.status === 'active' ? 'success' : 'info'" effect="plain">
                    {{ space.status === 'active' ? '启用' : '停用' }}
                  </el-tag>
                </div>
                <p class="detail-desc">{{ space.description || '暂无描述' }}</p>
              </div>
            </div>
            <div class="detail-top-actions" v-if="isTeacher">
              <el-button :icon="Edit" @click="openEditDialog">编辑信息</el-button>
            </div>
          </div>

          <!-- ===== Summary Bar ===== -->
          <div class="summary-bar">
            <div class="summary-item">
              <span class="summary-label">绑定专业</span>
              <div class="summary-tags" v-if="majors.length > 0">
                <span v-for="major in majors" :key="major.id" class="summary-tag summary-tag--indigo">{{ major.major_name || `专业 #${major.major_id}` }}<template v-if="major.enrollment_year"> · {{ major.enrollment_year }}级</template><template v-else> · 全部年级</template></span>
              </div>
              <span v-else class="summary-none">暂未绑定</span>
            </div>
            <div class="summary-divider"></div>
            <div class="summary-item">
              <span class="summary-label">空间学生</span>
              <span class="summary-val">{{ students.length }} 人</span>
            </div>
            <div class="summary-divider"></div>
            <div class="summary-item">
              <span class="summary-label">已发布资源</span>
              <span class="summary-val">{{ resources.vector_dbs.length + resources.bots.length }} 项</span>
            </div>
          </div>

          <!-- ===== Two-column Layout ===== -->
          <div class="detail-grid">
            <!-- Left Column -->
            <div class="detail-col">
              <!-- 绑定专业 -->
              <div class="section-card" v-if="isTeacher">
                <div class="section-head">
                  <div class="section-title-group">
                    <span class="section-dot" style="background: #6366f1"></span>
                    <h3 class="section-title">绑定专业</h3>
                    <span class="section-count">{{ majors.length }}</span>
                  </div>
                  <el-button type="primary" size="small" :icon="Plus" @click="openBindMajorDialog">绑定</el-button>
                </div>
                <div v-if="majors.length > 0" class="major-list">
                  <div v-for="major in majors" :key="major.id" class="major-item">
                    <div class="major-info">
                      <span class="major-name">{{ major.major_name || `专业 #${major.major_id}` }}</span>
                      <el-tag size="small" :type="major.enrollment_year ? 'primary' : 'info'" effect="plain" style="margin-left: 6px">
                        {{ major.enrollment_year ? `${major.enrollment_year}级` : '全部年级' }}
                      </el-tag>
                      <span class="major-code" v-if="major.major_code">{{ major.major_code }}</span>
                    </div>
                    <el-button type="danger" size="small" plain @click="handleUnbindMajor(major)">解绑</el-button>
                  </div>
                </div>
                <div v-else class="section-empty">暂未绑定专业，绑定后学生将自动加入空间</div>
              </div>

            </div>

            <!-- Right Column: Students -->
            <div class="detail-col" v-if="isTeacher">
              <div class="section-card section-card--full">
                <div class="section-head">
                  <div class="section-title-group">
                    <span class="section-dot" style="background: #f59e0b"></span>
                    <h3 class="section-title">空间学生</h3>
                    <span class="section-count">{{ students.length }} 人</span>
                  </div>
                  <el-button type="primary" size="small" :icon="Plus" @click="openAddStudentDialog">添加学生</el-button>
                </div>

                <!-- Student filters -->
                <div v-if="students.length > 0" class="student-filters">
                  <div v-if="students.length > 5" class="student-search">
                    <el-icon class="student-search-icon" :size="14"><Search /></el-icon>
                    <input v-model="studentSearch" class="student-search-input" placeholder="搜索姓名或学号..." />
                  </div>
                  <el-select
                    v-if="studentYears.length > 1"
                    v-model="studentYearFilter"
                    placeholder="全部年级"
                    size="small"
                    clearable
                    style="width: 120px; flex-shrink: 0"
                  >
                    <el-option v-for="y in studentYears" :key="y" :label="`${y}级`" :value="y" />
                  </el-select>
                </div>

                <div v-if="filteredStudents.length > 0" class="student-list">
                  <div v-for="stu in filteredStudents" :key="stu.id" class="student-item">
                    <div class="student-avatar">{{ (stu.name || stu.user_name || '?')[0] }}</div>
                    <div class="student-info">
                      <span class="student-name">{{ stu.name || stu.user_name || `用户 #${stu.id}` }}</span>
                      <span class="student-meta"><template v-if="stu.student_id">{{ stu.student_id }}</template><template v-if="stu.enrollment_year">{{ stu.student_id ? ' · ' : '' }}{{ stu.enrollment_year }}级</template><template v-if="stu.major_name"> · {{ stu.major_name }}</template><template v-if="stu.source === 'direct'"> · 手动添加</template></span>
                    </div>
                    <el-button v-if="stu.source === 'direct'" type="danger" size="small" :icon="Delete" circle plain @click="handleRemoveStudent(stu)" />
                  </div>
                </div>
                <div v-else-if="students.length > 0 && filteredStudents.length === 0" class="section-empty">无匹配的学生</div>
                <div v-else class="section-empty">暂无学生（请先绑定专业）</div>
              </div>
            </div>
          </div>

          <!-- ===== 已发布资源（全宽） ===== -->
          <div class="section-card">
            <div class="section-head">
              <div class="section-title-group">
                <span class="section-dot" style="background: #10b981"></span>
                <h3 class="section-title">已发布资源</h3>
              </div>
              <el-button v-if="isTeacher" type="primary" size="small" :icon="Plus" @click="openPublishDialog">发布</el-button>
            </div>

            <!-- Resource Tabs -->
            <div class="res-tabs">
              <button
                class="res-tab"
                :class="{ active: displayResourceTab === 'vector_db' }"
                @click="displayResourceTab = 'vector_db'"
              >
                知识库
                <span class="res-tab-count">{{ resources.vector_dbs.length }}</span>
              </button>
              <button
                class="res-tab"
                :class="{ active: displayResourceTab === 'bot' }"
                @click="displayResourceTab = 'bot'"
              >
                数字助理
                <span class="res-tab-count">{{ resources.bots.length }}</span>
              </button>
            </div>

            <!-- Vector DBs -->
            <div v-if="displayResourceTab === 'vector_db'" class="res-content">
              <div v-if="resources.vector_dbs.length > 0" class="resource-list">
                <div v-for="res in resources.vector_dbs" :key="res.id" class="resource-item">
                  <div class="resource-icon resource-icon--kb">KB</div>
                  <div class="resource-info">
                    <span class="resource-name">{{ res.name }}</span>
                    <span class="resource-desc" v-if="res.describe">{{ res.describe }}</span>
                  </div>
                  <el-button v-if="isTeacher" type="warning" size="small" plain @click="handleUnpublish('vector_db', res)">取消</el-button>
                </div>
              </div>
              <div v-else class="section-empty">暂无已发布的知识库</div>
            </div>

            <!-- Bots -->
            <div v-if="displayResourceTab === 'bot'" class="res-content">
              <div v-if="resources.bots.length > 0" class="resource-list">
                <div v-for="res in resources.bots" :key="res.id" class="resource-item">
                  <div class="resource-icon resource-icon--bot">AI</div>
                  <div class="resource-info">
                    <span class="resource-name">{{ res.name }}</span>
                    <span class="resource-desc" v-if="res.description">{{ res.description }}</span>
                  </div>
                  <el-button v-if="isTeacher" type="warning" size="small" plain @click="handleUnpublish('bot', res)">取消</el-button>
                </div>
              </div>
              <div v-else class="section-empty">暂无已发布的数字助理</div>
            </div>
          </div>

        </div>
      </div>
    </div>

    <!-- Edit Dialog -->
    <el-dialog v-model="editDialogVisible" title="编辑教学空间" width="480px">
      <el-form :model="editForm" label-width="80px">
        <el-form-item label="空间名称" required>
          <el-input v-model="editForm.name" placeholder="请输入教学空间名称" maxlength="50" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="editForm.description" type="textarea" :rows="3" placeholder="请输入描述（可选）" maxlength="200" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- Bind Major Dialog -->
    <el-dialog v-model="bindMajorDialogVisible" title="绑定专业" width="480px">
      <el-form label-width="80px">
        <el-form-item label="选择专业">
          <el-select v-model="selectedMajor" placeholder="请选择专业" style="width: 100%" filterable>
            <el-option v-for="m in collegeMajors" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="选择年级" v-if="selectedMajor">
          <el-select
            v-model="selectedEnrollmentYear"
            placeholder="全部年级"
            style="width: 100%"
            clearable
            :loading="loadingGrades"
          >
            <el-option :label="'全部年级'" :value="null" />
            <el-option
              v-for="g in majorGrades"
              :key="g.enrollment_year"
              :label="`${g.enrollment_year}级（${g.student_count}人）`"
              :value="g.enrollment_year"
            />
          </el-select>
          <div v-if="majorGrades.length === 0 && !loadingGrades && selectedMajor" style="font-size: 12px; color: #94a3b8; margin-top: 4px">
            该专业暂无已注册的学生年级数据
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bindMajorDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitBindMajor" :loading="bindLoading">绑定</el-button>
      </template>
    </el-dialog>

    <!-- Add Student Dialog -->
    <el-dialog v-model="addStudentDialogVisible" title="添加学生" width="420px">
      <el-form label-width="80px">
        <el-form-item label="学生ID">
          <el-input v-model="addStudentId" placeholder="请输入学生的用户ID" type="number" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addStudentDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitAddStudent" :loading="addStudentLoading">添加</el-button>
      </template>
    </el-dialog>

    <!-- Publish Resource Dialog -->
    <el-dialog v-model="publishDialogVisible" title="发布资源" width="560px">
      <div v-loading="publishLoading" class="publish-list">
        <div v-if="ownVectors.length > 0" class="publish-section">
          <div class="publish-section-title">知识库</div>
          <el-checkbox-group v-model="selectedVectorDbs">
            <div v-for="item in ownVectors" :key="item.id" class="publish-item">
              <el-checkbox :value="item.id" :disabled="isVdbPublished(item.id)">
                <span class="publish-item-name">{{ item.name }}</span>
                <el-tag v-if="isVdbPublished(item.id)" size="small" type="info" effect="plain" style="margin-left: 8px">已发布</el-tag>
              </el-checkbox>
            </div>
          </el-checkbox-group>
        </div>
        <div v-if="ownBots.length > 0" class="publish-section">
          <div class="publish-section-title">数字助理</div>
          <el-checkbox-group v-model="selectedBots">
            <div v-for="item in ownBots" :key="item.id" class="publish-item">
              <el-checkbox :value="item.id" :disabled="isBotPublished(item.id)">
                <span class="publish-item-name">{{ item.name }}</span>
                <el-tag v-if="isBotPublished(item.id)" size="small" type="info" effect="plain" style="margin-left: 8px">已发布</el-tag>
              </el-checkbox>
            </div>
          </el-checkbox-group>
        </div>
        <el-empty v-if="ownVectors.length === 0 && ownBots.length === 0 && !publishLoading" description="暂无可发布的资源" :image-size="60" />
      </div>

      <template #footer>
        <el-button @click="publishDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitPublish" :loading="publishLoading" :disabled="totalSelected === 0">
          发布 ({{ totalSelected }})
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
/* ===== Page Layout ===== */
.detail-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ===== Top Header ===== */
.detail-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 20px;
  background: #fff;
  border: 1px solid #e6ebf2;
  border-radius: 10px;
}

.detail-top-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  flex: 1;
}

.back-btn {
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
.back-btn:hover { border-color: #c7d2fe; color: #4f46e5; background: #eef2ff; }

.detail-info { min-width: 0; flex: 1; }

.detail-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 4px;
}

.detail-title {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 650;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-desc {
  margin: 0;
  font-size: 13px;
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-code {
  font-size: 13px;
  font-weight: 700;
  color: #6366f1;
  background: #eef2ff;
  padding: 2px 8px;
  border-radius: 4px;
  flex-shrink: 0;
}

.detail-top-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

/* ===== Summary Bar ===== */
.summary-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 20px;
  background: #fff;
  border: 1px solid #e6ebf2;
  border-radius: 10px;
  flex-wrap: wrap;
}

.summary-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.summary-label {
  font-size: 12.5px;
  font-weight: 500;
  color: #94a3b8;
  flex-shrink: 0;
}

.summary-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.summary-tag {
  font-size: 12px;
  font-weight: 500;
  padding: 2px 10px;
  border-radius: 4px;
}

.summary-tag--indigo {
  background: #eef2ff;
  color: #4f46e5;
}

.summary-val {
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}

.summary-none {
  font-size: 12.5px;
  color: #cbd5e1;
}

.summary-divider {
  width: 1px;
  height: 18px;
  background: #e2e8f0;
  flex-shrink: 0;
}

/* ===== Grid Layout ===== */
.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  align-items: start;
}

.detail-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ===== Section Card ===== */
.section-card {
  background: #fff;
  border: 1px solid #e6ebf2;
  border-radius: 10px;
  padding: 16px 18px;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.section-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.section-dot {
  display: inline-block;
  width: 3px;
  height: 14px;
  border-radius: 2px;
  flex-shrink: 0;
}

.section-title {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: #1e293b;
}

.section-count {
  font-size: 12px;
  color: #94a3b8;
  font-weight: 500;
}

.section-empty {
  padding: 20px;
  text-align: center;
  font-size: 13px;
  color: #94a3b8;
  background: #f9fafb;
  border-radius: 8px;
}

/* ===== Major List ===== */
.major-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.major-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
}

.major-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.major-name {
  font-size: 13.5px;
  font-weight: 500;
  color: #1e293b;
}

.major-code {
  font-size: 12px;
  color: #94a3b8;
}

/* ===== Resource Tabs & List ===== */
.res-tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 12px;
  border-bottom: 1px solid #f1f5f9;
}

.res-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
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

.res-tab:hover { color: #4f46e5; }
.res-tab.active { color: #4f46e5; border-bottom-color: #4f46e5; font-weight: 600; }

.res-tab-count {
  padding: 1px 6px;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 600;
  background: #f1f5f9;
  color: #64748b;
}

.res-tab.active .res-tab-count {
  background: #e0e7ff;
  color: #4338ca;
}

.res-content {
  min-height: 52px;
}

.res-content > .section-empty {
  min-height: 52px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 14px 20px;
}

.resource-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.resource-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
}

.resource-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 6px;
  font-size: 10px;
  font-weight: 700;
  flex-shrink: 0;
}

.resource-icon--kb { background: #dcfce7; color: #16a34a; }
.resource-icon--bot { background: #e0e7ff; color: #4f46e5; }

.resource-info {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  flex: 1;
}

.resource-name {
  font-size: 13px;
  font-weight: 500;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.resource-desc {
  font-size: 12px;
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ===== Student List ===== */
.student-filters {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.student-search {
  display: flex;
  align-items: center;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 0 10px;
  height: 32px;
  flex: 1;
  transition: border-color 0.15s;
}

.student-search:focus-within { border-color: #a5b4fc; background: #fff; }
.student-search-icon { color: #94a3b8; flex-shrink: 0; }

.student-search-input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 12.5px;
  padding: 0 8px;
  color: #1e293b;
  height: 100%;
}

.student-search-input::placeholder { color: #94a3b8; }

.student-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 400px;
  overflow-y: auto;
}

.student-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  transition: background 0.1s;
}

.student-item:hover { background: #f8fafc; }

.student-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #f1f5f9;
  color: #64748b;
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
}

.student-info {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.student-name {
  font-size: 13px;
  font-weight: 500;
  color: #1e293b;
}

.student-meta {
  font-size: 11.5px;
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ===== Publish Dialog ===== */
.publish-list {
  min-height: 120px;
  max-height: 400px;
  overflow-y: auto;
}

.publish-section {
  margin-bottom: 12px;
}

.publish-section:last-child { margin-bottom: 0; }

.publish-section-title {
  font-size: 13px;
  font-weight: 600;
  color: #64748b;
  padding: 4px 0 8px;
  border-bottom: 1px solid #f1f5f9;
  margin-bottom: 4px;
}

.publish-item {
  padding: 8px 4px;
  border-bottom: 1px solid #f3f4f6;
}

.publish-item:last-child { border-bottom: none; }

.publish-item-name {
  font-size: 13.5px;
  color: #1e293b;
}

/* ===== Responsive ===== */
@media (max-width: 860px) {
  .detail-top { flex-direction: column; align-items: flex-start; }
  .detail-top-actions { width: 100%; justify-content: flex-end; }
  .detail-grid { grid-template-columns: 1fr; }
  .summary-bar { flex-direction: column; align-items: flex-start; gap: 8px; }
  .summary-divider { display: none; }
}

@media (max-width: 480px) {
  .quick-stats { grid-template-columns: 1fr; }
}
</style>
