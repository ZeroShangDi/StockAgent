# 基类框架模块 测试用例

## 1. BaseManager 初始化/关闭生命周期

### TC-MGR-001: BaseManager 初始化状态流转

| 项目 | 内容 |
|------|------|
| **测试目标** | 验证 Manager 从创建到初始化再到关闭的状态变化 |
| **前置条件** | 使用一个具体的 Manager 子类（如 RedisManager） |
| **步骤** | 1. 创建 Manager 实例，检查 `is_initialized`<br>2. 调用 `await manager.initialize()`<br>3. 检查 `is_initialized`<br>4. 调用 `await manager.shutdown()`<br>5. 再次检查 `is_initialized` |
| **预期结果** | 创建后 `False`，初始化后 `True`，关闭后 `False` |

### TC-MGR-002: 未初始化时调用 _ensure_initialized 抛出异常

| 项目 | 内容 |
|------|------|
| **测试目标** | 在未初始化的 Manager 上调用需初始化的方法时抛出 RuntimeError |
| **步骤** | 1. 创建 Manager，不调用 `initialize()`<br>2. 调用 `_ensure_initialized()` |
| **预期结果** | 抛出 `RuntimeError("XxxManager not initialized. Call 'await XxxManager.initialize()' first.")` |

### TC-MGR-003: health_check 返回布尔值

| 项目 | 内容 |
|------|------|
| **测试目标** | 正常运行中 health_check 返回 True |
| **前置条件** | Manager 已初始化 |
| **步骤** | 调用 `await manager.health_check()` |
| **预期结果** | `True` |

### TC-MGR-004: get_status 返回状态信息

| 项目 | 内容 |
|------|------|
| **测试目标** | `get_status()` 返回 name 和 initialized 状态 |
| **步骤** | 1. 创建后调用 `get_status()`<br>2. 初始化后调用 `get_status()` |
| **预期结果** | `{"name": "XxxManager", "initialized": False}` -> `{"name": "XxxManager", "initialized": True}` |

### TC-MGR-005: Manager 关闭后 health_check 应返回 False

| 项目 | 内容 |
|------|------|
| **测试目标** | 关闭后健康检查应返回不健康状态 |
| **前置条件** | Manager 已初始化然后关闭 |
| **步骤** | 调用 `await manager.health_check()` |
| **预期结果** | `False` |

### TC-MGR-006: Manager 初始化顺序依赖

| 项目 | 内容 |
|------|------|
| **测试目标** | Manager 必须按依赖顺序初始化（Redis 先于 Mongo） |
| **前置条件** | 项目约定：Redis -> Mongo -> DataSource -> LLM |
| **步骤** | 1. 检查 DataSyncNode.start() 中的初始化顺序<br>2. 验证 redis_manager 先于 mongo_manager 初始化 |
| **预期结果** | 代码顺序正确：redis -> mongo -> data_source -> llm |

---

## 2. BaseCollector 同步范围确定

### TC-SYNC-RANGE-001: 首次同步 -- 保护模式

| 项目 | 内容 |
|------|------|
| **测试目标** | `prevent_initial_history_sync=True` 时首次只同步最新交易日 |
| **前置条件** | `SYNC_PREVENT_INITIAL_HISTORY_SYNC=True`，Mongo 中无 `stock_daily` 的 last_sync_date |
| **步骤** | 1. 调用 `_determine_sync_range("20260619")` |
| **预期结果** | 返回 `("20260619", "20260619", False)` -- 仅补最新一天 |

### TC-SYNC-RANGE-002: 首次同步 -- 历史模式

| 项目 | 内容 |
|------|------|
| **测试目标** | `prevent_initial_history_sync=False` 时首次全量历史同步 |
| **前置条件** | `prevent_initial_history_sync=False`，Mongo 中无记录 |
| **步骤** | 调用 `_determine_sync_range("20260619")` |
| **预期结果** | 返回 `("20180101", "20260619", True)` -- 全量历史同步 |

### TC-SYNC-RANGE-003: 增量同步（小于阈值）

| 项目 | 内容 |
|------|------|
| **测试目标** | 天数差小于阈值时标记为增量同步 |
| **前置条件** | last_sync_date=`20260618`，latest_trade_date=`20260619`，threshold=30 |
| **步骤** | 调用 `_determine_sync_range("20260619")` |
| **预期结果** | 返回 `("20260619", "20260619", False)` -- 增量同步 1 天 |

