# 基类框架模块 功能说明

## 概述

基类框架位于 `DataSync/core/base/` 目录下，定义了 DataSync 所有任务的统一基类体系，提供生命周期管理、调度执行、数据采集、检查点、失败重试等通用能力。

```
DataSync/core/base/
├── manager.py         # BaseManager - 资源管理器基类
├── scheduled_job.py   # ScheduledJob - 定时任务基类（核心层）
├── collector.py       # BaseCollector - 数据采集器基类
├── task.py            # BaseTask - 处理任务基类
├── generator.py       # BaseGenerator - 生成器基类
├── tool.py            # BaseTool - 工具基类（MCP 工具）
└── node.py            # BaseNode - 节点基类（见 config-node 模块）
```

**继承层次**：

```
ScheduledJob (定时任务抽象)
├── BaseCollector (数据采集)
├── BaseTask (处理任务)
└── BaseGenerator (内容生成)

BaseManager (资源管理器)

BaseTool (MCP 工具, Generic[InputT, OutputT])
```

---

## 1. BaseManager -- 资源管理器基类

文件位置：`DataSync/core/base/manager.py`

### 1.1 概述

所有资源管理器（Redis、MongoDB、Milvus 等）必须继承 `BaseManager`，统一生命周期和健康检查契约。

### 1.2 抽象方法

| 方法 | 签名 | 说明 |
|------|------|------|
| `initialize()` | `async -> None` | 初始化管理器，建立连接，完成后设置 `_initialized = True` |
| `shutdown()` | `async -> None` | 关闭管理器，释放连接和资源 |
| `health_check()` | `async -> bool` | 健康检查，返回 `True` 表示健康 |

### 1.3 内置机制

- **初始化保护**：`_ensure_initialized()` 方法在未初始化时抛出 `RuntimeError`
- **状态查询**：`is_initialized` 属性、`get_status()` 方法返回 `{"name": "...", "initialized": bool}`
- **惰性 logger**：`logger` 属性访问时才创建，格式为 `manager.{ClassName}`

### 1.4 使用示例

```python
from core.base.manager import BaseManager

class RedisManager(BaseManager):
    async def initialize(self) -> None:
        self._client = await aioredis.from_url(settings.redis.url)
        self._initialized = True

    async def shutdown(self) -> None:
        if hasattr(self, '_client'):
            await self._client.close()
        self._initialized = False

    async def health_check(self) -> bool:
        try:
            await self._client.ping()
            return True
        except Exception:
            return False

# 模块级单例
redis_manager = RedisManager()
```

### 1.5 全局管理器生命周期

DataSyncNode 在 `start()` 中按依赖顺序初始化管理器：
```python
await redis_manager.initialize()       # 1. 心跳注册 + 分布式锁
await mongo_manager.initialize()       # 2. 数据存储
await data_source_manager.initialize() # 3. 统一数据源管理
await llm_manager.initialize()         # 4. LLM / 统计分析
```

在 `_graceful_shutdown()` 末尾统一调用 `shutdown_all_managers()` 关闭。

---

## 2. ScheduledJob -- 定时任务基类

文件位置：`DataSync/core/base/scheduled_job.py`

### 2.1 概述

`ScheduledJob` 是所有定时调度任务的公共基类，提供调度时间管理、运行状态追踪、统一的 `run()` 入口。

### 2.2 类属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `name` | `str` | 任务名称（子类必须定义） |
| `description` | `str` | 任务描述（子类必须定义） |
| `default_schedule` | `str` | 默认 cron 表达式（子类必须定义） |
| `run_at_startup` | `bool` | 启动时是否立即运行（默认 `True`） |
| `dataset_name` | `Optional[str]` | 数据集名称（能力声明用） |
| `resource_class` | `Optional[str]` | 资源分类：core / heavy / background |
| `target_collections` | `Iterable[str]` | 目标 Mongo 集合 |
| `dependencies` | `Iterable[str]` | 依赖的其他任务 |
| `source_chain_keys` | `Iterable[str]` | 数据源链路 key |
| `supports_backfill` | `bool` | 是否支持历史补缺 |
| `quality_checks` | `Iterable[str]` | 质量检查项 |
| `recoverability` | `Mapping[str, Any]` | 可恢复性声明 |
| `_log_prefix` | `str` | 日志前缀（子类覆盖：collector/task/generator） |

