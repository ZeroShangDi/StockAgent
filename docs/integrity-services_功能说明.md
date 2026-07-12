# 服务-完整性与恢复功能说明

## 概述

完整性与恢复模块 (`nodes/data_sync/services/`) 为 DataSync 提供核心链路数据完整性检查、按交易日定向恢复和历史补缺队列管理三大能力。该模块确保每日收盘后的核心数据集达到"可交易分析"状态。

## 文件结构

```
nodes/data_sync/services/
├── core_integrity.py      # 核心链路完整性检查
├── recovery_contract.py   # 恢复契约（交易日校验、结果封装）
└── backfill_queue.py      # 历史补缺任务队列
```

---

## 1. 核心完整性检查 (`core_integrity.py`)

### 1.1 CORE_DATASETS（核心数据集列表）

定义了 DataSync 收盘后必须就绪的 8 个核心数据集：

```
["stock_daily", "index_daily", "daily_basic",
 "moneyflow_industry", "moneyflow_concept", "limit_list",
 "daily_stats", "market_statistics_cache"]
```

### 1.2 GRACEFULLY_DEGRADED_DATASETS（允许降级的数据集）

由于上游数据源权限/接口限制，以下 2 个数据集允许暂时为空：

```
{"moneyflow_industry", "moneyflow_concept"}
```

当 Tushare Token 缺少 `moneyflow_ind_dc` 权限时，这两个数据集状态标记为 `degraded` 而非 `missing`，不阻塞完整性判断。

### 1.3 关键常量

| 常量 | 值 | 说明 |
|------|---|------|
| `CORE_INDEX_CODES` | `["000001.SH", "399001.SZ", "399006.SZ"]` | 三大核心指数 |
| `MARKET_STATISTICS_EXPECTED_COUNT` | 9 | 市场统计缓存期望文档数 |
| `STOCK_DATASET_COVERAGE_THRESHOLD` | 0.85 (85%) | 股票级数据集覆盖率阈值 |
| `DEFAULT_RECOVERABILITY` | 完整恢复能力 | mode=full, can_recover/backfill/rerun=True |

### 1.4 核心函数: `build_core_integrity_overview(days=3)`

构建最近 `days` 个交易日的核心链路完整性概览。

**执行流程:**

```
1. 获取最近交易日 (latest_trade_date)
   └── 通过 data_source_manager.get_latest_trade_date()

2. 获取最近 days 个交易日列表
   └── 从交易日历中取最近 days 个

3. 统计活跃上市股票数量
   └── 过滤: list_status="L", name 不含"退"

4. 构建最新交易日 SLA 期望
   └── _build_latest_trade_date_expectation(latest_trade_date)

5. 对每个交易日:
   ├── 查询各数据集文档数 (_gather_counts)
   ├── 按数据集类型判定状态 (_build_dataset_statuses)
   │   ├── stock_daily / daily_basic: 覆盖率 >= 85% 判定
   │   ├── index_daily: 三大指数全部就绪
   │   ├── moneyflow_*: 空数据时标记为 degraded
   │   ├── limit_list: 有数据或执行成功即可
   │   ├── daily_stats: 至少 1 条记录
   │   └── market_statistics_cache: 至少 9 条记录
   └── 最新交易日根据 SLA 窗口调整状态
```

**返回结构:**

```python
{
    "success": True,
    "days": 3,
    "latest_trade_date": "20240601",
    "latest_trade_date_expected_ready": True,    # 是否已过期望就绪时间
    "latest_trade_date_awaiting_sync_window": False,  # 是否在等待窗口
    "latest_trade_date_syncing_window": False,       # 是否在同步窗口
    "latest_trade_date_failed_after_reached": False,  # 是否已过告警时间
    "latest_trade_date_sla_phase": "historical",  # waiting_window/syncing_window/failed/historical
    "latest_ready": True,             # 最新日是否全部就绪
    "latest_effectively_ready": True, # 考虑了SLA窗口后的实际就绪状态
    "recent_window_ready": True,      # 窗口内是否有未完成的阻塞日
    "ready_trade_dates": [...],       # 已就绪的交易日
    "incomplete_trade_dates": [...],  # 未完成的交易日
    "blocking_incomplete_trade_dates": [...],  # 阻塞级未完成（expected_ready=True 的）
    "pending_trade_dates": [...],     # 等待中的交易日（在SLA窗口内）
    "overview": [...],                # 每日详细状态
}
```

