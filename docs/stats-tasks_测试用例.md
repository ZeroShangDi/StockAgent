# 数据处理-统计任务 测试用例

## 一、DailyStatsTask 测试用例

### 1.1 DailyStats 正常计算（完整依赖数据）

**前置条件：**
- MongoDB 中已存在 `trade_date = "20250620"` 的数据：
  - `stock_daily` 集合中有 4500+ 条记录（包含 `ts_code`, `pct_chg` 字段）
  - `moneyflow_industry` 集合中有 60+ 条记录（包含 `pct_change`, `name`, `net_amount`）
  - `moneyflow_concept` 集合中有 200+ 条记录
  - `limit_list` 集合中有涨跌停记录（包含 `limit="U"` 和 `limit="D"`，`limit_times` 从 1 到 6+）
  - `index_daily` 中有 "000001.SH"、"399001.SZ"、"000300.SH" 的记录
- `daily_stats` 中该日期不存在记录

**操作：** 调用 `task._compute_single_day("20250620")`

**预期结果：**

| 验证项 | 预期 |
|---|---|
| `sector_ranking` 记录数 | ≥ 80 条（industry_top 20 + industry_bottom 20 + concept_top 20 + concept_bottom 20，如果数据足够）|
| `sector_ranking` 排序 | `industry_top` 按 `pct_change` 降序，`industry_bottom` 按 `pct_change` 升序 |
| `daily_stats.trade_date` | `"20250620"` |
| `daily_stats.limit_up_count` | `limit_list` 中 `limit="U"` 记录数 |
| `daily_stats.limit_down_count` | `limit_list` 中 `limit="D"` 记录数 |
| `daily_stats.limit_1` | `limit="U"` 且 `limit_times=1` 的记录数 |
| `daily_stats.max_limit_height` | 最大连板数 |
| `daily_stats.up_count + down_count + flat_count` | = `stock_daily` 记录数 |
| `daily_stats.seal_rate` | `limit_up_count / (limit_up_count + broken_limit_count) * 100` |
| `daily_stats.promotion_rate` | 在 0-100 之间 |
| `market_analysis.trade_date` | `"20250620"` |
| `market_analysis.sentiment_score` | 0-100 之间的浮点数 |
| `market_analysis.strength_score` | 0-100 之间的浮点数 |
| `market_analysis.cycle` | 七种有效值之一 |

### 1.2 依赖缺失处理

#### 1.2.1 stock_daily 缺失

**前置条件：**
- `stock_daily` 集合中 `trade_date = "20250620"` 无数据
- 其他依赖数据正常

**操作：** 调用 `task._compute_single_day("20250620")`

**预期结果：**
- `daily_stats.pct_chg_list` 为空列表
- `daily_stats.pct_chg_median` 为 `None`
- `daily_stats.up_count`, `down_count`, `flat_count` 均为 `0`
- `daily_stats.up_5pct_count`, `down_5pct_count` 均为 `0`
- `daily_stats.up_ratio` = 0, `down_ratio` = 0
- 其他字段（涨跌停、成交额等）正常计算
- 不抛异常，正常写入 `daily_stats` 文档

#### 1.2.2 limit_list 缺失

**前置条件：**
- `limit_list` 集合中 `trade_date = "20250620"` 无数据
- 其他依赖数据正常

**操作：** 调用 `task._compute_single_day("20250620")`

**预期结果：**
- `daily_stats.limit_up_count` = 0
- `daily_stats.limit_down_count` = 0
- `daily_stats.max_limit_height` = 0
- `daily_stats.limit_1`~`limit_6_plus` 均为 0
- `daily_stats.broken_limit_count` = 0
- `daily_stats.seal_rate` = 0
- `daily_stats.cont_board_count` = 0
- `daily_stats.promotion_rate` = `None`（无法计算晋级率）
- 不抛异常

### 1.3 板块排名排序验证

**前置条件：**
- `moneyflow_industry` 中有以下测试数据（模拟）：

| name | pct_change |
|---|---|
| 半导体 | 5.2 |
| 通信设备 | 3.1 |
| 银行 | 1.8 |
| ... | ... |
| 房地产 | -4.5 |
| 钢铁 | -3.2 |
| 煤炭 | -2.1 |

**操作：** 调用 `task._compute_sector_ranking("20250620")`

**预期结果：**
- `industry_top` 第一条：`name="半导体"`, `pct_change=5.2`, `rank=1`
- `industry_top` 第二条：`name="通信设备"`, `pct_change=3.1`, `rank=2`
- `industry_bottom` 第一条：`name="房地产"`, `pct_change=-4.5`, `rank=1`
- `industry_bottom` 最后一条的 `pct_change` 值最大（跌幅最小）
- 如果数据不足 20 条，则输出实际数量
- `sector_ranking` 中该日期的旧数据在写入前被清除（通过 `delete_many`）