### 2.3 核心方法

#### run() -> dict

运行任务，统一包装 `_do_work()`：

```python
result = {
    "success": True/False,
    "count": ...,
    "duration_ms": ...,
    # + _do_work() 返回的其他字段
}
```

失败时：
```python
result = {
    "success": False,
    "error": str(e),
    "duration_ms": ...,
}
```

#### schedule 属性

```python
@property
def schedule(self) -> str:
    return self.default_schedule  # 子类可重写从配置读取
```

#### capability_manifest() -> dict

导出任务静态能力声明（不包含运行状态），用于数据能力目录和运维页面：

- `name`, `description`, `dataset_name`, `resource_class`
- `default_schedule`, `effective_schedule`
- `target_collections`, `dependencies`, `source_chain_keys`
- `supports_recover_trade_date`, `supports_backfill`
- `recoverability`（包含 `mode`, `can_rerun`, `severity_on_missing`, `reason`）
- `quality_checks`, `run_at_startup`

#### _build_recoverability() -> dict

生成数据可恢复性声明：

| mode | 条件 |
|------|------|
| `full` | 支持按交易日或历史窗口进行可靠补缺 |
| `best_effort` | 可重新运行获取最新结果，但历史补缺能力有限 |
| `none` | 错过采集窗口后无法可靠还原当时数据 |

`severity_on_missing` 根据 mode 和 resource_class 自动推导：core 任务默认为 `warning`，其他默认为 `info`。

### 2.4 子类实现要求

子类必须实现 `_do_work()` 方法：

```python
@abstractmethod
async def _do_work(self) -> Dict[str, Any]:
    raise NotImplementedError
```

---

## 3. BaseCollector -- 采集器基类

文件位置：`DataSync/core/base/collector.py`

### 3.1 概述

`BaseCollector` 继承 `ScheduledJob`，用于从外部数据源（Tushare、AkShare、BaoStock、Coze）采集数据。提供同步范围计算、交易日历获取、批量写入、并行采集、失败重试、检查点等通用功能。

### 3.2 类属性

| 属性 | 默认值 | 说明 |
|------|--------|------|
| `HISTORY_START_DATE` | `"20180101"` | 历史数据起始日期 |
| `HISTORY_SYNC_DAYS_THRESHOLD` | `30` | 超过此天数差视为历史同步 |
| `INITIAL_SYNC_DAYS` | `30` | 首次同步回补天数 |
| `WRITE_BATCH_SIZE` | `1000` | 批量写入默认批次大小 |
| `MAX_RETRY_COUNT` | `3` | 失败项目最大重试次数 |
| `BAD_RECORD_SAMPLE_LIMIT` | `5` | 日志中最多输出的坏数据样本数 |
| `DEAD_LETTER_BUFFER_LIMIT` | `20` | 单批最大死信记录数 |

### 3.3 核心方法详解

#### collect() -> Dict[str, Any] (抽象方法)

```python
@abstractmethod
async def collect(self) -> Dict[str, Any]:
    """执行采集，返回至少包含 count 字段的 dict"""
    raise NotImplementedError
```

子类必须实现此方法。`_do_work()` 内部调用 `collect()`。

---

#### _determine_sync_range(latest_trade_date, history_start_date, history_threshold_days) -> Optional[Tuple[str, str, bool]]

确定同步日期范围和同步类型。

**逻辑流程**：

```
last_sync_date = Mongo 中记录的上次同步日期

if last_sync_date is None (首次同步):
    if prevent_initial_history_sync == True:
        return (latest_trade_date, latest_trade_date, False)  # 仅补最新一天
    else:
        return (HISTORY_START_DATE, latest_trade_date, True)  # 全量历史同步

if last_sync_date >= latest_trade_date:
    return None  # 已是最新，无需同步

days_diff = (latest_date - last_sync_date).days
if days_diff > HISTORY_SYNC_DAYS_THRESHOLD (默认 30):
    return (next_day, latest_date, True)  # 历史同步（大量数据）
else:
    return (next_day, latest_date, False)  # 增量同步（少量数据）
```

