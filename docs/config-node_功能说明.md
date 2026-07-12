# 配置与节点模块 功能说明

## 概述

配置与节点模块负责 DataSync 服务的全局配置管理和节点生命周期管理，包含三个核心组件：
- **Pydantic Settings 配置模型** (`core/settings.py`) -- 通过环境变量管理所有运行参数
- **YAML 配置管理器** (`src/config/manager.py`) -- 管理 `config/` 目录下的 YAML 配置文件
- **节点基类** (`core/base/node.py`) -- 提供节点生命周期、心跳、RPC 注册、信号处理

---

## 1. Pydantic Settings 配置模型

文件位置：`DataSync/core/settings.py`

### 1.1 架构设计

主配置类 `Settings` 聚合 14 个子配置类，每个子配置类独立从环境变量读取，通过 `@property` 延迟加载，使用 `@lru_cache()` 缓存实例，确保全局单例。

```
Settings (主配置)
├── RedisSettings          # REDIS_ 前缀
├── MongoSettings          # MONGO_ 前缀
├── MongoMirrorSettings    # MONGO_MIRROR_ 前缀
├── MilvusSettings         # MILVUS_ 前缀
├── TushareSettings        # TUSHARE_ 前缀
├── CozeSettings           # COZE_ 前缀
├── LLMSettings            # LLM_ 前缀
├── ObservabilitySettings  # OBS_ 前缀
├── NodeSettings           # 无前缀 (NODE_TYPE, NODE_ID, ...)
├── DataSyncSettings       # SYNC_ 前缀
├── WebSettings            # WEB_ 前缀
├── ListenerSettings       # LISTENER_ 前缀
├── NotificationSettings   # NOTIFY_ 前缀
├── RPCSettings            # RPC_ 前缀
```

### 1.2 关键子配置详解

#### RedisSettings (env_prefix="REDIS_")

| 字段 | 环境变量 | 默认值 | 说明 |
|------|---------|--------|------|
| `host` | `REDIS_HOST` | `localhost` | 连接地址 |
| `port` | `REDIS_PORT` | `6379` | 端口 |
| `password` | `REDIS_PASSWORD` | None | SecretStr 类型 |
| `db` | `REDIS_DB` | `0` | 数据库编号 |
| `max_connections` | `REDIS_MAX_CONNECTIONS` | `30` | 连接池大小 |
| `task_queue` | `REDIS_TASK_QUEUE` | `agent:tasks` | 任务队列名 |
| `result_channel_prefix` | `REDIS_RESULT_CHANNEL_PREFIX` | `agent:results` | 结果频道前缀 |
| `node_registry_prefix` | `REDIS_NODE_REGISTRY_PREFIX` | `agent:nodes` | 节点注册前缀 |

属性 `url`：自动拼接认证信息和 Redis URL。

#### MongoSettings (env_prefix="MONGO_")

| 字段 | 环境变量 | 默认值 | 说明 |
|------|---------|--------|------|
| `host` | `MONGO_HOST` | `localhost` | 连接地址 |
| `port` | `MONGO_PORT` | `27017` | 端口 |
| `username` | `MONGO_USERNAME` | None | 用户名 |
| `password` | `MONGO_PASSWORD` | None | SecretStr 类型 |
| `database` | `MONGO_DATABASE` | `stock_agent` | 数据库名 |
| `max_pool_size` | `MONGO_MAX_POOL_SIZE` | `20` | 连接池大小 |
| `ensure_indexes` | `MONGO_ENSURE_INDEXES` | True | 启动时是否建索引 |
| `index_startup_scope` | `MONGO_INDEX_STARTUP_SCOPE` | `core` | 索引创建范围 |
| `index_create_timeout_seconds` | `MONGO_INDEX_CREATE_TIMEOUT_SECONDS` | `10` | 索引创建超时 |

#### MongoMirrorSettings (env_prefix="MONGO_MIRROR_")

用于主库数据的镜像同步目标库配置。与 MongoSettings 结构类似，`enabled` 默认为 `False`，`database` 默认为 `stock_agent_remote`。

#### TushareSettings (env_prefix="TUSHARE_")

