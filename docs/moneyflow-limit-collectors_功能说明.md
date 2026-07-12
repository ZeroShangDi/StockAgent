# 数据采集-资金涨跌 功能说明

## 概述

资金涨跌采集模块负责采集 A 股市场的行业/概念板块资金流向数据和每日涨跌停统计数据，为复盘分析和资金面研究提供数据支撑。三类采集器均采用按交易日维度的同步策略，通过 `DataSourceManager` 的统一回退链机制保障数据可用性。

---

## 1. MoneyflowIndustryCollector（行业资金流向采集）

- **文件路径**: `nodes/data_sync/collectors/stock/moneyflow_industry.py`
- **类名**: `MoneyflowIndustryCollector`
- **用途**: 采集同花顺（THS）行业资金流向数据，反映各行业板块的当日主力资金净流入/流出情况。
- **数据源**: Tushare 的 `moneyflow_ind_ths` 接口，回退链为 `get_moneyflow_industry` -> tushare > akshare。
- **目标集合**: `moneyflow_industry`（MongoDB）
- **去重键**: `ts_code, trade_date`
- **调度**: 默认 cron `0 16 * * 1-5`（每个交易日 16:00 收盘后），可通过 `SYNC_MONEYFLOW_INDUSTRY_SCHEDULE` 环境变量覆盖。
- **依赖**: `trade_calendar`（获取交易日列表）。
- **支持回补**: `supports_backfill = True`
- **关键配置**:
  - `INITIAL_SYNC_DAYS = 30` —— 首次同步默认往前回补 30 个交易日
  - `WRITE_BATCH_SIZE = 1000`
  - `MAX_CONCURRENT = 5` —— 5 路并行处理不同交易日
  - `API_INTERVAL = 0.2` —— 每次 API 调用后间隔 0.2 秒，降低源端压力
- **采集策略**:
  1. 获取最新交易日，检查是否已同步（`is_synced` + 覆盖检查）。
  2. 通过 `_determine_sync_range_simple` 确定同步日期范围：首次运行回补最近 30 天，增量从上次同步日期 +1 天开始。
  3. 获取该范围内的所有交易日列表。
  4. 并行（`max_concurrent=5`）按交易日逐日拉取行业资金流向数据，每次调用后 `asyncio.sleep(0.2)`。
  5. 以 `(ts_code, trade_date)` 为去重键 upsert 写入 MongoDB。
  6. 记录同步标记。
- **覆盖检查**: 通过 `_has_trade_date_coverage` 检查 `moneyflow_industry` 表中是否有该交易日的记录。
- **恢复接口**: `recover_trade_date(trade_date)` 定向补单日数据。
- **关键字段**: `ts_code`（行业代码）, `trade_date`（交易日期）, 主力净流入/流出金额相关字段（`buy_sm_vol`, `sell_sm_vol`, `buy_elg_vol`, `sell_elg_vol`, `net_mf_vol` 等）。
- **质量检查**: 必填字段 `ts_code,trade_date`，去重键 `ts_code,trade_date`.

---

## 2. MoneyflowConceptCollector（概念板块资金流向采集）

- **文件路径**: `nodes/data_sync/collectors/stock/moneyflow_concept.py`
- **类名**: `MoneyflowConceptCollector`
- **用途**: 采集同花顺概念板块资金流向数据，与行业资金流互补，覆盖概念题材类的资金动向。
- **数据源**: Tushare 的 `moneyflow_cnt_ths` 接口，回退链为 `get_moneyflow_concept` -> tushare > akshare。
- **目标集合**: `moneyflow_concept`（MongoDB）
- **去重键**: `ts_code, trade_date`
- **调度**: 默认 cron `5 16 * * 1-5`（每个交易日 16:05，晚于行业资金流 5 分钟），可通过 `SYNC_MONEYFLOW_CONCEPT_SCHEDULE` 环境变量覆盖。
- **依赖**: `trade_calendar`
- **支持回补**: `supports_backfill = True`
- **关键配置**: 与 `MoneyflowIndustryCollector` 完全一致 —— `INITIAL_SYNC_DAYS=30`, `MAX_CONCURRENT=5`, `API_INTERVAL=0.2`。
- **采集策略**: 与 `MoneyflowIndustryCollector` 完全对称：
  - 先检查是否已同步 + 覆盖情况。
  - 确定同步日期范围（首次 30 天，增量逐日）。
  - 并行按交易日拉取，每次间隔 0.2 秒。
  - upsert 写入 MongoDB，记录同步标记。