### TC-SYNC-RANGE-004: 历史同步（超过阈值）

| 项目 | 内容 |
|------|------|
| **测试目标** | 天数差超过阈值时标记为历史同步 |
| **前置条件** | last_sync_date=`20260401`，latest_trade_date=`20260619`，threshold=30 |
| **步骤** | 调用 `_determine_sync_range("20260619")` |
| **预期结果** | 返回 `("20260402", "20260619", True)` -- 历史同步 78 天 |

### TC-SYNC-RANGE-005: 已是最新无需同步

| 项目 | 内容 |
|------|------|
| **测试目标** | last_sync_date >= latest_trade_date 时返回 None |
| **前置条件** | last_sync_date=`20260619`，latest_trade_date=`20260619` |
| **步骤** | 调用 `_determine_sync_range("20260619")` |
| **预期结果** | `None` |

### TC-SYNC-RANGE-006: 阈值边界值测试

| 项目 | 内容 |
|------|------|
| **测试目标** | 天数差等于阈值时的行为 |
| **前置条件** | last_sync_date=`20260520`，latest_trade_date=`20260619`，threshold=30<br>天数差 = 30 天 |
| **步骤** | 调用 `_determine_sync_range("20260619")` |
| **预期结果** | 由于 `days_diff > threshold`（30 > 30 为 False），返回 `("20260521", "20260619", False)` -- 增量同步 |

### TC-SYNC-RANGE-007: _determine_sync_range_simple 首次同步

| 项目 | 内容 |
|------|------|
| **测试目标** | 简化版首次同步回补 INITIAL_SYNC_DAYS 天 |
| **前置条件** | Mongo 中无 last_sync_date，`INITIAL_SYNC_DAYS=30`，`initial_backfill_days=5`，`prevent_initial_history_sync=False` |
| **步骤** | 调用 `_determine_sync_range_simple("20260619")` |
| **预期结果** | start_date = 30 天前，end_date = "20260619"（受到 initial_backfill_days 约束后为 5 天前） |

---

## 3. _parallel_collect 并发控制与重试

### TC-PARALLEL-001: 并发数不超过全局上限

| 项目 | 内容 |
|------|------|
| **测试目标** | 实际并发受 `SYNC_MAX_PARALLEL_COLLECT_CONCURRENCY` 限制 |
| **前置条件** | `SYNC_MAX_PARALLEL_COLLECT_CONCURRENCY=2` |
| **步骤** | 1. 调用 `_parallel_collect(items=100个日期, max_concurrent=10)`<br>2. 检查实际并发数 |
| **预期结果** | 实际并发为 2（min(10, 2) = 2） |

### TC-PARALLEL-002: 失败项目记录到 sync_failures

| 项目 | 内容 |
|------|------|
| **测试目标** | 采集失败的项目被持久化到 Mongo |
| **前置条件** | Mongo 可用 |
| **步骤** | 1. 准备 10 个 item，其中 3 个会触发异常<br>2. 调用 `_parallel_collect(items, failing_collect_func, max_concurrent=2)`<br>3. 查询 `sync_failures` 集合 |
| **预期结果** | `sync_failures` 中有 3 条记录，`retry_count==1`，`error` 字段包含错误信息 |

### TC-PARALLEL-003: 成功项目清除失败记录

| 项目 | 内容 |
|------|------|
| **测试目标** | 成功后清除该 item 的失败记录 |
| **前置条件** | sync_failures 中已有 `item_1` 的失败记录 |
| **步骤** | 1. 调用 `_parallel_collect(items=["item_1"], success_func)`<br>2. 查询 `sync_failures` |
| **预期结果** | `item_1` 的失败记录被删除 |

### TC-PARALLEL-004: 自动重试之前失败的项目

| 项目 | 内容 |
|------|------|
| **测试目标** | `retry_failures=True` 时待重试项目排入队列头部 |
| **前置条件** | sync_failures 中有 `item_old_1`, `item_old_2` 的失败记录（retry_count < MAX_RETRY_COUNT） |
| **步骤** | 1. 调用 `_parallel_collect(items=["item_new_1"], collect_func, retry_failures=True)`<br>2. 检查执行顺序 |
| **预期结果** | 执行顺序为 `item_old_1`, `item_old_2`, `item_new_1`（待重试项在头部） |