### 1.5 SLA 时间窗口机制 (`_build_latest_trade_date_expectation`)

基于三个可配置时间点（本地时间），判定最新交易日所处的阶段：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `core_ready_check_after_local_time` | 15:30 | 开始检查（在此之前为 waiting_window） |
| `core_ready_expected_after_local_time` | 16:10 | 期望就绪（此之后 expected_ready=True） |
| `core_ready_fail_after_local_time` | 17:00 | 告警触发（此之后 failed_after_reached=True） |

**SLA 阶段状态机:**

```
[收盘]
  │
  ├── 15:30 前  → phase = "waiting_window"
  │   数据集未就绪标记为 waiting_window（不是 missing）
  │   recovery_allowed = False
  │
  ├── 15:30 ~ 16:10 → phase = "syncing_window"
  │   数据集未就绪标记为 syncing_window
  │   recovery_allowed = True
  │
  ├── 16:10 ~ 17:00 → phase = "overdue"
  │   expected_ready = True
  │   未就绪状态标记为 missing
  │
  └── 17:00 后 → phase = "failed"
      failed_after_reached = True
      未就绪状态标记为 failed
      触发 critical 级别告警
```

非今日日期直接设为 `historical` 阶段，`expected_ready = True`。

### 1.6 数据集状态判定规则

#### 股票级覆盖率判定 (`_coverage_status`)
- 适用于: `stock_daily`, `daily_basic`
- 判定: `coverage = count / listed_stock_count`
- OK: `count > 0 AND coverage >= 0.85`
- 状态: ready / warning (count > 0 but coverage < 85%) / missing (count = 0)

#### 指数就绪判定
- 适用于: `index_daily`
- 判定: `count >= 3`（三大核心指数全部有数据）
- OK: True/False
- 状态: ready / warning (count > 0) / missing (count = 0)

#### 资金流向降级判定 (`_moneyflow_degraded_status`)
- 适用于: `moneyflow_industry`, `moneyflow_concept`
- 有数据时按一般存在性判定
- 无数据时: OK=True, state="degraded", 提示权限不足

#### 存在性+执行记录判定 (`_presence_or_executed_status`)
- 适用于: `limit_list`
- OK: `count > 0 OR execution_succeeded`
- 说明: 执行成功但没有涨停/跌停是合法状态

#### 存在性判定 (`_presence_status`)
- 适用于: `daily_stats`, `market_statistics_cache`
- 判定: `count >= expected_min`

### 1.7 可恢复性描述 (`DEFAULT_RECOVERABILITY`)

每个核心数据集都有关联的可恢复性元数据：

```python
{
    "mode": "full",                  # 恢复模式
    "can_recover_trade_date": True,  # 支持按交易日定向恢复
    "can_backfill": True,            # 支持进入夜间补缺队列
    "can_rerun": True,               # 支持重跑
    "severity_on_missing": "warning",# 缺失时的严重级别
}
```

---

## 2. 恢复契约 (`recovery_contract.py`)

### 2.1 `validate_recovery_trade_date(trade_date)`

校验恢复目标日期是否为有效的交易日。

**输入:** `trade_date` (str, YYYYMMDD格式)

**校验流程:**
1. 检查格式：必须为 8 位数字
2. 通过 `data_source_manager.get_trade_calendar(start=trade_date, end=trade_date)` 查询交易日历
3. 若 `trade_date` 不在交易日列表中，返回 `skipped=True, reason="non_trade_date"`

**返回值:**
```python
{
    "ok": True/False,        # 是否可恢复
    "success": True/False,   # 校验是否成功（即使 skipped 也是 True，异常才是 False）
    "trade_date": "20240601",
    "skipped": True/False,   # 是否跳过恢复
    "reason": "non_trade_date" / None,  # 跳过原因
    "source": "tushare",     # 交易日历数据源
    "warnings": [...],       # 警告列表
}
```

### 2.2 `skipped_recovery_result(job_name, guard)`

为校验失败/跳过的恢复操作生成统一的结果结构。

