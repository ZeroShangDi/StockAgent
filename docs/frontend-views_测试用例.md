# 前端视图层 测试用例

## TC-FV-01: 用户登录流程

**测试目标**: 验证登录页面完整交互链路。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 访问 `/login` 页面 | 显示登录表单（用户名/密码/记住我/登录按钮/注册链接） |
| 2 | 输入错误用户名密码，点击登录 | 显示错误提示 "用户名或密码错误" |
| 3 | 输入正确凭据，点击登录 | 调用 `POST /api/v1/auth/login`，存储 access_token + refresh_token 到 localStorage |
| 4 | 登录后重定向 | 跳转到 `/dashboard` 或 redirect 参数指定的页面 |
| 5 | 已登录状态访问 `/login` | 自动重定向到 `/dashboard` |
| 6 | 勾选"记住我"登录 | localStorage 中 token 持久化 |

---

## TC-FV-02: 路由鉴权守卫

**测试目标**: 验证路由 auth guard 工作正常。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 未登录访问 `/dashboard` | 重定向到 `/login?redirect=/dashboard` |
| 2 | 未登录访问 `/analysis` | 重定向到 `/login?redirect=/analysis` |
| 3 | 已登录访问 `/login` | 重定向到 `/dashboard` |
| 4 | 访问不存在的路由 `/xyz` | 显示 NotFound 404 页面 |
| 5 | 页面标题随路由变化 | `document.title` 为 `"{meta.title} - StockAgent"` |

---

## TC-FV-03: Dashboard 仪表盘

**测试目标**: 验证仪表盘核心组件渲染和数据加载。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 登录后进入 `/dashboard` | 页面加载，显示搜索框和快速操作按钮 |
| 2 | MarketOverviewCard 加载 | 显示上证/深证/创业板指数数据（指数值、涨跌幅、颜色） |
| 3 | WatchlistCard 加载 | 显示自选股列表及实时行情 |
| 4 | RecentTasks 加载 | 显示最近的分析任务列表及状态徽章 |
| 5 | TaskProgressCard 加载 | 显示活跃任务的进度条 |
| 6 | 点击"大盘分析"按钮 | 触发 analyzeMarket，创建任务并跳转 |
| 7 | 在搜索框输入股票名称 | 显示搜索建议下拉框 |
| 8 | 选择股票后确认 | 触发 analyzeStock，创建任务并跳转 |

---

## TC-FV-04: Analysis 分析详情页

**测试目标**: 验证分析任务详情页面交互。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 进入 `/analysis/:taskId` | 显示任务基本信息（股票名/代码/状态/创建时间） |
| 2 | WebSocket 推送 agent_thought | AgentThinking 组件实时展示思考过程（打字机效果） |
| 3 | WebSocket 推送 task_result | 分析结果卡片渲染（Markdown 内容、评分柱） |
| 4 | 风险警告显示 | 高风险分析结果以醒目样式标注 |
| 5 | 目标价/止损价显示 | 数值以格式化样式展示 |
| 6 | 任务仍在运行中 | 显示进度条和状态徽章（running） |
| 7 | 任务完成 | 状态变为 completed，停止显示进度动画 |

---

## TC-FV-05: Market 市场分析页

**测试目标**: 验证大盘分析页面数据展示。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 进入 `/market/analysis` | 终端风格页面加载，显示统计条 |
| 2 | 统计条数据 | 显示强度/情绪/成交量/涨跌停/北向资金数值 |
| 3 | 主题雷达 | 显示各主题板块强度雷达图或条形图 |
| 4 | 周期指标 | 显示当前市场周期阶段 |
| 5 | 切换标签页 | 各面板正常切换，数据正确加载 |

---

## TC-FV-06: Market Weather 晴雨表

**测试目标**: 验证市场晴雨表仪表板。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 进入 `/market/weather` | 显示仪表板，含投资建议/建议仓位/超额收益 |
| 2 | 准确率显示 | 显示历史准确率统计 |
| 3 | 因子分解图表 | ECharts 图表正常渲染 |
| 4 | 点击回测按钮 | 打开回测对话框 |

---

## TC-FV-07: Stock Detail 股票详情

**测试目标**: 验证股票详情页完整功能。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 进入 `/stock/000001.SZ` | 头部卡片显示股票名称/代码/行业/当前价格 |
| 2 | 指标网格 | 显示 PE/PB/市值/涨跌幅/换手率等指标 |
| 3 | K线图面板 | ECharts K线图正常渲染，支持日/周/月切换 |
| 4 | 自选切换 | 点击星标按钮，自选状态切换，WatchlistCard 同步更新 |
| 5 | AI 分析按钮 | 点击触发 analyzeStock，跳转到分析详情页 |
| 6 | 修复数据按钮 | 调用修复 API，显示操作结果提示 |
| 7 | 底部导航切换 | 历史分析/新闻/财务标签页正常切换加载 |
| 8 | 快速洞察卡片 | 显示 30 日收益和概念板块信息 |

---

## TC-FV-08: StockPicker 一句话选股

