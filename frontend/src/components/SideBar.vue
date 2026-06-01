<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { ref, computed, onMounted, watch } from 'vue'
import { useUserStore } from '../stores/user'
import { useRoute } from 'vue-router'
import { ElTag, ElDropdown, ElDropdownMenu, ElDropdownItem, ElMessage } from 'element-plus'
import { getUserOrganizations, type Organization } from '../api/organization'
import {
  ChatDotRound,
  Clock,
  DataAnalysis,
  House,
  Key,
  OfficeBuilding,
  Reading,
  Service,
  Setting,
  User,
} from '@element-plus/icons-vue'

const userStore = useUserStore()
const route = useRoute()
const activeItem = ref('')

const setActiveItem = (item: string) => {
  activeItem.value = item
}

// 根据路由自动设置激活项
const updateActiveItem = () => {
  const path = route.path
  
  // 精确匹配优先
  if (path === '/') {
    activeItem.value = 'dashboard'
  } else if (path === '/history' || path.startsWith('/history/')) {
    activeItem.value = 'history'
  } else if (path === '/user' || path.startsWith('/user/')) {
    activeItem.value = 'user'
  } else if (path === '/permission' || path.startsWith('/permission/')) {
    activeItem.value = 'permission'
  } else if (path === '/organization' || path.startsWith('/organization/')) {
    activeItem.value = 'organization'
  } else if (path === '/admin/teaching-space' || path.startsWith('/admin/teaching-space/')) {
    activeItem.value = 'admin-teaching-space'
  } else if (path === '/teaching-space' || path.startsWith('/teaching-space/')) {
    activeItem.value = 'teaching-space'
  } else if (path === '/config' || path.startsWith('/config/')) {
    activeItem.value = 'config'
  } else if (path === '/database' || path.startsWith('/database/')) {
    activeItem.value = 'database'
  } else if (path === '/bots' || path.startsWith('/bots/')) {
    activeItem.value = 'bots'
  } else if (path === '/chat' || path.startsWith('/chat') || path === '/intro') {
    activeItem.value = 'chat'
  } else {
    activeItem.value = ''
  }
}

// 监听路由变化，自动更新激活项
watch(() => route.path, () => {
  updateActiveItem()
}, { immediate: true })

// 组织列表
const organizations = ref<Organization[]>([])
const loadingOrgs = ref(false)

const loadOrganizations = async () => {
  if (!userStore.user?.id) return
  loadingOrgs.value = true
  try {
    organizations.value = await getUserOrganizations(Number(userStore.user.id))
  } catch (error) {
    console.error('加载组织列表失败:', error)
  } finally {
    loadingOrgs.value = false
  }
}

// 切换组织
const switchOrganization = async (org: Organization) => {
  await userStore.switchOrganization(org.id)
  ElMessage.success(`已切换到 ${userStore.getOrganizationDisplay(org)?.name || org.name}`)
}

const currentOrgDisplay = computed(() => userStore.currentOrganizationDisplay)
const displayOrganizations = computed(() => {
  return organizations.value.map(org => ({
    ...org,
    display: userStore.getOrganizationDisplay(org),
  }))
})

const userRole = computed(() => userStore.user?.role || 'student')
const isStudent = computed(() => userRole.value === 'student')

const isAdmin = computed(() => userRole.value === 'admin')

const menuItems = computed(() => {
  const items: Array<{ id: string; name: string; icon: any; path: string; requirePermission?: string; hideForStudent?: boolean; adminOnly?: boolean; hideForAdmin?: boolean }> = [
    { id: 'dashboard', name: '首页', icon: House, path: '/' },
    { id: 'database', name: '知识库', icon: DataAnalysis, path: '/database', requirePermission: 'knowledge:read' },
    { id: 'config', name: '模型配置', icon: Setting, path: '/config', requirePermission: 'config:read', adminOnly: true },
    { id: 'bots', name: '数字助理', icon: Service, path: '/bots' },
    { id: 'teaching-space', name: '教学空间', icon: Reading, path: '/teaching-space', hideForAdmin: true },
    { id: 'admin-teaching-space', name: '空间管理', icon: Reading, path: '/admin/teaching-space', adminOnly: true },
    { id: 'organization', name: '组织架构', icon: OfficeBuilding, path: '/organization', requirePermission: 'organization:read' },
    { id: 'chat', name: '智能对话', icon: ChatDotRound, path: '/intro' },
    { id: 'history', name: '对话历史', icon: Clock, path: '/history' },
    { id: 'permission', name: '权限管理', icon: Key, path: '/permission', requirePermission: 'permission:read' },
    { id: 'user', name: '个人中心', icon: User, path: '/user' },
  ]

  return items.filter(item => {
    if (item.adminOnly && !isAdmin.value) return false
    if (item.hideForAdmin && isAdmin.value) return false
    if (item.hideForStudent && isStudent.value) return false
    if (!item.requirePermission) return true
    return userStore.hasPermissionComputed(item.requirePermission)
  })
})

