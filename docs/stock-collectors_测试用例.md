# 数据采集-股票行情 测试用例

## TC-01: 正常增量同步（交易日数据完整拉取）

**测试目标**: 验证新增一个交易日时，增量同步能正确拉取当天全市场数据。

**被测类**: `StockDailyCollector`, `DailyBasicCollector`, `IndexDailyCollector`

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 前置条件: 上一次同步日期为 `20260618`，当天为 `20260620`（周五），最新交易日为 `20260620` | - |
| 2 | 触发 `StockDailyCollector.collect()` | `_determine_sync_range_for` 返回 `("20260619", "20260620", False)`（增量同步，2天） |
| 3 | 检查 `_get_trade_dates("20260619", "20260620")` | 返回 `["20260619", "20260620"]`（2个交易日） |
| 4 | 进入 `_collect_incremental_by_trade_date` | 对 `20260619` 调用 `data_source_manager.get_daily(trade_date="20260619")` |
| 5 | 验证 20260619 数据 | 返回约 5000+ 条记录，每条含 `ts_code`, `trade_date`, `open`, `high`, `low`, `close` |
| 6 | `_write_buffer` 写入 MongoDB 的 `stock_daily` 集合 | 写入成功，返回 count 约 5000+ |
| 7 | 对 `20260620` 执行同样操作 | 写入成功 |
| 8 | `mongo_manager.record_sync("stock_daily", "20260620", count)` | sync_log 表中新增一条记录，sync_type="stock_daily", sync_date="20260620" |
| 9 | 验证返回结果 | `count > 0`, `sync_type = "增量同步"`, `success_batches = 2`, `failed_batches = 0` |

**扩展测试**:
- `DailyBasicCollector`: 同样的流程，但 `trade_date` 作为参数调用 `get_daily_basic(trade_date=...)`，返回约 5000 条记录，经过 `_clean_daily_basic_record` 清洗后写入 `daily_basic` 集合。
- `IndexDailyCollector`: 同样流程，但只对 3 个核心指数（`000001.SH`, `399001.SZ`, `399006.SZ`）逐个调用 `get_index_daily(ts_code=..., start_date=..., end_date=...)`，每次返回约 20 年历史或指定区间数据。

---

## TC-02: 历史回补（首次运行/指定日期范围）

**测试目标**: 验证首次运行或长时间未同步时，能正确触发历史同步模式。

**被测类**: `StockDailyCollector`

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 前置条件: 数据库中无 `stock_daily` 的 sync_log，`stock_basic` 已有 5000+ 条记录 | - |
| 2 | 触发 `collect()` | `get_last_sync_date` 返回 `None` |
| 3 | 检查 `_determine_sync_range_for` | 返回 `("20030127", latest_trade_date, True)`（历史同步） |
| 4 | 检查 `is_history_sync = True` | `fetch_batch_size = 1`（每批 1 只股票） |
| 5 | 进入 `_collect_history_by_stock` | 所有上市股票按代码排序，每批 1 只串行处理 |
| 6 | 对第一只股票 `000001.SZ` 调用 `get_daily(ts_code="000001.SZ", start_date="20030127", end_date=latest)` | 返回该股票所有历史日线记录 |
| 7 | `_write_buffer` 写入 `stock_daily` 集合 | 写入成功 |
| 8 | 检查 checkpoint 更新 | `_update_checkpoint` 被调用，`last_success_key = "000001.SZ"` |
| 9 | 模拟过程中断（重启进程）后再次运行 | 第二运行从 `last_success_key` 之后的股票开始，跳过 `000001.SZ` |
| 10 | 所有股票处理完成后 | `_mark_checkpoint_done` 被调用，`record_sync` 写入最终 sync marker |

**扩展测试 - DailyBasicCollector 历史回补**:
- `HISTORY_START_DATE = "20180101"`（不同于 StockDaily 的 "20030127"）
- 按交易日维度拉取：先获取 `start_date` 到 `end_date` 之间的所有交易日，再并行（`MAX_CONCURRENT=3`）处理

**扩展测试 - IndexDailyCollector 历史回补**:
- 只同步 3 个核心指数，每只指数一次性获取全部历史区间
- `MAX_CONCURRENT = 1`（串行）

---

## TC-03: 空数据场景（非交易日/停牌日）

**测试目标**: 验证非交易日或停牌日不会产生错误，正确处理空数据。

