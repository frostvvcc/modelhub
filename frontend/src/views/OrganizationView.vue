<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { Plus, Edit, Delete, User, Refresh, ArrowRight, Connection, View, Search, Reading } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router';
import {
  createOrganization, getOrganizationTree, updateOrganization,
  deleteOrganization, getMembers, removeMember, getGradeDistribution,
  type Organization, type OrganizationMember, type GradeDistribution
} from '../api/organization';
import { fetchOwnVectors } from '../api/vectorDb';
import { getSpacesByMajor, type TeachingSpace } from '../api/teachingSpace';
import { useUserStore } from '../stores/user';

const router = useRouter();
const userStore = useUserStore();

const organizationTree = ref<Organization | null>(null);
const loading = ref(false);
const dialogVisible = ref(false);
const memberDialogVisible = ref(false);
const currentOrg = ref<Organization | null>(null);
const currentOrgMembers = ref<OrganizationMember[]>([]);
const canWriteOrganization = computed(() => userStore.userPermissions.includes('organization:write'));

// ===== 面包屑钻取 =====
const breadcrumb = ref<Organization[]>([]);
const currentNode = computed(() => breadcrumb.value.length > 0 ? breadcrumb.value[breadcrumb.value.length - 1] : null);
const childOrgs = computed(() => currentNode.value?.children || []);

const childSearchKeyword = ref('');

const flattenDescendants = (org: Organization): Organization[] => {
  const result: Organization[] = [];
  for (const child of (org.children || [])) {
    result.push(child);
    result.push(...flattenDescendants(child));
  }
  return result;
};

const filteredChildOrgs = computed(() => {
  const kw = childSearchKeyword.value.trim().toLowerCase();
  if (!kw) return childOrgs.value;
  if (!currentNode.value) return [];
  const all = flattenDescendants(currentNode.value);
  return all.filter(org =>
    org.name.toLowerCase().includes(kw) ||
    (orgTypeLabels[org.type] || '').includes(kw)
  );
});

const isSearching = computed(() => childSearchKeyword.value.trim().length > 0);

const orgTypeLabels: Record<string, string> = {
  school: '学校', college: '学院', major: '专业', department: '部门',
};

const orgTypeOptions = [
  { label: '学校', value: 'school' }, { label: '学院', value: 'college' }, { label: '专业', value: 'major' }, { label: '部门', value: 'department' },
];

// ===== 教学空间（仅专业级展示）=====
const majorSpaces = ref<TeachingSpace[]>([]);
const loadingSpaces = ref(false);

const loadMajorSpaces = async (org: Organization) => {
  if (org.type !== 'major') { majorSpaces.value = []; return; }
  loadingSpaces.value = true;
  try {
    majorSpaces.value = await getSpacesByMajor(org.id);
  } catch { majorSpaces.value = []; }
  finally { loadingSpaces.value = false; }
};

// ===== 年级分布（仅专业级展示）=====
const gradeDistribution = ref<GradeDistribution[]>([]);
const loadingGrades = ref(false);

const loadGradeDistribution = async (org: Organization) => {
  if (org.type !== 'major') { gradeDistribution.value = []; return; }
  loadingGrades.value = true;
  try {
    gradeDistribution.value = await getGradeDistribution(org.id);
  } catch { gradeDistribution.value = []; }
  finally { loadingGrades.value = false; }
};

const totalGradeStudents = computed(() => gradeDistribution.value.reduce((sum, g) => sum + g.student_count, 0));

// ===== 知识库（仅非学校级展示）=====
const orgVectorDbs = ref<any[]>([]);
const loadingKbs = ref(false);

const getOrgDbVisibilityLabel = (db: any) => {
  if (!db.organization_id) return '私有';
  if (db.org_name) return db.org_name;
  return '组织';
};
const getOrgDbVisibilityType = (db: any): 'success' | 'primary' | 'info' => {
  if (!db.organization_id) return 'info';
  return 'primary';
};

