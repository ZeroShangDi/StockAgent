# 核心管理-MongoDB与Redis 功能说明

## 概述

MongoDB 和 Redis 是 DataSync 的两大基础设施组件，分别负责持久化存储和内存缓存/消息传递。

**代码位置：**

| 文件 | 类名 | 全局单例 | 说明 |
|---|---|---|---|
| `core/managers/mongo_manager.py` | `MongoManager` | `mongo_manager` | MongoDB 连接、CRUD、索引管理、批量写入、同步记录 |
| `core/managers/redis_manager.py` | `RedisManager` | `redis_manager` | Redis 连接、分布式锁、任务队列、Pub/Sub、缓存 |

两个管理器均继承自 `core.base.BaseManager`，遵循统一的 `initialize()` / `shutdown()` / `health_check()` 生命周期。

---

## 一、MongoManager

### 1.1 初始化流程

```python
await mongo_manager.initialize()
```

**初始化步骤：**
1. 通过 `normalize_local_service_host` 处理 host（Docker 环境下将 `localhost` 替换为服务名）
2. 解析超时配置（通过环境变量 `MONGO_CONNECT_TIMEOUT_MS`、`MONGO_SERVER_SELECTION_TIMEOUT_MS`、`MONGO_SOCKET_TIMEOUT_MS`，默认均为 5000ms）
3. 创建 `AsyncIOMotorClient`，配置 `maxPoolSize`（通过 `MONGO_MAX_POOL_SIZE` 配置，默认 100）
4. 执行 `ping` 测试连接（超时 = max(三个超时)/1000 + 0.5 秒）
5. 可选：通过 `MONGO_ENSURE_INDEXES` 控制是否创建索引
6. 可选：初始化镜像库连接（`MONGO_MIRROR_ENABLED=true` 时开启）

### 1.2 连接池配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `MONGO_HOST` | `localhost` | MongoDB 主机 |
| `MONGO_PORT` | `27017` | MongoDB 端口 |
| `MONGO_DATABASE` | - | 数据库名 |
| `MONGO_MAX_POOL_SIZE` | `100` | 连接池最大连接数 |
| `MONGO_CONNECT_TIMEOUT_MS` | `5000` | 连接超时（毫秒） |
| `MONGO_SERVER_SELECTION_TIMEOUT_MS` | `5000` | 服务选择超时（毫秒） |
| `MONGO_SOCKET_TIMEOUT_MS` | `5000` | Socket 超时（毫秒） |
| `MONGO_ENSURE_INDEXES` | `true` | 启动时是否自动建索引 |
| `MONGO_INDEX_STARTUP_SCOPE` | `core` | 启动时索引范围（all/core/none） |

### 1.3 索引管理

#### 自启动创建

初始化时自动为所有业务表创建必要索引：

```python
async def _ensure_indexes(scope="core", collections=None):
    # scope="core" → 仅创建 CORE_INDEX_COLLECTIONS 中定义的集合索引
    # scope="all"  → 创建所有集合的索引
    # scope="none" → 跳过索引创建
```

#### 核心索引集合（CORE_INDEX_COLLECTIONS）

共 22 个集合，包含：
- 行情数据：`stock_basic`, `stock_daily`, `index_basic`, `index_daily`, `daily_basic`
- 资金流向：`moneyflow_industry`, `moneyflow_concept`
- 涨跌停：`limit_list`
- 统计结果：`sector_ranking`, `daily_stats`, `market_analysis`, `market_weather_daily`
- 数据同步元数据：`sync_records`, `job_execution_records`, `readiness_markers`
- 运维相关：`ops_events`, `datasync_dead_letters`, `datasync_checkpoints`, `datasync_backfill_jobs`, `datasync_backfill_budgets`
- 股票关系：`stock_relations`

#### 索引创建幂等性

通过 `_filter_missing_indexes` 方法保证：
1. 调用 `collection.list_indexes()` 列出已有索引名称
2. 跳过已存在的同名索引
3. 仅创建缺失的索引