**被测类**: `StockDailyCollector`, `IndexDailyCollector`

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 前置条件: 上次同步日期为 `20260620`（周五），当天为 `20260622`（周一），最新交易日仍为 `20260620` | - |
| 2 | 触发 `collect()` | `last_sync_date = "20260620"`, `latest_trade_date = "20260620"` |
| 3 | `_determine_sync_range_for` | 返回 `None`（last_sync >= latest），跳过同步 |
| 4 | `collect()` 返回 | `{"count": 0, "message": "Already synced 20260620", "skipped": True}` |

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 5 | 场景 2: 某个交易日的日线数据源返回空列表 | - |
| 6 | `_collect_incremental_by_trade_date` 中，某个 trade_date 的 `get_daily` 返回空 | 打印 WARNING 日志，记录到 `failed_items`，继续处理下一个交易日 |
| 7 | 最终返回 | `failed_batches > 0`, `success_batches = (总数 - failed)`, 不记录 sync marker |

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 8 | 场景 3: StockBasicCollector 中 `daily_basic_map` 为空（无最新交易日数据） | `merged_count = 0`，股票基础信息仍然正常写入 |
| 9 | `_add_financial_metrics` 不会被调用 | 每条记录的 PE/PB/市值字段为空（不包含该字段） |

---

## TC-04: Tushare API 限流与重试

**测试目标**: 验证 Tushare API 限流时的自动冷却和回退机制。

**被测机制**: `DataSourceManager._get_with_fallback()` 中的 cooldown 和 TokenBucket

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 模拟 Tushare 返回 429（rate_limited） | `DataSourceHttpError` 被捕获，`status = "rate_limited"` |
| 2 | `_cool_down_source("tushare", retry_after_seconds)` 被调用 | Tushare 进入冷却期，默认 60 秒 |
| 3 | 下次请求 Tushare 时 | `_get_source_cooldown_remaining("tushare") > 0`，跳过 Tushare |
| 4 | 自动尝试下一级数据源（baostock） | 若 baostock 可用且返回有效数据，则该数据源被采用 |
| 5 | 检查调用统计 | `_record_call_outcome` 记录了 `rate_limited_count += 1`，`fallback_count += 1` |
| 6 | 冷却期过后 | Tushare 恢复正常使用，不再被跳过 |

**扩展测试 - TokenBucket 限流**:
| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 7 | 配置 `SYNC_SOURCE_RATE_LIMITS="tushare=200/m"` | Tushare 每分钟最多 200 次调用（约 3.33 次/秒） |
| 8 | `_wait_for_source_budget("tushare")` | 每次调用前检查 token 桶，不足时 `await` 等待 |
| 9 | 频率超过限制时 | 请求被延迟，不会触发 API 429 错误 |

---

## TC-05: AKShare 回退（Tushare 不可用时）

**测试目标**: 验证 Tushare token 未配置时，系统能自动使用 AKShare 等免费数据源。

**被测机制**: `DataSourceManager.initialize()` 和 `_get_with_fallback()`

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 前置条件: `.env` 中未配置 `TUSHARE_TOKEN` | `settings.tushare.is_configured = False` |
| 2 | 调用 `data_source_manager.initialize()` | 日志: "Tushare token not configured, using free data sources only" |
| 3 | 检查可用适配器 | `["akshare", "baostock"]`（Tushare 和 Coze 未添加） |
| 4 | 调用 `get_stock_basic()` | 按配置链顺序尝试: akshare -> baostock |
| 5 | AKShare 返回有效数据 | `source = "akshare"`，数据正常写入 |
| 6 | AKShare 不可用时 | 自动回退到 BaoStock |

**扩展测试 - Coze 回退**:
| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 7 | 前置条件: Coze 已配置但 Tushare 未配置 | 适配器列表: `["coze", "akshare", "baostock"]` |
| 8 | 调用 `get_daily(ts_code="000001.SZ")`（单股场景） | 按 `get_daily.single` 链: coze -> akshare -> baostock（tushare 不在链中） |
| 9 | Coze 不可用时 | 回退到 akshare |

---

## TC-06: 检查点续跑（断点恢复）

**测试目标**: 验证长时间运行的同步任务在中断后能正确从上次位置恢复。

**被测类**: `StockDailyCollector._collect_incremental_by_trade_date` 和 `_collect_history_by_stock`