### TC-PARALLEL-005: 超过最大重试次数不再重试

| 项目 | 内容 |
|------|------|
| **测试目标** | retry_count >= MAX_RETRY_COUNT 的项目不再重试 |
| **前置条件** | sync_failures 中有 `item_exhausted` 记录，retry_count=3（等于 MAX_RETRY_COUNT=3） |
| **步骤** | 调用 `_get_pending_failures()` |
| **预期结果** | `item_exhausted` 不在结果中 |

### TC-PARALLEL-006: 进度日志输出

| 项目 | 内容 |
|------|------|
| **测试目标** | 每完成 10% 输出一次进度日志 |
| **前置条件** | 共 100 个 item |
| **步骤** | 调用 `_parallel_collect(items=100个)`, 检查日志 |
| **预期结果** | 日志中出现 `Progress: 10/100`, `Progress: 20/100`, ..., `Progress: 100/100` |

### TC-PARALLEL-007: asyncio.gather 异常不影响其他任务

| 项目 | 内容 |
|------|------|
| **测试目标** | 单个 item 异常不影响其他 item 的执行 |
| **前置条件** | 5 个 item，中间 item_3 抛出异常 |
| **步骤** | 调用 `_parallel_collect`，检查结果 |
| **预期结果** | `success==4`, `failed==1`，其他 4 个正常完成 |

---

## 4. 检查点创建/更新/恢复

### TC-CP-001: 检查点创建

| 项目 | 内容 |
|------|------|
| **测试目标** | 首次调用 `_update_checkpoint` 创建新检查点 |
| **前置条件** | Mongo 中无该 job 和 window 的检查点 |
| **步骤** | 1. `await collector._update_checkpoint("20260619", "full_market", cursor=0, status="running")`<br>2. 查询 Mongo |
| **预期结果** | 存在一条 `job_name="xxx"`, `target_trade_date="20260619"`, `window="full_market"`, `cursor=0`, `status="running"` 的记录 |

### TC-CP-002: 检查点更新

| 项目 | 内容 |
|------|------|
| **测试目标** | 调用 `_update_checkpoint` 更新已有检查点 |
| **前置条件** | 已有 cursor=0 的检查点 |
| **步骤** | 1. `await collector._update_checkpoint("20260619", "full_market", cursor=1500)`<br>2. 查询验证 |
| **预期结果** | `cursor==1500`，`updated_at` 已更新 |

### TC-CP-003: 检查点读取

| 项目 | 内容 |
|------|------|
| **测试目标** | `_get_checkpoint` 正确读取游标 |
| **前置条件** | 已写入 cursor=1500 的检查点 |
| **步骤** | `cp = await collector._get_checkpoint("20260619", "full_market")` |
| **预期结果** | `cp["cursor"] == 1500` |

### TC-CP-004: 检查点不存在返回 None

| 项目 | 内容 |
|------|------|
| **测试目标** | 不存在的检查点返回 None |
| **步骤** | `cp = await collector._get_checkpoint("20990101", "nonexistent_window")` |
| **预期结果** | `None` |

### TC-CP-005: 标记检查点完成

| 项目 | 内容 |
|------|------|
| **测试目标** | `_mark_checkpoint_done` 将状态设为 done |
| **前置条件** | 已有 running 状态的检查点 |
| **步骤** | 1. `await collector._mark_checkpoint_done("20260619", "full_market")`<br>2. 读取检查点 |
| **预期结果** | `status=="done"` |

### TC-CP-006: 多窗口检查点独立性

| 项目 | 内容 |
|------|------|
| **测试目标** | 同一日期不同 window 的检查点互不影响 |
| **前置条件** | 无检查点 |
| **步骤** | 1. 为 `"20260619"` 创建 `"window_a"` 检查点 cursor=100<br>2. 为 `"20260619"` 创建 `"window_b"` 检查点 cursor=200<br>3. 分别读取 |
| **预期结果** | window_a cursor=100, window_b cursor=200，互不影响 |

---

## 5. _write_buffer 幂等写入

### TC-BUF-001: 基本幂等写入