- **恢复接口**: `recover_trade_date(trade_date)` 定向补单日数据。
- **关键字段**: `ts_code`（概念板块代码）, `trade_date`, 资金流入/流出相关字段。
- **质量检查**: 必填字段 `ts_code,trade_date`，去重键 `ts_code,trade_date`.

---

## 3. LimitListCollector（涨跌停数据采集）

- **文件路径**: `nodes/data_sync/collectors/stock/limit_list.py`
- **类名**: `LimitListCollector`
- **用途**: 采集 A 股每日涨跌停统计数据，包括涨停/跌停股票列表、涨停原因、封板时间、炸板次数等，是短线复盘的核心数据。
- **数据源**: Tushare 的 `limit_list_d` 接口，回退链为 `get_limit_list` -> tushare > akshare。
- **目标集合**: `limit_list`（MongoDB）
- **去重键**: `ts_code, trade_date`
- **调度**: 默认 cron `10 16 * * 1-5`（每个交易日 16:10，晚于概念资金流 5 分钟），可通过 `SYNC_LIMIT_LIST_SCHEDULE` 环境变量覆盖。
- **依赖**: `trade_calendar`
- **支持回补**: `supports_backfill = True`
- **关键配置**:
  - `INITIAL_SYNC_DAYS = 30`
  - `WRITE_BATCH_SIZE = 1000`
  - `MAX_CONCURRENT = 3` —— limit_list API 限流较严格，并发度低于资金流采集器
  - `API_INTERVAL = 0.5` —— API 调用间隔 0.5 秒，比资金流采集器更保守
- **采集策略**: 与资金流采集器类似，按交易日维度处理：
  1. 获取最新交易日，检查是否已同步。
  2. 特殊覆盖检查: 除了检查 `limit_list` 表中是否有该交易日的记录外，还会检查 `get_last_sync_date` 是否等于该交易日（双重保障）。
  3. 确定同步日期范围（首次 30 天，增量逐日）。
  4. 并行（`max_concurrent=3`）按交易日逐日拉取涨跌停数据，每次间隔 0.5 秒。
  5. upsert 写入，记录同步标记。
- **恢复接口**: `recover_trade_date(trade_date)` 定向补单日数据。
- **关键字段**: `ts_code`, `trade_date`, `limit`（涨跌停类型: U=涨停/D=跌停）, `up_stat`（涨停次数）, `down_stat`（跌停次数）, 封板时间、炸板次数、涨停原因等。
- **质量检查**: 必填字段 `ts_code,trade_date`，去重键 `ts_code,trade_date`.

---

## 通用机制

### 同步范围判定（`_determine_sync_range_simple`）

三个采集器均使用简化的同步范围判定（不区分增量/历史模式）：

1. 查询上次同步日期（`get_last_sync_date(self.name)`）。
2. 若无记录 -> 从 `latest_trade_date - INITIAL_SYNC_DAYS` 开始（首次回补 30 天）。
3. 若上次同步日期 < 最新交易日 -> 从上次日期 +1 天同步到最新交易日。
4. 若上次同步日期 >= 最新交易日 -> 跳过。

与股票日线采用的历史/增量双模式不同，这里不使用 `_determine_sync_range`，因为：
- 资金流和涨跌停数据量较小（每日几百到几千条），不需要分批策略。
- AKShare/Tushare 的资金流接口通常只提供最近 30 天的数据，历史回溯范围有限。

### 覆盖检查（Coverage Check）

三个采集器都在 `already_synced` 之外增加了 `_has_trade_date_coverage` 检查：
- 如果 sync marker 记录已完成，但目标集合中实际没有数据（可能被误删或写入失败），会自动触发重新同步。
- LimitListCollector 的覆盖检查最为严格，除了检查数据库记录外还检查 `last_sync_date`。

### AKShare 仅 30 天限制

AKShare 的资金流接口普遍只提供最近约 30 个交易日的回看数据。首次同步时：
- `INITIAL_SYNC_DAYS = 30` 刚好匹配 AKShare 的数据窗口。
- 如果 Tushare 不可用，系统会尝试 AKShare 获取最近 30 天数据。
- 超过 30 天的历史数据只能通过 Tushare 获取。

### 回退链验证

| 方法 | 回退链 | 说明 |
|------|--------|------|
| `get_moneyflow_industry` | tushare -> akshare | 行业资金流向 |
| `get_moneyflow_concept` | tushare -> akshare | 概念板块资金流向 |
| `get_limit_list` | tushare -> akshare | 涨跌停统计 |

- 每个数据源有独立的超时限制（`_get_method_timeout`: 资金流 25 秒, 涨跌停 20 秒）。
- 达到超时或错误时自动回退到下一源。
- 所有源都失败时抛出 `DataSourceChainError`。
