<!-- views/RegisterView.vue -->
<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '../stores/user'
import { ElNotification } from 'element-plus'
import api from '../utils/api'
import { getDepartments, getMajors } from '../api/organization'

const router = useRouter()
const userStore = useUserStore()

const name = ref('')
const email = ref('')
const employeeId = ref('')
const password = ref('')
const confirmPassword = ref('')
const selectedRole = ref('student')
const selectedSchool = ref<number | undefined>(undefined)
const selectedOrg = ref<number | undefined>(undefined)
const selectedMajor = ref<number | undefined>(undefined)
const schools = ref<{id: number, name: string, code: string}[]>([])
const departments = ref<{id: number, name: string, code: string, type: string}[]>([])
const majors = ref<{id: number, name: string, code: string, type: string}[]>([])
const loadingDepts = ref(false)
const loadingMajors = ref(false)
const studentId = ref('')
const agreeTerms = ref(false)
const loading = ref(false)

const detectedYear = computed(() => {
  if (studentId.value.length >= 4 && /^\d{4}/.test(studentId.value)) {
    const year = parseInt(studentId.value.substring(0, 4))
    const currentYear = new Date().getFullYear()
    if (year >= 2000 && year <= currentYear) return year
  }
  return null
})

onMounted(async () => {
  try {
    const res = await api.get('/organization/schools')
    schools.value = res.data.data || []
  } catch {
    // 学校列表加载失败不阻塞注册
  }
})

watch(selectedSchool, async (schoolId) => {
  selectedOrg.value = undefined
  selectedMajor.value = undefined
  departments.value = []
  majors.value = []
  if (!schoolId) return
  loadingDepts.value = true
  try {
    departments.value = await getDepartments(schoolId)
  } catch {
    departments.value = []
  } finally {
    loadingDepts.value = false
  }
})

const loadMajors = async () => {
  selectedMajor.value = undefined
  majors.value = []
  if (!selectedOrg.value || selectedRole.value !== 'student') return
  loadingMajors.value = true
  try {
    majors.value = await getMajors(selectedOrg.value)
  } catch {
    majors.value = []
  } finally {
    loadingMajors.value = false
  }
}

watch(selectedOrg, () => { loadMajors() })
watch(selectedRole, () => { loadMajors() })

const handleRegister = async () => {
  if (!name.value || !password.value || !confirmPassword.value) {
    ElNotification({ title: '错误', message: '请填写姓名和密码', type: 'error' })
    return
  }

  if (selectedRole.value === 'student') {
    if (!studentId.value.trim()) {
      ElNotification({ title: '错误', message: '学生注册请填写学号', type: 'error' })
      return
    }
    if (!detectedYear.value) {
      ElNotification({ title: '错误', message: '学号格式不正确，前4位应为入学年份', type: 'error' })
      return
    }
  }

  if (selectedRole.value === 'teacher' && !employeeId.value.trim()) {
    ElNotification({ title: '错误', message: '教师注册请填写工号', type: 'error' })
    return
  }

  if (password.value.length < 8) {
    ElNotification({ title: '错误', message: '密码长度不能少于8位', type: 'error' })
    return
  }

  if (password.value !== confirmPassword.value) {
    ElNotification({ title: '错误', message: '两次输入的密码不一致', type: 'error' })
    return
  }

  if (!agreeTerms.value) {
    ElNotification({ title: '错误', message: '请同意服务条款和隐私政策', type: 'error' })
    return
  }

  loading.value = true
  try {
    const orgId = selectedRole.value === 'student' && selectedMajor.value
      ? selectedMajor.value
      : selectedOrg.value
    await userStore.register(name.value, password.value, {
      role: selectedRole.value,
      schoolId: selectedSchool.value,
      organizationId: orgId,
      studentId: selectedRole.value === 'student' ? studentId.value.trim() : undefined,
      employeeId: selectedRole.value === 'teacher' ? employeeId.value.trim() : undefined,
      email: email.value.trim() || undefined,
    })
  } catch (error) {
    // register 方法内部已处理通知
  } finally {
    loading.value = false
  }
}

const goToLogin = () => {
  router.push('/login')
}
</script>

