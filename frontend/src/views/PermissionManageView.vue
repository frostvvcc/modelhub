<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import type { FormInstance, FormRules } from 'element-plus';
import {
  getRoles,
  getAllPermissions,
  getRolePermissions,
  createRole,
  updateRole,
  deleteRole,
  assignPermissionToRole,
  removePermissionFromRole,
  assignRoleToUser,
  getUserRoles,
  type Role,
  type Permission
} from '../api/permission';
import { getUserOrganizations, type Organization } from '../api/organization';
import { useUserStore } from '../stores/user';
import api from '../utils/api';

const userStore = useUserStore();

const roles = ref<Role[]>([]);
const permissions = ref<Permission[]>([]);
const organizations = ref<Organization[]>([]);
const totalMembers = ref(0);
const loading = ref(false);

const selectedRole = ref<Role | null>(null);
const rolePermissions = ref<number[]>([]);

const roleFormRef = ref<FormInstance>();
const roleForm = reactive({
  id: null as number | null,
  name: '',
  code: '',
  description: '',
  level: 'class',
  is_system: false,
  school_id: null as number | null,
});

const userRoleForm = reactive({
  user_id: null as number | null,
  role_id: null as number | null,
  organization_id: null as number | null,
});

const userSearchKeyword = ref('');
const userList = ref<Record<string, unknown>[]>([]);
const userListLoading = ref(false);
const roleMap: Record<string, string> = { admin: '管理员', teacher: '教师', student: '学生' };
const roleOptions = [
  { label: '学生', value: 'student' },
  { label: '教师', value: 'teacher' },
  { label: '管理员', value: 'admin' },
];

const permGroupColors = ['#f59e0b', '#6366f1', '#10b981', '#ec4899', '#8b5cf6', '#06b6d4', '#f97316', '#14b8a6'];

const searchUsers = async () => {
  userListLoading.value = true;
  try {
    const res = await api.get('/user/admin/users', { params: { keyword: userSearchKeyword.value } });
    userList.value = res.data.data || [];
  } catch (error: unknown) {
    ElMessage.error(error.response?.data?.message || '搜索用户失败');
  } finally {
    userListLoading.value = false;
  }
};

const changeUserRole = async (userId: number, newRole: string) => {
  try {
    await api.put(`/user/admin/users/${userId}/role`, null, { params: { role: newRole } });
    ElMessage.success('角色更新成功');
    await searchUsers();
  } catch (error: unknown) {
    ElMessage.error(error.response?.data?.message || '角色更新失败');
  }
};

const roleRules: FormRules = {
  name: [{ required: true, message: '请输入角色名称', trigger: 'blur' }],
  code: [{ required: true, message: '请输入角色代码', trigger: 'blur' }],
  level: [{ required: true, message: '请选择权限级别', trigger: 'change' }],
};

const levelOptions = [
  { label: '系统级', value: 'system' },
  { label: '学校级', value: 'school' },
  { label: '学院级', value: 'college' },
];

const groupedPermissions = computed(() => {
  const grouped: Record<string, Permission[]> = {};
  permissions.value.forEach(perm => {
    if (!grouped[perm.resource]) {
      grouped[perm.resource] = [];
    }
    grouped[perm.resource].push(perm);
  });
  return grouped;
});

const groupedPermissionKeys = computed(() => Object.keys(groupedPermissions.value));

const loadData = async () => {
  loading.value = true;
  try {
    const schoolId = userStore.currentSchool?.id;
    const [rolesData, permissionsData, orgsData] = await Promise.all([
      getRoles(schoolId, true),
      getAllPermissions(),
      getUserOrganizations(Number(userStore.user?.id))
    ]);
    roles.value = rolesData;
    permissions.value = permissionsData;
    organizations.value = orgsData;
    try {
      const usersRes = await api.get('/user/admin/users', { params: { keyword: '' } });
      totalMembers.value = usersRes.data.data?.length || 0;
    } catch { totalMembers.value = 0; }
  } catch (error: unknown) {
    ElMessage.error(error.response?.data?.message || '加载数据失败');
  } finally {
    loading.value = false;
  }
};