| 字段 | 环境变量 | 默认值 | 说明 |
|------|---------|--------|------|
| `token` | `TUSHARE_TOKEN` | SecretStr("") | Tushare Pro API Token |
| `rate_limit` | `TUSHARE_RATE_LIMIT` | `200` | 每分钟请求数限制 |
| `batch_size` | `TUSHARE_BATCH_SIZE` | `100` | 批量请求大小 |

属性 `is_configured`：检查 Token 是否已配置。

#### CozeSettings (env_prefix="COZE_")

| 字段 | 环境变量 | 默认值 | 说明 |
|------|---------|--------|------|
| `api_token` | `COZE_API_TOKEN` | SecretStr("") | API Token |
| `api_base` | `COZE_API_BASE` | `https://api.coze.cn` | API 地址 |
| `workflow_id` | `COZE_WORKFLOW_ID` | `7635993821533487155` | 工作流 ID |
| `space_id` | `COZE_SPACE_ID` | `7492401860964810793` | 空间 ID |
| `market_indicator_workflow_id` | `COZE_MARKET_INDICATOR_WORKFLOW_ID` | `7587701552685629494` | 市场指标工作流 ID |
| `stock_picker_workflow_id` | `COZE_STOCK_PICKER_WORKFLOW_ID` | `7579577947649277987` | 选股工作流 ID |
| `timeout` | `COZE_TIMEOUT` | `30.0` | 请求超时（秒） |
| `max_retries` | `COZE_MAX_RETRIES` | `2` | 重试次数 |
| `retry_backoff_seconds` | `COZE_RETRY_BACKOFF_SECONDS` | `0.5` | 重试退避起始秒数 |
| `retry_backoff_max_seconds` | `COZE_RETRY_BACKOFF_MAX_SECONDS` | `5.0` | 最大退避秒数 |

#### LLMSettings (env_prefix="LLM_")

| 字段 | 环境变量 | 默认值 | 说明 |
|------|---------|--------|------|
| `provider` | `LLM_PROVIDER` | `dashscope` | 主提供商：openai/dashscope/zhipu/ollama/deepseek |
| `api_key` | `LLM_API_KEY` | None | API Key |
| `api_base` | `LLM_API_BASE` | None | API 基础 URL |
| `model_name` | `LLM_MODEL_NAME` | `qwen-plus` | 主模型名 |
| `embedding_model` | `LLM_EMBEDDING_MODEL` | `text-embedding-v3` | Embedding 模型 |
| `fast_model` | `LLM_FAST_MODEL` | None | 简单任务模型 |
| `balanced_model` | `LLM_BALANCED_MODEL` | None | 一般任务模型 |
| `quality_model` | `LLM_QUALITY_MODEL` | None | 复杂任务模型 |
| `temperature` | `LLM_TEMPERATURE` | `0.7` | 温度参数 |
| `max_tokens` | `LLM_MAX_TOKENS` | `4096` | 最大 Token 数 |
| `max_concurrent_requests` | `LLM_MAX_CONCURRENT_REQUESTS` | `10` | 并发限制 |
| `cache_enabled` | `LLM_CACHE_ENABLED` | True | 是否启用缓存 |
| `cache_chat_ttl` | `LLM_CACHE_CHAT_TTL` | `3600` | Chat 缓存 TTL（秒） |
| `cache_embedding_ttl` | `LLM_CACHE_EMBEDDING_TTL` | `86400` | Embedding 缓存 TTL（秒） |

#### ObservabilitySettings (env_prefix="OBS_")

| 字段 | 环境变量 | 默认值 | 说明 |
|------|---------|--------|------|
| `loki_url` | `OBS_LOKI_URL` | None | Loki 地址 |
| `loki_enabled` | `OBS_LOKI_ENABLED` | False | 是否启用 Loki |
| `phoenix_enabled` | `OBS_PHOENIX_ENABLED` | False | 是否启用 Phoenix 追踪 |
| `log_level` | `OBS_LOG_LEVEL` | `INFO` | 日志级别 |
| `log_to_file` | `OBS_LOG_TO_FILE` | True | 是否输出到文件 |
| `log_dir` | `OBS_LOG_DIR` | `logs` | 日志目录 |
| `log_max_size_mb` | `OBS_LOG_MAX_SIZE_MB` | `50` | 单文件最大 MB |
| `log_backup_count` | `OBS_LOG_BACKUP_COUNT` | `10` | 备份文件保留数 |
| `log_sample_limit` | `OBS_LOG_SAMPLE_LIMIT` | `5` | 坏数据样本数 |
| `log_max_value_chars` | `OBS_LOG_MAX_VALUE_CHARS` | `500` | 日志字段最大字符数 |