const loadKbs = async (org: Organization) => {
  if (org.type === 'school') { orgVectorDbs.value = []; return; }
  loadingKbs.value = true;
  try {
    const allDbs = await fetchOwnVectors(org.id);
    orgVectorDbs.value = allDbs.filter((db: any) =>
      db.organization_id === org.id
    );
  } catch { orgVectorDbs.value = []; }
  finally { loadingKbs.value = false; }
};

const form = ref({ name: '', code: '', org_type: 'college', parent_id: null as number | null, description: '', school_id: null as number | null });
const formRules = {
  name: [{ required: true, message: '请输入组织名称', trigger: 'blur' }],
  code: [{ required: true, message: '请输入组织编码', trigger: 'blur' }],
  org_type: [{ required: true, message: '请选择组织类型', trigger: 'change' }],
};

// 导航到某个组织
const navigateTo = async (org: Organization) => {
  const path = buildPathTo(org, organizationTree.value);
  if (path.length > 0) {
    breadcrumb.value = path;
    childSearchKeyword.value = '';
    await Promise.all([loadKbs(org), loadMajorSpaces(org), loadGradeDistribution(org)]);
  }
};

// 面包屑点击
const navigateToBreadcrumb = async (index: number) => {
  breadcrumb.value = breadcrumb.value.slice(0, index + 1);
  childSearchKeyword.value = '';
  if (currentNode.value) await Promise.all([loadKbs(currentNode.value), loadMajorSpaces(currentNode.value), loadGradeDistribution(currentNode.value)]);
};

// 从树中找到到达目标节点的路径
const buildPathTo = (target: Organization, root: Organization | null): Organization[] => {
  if (!root) return [];
  if (root.id === target.id) return [root];
  for (const child of (root.children || [])) {
    const sub = buildPathTo(target, child);
    if (sub.length > 0) return [root, ...sub];
  }
  return [];
};

const loadOrganizationTree = async () => {
  if (!userStore.currentSchool) { ElMessage.warning('请先选择学校'); return; }
  loading.value = true;
  try {
    const tree = await getOrganizationTree(userStore.currentSchool.id);
    organizationTree.value = tree;
    if (tree) { breadcrumb.value = [tree]; }
  } catch (error: any) {
    ElMessage.error(error.response?.data?.message || '加载组织树失败');
  } finally { loading.value = false; }
};

const getNextOrgType = (t: string) => ({ school: 'college', college: 'major' }[t] || 'college');

const handleCreate = (parentOrg?: Organization) => {
  form.value = { name: '', code: '', org_type: parentOrg ? getNextOrgType(parentOrg.type) : 'school', parent_id: parentOrg?.id || null, description: '', school_id: userStore.currentSchool?.id || null };
  currentOrg.value = null;
  dialogVisible.value = true;
};

const submitForm = async () => {
  loading.value = true;
  try {
    await createOrganization({ ...form.value, parent_id: form.value.parent_id ?? undefined, school_id: form.value.school_id ?? undefined });
    ElMessage.success('创建成功');
    dialogVisible.value = false;
    await loadOrganizationTree();
  } catch (error: any) { ElMessage.error(error.response?.data?.message || '创建失败'); }
  finally { loading.value = false; }
};

const handleEdit = (org: Organization) => {
  form.value = { name: org.name, code: org.code, org_type: org.type, parent_id: org.parent_id, description: org.description || '', school_id: org.school_id };
  currentOrg.value = org;
  dialogVisible.value = true;
};

const updateForm = async () => {
  if (!currentOrg.value) return;
  loading.value = true;
  try {
    await updateOrganization(currentOrg.value.id, { name: form.value.name, description: form.value.description });
    ElMessage.success('更新成功');
    dialogVisible.value = false;
    await loadOrganizationTree();
  } catch (error: any) { ElMessage.error(error.response?.data?.message || '更新失败'); }
  finally { loading.value = false; }
};

