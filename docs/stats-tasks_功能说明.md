# 数据处理-统计任务 功能说明

## 概述

统计任务模块包含两个核心 Task，负责在每日收盘后对已同步的基础行情数据进行聚合计算，产出板块排名、连板统计、涨跌统计、情绪周期分析以及市场统计预聚合缓存。

**代码位置：**

| 文件 | 类名 | 说明 |
|---|---|---|
| `nodes/data_sync/tasks/daily_stats.py` | `DailyStatsTask` | 每日统计：板块排名、涨跌统计、连板统计、情绪周期分析 |
| `nodes/data_sync/tasks/market_statistics_cache.py` | `MarketStatisticsCacheTask` | 市场统计缓存：1w/1m/3m/1y 预聚合 |

---

## 一、DailyStatsTask（每日统计任务）

### 1.1 基本信息

| 属性 | 值 |
|---|---|
| `name` | `daily_stats` |
| `dataset_name` | `daily_stats` |
| `resource_class` | `core` |
| `default_schedule` | `30 16 * * 1-5`（每个交易日 16:30） |
| `target_collections` | `daily_stats`, `sector_ranking`, `market_analysis` |
| `supports_backfill` | `True` |
| `INITIAL_SYNC_DAYS` | `30`（首次运行时自动回补最近 30 天的缺失数据） |

### 1.2 依赖

```python
dependencies = (
    "stock_daily",         # 个股日线（涨跌幅数据）
    "moneyflow_industry",  # 行业资金流向（板块排名来源）
    "moneyflow_concept",   # 概念板块资金流向（板块排名来源）
    "limit_list",          # 涨跌停列表（连板、涨跌停统计来源）
)
source_chain_keys = ("get_latest_trade_date", "get_trade_calendar")
```

### 1.3 执行流程

`execute()` 方法按以下步骤执行：

```
1. 获取最新交易日 (data_source_manager.get_latest_trade_date)
    |
2. _check_and_backfill() — 检查最近 30 天缺失数据并回补
    |   - 获取近30天交易日列表
    |   - 查 daily_stats.distinct("trade_date") 得已计算日期
    |   - 对缺失日期按时间顺序依次调用 _compute_single_day
    |
3. is_synced("daily_stats", latest_trade_date) — 检查当天是否已完成
    |   - 若已同步: 返回 skipped
    |   - 若未同步: 继续
    |
4. _compute_single_day(latest_trade_date)
    |   - _compute_sector_ranking(trade_date) → sector_ranking 集合
    |   - _compute_daily_stats(trade_date)     → daily_stats 集合
    |   - analysis_manager.analyze_and_store()  → market_analysis 集合
    |
5. mongo_manager.record_sync("daily_stats", latest_trade_date, count=1)
```

### 1.4 核心方法详解

#### 1.4.1 `_compute_single_day(trade_date, force=False)`

计算单个交易日的所有统计数据，按顺序调用三个子方法：

```python
async def _compute_single_day(self, trade_date: str, force: bool = False):
    # 1. 板块排名
    ranking_result = await self._compute_sector_ranking(trade_date)
    # 2. 每日综合统计
    stats_result = await self._compute_daily_stats(trade_date)
    # 3. 情绪周期分析（依赖前一天的 daily_stats）
    prev_stats = await mongo_manager.find_one(
        "daily_stats",
        {"trade_date": {"$lt": trade_date}},
        sort=[("trade_date", -1)],
    )
    analysis_result = await analysis_manager.analyze_and_store(
        stats=stats_result,
        prev_stats=prev_stats,
        mongo_manager=mongo_manager,
    )
```

**参数说明：**
- `trade_date`: 交易日，格式 `YYYYMMDD`，如 `"20250620"`
- `force`: 目前仅在 `backfill()` 和 `recover_trade_date()` 中传 `True`，但 `_compute_single_day` 本身不对该参数做特殊处理（仅透传）。实际覆盖行为由 `_compute_daily_stats` 中的 `upsert=True` 保证