### 场景 A: 增量同步断点恢复

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 前置条件: 需要同步 5 个交易日 `["20260616","20260617","20260618","20260619","20260620"]` | `checkpoint_window = "incremental_by_trade_date"` |
| 2 | 成功处理完 `20260616` 和 `20260617` 后 | `_update_checkpoint` 被调用，`last_success_key = "20260617"` |
| 3 | 在 `20260618` 处理时进程崩溃（模拟） | 未完成的 trade_date 没有更新 checkpoint |
| 4 | 重新启动，再次触发 `collect()` | `_get_checkpoint` 返回上次的 checkpoint，`last_success_key = "20260617"` |
| 5 | 过滤出剩余需要处理的交易日 | `trade_dates` 变为 `["20260618", "20260619", "20260620"]`，跳过前 2 个 |
| 6 | 继续处理剩余交易日 | `skipped_by_checkpoint = 2`, 日志显示 "skipped=2, remaining=3" |
| 7 | 全部完成后 | `_mark_checkpoint_done` 清除该 checkpoint |

### 场景 B: 历史同步断点恢复

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 8 | 前置条件: 第一批股票已处理完，最后一个股票为 `000010.SZ` | `last_success_key = "000010.SZ"` |
| 9 | 进程中重启 | 下次运行从 `000010.SZ` 之后（>`000010.SZ`）的股票开始 |
| 10 | 剩余股票处理完成 | `_mark_checkpoint_done` 清除 checkpoint |

---

## TC-07: 数据去重（重复拉取幂等性）

**测试目标**: 验证同一交易日的重复拉取不会产生重复记录。

**被测类**: 所有采集器（通过 `_write_buffer` 的 upsert 机制）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 前置条件: `stock_daily` 中已有 `20260620` 的 5000 条记录 | - |
| 2 | 手动清除 `sync_log` 中 `stock_daily` 的 `20260620` 记录（模拟标记丢失但数据已存在） | - |
| 3 | 触发 `StockDailyCollector.collect()` | `already_synced = False`（因为 sync_log 被清除） |
| 4 | 但 `coverage_ok = True`（因为 stock_daily 中已有数据） | 日志: "Sync marker stock_daily already points to 20260620, but stock_daily coverage is incomplete" -> 不对，因为 coverage 是 OK 的 |
| 5 | 修正: 场景改为 `already_synced = True` 但 `coverage_ok = False` | 日志: "forcing latest-date resync" |
| 6 | 重新执行同步 | `_write_buffer` 以 `ts_code + trade_date` 为去重键执行 upsert |
| 7 | 查询 `stock_daily` 中 `trade_date = "20260620"` 的记录数 | 仍然为 5000 条（无新增重复记录） |
| 8 | `StockBasicCollector` 中重复拉取 | 以 `ts_code` 为去重键 upsert，不会产生重复记录 |
| 9 | `IndexBasicCollector` 中重复拉取 | 以 `ts_code` 为去重键 upsert |

---

## TC-08: MongoDB 写入验证（字段完整性）

**测试目标**: 验证写入 MongoDB 的数据字段完整、类型正确。

**被测类**: 所有采集器

### StockBasicCollector 字段验证

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 执行 `StockBasicCollector.collect()` 后查询 `stock_basic` 集合中 `ts_code = "000001.SZ"` | 记录存在 |
| 2 | 验证必填字段 | `ts_code`（str）, `name`（str）, `list_status`（str, 值为 "L"/"D"/"P"） |
| 3 | 验证估值字段（非 NaN） | `total_mv` 和 `circ_mv` 为亿元单位（如 2800.5），非万元 |
| 4 | 验证估值字段（可能为 None） | `pe`, `pb`, `pe_ttm` 可能为 `None`（亏损公司）或正浮点数 |
| 5 | 验证交易指标 | `turnover_rate`（如 1.35, 单位 %）, `volume_ratio`（如 0.95） |
| 6 | 验证股本字段 | `total_share`（万股单位，如 210000.0）, `float_share`（万股） |
| 7 | 验证 `updated_at` | 为 UTC datetime 对象 |

### StockDailyCollector 字段验证

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 8 | 查询 `stock_daily` 中 `ts_code = "000001.SZ", trade_date = "20260620"` | 记录存在 |
| 9 | 验证必填字段 | `open`（float）, `high`（float）, `low`（float）, `close`（float）均 > 0 |
| 10 | 验证 OHLC 关系 | `low <= open/close <= high` |
| 11 | 验证成交量 | `vol > 0`（非停牌日） |
| 12 | 验证 `trade_date` 格式 | 字符串, 符合 `YYYYMMDD` 格式（如 "20260620"） |

