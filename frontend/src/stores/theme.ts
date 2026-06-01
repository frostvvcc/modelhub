import { defineStore } from 'pinia'

// 定义主题类型
export type Theme = {
  id: string
  name: string
  background: string
}

export const useThemeStore = defineStore('theme', {
  state: () => ({
    // 可用主题列表
    themes: [
      {
        id: 'default',
        name: '浅灰',
        background: '#f7f8fb'
      },
      {
        id: 'white',
        name: '纯白',
        background: '#ffffff'
      },
      {
        id: 'cool-blue',
        name: '淡蓝',
        background: '#f4f8ff'
      },
      {
        id: 'soft-green',
        name: '淡绿',
        background: '#f5faf7'
      }
    ] as Theme[],
    // 当前选中的主题ID
    currentThemeId: 'default'
  }),
  getters: {
    currentTheme(): Theme {
      return this.themes.find(t => t.id === this.currentThemeId) || this.themes[0]
    }
  },
  actions: {
    setTheme(themeId: string) {
      this.currentThemeId = themeId
      // 保存到本地存储
      localStorage.setItem('theme', themeId)
    }
  }
})
