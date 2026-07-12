# 核心管理-MongoDB与Redis 测试用例

## 一、MongoManager 测试用例

### 1.1 MongoDB 连接/重连

#### 1.1.1 正常连接

**前置条件：**
- MongoDB 服务运行中
- 环境变量 `MONGO_HOST`, `MONGO_PORT`, `MONGO_DATABASE` 配置正确

**操作：** 调用 `await mongo_manager.initialize()`

**预期结果：**
- `mongo_manager._client` 不为 `None`
- `mongo_manager._db` 不为 `None`
- `mongo_manager._initialized` = `True`
- `ping` 命令成功
- 日志输出 `"MongoDB connected, database: xxx ✓"`

#### 1.1.2 连接失败处理

**前置条件：**
- MongoDB 服务未启动，或配置了错误的 `MONGO_HOST`

**操作：** 调用 `await mongo_manager.initialize()`

**预期结果：**
- 抛出连接异常（`pymongo.errors.ServerSelectionTimeoutError` 或超时异常）
- `mongo_manager._initialized` 保持 `False`
- 镜像库连接失败不阻断主库初始化（打印 warning 后继续）

#### 1.1.3 连接池配置

**前置条件：** `MONGO_MAX_POOL_SIZE=50`

**操作：** 初始化并检查

**预期结果：**
- `AsyncIOMotorClient` 以 `maxPoolSize=50` 创建
- 日志输出包含 `pool_size=50`

#### 1.1.4 主动关闭

**操作：** 调用 `await mongo_manager.shutdown()`

**预期结果：**
- `_client.close()` 被调用
- `_client`, `_db` 均设为 `None`
- `_initialized` = `False`
- 如果开启了镜像库，镜像连接也一并关闭

#### 1.1.5 健康检查

**操作：** 分别在有连接和无连接状态下调用 `await mongo_manager.health_check()`

**预期结果：**
- 连接正常时：返回 `True`
- 连接断开时：返回 `False`（不抛异常）
- 开启镜像时：主库和镜像都健康才返回 `True`

### 1.2 索引创建幂等性

#### 1.2.1 首次创建

**前置条件：** 集合不存在或索引不存在

**操作：** 调用 `await mongo_manager.initialize()` 或 `await mongo_manager._ensure_indexes(scope="core")`

**预期结果：**
- 所有 `CORE_INDEX_COLLECTIONS` 集合的索引创建成功
- `list_indexes()` 返回的索引名包含期望的索引

#### 1.2.2 重复创建（幂等性）

**前置条件：** 所有索引已存在（与 1.2.1 完全相同的索引）

**操作：** 再次调用 `await mongo_manager._ensure_indexes(scope="core")`

**预期结果：**
- `_filter_missing_indexes` 发现所有索引已存在，返回空列表
- `create_indexes` 不被调用
- 不抛异常
- 日志不报 "Index conflict" 错误

#### 1.2.3 索引冲突自动修复

**前置条件：**
- `stock_daily` 集合已存在同名索引 `ts_code_1_trade_date_-1`，但键顺序或属性不同（如非 unique）

**操作：** 调用 `_safe_create_indexes("stock_daily", [...])`

**预期结果：**
- MongoDB 抛出 `OperationFailure(code=86)`
- 自动 `drop_index` 旧索引
- 重新 `create_indexes` 创建新索引
- 最终索引属性与期望一致

#### 1.2.4 scope 控制

| scope 值 | 预期行为 |
|---|---|
| `"core"` | 仅创建 `CORE_INDEX_COLLECTIONS` 中集合的索引 |
| `"all"` / `"full"` | 创建所有集合的索引 |
| `"none"` / `"skip"` / `"off"` | 跳过所有索引创建 |

### 1.3 upsert vs insert_many 行为

#### 1.3.1 upsert（update_one + upsert=True）

**前置条件：** `test_collection` 为空

