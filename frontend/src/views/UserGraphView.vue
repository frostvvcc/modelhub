<script setup lang="ts">
import { ref, onMounted, computed, reactive } from 'vue'
import { ElNotification } from 'element-plus'
import { getUserInfo, uploadAvatar, updateProfile, changePassword } from '../api/user'
import { useUserStore } from '../stores/user'
import type { Organization } from '../api/organization'

interface UserInfo {
  id: number
  name: string
  email: string
  type: string
  role: string
  avatar: string
  describe: string | null
  school_id: number | null
  student_id: string | null
  employee_id: string | null
  phone: string | null
  enrollment_year: number | null
  status: string
  create_at: string
  update_at: string
}

const userInfo = ref<UserInfo | null>(null)
const userStore = useUserStore()

const organizations = ref<Organization[]>([])

const activeTab = ref('profile')
const profileEditing = ref(false)

const roleMap: Record<string, string> = {
  admin: '管理员',
  teacher: '教师',
  student: '学生',
}

const orgTypeMap: Record<string, string> = {
  school: '学校',
  college: '学院',
  department: '系',
  class: '班级',
}

const orgRoleMap: Record<string, string> = {
  admin: '管理员',
  member: '成员',
  teacher: '教师',
  student: '学生',
}

// ===== 个人资料编辑 =====
const profileForm = reactive({
  name: '',
  describe: '',
  phone: '',
  student_id: '',
  employee_id: '',
})
const profileSaving = ref(false)

function syncProfileForm() {
  if (!userInfo.value) return
  profileForm.name = userInfo.value.name || ''
  profileForm.describe = userInfo.value.describe || ''
  profileForm.phone = userInfo.value.phone || ''
  profileForm.student_id = userInfo.value.student_id || ''
  profileForm.employee_id = userInfo.value.employee_id || ''
}

function startEditProfile() {
  syncProfileForm()
  profileEditing.value = true
}

function cancelEditProfile() {
  profileEditing.value = false
}

async function saveProfile() {
  profileSaving.value = true
  try {
    const result = await updateProfile({
      name: profileForm.name || undefined,
      describe: profileForm.describe || undefined,
      phone: profileForm.phone || undefined,
      student_id: profileForm.student_id || undefined,
      employee_id: profileForm.employee_id || undefined,
    })
    if (userInfo.value) {
      Object.assign(userInfo.value, result)
    }
    if (userStore.user && result.name) {
      userStore.user.name = result.name
    }
    profileEditing.value = false
    ElNotification.success({ title: '成功', message: '个人资料已更新' })
  } catch (error: any) {
    ElNotification.error({ title: '错误', message: error.response?.data?.message || '更新失败' })
  } finally {
    profileSaving.value = false
  }
}

// ===== 头像上传 =====
const avatarInput = ref<HTMLInputElement | null>(null)

function changeAvatar() {
  avatarInput.value?.click()
}

async function handleAvatarUpload(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return

  try {
    const formData = new FormData()
    formData.append('file', file)
    const response = await uploadAvatar(formData)
    userStore.updateUserAvatar(response)
    if (userInfo.value) {
      userInfo.value.avatar = userStore.user?.avatar ?? userInfo.value.avatar
    }
    ElNotification.success({ title: '成功', message: '头像上传成功' })
  } catch {
    if (userInfo.value) {
      userInfo.value.avatar = userStore.user?.avatar ?? userInfo.value.avatar
    }
    ElNotification.error({ title: '错误', message: '头像上传失败，请重试' })
  }
}

// ===== 修改密码 =====
const passwordEditing = ref(false)
const passwordForm = reactive({
  oldPassword: '',
  newPassword: '',
  confirmPassword: '',
})
const passwordSaving = ref(false)

function cancelPasswordEdit() {
  passwordEditing.value = false
  passwordForm.oldPassword = ''
  passwordForm.newPassword = ''
  passwordForm.confirmPassword = ''
}

