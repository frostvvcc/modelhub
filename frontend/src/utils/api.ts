// utils/api.ts
import axios from 'axios'
import { useUserStore } from '../stores/user'
import { ElMessage } from 'element-plus'


// 创建 axios 实例
const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 100000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器 - 添加认证 token
api.interceptors.request.use(config => {
  const userStore = useUserStore()
  const token = userStore.getToken()
  
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  
  // 如果数据是 FormData，不设置 Content-Type，让浏览器自动设置
  if (config.data instanceof FormData) {
    delete config.headers['Content-Type']
  }
  
  return config
}, error => {
  return Promise.reject(error)
})

// 响应拦截器 - 处理认证错误
api.interceptors.response.use(response => {
  return response
}, error => {
  if (error.response && error.response.status === 401) {
    const requestUrl = error.config?.url || ''
    if (!requestUrl.includes('/user/login')) {
      const userStore = useUserStore()
      userStore.logout()
      window.location.href = '/login?reason=session_expired'
    }
  }
  if (error.response && error.response.status === 403) {
    if (!error.config?._silent403) {
      ElMessage.error('权限不足')
    }
  }
  
  return Promise.reject(error)
})

export default api