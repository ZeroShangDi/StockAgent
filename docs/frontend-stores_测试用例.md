# 前端状态管理 测试用例

## TC-FS-01: useUserStore 登录状态管理

**测试目标**: 验证用户登录/登出状态流转。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 初始状态 | `isLoggedIn=false`, `userInfo=null` |
| 2 | 调用 `setLoggedIn()` | `isLoggedIn=true` |
| 3 | 调用 `fetchUserInfo()` | API 请求成功，`userInfo` 更新为后端返回的用户数据 |
| 4 | `userId` getter | 返回 `userInfo.user_id` |
| 5 | `username` getter | 返回 `userInfo.username` |
| 6 | `isAdmin` getter | 返回 `userInfo.is_admin` |
| 7 | 调用 `clearUser()` | `isLoggedIn=false`, `userInfo=null` |

---

## TC-FS-02: useUserStore 自选股操作

**测试目标**: 验证自选股 CRUD。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `addToWatchlist("000001.SZ")` | API PUT 调用，`watchlist` 数组新增 "000001.SZ" |
| 2 | 再次 `addToWatchlist("000001.SZ")` | API 去重，不重复添加 |
| 3 | `removeFromWatchlist("000001.SZ")` | API DELETE 调用，`watchlist` 移除该代码 |
| 4 | 从空 watchlist 移除 | 正常处理，不报错 |

---

## TC-FS-03: useMarketStore 行情缓存

**测试目标**: 验证市场数据缓存机制。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `fetchOverview()` | `overview` 更新，`lastUpdated` 记录时间戳 |
| 2 | `shIndex` / `szIndex` / `cybIndex` getters | 返回正确的指数值 |
| 3 | `marketStats` getter | 返回 `{up, down, flat, limitUp, limitDown}` 统计 |
| 4 | `fetchQuotes(["000001.SZ", "000002.SZ"])` | `quotesMap` 新增两条 |
| 5 | `getQuote("000001.SZ")` | 返回缓存的行情对象 |
| 6 | 缓存未命中 `getQuote("999999.SZ")` | 返回 undefined，不报错 |
| 7 | `searchStocks("平安")` | 返回模糊搜索结果列表 |
| 8 | `clearCache()` | `quotesMap` 和 `stockBasicMap` 清空 |

---

## TC-FS-04: useTaskStore 任务管理

**测试目标**: 验证任务列表和实时更新。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `fetchTasks()` | `tasks` 填充任务列表 |
| 2 | `runningTasks` getter | 仅返回 status=running 的任务 |
| 3 | `completedTasks` getter | 仅返回 status=completed 的任务 |
| 4 | `selectTask(taskId)` | `currentTask` 设置为该任务 |
| 5 | `cancelTask(taskId)` | API DELETE 调用，任务状态变为 cancelled |
| 6 | WebSocket 推送 `{type:"task_progress", task_id, percentage:50, message}` | `updateTaskProgress()` 调用，`progressMap[taskId]` 更新 |
| 7 | WebSocket 推送 `{type:"agent_thought", task_id, thought}` | `appendAgentThought()` 调用，`thoughtsMap[taskId]` 追加 |
| 8 | WebSocket 推送 `{type:"task_completed", task_id, result}` | `updateTaskResult()` 调用，任务状态更新为 completed |
| 9 | `clearThoughts(taskId)` | `thoughtsMap[taskId]` 清空 |

---

## TC-FS-05: useThemeStore 主题切换

**测试目标**: 验证主题切换和持久化。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 初始 `mode` | 从 localStorage 读取或默认 `'system'` |
| 2 | `toggleTheme()` | light ↔ dark 切换 |
| 3 | `setTheme('dark')` | `mode='dark'`, localStorage 更新 |
| 4 | `isDark` getter (mode='dark') | 返回 `true` |
| 5 | `isDark` getter (mode='light') | 返回 `false` |
| 6 | `isDark` getter (mode='system' and systemPrefersDark=true) | 返回 `true` |
| 7 | `applyTheme()` | `document.documentElement` class 和 CSS 变量更新 |
| 8 | 刷新页面 | 主题保持（localStorage 持久化生效） |
| 9 | 系统主题切换（暗色→亮色）| `initTheme()` 监听 `matchMedia('prefers-color-scheme: dark')`，自动同步 |

---

## TC-FS-06: useWebSocket 连接管理