**测试目标**: 验证自然语言选股流程。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 进入 `/stock-picker` | 显示查询输入框和快速示例按钮 |
| 2 | 点击快速示例 | 输入框自动填充示例查询语句 |
| 3 | 输入 "流通市值大于100亿且roe大于15%的股票" 并提交 | 调用选股 API，加载中显示 loading |
| 4 | 结果展示 | 表格显示符合条件的股票列表（代码/名称/行业/相关指标） |
| 5 | 点击"深度复盘" | 跳转到 StockPickerReviewView |
| 6 | 点击"加入池" | 股票添加到指定池子 |

---

## TC-FV-09: Stock Pools 股票池管理

**测试目标**: 验证股票池 CRUD 操作。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 进入 `/stock-pools` | 左侧显示池子列表，右侧显示选中池子的股票 |
| 2 | 创建新池子 | 输入名称，创建成功，池子列表更新 |
| 3 | 向池子添加股票 | 输入 ts_code，添加成功，表格新增一行 |
| 4 | 从池子移除股票 | 点击删除，确认后移除 |
| 5 | 删除池子 | 点击删除，确认后池子被删除 |
| 6 | 批量加入 V2 监听 | 选中多只股票，点击批量操作按钮 |

---

## TC-FV-10: Backtest 回测

**测试目标**: 验证回测参数配置与结果展示。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 进入 `/backtest` | 显示参数表单和结果区域 |
| 2 | 搜索并选择股票 `000001.SZ` | 股票代码填充到表单 |
| 3 | 设置日期范围、初始现金、阈值 | 表单验证通过 |
| 4 | 提交回测 | 调用 `POST /api/v1/backtest/submit`，显示 loading |
| 5 | 回测完成 | 显示收益曲线图、指标（夏普比率/最大回撤/胜率）、交易列表 |
| 6 | 历史侧栏 | 显示之前的回测记录，可点击查看详情 |

---

## TC-FV-11: Assistant 智能工作台

**测试目标**: 验证 AI 聊天界面和 SSE 流式传输。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 进入 `/assistant` | 显示 ChatGPT 风格聊天界面 |
| 2 | 输入消息并发送 | 调用 SSE 流式 API，消息逐字显示 |
| 3 | Markdown 渲染 | 代码块、表格、标题正确渲染 |
| 4 | 产物面板 | 当消息含 artifact 时，iframe 面板显示内容 |
| 5 | 快速提示 | 点击预设提示，自动填入输入框 |

---

## TC-FV-12: HotNews 新闻聚合

**测试目标**: 验证新闻源管理和展示。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 进入 `/market/news` | 显示多个新闻源卡片 |
| 2 | 拖拽源卡片 | 卡片位置更新，localStorage 保存新布局 |
| 3 | 切换 focus/hottest/realtime 模式 | 新闻列表按模式过滤 |
| 4 | 点击新闻链接 | 在新标签页打开原文 |
| 5 | 新闻源启用/停用 | 切换后该源卡片显示/隐藏 |

---

## TC-FV-13: TradeReview 交易复盘

**测试目标**: 验证交易复盘完整流程。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 进入 `/trade-review` | 显示群组列表和5个标签页 |
| 2 | CSV 导入 | 选择 CSV 文件，数据解析后展示在记录表 |
| 3 | 热力图标签页 | PnL 热力图（TradeReviewPnLHeatmap）正常渲染 |
| 4 | 点击某笔交易 | 跳转到 TradeReviewSessionView |
| 5 | 复盘表单填写 | 操作原因/心态/市场背景/结果判定可编辑 |
| 6 | Ctrl+S 保存 | 提交复盘数据，显示保存成功 |
| 7 | 键盘快捷键 | 1=成功/2=失败，方向键切换记录 |

---

## TC-FV-14: Strategy V2 策略中心

**测试目标**: 验证 V2 策略管理功能。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 进入 `/strategies-v2` | 显示策略定义列表 |
| 2 | 点击某策略的任务 | 跳转到任务中心，显示该策略的任务列表 |
| 3 | 点击某任务运行记录 | 跳转到运行详情，显示 items/logs/audit |

---

## TC-FV-15: 主题切换

**测试目标**: 验证暗色/亮色主题切换。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 点击顶栏主题切换按钮 | 主题在 light/dark 之间切换 |
| 2 | dark 模式 | document.documentElement 添加 dark class，CSS 变量切换 |
| 3 | 刷新页面 | 主题偏好保持（localStorage 持久化） |

---

## TC-FV-16: WebSocket 实时通信

**测试目标**: 验证 WebSocket 连接和消息处理。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | Dashboard 加载时 | WebSocket 自动连接（`/ws?token=<jwt>`） |
| 2 | 发送心跳 ping | 30 秒间隔发送 ping |
| 3 | 收到 task_progress 消息 | useWebSocket 分发到 useTaskStore.updateTaskProgress |
| 4 | 收到 agent_thought 消息 | 追加到 thoughtsMap，AgentThinking 组件渲染 |
| 5 | WebSocket 断开 | 自动重连（最多 5 次，3 秒间隔） |
| 6 | 5 次重连失败 | 停止重连，UI 显示连接断开提示 |

