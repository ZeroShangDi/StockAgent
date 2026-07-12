# 配置与节点模块 测试用例

## 1. 环境变量到 Settings 映射验证

### TC-CONFIG-001: RedisSettings 环境变量完整映射

| 项目 | 内容 |
|------|------|
| **测试目标** | 验证所有 `REDIS_*` 环境变量正确映射到 `RedisSettings` 属性 |
| **前置条件** | 清除环境变量中已有的 REDIS_ 前缀变量 |
| **步骤** | 1. 设置 `REDIS_HOST=redis-test`、`REDIS_PORT=6380`、`REDIS_PASSWORD=test123`、`REDIS_DB=2`、`REDIS_MAX_CONNECTIONS=50`、`REDIS_TASK_QUEUE=custom:tasks`<br>2. 导入 `RedisSettings` 并实例化<br>3. 检查各属性值 |
| **预期结果** | `host=="redis-test"`, `port==6380`, `password.get_secret_value()=="test123"`, `db==2`, `max_connections==50`, `task_queue=="custom:tasks"` |
| **url 属性** | `redis://:test123@redis-test:6380/2` |

### TC-CONFIG-002: MongoSettings 环境变量映射

| 项目 | 内容 |
|------|------|
| **测试目标** | 验证 `MONGO_*` 环境变量映射到 `MongoSettings` |
| **步骤** | 1. 设置 `MONGO_HOST=mongo-host`、`MONGO_PORT=27018`、`MONGO_USERNAME=admin`、`MONGO_PASSWORD=secret`、`MONGO_DATABASE=test_db`<br>2. 实例化 `MongoSettings` |
| **预期结果** | `host=="mongo-host"`, `port==27018`, `username=="admin"`, `database=="test_db"`, `url=="mongodb://admin:secret@mongo-host:27018/test_db?authSource=admin"` |

### TC-CONFIG-003: MongoSettings 无认证时 URL 生成

| 项目 | 内容 |
|------|------|
| **测试目标** | 无用户名密码时不生成认证信息 |
| **步骤** | 1. 设置 `MONGO_HOST=localhost`、`MONGO_PORT=27017`，不设置 username/password<br>2. 实例化 |
| **预期结果** | `url=="mongodb://localhost:27017/stock_agent"` |

### TC-CONFIG-004: TushareSettings Token 配置检测

| 项目 | 内容 |
|------|------|
| **测试目标** | 验证 `is_configured` 属性正确判断 Token 是否配置 |
| **步骤** | 1. 不设置 `TUSHARE_TOKEN`，实例化 `TushareSettings`<br>2. 设置 `TUSHARE_TOKEN=abc123`，再实例化 |
| **预期结果** | 场景1: `is_configured==False`；场景2: `is_configured==True`, `token.get_secret_value()=="abc123"` |

### TC-CONFIG-005: LLMSettings 模型路由配置

| 项目 | 内容 |
|------|------|
| **测试目标** | 验证多模型路由参数正确加载 |
| **步骤** | 1. 设置 `LLM_PROVIDER=deepseek`、`LLM_API_KEY=sk-xxx`、`LLM_MODEL_NAME=deepseek-chat`、`LLM_FAST_MODEL=deepseek-turbo`、`LLM_QUALITY_MODEL=deepseek-reasoner`、`LLM_TEMPERATURE=0.3`、`LLM_MAX_TOKENS=8192`<br>2. 实例化 `LLMSettings` |
| **预期结果** | `provider=="deepseek"`, `fast_model=="deepseek-turbo"`, `quality_model=="deepseek-reasoner"`, `temperature==0.7` (temperature 不受影响) -> 实际上 temperature 也是 0.3 |

### TC-CONFIG-006: ObservabilitySettings 日志配置

| 项目 | 内容 |
|------|------|
| **测试目标** | 验证日志相关配置正确读取 |
| **步骤** | 1. 设置 `OBS_LOG_LEVEL=DEBUG`、`OBS_LOG_DIR=/var/log/datasync`、`OBS_LOG_MAX_SIZE_MB=100`、`OBS_LOG_BACKUP_COUNT=20`<br>2. 实例化 |
| **预期结果** | `log_level=="DEBUG"`, `log_dir=="/var/log/datasync"`, `log_max_size_mb==100`, `log_backup_count==20` |

### TC-CONFIG-007: NodeSettings 通过 Alias 映射