const selectRole = async (role: Role) => {
  selectedRole.value = role;
  Object.assign(roleForm, {
    id: role.id,
    name: role.name,
    code: role.code,
    description: role.description || '',
    level: role.level,
    is_system: role.is_system,
    school_id: role.school_id,
  });

  try {
    const rolePerms = await getRolePermissions(role.id);
    rolePermissions.value = rolePerms.map((p: Permission) => p.id);
  } catch (error: unknown) {
    ElMessage.error('加载角色权限失败');
  }
};

const handleCreateRole = () => {
  selectedRole.value = null;
  Object.assign(roleForm, {
    id: null,
    name: '',
    code: '',
    description: '',
    level: 'class',
    is_system: false,
    school_id: userStore.currentSchool?.id || null,
  });
  rolePermissions.value = [];
};

const isCreatingNew = computed(() => selectedRole.value === null && roleForm.id === null && roleForm.name === '');

const saveRole = async () => {
  if (!roleFormRef.value) return;

  await roleFormRef.value.validate(async (valid) => {
    if (!valid) return;

    try {
      if (roleForm.id) {
        await updateRole(roleForm.id, {
          name: roleForm.name,
          description: roleForm.description,
          level: roleForm.level,
        });
        ElMessage.success('角色更新成功');
        await loadData();
        await selectRole(roles.value.find(r => r.id === roleForm.id)!);
      } else {
        const newRole = await createRole({
          name: roleForm.name,
          code: roleForm.code,
          description: roleForm.description,
          level: roleForm.level,
          is_system: roleForm.is_system,
          school_id: roleForm.school_id || undefined,
        });

        ElMessage.success('角色创建成功');
        await loadData();
        await selectRole(newRole);
      }
    } catch (error: unknown) {
      ElMessage.error(error.response?.data?.message || '保存失败');
    }
  });
};

const saveRolePermissions = async () => {
  if (!selectedRole.value) {
    ElMessage.warning('请先选择角色');
    return;
  }

  try {
    const currentPerms = await getRolePermissions(selectedRole.value.id);
    const currentPermIds = currentPerms.map((p: Permission) => p.id);

    const toAdd = rolePermissions.value.filter(id => !currentPermIds.includes(id));
    const toRemove = currentPermIds.filter((id: number) => !rolePermissions.value.includes(id));

    for (const permId of toAdd) {
      await assignPermissionToRole(selectedRole.value.id, permId);
    }

    for (const permId of toRemove) {
      await removePermissionFromRole(selectedRole.value.id, permId);
    }

    ElMessage.success('权限分配成功');
  } catch (error: unknown) {
    ElMessage.error(error.response?.data?.message || '权限分配失败');
  }
};