**作用:** 确保所有调用方对被跳过的恢复操作返回一致的字段结构（`success`, `count`, `trade_date`, `skipped`, `reason`, `sources`, `warnings`）。

### 2.3 `compact_sources(sources, default=None)`

将采集结果中的来源信息压缩为稳定、去重、可读的列表。支持列表/元组/集合嵌套展开。

### 2.4 `extract_sources_from_parallel_result(result, default=None)`

从并行恢复结果中提取数据源列表。遍历 `result["results"]`，收集成功的 item 中的 `source` 和 `sources`。

### 2.5 `primary_source(sources, default="unknown")`

从来源列表中提取主数据源标识。单个来源返回自身，多个返回 `"multiple"`。

### 2.6 `build_recovery_warnings(guard, failed_count=0, failed_items=None)`

构建恢复告警信息，合并不超过 3 条失败明细。

---

## 3. 历史补缺队列 (`backfill_queue.py`)

### 3.1 `BackfillQueueService` 类

DataSync 历史补缺队列服务，负责可靠地小批量领取和更新补缺任务状态。

**设计原则:** 队列只负责领取和状态管理。具体数据恢复仍复用各任务的 `recover_trade_date` 能力，避免在队列层捏造或绕开采集器校验逻辑。

### 3.2 核心方法

#### `enqueue(dataset, target_trade_date, **kwargs)`

创建一个补缺任务。关键特性：同一 `dataset/date/window` 会去重。

参数:
- `dataset`: 数据集名称（如 `stock_daily`）
- `target_trade_date`: 目标交易日
- `start_date` / `end_date`: 可选日期范围
- `priority`: 优先级（默认100）
- `created_by`: 创建来源（默认 "manual"）
- `payload`: 额外负载数据

#### `list_jobs(status=None, dataset=None, limit=20)`

列出补缺任务，支持按状态和数据集合过滤。

#### `run_once(node, limit, max_attempts, **kwargs)`

领取并执行一小批补缺任务（核心方法）。

**执行流程:**
```
1. 检查预算限额:
   ├── max_jobs_per_night: 每夜最大作业数（配置: settings.data_sync.backfill_max_jobs_per_night）
   ├── max_external_requests_per_night: 每夜最大外部请求数
   └── consecutive_failure_limit: 连续失败上限（配置: settings.data_sync.backfill_consecutive_failure_limit）
   └── 任一超限 -> stopped_reason

2. 循环领取任务（最多 limit 个）:
   ├── mongo.claim_backfill_jobs(limit=1, node_id, max_attempts)
   ├── 依赖 node._recover_job_trade_date(dataset, trade_date)
   │    trigger="backfill_queue"
   │    force_backfill_window=True
   ├── 成功 -> mark_backfill_job_done
   └── 失败 -> mark_backfill_job_failed (含 max_attempts 判断)

3. 每步更新预算状态:
   └── mongo.record_backfill_budget_usage(budget_key, job_success, external_requests, result)
```

**停止原因:**
- `backfill_job_budget_disabled`: `max_jobs_per_night <= 0`
- `backfill_job_budget_exhausted`: 已消耗作业数达到上限
- `backfill_request_budget_disabled`: `max_external_requests_per_night <= 0`
- `backfill_request_budget_exhausted`: 外部请求数达到上限
- `backfill_consecutive_failures_exhausted`: 连续失败次数达到上限

**返回值:**
```python
{
    "success": True,
    "claimed": 5,           # 领取的任务数
    "success_count": 3,     # 成功完成的
    "failed_count": 2,      # 失败的
    "stopped_reason": None, # 停止原因
    "budget_date": "20240601",
    "budget": {             # 预算状态
        "state": {...},
        "max_jobs_per_night": 100,
        "max_external_requests_per_night": 500,
        "consecutive_failure_limit": 10,
    },
    "results": [...]        # 每个任务的结果明细
}
```

### 3.3 相关配置项

| 配置项 | 说明 |
|--------|------|
| `backfill_jobs_per_round` | 每轮领取任务数 |
| `backfill_max_attempts` | 单个任务最大重试次数 |
| `backfill_max_jobs_per_night` | 每夜最大作业数（0=禁用） |
| `backfill_max_external_requests_per_night` | 每夜最大外部请求数 |
| `backfill_consecutive_failure_limit` | 连续失败上限 |