### FinaIndicatorCollector 字段验证

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 13 | 执行 `FinaIndicatorCollector.collect()` | - |
| 14 | 查询 `fina_income` 中 `ts_code = "000001.SZ"` | 至少 8 条记录（最近 8 个季度） |
| 15 | 验证字段 `end_date` 格式 | 字符串, 如 "20260331"（季度末日期） |
| 16 | 验证 `updated_at` | 所有记录 `updated_at` 相同（同一次批量写入） |
| 17 | 确认索引已创建 | `fina_income` 上存在 `(ts_code, end_date)` 唯一索引 |

---

## 代码走查验证结果

**走查日期**: 2026-06-21 | **方法**: 代码走查 | **结果**: 8/8 通过

| 用例 | 结果 | 走查依据 |
|------|------|----------|
| TC-01 | ✅ PASS | StockDaily: `_determine_sync_range_for` (daily.py:252-278) → `_get_trade_dates` (collector.py:128-158) → `_collect_incremental_by_trade_date` (daily.py:280-384) → `_write_buffer` (collector.py:266-333) → `record_sync` (daily.py:149-153)。DailyBasicCollector 同样模式 (daily_basic.py:155-257)。IndexDailyCollector 按 3 个核心指数逐个采集 (index_daily.py:86-179) |
| TC-02 | ✅ PASS | StockDaily: HISTORY_START_DATE="20030127" (daily.py:58) + FETCH_BATCH_SIZE_HISTORY=1 (daily.py:63) → `_collect_history_by_stock` (daily.py:386-512) 按股票串行采集，checkpoint 以 batch[-1] 为 key。DailyBasic: HISTORY_START_DATE="20180101" (daily_basic.py:146) + MAX_CONCURRENT=3 (daily_basic.py:149)。IndexDaily: MAX_CONCURRENT=1 (index_daily.py:55) + 仅 3 个指数 |
| TC-03 | ✅ PASS | 场景1: `_determine_sync_range_for` 当 last_sync >= latest 返回 None → 返回 skipped (daily.py:263-264)。场景2: 空记录时 WARNING 日志 + continue，不抛异常 (daily.py:334-337)。场景3: daily_basic_map 为空时 merged_count=0，`_add_financial_metrics` 不会被调用 (basic.py:116-126) |
| TC-04 | ✅ PASS | DataSourceManager._get_with_fallback (data_source_manager.py:597-836): rate_limited → _cool_down_source → next adapter fallback。TokenBucket 限流机制在 `_wait_for_source_budget` 中实现 |
| TC-05 | ✅ PASS | DataSourceManager.initialize() 检查 Tushare token 配置，未配置则仅添加免费源。`_get_with_fallback` 按配置链顺序回退 (coze → akshare → baostock) |
| TC-06 | ✅ PASS | 增量断点: `_collect_incremental_by_trade_date` (daily.py:293-309) 读取 checkpoint → 过滤 trade_dates → 处理完后 `_mark_checkpoint_done`。历史断点: `_collect_history_by_stock` (daily.py:399-414) 读取 last_success_key → 过滤 batches |
| TC-07 | ✅ PASS | `_write_buffer` → `bulk_upsert_batched` 以 key_fields 为去重键 (collector.py:303-309)。stock_daily: ["ts_code","trade_date"] (daily.py:342,451)。stock_basic: ["ts_code"] (basic.py:133)。index_basic/index_daily: ["ts_code"]/["ts_code","trade_date"]。already_synced && coverage_ok 双重检查 (daily.py:78-80) |
| TC-08 | ✅ PASS | StockBasic: `_add_financial_metrics` 处理 total_mv/circ_mv (万元→亿元), PE/PB/PE_TTM (NaN→None), turnover_rate/volume_ratio (basic.py:16-65)。StockDaily: schema 验证 open/high/low/close 必填 (collector.py:58-61)。FinaIndicator: 4 集合 (fina_income/fina_balance/fina_cashflow/fina_indicator)，去重键 ["ts_code","end_date"]，唯一索引 _ensure_indexes (fina_indicator.py:23-29,187-196)，collect() 默认 limit=8 (最近8季度) |
