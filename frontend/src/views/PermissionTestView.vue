<template>
  <div class="permission-test-container">
    <div class="header-section">
      <h2>权限系统测试页面</h2>
      <p class="subtitle">测试简化后的权限系统功能</p>
    </div>

    <!-- 用户信息显示 -->
    <div class="user-info-section">
      <el-card class="user-card">
        <template #header>
          <div class="card-header">
            <span>当前用户信息</span>
          </div>
        </template>
        <div class="user-details">
          <div v-if="userStore.user" class="user-info">
            <div class="info-item">
              <span class="label">用户名:</span>
              <span class="value">{{ userStore.user.name }}</span>
            </div>
            <div class="info-item">
              <span class="label">邮箱:</span>
              <span class="value">{{ userStore.user.email }}</span>
            </div>
            <div class="info-item">
              <span class="label">角色:</span>
              <span class="value">{{ userStore.user.role || 'student' }}</span>
            </div>
            <div class="info-item">
              <span class="label">学校ID:</span>
              <span class="value">{{ userStore.user.school_id || '未设置' }}</span>
            </div>
          </div>
          <div v-else class="no-user">
            <el-alert title="未登录" type="warning" :closable="false">
              请先登录以测试权限功能
            </el-alert>
          </div>
        </div>
      </el-card>
    </div>

    <!-- 权限测试区域 -->
    <div class="permission-test-section">
      <el-card class="test-card">
        <template #header>
          <div class="card-header">
            <span>权限测试</span>
          </div>
        </template>
        
        <!-- 知识库权限测试 -->
        <div class="test-group">
          <h3>知识库权限测试</h3>
          <div class="test-cases">
            <div class="test-case" v-for="testCase in vectorDbTestCases" :key="testCase.id">
              <div class="case-header">
                <span class="case-title">{{ testCase.title }}</span>
                <el-button 
                  type="primary" 
                  size="small" 
                  @click="runVectorDbTest(testCase)"
                  :loading="testCase.loading"
                >
                  测试
                </el-button>
              </div>
              <div class="case-description">
                {{ testCase.description }}
              </div>
              <div class="case-result" v-if="testCase.result !== null">
                <el-tag :type="testCase.result ? 'success' : 'danger'">
                  {{ testCase.result ? '通过' : '拒绝' }}
                </el-tag>
                <span class="result-text">{{ testCase.resultText }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 文档操作权限测试 -->
        <div class="test-group">
          <h3>文档操作权限测试</h3>
          <div class="test-cases">
            <div class="test-case" v-for="testCase in documentTestCases" :key="testCase.id">
              <div class="case-header">
                <span class="case-title">{{ testCase.title }}</span>
                <el-button 
                  type="primary" 
                  size="small" 
                  @click="runDocumentTest(testCase)"
                  :loading="testCase.loading"
                >
                  测试
                </el-button>
              </div>
              <div class="case-description">
                {{ testCase.description }}
              </div>
              <div class="case-result" v-if="testCase.result !== null">
                <el-tag :type="testCase.result ? 'success' : 'danger'">
                  {{ testCase.result ? '通过' : '拒绝' }}
                </el-tag>
                <span class="result-text">{{ testCase.resultText }}</span>
              </div>
            </div>
          </div>
        </div>
      </el-card>
    </div>

    <!-- 权限说明 -->
    <div class="permission-explanation-section">
      <el-card class="explanation-card">
        <template #header>
          <div class="card-header">
            <span>权限系统说明</span>
          </div>
        </template>
        <div class="explanation-content">
          <h3>简化权限系统规则</h3>
          <ul>
            <li><strong>管理员 (admin)</strong>: 拥有所有权限</li>
            <li><strong>教师 (teacher)</strong>: 可以访问公开和教师知识库，可以上传文档到公开和教师知识库</li>
            <li><strong>学生 (student)</strong>: 只能访问公开知识库，只能上传文档到公开知识库</li>
          </ul>
          
          <h3>知识库权限范围</h3>
          <ul>
            <li><strong>公开 (public)</strong>: 所有用户都可以访问</li>
            <li><strong>教师 (teacher)</strong>: 只有教师和管理员可以访问</li>
            <li><strong>私有 (private)</strong>: 只有创建者和管理员可以访问</li>
          </ul>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '../stores/user'

const userStore = useUserStore()

// 知识库权限测试用例
const vectorDbTestCases = reactive([
  {
    id: 1,
    title: '学生访问公开知识库',
    description: '测试学生角色是否可以访问公开知识库',
    scope: 'public',
    operation: 'read',
    userRole: 'student',
    result: null,
    resultText: '',
    loading: false
  },
  {
    id: 2,
    title: '学生访问教师知识库',
    description: '测试学生角色是否可以访问教师知识库',
    scope: 'teacher',
    operation: 'read',
    userRole: 'student',
    result: null,
    resultText: '',
    loading: false
  },
  {
    id: 3,
    title: '教师访问教师知识库',
    description: '测试教师角色是否可以访问教师知识库',
    scope: 'teacher',
    operation: 'read',
    userRole: 'teacher',
    result: null,
    resultText: '',
    loading: false
  },
  {
    id: 4,
    title: '管理员访问私有知识库',
    description: '测试管理员角色是否可以访问私有知识库',
    scope: 'private',
    operation: 'read',
    userRole: 'admin',
    result: null,
    resultText: '',
    loading: false
  }
])

// 文档操作权限测试用例
const documentTestCases = reactive([
  {
    id: 1,
    title: '学生上传到公开知识库',
    description: '测试学生角色是否可以上传文档到公开知识库',
    scope: 'public',
    operation: 'write',
    userRole: 'student',
    result: null,
    resultText: '',
    loading: false
  },
  {
    id: 2,
    title: '学生上传到教师知识库',
    description: '测试学生角色是否可以上传文档到教师知识库',
    scope: 'teacher',
    operation: 'write',
    userRole: 'student',
    result: null,
    resultText: '',
    loading: false
  },
  {
    id: 3,
    title: '教师上传到教师知识库',
    description: '测试教师角色是否可以上传文档到教师知识库',
    scope: 'teacher',
    operation: 'write',
    userRole: 'teacher',
    result: null,
    resultText: '',
    loading: false
  }
])

// 运行知识库权限测试
const runVectorDbTest = async (testCase: any) => {
  if (!userStore.user) {
    ElMessage.warning('请先登录')
    return
  }

  testCase.loading = true
  
  try {
    // 模拟用户角色
    const originalRole = userStore.user.role
    userStore.user.role = testCase.userRole
    
    // 使用简化权限检查
    const hasPermission = await userStore.checkSimplePermission(testCase.operation)
    
    // 恢复原始角色
    userStore.user.role = originalRole
    
    testCase.result = hasPermission
    testCase.resultText = hasPermission 
      ? `用户角色 ${testCase.userRole} 可以${testCase.operation} ${testCase.scope} 知识库`
      : `用户角色 ${testCase.userRole} 无法${testCase.operation} ${testCase.scope} 知识库`
    
    ElMessage.success(`测试完成: ${testCase.title}`)
  } catch (error) {
    console.error('权限测试失败:', error)
    testCase.result = false
    testCase.resultText = '测试失败'
    ElMessage.error('测试失败')
  } finally {
    testCase.loading = false
  }
}

// 运行文档操作权限测试
const runDocumentTest = async (testCase: any) => {
  if (!userStore.user) {
    ElMessage.warning('请先登录')
    return
  }

  testCase.loading = true
  
  try {
    // 模拟用户角色
    const originalRole = userStore.user.role
    userStore.user.role = testCase.userRole
    
    // 使用简化权限检查
    const hasPermission = await userStore.checkSimplePermission(testCase.operation)
    
    // 恢复原始角色
    userStore.user.role = originalRole
    
    testCase.result = hasPermission
    testCase.resultText = hasPermission 
      ? `用户角色 ${testCase.userRole} 可以${testCase.operation}文档到${testCase.scope}知识库`
      : `用户角色 ${testCase.userRole} 无法${testCase.operation}文档到${testCase.scope}知识库`
    
    ElMessage.success(`测试完成: ${testCase.title}`)
  } catch (error) {
    console.error('权限测试失败:', error)
    testCase.result = false
    testCase.resultText = '测试失败'
    ElMessage.error('测试失败')
  } finally {
    testCase.loading = false
  }
}

onMounted(() => {
  if (!userStore.user) {
    ElMessage.info('请先登录以测试权限功能')
  }
})
</script>

<style scoped>
.permission-test-container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 2rem;
}

