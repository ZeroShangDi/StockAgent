# 数据采集-股票行情 功能说明

## 概述

股票行情采集模块负责从多个数据源（Tushare、AKShare、BaoStock、Coze）采集 A 股市场的基础信息、日线行情、每日指标、指数数据和财务数据，统一写入 MongoDB 并支持检查点续跑与自动回退。

---

## 1. StockBasicCollector（股票基础信息采集）

- **文件路径**: `nodes/data_sync/collectors/stock/basic.py`
- **类名**: `StockBasicCollector`
- **用途**: 采集所有 A 股上市公司的基本信息，并合并最新交易日的估值指标（PE、PB、市值、换手率等）。
- **数据源链**: `get_stock_basic` -> akshare > baostock > coze > tushare；合并时使用 `get_daily_basic.full_market` -> tushare > baostock > akshare > coze。
- **目标集合**: `stock_basic`（MongoDB）
- **去重键**: `ts_code`
- **调度**: 默认 cron `0 9 * * 1-5`（每个交易日 9:00），可通过 `SYNC_STOCK_BASIC_SCHEDULE` 环境变量覆盖。
- **依赖**: `daily_basic:latest_optional`（可选依赖，无数据时不影响基础信息同步）
- **采集策略**:
  - 先通过 `is_synced("stock_basic", today)` 检查今日是否已同步，已同步则跳过。
  - 拉取全部股票基础信息（含 `ts_code`、`name`、`list_status`、`area`、`industry` 等）。
  - 获取最新交易日，并查询该日的 `daily_basic` 数据（PE、PB、市值、换手率等）。
  - 调用 `_add_financial_metrics()` 将市值从万元转换为亿元，过滤 NaN 值，亏损公司的 PE 保留 None。
  - 使用 `_write_buffer()` 批量 upsert 写入 MongoDB，写入成功后调用 `record_sync()` 记录同步标记。
- **关键字段**: `ts_code`, `name`, `list_status`, `industry`, `pe`, `pb`, `pe_ttm`, `total_mv`, `circ_mv`, `turnover_rate`, `total_share`, `float_share`, `updated_at`.
- **质量检查**: 必填字段 `ts_code,name,list_status`，去重键 `ts_code`.
- **错误处理**: 数据源不可用时自动回退到下一级源；daily_basic 不可用时基础信息仍会写入（只是缺少估值字段）。

---

## 2. StockDailyCollector（日线行情采集）

- **文件路径**: `nodes/data_sync/collectors/stock/daily.py`
- **类名**: `StockDailyCollector`
- **用途**: 采集所有 A 股股票的日线行情数据（开盘价、收盘价、最高价、最低价、成交量等），支持三种同步模式。
- **数据源链**:
  - 全市场按交易日: `get_daily.full_market` -> tushare > baostock > akshare > coze
  - 单股/批量: `get_daily.single` -> coze > akshare > baostock > tushare
- **目标集合**: `stock_daily`（MongoDB）
- **去重键**: `ts_code, trade_date`
- **调度**: 默认 cron `30 15 * * 1-5`（每个交易日 15:30 收盘后），可通过 `SYNC_STOCK_DAILY_SCHEDULE` 环境变量覆盖。
- **依赖**: `stock_basic`（获取全部上市股票列表）, `trade_calendar`（计算交易日区间）。
- **支持回补**: `supports_backfill = True`
- **关键配置**:
  - `HISTORY_START_DATE = "20030127"` —— 历史回补起始日期（上交所最早日期）
  - `HISTORY_SYNC_DAYS_THRESHOLD = 30` —— 超过 30 天未同步则触发历史同步模式
  - `FETCH_BATCH_SIZE_HISTORY = 1` —— 历史同步每秒 1 只股票（数据量大）
  - `FETCH_BATCH_SIZE_INCREMENTAL = 500` —— 增量同步每批 500 只
  - `WRITE_BATCH_SIZE = 1000`
- **三种同步模式**:
  1. **增量同步** (`_collect_incremental_by_trade_date`): 按交易日逐日拉取整个市场的日线数据，每天一次请求。自上次同步日期 +1 天起，遍历到今天。支持断点续跑（checkpoint）。
  2. **历史同步** (`_collect_history_by_stock`): 按股票逐只拉取全量历史数据，用于首次运行或长时间未同步的情况。每批 1 只股票串行执行（`max_concurrent=1`），支持检查点断点恢复。
  3. **重点股同步** (`_collect_focus_stocks`): 当 `SYNC_FOCUS_STOCKS_ONLY=true` 或仅有 Coze 数据源时启用，仅同步用户自选股和策略订阅股的日线数据。3 路并发。
- **覆盖检查**: 同步前检查目标交易日是否已有数据覆盖。若 sync marker 已标记完成但实际缺失覆盖，会强制重新同步。
- **恢复接口**: `recover_trade_date(trade_date)` 定向补单日数据，不回退 sync marker。
- **关键字段**: `ts_code`, `trade_date`, `open`, `high`, `low`, `close`, `vol`, `amount`.
- **质量检查**: 必填字段 `ts_code,trade_date,open,high,low,close`，去重键 `ts_code,trade_date`.