**返回值**：`(start_date, end_date, is_history_sync)`，不需要同步时返回 `None`。

**示例**：
```python
# 首次同步（保护模式）
range_info = await self._determine_sync_range("20260619")
# (20260619, 20260619, False)  -- 仅补最新交易日

# 增量同步（上次 20260618，最新 20260620，差 2 天）
range_info = await self._determine_sync_range("20260620")
# (20260619, 20260620, False)  -- 增量同步 2 天

# 历史同步（上次 20260501，最新 20260620，差 50 天 > 30 阈值）
range_info = await self._determine_sync_range("20260620")
# (20260502, 20260620, True)  -- 历史同步
```

#### _determine_sync_range_simple(latest_trade_date, initial_sync_days) -> Optional[Tuple[str, str]]

简化版同步范围确定（不区分历史/增量），用于 `limit_list` 等场景。

#### _get_trade_dates(start_date, end_date) -> List[str]

获取日期范围内的交易日列表。

- 优先通过 `data_source_manager.get_trade_calendar()` 获取
- 失败时降级为周一至周五的工作日列表

---

#### _write_buffer(buffer, collection, key_fields, batch_size) -> int

批量写入数据到 MongoDB，包含数据校验、死信记录、自适应批次。

**流程**：
1. `_validate_records_with_dead_letters()` -- 校验数据，分离坏记录
2. `_record_dead_letters()` -- 将坏记录写入死信集合
3. `mongo_manager.bulk_upsert_batched()` -- 利用自适应批次大小分批写入
4. 记录写入日志和结果统计

**写入结果记录**：
```python
self._write_results.append({
    "collection": "stock_daily",
    "matched": 100, "modified": 5,
    "upserted": 95, "failed": 0,
    "total": 100, "batch_count": 1,
    "batch_size": 1000, "batch_size_history": [...],
    "adaptive_batching": {...}
})
```

#### _validate_records_with_dead_letters(records, collection) -> Tuple[List, List]

核心集合入库前的轻量校验与清洗。根据 `CORE_RECORD_SCHEMAS` 中定义的 schema 进行：

- **必填字段检查**（`required`）：缺失时标记为 `missing_required`
- **日期标准化**（`date_fields`）：通过 `_normalize_yyyymmdd()` 统一为 `YYYYMMDD`
- **浮点数安全转换**（`float_fields`）：非数值或 NaN/Inf 转为 None
- **整数安全转换**（`int_fields`）

返回 `(valid_records, dead_letters)` 元组。

**核心集合 Schema 示例**：
```python
CORE_RECORD_SCHEMAS = {
    "stock_daily": {
        "required": ["ts_code", "trade_date", "open", "high", "low", "close"],
        "date_fields": ["trade_date"],
        "float_fields": ["open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"],
    },
    "limit_list": {
        "required": ["ts_code", "trade_date", "limit"],
        "date_fields": ["trade_date"],
        "float_fields": ["close", "pct_chg", "amount", "limit_amount", "float_mv", "total_mv", "turnover_ratio", "fd_amount"],
        "int_fields": ["open_times", "limit_times"],
    },
    # ... 更多集合
}
```

---

## 4. 检查点机制 (Checkpoint)

BaseCollector 提供检查点（checkpoint）机制，用于支持大数据量采集的断点续跑。

### 4.1 _get_checkpoint(target_trade_date, window) -> Optional[Dict]

读取当前采集器指定窗口的续跑游标。

```python
cp = await self._get_checkpoint("20260619", "full_market")
# {"status": "running", "cursor": 1500, "last_success_key": "600519.SH"}
```

### 4.2 _update_checkpoint(target_trade_date, window, cursor, last_success_key, status, details)

更新检查点游标。

