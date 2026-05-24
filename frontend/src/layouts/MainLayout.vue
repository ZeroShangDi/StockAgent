<script setup lang="ts">
/**
 * 主布局 - 包含侧边栏和顶部导航
 * 支持 Light/Dark 主题切换
 */

import { ref, computed, onBeforeUnmount, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ElContainer,
  ElAside,
  ElHeader,
  ElMain,
  ElMenu,
  ElMenuItem,
  ElDropdown,
  ElDropdownMenu,
  ElDropdownItem,
  ElAvatar,
  ElBadge,
  ElIcon,
  ElTooltip,
} from 'element-plus'
import {
  HomeFilled,
  DataAnalysis,
  TrendCharts,
  Star,
  Setting,
  Fold,
  Expand,
  User,
  SwitchButton,
  Bell,
  Histogram,
  Sunny,
  Moon,
  Promotion,
  Document,
  WarningFilled,
  Opportunity,
  CollectionTag,
  DataLine,
  ChatDotRound,
  AlarmClock,
} from '@element-plus/icons-vue'
import { useAuth } from '@/hooks'
import { useUserStore, useTaskStore, useThemeStore } from '@/stores'

const route = useRoute()
const router = useRouter()
const { logout } = useAuth()
const userStore = useUserStore()
const taskStore = useTaskStore()
const themeStore = useThemeStore()

// ==================== 状态 ====================

const isCollapsed = ref(false)
const focusModeEnabled = ref(false)

// ==================== 计算属性 ====================

const activeMenu = computed(() => {
  const path = route.path
  if (path.startsWith('/analysis')) return '/analysis'
  if (path.startsWith('/assistant')) return '/assistant'
  if (path.startsWith('/automation-overview')) return '/automation-overview'
  if (path.startsWith('/usage-guide')) return '/usage-guide'
  if (path.startsWith('/strategies-v2')) return '/strategies-v2'
  if (path.startsWith('/strategy-tasks') || path.startsWith('/strategy-runs')) return '/strategy-tasks'
  if (path.startsWith('/stock-picker')) return '/stock-picker'
  if (path.startsWith('/stock-pools')) return '/stock-pools'
  if (path.startsWith('/positions')) return '/trade-review'
  if (path.startsWith('/stock-statistics')) return '/stock-statistics'
  if (path.startsWith('/trade-review')) return '/trade-review'
  if (path.startsWith('/kline-practice')) return '/kline-practice'
  if (path.startsWith('/stock')) return '/analysis'
  if (path.startsWith('/strategies')) return '/strategies'
  return path
})

const activeTaskCount = computed(() => taskStore.activeTaskCount)
const isFocusMode = computed(() => focusModeEnabled.value || route.matched.some(record => record.meta.immersive))

// ==================== 菜单项 ====================

const menuSections = [
  {
    key: 'market-data',
    title: '市场与数据',
    items: [
      { path: '/market-weather', icon: Sunny, title: '市场晴雨表' },
      { path: '/stock-statistics', icon: Histogram, title: '股票统计' },
      { path: '/market', icon: Histogram, title: '行情分析' },
      { path: '/sector-strategy', icon: TrendCharts, title: '板块分析' },
      { path: '/hot-news', icon: Promotion, title: '热点追踪' },
    ],
  },
  {
    key: 'stock-selection',
    title: '选股与股池',
    items: [
      { path: '/stock-picker', icon: Opportunity, title: '一句话选股' },
      { path: '/stock-pools', icon: CollectionTag, title: '股池管理' },
      { path: '/watchlist', icon: Star, title: '自选股' },
    ],
  },
  {
    key: 'strategy-tasks',
    title: '策略与任务',
    items: [
      { path: '/strategies-v2', icon: DataAnalysis, title: '策略中心 V2' },
      { path: '/strategy-tasks', icon: TrendCharts, title: '场景任务 V2' },
    ],
  },
  {
    key: 'review-trading',
    title: '交易与复盘',
    items: [
      { path: '/trade-review', icon: Document, title: '交割单复盘' },
      { path: '/reports', icon: Document, title: '报告回顾' },
      { path: '/kline-practice', icon: DataLine, title: '盘感练习' },
    ],
  },
  {
    key: 'workspace',
    title: '智能工作区',
    items: [
      { path: '/assistant', icon: ChatDotRound, title: 'AI 工作台' },
      { path: '/analysis', icon: DataAnalysis, title: '分析任务' },
      { path: '/dashboard', icon: HomeFilled, title: '仪表盘' },
    ],
  },
  {
    key: 'system',
    title: '系统',
    items: [
      { path: '/usage-guide', icon: Document, title: '使用说明' },
      { path: '/automation-overview', icon: AlarmClock, title: '自动任务总览' },
      { path: '/system-status', icon: WarningFilled, title: '能力状态' },
      { path: '/settings', icon: Setting, title: '设置' },
    ],
  },
  {
    key: 'legacy',
    title: '旧版待下线',
    items: [
      { path: '/strategies', icon: TrendCharts, title: '市场监听' },
      { path: '/factor-selection', icon: DataAnalysis, title: '因子选股' },
      { path: '/backtest', icon: DataAnalysis, title: '单股回测' },
    ],
  },
]

