# Web API 网关 测试用例

## TC-WEB-01: 用户注册流程

**测试目标**: 验证完整的用户注册流程。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | POST `/api/v1/auth/register` body: `{username:"testuser", email:"test@example.com", password:"Test1234!"}` | 返回 `RegisterResponse{user_id, username, message="注册成功"}` |
| 2 | 检查 MongoDB `users` 集合 | 新增一条记录，`username="testuser"`，`password_hash` 为 bcrypt 哈希，`is_admin=False` |
| 3 | 再次用相同 username 注册 | 返回 400: `{"detail": "用户名已存在"}` |
| 4 | 用相同 email 不同 username 注册 | 返回 400: `{"detail": "邮箱已被注册"}` |

---

## TC-WEB-02: 登录与 Token 刷新

**测试目标**: 验证 JWT 双 Token 机制。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | POST `/api/v1/auth/login` form: `username, password` | 返回 `TokenResponse{access_token, refresh_token, token_type="bearer", user_id, username}` |
| 2 | 解码 `access_token` | `sub`=user_id, `type`="access", `exp` 在配置的有效期内 |
| 3 | 解码 `refresh_token` | `sub`=user_id, `type`="refresh", `exp` 约 30 天后 |
| 4 | POST `/api/v1/auth/refresh` body: `{refresh_token}` | 返回新的 `access_token` 和 `refresh_token` |
| 5 | 用错误密码登录 | 返回 401: `{"detail": "用户名或密码错误"}` |
| 6 | 用不存在的用户名登录 | 返回 401 |

---

## TC-WEB-03: JWT 鉴权拦截

**测试目标**: 验证未认证请求被正确拦截。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 不带 Token 访问 `GET /api/v1/tasks/xxx` | 返回 401: `{"detail": "无效的认证凭据"}` |
| 2 | 带过期 Token 访问 | 返回 401 |
| 3 | 带 refresh_token (type≠access) 访问 | 返回 401 |
| 4 | 带有效 access_token 访问 | 正常返回数据 |

---

## TC-WEB-04: 管理员权限控制

**测试目标**: 验证 `require_admin` 依赖注入。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 普通用户访问管理员接口 | 返回 403: `{"detail": "需要管理员权限"}` |
| 2 | 管理员用户访问管理员接口 | 正常执行 |
| 3 | 未登录用户访问管理员接口 | 返回 401（先被认证拦截） |

---

## TC-WEB-05: WebSocket 连接与消息推送

**测试目标**: 验证 WebSocket 实时通信链路。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 建立 WebSocket 连接 `ws://host/ws?token=<valid_access_token>` | 连接成功，`ConnectionManager.connect()` 被调用 |
| 2 | 同一 user_id 建立第二个连接 | 两个连接都加入 `_connections[user_id]` |
| 3 | `manager.send_to_user(user_id, {"type":"test"})` | 该用户所有连接都收到消息 |
| 4 | 订阅任务 `subscribe_task(user_id, task_id)` | `_task_subscribers[task_id]` 包含 user_id |
| 5 | `broadcast_task_update(task_id, {"progress":50})` | 所有订阅该任务的用户收到进度更新 |
| 6 | 断开一个连接 | `disconnect()` 移除该连接，其他连接不受影响 |
| 7 | 用户所有连接断开 | `_connections[user_id]` 被删除 |
| 8 | 不带 Token 连接 WebSocket | 连接被拒绝 |

---

## TC-WEB-06: 密码修改

**测试目标**: 验证密码修改流程。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | POST `/api/v1/auth/change-password` body: `{old_password:"wrong", new_password:"New1234!"}` | 返回 400: `{"detail": "原密码错误"}` |
| 2 | POST 正确的 `old_password` 和 `new_password` | 返回 `{"message": "密码修改成功"}` |
| 3 | 用旧密码登录 | 返回 401 |
| 4 | 用新密码登录 | 登录成功，last_login 更新 |

---

## TC-WEB-07: 默认管理员创建

**测试目标**: 验证 `ensure_default_admin_user` 逻辑。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 首次启动，users 集合为空 | 自动创建管理员用户（username=MongoDB 用户名），`is_admin=True` |
| 2 | 再次启动，管理员密码未变 | 不修改 password_hash，更新 is_admin=True |
| 3 | 修改 Mongo 密码后重启 | `verify_password` 失败，自动更新 password_hash |

---