### 1.4 连板统计准确性

**前置条件：**
- `limit_list` 中有以下涨停记录：

| ts_code | limit | limit_times | open_times |
|---|---|---|---|
| 000001.SZ | U | 1 | 0 |
| 000002.SZ | U | 1 | 1 |
| 000003.SZ | U | 2 | 0 |
| 000004.SZ | U | 3 | 0 |
| 000005.SZ | U | 4 | 0 |
| 000006.SZ | U | 5 | 0 |
| 000007.SZ | U | 6 | 0 |
| 000008.SZ | U | 7 | 0 |
| 000009.SZ | D | 1 | 0 |

**操作：** 调用 `task._compute_daily_stats("20250620")`

**预期结果：**

| 字段 | 预期值 | 说明 |
|---|---|---|
| `limit_up_count` | 8 | 8 只涨停 |
| `limit_down_count` | 1 | 1 只跌停 |
| `limit_1` | 2 | 000001, 000002 |
| `limit_2` | 1 | 000003 |
| `limit_3` | 1 | 000004 |
| `limit_4` | 1 | 000005 |
| `limit_5` | 1 | 000006 |
| `limit_6_plus` | 2 | 000007 (6板), 000008 (7板) |
| `max_limit_height` | 7 | 000008 的 7 板 |
| `broken_limit_count` | 1 | 000002 炸过板 |
| `total_limit_up` | 8 | 各档合计 |
| `cont_board_count` | 6 | 2板及以上（排除 limit_1） |

### 1.5 涨跌停封板率计算

**前置条件：**
- 涨停股 50 只，其中 10 只曾炸板（`open_times > 0`）
- 即 `limit_up_count = 50`, `broken_limit_count = 10`

**预期结果：**
- `seal_rate = 50 / (50 + 10) * 100 = 83.33`（保留两位小数）
- 如果 `limit_up_count = 0` 且 `broken_limit_count = 0`，则 `seal_rate = 0`

### 1.6 情绪周期分析

#### 1.6.1 chaos（混沌期）

**前置条件：**
- 连板高度 ≤ 3
- 情绪评分在 30~50 之间
- 量能 v_ratio < 0.9

**预期结果：**
- `market_analysis.cycle` = `"chaos"`
- `market_analysis.cycle_reason` 包含 "无明确主线" 或 "情绪震荡"

#### 1.6.2 recovery（修复期）

**前置条件：**
- 双评分在 20~40 之间
- 双趋势均为 "up"
- 连板高度 ≥ 3（处于回升中）

**预期结果：**
- `market_analysis.cycle` = `"recovery"`
- `market_analysis.cycle_reason` 包含 "修复萌芽" 或 "双评分回暖"

#### 1.6.3 main_upward（主升期）

**前置条件：**
- 双评分 ≥ 60
- 双趋势均为 "up" 或 "flat"
- 连板高度 ≥ 5
- v_ratio > 1.2
- 封板率 > 80%

**预期结果：**
- `market_analysis.cycle` = `"main_upward"`
- 仓位建议为 `{"level": "重仓", "range": "7~10成"}`

#### 1.6.4 divergence（分歧期）

**前置条件：**
- 一种评分 ≥ 60，另一种 < 60（评分背离）
- 或：双评分 ≥ 50 但趋势方向相反（情绪 up + 强度 down）

**预期结果：**
- `market_analysis.cycle` = `"divergence"`
- `cycle_reason` 包含 "评分背离" 或 "趋势背离"

#### 1.6.5 decline（退潮期）

**前置条件：**
- 双评分 < 40 且双趋势 "down"
- 或：v_ratio 连续下降且跌停数超过均值 2 倍
- 或：连板高度从前日 ≥4 回落 ≥2 级

**预期结果：**
- `market_analysis.cycle` = `"decline"`
- 仓位建议为 `{"level": "空仓", "range": "0~1成"}`

#### 1.6.6 ice_point（冰点期）

**前置条件：**
- 双评分 < 20 且双趋势非 "up"
- 连板高度 ≤ 2
- 跌停数超过均值的 2 倍以上

**预期结果：**
- `market_analysis.cycle` = `"ice_point"`
- 仓位建议为 `{"level": "空仓", "range": "0成"}`

### 1.7 数据不足时的降级

**前置条件：**
- `daily_stats` 历史不足 10 天（无法计算 MA10 基准）

**预期结果：**
- `market_analysis.baseline_data_count` < 10
- 周期可能判定为 `"unknown"`
- 核心分计算中无基准的因子默认给 50%（如无历史时 `_calc_relative_score` 返回 `max_score * 0.5`）
- 不抛异常