<template>
  <div class="auth-container">
    <div class="auth-card">
      <div class="auth-header">
        <ElAvatar :size="64" src="/ModelHub.png" />
        <h2>创建账号</h2>
        <p>加入我们的平台</p>
      </div>
      
      <div class="auth-form">
        <div class="form-group">
          <label>姓名</label>
          <ElInput
            v-model="name"
            placeholder="请输入您的姓名"
            size="large"
            required
          />
        </div>
        
        <div class="form-group">
          <label>密码</label>
          <ElInput
            v-model="password"
            type="password"
            placeholder="至少8位字符"
            size="large"
            show-password
            required
          />
        </div>
        
        <div class="form-group">
          <label>确认密码</label>
          <ElInput
            v-model="confirmPassword"
            type="password"
            placeholder="请再次输入密码"
            size="large"
            show-password
            required
          />
        </div>

        <div class="form-group">
          <label>我的身份</label>
          <ElSelect v-model="selectedRole" size="large" style="width: 100%">
            <ElOption label="学生" value="student" />
            <ElOption label="教师" value="teacher" />
          </ElSelect>
        </div>

        <div class="form-group" v-if="selectedRole === 'student'">
          <label>学号</label>
          <ElInput
            v-model="studentId"
            placeholder="请输入学号（前4位为入学年份）"
            size="large"
            maxlength="20"
          />
          <div class="year-hint" v-if="detectedYear">
            已识别为 <strong>{{ detectedYear }} 级</strong>
          </div>
          <div class="year-hint year-error" v-else-if="studentId.length >= 4">
            无法识别入学年份，请检查学号
          </div>
        </div>

        <div class="form-group" v-if="selectedRole === 'teacher'">
          <label>工号</label>
          <ElInput
            v-model="employeeId"
            placeholder="请输入工号"
            size="large"
            maxlength="20"
          />
        </div>

        <div class="form-group">
          <label>邮箱 <span class="optional-hint">（可选）</span></label>
          <ElInput
            v-model="email"
            placeholder="请输入邮箱"
            size="large"
          />
        </div>

        <div class="form-group">
          <label>所属组织 <span class="optional-hint">（可选）</span></label>
          <div class="org-cascading">
            <ElSelect
              v-model="selectedSchool"
              size="large"
              style="width: 100%"
              placeholder="请选择学校"
              clearable
              filterable
            >
              <ElOption
                v-for="school in schools"
                :key="school.id"
                :label="school.name"
                :value="school.id"
              />
            </ElSelect>
            <ElSelect
              v-if="selectedSchool"
              v-model="selectedOrg"
              size="large"
              style="width: 100%"
              placeholder="请选择学院/部门"
              clearable
              filterable
              :loading="loadingDepts"
            >
              <ElOption
                v-for="dept in departments"
                :key="dept.id"
                :label="dept.name"
                :value="dept.id"
              />
            </ElSelect>
            <ElSelect
              v-if="selectedOrg && selectedRole === 'student'"
              v-model="selectedMajor"
              size="large"
              style="width: 100%"
              placeholder="请选择专业"
              clearable
              filterable
              :loading="loadingMajors"
              no-data-text="该学院下暂无专业，请联系管理员添加"
            >
              <ElOption
                v-for="major in majors"
                :key="major.id"
                :label="major.name"
                :value="major.id"
              />
            </ElSelect>
          </div>
        </div>

        <div class="form-options">
          <ElCheckbox v-model="agreeTerms">
            我同意 <span class="terms-link">服务条款</span> 和 <span class="terms-link">隐私政策</span>
          </ElCheckbox>
        </div>
        
        <ElButton
          type="primary"
          size="large"
          @click="handleRegister"
          :loading="loading"
          class="auth-button"
        >
          注册
        </ElButton>
        
        <div class="auth-divider">
          <span>已有账号?</span>
        </div>
        
        <ElButton
          plain
          size="large"
          @click="goToLogin"
          class="auth-button"
        >
          登录现有账号
        </ElButton>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 原有样式... */
.auth-container {
  flex: 1;
  display: flex;
  justify-content: center;
  align-items: center;
  /* min-height: 100vh; */
  height: calc(var(--vh, 1vh) * 100 - 280px);
  padding: 2rem;
}

.auth-card {
  width: 100%;
  max-width: 600px;
  background: white;
  border-radius: 12px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
  overflow: hidden;
  padding: 2.5rem;
}

.auth-header {
  text-align: center;
  margin-bottom: 2rem;
}

.auth-header h2 {
  margin: 1rem 0 0.5rem;
  font-size: 1.5rem;
  color: #303133;
}

.auth-header p {
  margin: 0;
  color: #909399;
  font-size: 0.95rem;
}

.form-row {
  display: flex;
  gap: 12px;
}

.form-half {
  flex: 1;
  min-width: 0;
}

.optional-hint {
  color: #a1a1aa;
  font-weight: 400;
  font-size: 0.8rem;
}

.org-cascading {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.form-group {
  margin-bottom: 1.5rem;
}

.form-group label {
  display: block;
  margin-bottom: 0.5rem;
  font-size: 0.9rem;
  color: #606266;
  font-weight: 500;
  text-align: left;
}

.form-options {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
}

.forgot-password {
  color: #4277b9;
  text-decoration: none;
  font-size: 0.9rem;
}

.forgot-password:hover {
  text-decoration: underline;
}

.auth-button {
  width: 100%;
  /* margin-bottom: 1rem; */
}

.auth-divider {
  position: relative;
  text-align: center;
  /* margin: 1.5rem 0; */
}

.auth-divider span {
  position: relative;
  padding: 0 1rem;
  background: white;
  color: #909399;
  font-size: 0.9rem;
}

.auth-divider:before {
  content: '';
  position: absolute;
  top: 50%;
  left: 0;
  right: 0;
  height: 1px;
  background: #dcdfe6;
  z-index: -1;
}

/* 新增警告样式 */
.auth-alert {
  margin-top: 1rem;
  max-width: 100%;
}

:deep(.el-alert) {
  padding: 8px 16px;
}
.terms-link {
  color: #4277b9;
  text-decoration: none;
}

.terms-link:hover {
  text-decoration: underline;
}

.year-hint {
  margin-top: 6px;
  font-size: 12px;
  color: #67c23a;
}

.year-hint strong {
  font-weight: 600;
}

.year-error {
  color: #f56c6c;
}
</style>