## TC-WEB-08: Trace ID 中间件

**测试目标**: 验证请求追踪机制。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 请求带 `X-Trace-ID: custom-id-123` | Response Header 中 `X-Trace-ID: custom-id-123` |
| 2 | 请求不带 `X-Trace-ID` | Response Header 中 `X-Trace-ID` 为自动生成的 32 位 hex |
| 3 | `request.state.trace_id` 可访问 | 下游代码能获取 trace_id |

---

## TC-WEB-09: CORS 配置

**测试目标**: 验证跨域配置按环境切换。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | DEBUG=true 时请求带任意 Origin | `Access-Control-Allow-Origin: *` |
| 2 | DEBUG=false 时从 `localhost:5173` 请求 | CORS 通过 |
| 3 | DEBUG=false 时从其他 Origin 请求 | CORS 拒绝 |

---

## TC-WEB-10: 健康检查

**测试目标**: 验证健康检查端点。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | GET `/health`，所有管理器正常 | `{"status": "healthy", "managers": {"mongodb": true, "redis": true, ...}}` |
| 2 | GET `/health`，MongoDB 不可用 | `{"status": "unhealthy", "managers": {"mongodb": false, ...}}` |

---

## TC-WEB-11: API 文档访问控制

**测试目标**: 验证 Swagger/ReDoc 文档的访问控制。

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | DEBUG=true 访问 `/docs` | Swagger UI 正常显示 |
| 2 | DEBUG=false 访问 `/docs` | 404 或不可访问 |
| 3 | DEBUG=true 访问 `/redoc` | ReDoc 正常显示 |
| 4 | DEBUG=false 访问 `/redoc` | 404 或不可访问 |

---

## 代码走查验证结果

**走查日期**: 2026-06-21 | **方法**: 代码走查 | **结果**: 11/11 通过

| 用例 | 结果 | 走查依据 |
|------|------|----------|
| TC-WEB-01 | ✅ PASS | auth.py:168-203: `register()` 检查 username/email 重复 (line 172-181), `password_hash` 为 bcrypt (line 191), `is_admin=False` (line 196), message="注册成功" (line 202) |
| TC-WEB-02 | ✅ PASS | auth.py:206-254 login (line 206-254): access_token type="access" (line 86), refresh_token type="refresh" (line 98, 30天过期 line 98), refresh 端点 (line 257-289), 密码错误→401 (line 229-235) |
| TC-WEB-03 | ✅ PASS | auth.py:108-132: `get_current_user_id()` token_type must be "access" (line 126), JWTError→401 detail="无效的认证凭据" (line 111-112) |
| TC-WEB-04 | ✅ PASS | auth.py:155-162: `require_admin()` checks `current_user.is_admin` → 403 "需要管理员权限"; unauthenticated users caught by `get_current_user` dependency first → 401 |
| TC-WEB-05 | ✅ PASS | websocket.py:25-74: ConnectionManager.connect() (line 34-40), multi-connections per user (set per user_id), send_to_user (line 49-56), subscribe_task (line 58-62), broadcast_task_update (line 69-73), disconnect removes connection (line 42-47), token verified before connect (line 79+) |
| TC-WEB-06 | ✅ PASS | auth.py:299-317: `change_password()` verifies old_password (line 308) → 400, updates password_hash (line 314), returns "密码修改成功" (line 317) |
| TC-WEB-07 | ✅ PASS | app.py:28-72: `ensure_default_admin_user()` uses Mongo admin username (line 30-32), if existing verifies/changes password (line 39-54), new user gets is_admin=True (line 68) |
| TC-WEB-08 | ✅ PASS | app.py:124-133: trace_id_middleware reads X-Trace-ID header (line 127), auto-generates uuid4 hex (32 chars), sets on request.state (line 128), response header X-Trace-ID (line 131) |
| TC-WEB-09 | ✅ PASS | app.py:115-121: allow_origins=["*"] if DEBUG else ["http://localhost:5173"] (line 117), allow_credentials=True/allow_methods/allow_headers (line 118-120) |
| TC-WEB-10 | ✅ PASS | app.py:138-149: /health endpoint calls health_check_all(), all True→"healthy", any False→"unhealthy" (line 144-148) |
| TC-WEB-11 | ✅ PASS | app.py:102-110: FastAPI docs_url="/docs" if settings.debug else None (line 108), redoc_url="/redoc" if settings.debug else None (line 109) |