**索引冲突处理：**
- 如果已存在同名但属性不同的索引，MongoDB 抛出 `OperationFailure(code=86)`
- 自动 `drop_index` 旧索引后重新创建

#### 索引创建超时

通过 `MONGO_INDEX_CREATE_TIMEOUT_SECONDS` 控制（默认值由 `settings.mongo.index_create_timeout_seconds` 提供，最小 1 秒），超时后跳过该集合，打印 warning。

#### 关键索引示例

```python
# stock_daily: 股票代码 + 交易日期复合唯一索引
IndexModel([("ts_code", ASCENDING), ("trade_date", DESCENDING)], unique=True)
IndexModel([("trade_date", DESCENDING)])  # 按日期查询

# daily_stats: 交易日唯一索引
IndexModel([("trade_date", DESCENDING)], unique=True)

# sector_ranking: 日期 + 排名类型 + 排名 复合唯一索引
IndexModel([("trade_date", DESCENDING), ("ranking_type", ASCENDING), ("rank", ASCENDING)], unique=True)

# sync_records: 同步类型唯一索引（每个 sync_type 只保留一条记录）
IndexModel([("sync_type", ASCENDING)], unique=True)
```

### 1.4 通用 CRUD 方法

| 方法 | 说明 | 特殊行为 |
|---|---|---|
| `insert_one(collection, document)` | 插入单条 | 自动添加 `created_at` |
| `insert_many(collection, documents)` | 批量插入 | 自动添加 `created_at` |
| `find_one(collection, filter, projection, sort)` | 查询单条 | 支持排序（取第一条） |
| `find_many(collection, filter, projection, sort, limit, skip)` | 查询多条 | 所有标准查询参数 |
| `update_one(collection, filter, update, upsert)` | 更新单条 | 自动添加 `updated_at`；无 `$` 操作符时自动包装为 `$set` |
| `update_many(collection, filter, update)` | 更新多条 | 同上 |
| `delete_one(collection, filter)` | 删除单条 | - |
| `delete_many(collection, filter)` | 删除多条 | - |
| `count(collection, filter)` | 统计数量 | - |
| `aggregate(collection, pipeline)` | 聚合查询 | 返回完整列表 |

**自动时间戳：**
- `insert_one` / `insert_many`：自动添加 `created_at = datetime.now(UTC)`
- `update_one` / `update_many`：自动添加 `updated_at = datetime.now(UTC)`

**update 操作符自动包装：**
- 如果 update 字典不包含 `$` 开头的操作符（如 `$set`, `$inc`），自动包装为 `{"$set": update}`
- 例如 `update_one("daily_stats", {"trade_date": "20250620"}, {"field": 123})` → 实际发送 `{"$set": {"field": 123, "updated_at": ...}}`

### 1.5 高性能批量写入

#### bulk_upsert

```python
result = await mongo_manager.bulk_upsert(
    collection="stock_daily",
    documents=docs,
    key_fields=["ts_code", "trade_date"],
    batch_size=1000,
)
```

返回：
```json
{
    "matched": 4500,
    "modified": 200,
    "upserted": 300,
    "total": 5000,
    "batch_count": 5,
    "batch_errors": []
}
```

**特性：**
- 使用 MongoDB `BulkWrite` + `UpdateOne(upsert=True)`
- 支持复合键匹配（`key_fields` 可传多个字段）
- 验证每个文档的 `key_fields` 非空，缺失时抛出 `ValueError`
- 通过 `BulkUpsertBatchError` 携带失败详情

#### bulk_upsert_batched（自适应批处理）

内部实现采用自适应批次大小：

1. **启动批次大小：** `settings.data_sync.bulk_upsert_batch_size`（通常 1000）
2. **限幅：** min = `bulk_upsert_min_batch_size`, max = `bulk_upsert_max_batch_size`，上限 5000
3. **慢批缩容：** 如果批次耗时超过 `bulk_upsert_slow_batch_ms`（默认值从配置读取），批大小减半，不低于 `min_batch_size`
4. **稳定扩容：** 连续 `stable_batches_to_grow` 批次不慢，批大小翻倍恢复，不超过 `configured_batch_size`