#### NodeSettings (无 env_prefix，使用 alias)

| 字段 | 环境变量/alias | 默认值 | 说明 |
|------|--------------|--------|------|
| `node_type` | `NODE_TYPE` | `data_sync` | 节点类型 |
| `node_id` | `NODE_ID` | None | 节点 ID（自动生成） |
| `heartbeat_interval` | `NODE_HEARTBEAT_INTERVAL` | `10` | 心跳间隔（秒） |
| `node_ttl` | `NODE_TTL` | `30` | 节点过期时间（秒） |

#### DataSyncSettings -- SyncProfile 档位与调度控制 (env_prefix="SYNC_")

这是最重要的配置子类，控制数据同步的所有行为。

**运行档位（profile）**：

| 档位 | 值 | 行为 |
|------|-----|------|
| `conservative` | 默认 | 仅注册核心市场链路任务（`CORE_JOB_NAMES` 中定义的任务） |
| `full` | 全量 | 注册全部内置任务，包括新闻、复盘、财务等 |
| `custom` | 自定义 | 仅注册 `enabled_jobs` 白名单中的任务 |

**任务注册优先级**：`enabled_jobs` 白名单 > `disabled_jobs` 黑名单 > `profile` 档位。

**核心调度字段**：

| 字段 | 环境变量 | 默认值 | 说明 |
|------|---------|--------|------|
| `max_running_jobs` | `SYNC_MAX_RUNNING_JOBS` | `1` | 最大并发任务数 |
| `max_parallel_collect_concurrency` | `SYNC_MAX_PARALLEL_COLLECT_CONCURRENCY` | `2` | 并行采集最大并发 |
| `job_timeout_seconds` | `SYNC_JOB_TIMEOUT_SECONDS` | `1200` | 任务超时（秒） |
| `lock_timeout_seconds` | `SYNC_LOCK_TIMEOUT_SECONDS` | `1200` | 分布式锁超时 |
| `scheduler_misfire_grace_seconds` | `SYNC_SCHEDULER_MISFIRE_GRACE_SECONDS` | `300` | 错过调度宽限期 |
| `prevent_initial_history_sync` | `SYNC_PREVENT_INITIAL_HISTORY_SYNC` | True | 首次运行禁止全历史回补 |
| `initial_backfill_days` | `SYNC_INITIAL_BACKFILL_DAYS` | `5` | 首次回补天数 |
| `run_initial_sync` | `SYNC_RUN_INITIAL_SYNC` | False | 启动后是否立即全量同步 |

**闲时窗口（Backfill Window）**：

| 字段 | 环境变量 | 默认值 | 说明 |
|------|---------|--------|------|
| `backfill_window_start` | `SYNC_BACKFILL_WINDOW_START` 或 `DATASYNC_BACKFILL_WINDOW_START` | `00:00` | 闲时窗口开始 |
| `backfill_window_end` | `SYNC_BACKFILL_WINDOW_END` 或 `DATASYNC_BACKFILL_WINDOW_END` | `08:00` | 闲时窗口结束 |
| `backfill_queue_schedule` | `SYNC_BACKFILL_QUEUE_SCHEDULE` | `*/30 * * * *` | 补缺队列调度 |
| `backfill_jobs_per_round` | `SYNC_BACKFILL_JOBS_PER_ROUND` | `2` | 每轮最多 job 数 |
| `backfill_max_attempts` | `SYNC_BACKFILL_MAX_ATTEMPTS` | `3` | 最大重试次数 |
| `backfill_max_jobs_per_night` | `SYNC_BACKFILL_MAX_JOBS_PER_NIGHT` 或 `DATASYNC_*` | `24` | 每晚最大 job 数 |
| `backfill_max_external_requests_per_night` | `SYNC_BACKFILL_MAX_EXTERNAL_REQUESTS_PER_NIGHT` 或 `DATASYNC_*` | `300` | 每晚最大外部请求 |
| `backfill_consecutive_failure_limit` | `SYNC_BACKFILL_CONSECUTIVE_FAILURE_LIMIT` 或 `DATASYNC_*` | `3` | 连续失败上限 |