async function savePassword() {
  if (!passwordForm.oldPassword || !passwordForm.newPassword) {
    ElNotification.warning({ title: '提示', message: '请填写完整密码信息' })
    return
  }
  if (passwordForm.newPassword.length < 6) {
    ElNotification.warning({ title: '提示', message: '新密码长度不能少于6位' })
    return
  }
  if (passwordForm.newPassword !== passwordForm.confirmPassword) {
    ElNotification.warning({ title: '提示', message: '两次输入的新密码不一致' })
    return
  }

  passwordSaving.value = true
  try {
    await changePassword(passwordForm.oldPassword, passwordForm.newPassword)
    ElNotification.success({ title: '成功', message: '密码修改成功' })
    cancelPasswordEdit()
  } catch (error: any) {
    ElNotification.error({ title: '错误', message: error.response?.data?.message || '密码修改失败' })
  } finally {
    passwordSaving.value = false
  }
}

// ===== 工具函数 =====
const formatDate = (dateStr: string) => {
  return new Date(dateStr).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const statusMap: Record<string, { label: string; class: string }> = {
  active: { label: '正常', class: 'status-active' },
  inactive: { label: '未激活', class: 'status-inactive' },
  suspended: { label: '已停用', class: 'status-suspended' },
}

// ===== 初始化 =====
onMounted(async () => {
  try {
    const res = await getUserInfo()
    userInfo.value = res.user_info
    if (userInfo.value) {
      userStore.updateUserAvatar(userInfo.value.avatar)
      userInfo.value.avatar = userStore.user?.avatar ?? userInfo.value.avatar
    }
    organizations.value = res.organizations || []
  } catch (error: any) {
    ElNotification.error({
      title: '错误',
      message: error.message || '获取数据失败',
      duration: 5000,
    })
  }
})
</script>

<template>
  <div class="page-container">
    <div class="content-section">
      <!-- 用户信息区域 -->
      <div class="user-info-section">
        <div class="user-card">
          <div class="avatar-container">
            <img :src="userInfo?.avatar" class="avatar-img" :alt="userInfo?.name?.charAt(0) || 'U'" />
            <button class="change-avatar-btn" @click="changeAvatar">更换头像</button>
            <input type="file" accept="image/*" @change="handleAvatarUpload" hidden ref="avatarInput" />
          </div>
          <div class="user-details">
            <h2>{{ userInfo?.name || '未命名用户' }}</h2>
            <p class="email">{{ userInfo?.email || '未设置邮箱' }}</p>
            <div class="user-meta">
              <span class="badge">{{ roleMap[userInfo?.role ?? ''] || '未设置角色' }}</span>
              <span class="join-date">加入时间: {{ userInfo?.create_at ? formatDate(userInfo.create_at) : '未知' }}</span>
            </div>
            <p class="description">{{ userInfo?.describe || '该用户暂无描述信息' }}</p>
          </div>
        </div>
      </div>

      <!-- 标签页区域 -->
      <div class="tabs-container">
        <div class="tabs">
          <button
            :class="['tab', { active: activeTab === 'profile' }]"
            @click="activeTab = 'profile'; profileEditing = false"
          >
            <el-icon><User /></el-icon> 个人资料
          </button>
          <button
            :class="['tab', { active: activeTab === 'security' }]"
            @click="activeTab = 'security'; passwordEditing = false"
          >
            <el-icon><Lock /></el-icon> 账号安全
          </button>
          <button
            :class="['tab', { active: activeTab === 'organizations' }]"
            @click="activeTab = 'organizations'"
          >
            <el-icon><OfficeBuilding /></el-icon> 我的组织
            <span class="count-badge">{{ organizations.length }}</span>
          </button>
        </div>

        <!-- Tab: 个人资料 -->
        <div class="tab-content" v-if="activeTab === 'profile'">
          <!-- 只读模式 -->
          <div v-if="!profileEditing" class="profile-view">
            <div class="info-grid profile-grid">
              <div class="info-item">
                <span class="info-label">姓名</span>
                <span class="info-value">{{ userInfo?.name || '-' }}</span>
              </div>
              <div class="info-item">
                <span class="info-label">邮箱</span>
                <span class="info-value">{{ userInfo?.email || '-' }}</span>
              </div>
              <div class="info-item">
                <span class="info-label">手机号</span>
                <span class="info-value">{{ userInfo?.phone || '未设置' }}</span>
              </div>
              <div class="info-item">
                <span class="info-label">角色</span>
                <span class="info-value">{{ roleMap[userInfo?.role ?? ''] || '-' }}</span>
              </div>
              <div class="info-item" v-if="userInfo?.role === 'student'">
                <span class="info-label">学号</span>
                <span class="info-value">{{ userInfo?.student_id || '未设置' }}</span>
              </div>
              <div class="info-item" v-if="userInfo?.role === 'student' && userInfo?.enrollment_year">
                <span class="info-label">年级</span>
                <span class="info-value">{{ userInfo.enrollment_year }} 级</span>
              </div>
              <div class="info-item" v-if="userInfo?.role === 'teacher' || userInfo?.role === 'admin'">
                <span class="info-label">工号</span>
                <span class="info-value">{{ userInfo?.employee_id || '未设置' }}</span>
              </div>
            </div>
            <div class="info-item" style="margin-top: 14px;">
              <span class="info-label">个人简介</span>
              <span class="info-value">{{ userInfo?.describe || '暂无简介' }}</span>
            </div>
            <div class="form-actions" style="margin-top: 20px;">
              <button class="btn-primary" @click="startEditProfile">
                <el-icon><Edit /></el-icon> 编辑资料
              </button>
            </div>
          </div>

          <!-- 编辑模式 -->
          <div v-else class="form-section">
            <div class="form-group">
              <label class="form-label">姓名</label>
              <input v-model="profileForm.name" class="form-input" placeholder="请输入姓名" />
            </div>
            <div class="form-group">
              <label class="form-label">个人简介</label>
              <textarea v-model="profileForm.describe" class="form-textarea" placeholder="介绍一下自己吧" rows="3" />
            </div>
            <div class="form-group">
              <label class="form-label">手机号</label>
              <input v-model="profileForm.phone" class="form-input" placeholder="请输入手机号" />
            </div>
            <div class="form-group" v-if="userInfo?.role === 'student'">
              <label class="form-label">学号</label>
              <input v-model="profileForm.student_id" class="form-input" placeholder="请输入学号" />
            </div>
            <div class="form-group" v-if="userInfo?.role === 'teacher' || userInfo?.role === 'admin'">
              <label class="form-label">工号</label>
              <input v-model="profileForm.employee_id" class="form-input" placeholder="请输入工号" />
            </div>
            <div class="form-actions">
              <button class="btn-primary" :disabled="profileSaving" @click="saveProfile">
                {{ profileSaving ? '保存中...' : '保存修改' }}
              </button>
              <button class="btn-secondary" @click="cancelEditProfile">取消</button>
            </div>
          </div>
        </div>

        <!-- Tab: 账号安全 -->
        <div class="tab-content" v-if="activeTab === 'security'">
          <div class="security-section">
            <!-- 账号状态 -->
            <div class="security-card">
              <h3 class="section-title">账号状态</h3>
              <div class="info-grid">
                <div class="info-item">
                  <span class="info-label">账号状态</span>
                  <span :class="['status-badge', statusMap[userInfo?.status ?? 'active']?.class]">
                    {{ statusMap[userInfo?.status ?? 'active']?.label }}
                  </span>
                </div>
                <div class="info-item">
                  <span class="info-label">邮箱</span>
                  <span class="info-value">{{ userInfo?.email || '-' }}</span>
                </div>
                <div class="info-item">
                  <span class="info-label">注册时间</span>
                  <span class="info-value">{{ userInfo?.create_at ? formatDate(userInfo.create_at) : '-' }}</span>
                </div>
                <div class="info-item">
                  <span class="info-label">最近更新</span>
                  <span class="info-value">{{ userInfo?.update_at ? formatDate(userInfo.update_at) : '-' }}</span>
                </div>
              </div>
            </div>

            <!-- 修改密码 -->
            <div class="security-card">
              <div class="security-card-header">
                <h3 class="section-title">登录密码</h3>
                <button v-if="!passwordEditing" class="btn-primary" @click="passwordEditing = true">
                  修改密码
                </button>
              </div>
              <p v-if="!passwordEditing" class="security-hint">定期修改密码可以保护账号安全</p>
              <div v-else class="form-section compact">
                <div class="form-group">
                  <label class="form-label">当前密码</label>
                  <input v-model="passwordForm.oldPassword" type="password" class="form-input" placeholder="请输入当前密码" />
                </div>
                <div class="form-group">
                  <label class="form-label">新密码</label>
                  <input v-model="passwordForm.newPassword" type="password" class="form-input" placeholder="请输入新密码（至少6位）" />
                </div>
                <div class="form-group">
                  <label class="form-label">确认新密码</label>
                  <input v-model="passwordForm.confirmPassword" type="password" class="form-input" placeholder="请再次输入新密码" />
                </div>
                <div class="form-actions">
                  <button class="btn-primary" :disabled="passwordSaving" @click="savePassword">
                    {{ passwordSaving ? '修改中...' : '确认修改' }}
                  </button>
                  <button class="btn-secondary" @click="cancelPasswordEdit">取消</button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Tab: 我的组织 -->
        <div class="tab-content" v-if="activeTab === 'organizations'">
          <div v-if="organizations.length === 0" class="empty-state">
            <el-icon class="empty-icon"><OfficeBuilding /></el-icon>
            <p>暂未加入任何组织</p>
          </div>
          <div v-else class="org-list">
            <div
              v-for="org in organizations"
              :key="org.id"
              class="org-card"
            >
              <div class="org-card-left">
                <div class="org-icon">
                  <el-icon v-if="org.type === 'school'"><School /></el-icon>
                  <el-icon v-else><OfficeBuilding /></el-icon>
                </div>
                <div class="org-info">
                  <h4>{{ org.name }}</h4>
                  <p class="org-meta-text">
                    <span class="org-type-tag">{{ orgTypeMap[org.type] || org.type }}</span>
                    <span v-if="org.description" class="org-desc">{{ org.description }}</span>
                  </p>
                </div>
              </div>
              <div class="org-card-right">
                <span class="org-status" :class="org.status === 'active' ? 'status-active' : 'status-inactive'">
                  {{ org.status === 'active' ? '正常' : '停用' }}
                </span>
              </div>
            </div>
          </div>
        </div>

      </div>
    </div>
  </div>
</template>

<style scoped>
.content-section {
  display: flex;
  flex-direction: column;
}

/* ===== 用户信息区域 ===== */
.user-info-section {
  padding: 20px;
  margin-bottom: 20px;
}

.user-card {
  display: flex;
  align-items: flex-start;
  gap: 24px;
}

.avatar-container {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.avatar-img {
  width: 88px;
  height: 88px;
  border-radius: 50%;
  object-fit: cover;
}

.change-avatar-btn {
  padding: 4px 10px;
  background-color: transparent;
  color: #64748b;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.78rem;
  transition: all 0.15s ease;
}

.change-avatar-btn:hover {
  background-color: #f1f5f9;
  border-color: #c7d2fe;
  color: #4f46e5;
}

.user-details {
  flex: 1;
}

.user-details h2 {
  margin: 0;
  font-size: 1.3rem;
  color: #1e293b;
  font-weight: 600;
}

.email {
  color: #94a3b8;
  margin: 2px 0 10px;
  font-size: 0.88rem;
}

.user-meta {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 10px;
}

.badge {
  background: #f1f5f9;
  color: #64748b;
  padding: 3px 10px;
  border-radius: 6px;
  font-size: 0.78rem;
  font-weight: 500;
  border: 1px solid #e2e8f0;
}

.join-date {
  color: #94a3b8;
  font-size: 0.82rem;
}

.description {
  color: #475569;
  line-height: 1.6;
  font-size: 0.88rem;
  background: #f8fafc;
  padding: 10px 14px;
  border-radius: 8px;
  border-left: 3px solid #c7d2fe;
}

/* ===== 标签页 ===== */
.tabs-container {
  border: 1px solid #e6ebf2;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  flex-grow: 1;
  display: flex;
  flex-direction: column;
}

.tabs {
  display: flex;
  border-bottom: 1px solid #e6ebf2;
}

.tab {
  flex: 1;
  padding: 12px 16px;
  background: none;
  border: none;
  cursor: pointer;
  font-size: 0.88rem;
  font-weight: 500;
  color: #64748b;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  transition: all 0.15s ease;
  position: relative;
}

.tab:hover {
  background: #f5f3ff;
  color: #4f46e5;
}

.tab.active {
  background: white;
  color: #4f46e5;
  border-bottom: 2px solid #4f46e5;
}

.tab.active .count-badge {
  background: #4f46e5;
  color: white;
}

.count-badge {
  background: #f1f5f9;
  color: #64748b;
  border-radius: 10px;
  padding: 1px 8px;
  font-size: 0.78rem;
}

.tab-content {
  padding: 20px;
  flex-grow: 1;
}

/* ===== 表单样式 ===== */
.form-section {
  max-width: 560px;
}

.form-section.compact {
  max-width: 420px;
}

.form-group {
  margin-bottom: 18px;
  flex: 1;
}

.form-label {
  display: block;
  font-size: 0.82rem;
  font-weight: 500;
  color: #475569;
  margin-bottom: 6px;
}

.form-input {
  width: 100%;
  padding: 9px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.88rem;
  color: #1e293b;
  background: #fff;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
  box-sizing: border-box;
}

.form-input:focus {
  outline: none;
  border-color: #818cf8;
  box-shadow: 0 0 0 3px rgba(129, 140, 248, 0.12);
}

.form-textarea {
  width: 100%;
  padding: 9px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.88rem;
  color: #1e293b;
  background: #fff;
  resize: vertical;
  font-family: inherit;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
  box-sizing: border-box;
}

.form-textarea:focus {
  outline: none;
  border-color: #818cf8;
  box-shadow: 0 0 0 3px rgba(129, 140, 248, 0.12);
}

.form-row {
  display: flex;
  gap: 16px;
}

.form-actions {
  display: flex;
  gap: 10px;
  margin-top: 8px;
}

.btn-primary {
  padding: 9px 22px;
  background: #4f46e5;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 0.88rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s ease;
}

.btn-primary:hover:not(:disabled) {
  background: #4338ca;
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-secondary {
  padding: 9px 22px;
  background: #f1f5f9;
  color: #475569;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 0.88rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.btn-secondary:hover {
  background: #e2e8f0;
}

/* ===== 安全页面 ===== */
.security-section {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.security-card {
  background: #fafbfd;
  border: 1px solid #eef0f4;
  border-radius: 10px;
  padding: 20px;
}

.section-title {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  color: #1e293b;
}

.security-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.security-hint {
  margin: 0;
  font-size: 0.84rem;
  color: #94a3b8;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 14px;
}

.info-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.info-label {
  font-size: 0.78rem;
  color: #94a3b8;
}

.info-value {
  font-size: 0.88rem;
  color: #334155;
  font-weight: 500;
}

.status-badge {
  display: inline-block;
  width: fit-content;
  padding: 2px 10px;
  border-radius: 6px;
  font-size: 0.8rem;
  font-weight: 500;
}

.status-active {
  background: #ecfdf5;
  color: #059669;
}

.status-inactive {
  background: #fef3c7;
  color: #d97706;
}

.status-suspended {
  background: #fef2f2;
  color: #dc2626;
}

/* ===== 组织列表 ===== */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  color: #94a3b8;
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 12px;
}

.empty-state p {
  font-size: 0.92rem;
}

.org-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.org-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 18px;
  background: #fff;
  border: 1px solid #eef0f4;
  border-radius: 10px;
}

.org-card-left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.org-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  background: #eef2ff;
  color: #6366f1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
}

.org-info h4 {
  margin: 0;
  font-size: 0.92rem;
  color: #1e293b;
  font-weight: 600;
}

.org-meta-text {
  margin: 4px 0 0;
  font-size: 0.8rem;
  color: #94a3b8;
  display: flex;
  align-items: center;
  gap: 8px;
}

.org-type-tag {
  background: #f1f5f9;
  padding: 1px 8px;
  border-radius: 4px;
  font-size: 0.75rem;
  color: #64748b;
}

.org-desc {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 300px;
}

.org-card-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.org-status {
  padding: 2px 10px;
  border-radius: 6px;
  font-size: 0.78rem;
  font-weight: 500;
}

/* ===== 个人资料只读 ===== */
.profile-view {
  max-width: 560px;
}

.profile-grid {
  grid-template-columns: repeat(2, 1fr);
}
</style>