相关配置（`settings.data_sync`）：
| 配置项 | 说明 |
|---|---|
| `bulk_upsert_batch_size` | 请求批次大小 |
| `bulk_upsert_min_batch_size` | 最小批次大小 |
| `bulk_upsert_max_batch_size` | 最大批次大小 |
| `bulk_upsert_slow_batch_ms` | 慢批次阈值（毫秒） |
| `bulk_upsert_stable_batches_to_grow` | 稳定后扩容需要的连续批次数 |

#### bulk_insert

纯批量插入（非 upsert），用于日志类数据（如 `job_execution_records`、`datasync_dead_letters`）。

### 1.6 镜像库（Mirror）支持

通过环境变量 `MONGO_MIRROR_ENABLED=true` 开启。

**特性：**
- 所有写操作（`insert_one`/`insert_many`/`update_one`/`update_many`/`delete_one`/`delete_many`/`bulk_upsert`）自动同步到镜像库
- 镜像写入失败不影响主库操作（best-effort）
- 通过 `get_target_status()` 可查看主库/镜像库的连接状态
- 降级追踪：`_mirror_degraded_since` / `_last_mirror_recovered_at`

### 1.7 数据同步辅助方法

#### record_sync — 记录同步状态

```python
await mongo_manager.record_sync(
    sync_type="stock_daily",
    sync_date="20250620",
    count=4500,
)
```

每个 `sync_type` 在 `sync_records` 集合中只保留一条记录，通过 `upsert=True` 更新。

**文档结构：**
```json
{
    "sync_type": "stock_daily",
    "sync_date": "20250620",
    "last_count": 4500,
    "updated_at": "2025-06-20T16:00:00Z"
}
```

#### is_synced — 检查是否已同步

```python
synced = await mongo_manager.is_synced("daily_stats", "20250620")
```

**逻辑：** 查询 `sync_records` 中该 `sync_type` 的记录，如果 `sync_date >= 查询日期`（字符串比较），返回 `True`。

**支持按月粒度：** 传入 `granularity="month"` 时只比较 `YYYYMM` 部分。

#### get_last_sync_date — 获取最后同步日期

```python
last_date = await mongo_manager.get_last_sync_date("stock_daily")
# 返回 "20250620" 或 None
```

#### record_job_execution — 记录任务执行明细

```python
execution_id = await mongo_manager.record_job_execution(
    job_name="stock_daily",
    node_id="datasync-01",
    started_at=start_time,
    finished_at=end_time,
    status="success",
    trigger="scheduler",
    target_trade_date="20250620",
    count=4500,
    duration_ms=1234.5,
    resource_class="core",
    source="tushare",
)
```

写入 `job_execution_records` 集合，每条自动生成 `execution_id`（UUID hex）。

### 1.8 其他辅助功能

#### 就绪标记（Readiness Markers）

```python
await mongo_manager.upsert_readiness_marker(
    marker_type="core_chain_ready",
    trade_date="20250620",
    status="ready",
    ready_datasets=["stock_daily", "limit_list"],
    pending_datasets=[],
)
```

写入 `readiness_markers` 集合，用于核心链路就绪状态追踪。

#### 运维事件（Ops Events）

```python
await mongo_manager.record_ops_event(
    event_type="data_gap_detected",
    severity="warning",
    message="stock_daily missing for 20250619",
    source="datasync",
)
```

#### 死信记录（Dead Letters）

```python
count = await mongo_manager.record_dead_letters(
    job_name="stock_daily",
    collection="stock_daily",
    records=bad_records,
    target_trade_date="20250620",
)
```

单批最多 100 条，通过 `dead_letter_max_records_per_batch` 配置（默认 20）。

#### 断点续跑（Checkpoints）