// ==================== 生命周期 ====================

onMounted(() => {
  // 初始化主题
  themeStore.initTheme()
  focusModeEnabled.value = typeof window !== 'undefined' && window.localStorage.getItem('stockagent.focus_mode') === '1'
  window.addEventListener('stockagent-focus-mode-change', handleFocusModeChange)
})

onBeforeUnmount(() => {
  window.removeEventListener('stockagent-focus-mode-change', handleFocusModeChange)
})

// ==================== 方法 ====================

function handleMenuSelect(path: string): void {
  router.push(path)
}

function toggleCollapse(): void {
  isCollapsed.value = !isCollapsed.value
}

function toggleTheme(): void {
  themeStore.toggleTheme()
}

async function handleLogout(): Promise<void> {
  await logout()
}

function handleFocusModeChange(): void {
  focusModeEnabled.value = typeof window !== 'undefined' && window.localStorage.getItem('stockagent.focus_mode') === '1'
}

function toggleFocusMode(): void {
  const nextValue = !focusModeEnabled.value
  focusModeEnabled.value = nextValue
  window.localStorage.setItem('stockagent.focus_mode', nextValue ? '1' : '0')
  window.dispatchEvent(new Event('stockagent-focus-mode-change'))
}
</script>

<template>
  <ElContainer class="main-layout" :class="{ 'focus-mode': isFocusMode }">
    <button
      class="global-focus-fab"
      :class="{ active: isFocusMode }"
      :aria-label="isFocusMode ? '退出专注模式' : '进入专注模式'"
      :title="isFocusMode ? '退出专注模式' : '进入专注模式'"
      type="button"
      @click="toggleFocusMode"
    >
      <span class="global-focus-fab-dot" />
      <span class="global-focus-fab-label">{{ isFocusMode ? '退出专注' : '进入专注' }}</span>
    </button>
    <!-- 侧边栏 -->
    <ElAside v-show="!isFocusMode" :width="isCollapsed ? '64px' : '220px'" class="sidebar">
      <div class="logo" :class="{ collapsed: isCollapsed }">
        <img src="/logo.svg" alt="Logo" class="logo-img" />
        <span v-if="!isCollapsed" class="logo-text">StockAgent</span>
      </div>
      
      <ElMenu
        :default-active="activeMenu"
        :collapse="isCollapsed"
        class="sidebar-menu"
        @select="handleMenuSelect"
      >
        <template v-for="section in menuSections" :key="section.key">
          <div v-if="!isCollapsed" class="menu-section-label">
            {{ section.title }}
          </div>
          <ElMenuItem
            v-for="item in section.items"
            :key="item.path"
            :index="item.path"
            class="menu-item-wrapper"
          >
            <ElIcon><component :is="item.icon" /></ElIcon>
            <template #title>
              <div class="menu-title-wrapper">
                <span>{{ item.title }}</span>
                <span 
                  v-if="item.path === '/analysis' && activeTaskCount > 0"
                  class="menu-badge-dot"
                >
                  {{ activeTaskCount > 99 ? '99+' : activeTaskCount }}
                </span>
              </div>
            </template>
          </ElMenuItem>
          <div v-if="!isCollapsed && section.key !== menuSections[menuSections.length - 1].key" class="menu-section-divider"></div>
        </template>
      </ElMenu>
      
      <div class="collapse-btn" @click="toggleCollapse">
        <ElIcon :size="20">
          <Fold v-if="!isCollapsed" />
          <Expand v-else />
        </ElIcon>
      </div>
    </ElAside>
    
    <!-- 主内容区 -->
    <ElContainer class="main-container">
      <!-- 顶部栏 -->
      <ElHeader v-show="!isFocusMode" class="header">
        <div class="header-left">
          <h2 class="page-title">{{ $route.meta.title }}</h2>
        </div>
        
        <div class="header-right">
          <!-- 主题切换 -->
          <ElTooltip :content="themeStore.isDark ? '切换到浅色模式' : '切换到深色模式'" placement="bottom">
            <button class="theme-toggle" @click="toggleTheme">
              <Transition name="theme-icon" mode="out-in">
                <Moon v-if="themeStore.isDark" key="dark" class="theme-icon" />
                <Sunny v-else key="light" class="theme-icon" />
              </Transition>
            </button>
          </ElTooltip>
          
          <!-- 通知 -->
          <ElBadge :value="activeTaskCount" :hidden="activeTaskCount === 0" class="notification">
            <ElIcon :size="20"><Bell /></ElIcon>
          </ElBadge>
          
          <!-- 用户菜单 -->
          <ElDropdown trigger="click" @command="handleMenuSelect">
            <div class="user-info">
              <ElAvatar :size="32" :src="userStore.avatar || undefined">
                {{ userStore.nickname.charAt(0) }}
              </ElAvatar>
              <span class="username">{{ userStore.nickname }}</span>
            </div>
            <template #dropdown>
              <ElDropdownMenu>
                <ElDropdownItem :icon="User" command="/settings">
                  个人中心
                </ElDropdownItem>
                <ElDropdownItem :icon="Setting" command="/settings">
                  设置
                </ElDropdownItem>
                <ElDropdownItem divided :icon="SwitchButton" @click="handleLogout">
                  退出登录
                </ElDropdownItem>
              </ElDropdownMenu>
            </template>
          </ElDropdown>
        </div>
      </ElHeader>
      
      <!-- 内容区 -->
      <ElMain class="main-content">
        <RouterView />
      </ElMain>
    </ElContainer>
  </ElContainer>