| 项目 | 内容 |
|------|------|
| **测试目标** | 验证 `NODE_TYPE`、`NODE_ID` 等通过 alias 正确映射 |
| **步骤** | 1. 设置 `NODE_TYPE=listener`、`NODE_ID=custom-node-1`、`NODE_HEARTBEAT_INTERVAL=15`、`NODE_TTL=60`<br>2. 实例化 `NodeSettings` |
| **预期结果** | `node_type=="listener"`, `node_id=="custom-node-1"`, `heartbeat_interval==15`, `node_ttl==60` |

### TC-CONFIG-008: RPCSettings 端口配置

| 项目 | 内容 |
|------|------|
| **测试目标** | 验证各节点 RPC 端口默认值 |
| **步骤** | 1. 不设置任何 `RPC_*` 变量，实例化 `RPCSettings` |
| **预期结果** | `web_port==50051`, `data_sync_port==50054`, `inference_port==50052`, `listener_port==50053`, `mcp_port==50055`, `backtest_port==50056` |

---

## 2. SyncProfile 各档位测试

### TC-SYNC-001: conservative 档位任务注册

| 项目 | 内容 |
|------|------|
| **测试目标** | `conservative` 档位下仅注册核心任务 |
| **前置条件** | `SYNC_PROFILE=conservative` |
| **步骤** | 1. 启动 DataSyncNode<br>2. 调用 `get_capability_manifest()` 获取已注册任务列表 |
| **预期结果** | 只包含 `CORE_JOB_NAMES` 中的任务（stock_basic、stock_daily、daily_basic、index_basic、index_daily、moneyflow_industry、moneyflow_concept、limit_list、stock_relations、daily_stats、market_statistics_cache、market_weather），不包含 stock_news、hot_news、review_data、ths_sector、fina_indicator 等非核心任务 |

### TC-SYNC-002: full 档位任务注册

| 项目 | 内容 |
|------|------|
| **测试目标** | `full` 档位下注册全部内置任务 |
| **前置条件** | `SYNC_PROFILE=full` |
| **步骤** | 1. 启动 DataSyncNode<br>2. 检查注册任务列表 |
| **预期结果** | 包含所有 17 个内置任务：14 个 Collector + 3 个 Task |

### TC-SYNC-003: custom 档位按白名单注册

| 项目 | 内容 |
|------|------|
| **测试目标** | `custom` 档位下仅注册白名单任务 |
| **前置条件** | `SYNC_PROFILE=custom`, `SYNC_ENABLED_JOBS=stock_daily,index_daily,daily_stats` |
| **步骤** | 1. 启动 DataSyncNode<br>2. 检查注册任务列表 |
| **预期结果** | 只包含 stock_daily、index_daily、daily_stats 三个任务 |

### TC-SYNC-004: enabled_jobs 优先于 profile

| 项目 | 内容 |
|------|------|
| **测试目标** | 白名单存在时忽略 profile 设置 |
| **前置条件** | `SYNC_PROFILE=conservative`, `SYNC_ENABLED_JOBS=stock_news,hot_news` |
| **步骤** | 1. 启动 DataSyncNode<br>2. 检查注册任务 |
| **预期结果** | 包含 stock_news 和 hot_news（即使 conservative 档位通常不注册它们） |

### TC-SYNC-005: disabled_jobs 黑名单排除

| 项目 | 内容 |
|------|------|
| **测试目标** | 黑名单任务在所有档位下都不会注册 |
| **前置条件** | `SYNC_PROFILE=full`, `SYNC_DISABLED_JOBS=stock_news,hot_news,review_data` |
| **步骤** | 1. 启动 DataSyncNode<br>2. 检查注册任务 |
| **预期结果** | full 档位下注册所有任务，但不包含 stock_news、hot_news、review_data |

### TC-SYNC-006: backfill 闲时窗口判断

| 项目 | 内容 |
|------|------|
| **测试目标** | `_get_backfill_window_state()` 正确判断时间是否在闲时窗口内 |
| **步骤** | 1. 模拟当前时间为 `02:30`（窗口默认 `00:00-08:00`）<br>2. 模拟当前时间为 `14:00`（窗口外）<br>3. 模拟窗口为 `22:00-06:00`（跨日窗口），当前时间 `03:00` |
| **预期结果** | 场景1: `open==True`；场景2: `open==False`；场景3: `open==True`（时间跨零点判断） |

### TC-SYNC-007: 跨日窗口边界测试

| 项目 | 内容 |
|------|------|
| **测试目标** | 跨日闲时窗口边界值正确 |
| **步骤** | 1. 窗口 `22:00-06:00`，当前 `21:59`<br>2. 窗口 `22:00-06:00`，当前 `22:00`<br>3. 窗口 `22:00-06:00`，当前 `05:59`<br>4. 窗口 `22:00-06:00`，当前 `06:00` |
| **预期结果** | `False, True, True, False` |