---

## 3. DailyBasicCollector（每日指标采集）

- **文件路径**: `nodes/data_sync/collectors/stock/daily_basic.py`
- **类名**: `DailyBasicCollector`
- **用途**: 采集每只股票每个交易日的估值指标和交易指标，用于因子选股回测。
- **数据源链**:
  - 全市场按交易日: `get_daily_basic.full_market` -> tushare > baostock > akshare > coze
  - 单股: `get_daily_basic.single` -> coze > akshare > baostock > tushare
- **目标集合**: `daily_basic`（MongoDB）
- **去重键**: `ts_code, trade_date`
- **调度**: 默认 cron `0 16 * * 1-5`（每个交易日 16:00 收盘后），可通过 `SYNC_DAILY_BASIC_SCHEDULE` 环境变量覆盖。
- **依赖**: `stock_basic`, `trade_calendar`
- **支持回补**: `supports_backfill = True`
- **关键配置**:
  - `HISTORY_START_DATE = "20180101"` —— 历史回补起始日期（比日线更近，因为新三板/早期数据较少）
  - `HISTORY_SYNC_DAYS_THRESHOLD = 30`
  - `WRITE_BATCH_SIZE = 5000`
  - `MAX_CONCURRENT = 3`
- **数据清洗** (`_clean_daily_basic_record`):
  - 市值从万元转换为亿元（`total_mv / 10000`）
  - 过滤 NaN 值（使用 `value == value` 判断）
  - 亏损公司 PE 保留 `None`（不清除字段）
  - 保留 `turnover_rate_f`（自由流通股换手率）、`free_share`（自由流通股本）等扩展字段
- **全字段清单**: `ts_code`, `trade_date`, `close`, `turnover_rate`, `turnover_rate_f`, `volume_ratio`, `pe`, `pe_ttm`, `pb`, `ps`, `ps_ttm`, `dv_ratio`, `dv_ttm`, `total_share`, `float_share`, `free_share`, `total_mv`, `circ_mv`, `updated_at`.
- **质量检查**: 必填字段 `ts_code,trade_date`，去重键 `ts_code,trade_date`，数值归一化 `numeric_normalization`.

---

## 4. IndexBasicCollector（指数基础信息采集）

- **文件路径**: `nodes/data_sync/collectors/stock/index_basic.py`
- **类名**: `IndexBasicCollector`
- **用途**: 采集四大市场（上交所 SSE、深交所 SZSE、申万 SW、中证 CSI）的指数基础信息。
- **数据源链**: `get_index_basic`（默认回退链由 DataSourceManager 管理）
- **目标集合**: `index_basic`（MongoDB）
- **去重键**: `ts_code`
- **调度**: 默认 cron `0 9 * * 1-5`（每个交易日 9:00），可通过 `SYNC_INDEX_BASIC_SCHEDULE` 环境变量覆盖。
- **覆盖市场**: `["SSE", "SZSE", "SW", "CSI"]` —— 4 路并行采集（`max_concurrent=4`），每个市场拉取后立即写入。
- **采集策略**:
  - 按天去重（`is_synced("index_basic", today)`），已同步则跳过。
  - 并行采集 4 个市场，各市场独立写入，支持失败重试。
  - 无数据时不写入并返回空结果。
- **关键字段**: `ts_code`, `name`, `market`, `publisher`, `category`.
- **质量检查**: 必填字段 `ts_code,name`，去重键 `ts_code`.

---

## 5. IndexDailyCollector（指数日线采集）

- **文件路径**: `nodes/data_sync/collectors/stock/index_daily.py`
- **类名**: `IndexDailyCollector`
- **用途**: 采集三大核心指数的日线行情数据。
- **数据源链**: `get_index_daily` -> tushare > baostock > akshare（Coze 不参与指数日线链）
- **目标集合**: `index_daily`（MongoDB）
- **去重键**: `ts_code, trade_date`
- **调度**: 默认 cron `35 15 * * 1-5`（每个交易日 15:35 收盘后，晚于个股日线 5 分钟），可通过 `SYNC_INDEX_DAILY_SCHEDULE` 环境变量覆盖。
- **依赖**: `index_basic`, `trade_calendar`
- **支持回补**: `supports_backfill = True`
- **核心指数**: `["000001.SH"（上证指数）, "399001.SZ"（深证成指）, "399006.SZ"（创业板指）]`
- **关键配置**:
  - `HISTORY_START_DATE = "20030127"`
  - `HISTORY_SYNC_DAYS_THRESHOLD = 30`
  - `MAX_CONCURRENT = 1` —— 只有 3 个指数，串行执行更稳定