**核心链路 SLA**：

| 字段 | 环境变量 | 默认值 | 说明 |
|------|---------|--------|------|
| `core_ready_check_after_local_time` | `SYNC_CORE_READY_CHECK_AFTER_LOCAL_TIME` | `15:30` | 开始观察时间 |
| `core_ready_expected_after_local_time` | `SYNC_CORE_READY_EXPECTED_AFTER_LOCAL_TIME` | `16:10` | 期望就绪时间 |
| `core_ready_fail_after_local_time` | `SYNC_CORE_READY_FAIL_AFTER_LOCAL_TIME` | `17:00` | 失败告警时间 |
| `run_core_gap_recovery_on_startup` | `SYNC_RUN_CORE_GAP_RECOVERY_ON_STARTUP` | True | 启动时执行缺口恢复 |
| `recent_core_gap_recovery_days` | `SYNC_RECENT_CORE_GAP_RECOVERY_DAYS` | `3` | 缺口恢复检查天数 |

**批量写入控制**：

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `dead_letter_max_records_per_batch` | `20` | 单批次死信上限 |
| `bulk_upsert_batch_size` | `1000` | 幂等批量写入批次大小 |
| `bulk_upsert_min_batch_size` | `100` | 自适应批次下限 |
| `bulk_upsert_max_batch_size` | `1000` | 自适应批次上限 |
| `bulk_upsert_slow_batch_ms` | `1500` | 慢批次阈值 (ms) |
| `bulk_upsert_stable_batches_to_grow` | `3` | 连续稳定批次后方可扩容 |

**各类调度时间（Cron 表达式）**：
- `stock_basic_schedule` -- 股票基础信息（默认每个交易日 9:00）
- `stock_daily_schedule` -- 日线数据（默认每个交易日 15:30）
- `daily_basic_schedule` -- 基础指标（默认每个交易日 16:00）
- `index_daily_schedule` -- 指数日线（默认每个交易日 15:35）
- `limit_list_schedule` -- 涨跌停（默认每个交易日 16:10）
- `news_schedule` -- 新闻采集（默认每 2 小时）
- `market_weather_schedule` -- 晴雨表（收盘后执行）
- `review_data_schedule` -- 复盘数据（默认每个交易日 19:30）
- `fina_indicator_schedule` -- 财务数据（默认每月 1 日 9:00）

#### RPCSettings (env_prefix="RPC_")

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `web_port` | `50051` | Web 节点端口 |
| `inference_port` | `50052` | Inference 节点端口 |
| `listener_port` | `50053` | Listener 节点端口 |
| `data_sync_port` | `50054` | DataSync 节点端口 |
| `mcp_port` | `50055` | MCP 节点端口 |
| `backtest_port` | `50056` | Backtest 节点端口 |
| `timeout` | `10.0` | RPC 超时（秒） |
| `max_retries` | `3` | 重试次数 |

### 1.3 使用方式

```python
from core.settings import settings

# 访问子配置
redis_host = settings.redis.host
mongo_db = settings.mongo.database
tushare_token = settings.tushare.token.get_secret_value()
profile = settings.data_sync.profile    # "conservative" / "full" / "custom"
```

SecretStr 类型的敏感字段通过 `.get_secret_value()` 获取明文。

### 1.4 容器内地址规范化

`normalize_local_service_host()` 函数在非容器环境下将 Docker Compose 风格的主机名（如 `redis`、`mongodb`、`milvus`）自动转换为 `localhost`，通过 `/.dockerenv` 文件或 `DATASYNC_IN_DOCKER` 环境变量判断运行环境。

---