**测试目标**: 验证 WebSocket 连接生命周期。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | Dashboard 首次加载 | 自动建立 WebSocket 连接 `/ws?token=<jwt>` |
| 2 | 收到 pong | 心跳正常（30s ping/pong） |
| 3 | WebSocket 意外断开 | 自动重连（3s 后首次尝试） |
| 4 | 第 2-5 次重连 | 继续重试 |
| 5 | 第 5 次重连失败 | 停止重连，显示连接断开提示 |
| 6 | 手动刷新页面 | WebSocket 重新连接并重置重试计数 |

---

## TC-FS-07: useAuth 认证流程

**测试目标**: 验证认证 hook 的完整流程。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `login("user", "pass")` | POST `/api/v1/auth/login` → 保存 token → `fetchUserInfo()` → 重定向 `/dashboard` |
| 2 | 登录后 `checkAuth()` | 返回 `true` |
| 3 | `logout()` | 清除 localStorage token → `clearUser()` → 重定向 `/login` |
| 4 | 登出后 `checkAuth()` | 返回 `false` |
| 5 | `register(data)` | POST `/api/v1/auth/register` → 重定向 `/login` |
| 6 | `changePassword(old, new)` | POST `/api/v1/auth/change-password` → 成功提示 |

---

## TC-FS-08: Axios 拦截器 Token 刷新

**测试目标**: 验证 401 自动刷新机制。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 发送请求，access_token 已过期 | 返回 401 |
| 2 | 响应拦截器捕获 401 | 自动调用 `/api/v1/auth/refresh`（refresh_token） |
| 3 | 刷新成功 | 新 access_token 存入 localStorage，原请求重试 |
| 4 | 多个请求同时 401 | 刷新期间其他请求排队等待，刷新完成后一起重试 |
| 5 | refresh_token 也过期 | 清除 token，重定向到 `/login` |

---

## 代码走查验证结果

**走查日期**: 2026-06-21 | **方法**: 代码走查 | **结果**: 8/8 通过

| 用例 | 结果 | 走查依据 |
|------|------|----------|
| TC-FS-01 | ✅ PASS | user.ts:14-15: isLoggedIn=ref(false), userInfo=ref(null); setLoggedIn (line 68-70), fetchUserInfo (line 56-65) sets userInfo+isLoggedIn; userId/username/isAdmin computed (line 25/28/51); clearUser (line 78-81) null+false |
| TC-FS-02 | ✅ PASS | user.ts:83-107: addToWatchlist calls userApi.addToWatchlist, checks !includes before push (line 87-88); removeFromWatchlist calls userApi.removeFromWatchlist, filter (line 101); empty watchlist remove safe (filter on empty array) |
| TC-FS-03 | ✅ PASS | market.ts: Pinia store with overview/quotesMap/stockBasicMap; fetchOverview/fetchQuotes/getQuote/searchStocks/clearCache actions |
| TC-FS-04 | ✅ PASS | task.ts: tasks list, fetchTasks fills tasks, runningTasks/completedTasks computed filters, selectTask sets currentTask, cancelTask calls API, updateTaskProgress/appendAgentThought/updateTaskResult handle WebSocket messages, clearThoughts clears thoughtsMap |
| TC-FS-05 | ✅ PASS | theme.ts: mode from localStorage or 'system', toggleTheme light↔dark, setTheme updates mode+localStorage, isDark computed checks mode + system preference, applyTheme updates document.documentElement, initTheme listens matchMedia |
| TC-FS-06 | ✅ PASS | WebSocket composable: auto-connect on Dashboard mount, 30s ping/pong heartbeat, auto-reconnect on disconnect (3s interval, max 5 retries), stop on 5th failure with UI disconnect indicator, reset on manual refresh |
| TC-FS-07 | ✅ PASS | auth composable: login POSTs /auth/login → saves token → fetchUserInfo → redirect /dashboard; checkAuth checks token; logout clears token+clearUser → redirect /login; register POSTs /auth/register → redirect /login; changePassword POSTs /auth/change-password |
| TC-FS-08 | ✅ PASS | client.ts:102-168: 401 interceptor → isRefreshing check (line 112-121) queues subscribers; POST /auth/refresh (line 133-138); onTokenRefreshed notifies all (line 62-65); new token stored in localStorage (line 141-142); originalRequest retried (line 148-150); refresh failure → handleAuthError clears tokens + redirect /login (line 172-189) |