</template>

<style scoped lang="scss">
.main-layout {
  min-height: 100vh;
  overflow: hidden;
}

.global-focus-fab {
  position: fixed;
  left: calc(v-bind("isFocusMode ? '20px' : (isCollapsed ? '80px' : '236px')"));
  bottom: calc(env(safe-area-inset-bottom, 0px) + 24px);
  z-index: 3000;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0;
  width: 48px;
  height: 48px;
  padding: 0;
  border: 1px solid rgba(37, 99, 235, 0.28);
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.96);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  box-shadow: 0 16px 36px rgba(37, 99, 235, 0.28);
  backdrop-filter: blur(12px);
  overflow: hidden;
  cursor: pointer;
  transition:
    width 0.24s ease,
    transform 0.2s ease,
    box-shadow 0.2s ease,
    background-color 0.2s ease,
    border-color 0.2s ease,
    left 0.3s ease;
}

.global-focus-fab:hover,
.global-focus-fab:focus-visible {
  width: 126px;
  justify-content: flex-start;
  gap: 10px;
  padding: 0 16px 0 15px;
  transform: translateY(-1px);
  background: rgba(29, 78, 216, 0.98);
  box-shadow: 0 20px 40px rgba(37, 99, 235, 0.34);
}

.global-focus-fab.active {
  background: rgba(15, 23, 42, 0.92);
  border-color: rgba(15, 23, 42, 0.35);
  box-shadow: 0 16px 36px rgba(15, 23, 42, 0.24);
}

.global-focus-fab.active:hover,
.global-focus-fab.active:focus-visible {
  background: rgba(15, 23, 42, 0.98);
  box-shadow: 0 20px 44px rgba(15, 23, 42, 0.28);
}

.global-focus-fab-dot {
  width: 10px;
  height: 10px;
  flex: 0 0 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 0 0 5px rgba(255, 255, 255, 0.14);
  transition: transform 0.24s ease, box-shadow 0.24s ease, background-color 0.24s ease;
}

.global-focus-fab:hover .global-focus-fab-dot,
.global-focus-fab:focus-visible .global-focus-fab-dot {
  transform: scale(1.05);
  box-shadow: 0 0 0 6px rgba(255, 255, 255, 0.16);
}

.global-focus-fab-label {
  max-width: 0;
  overflow: hidden;
  opacity: 0;
  white-space: nowrap;
  transform: translateX(-6px);
  transition:
    max-width 0.24s ease,
    opacity 0.18s ease,
    transform 0.24s ease;
}

.global-focus-fab:hover .global-focus-fab-label,
.global-focus-fab:focus-visible .global-focus-fab-label {
  max-width: 72px;
  opacity: 1;
  transform: translateX(0);
}

.main-layout.focus-mode {
  .main-container {
    margin-left: 0;
    width: 100%;
  }

  .main-content {
    padding: 20px;
  }
}

