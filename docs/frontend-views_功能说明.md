# 前端视图层 功能说明

## 概述

StockAgent 前端是基于 Vue 3.4 + TypeScript + Vite 5 构建的单页应用，使用 Pinia 状态管理、Vue Router 路由、Element Plus UI 组件库、ECharts 图表和 Tailwind CSS 样式框架。

**技术栈**:
- Vue 3.4 Composition API + `<script setup>`
- TypeScript 严格模式
- Vite 5 构建（自动导入 Vue/Vue Router/Pinia API）
- Pinia 2 状态管理
- Vue Router 4 懒加载路由
- Axios 1.6 HTTP 客户端（JWT 自动注入 + 刷新）
- ECharts 5 图表
- Element Plus 2.6（中文语言包）
- SCSS + Tailwind CSS + CSS 变量主题

## 架构

```
main.ts → App.vue → Router (auth guard)
                      ├── /login, /register → AuthLayout → Auth Views
                      └── /* → MainLayout (侧边栏+顶栏)
                                ├── Dashboard
                                ├── Analysis (列表+详情)
                                ├── Market (分析/晴雨表/统计/板块/新闻)
                                ├── Stock (详情/选股/池子/复盘)
                                ├── Backtest (回测+因子选股)
                                ├── Strategy V2 (策略中心/任务/运行)
                                ├── Assistant (AI 工作台)
                                ├── Practice (盘感练习)
                                ├── Reports (报告)
                                └── System (状态/自动化)
```

## 路由守卫

- `requiresAuth: true` — 未登录重定向到 `/login?redirect=<原路径>`
- `guest: true` — 已登录重定向到 `/dashboard`
- 页面标题: `route.meta.title + ' - StockAgent'`

## 视图模块

### 1. Auth 认证 (2 个视图)

**LoginView** (`views/auth/LoginView.vue`)
- 用户名/密码登录（form-urlencoded 格式）
- "记住我"功能
- 链接到注册页
- 调用 `useAuth().login()` → 保存 Token → 获取用户 → 重定向

**RegisterView** (`views/auth/RegisterView.vue`)
- 注册表单: 用户名/邮箱/密码/昵称/确认密码/同意条款
- 调用 `useAuth().register()` → 重定向到登录

### 2. Dashboard 仪表盘 (1 个视图)

**DashboardView** (`views/dashboard/DashboardView.vue`)
- ChatGPT 风格搜索输入框
- 快速操作按钮（大盘分析/快速分析）
- 4 个仪表盘组件:
  - `MarketOverviewCard` — 大盘指数（上证/深证/创业板）
  - `TaskProgressCard` — 活跃任务进度
  - `RecentTasks` — 最近任务列表
  - `WatchlistCard` — 自选股行情
- WebSocket 实时连接

### 3. Analysis 分析 (2 个视图)

**AnalysisListView** (`views/analysis/AnalysisListView.vue`)
- 任务列表卡片（按状态/类型筛选）
- 创建分析对话框（股票/大盘/自定义）
- 信号徽章/置信度/进度条

**AnalysisDetailView** (`views/analysis/AnalysisDetailView.vue`)
- 任务详情表格
- Agent 思考过程流（打字机效果）
- 分析结果卡片: 评分柱、Markdown 渲染、风险警告、目标价/止损价

### 4. Market 市场 (5 个视图)

**MarketAnalysisView** (`views/market/MarketAnalysisView.vue`)
- 终端风格大盘分析
- 统计条: 强度/情绪/成交量/涨跌停/北向资金
- 主题雷达条、周期指标、多标签分析面板

**MarketWeatherView** (`views/market/MarketWeatherView.vue`)
- 市场天气仪表板
- 投资建议/建议仓位/超额收益/准确率
- 因子分解图表、回测对话框

**StockStatisticsView** (`views/market/StockStatisticsView.vue`)
- 多页面统计浏览器
- 左侧导航: 极限分析/龙头周期/情绪/阶段涨幅/胜率/连板/反弹
- 日期/周期筛选

**SectorStrategyView** (`views/market/SectorStrategyView.vue`)
- 板块分析中心
- 趋势诊断、主题网格（CORE/PULSE/FADE）
- 板块散点图、时间线、排名表

**HotNewsView** (`views/market/HotNewsView.vue`)
- 新闻聚合器
- 多源管理（focus/hottest/realtime）
- 可拖拽源卡片（localStorage 持久化布局）

### 5. Stock 股票 (8 个视图)

**StockDetailView** (`views/stock/StockDetailView.vue`)
- 专业股票详情页
- 头部卡片: 名称/代码/行业/价格/指标网格
- K线图面板（日/周/月切换）
- 修复数据按钮、自选切换、AI 分析按钮
- 快速洞察卡片（30日收益/概念板块）
- V2 监听任务订阅
- 底部导航: 历史分析/新闻/财务

