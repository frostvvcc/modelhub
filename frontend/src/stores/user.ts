// stores/user.ts
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElNotification } from 'element-plus'
import api from '../utils/api'
import { getUserInfo } from '../api/user'
import { getUserOrganizations, type Organization } from '../api/organization'
import { getUserRoles, getUserPermissions, checkPermission, type Role, type Permission } from '../api/permission'

interface User {
  id: string | number
  name: string
  email: string
  avatar: string
  role?: string
  school_id?: number | null
  student_id?: string | null
  employee_id?: string | null
  phone?: string | null
  enrollment_year?: number | null
  status?: string
}

export const useUserStore = defineStore('user', () => {
  const router = useRouter()
  
  // 用户信息
  const user = ref<User | null>(null)
  
  // 认证 token
  const token = ref<string | null>(null)
  
  // 登录状态
  const isAuthenticated = ref(false)

  // 组织上下文
  const currentOrganization = ref<Organization | null>(null)
  const userOrganizations = ref<Organization[]>([])

  const isVirtualOrganization = (org?: Organization | null) => {
    if (!org) return false
    return org.code?.startsWith('VIRTUAL_') || org.name?.startsWith('虚拟')
  }

  const getOrganizationDisplay = (org?: Organization | null) => {
    if (!org) return null
    const virtualDisplay: Record<string, { name: string; type: string }> = {
      VIRTUAL_PUBLIC: { name: '公共资料空间', type: '公共' },
      VIRTUAL_TEACHER: { name: '教师资料空间', type: '教师' },
      VIRTUAL_PRIVATE: { name: '个人资料空间', type: '个人' },
    }
    return virtualDisplay[org.code] || { name: org.name, type: org.type }
  }
  
  // 角色和权限
  const userRoles = ref<Role[]>([])
  const userPermissions = ref<string[]>([])
  
  // 计算属性：当前学校
  const currentSchool = computed(() => {
    if (!user.value?.school_id) return null
    return userOrganizations.value.find(org =>
      org.id === user.value?.school_id
      && org.type === 'school'
      && !isVirtualOrganization(org)
    ) || null
  })

  const currentOrganizationDisplay = computed(() => getOrganizationDisplay(currentOrganization.value))
  
  // 计算属性：是否有指定权限
  const hasPermissionComputed = computed(() => {
    return (permission: string) => {
      return userPermissions.value.includes(permission)
    }
  })
  
  // 加载用户上下文（组织、角色、权限）
  async function loadUserContext() {
    if (!user.value) return
    
    try {
      // 加载用户详细信息（包含组织和角色）
      const userInfo = await getUserInfo()
      if (userInfo.user_info) {
        user.value = {
          ...user.value,
          ...userInfo.user_info,
          avatar: userInfo.user_info.avatar
            ? `${import.meta.env.VITE_API_BASE_URL}/user/avatar/${userInfo.user_info.avatar}`
            : '/ModelHub.png',
        }
      }
      
      // 加载用户组织
      if (userInfo.organizations) {
        userOrganizations.value = userInfo.organizations
        // 如果只有一个组织，自动设置为当前组织
        if (userOrganizations.value.length === 1) {
          currentOrganization.value = userOrganizations.value[0]
        } else if (user.value?.school_id) {
          // 默认设置为学校
          const school = userOrganizations.value.find(org => org.id === user.value?.school_id && org.type === 'school')
          if (school) {
            currentOrganization.value = school
          }
        }
      } else {
        // 如果没有，尝试从API获取
        if (user.value) {
          const orgs = await getUserOrganizations(Number(user.value.id))
          userOrganizations.value = orgs
        }
      }
      
      // 加载用户角色
      if (userInfo.roles) {
        userRoles.value = userInfo.roles
      } else {
        if (user.value) {
          const roles = await getUserRoles(Number(user.value.id))
          userRoles.value = roles
        }
      }
      
      // 加载用户权限
      if (userInfo.permissions) {
        userPermissions.value = userInfo.permissions
      } else {
        if (user.value) {
          const permissions = await getUserPermissions(Number(user.value.id))
          userPermissions.value = permissions
        }
      }
      
      // 保存到本地存储
      saveToLocalStorage()
    } catch (error) {
      console.error('加载用户上下文失败:', error)
    }
  }
  
  // 登录方法（学号/工号/邮箱 + 密码）
  async function login(account: string, password: string) {
    try {
      const response = await api.post('/user/login', { account, password })

      const data = response.data.data
      
      user.value = {
          id: data.id,
          name: data.name,
          email: data.email,
          avatar: data.avatar ? `${import.meta.env.VITE_API_BASE_URL}/user/avatar/${data.avatar}` : '/ModelHub.png',
          school_id: data.school_id,
          role: data.role || 'student', // 添加角色信息，默认为学生
      }
      token.value = data.token
      isAuthenticated.value = true
      
      // 保存到本地存储
      saveToLocalStorage()
      
      // 加载用户上下文（组织、角色、权限）
      await loadUserContext()
      
      ElNotification.success({
        title: '登录成功',
        message: `欢迎回来，${data.name}！`
      })
      
      return true
      
    } catch (error: any) {
      ElNotification.error({
        title: '登录失败',
        message: error.response?.data?.message || '邮箱或密码不正确'
      })
      return false
    }
  }
  
  // 简化的权限检查（基于用户角色）
  async function checkSimplePermission(operation: 'read' | 'write' | 'delete') {
    if (!user.value) return false
    const userRole = user.value.role || 'student'
    if (userRole === 'admin') return true

    switch (operation) {
      case 'read':
        return true
      case 'write':
        return userRole === 'teacher' || userRole === 'admin'
      case 'delete':
        return userRole === 'admin'
    }
    return false
  }

  // 检查权限（支持组织上下文）
  async function hasPermission(permission: string, organizationId?: number) {
    try {
      // 验证权限代码不为空
      if (!permission || permission.trim() === '') {
        return false
      }

      // 先检查本地权限列表
      if (userPermissions.value.includes(permission)) {
        return true
      }

      // 如果指定了组织，检查组织级权限
      if (organizationId) {
        const hasPerm = await checkPermission(permission, organizationId)
        if (hasPerm) {
          // 更新本地权限列表
          if (!userPermissions.value.includes(permission)) {
            userPermissions.value.push(permission)
          }
          return true
        }
      }

      // 兜底：检查全局权限（不带组织上下文）
      // 防止角色分配在全局而非组织级别时，带组织检查失败
      if (organizationId) {
        const globalPerm = await checkPermission(permission)
        if (globalPerm) {
          if (!userPermissions.value.includes(permission)) {
            userPermissions.value.push(permission)
          }
          return true
        }
      }

      return false
    } catch (error) {
      console.error('权限检查失败:', error)
      return false
    }
  }
  
  // 切换组织
  async function switchOrganization(organizationId: number) {
    const org = userOrganizations.value.find(o => o.id === organizationId)
    if (org) {
      currentOrganization.value = org
      // 重新加载权限：先加载该组织下的权限，再合并全局权限，防止切换组织后权限丢失
      const orgPermissions = await getUserPermissions(Number(user.value?.id), organizationId)
      const globalPermissions = await getUserPermissions(Number(user.value?.id))
      // 合并去重：组织权限 + 全局权限
      const merged = new Set([...orgPermissions, ...globalPermissions])
      userPermissions.value = Array.from(merged)
      saveToLocalStorage()
    }
  }
  
  // 保存到本地存储
  function saveToLocalStorage() {
    if (user.value) {
      localStorage.setItem('user', JSON.stringify(user.value))
    }
    if (token.value) {
      localStorage.setItem('token', token.value)
    }
    localStorage.setItem('isAuthenticated', isAuthenticated.value ? 'true' : 'false')
    if (currentOrganization.value) {
      localStorage.setItem('currentOrganization', JSON.stringify(currentOrganization.value))
    }
  }
    
  async function register(name: string, password: string, opts?: { role?: string; schoolId?: number; organizationId?: number; studentId?: string; employeeId?: string; email?: string }) {
    try {
      const payload: any = { name, password }
      if (opts?.role) payload.role = opts.role
      if (opts?.schoolId) payload.school_id = opts.schoolId
      if (opts?.organizationId) payload.organization_id = opts.organizationId
      if (opts?.studentId) payload.student_id = opts.studentId
      if (opts?.employeeId) payload.employee_id = opts.employeeId
      if (opts?.email) payload.email = opts.email
      const response = await api.post('/user/register', payload)
      if (response.data.data) {
        const data = response.data.data
        ElNotification.success({
            title: '注册成功',
            message: `欢迎加入，${name}！`
        })
        
        router.push('/login')
        
        return true
      }else {
        // 处理业务逻辑失败
        const errorMsg = response.data.message || '注册失败'
        ElNotification.error({
            title: '注册失败',
            message: errorMsg || '注册过程中出现问题'
        })
        return false
      }
    } catch (error: any) {
      ElNotification.error({
        title: '注册失败',
        message: error.response?.data?.message || '注册过程中出现问题'
      })
      return false
    }
  }
  
  function logout() {
    user.value = null
    token.value = null
    isAuthenticated.value = false
    currentOrganization.value = null
    userOrganizations.value = []
    userRoles.value = []
    userPermissions.value = []
    
    localStorage.removeItem('user')
    localStorage.removeItem('token')
    localStorage.removeItem('isAuthenticated')
    localStorage.removeItem('currentOrganization')
    
    // router.push('/login')
  }
  
  async function init() {
    const storedUser = localStorage.getItem('user')
    const storedToken = localStorage.getItem('token')
    const storedAuth = localStorage.getItem('isAuthenticated')
    const storedOrg = localStorage.getItem('currentOrganization')
    
    if (storedUser && storedToken && storedAuth === 'true') {
      try {
        user.value = JSON.parse(storedUser)
      } catch {
        localStorage.removeItem('user')
        return
      }
      token.value = storedToken
      isAuthenticated.value = true

      if (storedOrg) {
        try {
          currentOrganization.value = JSON.parse(storedOrg)
        } catch {
          localStorage.removeItem('currentOrganization')
        }
      }
      
      // 加载用户上下文
      await loadUserContext()
    }
  }
  
  function getToken() {
    return token.value
  }

  function updateUserAvatar(avatar: string) {
    if (user.value) {
      user.value.avatar = avatar ? `${import.meta.env.VITE_API_BASE_URL}/user/avatar/${avatar}` : '/ModelHub.png';
    }
  }
  
  return {
    user,
    token,
    isAuthenticated,
    currentOrganization,
    currentOrganizationDisplay,
    userOrganizations,
    isVirtualOrganization,
    getOrganizationDisplay,
    userRoles,
    userPermissions,
    currentSchool,
    hasPermissionComputed,
    login,
    register,
    logout,
    init,
    getToken,
    updateUserAvatar,
    hasPermission,
    checkSimplePermission,
    loadUserContext,
    switchOrganization
  }
})