**操作：**
```python
# 第一次
await mongo_manager.update_one("test_collection", {"_id": 1}, {"name": "A", "value": 100}, upsert=True)
# 第二次
await mongo_manager.update_one("test_collection", {"_id": 1}, {"name": "A", "value": 200}, upsert=True)
```

**预期结果：**
- 第一次：插入新文档（`upserted_id` 有值）
- 第二次：更新已有文档（`modified_count = 1`）
- 最终文档只有一条，`value=200`
- 每次更新自动添加 `updated_at` 时间戳

#### 1.3.2 insert_many（纯插入）

**前置条件：** 集合中已存在 `{"_id": 1, "name": "A"}` 的文档

**操作：**
```python
await mongo_manager.insert_many("test_collection", [
    {"_id": 1, "name": "B"},  # 重复 ID
    {"_id": 2, "name": "C"},
])
```

**预期结果：**
- 抛出 `pymongo.errors.BulkWriteError`（`_id=1` 重复）
- 在 `ordered=False` 模式下，`_id=2` 仍然插入成功

### 1.4 bulk_upsert 性能与正确性

#### 1.4.1 正常批量写入

**前置条件：** 构造 5000 条测试文档，每条包含 `ts_code` 和 `trade_date`

**操作：**
```python
result = await mongo_manager.bulk_upsert(
    collection="stock_daily",
    documents=docs,
    key_fields=["ts_code", "trade_date"],
    batch_size=1000,
)
```

**预期结果：**
- `result["total"]` = 5000
- `result["batch_count"]` = 5（每批 1000）
- 所有文档被正确写入
- `_id` 不存在时 upsert，存在时 update

#### 1.4.2 自适应批大小

**前置条件：** MongoDB 响应时间变化（可通过模拟慢查询观察）

**预期行为：**
- 批次耗时 ≥ `slow_batch_ms` 时：批次大小减半
- 连续 `stable_batches_to_grow` 批稳定后：批次大小翻倍恢复
- 批次大小始终在 `[min_batch_size, max_batch_size]` 范围内

#### 1.4.3 key_fields 缺失校验

**前置条件：** 文档中缺少 `trade_date` 字段

**操作：** 调用 `bulk_upsert`

**预期结果：**
- 抛出 `ValueError("Document missing key_fields ['trade_date'] at index X")`
- 不会写入任何数据

#### 1.4.4 空文档列表

**操作：** `bulk_upsert(collection="test", documents=[], key_fields=["id"])`

**预期结果：**
- 返回全零结果：`{"matched": 0, "modified": 0, "upserted": 0, "total": 0}`
- 不抛异常

### 1.5 record_sync / is_synced / get_last_sync_date 一致性

#### 1.5.1 记录同步状态后检查

**操作：**
```python
await mongo_manager.record_sync("stock_daily", "20250620", count=4500)
synced = await mongo_manager.is_synced("stock_daily", "20250620")
last_date = await mongo_manager.get_last_sync_date("stock_daily")
```

**预期结果：**
- `synced` = `True`（因为 `"20250620" <= "20250620"`）
- `last_date` = `"20250620"`

#### 1.5.2 检查更早日期

**操作：**
```python
# 记录已同步到 20250620
synced = await mongo_manager.is_synced("stock_daily", "20250619")
```

**预期结果：**
- `synced` = `True`（`"20250619" <= "20250620"`）

#### 1.5.3 检查更新日期

**操作：**
```python
synced = await mongo_manager.is_synced("stock_daily", "20250621")
```

**预期结果：**
- `synced` = `False`（`"20250621" > "20250620"`）

#### 1.5.4 未同步过

**操作：**
```python
synced = await mongo_manager.is_synced("unknown_type", "20250620")
last_date = await mongo_manager.get_last_sync_date("unknown_type")
```

**预期结果：**
- `synced` = `False`
- `last_date` = `None`

#### 1.5.5 按月粒度

**操作：**
```python
await mongo_manager.record_sync("monthly_report", "20250615")
synced = await mongo_manager.is_synced("monthly_report", "20250601", granularity="month")
```