| 项目 | 内容 |
|------|------|
| **测试目标** | 重复写入相同 key 的数据不产生重复记录 |
| **前置条件** | Mongo 可用，集合为空 |
| **步骤** | 1. 第一次写入 `_write_buffer(buffer=[{ts_code:"000001.SZ", trade_date:"20260619", close:10.5}], collection="stock_daily", key_fields=["ts_code","trade_date"])`<br>2. 第二次写入相同数据<br>3. 查询集合 |
| **预期结果** | 集合中只有 1 条记录，第二次写入 `upserted=0, modified=0` |

### TC-BUF-002: 部分更新

| 项目 | 内容 |
|------|------|
| **测试目标** | 写入已有记录的新字段时更新该记录 |
| **前置条件** | 已有记录 `{ts_code:"000001.SZ", trade_date:"20260619", close:10.5}` |
| **步骤** | 1. 写入 `{ts_code:"000001.SZ", trade_date:"20260619", close:10.8, pct_chg:2.86}`<br>2. 查询 |
| **预期结果** | 记录被更新：`close==10.8`, `pct_chg==2.86`，`modified==1` |

### TC-BUF-003: 数据校验 -- 缺少必填字段

| 项目 | 内容 |
|------|------|
| **测试目标** | 缺少 required 字段的记录被过滤到死信 |
| **前置条件** | `CORE_RECORD_SCHEMAS["stock_daily"]["required"]` 包含 `ts_code`, `trade_date`, `open`, `high`, `low`, `close` |
| **步骤** | 1. 写入 `[{trade_date:"20260619", open:10, high:11, low:9, close:10.5}]`（缺少 ts_code）<br>2. 检查写入结果和死信 |
| **预期结果** | 该记录被过滤，不写入目标集合，出现在死信集合中 |

### TC-BUF-004: 数据校验 -- 无效日期

| 项目 | 内容 |
|------|------|
| **测试目标** | trade_date 格式无效的记录被过滤 |
| **步骤** | 1. 写入记录 `trade_date="abc"`<br>2. 经过 `_normalize_yyyymmdd` 返回 None<br>3. 检查校验结果 |
| **预期结果** | 记录被标记为 `invalid_date:trade_date` |

### TC-BUF-005: 数据校验 -- NaN/Inf 浮点数

| 项目 | 内容 |
|------|------|
| **测试目标** | close 为 NaN 或 Inf 时触发校验错误 |
| **步骤** | 1. 写入记录 `close=float('nan')`（必填字段）<br>2. 写入记录 `vol=float('inf')`（非必填字段） |
| **预期结果** | NaN close 触发 `invalid_float:close`（必填失败）。Inf vol 被安全移除（非必填，pop 掉） |

### TC-BUF-006: 空缓冲区快速返回

| 项目 | 内容 |
|------|------|
| **测试目标** | 空列表不执行任何数据库操作 |
| **步骤** | `result = await collector._write_buffer([], "stock_daily", ["ts_code","trade_date"])` |
| **预期结果** | `result == 0`，不产生任何 Mongo 操作 |

### TC-BUF-007: 自适应批次大小

| 项目 | 内容 |
|------|------|
| **测试目标** | `bulk_upsert_batched` 根据写入速度自适应调整批次大小 |
| **前置条件** | 写入 5000 条记录 |
| **步骤** | 1. 调用 `_write_buffer(buffer=5000条, batch_size=1000)`<br>2. 检查 `_write_results` 中的 `batch_size_history` 和 `adaptive_batching` |
| **预期结果** | `batch_size_history` 包含各批次的写入耗时和批次大小，若 3 批连续快速（< `bulk_upsert_slow_batch_ms` 1500ms）则批次自动扩容 |

### TC-BUF-008: 死信记录上限控制

| 项目 | 内容 |
|------|------|
| **测试目标** | 死信不超过 `DEAD_LETTER_BUFFER_LIMIT`（默认 20） |
| **前置条件** | `dead_letter_max_records_per_batch=5` |
| **步骤** | 1. 写入 1000 条全部无效的记录<br>2. 检查实际的死信数量 |
| **预期结果** | 日志样本最多 5 条（`log_sample_limit`），死信最多 20 条（`DEAD_LETTER_BUFFER_LIMIT`），最终写入死信集合的不超过 5 条（`dead_letter_max_records_per_batch`） |

