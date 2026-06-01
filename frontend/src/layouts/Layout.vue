<script setup lang="ts">
import NavBar from '@/components/NavBar.vue'
import SideBar from '@/components/SideBar.vue'
import { useUserStore } from '../stores/user'
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { useThemeStore } from '../stores/theme'
import { useRoute } from 'vue-router'
import { ElButton } from 'element-plus'
import { Close, Menu } from '@element-plus/icons-vue'

const userStore = useUserStore()
userStore.init()

const themeStore = useThemeStore()
const route = useRoute()
const isScrolled = ref(false)
const isMobileSidebarOpen = ref(false)

const handleScroll = () => {
  isScrolled.value = window.scrollY > 10
}

onMounted(() => {
  window.addEventListener('scroll', handleScroll)
  const savedTheme = localStorage.getItem('theme')
  if (savedTheme && themeStore.themes.some(t => t.id === savedTheme)) {
    themeStore.setTheme(savedTheme)
    updateBackground(themeStore.currentTheme.background)
  }
})

onUnmounted(() => {
  window.removeEventListener('scroll', handleScroll)
})

const updateBackground = (background: string) => {
  const bgElement = document.querySelector('.content-container') as HTMLElement
  if (bgElement) {
    // 检测是否是纯色（不包含"gradient"关键词）
    if (!background.includes('gradient')) {
      bgElement.style.setProperty('--theme-background-color', background)
      bgElement.style.setProperty('--theme-background-image', 'none')
    } else {
      bgElement.style.setProperty('--theme-background-image', background)
      bgElement.style.setProperty('--theme-background-color', '#ffffff')
    }
  }
}

watch(() => themeStore.currentTheme, (newTheme) => {
  updateBackground(newTheme.background)
}, { immediate: true })

watch(() => route.path, () => {
  isMobileSidebarOpen.value = false
})
</script>

<template>
  <div class="layout-container">
    <!-- 顶部导航栏 - 固定位置 -->
    <header class="sticky-header" :class="{ 'scrolled': isScrolled }">
      <NavBar />
    </header>

    <!-- 主体布局 - 包含侧边栏和内容 -->
    <div class="main-layout" :class="{ 'no-sidebar': !userStore.isAuthenticated }">
      <ElButton
        v-if="userStore.isAuthenticated"
        class="mobile-sidebar-toggle"
        :icon="isMobileSidebarOpen ? Close : Menu"
        circle
        @click="isMobileSidebarOpen = !isMobileSidebarOpen"
      />
      <!-- 左侧边栏 - 固定位置 -->
      <SideBar
        v-if="userStore.isAuthenticated"
        class="sidebar"
        :class="{ 'mobile-open': isMobileSidebarOpen }"
      />
      <div
        v-if="userStore.isAuthenticated && isMobileSidebarOpen"
        class="sidebar-backdrop"
        @click="isMobileSidebarOpen = false"
      />
      
      <!-- 右侧内容区域 - 可滚动 -->
      <div class="content-container">
        <main class="main-content">
          <slot />
        </main>
        
        <!-- 页脚 -->
        <!-- <footer class="app-footer">
          <p>&copy; 2025 ModelHub. All rights reserved.</p>
        </footer> -->
      </div>
    </div>
  </div>
</template>

<style scoped>
.layout-container {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  width: 100%;
  position: relative;
}

.layout-container::before {
  content: "";
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: -1;
  background-color: #fff;
}

.sticky-header {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 1000;
  height: 56px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  background-color: #ffffff;
  border-bottom: 1px solid #eef0f4;
}

/* 主布局 - 侧边栏 + 内容区域 */
.main-layout {
  display: flex;
  position: fixed;
  top: 56px;
  left: 0;
  right: 0;
  bottom: 0; /* 填满剩余空间 */
  z-index: 90;
}

.mobile-sidebar-toggle {
  display: none;
}

/* 侧边栏样式 */
.sidebar {
  width: 220px;
  background-color: #f8f9fc;
  border-right: 1px solid #eef0f4;
  height: 100%;
  overflow-y: auto;
  position: relative;
  z-index: 95;
}

/* 内容容器 */
.content-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: calc(100vh - 56px);
  padding: 0;
  overflow-y: auto;
  position: relative;
  background-color: transparent; /* 确保背景透明 */
}

.content-container::before {
  content: "";
  position: fixed; /* 改为fixed定位 */
  top: 56px;
  left: 220px;
  right: 0;
  bottom: 0;
  z-index: -1;
  background-image: var(--theme-background-image);
  background-color: var(--theme-background-color, #ffffff);
}

.main-layout.no-sidebar .content-container::before {
  left: 0;
}

.main-layout.no-sidebar .main-content {
  padding-left: 2rem;
}

.app-footer {
  padding: 1rem;
  text-align: center;
  border-top: 1px solid #dee2e6;
  background-color: white;
  z-index: 10;
  margin-top: auto;
}

.main-content {
  padding: 1.25rem 1.5rem;
  flex: 1;
}

/* 响应式设计 */
@media (max-width: 992px) {
  .mobile-sidebar-toggle {
    display: inline-flex;
    position: fixed;
    top: 68px;
    left: 16px;
    z-index: 1300;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
  }

  .sidebar {
    position: fixed;
    top: 56px;
    left: 0;
    bottom: 0;
    width: min(280px, 86vw);
    transform: translateX(-105%);
    transition: transform 0.22s ease;
    z-index: 1250;
    display: flex;
  }

  .sidebar.mobile-open {
    transform: translateX(0);
  }

  .sidebar-backdrop {
    position: fixed;
    top: 56px;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(15, 23, 42, 0.35);
    z-index: 1200;
  }
  
  .content-container {
    width: 100%;
  }

  .content-container::before {
    left: 0;
  }
  
  .main-content {
    padding: 3.5rem 1rem 1rem;
  }
}
</style>