## 2. YAML 配置管理器 (ConfigManager)

文件位置：`DataSync/src/config/manager.py`

### 2.1 核心设计

`ConfigManager` 是一个全局单例模式（`__new__` 方法控制），管理 `DataSync/config/` 目录下所有 YAML 配置文件。

```
config/
├── collector.yaml         # 新闻采集器配置
├── datasync_capabilities.yaml  # 数据能力声明
├── news_filter.yaml       # 新闻筛选配置
├── report.yaml            # 报告生成配置
├── review.yaml            # 复盘配置
└── prompts/               # LLM Prompt 模板
```

### 2.2 主要方法

| 方法 | 签名 | 说明 |
|------|------|------|
| `load(config_dir, reload)` | `-> int` | 加载所有 `.yaml` 和 `.yml` 文件，返回加载数量 |
| `get(key, default)` | `-> Any` | 点号路径访问，如 `"report.morning_report.enabled"` |
| `get_module(module_name)` | `-> dict` | 获取整个模块配置 |
| `set(key, value)` | `-> None` | 运行时设置（不持久化） |
| `has(key)` | `-> bool` | 检查配置是否存在 |
| `reload()` | `-> int` | 重新加载所有配置 |
| `list_modules()` | `-> list` | 列出所有已加载模块名 |
| `to_dict()` | `-> dict` | 导出全部配置 |

### 2.3 加载机制

- 启动时调用 `config_manager.load()` 一次性加载所有文件到内存
- 每个 YAML 文件以文件名（不含扩展名）作为模块名 key
- 支持 `.yaml` 和 `.yml` 两种扩展名
- 配置目录不存在时自动创建

### 2.4 配置合并与覆盖

- 同一模块名不会重复加载（先加载 `.yaml`，再跳过同名 `.yml`）
- `reload=True` 时清空所有现有配置重新加载
- 运行时 `set()` 仅在内存中生效，不写回文件

### 2.5 配置示例

`config/report.yaml` 示例结构：
```yaml
morning_report:
  enabled: true
  schedule: "0 8 * * 1-5"
  max_news: 10
  title_template: "【{date}】早间财经要闻"

evening_report:
  enabled: true
  schedule: "0 18 * * 1-5"
  max_news: 8

push:
  wecom_enabled: true
  max_retries: 3

format:
  date_format: "%Y年%m月%d日"
  max_summary_length: 200
```

访问方式：
```python
from src.config.manager import config_manager
config_manager.get("report.morning_report.max_news")  # 10
config_manager.get("report.push.wecom_enabled")        # True
```

---

## 3. YAML 配置文件结构

### collector.yaml

新闻采集器通用配置：
- `general` -- 默认采集间隔、最大数量、并发数、超时、重试
- `dedup` -- 去重配置，按源优先级的 TTL、事件核心指纹
- 各数据源独立配置块

### report.yaml

报告生成配置：早报 `morning_report` / 晚报 `evening_report` 的启用、调度、推送、格式化参数。

### news_filter.yaml

新闻筛选规则：噪音关键词、核心主体关键词、政策级别映射、行业分类规则等。

### review.yaml

复盘数据配置：各类复盘维度的数据源、参数、阈值。

### datasync_capabilities.yaml

数据能力声明：所有任务的能力元数据、数据源链路覆盖。

---

## 4. 节点基类 (BaseNode)

文件位置：`DataSync/core/base/node.py`

### 4.1 概述

`BaseNode` 是所有节点类型的抽象基类（ABC），提供统一的生命周期管理、心跳、RPC、信号处理机制。

### 4.2 类属性

| 属性 | 默认值 | 说明 |
|------|--------|------|
| `node_type` | 子类必须定义 | NodeType 枚举值 |
| `HEARTBEAT_INTERVAL` | `5` | 心跳间隔（秒） |
| `HEARTBEAT_TTL` | `15` | 心跳 TTL（秒），超时未更新视为离线 |
| `SHUTDOWN_TIMEOUT` | `30` | 优雅关闭等待任务超时（秒） |
| `DEFAULT_RPC_PORT` | `50051` | 默认 RPC 端口 |

### 4.3 生命周期管理