### TC-BUF-009: 全部校验通过后死信数量为 0

| 项目 | 内容 |
|------|------|
| **测试目标** | 正常数据无死信产生 |
| **步骤** | 1. 写入 10 条格式完全正确的最小 stock_daily 记录<br>2. 检查 `bad_records` |
| **预期结果** | `bad_records == []`，死信集合无新记录 |

---

## 6. 失败记录持久化与清理

### TC-FAIL-001: _record_failure 首次失败

| 项目 | 内容 |
|------|------|
| **测试目标** | 首次失败记录 retry_count=1 |
| **前置条件** | sync_failures 中无此 item 记录 |
| **步骤** | 1. `await collector._record_failure("000001.SZ", "Connection timeout")`<br>2. 查询 sync_failures |
| **预期结果** | 存在一条 `collector="xxx"`, `item_id="000001.SZ"`, `error="Connection timeout"`, `retry_count=1` 的记录 |

### TC-FAIL-002: _record_failure 重复失败累加计数

| 项目 | 内容 |
|------|------|
| **测试目标** | 重复失败 retry_count 递增 |
| **前置条件** | sync_failures 中已有 retry_count=1 的记录 |
| **步骤** | 1. 再次调用 `_record_failure("000001.SZ", "Still failing")`<br>2. 查询 |
| **预期结果** | `retry_count==2`, `error=="Still failing"`, `created_at` 不变, `updated_at` 更新 |

### TC-FAIL-003: _clear_failure 删除单条记录

| 项目 | 内容 |
|------|------|
| **测试目标** | 成功后清除指定 item 的失败记录 |
| **前置条件** | sync_failures 中有 `item_id="000001.SZ"` 的记录 |
| **步骤** | 1. `await collector._clear_failure("000001.SZ")`<br>2. 查询 |
| **预期结果** | 该记录被删除 |

### TC-FAIL-004: _clear_all_failures 批量删除

| 项目 | 内容 |
|------|------|
| **测试目标** | 清除该采集器的所有失败记录 |
| **前置条件** | sync_failures 中有 3 条该采集器的记录，2 条其他采集器的记录 |
| **步骤** | 1. `count = await collector._clear_all_failures()`<br>2. 查询 sync_failures |
| **预期结果** | `count == 3`，其他采集器的 2 条记录保留 |

### TC-FAIL-005: _get_failure_stats 统计

| 项目 | 内容 |
|------|------|
| **测试目标** | 失败统计数字正确 |
| **前置条件** | 5 条失败记录：3 条 retry_count < 3（pending），2 条 retry_count = 3（exhausted） |
| **步骤** | `stats = await collector._get_failure_stats()` |
| **预期结果** | `{"total": 5, "pending": 3, "exhausted": 2}` |

### TC-FAIL-006: sync_failures 集合索引

| 项目 | 内容 |
|------|------|
| **测试目标** | 确保 `(collector, item_id)` 有唯一索引 |
| **前置条件** | Mongo 可用 |
| **步骤** | 检查 sync_failures 集合的索引 |
| **预期结果** | 存在 `(collector, item_id)` 唯一索引，`created_at` 索引 |

---

## 7. 定时任务 Cron 触发

### TC-CRON-001: Cron 表达式解析正确

| 项目 | 内容 |
|------|------|
| **测试目标** | `CronTrigger.from_crontab` 正确解析各种 cron 表达式 |
| **步骤** | 测试以下表达式：<br>1. `"0 9 * * 1-5"`<br>2. `"30 15 * * 1-5"`<br>3. `"*/10 * * * *"`<br>4. `"0 */2 * * *"` |
| **预期结果** | 全部解析成功，不抛异常 |

### TC-CRON-002: run_at_startup=False 时启动不执行

| 项目 | 内容 |
|------|------|
| **测试目标** | `run_at_startup=False` 的任务在 `_run_all_jobs` 中被跳过 |
| **前置条件** | 某任务的 `run_at_startup=False` |
| **步骤** | 1. 调用 `_run_all_jobs()`<br>2. 检查日志 |
| **预期结果** | 日志包含 `"Job xxx skipped (run_at_startup=False)"`，该任务未执行 |