- **同步策略**: 与 StockDailyCollector 相同，先确定同步范围（增量/历史），再按指数逐个拉取。
- **覆盖检查**: 逐个检查 3 个指数是否都已落库，缺失任何一只都会触发重新同步。
- **恢复接口**: `recover_trade_date(trade_date)` 定向补单日数据。
- **关键字段**: `ts_code`, `trade_date`, `open`, `high`, `low`, `close`, `vol`, `amount`.
- **质量检查**: 必填字段 `ts_code,trade_date,open,high,low,close`，去重键 `ts_code,trade_date`.

---

## 6. FinaIndicatorCollector（财务指标采集）

- **文件路径**: `nodes/data_sync/collectors/stock/fina_indicator.py`
- **类名**: `FinaIndicatorCollector`
- **用途**: 采集上市公司的完整财务数据，包括利润表、资产负债表、现金流量表、财务指标四大类。支持增量同步和初始化历史同步。
- **数据源**: 首选 `tushare`（`PREFERRED_SOURCE = "tushare"`），回退链为 `get_financial_data` -> coze > akshare > baostock > tushare。
- **目标集合**（4 个）:
  - `fina_income` —— 利润表（去重键: `ts_code, end_date`）
  - `fina_balance` —— 资产负债表（去重键: `ts_code, end_date`）
  - `fina_cashflow` —— 现金流量表（去重键: `ts_code, end_date`）
  - `fina_indicator` —— 财务指标（去重键: `ts_code, end_date`）
- **调度**: 默认 cron `0 9 1 * *`（每月 1 号 09:00），可通过 `SYNC_FINA_INDICATOR_SCHEDULE` 环境变量覆盖。
- **采集策略**:
  - **增量同步** (`collect`): 对每只上市股票拉取最近 8 个季度的财务数据，按月去重（`granularity="month"`）。
  - **初始化同步** (`init_sync`): 拉取每只股票最近 N 年的历史数据（默认 5 年 = 20 个季度），包含退市股票（`include_delisted=True`）。
- **关键配置**:
  - `MAX_CONCURRENT = 10` —— 10 路并发抓取，最大化吞吐
  - 每只股票串行处理四大报表，保证数据一致性
  - 自动创建索引（`_ensure_indexes`）: 为每个集合创建 `(ts_code, end_date)` 唯一索引，以及 `end_date` 和 `ts_code` 单字段索引
- **数据源回退告警**: 如果不是从首选源（tushare）获取，会打印 Warning 级别日志。
- **关键字段**: `ts_code`, `end_date`, `updated_at` 以及各报表特有字段（如利润表的 `revenue`, `n_income` 等）。
- **错误处理**: `DataSourceChainError` 会在所有源都失败时抛出；部分股票失败不影响其他股票。

---

## 通用机制

### 数据源回退链

所有股票数据采集器通过 `DataSourceManager._get_with_fallback()` 实现统一的数据源回退机制：

1. 按配置的优先级顺序逐一尝试数据源（tushare > baostock > akshare > coze 或相反）。
2. 每个数据源有独立的超时限制、冷却期（cooldown）和速率限制（TokenBucket）。
3. 源端返回超时/限流/服务不可用等错误时自动冷却该源并尝试下一级。
4. 核心同步方法（`CORE_SYNC_METHODS`）的超时和调用统计会被记录。
5. 回退优先级可通过 `SYNC_SOURCE_CHAIN_OVERRIDES` 环境变量自定义。

### 同步范围判定（`_determine_sync_range` / `_determine_sync_range_for`）

所有支持回补的采集器使用统一的同步范围判定逻辑：
1. 查询上一次同步日期（通过 `mongo_manager.get_last_sync_date(sync_type)`）。
2. 若无记录 -> 首次同步，从 `HISTORY_START_DATE` 开始，标记为历史同步。
3. 若上次同步日期 < 最新交易日，计算间隔天数：
   - 间隔 > `HISTORY_SYNC_DAYS_THRESHOLD`（默认 30 天） -> 历史同步
   - 间隔 <= 阈值 -> 增量同步
4. 增量同步从上次日期 +1 天开始，到最新交易日结束。

### 检查点续跑（Checkpoint）

`StockDailyCollector` 和 `DailyBasicCollector` 实现了检查点机制：
- 增量同步模式：每处理一个交易日后更新检查点（`_update_checkpoint`），记录已处理进度。
- 历史同步模式：每处理一批股票后更新检查点，记录最后一个完成的股票代码。
- 下次运行时会从检查点恢复，跳过已完成的项。

### 重点股模式（Focus Mode）

当 `SYNC_FOCUS_STOCKS_ONLY=true` 或仅有 Coze 数据源时，`StockDailyCollector` 和 `DailyBasicCollector` 会自动切换到重点股模式：
- 从 `users.watchlist` 和 `strategy_subscriptions.watch_list` 中提取股票代码。
- 只同步这些股票的数据，大幅降低数据量和请求次数。
