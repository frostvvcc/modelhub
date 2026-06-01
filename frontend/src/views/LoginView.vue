<!-- views/LoginView.vue -->
<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '../stores/user'
import { ElNotification } from 'element-plus'

const router = useRouter()
const userStore = useUserStore()

const account = ref('')
const password = ref('')
const rememberMe = ref(false)
const loading = ref(false)

const handleLogin = async () => {
  if (!account.value || !password.value) {
    ElNotification({
      title: '错误',
      message: '请输入学号/工号和密码',
      type: 'error'
    })
    return
  }

  loading.value = true
  try {
    const success = await userStore.login(account.value, password.value)
    if (success) {
      // 检查是否有重定向路径
      const redirect = router.currentRoute.value.query.redirect
      if (typeof redirect === 'string') {
        router.push(redirect)
      } else {
        router.push('/')
      }
    }
  } catch (error) {
  } finally {
    loading.value = false
  }
}

const goToRegister = () => {
  router.push('/register')
}
</script>

<template>
  <div class="auth-container">
    <div class="auth-card">
      <div class="auth-header">
        <ElAvatar :size="64" src="/ModelHub.png" />
        <h2>欢迎回来</h2>
        <p>登录以继续使用 ModelHub</p>
      </div>
      
      <div class="auth-form">
        <div class="form-group">
          <label>学号 / 工号</label>
          <ElInput
            v-model="account"
            placeholder="请输入学号或工号"
            size="large"
          />
        </div>
        
        <div class="form-group">
          <label>密码</label>
          <ElInput
            v-model="password"
            type="password"
            placeholder="请输入密码"
            size="large"
            show-password
          />
        </div>
        
        <div class="form-options">
          <ElCheckbox v-model="rememberMe">记住我</ElCheckbox>
          <span class="forgot-password muted">忘记密码请联系管理员</span>
        </div>
        
        <ElButton
          type="primary"
          size="large"
          @click="handleLogin"
          :loading="loading"
          class="auth-button"
        >
          登录
        </ElButton>
        
        <div class="auth-divider">
          <span>或</span>
        </div>
        
        <ElButton
          plain
          size="large"
          @click="goToRegister"
          class="auth-button"
        >
          注册新账号
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
  min-height: calc(100vh - 160px);
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

.forgot-password.muted {
  color: #909399;
  cursor: default;
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
</style>