```python
await self._update_checkpoint(
    target_trade_date="20260619",
    window="full_market",
    cursor=1500,          # 当前处理到的位置
    last_success_key="600519.SH",  # 最后成功的 key
    status="running",
)
```

### 4.3 _mark_checkpoint_done(target_trade_date, window, details)

标记检查点完成。

```python
await self._mark_checkpoint_done("20260619", "full_market")
```

### 4.4 检查点使用场景

1. **全市场日线采集**：处理 5000+ 只股票时，每 500 只更新一次游标。中断后从游标处继续。
2. **历史回补**：跨多天采集时，每天一个 window，逐天标记完成状态。
3. **多窗口并行**：同一 target_trade_date 可创建多个 window，分别追踪进度。

---

## 5. _parallel_collect 并发控制与重试

### 5.1 方法签名

```python
async def _parallel_collect(
    self,
    items: List[T],
    collect_func: Callable[[T], Any],
    max_concurrent: int = 3,
    retry_failures: bool = True,
    item_id_func: Optional[Callable[[T], str]] = None,
) -> Dict[str, Any]:
```

### 5.2 执行流程

```
1. 并发限制：实际并发 = min(max_concurrent, SYNC_MAX_PARALLEL_COLLECT_CONCURRENCY)

2. 失败重试（retry_failures=True 时）：
   - 从 Mongo sync_failures 集合读取待重试项目
   - 将待重试项目插入队列头部

3. 并行执行：使用 asyncio.Semaphore 控制并发
   - 每个 item 独立执行 collect_func
   - 成功：清除失败记录（_clear_failure）
   - 失败：记录失败（_record_failure）

4. 进度日志：每 10% 输出一次进度
```

### 5.3 返回值

```python
{
    "total": 5000,         # 总项目数
    "success": 4980,       # 成功数
    "failed": 20,          # 失败数
    "results": [...],      # 结果列表
    "failed_items": [...]  # 失败项目列表
}
```

### 5.4 并发控制

并发上限同时受参数和全局配置约束：
```python
max_concurrent = min(
    max(1, int(max_concurrent or 1)),
    max(1, int(settings.data_sync.max_parallel_collect_concurrency)),  # 默认 2
)
```

---

## 6. 失败记录管理

### 6.1 _record_failure(item_id, error_msg, extra_data)

将失败项目记录到 Mongo `sync_failures` 集合。

```python
# 使用 upsert 更新错误信息和重试计数
await collection.update_one(
    {"collector": self.name, "item_id": item_id},
    {
        "$set": {"error": error_msg, "updated_at": now},
        "$inc": {"retry_count": 1},
        "$setOnInsert": {"collector": self.name, "item_id": item_id, "created_at": now},
    },
    upsert=True,
)
```

### 6.2 _get_pending_failures(max_retry=None) -> List[Dict]

获取待重试的失败项目（`retry_count < MAX_RETRY_COUNT`）。

### 6.3 _clear_failure(item_id) -> None

成功处理后清除失败记录。

### 6.4 _clear_all_failures() -> int

清除该采集器的所有失败记录，返回删除数量。

### 6.5 _get_failure_stats() -> Dict

返回失败统计：
```python
{"total": 15, "pending": 10, "exhausted": 5}
```

---

## 7. BaseTask -- 处理任务基类

文件位置：`DataSync/core/base/task.py`

`BaseTask` 继承 `ScheduledJob`，用于数据处理、聚类、统计、清理等非采集类任务。

```python
class BaseTask(ScheduledJob):
    _log_prefix = "task"

    @abstractmethod
    async def execute(self) -> Dict[str, Any]:
        raise NotImplementedError

    async def _do_work(self) -> Dict[str, Any]:
        return await self.execute()
```

**示例**：
```python
class EventClusteringTask(BaseTask):
    name = "event_clustering"
    description = "事件聚类去重"
    default_schedule = "*/10 * * * *"

    async def execute(self) -> dict:
        result = await cluster_engine.process_pending()
        return {"count": result.new_events}
```

---