#### 1.4.2 `_compute_sector_ranking(trade_date)` — 板块排名

**数据来源：**
- `moneyflow_industry` 集合：行业资金流向数据
- `moneyflow_concept` 集合：概念板块资金流向数据

**计算逻辑：**
1. 从 `moneyflow_industry` 查询 `{"trade_date": trade_date}` 的所有记录
2. 按 `pct_change` 字段降序排列
3. 取前 20 名为 `industry_top`（涨幅前20），后 20 名为 `industry_bottom`（跌幅前20）
4. 从 `moneyflow_concept` 重复相同逻辑，生成 `concept_top` 和 `concept_bottom`
5. 每次写入前先 `delete_many({"trade_date": trade_date})` 清理该日旧数据，再用 `insert_many` 写入

**写入 `sector_ranking` 集合的文档结构：**

```json
{
    "trade_date": "20250620",
    "ranking_type": "industry_top",     // industry_top | industry_bottom | concept_top | concept_bottom
    "rank": 1,                          // 排名，从 1 开始
    "ts_code": "BK0451.SH",            // 板块代码
    "name": "半导体",                    // 板块名称
    "pct_change": 3.45,                // 涨跌幅
    "net_amount": 1234567.89,          // 净流入金额
    "lead_stock": "000001.SZ"          // 领涨股
}
```

**索引：**
```python
IndexModel([("trade_date", DESCENDING), ("ranking_type", ASCENDING), ("rank", ASCENDING)], unique=True)
```

#### 1.4.3 `_compute_daily_stats(trade_date)` — 每日综合统计

这是最核心的方法，产出 20+ 个统计字段。按以下顺序从多个数据源聚合计算：

**步骤 1：从 `limit_list` 获取涨跌停数据**

查询：`{"trade_date": trade_date}`，投影 `ts_code`, `limit`, `limit_times`, `open_times`

处理逻辑：
| 字段 | 计算方式 |
|---|---|
| `limit_up_count` | `limit == "U"` 的记录数 |
| `limit_down_count` | `limit == "D"` 的记录数 |
| `limit_1` ~ `limit_5` | 按 `limit_times` 值分档统计涨停股票 |
| `limit_6_plus` | `limit_times >= 6` 的涨停股票数 |
| `max_limit_height` | 当日最高连板数 |
| `broken_limit_count` | 涨停股中 `open_times > 0`（曾炸板）的数量 |

**步骤 2：从 `stock_daily` 获取涨跌统计**

查询：`{"trade_date": trade_date}`，投影 `ts_code`, `pct_chg`

处理逻辑：
| 字段 | 计算方式 |
|---|---|
| `up_count` | `pct_chg > 0` 的股票数 |
| `down_count` | `pct_chg < 0` 的股票数 |
| `flat_count` | `pct_chg == 0` 的股票数 |
| `up_5pct_count` | `pct_chg >= 5` 的股票数 |
| `down_5pct_count` | `pct_chg <= -5` 的股票数 |
| `pct_chg_median` | 所有 `pct_chg` 的中位数（使用 Python `statistics.median`） |

**步骤 3：获取沪深港通资金流向**

调用：`data_source_manager.get_moneyflow_hsgt(trade_date=trade_date)`

写入字段：`hgt`, `sgt`, `north_money`, `ggt_ss`, `ggt_sz`, `south_money`（单位：百万元）

**步骤 4：获取两市成交额**

查询 `index_daily` 集合：
- 上证指数：`ts_code == "000001.SH"` → `sh_amount`
- 深证成指：`ts_code == "399001.SZ"` → `sz_amount`
- `total_amount = sh_amount + sz_amount`（单位：千元）

**步骤 5：获取大盘指数涨跌幅**

查询 `index_daily`：`ts_code == "000300.SH"`（沪深300）→ `index_pct_chg`

**步骤 6：计算衍生指标**