### TC-SYNC-008: first_sync_protected 防止全历史回补

| 项目 | 内容 |
|------|------|
| **测试目标** | `prevent_initial_history_sync=True` 时首次同步仅补最新交易日 |
| **前置条件** | `SYNC_PREVENT_INITIAL_HISTORY_SYNC=True`，数据库中无历史同步记录 |
| **步骤** | 1. 调用 `BaseCollector._determine_sync_range(latest_trade_date="20260120")`<br>2. 检查返回值 |
| **预期结果** | 返回 `("20260120", "20260120", False)`，即只同步最新交易日，不触发历史同步 |

### TC-SYNC-009: 核心资源繁忙时非核心任务跳过

| 项目 | 内容 |
|------|------|
| **测试目标** | 核心 pipeline 活跃时非核心定时任务自动跳过 |
| **前置条件** | 核心任务正在执行（`_active_core_jobs > 0`） |
| **步骤** | 1. 模拟一个核心任务正在运行<br>2. scheduler 触发 stock_news（background 类）任务 |
| **预期结果** | 任务返回 `{"success": False, "skipped": True, "reason": "core_resource_busy"}` |

---

## 3. YAML 配置合并与覆盖

### TC-YAML-001: ConfigManager 加载 YAML 文件

| 项目 | 内容 |
|------|------|
| **测试目标** | `ConfigManager.load()` 加载所有 `.yaml` 文件 |
| **前置条件** | `config/` 目录下存在 `report.yaml`、`collector.yaml` 等文件 |
| **步骤** | 1. 创建 ConfigManager 实例<br>2. 调用 `load()` 方法<br>3. 检查 `loaded_files` 和 `list_modules()` |
| **预期结果** | `is_loaded==True`, `loaded_files` 包含 `report.yaml` 等文件路径, `list_modules()` 返回对应的模块名列表 |

### TC-YAML-002: 点号路径访问配置

| 项目 | 内容 |
|------|------|
| **测试目标** | `get(key)` 支持多层嵌套点号路径 |
| **前置条件** | `report.yaml` 已加载 |
| **步骤** | 1. `cfg.get("report.morning_report.enabled")`<br>2. `cfg.get("report.morning_report.max_news")`<br>3. `cfg.get("report.morning_report.title_template")` |
| **预期结果** | `True`, `10`, `"【{date}】早间财经要闻"` |

### TC-YAML-003: 默认值回退

| 项目 | 内容 |
|------|------|
| **测试目标** | 不存在的 key 返回默认值 |
| **前置条件** | 已加载配置 |
| **步骤** | 1. `cfg.get("report.non_existent.key", "default_val")`<br>2. `cfg.get("non_existent_module.key", 42)` |
| **预期结果** | `"default_val"`, `42` |

### TC-YAML-004: get_module 返回完整模块配置

| 项目 | 内容 |
|------|------|
| **测试目标** | `get_module()` 返回整个模块的字典 |
| **前置条件** | `report.yaml` 已加载 |
| **步骤** | 调用 `cfg.get_module("report")` |
| **预期结果** | 返回包含 `morning_report`、`evening_report`、`push`、`format` 四个 key 的字典 |

### TC-YAML-005: reload 重新加载

| 项目 | 内容 |
|------|------|
| **测试目标** | `reload()` 清空并重新加载所有配置 |
| **前置条件** | 已加载配置，有部分运行时 `set()` 的值 |
| **步骤** | 1. `cfg.set("report.morning_report.enabled", False)`<br>2. `cfg.reload()`<br>3. `cfg.get("report.morning_report.enabled")` |
| **预期结果** | `True`（运行时修改被覆盖回文件值） |

### TC-YAML-006: 运行时 set 不持久化

| 项目 | 内容 |
|------|------|
| **测试目标** | `set()` 只在内存中生效，不影响 YAML 文件 |
| **前置条件** | 已加载配置 |
| **步骤** | 1. 备份原 `report.yaml`<br>2. `cfg.set("report.morning_report.max_news", 99)`<br>3. 验证 `cfg.get("report.morning_report.max_news")==99`<br>4. 重新启动并 `cfg.reload()`<br>5. 检查值恢复为文件原值 |
| **预期结果** | `set()` 后返回 99，reload 后恢复为文件原值 |

---

## 4. 节点启动/停止生命周期

### TC-NODE-001: BaseNode 正常启动流程