---

## 二、MarketStatisticsCacheTask 测试用例

### 2.1 多周期聚合

**前置条件：**
- MongoDB 中有至少 66 天的 `daily_stats`, `limit_list`, `stock_daily` 数据

**操作：** 调用 `task._build_for_trade_date("20250620")`

**预期结果：**
- 返回 `built = 9`（1 limit_snapshot + 4 leader_cycle + 4 sentiment）
- `market_statistics_cache` 集合插入 9 条记录
- 缓存类型覆盖：`limit_snapshot` ×1, `leader_cycle` ×4, `sentiment` ×4
- 各周期的 leader_cycle 数据范围：
  - `1w`: 最近 5 个交易日
  - `1m`: 最近 22 个交易日
  - `3m`: 最近 66 个交易日
  - `1y`: 最近 250 个交易日
- 当数据不足期望天数时，包含 `warnings` 提示覆盖不完整

### 2.2 覆盖率检查

**前置条件：**
- `market_statistics_cache` 中 `trade_date = "20250620"` 已有 9 条记录

**操作：** 调用 `task._has_trade_date_coverage("20250620")` 然后调用 `task.execute()`

**预期结果：**
- `_has_trade_date_coverage` 返回 `True`
- `execute()` 返回 `{"skipped": True, "count": 0}`
- 不会重复生成缓存

**边界条件：** 只有 8 条时返回 `False`，会重新生成全部 9 条

### 2.3 leader_cycle 排行榜验证

**前置条件：**
- `1m` 周期内有多只股票多次涨停

**操作：** 查询缓存 `market_statistics:leader_cycle:1m:20250620`

**预期结果：**
- `rankings` 数组最多 30 条，按涨停次数降序排列
- 每条包含：`rank`, `ts_code`, `name`, `theme`, `limit_count`, `max_board`
- 如果该周期内无涨停数据，包含 `warnings: ["limit_list 在当前周期内暂无数据"]`

### 2.4 sentiment 数据覆盖不足

**前置条件：**
- `daily_stats` 仅有最近 10 天数据
- 请求周期为 `3m`（期望 66 天）

**操作：** 查询缓存 `market_statistics:sentiment:3m:20250620`

**预期结果：**
- `trend` 数组仅包含实际可用的交易日数据（≤10 条）
- `warnings` 包含覆盖不足提示，格式如 `"市场情绪数据 当前仅覆盖 X 个交易日，近三个月 统计暂按现有数据展示"`

### 2.5 backfill vs recover_trade_date 行为差异

#### backfill

- `DailyStatsTask` 支持 `backfill(start_date, end_date)`，对范围内每个交易日调用 `_compute_single_day(force=True)`
- 批量操作，不记录 sync marker
- `MarketStatisticsCacheTask` **不支持** `backfill`（没有实现该方法，`supports_backfill` 未设置或为 `False`）

#### recover_trade_date

| 特性 | DailyStatsTask | MarketStatisticsCacheTask |
|---|---|---|
| 校验交易日 | `validate_recovery_trade_date` | `validate_recovery_trade_date` |
| 计算 | `_compute_single_day(force=True)` | `_build_for_trade_date(trade_date)` |
| 记录 sync marker | 否 | 否（主动声明"不回退 sync marker"） |
| 返回格式 | `{"success": True, "count": 1, "source": "local_compute", "warnings": [...], ...}` | `{"success": True, "count": 9, "source": "local_cache_build", "warnings": [...], ...}` |
| 增量幂等 | 不检查，直接覆盖 | 不检查，直接覆盖 |

### 2.6 force=True 时的数据覆盖行为

**前置条件：**
- `daily_stats` 中已存在 `trade_date = "20250620"` 的记录
- 底层数据有变化（如补入了新的 stock_daily）

**操作：** 通过 `backfill` 或 `recover_trade_date` 调用，传入 `force=True`

**预期结果：**
- `_compute_daily_stats` 使用 `upsert=True`，会覆盖已有记录的所有字段
- `_compute_sector_ranking` 先 `delete_many` 再 `insert_many`，完全覆盖
- `analysis_manager.analyze_and_store` 使用 `upsert=True`，完全覆盖
- 旧的 `created_at` 被新的 `updated_at` 替代
- 最终 `daily_stats`, `sector_ranking`, `market_analysis` 三张表均为最新计算结果

### 2.7 execute 幂等性

**前置条件：**
- `daily_stats` 中已有 `trade_date = "20250620"` 的记录

**操作：** 调用 `task.execute()`（通过调度器触发的正常执行）