.sidebar {
  background: var(--sidebar-bg);
  display: flex;
  flex-direction: column;
  transition: width 0.3s;
  position: fixed;
  top: 0;
  left: 0;
  height: 100vh;
  z-index: 100;
  
  .logo {
    height: 60px;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
    padding: 0 16px;
    border-bottom: 1px solid var(--sidebar-border);
    
    .logo-img {
      width: 32px;
      height: 32px;
    }
    
    .logo-text {
      font-size: 18px;
      font-weight: 700;
      color: white;
      white-space: nowrap;
    }
    
    &.collapsed {
      padding: 0;
      
      .logo-img {
        width: 28px;
        height: 28px;
      }
    }
  }

  .menu-section-label {
    padding: 14px 18px 8px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--text-secondary);
    opacity: 0.72;
  }

  .menu-section-divider {
    height: 1px;
    margin: 10px 16px;
    background: var(--sidebar-border);
    opacity: 0.7;
  }
  
  .sidebar-menu {
    flex: 1;
    border-right: none;
    background: transparent;
    overflow-y: auto;
    
    :deep(.el-menu-item) {
      color: var(--sidebar-text);
      
      &:hover {
        background: var(--sidebar-hover-bg);
        color: var(--sidebar-text-active);
      }
      
      &.is-active {
        background: var(--sidebar-active-bg);
        color: var(--sidebar-text-active);
      }
    }
    
    :deep(.menu-title-wrapper) {
      display: flex;
      align-items: center;
      justify-content: space-between;
      width: 100%;
      padding-right: 8px;
    }
    
    :deep(.menu-badge-dot) {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 18px;
      height: 18px;
      padding: 0 5px;
      font-size: 11px;
      font-weight: 600;
      color: #fff;
      background: var(--error);
      border-radius: 9px;
      margin-left: 8px;
      flex-shrink: 0;
    }
  }
  
  .collapse-btn {
    height: 48px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--sidebar-text);
    cursor: pointer;
    transition: all 0.3s;
    border-top: 1px solid var(--sidebar-border);
    
    &:hover {
      color: var(--sidebar-text-active);
      background: var(--sidebar-hover-bg);
    }
  }
}

.main-container {
  flex-direction: column;
  background: var(--bg-base);
  margin-left: v-bind("isCollapsed ? '64px' : '220px'");
  transition: margin-left 0.3s, background-color var(--transition-normal);
  height: 100vh;
  overflow-y: auto;
}

.header {
  background: var(--header-bg);
  border-bottom: 1px solid var(--header-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  position: sticky;
  top: 0;
  z-index: 50;
  transition: background-color var(--transition-normal), border-color var(--transition-normal);
  
  .header-left {
    .page-title {
      margin: 0;
      font-size: 18px;
      font-weight: 600;
      color: var(--text-primary);
    }
  }
  
  .header-right {
    display: flex;
    align-items: center;
    gap: 16px;
    
    .theme-toggle {
      width: 36px;
      height: 36px;
      display: flex;
      align-items: center;
      justify-content: center;
      background: var(--bg-muted);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      cursor: pointer;
      transition: all var(--transition-fast);
      
      .theme-icon {
        width: 18px;
        height: 18px;
        color: var(--text-secondary);
        transition: color var(--transition-fast);
      }
      
      &:hover {
        background: var(--bg-hover);
        border-color: var(--primary-400);
        
        .theme-icon {
          color: var(--primary-500);
        }
      }
    }
    
    .notification {
      cursor: pointer;
      color: var(--text-secondary);
      
      &:hover {
        color: var(--primary-500);
      }
    }
    
    .user-info {
      display: flex;
      align-items: center;
      gap: 8px;
      cursor: pointer;
      padding: 4px 8px;
      border-radius: var(--radius-md);
      transition: background var(--transition-fast);
      
      &:hover {
        background: var(--bg-hover);
      }
      
      .username {
        font-weight: 500;
        color: var(--text-primary);
      }
    }
  }
}

@media (max-width: 768px) {
  .global-focus-fab {
    left: 16px;
    bottom: calc(env(safe-area-inset-bottom, 0px) + 16px);
    width: 44px;
    height: 44px;
  }

  .global-focus-fab:hover,
  .global-focus-fab:focus-visible {
    width: 44px;
    padding: 0;
    gap: 0;
    justify-content: center;
    transform: none;
  }

  .global-focus-fab-label {
    display: none;
  }
}

.main-content {
  padding: 20px;
  flex: 1;
  overflow-x: hidden;
  background: var(--bg-base);
  transition: background-color var(--transition-normal);
}

// 主题图标切换动画
.theme-icon-enter-active,
.theme-icon-leave-active {
  transition: all 0.2s ease;
}

.theme-icon-enter-from {
  opacity: 0;
  transform: rotate(-90deg) scale(0.8);
}

.theme-icon-leave-to {
  opacity: 0;
  transform: rotate(90deg) scale(0.8);
}
</style>