**预期结果：**
- `synced` = `True`（`"202506" <= "202506"`）

### 1.6 执行记录写入与查询

**操作：**
```python
exec_id = await mongo_manager.record_job_execution(
    job_name="stock_daily",
    node_id="datasync-01",
    started_at=datetime(2025, 6, 20, 15, 0, 0, tzinfo=UTC),
    finished_at=datetime(2025, 6, 20, 15, 5, 0, tzinfo=UTC),
    status="success",
    trigger="scheduler",
    target_trade_date="20250620",
    count=4500,
    duration_ms=300000,
    resource_class="core",
    source="tushare",
)
```

**预期结果：**
- `exec_id` 为 32 字符 hex 字符串
- `job_execution_records` 中插入一条记录
- 记录包含所有传入字段 + `execution_id` + `created_at`
- 可通过 `find_one("job_execution_records", {"execution_id": exec_id})` 查询到

---

## 二、RedisManager 测试用例

### 2.1 心跳注册与过期

#### 2.1.1 正常注册

**操作：**
```python
await redis_manager.register_node(
    "datasync-01",
    {"node_type": "data_sync", "status": "running"},
    ttl=15,
)
```

**预期结果：**
- Redis 中存在 Key（格式：`{prefix}:datasync-01`）
- 值为 JSON 序列化的 `node_info`
- TTL 为 15 秒

#### 2.1.2 心跳续期

**操作：**
```python
await redis_manager.heartbeat("datasync-01", {"node_type": "data_sync", "status": "running"}, ttl=15)
# 等待 5 秒后查询
nodes = await redis_manager.get_all_nodes()
```

**预期结果：**
- 节点仍在活跃列表中
- TTL 被刷新为 15 秒
- 5 秒后仍可查到（因为 TTL 还剩 10 秒）

#### 2.1.3 TTL 过期

**操作：** 注册节点（TTL=2），等待 3 秒后查询

**预期结果：**
- `get_node("datasync-01")` 返回 `None`
- `get_all_nodes()` 不包含该节点

#### 2.1.4 注销

**操作：** `await redis_manager.unregister_node("datasync-01")`

**预期结果：**
- 返回 `True`（成功删除）
- Key 不存在时返回 `False`

#### 2.1.5 按类型过滤节点

**操作：**
```python
await redis_manager.register_node("node-1", {"node_type": "data_sync"}, ttl=15)
await redis_manager.register_node("node-2", {"node_type": "web"}, ttl=15)
sync_nodes = await redis_manager.get_all_nodes(node_type="data_sync")
```

**预期结果：**
- `sync_nodes` 列表包含 "node-1"
- `sync_nodes` 列表不包含 "node-2"

### 2.2 分布式锁获取/释放

#### 2.2.1 正常获取和释放

**操作：**
```python
async with redis_manager.dist_lock("test:lock", timeout=10) as lock:
    # 验证锁被持有
    assert lock._acquired == True
# 退出后验证锁已释放
```

**预期结果：**
- 进入 `async with` 时锁被成功获取
- 退出时锁被释放
- Redis 中 Key 不存在（已被删除）

#### 2.2.2 锁竞争（互斥性）

**操作：**
```python
# 协程1：先获取锁
lock1 = redis_manager.dist_lock("test:unique", timeout=10)
await lock1.acquire()  # 成功

# 协程2：尝试获取同一把锁
lock2 = redis_manager.dist_lock("test:unique", timeout=10, retry_times=1, retry_interval=0.1)
result = await lock2.acquire()  # 应该失败
```

**预期结果：**
- `lock1.acquire()` 返回 `True`
- `lock2.acquire()` 返回 `False`
- Redis 中只有一个锁 token

#### 2.2.3 锁释放安全性（只释放自己的锁）