const handleDeleteRole = async (role: Role) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除角色 "${role.name}" 吗？`,
      '确认删除',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning',
      }
    );

    await deleteRole(role.id);
    ElMessage.success('角色删除成功');
    if (selectedRole.value?.id === role.id) {
      selectedRole.value = null;
    }
    await loadData();
  } catch (error: unknown) {
    if (error !== 'cancel') {
      ElMessage.error(error.response?.data?.message || '删除失败');
    }
  }
};

const assignUserRole = async () => {
  if (!userRoleForm.user_id || !userRoleForm.role_id) {
    ElMessage.warning('请选择用户和角色');
    return;
  }

  try {
    await assignRoleToUser(
      userRoleForm.user_id,
      userRoleForm.role_id,
      userRoleForm.organization_id || undefined,
      userRoleForm.organization_id ? 'organization' : undefined
    );
    ElMessage.success('角色分配成功');
    Object.assign(userRoleForm, {
      user_id: null,
      role_id: null,
      organization_id: null,
    });
  } catch (error: unknown) {
    ElMessage.error(error.response?.data?.message || '角色分配失败');
  }
};

onMounted(() => {
  loadData();
});
</script>

<template>
  <div class="page-container">
    <div class="content-section">
      <h2>权限管理</h2>
      <p class="subtitle">管理系统角色、权限和用户角色分配</p>

      <el-skeleton :rows="5" animated v-if="loading" />

      <template v-else>
        <!-- 统计概览 -->
        <div class="stat-row">
          <div class="stat-card">
            <span class="stat-accent" style="background: #f59e0b"></span>
            <div class="stat-info">
              <span class="stat-value">{{ totalMembers }}</span>
              <span class="stat-label">学校成员总数</span>
            </div>
          </div>
          <div class="stat-card">
            <span class="stat-accent" style="background: #8b5cf6"></span>
            <div class="stat-info">
              <span class="stat-value">{{ permissions.length }}</span>
              <span class="stat-label">权限总数</span>
            </div>
          </div>
          <div class="stat-card">
            <span class="stat-accent" style="background: #10b981"></span>
            <div class="stat-info">
              <span class="stat-value">{{ groupedPermissionKeys.length }}</span>
              <span class="stat-label">资源类型</span>
            </div>
          </div>
        </div>

        <!-- 角色管理 + 权限分配 双列 -->
        <div class="main-grid">
          <!-- 左列：角色列表 -->
          <div class="pm-card">
            <div class="pm-card-header">
              <div class="pm-title-wrap">
                <span class="pm-accent" style="background: #f59e0b"></span>
                <h3 class="pm-title">角色管理</h3>
                <span class="pm-count-badge">{{ roles.length }}</span>
              </div>
              <button class="pm-link-btn primary" @click="handleCreateRole">+ 新建角色</button>
            </div>
            <div class="role-list">
              <div
                v-for="role in roles"
                :key="role.id"
                class="role-item"
                :class="{ active: selectedRole?.id === role.id }"
                @click="selectRole(role)"
              >
                <div class="role-color-bar" :style="{ background: role.is_system ? '#6366f1' : '#10b981' }"></div>
                <div class="role-body">
                  <div class="role-top">
                    <span class="role-name">{{ role.name }}</span>
                    <el-button
                      type="danger"
                      size="small"
                      text
                      @click.stop="handleDeleteRole(role)"
                      v-if="!role.is_system"
                      class="role-del-btn"
                    >删除</el-button>
                  </div>
                  <div class="role-meta">
                    <el-tag size="small" :type="role.is_system ? 'danger' : 'info'" effect="plain">
                      {{ role.is_system ? '系统' : '自定义' }}
                    </el-tag>
                    <el-tag size="small" type="warning" effect="plain">
                      {{ levelOptions.find(l => l.value === role.level)?.label || role.level }}
                    </el-tag>
                  </div>
                  <div class="role-description" v-if="role.description">{{ role.description }}</div>
                </div>
              </div>
            </div>
          </div>

          <!-- 右列：角色详情与权限分配 -->
          <div class="pm-card">
            <div class="pm-card-header">
              <div class="pm-title-wrap">
                <span class="pm-accent" style="background: #8b5cf6"></span>
                <h3 class="pm-title">角色详情与权限分配</h3>
              </div>
            </div>

            <div v-if="selectedRole || !isCreatingNew" class="role-detail">
              <el-form
                ref="roleFormRef"
                :model="roleForm"
                :rules="roleRules"
                label-width="90px"
                class="role-form"
              >
                <div class="form-grid">
                  <el-form-item label="角色名称" prop="name">
                    <el-input v-model="roleForm.name" :disabled="!!roleForm.id" placeholder="请输入角色名称" />
                  </el-form-item>
                  <el-form-item label="角色代码" prop="code">
                    <el-input v-model="roleForm.code" :disabled="!!roleForm.id" placeholder="请输入角色代码（唯一）" />
                  </el-form-item>
                  <el-form-item label="权限级别" prop="level">
                    <el-select v-model="roleForm.level" :disabled="!!roleForm.id" placeholder="请选择权限级别" style="width: 100%">
                      <el-option v-for="opt in levelOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
                    </el-select>
                  </el-form-item>
                  <el-form-item label="描述">
                    <el-input v-model="roleForm.description" type="textarea" :rows="2" placeholder="请输入角色描述" />
                  </el-form-item>
                </div>
                <el-form-item style="margin-bottom: 0">
                  <el-button type="primary" @click="saveRole" size="default">
                    {{ roleForm.id ? '更新' : '创建' }}角色
                  </el-button>
                </el-form-item>
              </el-form>

              <div class="perm-assign" v-if="selectedRole">
                <div class="perm-assign-head">
                  <span class="perm-assign-label">权限分配</span>
                  <el-button type="primary" size="small" @click="saveRolePermissions">保存权限</el-button>
                </div>
                <div class="perm-grid">
                  <div
                    v-for="(perms, resource, idx) in groupedPermissions"
                    :key="resource"
                    class="perm-group-card"
                  >
                    <div class="perm-group-bar" :style="{ background: permGroupColors[Number(idx) % permGroupColors.length] }"></div>
                    <div class="perm-group-body">
                      <div class="perm-group-name">{{ resource }}</div>
                      <el-checkbox-group v-model="rolePermissions" class="perm-checks">
                        <el-checkbox
                          v-for="perm in perms"
                          :key="perm.id"
                          :label="perm.id"
                          class="perm-check-item"
                        >
                          <span class="perm-name">{{ perm.name }}</span>
                          <span class="perm-code">{{ perm.code }}</span>
                        </el-checkbox>
                      </el-checkbox-group>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div v-else class="empty-state">
              <div class="empty-inner">
                <p>请从左侧选择角色或创建新角色</p>
              </div>
            </div>
          </div>
        </div>

        <!-- 用户管理 全宽卡片 -->
        <div class="pm-card user-section">
          <div class="pm-card-header">
            <div class="pm-title-wrap">
              <span class="pm-accent" style="background: #10b981"></span>
              <h3 class="pm-title">用户管理</h3>
            </div>
          </div>
          <div class="user-search-bar">
            <el-input
              v-model="userSearchKeyword"
              placeholder="搜索姓名或邮箱..."
              clearable
              @keydown.enter="searchUsers"
              size="default"
            />
            <el-button type="primary" @click="searchUsers" size="default">搜索</el-button>
          </div>
          <div v-loading="userListLoading">
            <div v-if="userList.length === 0" class="user-empty">
              <p>输入关键词搜索用户</p>
            </div>
            <div v-else class="user-grid">
              <div v-for="u in userList" :key="u.id" class="user-card">
                <div class="user-info">
                  <span class="user-avatar">{{ (u.name || '?')[0] }}</span>
                  <div class="user-text">
                    <span class="user-name">{{ u.name }}</span>
                    <span class="user-email">{{ u.email }}</span>
                  </div>
                </div>
                <el-select
                  :model-value="u.role"
                  @change="(val: string) => changeUserRole(u.id, val)"
                  size="small"
                  style="width: 120px"
                >
                  <el-option v-for="opt in roleOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
                </el-select>
              </div>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
/* ===== 统计概览 ===== */
.stat-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  margin-bottom: 14px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 14px;
  background: #fff;
  border: 1px solid #e6ebf2;
  border-radius: 10px;
  padding: 16px 18px;
  transition: all 0.2s;
}
.stat-card:hover {
  border-color: #c7d2fe;
  transform: translateY(-2px);
  box-shadow: 0 3px 12px rgba(99, 102, 241, 0.06);
}

.stat-accent {
  display: block;
  width: 3px;
  height: 32px;
  border-radius: 2px;
  flex-shrink: 0;
}

.stat-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stat-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #1e293b;
  line-height: 1.2;
}

.stat-label {
  font-size: 12px;
  color: #94a3b8;
}

/* ===== 双列主体 ===== */
.main-grid {
  display: grid;
  grid-template-columns: 340px 1fr;
  gap: 14px;
  margin-bottom: 14px;
}

/* ===== 通用卡片容器 ===== */
.pm-card {
  background: #fff;
  border: 1px solid #e6ebf2;
  border-radius: 10px;
  padding: 16px 18px;
}

.pm-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.pm-title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pm-accent {
  display: inline-block;
  width: 3px;
  height: 14px;
  border-radius: 2px;
  flex-shrink: 0;
}

.pm-title {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: #1e293b;
}

.pm-count-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: 10px;
  background: #f59e0b;
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
}

.pm-link-btn {
  border: none;
  background: none;
  font-size: 12px;
  cursor: pointer;
  padding: 4px 10px;
  border-radius: 6px;
  transition: all 0.15s;
  font-weight: 500;
}
.pm-link-btn.primary {
  color: #6366f1;
  background: #eef2ff;
}
.pm-link-btn.primary:hover {
  background: #e0e7ff;
  color: #4f46e5;
}

/* ===== 角色列表 ===== */
.role-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: calc(100vh - 320px);
  overflow-y: auto;
}

.role-item {
  display: flex;
  border: 1px solid #e6ebf2;
  border-radius: 10px;
  overflow: hidden;
  cursor: pointer;
  transition: all 0.2s;
  background: #fff;
}
.role-item:hover {
  border-color: #c7d2fe;
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.06);
}
.role-item.active {
  border-color: #818cf8;
  background: #f5f3ff;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.1);
}

.role-color-bar {
  width: 4px;
  flex-shrink: 0;
}

.role-body {
  flex: 1;
  padding: 12px 14px;
  min-width: 0;
}

.role-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.role-name {
  font-size: 13.5px;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.role-del-btn {
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.15s;
}
.role-item:hover .role-del-btn { opacity: 1; }

.role-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.role-description {
  font-size: 12px;
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ===== 角色详情 ===== */
.role-detail {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.role-form {
  padding-bottom: 16px;
  border-bottom: 1px solid #f1f5f9;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 20px;
}

/* ===== 权限分配 ===== */
.perm-assign-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.perm-assign-label {
  font-size: 13.5px;
  font-weight: 600;
  color: #1e293b;
}

.perm-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}

.perm-group-card {
  border: 1px solid #e6ebf2;
  border-radius: 10px;
  overflow: hidden;
  transition: all 0.2s;
}
.perm-group-card:hover {
  border-color: #c7d2fe;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.05);
}

.perm-group-bar {
  height: 4px;
  width: 100%;
}

.perm-group-body {
  padding: 12px 14px;
}

.perm-group-name {
  font-size: 13px;
  font-weight: 600;
  color: #334155;
  margin-bottom: 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid #f1f5f9;
}

.perm-checks {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.perm-check-item {
  margin: 0 !important;
  height: auto !important;
}

.perm-name {
  font-size: 12.5px;
  font-weight: 500;
  color: #1e293b;
}

.perm-code {
  font-size: 11px;
  color: #94a3b8;
  margin-left: 4px;
}

/* ===== 空状态 ===== */
.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 300px;
}

.empty-inner {
  text-align: center;
}

.empty-inner p {
  color: #94a3b8;
  font-size: 13px;
  margin: 0;
}

/* ===== 用户管理 ===== */
.user-section {
  margin-bottom: 14px;
}

.user-search-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
  max-width: 400px;
}

.user-empty {
  text-align: center;
  padding: 24px 0;
}
.user-empty p {
  color: #94a3b8;
  font-size: 12.5px;
  margin: 0;
}

.user-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 10px;
}

.user-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border: 1px solid #e6ebf2;
  border-radius: 10px;
  transition: all 0.2s;
}
.user-card:hover {
  border-color: #c7d2fe;
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.05);
}

.user-info {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex: 1;
}

.user-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
  flex-shrink: 0;
}

.user-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.user-name {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-email {
  font-size: 11.5px;
  color: #94a3b8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ===== 响应式 ===== */
@media (max-width: 1200px) {
  .main-grid {
    grid-template-columns: 300px 1fr;
  }
}

@media (max-width: 1024px) {
  .stat-row { grid-template-columns: repeat(3, 1fr); }
  .main-grid { grid-template-columns: 1fr; }
  .role-list { max-height: none; }
}

@media (max-width: 768px) {
  .stat-row { grid-template-columns: 1fr; }
  .form-grid { grid-template-columns: 1fr; }
  .perm-grid { grid-template-columns: 1fr; }
  .user-grid { grid-template-columns: 1fr; }
}
</style>