| 衍生指标 | 公式 |
|---|---|
| `total_stocks` | `up_count + down_count + flat_count` |
| `up_ratio` | `up_count / total_stocks * 100`（百分比） |
| `down_ratio` | `down_count / total_stocks * 100`（百分比） |
| `total_limit_up` | `limit_1 + limit_2 + limit_3 + limit_4 + limit_5 + limit_6_plus` |
| `seal_rate` | `limit_up_count / (limit_up_count + broken_limit_count) * 100`（封板率） |
| `cont_board_count` | `limit_2 + limit_3 + limit_4 + limit_5 + limit_6_plus`（2板及以上连板数） |

**步骤 7：计算晋级率 → `_compute_promotion_rate`**

#### 1.4.4 `_compute_promotion_rate(trade_date)` — 晋级率

昨日涨停股中，今日仍涨停的比例（百分比 0-100）。

```
1. 从 daily_stats 获取前一个交易日的 trade_date
2. 查询 limit_list 中前一日的涨停股（limit == "U"），提取 ts_code 集合 A
3. 查询 limit_list 中今日的涨停股，提取 ts_code 集合 B
4. promotion_rate = |A ∩ B| / |A| * 100
```

**写入方式：**

最终所有字段通过 `update_one` 以 `upsert=True` 模式写入 `daily_stats` 集合：
```python
await mongo_manager.update_one(
    "daily_stats",
    {"trade_date": trade_date},
    {"$set": stats},
    upsert=True,
)
```

`daily_stats` 唯一索引：`IndexModel([("trade_date", DESCENDING)], unique=True)`

### 1.5 回补机制

#### 自动回补（`_check_and_backfill`）

每次 `execute()` 时自动执行：
1. 获取最近 30 天的交易日列表（通过 `data_source_manager.get_trade_calendar`）
2. 查询 `daily_stats.distinct("trade_date")` 获取已计算日期
3. 对缺失日期按时间顺序依次调用 `_compute_single_day`
4. 每计算 10 天打印一次进度日志

#### 手动回补（`backfill(start_date, end_date)`）

通过 CLI `--backfill` 参数触发，支持指定日期范围：
```python
await DailyStatsTask.backfill("20250601", "20250620")
```
内部对范围内每个交易日调用 `_compute_single_day(date, force=True)`。

#### 定向恢复（`recover_trade_date(trade_date)`）

通过 CLI `--recover-latest-core-gaps` 或手动触发：
1. 先调用 `validate_recovery_trade_date(trade_date)` 校验交易日合法性
2. 调用 `_compute_single_day(trade_date, force=True)`
3. 返回结构化结果，包含 `warnings` 和 `source: "local_compute"`

### 1.6 情绪周期分析

统计完成后，由 `analysis_manager.analyze_and_store()` 进一步计算情绪评分和强度评分，产出 7 种周期判断：

| 周期 | 英文标识 | 含义 | 仓位建议 |
|---|---|---|---|
| 冰点期 | `ice_point` | 双评分极低（<20），空仓观望 | 0成 |
| 修复期 | `recovery` | 20≤双评分<40，有止跌迹象 | 2~3成 |
| 主升期 | `main_upward` | 双评分≥60，双趋势向上 | 7~10成 |
| 分歧期 | `divergence` | 评分背离或趋势背离 | 3~5成 |
| 退潮期 | `decline` | 双评分<40，双走弱 | 0~1成 |
| 混沌期 | `chaos` | 无明确周期 | 1~3成 |
| 未知 | `unknown` | 数据不足 | 0~2成 |

结果写入 `market_analysis` 集合，唯一索引：`IndexModel([("trade_date", DESCENDING)], unique=True)`

---

## 二、MarketStatisticsCacheTask（市场统计缓存任务）

### 2.1 基本信息