**预期结果：**
- `mongo_manager.is_synced("daily_stats", "20250620")` 返回 `True`（取决于 sync_records 中该 sync_type 的 sync_date >= "20250620"）
- 如果 `_check_and_backfill` 没有发现缺失日期，则直接返回 `{"skipped": True}`
- **不会**重新计算已有日期的数据

---

## 代码走查验证结果

**走查日期**: 2026-06-21 | **方法**: 代码走查 | **结果**: 14/14 通过

| 用例 | 结果 | 走查依据 |
|------|------|----------|
| 1.1 | ✅ PASS | `_compute_single_day` (daily_stats.py:213-250): `_compute_sector_ranking` → `_compute_daily_stats` → `analysis_manager.analyze_and_store`。sector_ranking 从 moneyflow_industry/concept 取前/后20名。daily_stats 从 limit_list + stock_daily 统计 |
| 1.2.1 | ✅ PASS | stock_daily 为空时 `pct_chg_list` 保持空列表 → median=None, up/down/flat=0 (daily_stats.py:447-475)。其他字段（limit_list/成交额/指数）独立计算不受影响 |
| 1.2.2 | ✅ PASS | limit_data 为空 → 整个 limit_list 统计块跳过 (daily_stats.py:415)，所有连板/涨跌停字段保持初始值 0。`seal_rate=0` (line 551)。`promotion_rate=None` (line 592-593, 无前日数据) |
| 1.3 | ✅ PASS | `_compute_sector_ranking` (daily_stats.py:268-296): sorted by pct_change desc → [:20]=top, [-20:][::-1]=bottom。先 `delete_many` 再 `insert_many` (lines 337-344)。数据不足20条时输出实际数量（切片 [:20] 自动处理） |
| 1.4 | ✅ PASS | `_compute_daily_stats` (daily_stats.py:427-438): limit_times 1-5 分档 + 6+ 聚合。`broken_limit_count` 由 `open_times>0` 计数 (line 440-441)。`cont_board_count = limit_2+limit_3+limit_4+limit_5+limit_6_plus` (line 554-557) |
| 1.5 | ✅ PASS | `seal_rate = limit_up / (limit_up + broken) * 100` (daily_stats.py:547-549)。边界: 两者均为 0 时 seal_rate=0 (line 551) |
| 1.6 | ✅ PASS | `analyze_and_store` (analysis_manager.py:1234-1432) 使用 V2.3 双趋势系统。核心分→3日EMA→趋势分→原始评分→5日EMA→双趋势3日判定→`identify_cycle_by_trends` (line 691-735)。7种周期 + 仓位建议 (POSITION_ADVICE lines 39-47) 完整映射 |
| 1.7 | ✅ PASS | `load_ma10_baseline` (analysis_manager.py:146-243) 取最近10天历史。`data_count < 10` 时日志 INFO。`_calc_relative_score` 在 avg=None 时返回 `max_score*0.5` (line 346)。`identify_cycle_by_trends` 在数据不足时双趋势为 "flat" → CHAOS |
| 2.1 | ✅ PASS | `_build_for_trade_date` (market_statistics_cache.py:91-122): 1 limit_snapshot + 4×(leader_cycle + sentiment) = 9。PERIODS=("1w","1m","3m","1y") (line 42) |
| 2.2 | ✅ PASS | `_has_trade_date_coverage` (line 124-126): count >= 9 返回 True。覆盖率不足时重新生成。execute() 中 already_synced && coverage_ok → skip (line 56-57) |
| 2.3-2.4 | ✅ PASS | 各周期的 leader_cycle/sentiment 通过 `_build_statistics_leader_cycle_payload` / `_build_statistics_sentiment_payload` 构建。leader_cycle rankings 最多 30 条，sentiment 覆盖不足时含 warnings |
| 2.5 | ✅ PASS | DailyStatsTask: `supports_backfill=True` (daily_stats.py:63) + `backfill()` 方法 (line 166-192)。MarketStatisticsCacheTask: 无 backfill 方法，无 `supports_backfill` 属性。recover_trade_date 行为对照准确 |
| 2.6 | ✅ PASS | force=True: `_compute_daily_stats` upsert=True (daily_stats.py:563-568)，`_compute_sector_ranking` delete_many + insert_many (lines 337-344)，`analyze_and_store` upsert=True (analysis_manager.py:1425-1430) — 完全覆盖 |
| 2.7 | ✅ PASS | execute() 先 `is_synced` → skip (daily_stats.py:87-95)，`_check_and_backfill` 只处理缺失日期 (daily_stats.py:118-164)。market_statistics_cache 同样 `is_synced + coverage_ok` → skip (market_statistics_cache.py:54-57) |
