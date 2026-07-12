# Web API 网关 功能说明

## 概述

Web API 网关是 StockAgent 系统的前端接入层，基于 FastAPI 构建，提供 REST API、WebSocket 实时推送、JWT 认证等功能。它是前端 Vue3 应用与后端微服务节点之间的桥梁。

**节点类型**: `NODE_TYPE=web`  
**入口文件**: `AgentServer/nodes/web/node.py`  
**应用工厂**: `AgentServer/nodes/web/app.py`  

## 架构

```
Frontend (Vue3) → Nginx → Web Node (FastAPI :8000)
                              ├── REST API (/api/v1/*)
                              ├── WebSocket (/ws)
                              ├── JWT Auth (bcrypt + jose)
                              ├── Redis (队列/发布订阅)
                              ├── MongoDB (用户/数据)
                              └── gRPC → 其他节点
```

## 生命周期

`app.py:lifespan()` 管理启动/关闭流程：
1. **启动**: `redis_manager.initialize()` → `mongo_manager.initialize()` → `notification_manager.initialize()` → `ensure_default_admin_user()` → `start_strategy_v2_scheduler()`
2. **关闭**: `stop_strategy_v2_scheduler()` → `notification_manager.shutdown()` → `mongo_manager.shutdown()` → `redis_manager.shutdown()`

## API 路由表

| 路由前缀 | 标签 | 模块 | 说明 |
|---------|------|------|------|
| `/api/v1/auth` | 认证 | `auth.py` | 注册/登录/刷新/登出/改密 |
| `/api/v1/users` | 用户 | `user.py` | 用户信息管理 |
| `/api/v1/tasks` | 任务 | `task.py` | 任务提交与状态查询 |
| `/api/v1/stocks` | 股票 | `stock.py` | 股票数据查询 |
| `/api/v1` | 一句话选股 | `stock_picker.py` | AI 选股推荐 |
| `/api/v1` | 市场分析 | `market.py` | 市场行情数据 |
| `/api/v1` | 市场晴雨表 | `market_weather.py` | 市场情绪分析 |
| `/api/v1/strategy/subscriptions` | 策略订阅 | `subscription.py` | 策略信号订阅 |
| `/api/v1` | 量化回测 | `backtest.py` | 回测任务与结果 |
| `/api/v1/reports` | 报告回顾 | `report.py` | AI 分析报告 |
| `/api/v1/system` | 系统状态 | `system.py` | 系统健康/节点状态 |
| `/api/v1/practice` | 盘感练习 | `practice.py` | 模拟交易练习 |
| `/api/v1` | 交割单复盘 | `trade_review.py` | 交易复盘分析 |
| `/api/v1` | 智能工作台 | `assistant.py` | AI 助手功能 |
| `/api/v1` | Strategy V2 | `strategy_v2.py` | V2 策略信号 |
| `/ws` | WebSocket | `websocket.py` | 实时推送 |

## 核心组件

### 1. JWT 认证 (auth.py)

**双 Token 机制**:
- `access_token`: 短期有效（默认 `jwt_expire_minutes` 分钟），用于 API 请求
- `refresh_token`: 长期有效（30 天），用于刷新 access_token

**密码安全**: bcrypt 哈希 (`hash_password` / `verify_password`)

**认证端点**:
- `POST /api/v1/auth/register` — 注册（用户名+邮箱+密码）
- `POST /api/v1/auth/login` — 登录，返回双 Token
- `POST /api/v1/auth/refresh` — 用 refresh_token 换新 access_token
- `POST /api/v1/auth/logout` — 登出
- `POST /api/v1/auth/change-password` — 修改密码（需旧密码验证）

**权限控制**:
- `get_current_user_id(token)` — 从 JWT 提取 user_id，验证 type=access
- `get_current_user(token)` — 返回 CurrentUser(user_id, username, is_admin)
- `require_admin(current_user)` — 验证管理员权限，否则 403

**默认管理员**: 启动时 `ensure_default_admin_user()` 用 Mongo 凭据创建/更新管理员账号，密码以 bcrypt 哈希存储。

### 2. WebSocket 实时推送 (websocket.py)

**连接管理** (`ConnectionManager`):
- `_connections`: user_id → Set[WebSocket]，支持单用户多连接
- `_task_subscribers`: task_id → Set[user_id]，任务订阅关系

**核心方法**:
- `connect(ws, user_id)` — 接受 WebSocket 连接，注册到用户连接池
- `disconnect(ws, user_id)` — 移除连接
- `send_to_user(user_id, message)` — 向用户所有连接广播消息
- `subscribe_task(user_id, task_id)` — 订阅任务进度
- `unsubscribe_task(user_id, task_id)` — 取消订阅
- `broadcast_task_update(task_id, message)` — 向所有订阅者广播任务更新

**认证**: WebSocket 连接通过 `?token=` 查询参数传递 JWT，`verify_token()` 验证并返回 user_id。

### 3. 任务系统 (task.py)

**任务提交流程**: 接收前端任务请求 → 写入 Redis 队列 → 对应节点消费 → 结果通过 WebSocket 实时推送

**特殊处理**:
- stock_name 缓存：创建 task 时自动缓存 `ts_code → stock_name` 映射（24小时 TTL）
- ts_code 标准化：自动修复 7 位代码（如 `0000001.SZ` → `000001.SZ`）

### 4. 中间件

- **CORS**: debug 模式允许所有来源，生产模式仅允许 `localhost:5173`
- **Trace ID**: 每个请求注入 `X-Trace-ID`（请求头传入或自动生成），响应的 Response Header 中返回

### 5. 健康检查

`GET /health` — 检查 MongoDB、Redis 等管理器连接状态，返回 `{"status": "healthy/unhealthy", "managers": {...}}`

## 配置依赖

| 配置项 | 说明 |
|--------|------|
| `JWT_SECRET` | JWT 签名密钥 |
| `JWT_EXPIRE_MINUTES` | access_token 有效期 |
| `JWT_ALGORITHM` | JWT 签名算法（默认 HS256） |
| `MONGO_*` | MongoDB 连接（用户数据存储） |
| `REDIS_*` | Redis 连接（任务队列/发布订阅） |
| `WEB_HOST` / `WEB_PORT` | Web 服务监听地址 |
| `DEBUG` | 调试模式（控制 CORS 和 API 文档） |