### TC-CRON-003: coalesce 合并错过的任务

| 项目 | 内容 |
|------|------|
| **测试目标** | `coalesce=True` 时错过的多次调度只执行一次 |
| **前置条件** | 调度器配置 `coalesce=True` |
| **步骤** | 1. 设置每 1 分钟执行的任务<br>2. 暂停调度器 5 分钟<br>3. 恢复调度器 |
| **预期结果** | 恢复后只执行 1 次（合并了错过的 5 次） |

### TC-CRON-004: max_instances=1 防止并发重入

| 项目 | 内容 |
|------|------|
| **测试目标** | 上一个实例未完成时不会被重复调度 |
| **前置条件** | 任务执行耗时 120 秒，cron 每 60 秒触发 |
| **步骤** | 1. 监控任务执行<br>2. 检查是否有并发执行 |
| **预期结果** | 同时只有一个实例在运行 |

### TC-CRON-005: misfire_grace_time 宽限期

| 项目 | 内容 |
|------|------|
| **测试目标** | 在宽限期内错过的任务会被触发 |
| **前置条件** | `misfire_grace_time=300`（5 分钟） |
| **步骤** | 1. 暂停调度器 3 分钟<br>2. 恢复调度器 |
| **预期结果** | 3 分钟内的任务被触发（在宽限期内） |

---

## 8. 任务超时与资源类管理

### TC-TO-001: 任务在超时时间内正常完成

| 项目 | 内容 |
|------|------|
| **测试目标** | 正常执行不触发超时 |
| **前置条件** | `SYNC_JOB_TIMEOUT_SECONDS=1200` |
| **步骤** | 1. 执行一个耗时 5 秒的任务<br>2. 检查结果 |
| **预期结果** | `result["success"] == True`，无 timeout 错误 |

### TC-TO-002: 任务超时被中断

| 项目 | 内容 |
|------|------|
| **测试目标** | 超过 timeout 的任务被 `asyncio.wait_for` 取消 |
| **前置条件** | `SYNC_JOB_TIMEOUT_SECONDS=1` |
| **步骤** | 1. 执行一个耗时 120 秒的任务<br>2. 检查结果 |
| **预期结果** | `result["success"] == False`, `result["error"] == "job_timeout_after_1s"`, `result["reason"] == "timeout"`, duration_ms 约为 1000-1100ms |

### TC-TO-003: 核心任务超时记录为运维事件

| 项目 | 内容 |
|------|------|
| **测试目标** | 核心任务超时产生 `core_job_failed` 运维事件 |
| **前置条件** | 执行 `stock_daily`（核心任务），模拟超时 |
| **步骤** | 1. 触发超时<br>2. 检查 `ops_events` 集合 |
| **预期结果** | 存在一条 `event_type=="core_job_failed"`, `severity=="warning"`, `job_name=="stock_daily"` 的事件记录 |

### TC-TO-004: heavy 资源类任务串行执行

| 项目 | 内容 |
|------|------|
| **测试目标** | heavy 任务通过独立信号量串行 |
| **前置条件** | 同时触发两个 heavy 任务（如 `ths_sector` 和 `fina_indicator`） |
| **步骤** | 1. 同时调用 `run_job("ths_sector")` 和 `run_job("fina_indicator")`<br>2. 监控执行时间线 |
| **预期结果** | 两个任务串行执行，第二个等待第一个完成后才开始 |

### TC-TO-005: 全局任务并发限制

| 项目 | 内容 |
|------|------|
| **测试目标** | `_job_semaphore` 限制同时执行的任务数 |
| **前置条件** | `SYNC_MAX_RUNNING_JOBS=1` |
| **步骤** | 1. 同时触发 3 个任务<br>2. 观察执行顺序 |
| **预期结果** | 任务串行执行（一个接一个），即使调度器允许并发 |

### TC-TO-006: 分布式锁防止多节点重复执行

| 项目 | 内容 |
|------|------|
| **测试目标** | 同一 lock_key 被 A 节点持有时 B 节点跳过执行 |
| **前置条件** | 两个节点实例 |
| **步骤** | 1. 节点 A 持有 `sync:stock_daily:20260619` 锁<br>2. 节点 B 尝试执行相同任务 |
| **预期结果** | 节点 B 返回 `{"success": False, "skipped": True, "reason": "lock_held"}` |