---

## 代码走查验证结果

**走查日期**: 2026-06-21 | **方法**: 代码走查 | **结果**: 16/16 通过

| 用例 | 结果 | 走查依据 |
|------|------|----------|
| TC-FV-01 | ✅ PASS | LoginView.vue: 登录表单含用户名/密码/记住我/登录按钮/注册链接; 错误→提示 "用户名或密码错误"; 成功→POST /api/v1/auth/login, 存储 access_token+refresh_token; 重定向 /dashboard; 已登录→自动跳转 |
| TC-FV-02 | ✅ PASS | router/index.ts:296-319: beforeEach 守卫, requiresAuth && !token → redirect /login?redirect= (line 307-312), guest && token → /dashboard (line 313-315), NotFound 路由 (line 277-281), document.title = title + " - StockAgent" (line 300) |
| TC-FV-03 | ✅ PASS | DashboardView.vue: 搜索框+快速操作按钮, MarketOverviewCard 显示指数数据, WatchlistCard 显示自选股行情, RecentTasks 显示任务列表, TaskProgressCard 显示进度; 大盘分析按钮→analyzeMarket; 搜索框→搜索建议→analyzeStock |
| TC-FV-04 | ✅ PASS | AnalysisDetailView.vue: 显示任务基本信息(股票名/代码/状态/创建时间), AgentThinking 实时展示思考过程, WebSocket 推送 task_result 渲染 Markdown, risk warning 样式, 目标价/止损价格式化, running→进度条+状态徽章, completed→停止动画 |
| TC-FV-05 | ✅ PASS | MarketAnalysisView.vue: 终端风格页面, 统计条显示强度/情绪/成交量/涨跌停/北向资金, 主题雷达图/条形图, 周期指标, 标签页切换 |
| TC-FV-06 | ✅ PASS | MarketWeatherView.vue: 仪表板含投资建议/建议仓位/A股+超额收益, 准确率统计, ECharts 因子分解图表, 回测对话框按钮 |
| TC-FV-07 | ✅ PASS | StockDetailView.vue: 头部卡片显示名称/代码/行业/价格, 指标网格 PE/PB/市值/涨跌幅/换手率, ECharts K线图支持日/周/月, 星标按钮→自选切换→WatchlistCard同步, AI分析按钮→analyzeStock, 修复按钮→修复API, 底部导航切换历史分析/新闻/财务, 快速洞察卡片含30日收益+概念板块 |
| TC-FV-08 | ✅ PASS | StockPickerView.vue: 查询输入框+快速示例按钮, 点击示例→填充, 输入提交→选股API+loading, 结果表格显示股票列表(代码/名称/行业/指标), 深度复盘→StockPickerReviewView, 加入池→添加到池子 |
| TC-FV-09 | ✅ PASS | StockPoolsView.vue: 左侧池子列表, 右侧股票列表; 创建池子, 添加股票, 移除股票, 删除池子, 批量加入V2监听 |
| TC-FV-10 | ✅ PASS | BacktestView.vue: 参数表单+结果区域, 搜索选择股票→填充代码, 日期范围/初始现金/阈值, POST /api/v1/backtest/submit, 完成显示收益曲线+夏普比率/最大回撤/胜率+交易列表, 历史侧栏 |
| TC-FV-11 | ✅ PASS | AssistantWorkspaceView.vue: ChatGPT风格聊天界面, SSE流式API→逐字显示, Markdown渲染含代码块/表格/标题, iframe artifact面板, 快速提示预设 |
| TC-FV-12 | ✅ PASS | HotNewsView.vue: 多个新闻源卡片, 拖拽→localStorage保存, focus/hottest/realtime 模式过滤, 点击→新标签页原文, 源启用/停用→显示/隐藏 |
| TC-FV-13 | ✅ PASS | TradeReviewView.vue: 群组列表+5标签页, CSV导入→解析展示, PnL热力图渲染, 点击交易→TradeReviewSessionView, 复盘表单含操作原因/心态/市场背景/结果判定, Ctrl+S保存, 键盘快捷键1=成功/2=失败+方向键切换 |
| TC-FV-14 | ✅ PASS | StrategyCenterV2View.vue: 策略定义列表; 点击任务→StrategyTaskCenterView; 点击运行记录→StrategyRunDetailView(items/logs/audit) |
| TC-FV-15 | ✅ PASS | ThemeToggle 组件: 顶栏按钮切换 light/dark, dark模式→document.documentElement添加dark class+CSS变量切换, localStorage持久化→刷新保持 |
| TC-FV-16 | ✅ PASS | useWebSocket composable: Dashboard加载→WebSocket自动连接 /ws?token=<jwt>; 30s ping间隔; task_progress→useTaskStore.updateTaskProgress; agent_thought→thoughtsMap→AgentThinking渲染; 断开→自动重连(最多5次/3秒间隔); 5次失败→停止重连+UI提示 |
