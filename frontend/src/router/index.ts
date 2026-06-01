import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import UserView from '../views/UserGraphView.vue'
import ConfigView  from '../views/ConfigCardView.vue'
import ModelConfigDetail from '../views/ModelConfigDetail.vue'
import VectorDbView from '../views/VectorDbView.vue'
import VectorDbDetail from '../views/VectorDbDetail.vue'
import ChatView from '../views/ChatView.vue';
import ChatHistoryView from '../views/ChatHistoryView.vue';
import ChatIntroView from '../views/ChatIntroView.vue';
import LoginView from '../views/LoginView.vue';
import RegisterView from '../views/RegisterView.vue';
import PermissionManageView from '../views/PermissionManageView.vue'
import PermissionTestView from '../views/PermissionTestView.vue'
import BotListView from '../views/BotListView.vue'
import BotDetailView from '../views/BotDetailView.vue'
import BotBuilderView from '../views/BotBuilderView.vue'
import BotChatView from '../views/BotChatView.vue'

import { useUserStore } from '../stores/user'
import { ElMessage } from 'element-plus'
declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth?: boolean
    requiresPermission?: string  // 权限代码
    requiresOrganization?: boolean  // 是否需要组织上下文
    organizationLevel?: string  // 组织级别要求：school/college/department/class
  }
}
const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      component: HomeView,
      meta: { requiresAuth: false } // 需要登录
    },
    {
      path: '/user',
      name: 'user',
      component: UserView,
      meta: { requiresAuth: true }
    },
    {
      path: '/config',
      name: 'config',
      component: ConfigView,
      meta: { requiresAuth: true,
        requiresPermission: 'config:read'
       }
    },
    {
      path: '/database',
      name: 'database',
      component: VectorDbView,
      meta: { requiresAuth: true,
        requiresPermission: 'knowledge:read'
       }
    },
    {
      path: '/database/:id',
      name: 'databaseDetail',
      component: VectorDbDetail,
      meta: { requiresAuth: true,
        requiresPermission: 'knowledge:read'
       }
    },
    {
      path: '/chat',
      name: 'chat',
      component: ChatView,
      meta: { requiresAuth: true }
    },
    {
      path: '/bots',
      name: 'bots',
      component: BotListView,
      meta: { requiresAuth: true }
    },
    {
      path: '/bots/create',
      name: 'botCreate',
      component: BotBuilderView,
      meta: { requiresAuth: true }
    },
    {
      path: '/bots/:id',
      name: 'botDetail',
      component: BotDetailView,
      meta: { requiresAuth: true }
    },
    {
      path: '/bots/:id/knowledge',
      name: 'botKnowledgeList',
      component: () => import('../views/BotKnowledgeListView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/bots/:id/edit',
      name: 'botEdit',
      component: BotBuilderView,
      meta: { requiresAuth: true }
    },
    {
      path: '/bots/:id/chat',
      name: 'botChat',
      component: BotChatView,
      meta: { requiresAuth: true }
    },
    {
      path: '/intro',
      name: 'intro',
      component: ChatIntroView,
      meta: { requiresAuth: true }
    },
    {
      path: '/history',
      name: 'history',
      component: ChatHistoryView,
      meta: { requiresAuth: true }
    },
    {
      path: '/login',
      name: 'login',
      component: LoginView,
      meta: { requiresAuth: false }
    },
    {
      path: '/register',
      name: 'register',
      component: RegisterView,
      meta: { requiresAuth: false }
    },
    {
      path: '/config/:id',
      name: 'configDetail',
      component: ModelConfigDetail,
      meta: { requiresAuth: true,
        requiresPermission: 'config:read'
       }
    },
    {
      path: '/permission',
      name: 'Permission',
      component: PermissionManageView,
      meta: { requiresAuth: true,
        requiresPermission: 'permission:read' }
    },
    {
      path: '/organization',
      name: 'Organization',
      component: () => import('../views/OrganizationView.vue'),
      meta: { 
        requiresAuth: true,
        requiresPermission: 'organization:read',
        requiresOrganization: true
      }
    },
    {
      path: '/teaching-space',
      name: 'TeachingSpace',
      component: () => import('../views/TeachingSpaceView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/admin/teaching-space',
      name: 'AdminTeachingSpace',
      component: () => import('../views/AdminTeachingSpaceView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/admin/teaching-space/:id',
      name: 'AdminTeachingSpaceDetail',
      component: () => import('../views/TeachingSpaceDetailView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/teaching-space/:id',
      name: 'TeachingSpaceDetail',
      component: () => import('../views/TeachingSpaceDetailView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/permission-test',
      name: 'PermissionTest',
      component: PermissionTestView,
      meta: { requiresAuth: true }
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'NotFound',
      component: () => import('../views/HomeView.vue'),
      meta: { requiresAuth: false }
    },
  ],
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) {
      return savedPosition
    } else {
      return { top: 0 }
    }
  }
})

// 添加导航守卫
router.beforeEach(async (to, from, next) => {
  const userStore = useUserStore()
  
  // 初始化用户状态（异步）
  if (!userStore.isAuthenticated) {
    await userStore.init()
  }
  
  // 检查路由是否需要认证
  if (to.meta.requiresAuth) {
    if (userStore.isAuthenticated && userStore.getToken()) {
      // 检查是否需要组织上下文
      if (to.meta.requiresOrganization) {
        if (!userStore.currentOrganization) {
          // 如果没有当前组织，尝试设置默认组织
          if (userStore.userOrganizations.length > 0) {
            await userStore.switchOrganization(userStore.userOrganizations[0].id)
          } else {
            ElMessage.warning('请先加入组织');
            next({ name: 'home' });
            return;
          }
        }
        
        // 检查组织级别要求
        if (to.meta.organizationLevel && userStore.currentOrganization) {
          const orgLevels = ['school', 'college', 'department', 'class']
          const requiredLevel = orgLevels.indexOf(to.meta.organizationLevel)
          const currentLevel = orgLevels.indexOf(userStore.currentOrganization.type)
          
          if (currentLevel > requiredLevel) {
            ElMessage.error(`需要${to.meta.organizationLevel}级别的组织权限`);
            next(from.fullPath);
            return;
          }
        }
      }
      
      // 检查权限（支持组织上下文）
      if (to.meta.requiresPermission) {
        // 验证权限代码不为空
        const permissionCode = to.meta.requiresPermission
        if (!permissionCode || permissionCode.trim() === '') {
          console.warn('路由权限检查：权限代码为空', to.path)
          next()
          return
        }
        
        const organizationId = userStore.currentOrganization?.id
        const hasPerm = await userStore.hasPermission(
          permissionCode,
          organizationId
        );
        if (!hasPerm) {
          ElMessage.error('无权限访问！');
          next(from.fullPath); // 返回原页面或跳转到无权限页面
          return;
        }
      }
      // 管理员访问教师版教学空间路由时，重定向到管理员版
      if (userStore.user?.role === 'admin' && to.path.startsWith('/teaching-space')) {
        const adminPath = '/admin' + to.path;
        next(adminPath);
        return;
      }
      next();
    } else {
      // 未认证，重定向到登录页
      next({
        name: 'login',
        query: {
          redirect: to.fullPath,
          reason: 'unauthenticated'
        }
      });
    }
  } else if ((to.name === 'login' || to.name === 'register') && userStore.isAuthenticated) {
    // 已登录用户访问登录/注册页，重定向到首页
    next({ name: 'home' });
  } else {
    // 其他情况正常导航
    next();
  }
})
export default router