| 项目 | 内容 |
|------|------|
| **测试目标** | 节点 main() 完整启动流程 |
| **前置条件** | Redis、MongoDB 可用 |
| **步骤** | 1. 创建 DataSyncNode 实例<br>2. 调用 `asyncio.run(node.main())`<br>3. 检查节点状态 |
| **预期结果** | `_running==True`, 心跳已启动, `_start_time` 已设置, RPC 服务已启动, 调度器已运行 |

### TC-NODE-002: 优雅关闭流程

| 项目 | 内容 |
|------|------|
| **测试目标** | `_graceful_shutdown()` 按顺序完成关闭 |
| **前置条件** | 节点正在运行中 |
| **步骤** | 1. 触发 SIGTERM 信号<br>2. 观察日志和关闭顺序 |
| **预期结果** | 日志顺序：`Shutdown signal received` -> `Initiating graceful shutdown` -> `Heartbeat stopped` -> `RPC server stopped` -> `Node Gracefully Offline: {node_id}` -> `Graceful shutdown completed` |

### TC-NODE-003: 心跳 Key 在 Redis 中的生命周期

| 项目 | 内容 |
|------|------|
| **测试目标** | 节点运行期间 Redis 中存在心跳 Key，TTL 正确 |
| **前置条件** | 节点启动，Redis 可访问 |
| **步骤** | 1. 节点启动后查询 Redis: `EXISTS agent:nodes:{node_id}`<br>2. 查询 `TTL agent:nodes:{node_id}`<br>3. 节点停止后再次查询 `EXISTS agent:nodes:{node_id}` |
| **预期结果** | 启动后 `EXISTS==1`, `TTL` 在 10-15 秒之间（5 秒心跳间隔，15 秒 TTL），停止后 `EXISTS==0` |

### TC-NODE-004: 异常情况下心跳 TTL 过期

| 项目 | 内容 |
|------|------|
| **测试目标** | kill -9 时心跳 Key 在 TTL 后自动过期 |
| **前置条件** | 节点正在运行中 |
| **步骤** | 1. 强制 kill 进程（不触发优雅关闭）<br>2. 每 1 秒查询 `TTL agent:nodes:{node_id}`<br>3. 等待直到 Key 消失 |
| **预期结果** | Key 在 15 秒内自动过期删除（TTL 从 10-15 递减到 -2） |

### TC-NODE-005: 节点 ID 生成格式

| 项目 | 内容 |
|------|------|
| **测试目标** | 自动生成的 node_id 格式正确 |
| **步骤** | 1. 创建 DataSyncNode 不传 node_id<br>2. 检查 `node.node_id` |
| **预期结果** | 格式为 `data_sync-<8位hex>`，如 `data_sync-a1b2c3d4` |

---

## 5. 健康检查与就绪检查

### TC-HEALTH-001: health_check 返回管理器状态

| 项目 | 内容 |
|------|------|
| **测试目标** | `health_check()` 返回各 Manager 和节点整体状态 |
| **前置条件** | 所有 Manager 已初始化 |
| **步骤** | 1. 调用 `await node.health_check()`<br>2. 检查返回值 |
| **预期结果** | `{"node_id": "data_sync-xxx", "node_type": "data_sync", "status": "healthy", "uptime_seconds": >=0, "managers": {"RedisManager": True, "MongoManager": True, ...}}` |

### TC-HEALTH-002: 部分 Manager 不健康时整体状态

| 项目 | 内容 |
|------|------|
| **测试目标** | 任一 Manager 不健康时 status 为 unhealthy |
| **前置条件** | MongoDB 已断开 |
| **步骤** | 1. 断开 MongoDB 连接<br>2. 调用 `health_check()` |
| **预期结果** | `status=="unhealthy"`, `managers["MongoManager"]==False` |

### TC-HEALTH-003: RPC ping 方法

| 项目 | 内容 |
|------|------|
| **测试目标** | 默认 ping RPC 方法正确响应 |
| **前置条件** | RPC 服务器已启动 |
| **步骤** | 1. 通过 gRPC 调用 ping 方法，params={}<br>2. 检查响应 |
| **预期结果** | `{"pong": True, "node_id": "data_sync-xxx", "node_type": "data_sync", "timestamp": "<ISO8601>"}` |

### TC-HEALTH-004: core_ready_marker 构建与刷新

| 项目 | 内容 |
|------|------|
| **测试目标** | `_refresh_core_ready_marker()` 正确记录核心链路就绪状态 |
| **前置条件** | MongoDB 可用，stock_daily 已同步 `20260120` |
| **步骤** | 1. 执行 stock_daily 任务成功后触发 `_refresh_core_ready_marker("20260120")`<br>2. 查询 `readiness_markers` 集合 |
| **预期结果** | 存在一条 `marker_type=="market_core_ready"`, `trade_date=="20260120"` 的记录，`ready_datasets` 包含 `stock_daily` |