.header-section {
  text-align: center;
  margin-bottom: 2rem;
}

.header-section h2 {
  color: #303133;
  margin-bottom: 0.5rem;
}

.subtitle {
  color: #606266;
  font-size: 1.1rem;
}

.user-info-section,
.permission-test-section,
.permission-explanation-section {
  margin-bottom: 2rem;
}

.card-header {
  font-weight: 600;
  font-size: 1.1rem;
}

.user-details {
  padding: 1rem 0;
}

.user-info {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1rem;
}

.info-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.5rem 0;
  border-bottom: 1px solid #f0f0f0;
}

.label {
  font-weight: 600;
  color: #606266;
}

.value {
  color: #303133;
}

.test-group {
  margin-bottom: 2rem;
}

.test-group h3 {
  color: #303133;
  margin-bottom: 1rem;
  padding-bottom: 0.5rem;
  border-bottom: 2px solid #409eff;
}

.test-cases {
  display: grid;
  gap: 1rem;
}

.test-case {
  padding: 1rem;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  background: #fafafa;
}

.case-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}

.case-title {
  font-weight: 600;
  color: #303133;
}

.case-description {
  color: #606266;
  font-size: 0.9rem;
  margin-bottom: 0.5rem;
}

.case-result {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.5rem;
}

.result-text {
  color: #606266;
  font-size: 0.9rem;
}

.explanation-content h3 {
  color: #303133;
  margin: 1rem 0 0.5rem 0;
}

.explanation-content ul {
  margin: 0.5rem 0;
  padding-left: 1.5rem;
}

.explanation-content li {
  margin: 0.25rem 0;
  color: #606266;
}

.no-user {
  text-align: center;
  padding: 2rem;
}

@media (max-width: 768px) {
  .permission-test-container {
    padding: 1rem;
  }
  
  .user-info {
    grid-template-columns: 1fr;
  }
  
  .case-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.5rem;
  }
}
</style>