**StockPickerView** (`views/stock/StockPickerView.vue`)
- 自然语言选股查询
- 快速示例、结果表格
- 工具栏: 深度复盘/复制代码/下载/加入池

**StockPoolsView** (`views/stock/StockPoolsView.vue`)
- 股票池管理
- 左侧分组侧栏、右侧详情表格
- CRUD 操作、批量加入 V2 监听任务

**StockPickerReviewView** (`views/stock/StockPickerReviewView.vue`)
- 选股结果深度复盘
- K线面板、股票信息、W 键加入自选

**StockPoolSessionView** (`views/stock/StockPoolSessionView.vue`)
- 沉浸式池子复盘
- K线 + 信息卡片 + V2 监听配置
- 参数: MA 买入/支撑阻力/固定止损/移动止损
- 池转移（复制/移动）
- 键盘快捷键: W/A/C/M/X

**TradeReviewView** (`views/stock/TradeReviewView.vue`)
- 交易复盘中心
- 群组管理 CRUD
- 5 个标签页: 热力图 PnL/分析得分/持仓/记录/逐笔
- CSV 导入、批量策略添加

**TradeReviewSessionView** (`views/stock/TradeReviewSessionView.vue`)
- 沉浸式单笔复盘
- K线（缩放窗口）、相关交易表
- 复盘表单: 操作原因/心态/市场背景/结果判定
- 键盘快捷键: Ctrl+S 保存/方向键导航/1=成功/2=失败
- 脏状态检测

**PositionReviewSessionView** (`views/stock/PositionReviewSessionView.vue`)
- 持仓复盘
- K线 + 持仓信息 + 盈亏显示
- 方向键导航

### 6. Backtest 回测 (2 个视图)

**BacktestView** (`views/backtest/BacktestView.vue`)
- 单股票回测
- 参数表单: 股票搜索/日期范围/现金/阈值/仓位大小
- 结果指标/图表/交易表、历史侧栏

**FactorSelectionView** (`views/backtest/FactorSelectionView.vue`)
- 多因子选股回测
- 因子选择（权重/方向）、历史管理

### 7. Strategy V2 策略 (4 个视图)

**StrategyCenterV2View** — 策略定义中心
**StrategyTaskCenterView** — 场景任务管理
**StrategyTaskDetailView** — 任务详情（运行记录、日志）
**StrategyRunDetailView** — 运行结果详情（项目/日志/操作审计）

### 8. Assistant 智能工作台 (1 个视图)

**AssistantWorkspaceView** (`views/assistant/AssistantWorkspaceView.vue`)
- ChatGPT 风格聊天界面
- SSE 流式消息（fetch + ReadableStream）
- Markdown 渲染 + 自定义代码块
- 产物面板（iframe）
- 快速提示

### 9. Practice 盘感练习 (3 个视图)

**PracticeView** — 练习列表与开始
**PracticeSessionView** — 练习会话
**PracticeHistoryView** — 练习历史

### 10. Reports 报告 (1 个视图)

**ReportView** — AI 分析报告列表与详情

### 11. Settings 设置 (1 个视图)

**SettingsView** — 用户偏好设置

### 12. System 系统 (3 个视图)

**SystemStatusView** — 系统运行状态
**SystemCozeView** — Coze 插件状态
**SystemAutomationView** — 自动化任务概览

## 布局

**MainLayout** (`layouts/MainLayout.vue`)
- 固定侧边栏（可折叠，7 个分组）
- 粘性顶栏（主题切换/通知徽章/用户下拉）
- 专注模式 FAB 按钮

**AuthLayout** (`layouts/AuthLayout.vue`)
- 双栏布局: 左侧品牌区（logo/标题/功能列表），右侧表单区

## 配色约定

中国市场红涨绿跌:
- `$color-up: #f23645`（涨/红色）
- `$color-down: #089981`（跌/绿色）

## 关键组件

| 组件 | 功能 |
|------|------|
| `AgentThinking` | Agent 思考过程流式显示（打字机效果） |
| `TaskStatusBadge` | 彩色状态徽章（可选进度条） |
| `StockChart` | ECharts K线图 |
| `StockReviewChartPanel` | 高级 K线 面板（周期切换/缩放/标记/工具栏） |
| `TradeReviewPnLHeatmap` | 盈亏热力图 |
| `BuildVersionWidget` | 构建版本/提交信息 |
| `SearchBar` | 可复用搜索输入框 |
| `MarketOverviewCard` | 大盘指数卡片 |
| `WatchlistCard` | 自选股行情列表 |