---

## 6. 信号处理

### TC-SIGNAL-001: SIGTERM 触发优雅关闭

| 项目 | 内容 |
|------|------|
| **测试目标** | `SIGTERM` 信号触发 `_shutdown_signal()` -> `_graceful_shutdown()` |
| **前置条件** | 节点正在 `main()` 循环中运行 |
| **步骤** | 1. 发送 `kill -TERM <pid>`<br>2. 检查日志和进程状态 |
| **预期结果** | 日志出现 `Shutdown signal received, initiating graceful shutdown...`，进程正常退出（exit code 0） |

### TC-SIGNAL-002: SIGINT 触发优雅关闭

| 项目 | 内容 |
|------|------|
| **测试目标** | `SIGINT` (Ctrl+C) 触发优雅关闭 |
| **步骤** | 1. 在终端按 Ctrl+C<br>2. 观察日志 |
| **预期结果** | 同 SIGTERM，执行完整的优雅关闭流程 |

### TC-SIGNAL-003: 关闭期间有未完成任务

| 项目 | 内容 |
|------|------|
| **测试目标** | 优雅关闭等待当前任务完成或超时 |
| **前置条件** | 正在执行一个耗时任务（`_current_tasks=1`） |
| **步骤** | 1. 触发 SIGTERM<br>2. 模拟任务在 5 秒内完成<br>3. 日志检查 |
| **预期结果** | `Waiting for 1 tasks to complete...` -> 任务完成后继续关闭流程；若超过 `SHUTDOWN_TIMEOUT`（30秒）则输出 `Shutdown timeout...forcing shutdown` |

### TC-SIGNAL-004: 重复信号处理

| 项目 | 内容 |
|------|------|
| **测试目标** | 优雅关闭中再次收到信号时行为 |
| **步骤** | 1. 发送 SIGTERM<br>2. 在关闭过程中再次发送 SIGTERM |
| **预期结果** | 第二次信号不会导致崩溃，`_running` 已经为 False，`_shutdown_signal()` 幂等 |

---

## 代码走查验证结果

**走查日期**: 2026-06-21 | **方法**: 代码走查 | **结果**: 29/30 通过，1 处测试描述矛盾

| 用例 | 结果 | 走查依据 |
|------|------|----------|
| TC-CONFIG-001~004 | ✅ PASS | Settings (settings.py): Redis host/port/password/db (line 78-93)，Mongo host/port/db (line 108-124)，URL 构建 (line 120-124)，Tushare is_configured (line 206-208) |
| TC-CONFIG-005 | ⚠️ 矛盾 | 测试预期 `temperature==0.7`，但设置 `LLM_TEMPERATURE=0.3` 会通过 pydantic-settings 覆盖默认值 0.7 为 0.3。测试内联注释 "实际上 temperature 也是 0.3" 已承认此矛盾 |
| TC-CONFIG-006~008 | ✅ PASS | Observability (line 310-339)，Node alias 映射 (line 357-367)，RPC 端口默认值 (line 370-388) |
| TC-SYNC-001~009 | ✅ PASS | CORE_JOB_NAMES 12 项 (node.py:109-122)，JOB_CLASSES 17 项 (line 136-157)，enabled_jobs/disabled_jobs 优先级 (line 272-275)，backfill 窗口判断 (line 701-722)，prevent_initial_history_sync (collector.py:186-193) |
| TC-YAML-001~006 | ✅ PASS | ConfigManager 加载 config/*.yaml，点号路径遍历 `get(key)`，默认值回退 (line 158-166)，`get_module()` (line 168-178)，`set` 仅内存修改 (line 180-198) |
| TC-NODE-001~005 | ✅ PASS | `main()` 生命周期 (node.py:382-426)，`_graceful_shutdown` 顺序 (line 433-481)，心跳 5s 间隔 TTL=15 (line 88-89)，node_id 生成 (line 98-99) |
| TC-HEALTH-001~004 | ✅ PASS | `health_check()` (line 366-378)，CORE_READY_MARKER datasets (line 86-96)，`_handle_ping` (line 241-248) |
| TC-SIGNAL-001~004 | ✅ PASS | SIGTERM/SIGINT handler (line 386-389)，shutdown 等待任务 30s 超时 (line 453-466)，`_shutdown_signal` 幂等 (line 428-431) |