| 属性 | 值 |
|---|---|
| `name` | `market_statistics_cache` |
| `dataset_name` | `market_statistics_cache` |
| `resource_class` | `core` |
| `default_schedule` | `35 16 * * 1-5`（每日 16:35，在 DailyStats 之后 5 分钟） |
| `target_collections` | `market_statistics_cache` |
| `run_at_startup` | `False` |
| `PERIODS` | `("1w", "1m", "3m", "1y")` |

### 2.2 依赖

```python
dependencies = ("daily_stats", "limit_list", "stock_daily")
source_chain_keys = ("get_latest_trade_date",)
quality_checks = ("expected_cache_entries:9", "derived_dataset")
```

### 2.3 执行流程

```
1. 获取最新交易日
2. 检查 is_synced + 覆盖率是否 ≥9 条（_has_trade_date_coverage）
   → 若都满足，跳过
3. _build_for_trade_date(latest_trade_date) — 构建 9 条缓存
4. record_sync 记录同步状态
```

### 2.4 `_build_for_trade_date(trade_date)` — 缓存构建

每个交易日生成 **9 条缓存**（1 + 4×2 = 9）：

```
1. limit_snapshot (1条)
   - cache_type: "limit_snapshot"
   - cache_key: trade_date（如 "20250620"）
   - 数据来源: limit_list（当日涨停股）
   - 内容: 涨停梯队分组、涨停类型分组（一字板/T字板/换手板/回封板/尾盘板）

2. leader_cycle (4条，每个周期一条)
   - cache_type: "leader_cycle"
   - cache_key: "{period}:{trade_date}"（如 "1w:20250620"）
   - 内容: 涨停龙头排行榜(Top30)、逐日晋级率趋势

3. sentiment (4条，每个周期一条)
   - cache_type: "sentiment"
   - cache_key: "{period}:{trade_date}"（如 "1w:20250620"）
   - 数据来源: daily_stats + market_analysis + limit_list + stock_daily
   - 内容: 情绪趋势（晋级率、炸板率、昨日涨停今日收益等）
```

### 2.5 缓存键结构

**Redis 键格式：**
```
market_statistics:{cache_type}:{cache_key}
```

示例：
- `market_statistics:limit_snapshot:20250620`
- `market_statistics:leader_cycle:1w:20250620`
- `market_statistics:leader_cycle:1m:20250620`
- `market_statistics:leader_cycle:3m:20250620`
- `market_statistics:leader_cycle:1y:20250620`
- `market_statistics:sentiment:1w:20250620`
- ...等

**Redis TTL：** `DEFAULT_REDIS_TTL = 6 * 3600`（6小时）

**MongoDB 存储：**
集合 `market_statistics_cache`，文档结构：
```json
{
    "cache_type": "leader_cycle",
    "cache_key": "1w:20250620",
    "trade_date": "20250620",
    "payload": { ... },
    "updated_at": "2025-06-20T16:35:00Z"
}
```

读取时优先从 Redis 获取，Redis 未命中时回退到 MongoDB。

### 2.6 周期定义

| 周期 | 交易日数 | 说明 |
|---|---|---|
| `1w` | 5 | 近一周 |
| `1m` | 22 | 近一个月 |
| `3m` | 66 | 近三个月 |
| `1y` | 250 | 近一年 |

当实际可用交易日不足期望天数时（如 `daily_stats` 历史数据不足 1y），会自动添加 `warnings` 标记，API 返回时会提示用户数据覆盖不完整。

### 2.7 recover_trade_date

支持定向恢复指定交易日缓存，不回退 sync marker（区别于 `execute()` 的幂等检查）：

```python
async def recover_trade_date(self, trade_date: str):
    guard = await validate_recovery_trade_date(trade_date)
    built = await self._build_for_trade_date(trade_date)
    # 返回结构化结果，不调用 record_sync
```

### 2.8 调度协同

| 时间 | 任务 | 说明 |
|---|---|---|
| 16:30 | DailyStatsTask | 板块排名 + 连板统计 + 情绪分析 |
| 16:35 | MarketStatisticsCacheTask | 读取 DailyStats 产出，构建 9 条缓存 |