const handleDelete = async (org: Organization) => {
  try {
    await ElMessageBox.confirm(`确定要删除组织"${org.name}"吗？`, '确认删除', { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' });
    loading.value = true;
    await deleteOrganization(org.id);
    ElMessage.success('删除成功');
    await loadOrganizationTree();
  } catch (error: any) {
    if (error !== 'cancel') ElMessage.error(error.response?.data?.message || '删除失败');
  } finally { loading.value = false; }
};

const handleViewMembers = async (org: Organization) => {
  currentOrg.value = org;
  loading.value = true;
  try { currentOrgMembers.value = await getMembers(org.id); memberDialogVisible.value = true; }
  catch (error: any) { ElMessage.error(error.response?.data?.message || '加载成员失败'); }
  finally { loading.value = false; }
};

const handleRemoveMember = async (member: OrganizationMember) => {
  if (!currentOrg.value) return;
  try { await removeMember(currentOrg.value.id, member.user_id); ElMessage.success('移除成功'); currentOrgMembers.value = await getMembers(currentOrg.value.id); }
  catch (error: any) { ElMessage.error(error.response?.data?.message || '移除失败'); }
};

onMounted(() => { if (userStore.currentSchool) loadOrganizationTree(); });
</script>

<template>
  <div class="page-container">
    <div class="content-section">
      <div class="page-header">
        <div>
          <h2>组织架构</h2>
          <p class="subtitle">管理学校、学院/部门及个人成员</p>
        </div>
        <div class="header-actions">
          <el-button type="primary" :icon="Plus" @click="handleCreate()" v-if="canWriteOrganization && !currentNode">创建学校</el-button>
          <el-button :icon="Refresh" @click="loadOrganizationTree">刷新</el-button>
        </div>
      </div>

      <!-- 面包屑：仅在进入子组织后显示，根节点时信息卡已展示校名 -->
      <div class="breadcrumb" v-if="breadcrumb.length > 1">
        <span
          v-for="(node, i) in breadcrumb"
          :key="node.id"
          class="breadcrumb-item"
          :class="{ active: i === breadcrumb.length - 1 }"
          @click="i < breadcrumb.length - 1 && navigateToBreadcrumb(i)"
        >
          {{ node.name }}
          <el-icon v-if="i < breadcrumb.length - 1" class="breadcrumb-sep" :size="12"><ArrowRight /></el-icon>
        </span>
      </div>

      <div v-loading="loading" class="org-body">
        <template v-if="currentNode">
          <!-- 当前组织信息卡 -->
          <div class="org-info-card">
            <div class="org-info-left">
              <h3>{{ currentNode.name }}</h3>
              <div class="org-info-meta">
                <el-tag size="small" type="info" effect="plain">{{ orgTypeLabels[currentNode.type] || currentNode.type }}</el-tag>
                <span v-if="childOrgs.length > 0">{{ childOrgs.length }} 个下级组织</span>
              </div>
              <p class="org-info-desc" v-if="currentNode.description">{{ currentNode.description }}</p>
            </div>
            <div class="org-info-actions" v-if="canWriteOrganization">
              <el-button v-if="currentNode.type === 'school'" size="small" :icon="Plus" @click="handleCreate(currentNode)">添加学院</el-button>
              <el-button v-if="currentNode.type === 'college'" size="small" :icon="Plus" @click="handleCreate(currentNode)">添加专业</el-button>
              <el-button size="small" :icon="Edit" @click="handleEdit(currentNode)">编辑</el-button>
              <el-button v-if="currentNode.type !== 'school'" size="small" :icon="User" @click="handleViewMembers(currentNode)">成员</el-button>
              <el-button size="small" type="danger" plain :icon="Delete" @click="handleDelete(currentNode)">删除</el-button>
            </div>
            <div class="org-info-actions" v-else-if="currentNode.type !== 'school'">
              <el-button size="small" :icon="User" @click="handleViewMembers(currentNode)">查看成员</el-button>
            </div>
          </div>

          <!-- 下级组织 -->
          <template v-if="childOrgs.length > 0">
            <div class="section-header">
              <h4 class="section-title">下级组织</h4>
              <el-input
                v-if="childOrgs.length >= 5"
                v-model="childSearchKeyword"
                class="child-search-input"
                placeholder="搜索学院、专业..."
                clearable
                :prefix-icon="Search"
                size="small"
              />
            </div>
            <div class="child-grid">
              <div v-for="child in filteredChildOrgs" :key="child.id" class="child-card" @click="navigateTo(child)">
                <div class="child-head">
                  <span class="child-name">{{ child.name }}</span>
                  <el-tag size="small" type="info" effect="plain">{{ orgTypeLabels[child.type] || child.type }}</el-tag>
                </div>
                <div class="child-meta">
                  <span v-if="child.children?.length">{{ child.children.length }} 个下属</span>
                  <span v-if="child.description" class="child-desc">{{ child.description }}</span>
                </div>
                <div class="child-foot">
                  <span class="child-enter">进入 <el-icon :size="12"><ArrowRight /></el-icon></span>
                </div>
              </div>
            </div>
            <el-empty v-if="isSearching && filteredChildOrgs.length === 0" description="未找到匹配的组织" :image-size="64" />
          </template>

          <!-- 年级分布（仅专业级展示） -->
          <template v-if="currentNode.type === 'major'">
            <div class="section-header">
              <h4 class="section-title">年级分布</h4>
              <span v-if="totalGradeStudents > 0" style="font-size: 12px; color: #94a3b8">共 {{ totalGradeStudents }} 名学生</span>
            </div>
            <el-skeleton :rows="1" animated v-if="loadingGrades" />
            <template v-else-if="gradeDistribution.length > 0">
              <div class="grade-grid">
                <div v-for="g in gradeDistribution" :key="g.enrollment_year" class="grade-card">
                  <span class="grade-year">{{ g.enrollment_year }} 级</span>
                  <span class="grade-count">{{ g.student_count }} 人</span>
                </div>
              </div>
            </template>
            <el-empty v-else description="暂无学生年级数据" :image-size="48" />
          </template>

          <!-- 绑定的教学空间（仅专业级展示） -->
          <template v-if="currentNode.type === 'major'">
            <h4 class="section-title">绑定的教学空间</h4>
            <el-skeleton :rows="2" animated v-if="loadingSpaces" />
            <template v-else-if="majorSpaces.length > 0">
              <div class="kb-grid">
                <div v-for="space in majorSpaces" :key="space.id" class="kb-card" @click="router.push(userStore.user?.role === 'admin' ? `/admin/teaching-space/${space.id}` : `/teaching-space/${space.id}`)">
                  <div class="kb-card-header">
                    <el-icon class="kb-icon space-icon"><Reading /></el-icon>
                    <span class="kb-name">{{ space.name }}</span>
                    <el-tag size="small" :type="space.status === 'active' ? 'success' : 'info'" effect="plain" style="margin-left: auto">
                      {{ space.status === 'active' ? '启用' : '停用' }}
                    </el-tag>
                  </div>
                  <p class="kb-desc">{{ space.description || '暂无描述' }}</p>
                  <div class="space-metrics">
                    <span class="space-metric"><strong>{{ space.teacher_name || '未知' }}</strong> 授课</span>
                    <span class="space-metric">{{ space.member_count ?? 0 }} 名学生</span>
                    <span class="space-metric">{{ space.resource_count ?? 0 }} 个资源</span>
                  </div>
                  <div class="kb-footer">
                    <el-tag size="small" effect="plain" type="primary" v-if="space.major_count">{{ space.major_count }} 个专业</el-tag>
                    <el-button link type="primary" size="small" :icon="View">查看</el-button>
                  </div>
                </div>
              </div>
            </template>
            <el-empty v-else description="该专业暂未绑定教学空间" :image-size="64" />
          </template>

          <!-- 知识库资源（仅非学校级展示） -->
          <template v-if="currentNode.type !== 'school' && !loadingKbs && orgVectorDbs.length > 0">
            <h4 class="section-title">知识库资源</h4>
            <div class="kb-grid">
              <div v-for="db in orgVectorDbs" :key="db.id" class="kb-card" @click="router.push(`/database/${db.id}`)">
                <div class="kb-card-header">
                  <el-icon class="kb-icon"><Connection /></el-icon>
                  <span class="kb-name">{{ db.name }}</span>
                </div>
                <p class="kb-desc">{{ db.describe || '暂无描述' }}</p>
                <div class="kb-footer">
                  <el-tag size="small" effect="plain" :type="getOrgDbVisibilityType(db)">{{ getOrgDbVisibilityLabel(db) }}</el-tag>
                  <el-button link type="primary" size="small" :icon="View">查看</el-button>
                </div>
              </div>
            </div>
          </template>

        </template>

        <el-empty v-else-if="!loading" description="暂无组织数据" />
      </div>
    </div>

    <!-- 创建/编辑对话框 -->
    <el-dialog v-model="dialogVisible" :title="currentOrg ? '编辑组织' : '创建组织'" width="600px">
      <el-form :model="form" :rules="formRules" label-width="100px">
        <el-form-item label="组织名称" prop="name"><el-input v-model="form.name" placeholder="请输入组织名称" /></el-form-item>
        <el-form-item label="组织编码" prop="code" v-if="!currentOrg"><el-input v-model="form.code" placeholder="请输入组织编码（唯一）" /></el-form-item>
        <el-form-item label="组织类型" prop="org_type" v-if="!currentOrg">
          <el-select v-model="form.org_type" placeholder="请选择组织类型">
            <el-option v-for="o in orgTypeOptions" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="3" placeholder="请输入组织描述" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="currentOrg ? updateForm() : submitForm()" :loading="loading">{{ currentOrg ? '更新' : '创建' }}</el-button>
      </template>
    </el-dialog>

    <!-- 成员管理对话框 -->
    <el-dialog v-model="memberDialogVisible" :title="canWriteOrganization ? '组织成员管理' : '组织成员'" width="800px">
      <el-table :data="currentOrgMembers" v-loading="loading">
        <el-table-column prop="user_name" label="姓名" min-width="100">
          <template #default="{ row }">{{ row.user_name || `用户 #${row.user_id}` }}</template>
        </el-table-column>
        <el-table-column label="学号/工号" min-width="120">
          <template #default="{ row }">{{ row.student_id || row.employee_id || '-' }}</template>
        </el-table-column>
        <el-table-column prop="role" label="组织角色" min-width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.role === 'admin' ? 'danger' : row.role === 'teacher' ? 'warning' : 'info'" effect="plain">
              {{ { admin: '管理员', teacher: '教师', student: '学生', guest: '访客', member: '成员' }[row.role] || row.role }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" min-width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'active' ? 'success' : 'info'" effect="plain">
              {{ row.status === 'active' ? '正常' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="join_at" label="加入时间" min-width="110">
          <template #default="{ row }">{{ row.join_at ? row.join_at.slice(0, 10) : '-' }}</template>
        </el-table-column>
        <el-table-column v-if="canWriteOrganization" label="操作" min-width="80">
          <template #default="{ row }"><el-button link type="danger" size="small" @click="handleRemoveMember(row)">移除</el-button></template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.header-actions { display: flex; gap: 8px; flex-shrink: 0; }

/* 面包屑 */
.breadcrumb { display: flex; align-items: center; gap: 2px; margin-bottom: 16px; padding: 10px 14px; background: #f8fafc; border-radius: 8px; flex-wrap: wrap; }
.breadcrumb-item { font-size: 13.5px; color: #6366f1; cursor: pointer; display: inline-flex; align-items: center; gap: 2px; transition: color 0.15s; }
.breadcrumb-item:hover { color: #4338ca; text-decoration: underline; }
.breadcrumb-item.active { color: #1e293b; font-weight: 600; cursor: default; }
.breadcrumb-item.active:hover { text-decoration: none; }
.breadcrumb-sep { color: #cbd5e1; margin: 0 4px; }

.org-body { min-height: 200px; }

/* 当前组织信息卡 */
.org-info-card { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 16px 20px; background: #fff; border: 1px solid #e6ebf2; border-radius: 10px; margin-bottom: 20px; }
.org-info-left { flex: 1; min-width: 0; }
.org-info-left h3 { margin: 0 0 6px; font-size: 17px; color: #1e293b; }
.org-info-meta { display: flex; align-items: center; gap: 10px; font-size: 12.5px; color: #6b7280; flex-wrap: wrap; }
.org-info-desc { margin: 8px 0 0; font-size: 13px; color: #6b7280; line-height: 1.5; }
.org-info-actions { display: flex; gap: 6px; flex-shrink: 0; flex-wrap: wrap; }

.section-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; gap: 12px; }
.section-header .section-title { margin: 0; }
.child-search-input { width: 220px; }
.section-title { font-size: 14px; font-weight: 600; color: #334155; margin: 0 0 12px; }

/* 下级组织卡片 */
.child-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 24px; }
.child-card { padding: 14px; border: 1px solid #e6ebf2; border-radius: 10px; background: #fff; cursor: pointer; transition: all 0.18s; display: flex; flex-direction: column; gap: 8px; }
.child-card:hover { border-color: #c7d2fe; box-shadow: 0 4px 16px rgba(99,102,241,0.08); transform: translateY(-2px); }
.child-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.child-name { font-size: 14px; font-weight: 600; color: #1e293b; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.child-meta { font-size: 12px; color: #9ca3af; display: flex; gap: 8px; }
.child-desc { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 160px; }
.child-foot { display: flex; justify-content: flex-end; margin-top: auto; }
.child-enter { display: inline-flex; align-items: center; gap: 3px; font-size: 12.5px; color: #818cf8; font-weight: 500; transition: color 0.15s; }
.child-card:hover .child-enter { color: #6366f1; }

/* 知识库卡片 */
.kb-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.kb-card { border: 1px solid #e6ebf2; border-radius: 8px; padding: 14px; background: #fff; cursor: pointer; transition: all 0.18s; display: flex; flex-direction: column; gap: 8px; }
.kb-card:hover { transform: translateY(-2px); box-shadow: 0 4px 16px rgba(15,23,42,0.06); border-color: #b9cdf8; }
.kb-card-header { display: flex; align-items: center; gap: 8px; }
.kb-icon { width: 28px; height: 28px; background: #eaf2ff; color: #2563eb; border-radius: 6px; font-size: 14px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; }
.kb-name { font-size: 13.5px; font-weight: 600; color: #1f2937; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kb-desc { margin: 0; font-size: 12px; color: #6b7280; line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.kb-footer { display: flex; align-items: center; justify-content: space-between; margin-top: auto; }

/* 教学空间卡片 */
.space-icon { background: #f0fdf4; color: #16a34a; }
.space-metrics { display: flex; align-items: center; gap: 12px; font-size: 12px; color: #6b7280; }
.space-metric strong { color: #1e293b; }

/* 年级分布卡片 */
.grade-grid { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 20px; }
.grade-card { display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 12px 20px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; min-width: 90px; }
.grade-year { font-size: 14px; font-weight: 600; color: #4f46e5; }
.grade-count { font-size: 12px; color: #64748b; }

@media (max-width: 1024px) { .child-grid, .kb-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 640px) {
  .child-grid, .kb-grid { grid-template-columns: 1fr; }
  .org-info-card { flex-direction: column; }
}
</style>