```
main()                      # 入口
  ├── 注册信号处理 (SIGTERM, SIGINT)
  ├── _running = True
  ├── start()               # 子类实现，初始化 Manager、启动 RPC
  ├── _start_heartbeat()    # 心跳协程：每 5 秒写 Redis，TTL 15 秒
  ├── _gc_monitor()         # GC 监控协程：每 5 分钟触发 GC
  ├── run()                 # 子类实现，节点主循环
  └── _graceful_shutdown()  # 优雅关闭
       ├── 停止心跳
       ├── 等待当前任务完成 (最多 SHUTDOWN_TIMEOUT 秒)
       ├── 停止 RPC 服务
       ├── _unregister()   # 主动删除 Redis 心跳 Key
       ├── stop()          # 子类实现
       └── shutdown_all_managers()
```

### 4.4 心跳机制

- 每 `HEARTBEAT_INTERVAL` 秒（5 秒）向 Redis 写入节点信息
- Key 格式：`agent:nodes:{node_id}`
- TTL 为 `HEARTBEAT_TTL` 秒（15 秒）
- 15 秒内未收到心跳则该节点视为离线
- 优雅关闭时主动调用 `_unregister()` 删除心跳 Key

节点信息 `NodeInfo` 包含：
```python
NodeInfo(
    node_id=self.node_id,
    node_type=self.node_type,
    host=socket.gethostname(),
    port=os.environ.get("PORT", settings.web.port),
    status="online" / "busy" / "offline",
    last_heartbeat=datetime.now(UTC),
    current_tasks=self._current_tasks,
    max_tasks=self._max_tasks,
    rpc_address=self._rpc_address,
)
```

### 4.5 健康检查

`health_check()` 方法返回：
```python
{
    "node_id": "data_sync-xxx",
    "node_type": "data_sync",
    "status": "healthy" / "unhealthy",
    "uptime_seconds": 1234,
    "managers": {"RedisManager": True, "MongoManager": True, ...}
}
```

### 4.6 RPC 注册

```python
# 注册方法
def register_rpc_method(name, handler, is_async=True)

# 子类覆盖 _register_rpc_methods 注册自定义方法
def _register_rpc_methods(self):
    super()._register_rpc_methods()
    self.register_rpc_method("refresh_hot_news", self._handle_refresh_hot_news)
```

默认注册 `ping` 方法用于健康探测。

### 4.7 信号处理

```python
# main() 方法中注册 Unix 信号
loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.create_task(self._shutdown_signal()))
loop.add_signal_handler(signal.SIGINT, lambda: asyncio.create_task(self._shutdown_signal()))
```

`_shutdown_signal()` 设置 `_running = False`，触发 `_graceful_shutdown()` 流程。Windows 平台不支持信号处理时会静默跳过。

### 4.8 日志配置

`_setup_logging()` 配置双重输出：
1. **控制台** -- `StreamHandler`，格式 `%(asctime)s | %(levelname)s | %(name)s | trace_id=%(trace_id)s | %(message)s`
2. **文件** -- `RotatingFileHandler`，路径 `{log_dir}/{node_type}.log`，支持按大小轮转（默认 50MB）

`TraceContextFilter` 实现 trace_id 注入，可通过 `set_trace_id()` / `clear_trace_id()` 控制。

### 4.9 DataSyncNode 具体实现

`DataSyncNode(BaseNode)` 位于 `DataSync/nodes/data_sync/node.py`，在 `start()` 中：
1. 依序初始化 `redis_manager` -> `mongo_manager` -> `data_source_manager` -> `llm_manager`
2. 启动 RPC 服务器
3. 注册所有定时任务（`_register_jobs`）
4. 创建 `AsyncIOScheduler` 调度器（coalesce=True, max_instances=1）
5. 调度核心链路缺口恢复和补缺队列 worker
6. 启动调度器

任务注册按 `profile` 档位过滤：`conservative` 只注册核心任务，`full` 注册全部，`custom` 按白名单。特殊规则：`heavy` 资源类任务串行执行（独立 `_heavy_job_semaphore`），非核心任务在核心链路活跃时自动跳过。