```python
# 创建/更新
checkpoint_id = await mongo_manager.upsert_checkpoint(
    job_name="stock_daily",
    target_trade_date="20250620",
    window="full",
    cursor={"last_ts_code": "603999.SH"},
    status="running",
)

# 读取
cp = await mongo_manager.get_checkpoint("stock_daily", "20250620", "full")

# 标记完成
await mongo_manager.mark_checkpoint_done("stock_daily", "20250620", "full")
```

#### 回补队列管理

| 方法 | 说明 |
|---|---|
| `create_backfill_job()` | 创建补缺任务（按 dataset+date 去重） |
| `list_backfill_jobs()` | 列出补缺任务（支持按状态/数据集过滤） |
| `claim_backfill_jobs()` | Worker 领取 pending 任务（原子操作，CAS 更新） |
| `mark_backfill_job_done()` | 标记任务完成 |
| `mark_backfill_job_failed()` | 标记失败（未超尝试次数回到 pending） |
| `pause_backfill_job()` | 暂停任务 |
| `resume_backfill_job()` | 恢复暂停的任务 |
| `record_backfill_budget_usage()` | 记录每日预算消耗 |

### 1.9 镜像库写入策略

所有写操作在主库完成后，异步调用 `_mirror_write` 执行镜像写入：
- 成功：记录 `_mirror_write_success_count`，清除降级状态
- 失败：记录 `_mirror_write_failure_count`，标记 `_mirror_degraded_since`
- 恢复：自动记录 `_last_mirror_recovered_at`

---

## 二、RedisManager

### 2.1 初始化流程

```python
await redis_manager.initialize()
```

**初始化步骤：**
1. 通过 `normalize_local_service_host` 处理 host
2. 从 `settings.redis.url` 读取连接 URL
3. 创建 `ConnectionPool`（`max_connections` 可通过 `REDIS_MAX_CONNECTIONS` 配置，默认 100）
4. 创建 `aioredis.Redis` 客户端（`decode_responses=True`）
5. 执行 `ping` 测试连接

**关键环境变量：**
| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `REDIS_HOST` | `localhost` | Redis 主机 |
| `REDIS_PORT` | `6379` | Redis 端口 |
| `REDIS_MAX_CONNECTIONS` | `100` | 连接池最大连接数 |
| `REDIS_TASK_QUEUE` | - | 任务队列名称 |
| `REDIS_NODE_REGISTRY_PREFIX` | - | 节点注册 Key 前缀 |
| `REDIS_RESULT_CHANNEL_PREFIX` | - | 结果发布频道前缀 |

### 2.2 分布式锁（DistributedLock）

**使用方式：**
```python
# 方式1: async with（推荐）
async with redis_manager.dist_lock("sync:daily:20250620", timeout=300):
    await sync_daily_data("20250620")
# 退出时自动释放

# 方式2: 非阻塞尝试
lock = await redis_manager.try_lock("sync:daily:20250620", timeout=300)
if lock:
    try:
        await do_work()
    finally:
        await lock.release()
```

**实现原理：**
- 使用 Redis `SET key token EX timeout NX` 实现互斥
- 每个锁生成唯一 `token`（UUID hex），释放时用 Lua 脚本确保只删除自己的锁
- **自动续期：** 每 `timeout/3` 秒续期一次，保持锁不意外过期
- 默认重试 3 次，间隔 0.1 秒

**参数说明：**
| 参数 | 默认值 | 说明 |
|---|---|---|
| `key` | - | 锁标识（自动加 `lock:` 前缀） |
| `timeout` | `60` | 锁超时时间（秒） |
| `retry_interval` | `0.1` | 重试间隔（秒） |
| `retry_times` | `3` | 重试次数 |

### 2.3 节点注册与心跳

