# 前端状态管理 (Pinia Stores) 功能说明

## 概述

前端使用 Pinia 2 Composition API 管理全局状态，共 4 个 Store。所有 Store 定义在 `frontend/src/stores/` 下。

**技术栈**:
- Pinia 2（`defineStore` Composition API 风格）
- 自动持久化: 通过 API 调用同步后端
- localStorage: Token、主题偏好等客户端状态

## 架构

```
Views → Stores → API modules → Backend
  ↑        ↓
  └── WebSocket (实时更新) ←── 
```

## Stores

### 1. useUserStore (`stores/user.ts`)

**职责**: 管理用户身份、偏好和自选股列表。

**State**:
- `userInfo: UserInfo | null` — 当前用户信息
- `isLoggedIn: boolean` — 登录状态
- `loading: boolean` — 加载状态

**Getters**:
- `userId` — 用户 ID
- `username` — 用户名
- `nickname` — 昵称
- `avatar` — 头像 URL
- `watchlist: string[]` — 自选股 ts_code 列表
- `preferences` — 用户偏好对象
- `theme` — 主题设置
- `isAdmin` — 是否管理员
- `notificationChannels` — 通知渠道列表

**Actions**:
- `fetchUserInfo()` — GET `/api/v1/users/me` 获取用户信息
- `setLoggedIn()` / `clearUser()` — 登录/登出状态管理
- `addToWatchlist(tsCode)` — 添加自选
- `removeFromWatchlist(tsCode)` — 移除自选
- `updatePreferences(prefs)` — 更新偏好
- `notificationChannels` CRUD — 通知渠道增删改查

**数据流**: 登录时 `setLoggedIn()` → `fetchUserInfo()` → 渲染 Dashboard。自选操作立即更新本地状态并同步 API。

---

### 2. useMarketStore (`stores/market.ts`)

**职责**: 管理市场行情数据和缓存。

**State**:
- `overview: MarketOverview | null` — 市场概况
- `quotesMap: Map<string, StockQuote>` — 股票行情缓存（key: ts_code）
- `stockBasicMap: Map<string, StockBasic>` — 股票基本信息缓存
- `industries: string[]` — 行业列表
- `loading: boolean` — 加载状态
- `lastUpdated: number` — 最后更新时间戳

**Getters**:
- `shIndex` / `shChange` — 上证指数/涨跌幅
- `szIndex` / `szChange` — 深证指数/涨跌幅
- `cybIndex` / `cybChange` — 创业板指数/涨跌幅
- `marketStats` — 涨/跌/平/涨停/跌停股票数
- `hotSectors` — 热门板块

**Actions**:
- `fetchOverview()` — 获取市场概况
- `fetchQuotes(tsCodes)` — 批量获取股票行情
- `getQuote(tsCode)` — 从缓存获取单股行情
- `fetchStockBasic(tsCode)` / `getStockBasic(tsCode)` — 获取/缓存股票信息
- `fetchIndustries()` — 获取行业列表
- `searchStocks(keyword)` — 搜索股票
- `clearCache()` — 清空缓存

**数据流**: Dashboard 加载时 `fetchOverview()` 获取大盘数据，股票详情页通过 `getQuote()` 读取缓存。

---

### 3. useTaskStore (`stores/task.ts`)

**职责**: 管理分析任务状态和实时进度。

**State**:
- `tasks: Task[]` — 任务列表
- `currentTask: Task | null` — 当前选中的任务
- `progressMap: Map<string, TaskProgress>` — 任务进度映射
- `thoughtsMap: Map<string, AgentThought[]>` — Agent 思考过程映射
- `loading: boolean` — 加载状态

**Getters**:
- `currentThoughts` — 当前任务的思考过程列表
- `currentProgress` — 当前任务的进度
- `activeTaskCount` — 活跃任务数
- `runningTasks` / `completedTasks` — 按状态分类
- `tasksByStatus` — 按 TaskStatus 分组的任务

**Actions**:
- `createTask()`, `fetchTasks()`, `cancelTask()`, `deleteTask()` — 任务 CRUD
- `updateTaskProgress(progress)` — WebSocket 推送进度更新
- `updateTaskResult(result)` — WebSocket 推送结果更新
- `appendAgentThought(thought)` — WebSocket 推送思考步骤
- `clearThoughts(taskId)` — 清空思考过程

**数据流**: WebSocket 接收 `task_progress`/`task_completed`/`task_failed`/`agent_thought` 消息 → 更新 progressMap/thoughtsMap → 视图响应式渲染。

---

### 4. useThemeStore (`stores/theme.ts`)

**职责**: 管理亮色/暗色主题切换。

**State**:
- `mode: 'light' | 'dark' | 'system'` — 主题模式
- `systemPrefersDark: boolean` — 系统暗色偏好

**Getters**:
- `isDark` — 当前是否暗色模式
- `themeName` — 主题名称（'light'/'dark'）

**Actions**:
- `setTheme(mode)` — 设置主题模式
- `toggleTheme()` — 切换 light/dark
- `applyTheme()` — 更新 `document.documentElement` class 和 Element Plus CSS 变量
- `initTheme()` — 监听 `prefers-color-scheme` 媒体查询变化

**数据流**: 用户切换 → `setTheme()` → localStorage 持久化 → `applyTheme()` → DOM 更新。系统主题变化时自动同步。

---

## Hooks（自定义组合式函数）

### useAuth (`hooks/useAuth.ts`)
- `login()` — 保存 token 到 localStorage → `fetchUserInfo()` → 重定向
- `register()` — 注册 → 重定向到登录
- `logout()` — 清除 token 和 Store
- `checkAuth()` — 验证登录状态
- `changePassword()` — 修改密码

### useTask (`hooks/useTask.ts`)
- `createTask()`, `analyzeStock()`, `analyzeMarket()`, `queryAnalysis()` — 创建各种分析
- `cancelTask()`, `refreshTaskList()`, `selectTask()` — 任务管理
- `getTaskStatusLabel()`, `getTaskTypeLabel()` — 状态/类型转中文标签

### useWebSocket (`hooks/useWebSocket.ts`)
- 单例 WebSocket 管理器
- 自动重连（最多 5 次，3 秒间隔）
- 心跳（30 秒 ping/pong）
- 消息分发: `task_progress` / `task_completed` / `task_failed` / `agent_thought`
- 连接 URL: `{wsBase}/ws?token={jwt}`

### useBuildVersion (`hooks/useBuildVersion.ts`)
- 读取构建时注入的 `__APP_BUILD_INFO__` 全局常量

## API 层 (`frontend/src/api/`)

**client.ts**: Axios 实例配置
- 请求拦截器: 注入 `Authorization: Bearer {token}` 和 `X-Trace-ID`
- 响应拦截器: 解包 `response.data`；401 时自动刷新 token（并发请求排队等待）
- 统一错误处理

**types.ts**: API 类型定义，与后端 Pydantic 模型严格对应

**modules/**: 15 个 API 模块（auth, user, task, stock, market, strategy, strategy-v2, backtest, stock-picker, trade-review, report, practice, system, assistant, stock-statistics）