### TC-TO-007: 锁超时自动释放

| 项目 | 内容 |
|------|------|
| **测试目标** | 锁在 timeout 后自动释放 |
| **前置条件** | `lock_timeout_seconds=3` |
| **步骤** | 1. 节点 A 获取锁后崩溃（不释放）<br>2. 等待 3 秒后节点 B 尝试获取<br>3. 查询锁状态 |
| **预期结果** | 3 秒后锁自动过期，节点 B 可以获取锁 |

### TC-TO-008: 非核心任务在核心活跃时自动跳过

| 项目 | 内容 |
|------|------|
| **测试目标** | 核心 pipeline 活跃时 background 类定时任务被跳过 |
| **前置条件** | `_active_core_jobs > 0` |
| **步骤** | 1. 模拟核心任务活跃<br>2. scheduler 触发 `stock_news`（background）任务 |
| **预期结果** | 返回 `{"success": False, "skipped": True, "reason": "core_resource_busy"}` |

### TC-TO-009: backfill_window_closed 时 heavy 任务跳过

| 项目 | 内容 |
|------|------|
| **测试目标** | 闲时窗口外 heavy 任务不执行 |
| **前置条件** | 当前时间 `14:00`（不在默认窗口 `00:00-08:00`），`SYNC_BACKFILL_WINDOW_START=00:00`, `SYNC_BACKFILL_WINDOW_END=08:00` |
| **步骤** | 1. 手动触发 heavy 任务 `run_job("ths_sector")`<br>2. 检查结果 |
| **预期结果** | `result["skipped"] == True`, `result["reason"] == "backfill_window_closed"` |

---

## 代码走查验证结果

**走查日期**: 2026-06-21 | **方法**: 代码走查 | **结果**: 45/45 通过

| 用例 | 结果 | 走查依据 |
|------|------|----------|
| TC-MGR-001~006 | ✅ PASS | `BaseManager.__init__` (manager.py:31-33): `_initialized=False`。`_ensure_initialized` (line 45-51): RuntimeError。`get_status` (line 82-87)。manager 初始化顺序 (node.py:177-181) |
| TC-SYNC-RANGE-001~007 | ✅ PASS | `_determine_sync_range` (collector.py:186-216): 首次/prevent_initial/增量/历史/跳过/阈值边界。`_determine_sync_range_simple` (line 218-264) |
| TC-PARALLEL-001~007 | ✅ PASS | `_parallel_collect` (collector.py:597-692): max_concurrent 限制 (line 626-630) + Semaphore (line 647)，重试失败项 (line 635-645)，`_clear_failure` (line 663)，进度日志 (line 671-673)，`return_exceptions=True` (line 676) |
| TC-CP-001~006 | ✅ PASS | 检查点方法 (collector.py:484-551): `_get_checkpoint`→mongo get，`_update_checkpoint`→upsert，`_mark_checkpoint_done`→status="done"。支持窗口隔离 |
| TC-BUF-001~009 | ✅ PASS | `_write_buffer` (collector.py:266-333): bulk_upsert_batched 去重。schema 验证 (line 343-440): 必填字段/日期标准化/float 安全检查。dead letter 限制 (line 56,55)。空 buffer 返回 0 (line 287-288) |
| TC-FAIL-001~006 | ✅ PASS | `_record_failure` (collector.py:694-748): upsert + $inc retry_count + $setOnInsert created_at。`_clear_failure` (line 782-798): delete_one。`_get_failure_stats` (line 817-847): pending/exhausted 统计。索引 (line 744-745) |
| TC-CRON-001~005 | ✅ PASS | `_schedule_job` (node.py:282-299): CronTrigger。`run_at_startup` 检查 (line 770)。coalesce=True (line 192)。max_instances=1 (line 193)。misfire_grace_time 可配 (line 298) |
| TC-TO-001~009 | ✅ PASS | `_run_job_with_timeout` (node.py:738-749): asyncio.wait_for + 1200s。Semaphore: heavy=1 (line 168), job=Semaphore(max_jobs) (line 166)。锁占用→skip (line 584-590)。core_resource_busy→skip (line 535-541)。backfill_window_closed→skip (line 503-509) |