```python
# 注册/续期
await redis_manager.register_node(
    node_id="datasync-01",
    node_info={"node_type": "data_sync", "host": "10.0.0.1", "status": "running"},
    ttl=15,
)

# 心跳续期（语义与 register_node 相同）
await redis_manager.heartbeat("datasync-01", node_info, ttl=15)

# 注销
await redis_manager.unregister_node("datasync-01")

# 查询所有活跃节点
nodes = await redis_manager.get_all_nodes(node_type="data_sync")

# 查询单个节点
node = await redis_manager.get_node("datasync-01")
```

**TTL 行为：** 节点信息通过 `SETEX` 存储，TTL 到期后自动删除。长时间未心跳的节点自动从注册表消失。默认 TTL 为 15 秒。

### 2.4 任务队列

```python
# 入队
await redis_manager.enqueue_task(
    {"task_id": "abc123", "type": "backfill", "dataset": "stock_daily"},
    queue=None,  # 使用默认队列
)

# 出队（阻塞）
task_json = await redis_manager.dequeue_task(queue=None, timeout=60)
task_data = json.loads(task_json)

# 队列长度
length = await redis_manager.get_queue_length()
```

底层使用 Redis List：
- `LPUSH` 入队（左侧推入）
- `BRPOP` 出队（右侧阻塞弹出，FIFO）

### 2.5 发布订阅

```python
# 发布任务结果
await redis_manager.publish_result("task_abc123", {"status": "done", "count": 100})

# 订阅
pubsub = await redis_manager.subscribe_result(
    "task_abc123",
    callback=lambda data: print(f"Received: {data}"),
)
```

- 频道格式：`{result_channel_prefix}:{task_id}`
- 支持 Pydantic model（自动调用 `model_dump(mode="json")`）
- callback 在独立 asyncio task 中运行

### 2.6 通用缓存

```python
# 设置
await redis_manager.cache_set("key_name", "value", ttl=3600)

# 获取
value = await redis_manager.cache_get("key_name")

# 删除
await redis_manager.cache_delete("key_name")
```

- Key 自动加 `cache:` 前缀
- 支持 TTL 过期

### 2.7 实时市场数据

```python
# 存储实时行情
await redis_manager.set_realtime_market_data({
    "sh_index": 3200.00,
    "sh_change": 1.23,
    "up_count": 2500,
    "down_count": 1800,
    "limit_up": 45,
    "update_time": "2025-06-20 10:30:00",
})

# 获取实时行情
data = await redis_manager.get_realtime_market_data()

# 发布增量
await redis_manager.publish_realtime_market_delta(delta_data)

# 写入 Redis Stream
event_id = await redis_manager.append_realtime_market_delta(delta_data)
```

- TTL: 3600 秒（1小时）
- Stream 最大长度: 512 条

### 2.8 热点新闻缓存

```python
# 存储
await redis_manager.set_hot_news("baidu", [{"title": "...", "url": "..."}])

# 获取单个来源
news = await redis_manager.get_hot_news("baidu")

# 获取所有来源
all_news = await redis_manager.get_all_hot_news()

# 统计
stats = await redis_manager.get_hot_news_stats()
# → {"stats": [{"source": "baidu", "count": 10, "updated_at": "..."}], "total": 10}
```

- Key 格式：`hot_news:{source}`
- TTL: 7200 秒（2小时）

### 2.9 错误处理

RedisManager 的方法在客户端未初始化时会通过 `_ensure_initialized()` 抛出异常。健康检查 `health_check()` 在连接断开时返回 `False` 而不是抛异常，适合用于就绪探测。

**连接断开自动恢复：** Redis 连接池本身支持自动重连。当 Redis 服务重启后，下一次操作会自动建立新连接。不需要手动调用 `initialize()` 恢复。

---

## 三、全局单例

两个管理器在模块底部导出为全局单例：

```python
# core/managers/mongo_manager.py
mongo_manager = MongoManager()

# core/managers/redis_manager.py
redis_manager = RedisManager()
```

在应用启动时通过统一的初始化流程调用 `initialize()`，业务代码直接 import 使用：

```python
from core.managers.mongo_manager import mongo_manager
from core.managers.redis_manager import redis_manager
```