**操作：**
```python
# 直接通过 Redis 客户端写入一个假的 lock token
await redis_manager.client.set("lock:test:owned", "fake_token", ex=60)

# 用 DistributedLock 尝试释放
lock = redis_manager.dist_lock("test:owned", timeout=10)
await lock.acquire()  # 获取失败（因为 fake_token 不匹配）= 不获取
# lock 的 _token 与 Redis 中的 "fake_token" 不同
release_result = await lock.release()
```

**预期结果：**
- Lua 脚本发现 token 不匹配，返回 0（不删除）
- `release_result` = `False`
- Redis 中的 `"lock:test:owned"` 仍存在（值为 `"fake_token"`）

#### 2.2.4 自动续期

**操作：**
```python
lock = redis_manager.dist_lock("test:extend", timeout=3)
await lock.acquire()
# 等待 4 秒（超过原始 timeout 但续期在 timeout/3=1秒 触发）
await asyncio.sleep(4)
ttl = await redis_manager.client.ttl("lock:test:extend")
await lock.release()
```

**预期结果：**
- 等待 4 秒后 TTL > 0（续期生效，未被过期删除）
- TTL ≤ 3（续期后的新 TTL）

#### 2.2.5 非阻塞尝试锁

**操作：**
```python
lock = await redis_manager.try_lock("test:try", timeout=10)
```

**预期结果：**
- 成功：返回 `DistributedLock` 对象
- 失败（已被占用）：返回 `None`
- 不会阻塞等待

### 2.3 任务队列操作

#### 2.3.1 入队出队

**操作：**
```python
await redis_manager.enqueue_task({"id": 1, "data": "hello"})
await redis_manager.enqueue_task({"id": 2, "data": "world"})
task1 = await redis_manager.dequeue_task(timeout=5)
task2 = await redis_manager.dequeue_task(timeout=5)
```

**预期结果：**
- `len(task1)` 为 2（FIFO 顺序：id=1 先出）
- `dequeue_task` 返回 JSON 字符串 `'{"id": 1, "data": "hello"}'`
- 队列为空后再 `dequeue_task(timeout=1)` 等待 1 秒后返回 `None`

#### 2.3.2 队列长度

**操作：**
```python
await redis_manager.enqueue_task({"id": 1})
await redis_manager.enqueue_task({"id": 2})
length = await redis_manager.get_queue_length()
```

**预期结果：** `length` = 2

### 2.4 发布订阅

**操作：**
```python
# 创建事件收集器
received = []
async def on_message(data):
    received.append(data)

# 订阅
pubsub = await redis_manager.subscribe_result("task_123", callback=on_message)

# 发布
await redis_manager.publish_result("task_123", {"status": "done"})

# 等待回调执行
await asyncio.sleep(0.5)
```

**预期结果：**
- `received` 列表包含一条记录 `{"status": "done"}`
- 频道名称为 `{prefix}:task_123`

### 2.5 缓存操作

**操作：**
```python
await redis_manager.cache_set("test_key", '{"value": 42}', ttl=60)
value = await redis_manager.cache_get("test_key")
await redis_manager.cache_delete("test_key")
missing = await redis_manager.cache_get("test_key")
```

**预期结果：**
- `value` = `'{"value": 42}'`
- `missing` = `None`
- Redis 中 Key 为 `cache:test_key`（自动前缀）

### 2.6 连接断开自动恢复

**操作：**
1. 正常初始化并操作
2. 停止 Redis 服务
3. `health_check()` 返回 `False`
4. 其他操作抛出连接异常
5. 重启 Redis 服务
6. 下一次操作自动成功（无需手动重新初始化）

**预期结果：**
- 连接池自动处理重连
- 不需要调用 `initialize()` 恢复
- Redis 重启后缓存数据丢失（取决于 Redis 持久化配置）

---

## 代码走查验证结果

**走查日期**: 2026-06-21 | **方法**: 代码走查 | **结果**: 13/14 通过，1 处测试描述偏差