// 判断菜单项是否激活
const isActive = (item: { id: string; path: string }) => {
  // 优先使用 activeItem
  if (activeItem.value === item.id) {
    return true
  }
  
  // 如果 activeItem 为空，使用路径匹配
  const path = route.path
  if (item.path === '/') {
    return path === '/'
  }
  // 确保路径匹配更精确，避免误匹配
  return path === item.path || path.startsWith(item.path + '/')
}

onMounted(() => {
  updateActiveItem()
  loadOrganizations()
})
</script>

<template>
  <div class="sidebar-container">
    <!-- 菜单项 -->
    <ul class="sidebar-menu">
      <li v-for="item in menuItems" :key="item.id">
        <RouterLink 
          :to="item.path" 
          class="menu-item"
          :class="{ active: isActive(item) }"
          @click="setActiveItem(item.id)"
        >
          <el-icon class="menu-icon">
            <component :is="item.icon" />
          </el-icon>
          <span class="menu-text">{{ item.name }}</span>
        </RouterLink>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.sidebar-container {
  display: flex;
  flex-direction: column;
  padding: 0.5rem;
  height: 100%;
  box-sizing: border-box;
}

.org-switcher {
  padding: 8px 10px;
  border: 1px solid #e8ecf2;
  border-radius: 8px;
  background-color: #fff;
  margin-bottom: 8px;
}

.org-switcher-header {
  margin-bottom: 6px;
}

.org-label {
  font-size: 0.78rem;
  color: #909399;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.current-org {
  margin-bottom: 6px;
}

.org-tag {
  width: 100%;
  display: flex;
  justify-content: center;
  padding: 4px 8px;
}

.org-name {
  font-weight: 500;
  font-size: 0.88rem;
}

.org-type {
  font-size: 0.8em;
  opacity: 0.7;
  margin-left: 4px;
}

.no-org {
  padding: 4px 8px;
  text-align: center;
  margin-bottom: 4px;
}

.no-org-text {
  font-size: 0.82rem;
  color: #c0c4cc;
}

.org-dropdown {
  width: 100%;
}

.switch-btn {
  width: 100%;
  padding: 6px;
  font-size: 0.85rem;
  color: #606266;
}

.switch-icon {
  font-size: 0.7rem;
  margin-left: 4px;
}

.org-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.org-item-name {
  font-weight: 500;
}

.org-item-type {
  font-size: 0.85em;
  color: #909399;
}

:deep(.el-dropdown-menu__item.is-current) {
  background-color: #ecf5ff;
  color: #409eff;
}

.sidebar-menu {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sidebar-menu li {
  margin: 0;
}

.sidebar-menu li:nth-child(1),
.sidebar-menu li:nth-child(5),
.sidebar-menu li:nth-child(7) {
  margin-bottom: 4px;
  padding-bottom: 4px;
  border-bottom: 1px solid #e8ecf2;
}

.menu-item {
  height: 38px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 10px;
  border-radius: 8px;
  text-decoration: none;
  color: #475569;
  transition: all 0.15s ease;
  box-sizing: border-box;
}

.menu-item:hover {
  background-color: #eef4ff;
  color: #2563eb;
}

.menu-item.active {
  background-color: #e0edff;
  color: #1d4ed8;
  font-weight: 600;
}

.menu-icon {
  width: 26px;
  height: 26px;
  flex: 0 0 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  background: #edf1f7;
  font-size: 14px;
}

.menu-item.active .menu-icon,
.menu-item:hover .menu-icon {
  background: #d0e0ff;
}

.menu-text {
  font-size: 0.88rem;
  white-space: nowrap;
}
</style>