## 8. BaseGenerator -- 生成器基类

文件位置：`DataSync/core/base/generator.py`

`BaseGenerator` 继承 `ScheduledJob`，用于报告生成、内容输出等任务。

```python
class BaseGenerator(ScheduledJob):
    _log_prefix = "generator"

    @abstractmethod
    async def generate(self) -> Dict[str, Any]:
        raise NotImplementedError

    async def _do_work(self) -> Dict[str, Any]:
        return await self.generate()
```

**示例**：
```python
class MorningReportGenerator(BaseGenerator):
    name = "morning_report"
    description = "生成早报"
    default_schedule = "50 8 * * 1-5"
    run_at_startup = False

    async def generate(self) -> dict:
        report = await report_generator.generate_and_push(
            report_type=ReportType.MORNING
        )
        return {"count": report.stats.event_count}
```

---

## 9. BaseTool -- MCP 工具基类

文件位置：`DataSync/core/base/tool.py`

`BaseTool` 是泛型基类 `BaseTool[InputT, OutputT]`，用于定义 MCP 工具。

### 9.1 设计

```python
class ToolResult(BaseModel):
    success: bool = True
    error_message: Optional[str] = None
    execution_time_ms: float = 0

class BaseTool(ABC, Generic[InputT, OutputT]):
    name: str
    description: str
    input_model: Type[InputT]   # Pydantic BaseModel
    output_model: Type[OutputT] # 继承 ToolResult 的 BaseModel

    @abstractmethod
    async def execute(self, input_data: InputT) -> OutputT:
        raise NotImplementedError
```

### 9.2 自动错误处理

`__call__` 方法自动捕获异常，失败时返回带 `success=False` 和 `error_message` 的结果。

### 9.3 get_schema() -> dict

返回工具的 Function Calling Schema（用于 LLM）：
```python
{
    "name": self.name,
    "description": self.description,
    "parameters": self.input_model.model_json_schema(),
}
```

---

## 10. Cron 定时调度机制

### 10.1 调度器配置

DataSyncNode 使用 `apscheduler` 的 `AsyncIOScheduler`：

```python
self._scheduler = AsyncIOScheduler(
    job_defaults={
        "coalesce": True,       # 错过的任务合并执行
        "max_instances": 1,     # 单任务不并发重入
        "misfire_grace_time": max(1, settings.data_sync.scheduler_misfire_grace_seconds),
    }
)
```

### 10.2 Cron 表达式示例

| 表达式 | 含义 |
|---------|------|
| `"0 9 * * 1-5"` | 每个工作日 9:00 |
| `"30 15 * * 1-5"` | 每个工作日 15:30 |
| `"0 */2 * * *"` | 每 2 小时 |
| `"*/10 * * * *"` | 每 10 分钟 |
| `"50 8 * * 1-5"` | 每个工作日 8:50 |
| `"0 18 * * 1-5"` | 每个工作日 18:00 |
| `"*/20 * * * *"` | 每 20 分钟 |

### 10.3 任务超时保护

每个任务通过 `asyncio.wait_for(job.run(), timeout=timeout_seconds)` 执行，超时时间由 `SYNC_JOB_TIMEOUT_SECONDS` 控制（默认 1200 秒 = 20 分钟）。

### 10.4 资源类管理

| 资源类 | 调度行为 |
|--------|---------|
| `core` | 正常调度，核心 pipeline 活跃时非核心任务自动跳过 |
| `heavy` | 串行执行（独立 `_heavy_job_semaphore`），只允许在闲时窗口运行 |
| `background` | 核心 pipeline 活跃时自动跳过 |

全局并发限制：`_job_semaphore = Semaphore(SYNC_MAX_RUNNING_JOBS)`，默认值为 1，确保默认配置下任务串行执行。

### 10.5 分布式锁

每个任务执行前获取 Redis 分布式锁：

```python
lock_key = f"sync:{job.name}:{today}"
lock = await redis_manager.try_lock(lock_key, timeout=lock_timeout)
```

锁被其他节点持有时跳过该任务，防止多节点重复执行。