| 用例 | 结果 | 走查依据 |
|------|------|----------|
| 1.1 | ✅ PASS | `initialize()` (mongo_manager.py:129-154): 创建 AsyncIOMotorClient → ping → `_initialized=True`。连接失败时异常被抛出，`_initialized` 保持 False。`shutdown()` (line 173-186): 关闭镜像+主客户端 → `_initialized=False`。`health_check()` (line 188-198): ping 检测+镜像检测 |
| 1.2 | ✅ PASS | `_ensure_indexes` (line 485-832): `_normalize_index_scope` (line 309-315) 处理 core/all/none。`_filter_missing_indexes` (line 334-354) 检查已存在索引。`_safe_create_indexes` (line 380-408): 捕获 OperationFailure(code=86) → drop_index → 重建 |
| 1.3.1 | ✅ PASS | `update_one` (line 897-917): 支持 `upsert=True`，自动添加 `updated_at` (line 912-915) |
| 1.3.2 | ⚠️ 偏差 | `insert_many` (line 847-853) 未传递 `ordered=False` 参数（使用默认 `ordered=True`），测试描述中 `_id=2` 仍插入成功的假设在默认行为下不成立。若需此行为应在方法中添加 `ordered=False` |
| 1.4 | ✅ PASS | `bulk_upsert` (line 997-1038) → `bulk_upsert_batched` (line 1054-1173): key_fields 缺失校验 (line 1092-1097)，空文档返回零结果 (line 1054-1065)，自适应批大小 (line 1127-1153) |
| 1.5 | ✅ PASS | `record_sync` (line 1243-1269): upsert 到 sync_records。`is_synced` (line 1821-1846): 字符串比较 + `granularity="month"` 支持 (line 1841-1843)。`get_last_sync_date` (line 1848-1862) |
| 1.6 | ✅ PASS | `record_job_execution` (line 1271-1316): 生成 32 字符 hex execution_id (line 1295)，通过 `insert_one` 写入 `job_execution_records` (line 1315) |
| 2.1 | ✅ PASS | `register_node` (redis_manager.py:371-387): setex 设置 TTL。`heartbeat` (line 389-398): 委托 register_node 刷新 TTL。`get_all_nodes` (line 412-430): 支持 node_type 过滤。`unregister_node` (line 400-410) |
| 2.2 | ✅ PASS | `dist_lock` (line 227): DistributedLock 类。acquire 使用 `SET NX` (line 64)。release 使用 Lua 脚本 token 校验 (line 91-97)。`_auto_extend` 续期 (line 106-118)。`try_lock` (line 260-274): retry_times=1, 不阻塞 |
| 2.3 | ✅ PASS | `enqueue_task` (line 278): lpush。`dequeue_task` (line 290): brpop FIFO。`get_queue_length` (line 313): llen。注：测试中 `len(task1)==2` 描述有误，dequeue_task 返回字符串而非元组 |
| 2.4 | ✅ PASS | `publish_result` (line 321) + `subscribe_result` (line 339): 后台监听任务 + callback 回调 |
| 2.5 | ✅ PASS | `cache_set` (line 451): 自动 "cache:" 前缀 + setex TTL。`cache_get` (line 446) / `cache_delete` (line 465) |
| 2.6 | ✅ PASS | redis.asyncio.ConnectionPool 内置自动重连，`health_check` (line 199-206) 异常时返回 False |
| 2.7 | ✅ PASS | `set_hot_news` (line 602-617): TTL=7200 (line 600)。`get_hot_news` (line 620-635)。`get_hot_news_stats` (line 658-681) |

### 2.7 热点新闻缓存

**操作：**
```python
await redis_manager.set_hot_news("baidu", [
    {"title": "Test News 1", "url": "http://example.com/1"},
    {"title": "Test News 2", "url": "http://example.com/2"},
])
news = await redis_manager.get_hot_news("baidu")
stats = await redis_manager.get_hot_news_stats()
```

**预期结果：**
- `news["source"]` = `"baidu"`
- `len(news["news"])` = 2
- `stats["total"]` = 2
- `stats["stats"][0]["count"]` = 2
- Key 的 TTL 为 7200 秒
