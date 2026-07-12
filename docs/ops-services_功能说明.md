# 服务-运维与分析功能说明

## 概述

运维与分析模块为 DataSync 提供全面的运行状态监控、市场统计聚合和市场晴雨表分析能力。包含运维总览聚合、市场统计数据构建、Coze 工作流客户端和市场晴雨表服务四大组件。

## 文件结构

```
nodes/data_sync/services/
├── ops_summary.py              # 运维总览服务
└── market_statistics.py        # 市场统计载荷构建

src/analysis/
├── coze_workflow_client.py     # Coze 工作流客户端
└── market_weather.py           # 市场晴雨表服务
```

---

## 1. 运维总览 (`ops_summary.py`)

### 1.1 核心函数: `build_ops_summary()`

聚合 DataSync 运行态最关键的信息，是 `--ops-summary` CLI 命令的底层实现。

**函数签名:**
```python
async def build_ops_summary(
    *,
    integrity_days: int = 3,
    recent_job_limit: int = 10,
    recent_failure_lookback_hours: int = 24,
    recent_event_lookback_hours: int = 24,
    core_runtime_lookback_hours: int = 24,
) -> Dict[str, Any]
```

### 1.2 聚合维度

`build_ops_summary` 将以下 11 个子查询的结果聚合到一个统一的结构中：

| 维度 | 来源 | 说明 |
|------|------|------|
| `core_integrity` | `build_core_integrity_overview()` | 核心链路完整性 |
| `sync_targets` | `mongo_manager.get_target_status()` | 主库/镜像库状态 |
| `readiness_marker` | MongoDB `readiness_markers` | 最近的就绪标记 |
| `recent_job_executions` | MongoDB `job_execution_records` | 最近作业执行记录 |
| `recent_effective_job_executions` | 同上（status in success/failed） | 最近有效作业（排除跳过） |
| `recent_core_effective_job_executions` | 同上（核心作业+有效） | 核心作业有效记录 |
| `recent_failed_job_executions` | `get_recent_failed_job_executions()` | 最近失败作业 |
| `recent_ops_events` | `get_recent_ops_events()` | 最近运维事件 |
| `recent_dead_letters` | `get_recent_dead_letters()` | 最近死信/脏数据样本 |
| `backfill_queue_status` | `get_backfill_queue_status()` | 补缺队列状态 |
| `core_job_runtime_summary` | `get_core_job_runtime_summary()` | 核心任务运行表现 |

### 1.3 告警机制 (`_build_alerts`)

从 11 个维度提取告警信号，使用优先级分层：同一类别中只取最高严重级别的告警（避免重复报警）。

**告警严重级别:**
| 级别 | 含义 |
|------|------|
| `critical` | 核心链路不可用、主库不健康 |
| `warning` | 有未恢复的失败、性能异常、镜像降级 |
| `info` | 状态恢复通知、预算耗尽等 |

**告警规则（按检查顺序）:**

| 触发条件 | 严重级别 | 告警代码 |
|---------|---------|---------|
| 最新交易日核心链路未就绪 + 已过期 | critical | `core_chain_not_ready` |
| 最新交易日在等待窗口中 | info | `latest_trade_date_awaiting_sync_window` |
| 最近窗口有未完成日 | warning | `recent_window_incomplete` |
| 主库不健康 | critical | `primary_target_unhealthy` |
| 镜像库启用但不健康 | warning | `mirror_target_unhealthy` |
| 镜像写路径当前降级 | warning | `mirror_write_path_degraded` |
| 镜像写路径最近恢复 | info | `mirror_write_path_recovered` |
| 镜像有写失败 | warning | `mirror_write_failures_detected` |
| 核心数据源超时（当前进程） | warning | `core_data_source_timeouts_detected` |
| 核心数据源降级/回退（当前进程） | warning | `core_data_source_degradation_detected` |
| 非核心数据源超时 | info | `non_core_data_source_timeouts_detected` |
| 非核心数据源回退 | info | `non_core_data_source_fallbacks_detected` |
| 核心作业最近失败 | warning | `recent_core_job_failures` |
| 非核心作业最近失败 | info | `recent_non_core_job_failures` |
| 有未恢复的 warning/critical 运维事件 | warning | `recent_warning_ops_events` |
| 核心采集器产生死信 | warning | `recent_core_dead_letters` |
| 非核心采集器产生死信 | info | `recent_non_core_dead_letters` |
| 核心作业无最近运行样本 | warning | `core_jobs_without_recent_samples` |
| 核心作业运行时间异常 | warning | `core_job_runtime_outliers` |
| 补缺队列连续失败熔断 | warning | `backfill_queue_failure_circuit_open` |
| 补缺队列预算耗尽 | info | `backfill_budget_exhausted` |
| 补缺队列有失败任务 | warning | `backfill_queue_failed_jobs` |
| 最近通过恢复流程标记就绪 | info | `recent_core_gap_recovery` |

### 1.4 总探针系统 (`build_probe_checks`)

生成 9 个布尔探针，便于 CLI 严格模式和监控系统直接消费：

| 探针 | 说明 |
|------|------|
| `summary_success` | 总览构建成功 |
| `primary_target_healthy` | 主库健康 |
| `latest_core_effectively_ready` | 最新核心链路有效就绪 |
| `recent_window_ready` | 最近窗口内无阻塞未完成日 |
| `no_unresolved_recent_failures` | 无未恢复的失败 |
| `no_unresolved_warning_events` | 无未恢复的告警事件 |
| `no_core_data_source_degradation` | 无核心数据源降级 |
| `no_core_runtime_outliers` | 无核心任务运行异常 |
| `backfill_queue_operational` | 补缺队列可运行 |

### 1.5 运行状态三态判定 (`derive_operational_status`)

```
healthy   - 全部探针通过，无 warning/critical 告警
degraded  - 部分探针不通过，或有 warning 级别告警（无 critical）
critical  - 有 critical 告警，或主库不健康，或核心链路未就绪
```

### 1.6 失败恢复检测

#### 未恢复失败检测 (`_find_unresolved_failure_records`)
- 遍历失败记录，检查是否被同 job_name 的后续成功执行覆盖
- 覆盖条件: 成功记录的 `started_at > 失败记录的 started_at`，且 `target_trade_date` 匹配

#### 未恢复告警检测 (`_find_unresolved_warning_ops_records`)
- 对 `core_gap_recovery_completed` 事件: 若 readiness_marker 状态为 ready，且 marker 时间戳晚于事件时间 -> 已恢复
- 对 `core_job_failed` 事件: 若同 job_name 有后续成功记录 -> 已恢复
- 对其他事件: 若同 event_type 有后续 info 级别事件 -> 已恢复

### 1.7 核心任务运行摘要 (`get_core_job_runtime_summary`)

聚合每个核心任务在指定窗口内的运行表现：

| 统计项 | 说明 |
|--------|------|
| `total_runs` / `executed_runs` | 总运行次数 / 有效执行次数（排除skip） |
| `success_count` / `failure_count` | 成功/失败次数 |
| `success_rate` | 成功率 = success / executed |
| `avg/p95/max/min_duration_ms` | 耗时分布 |
| `latest_executed_*` | 最近一次有效执行的信息 |

**异常检测:** (`_identify_core_runtime_outliers`)
- `latest_executed_duration_ms >= 10分钟` -> 异常
- `p95_duration_ms >= 5分钟` -> 异常

### 1.8 补缺队列状态 (`get_backfill_queue_status`)

返回补缺队列的统计摘要，避免在 ops-summary 中输出过大明细：

- 按状态统计: pending, running, failed, paused, done
- 最近作业样本（limit=10）
- 最近预算记录（limit=3）
- 预算耗尽判断: `jobs_consumed >= max_jobs_per_night` 或 `external_requests >= max_external_requests_per_night`
- 熔断判断: `consecutive_failures >= consecutive_failure_limit`

### 1.9 其他查询函数

| 函数 | 说明 |
|------|------|
| `get_recent_failed_job_executions(limit, lookback_hours, core_jobs_only)` | 最近失败作业，支持核心/全部过滤 |
| `get_recent_ops_events(limit, severities, lookback_hours)` | 最近运维事件，支持按严重级别过滤 |
| `get_recent_dead_letters(limit, lookback_hours)` | 最近死信样本，区分核心/非核心 |
| `get_core_job_runtime_summary(lookback_hours)` | 核心作业运行时摘要 |
| `get_backfill_queue_status(limit)` | 补缺队列状态摘要 |

---

## 2. 市场统计载荷构建 (`market_statistics.py`)

提供市场统计预聚合所需的纯数据构建函数，不包含持久化逻辑（持久化由调用方 job 负责）。

### 2.1 周期配置

| 周期 | PERIOD_DAY_MAP | PERIOD_LABEL_MAP |
|------|---------------|-----------------|
| 1w | 5 个交易日 | 近一周 |
| 1m | 22 个交易日 | 近一个月 |
| 3m | 66 个交易日 | 近三个月 |
| 1y | 250 个交易日 | 近一年 |

### 2.2 涨停梯队快照 (`_build_statistics_limit_snapshot_payload`)

**用途:** 构建单个交易日的涨停梯队全景。

**涨停类型识别 (`_resolve_limit_type`):**

| 类型 | 判定条件 |
|------|---------|
| 一字板 | `first_time in {"092500", "093000"}` 且 `open_times=0` |
| 回封板 | `open_times >= 2` |
| 尾盘板 | `last_time >= "144500"` |
| T字板 | `first_time <= "093500"` 且 `open_times > 0` |
| 换手板 | 换手率 >= 8 或炸板过，其余默认 |

**板数分组:**
- 首板 (board_count=1), 2板, 3板, 4板, 5板, 6板, 7板+ (board_count>=7)

**返回结构:**
```python
{
    "trade_date": "2024-06-01",
    "source": "limit_list",
    "warnings": [],
    "limit_fleet": {
        "total_count": 50,
        "groups": [{"key": "7板+", "label": "7板+", "count": 3, "items": [...]}, ...],
        "detail": [...]
    },
    "limit_types": {
        "groups": [{"type": "一字板", "count": 5, "share": 10.0, "items": [...]}, ...],
        "detail": [...]
    }
}
```

### 2.3 涨停梯队周期统计 (`_build_statistics_leader_cycle_payload`)

**用途:** 统计一个周期内的涨停龙头排行和晋级率趋势。

**龙头排行:** 按涨停次数和最高连板数排序（Top 30），含股票名称、主题、代码。

**晋级率趋势:** 每日计算各板位向上一板位的晋级率：
- `step12`: 1板->2板晋级率
- `step23`: 2板->3板晋级率
- `step34`, `step45`, `step56`, `step67`, `step7Plus`
- `total`: 总晋级率（有晋级/前日涨停总数）

### 2.4 市场情绪序列 (`_build_statistics_sentiment_payload`)

**用途:** 构建周期内的市场情绪时间序列数据。

**数据来源:**
- `daily_stats` 集合: 涨停数(limit_up_count)、炸板数(broken_limit_count)
- `market_analysis` 集合: 晋级率(promotion_rate)等分析结果
- `limit_list` 集合: 涨停股详情
- `stock_daily` 集合: 涨停股次日开盘/收盘表现

**每日情绪指标:**
| 指标 | 计算方式 |
|------|---------|
| `promotion_rate` | 优先取 analysis 记录，fallback 为 `晋级数/前日涨停数` |
| `explosion_rate` | `炸板数 / (涨停数+炸板数)` |
| `avg_follow_return` | 前日涨停股次日收盘平均收益率 |
| `open_premium` | 前日涨停股次日开盘平均溢价 |
| `high_premium` | 前日涨停股次日最高平均溢价 |

**覆盖度警告:** 若可用交易日数不足周期要求天数，在返回的 `warnings` 中添加覆盖度提示。

### 2.5 辅助函数

| 函数 | 说明 |
|------|------|
| `_get_market_trade_dates(limit)` | 从 daily_stats 获取可用交易日列表 |
| `_get_stock_meta_map(ts_codes)` | 批量获取股票元信息（name/industry/market） |
| `_resolve_period_trade_dates()` | 从完整交易日列表中截取指定周期 |
| `_safe_float(val, default)` | 安全数值转换 |
| `_display_trade_date()` | YYYYMMDD -> YYYY-MM-DD 显示格式 |

---

## 3. 市场晴雨表服务 (`src/analysis/market_weather.py`)

### 3.1 `MarketWeatherService` 类

调用 Coze 市场晴雨表工作流，解析返回的 6 个因子指标，计算交易信号，并持久化到 MongoDB `market_weather_daily` 集合。

**配置依赖:** `settings.coze.market_indicator_workflow_id`

### 3.2 6 个核心因子

| 因子名称 | 字段名 | 说明 |
|---------|--------|------|
| 市场温度指数 | `temperature_index` | 综合温度，范围 0-100 |
| 涨停溢价延续因子 | `limit_premium_factor` | 涨停溢价强度 |
| 趋势惯性累积因子 | `trend_factor` | 趋势持续度 |
| 量价共振强度因子 | `volume_factor` | 量价配合度 |
| 市场广度扩散因子 | `breadth_factor` | 市场参与度 |
| 多空动能极化因子 | `momentum_factor` | 多空力量对比 |

### 3.3 交易信号计算 (`_build_signal`)

#### 做不做（action）—— 基于仓位指数

仓位指数公式:
```
position = temp * 0.4
         + limit * 20
         + (trend * 0.6 + volume * 0.4) * 20
         - ((1 - breadth) * 0.6 + (1 - momentum) * 0.4) * 15
```

增强修正:
- 高温高动量 (temp > 70 and momentum > 0.7): +5 分
- 低温低动量 (temp < 30 and momentum < 0.3): -5 分

最终仓位指数: `clamp(position, 10, 90)`

| 仓位指数 | 操作建议 (action) |
|---------|-----------------|
| <= 30 | 持币 |
| <= 45 | 观望 |
| <= 65 | 持筹 |
| > 65 | 积极 |

#### 做多少（position）—— 仓位指数值

0-100 之间的整数，值越高表示可参与度越高。

#### 做什么（strategy）—— 操作策略

| 触发条件 | 策略 |
|---------|------|
| (temp<35 and limit<0.5 and momentum<0.4) 或 (temp<40 and volume>0.7 and momentum<0.5) | 低吸 |
| (limit>0.7 and trend>0.6 and temp>60) 或 (temp>65 and breadth>0.7 and momentum>0.6) | 追高 |
| trend>0.45 and volume>0.45 | 波段 |
| 其他 | 防守 |

#### 说明（note）—— 操作注释

根据 action + strategy 组合生成中文操作说明。

附加风险提示:
- `breadth < 0.4`: 市场广度不足警告
- `momentum < 0.3`: 多空动能偏弱警告
- `volume > 0.85 and trend < 0.5`: 量价背离风险
- `limit > 0.8 and breadth < 0.5`: 高溢价陷阱

### 3.4 数据流程

```
1. fetch_one(trade_date)
   ├── 调用 CozeWorkflowClient.run(workflow_id, {"type": "市场晴雨表", "date": display_date})
   ├── _parse_indicator -> 解析 getMarketIndicator 嵌套 JSON
   └── _build_record -> 计算 signal，组装完整记录

2. store_record(record)
   └── MongoDB upsert (by trade_date)

3. sync_recent(days=30, overwrite=False)
   ├── 获取最近 days 个交易日
   ├── 默认跳过已存在的记录 (overwrite=False 时)
   ├── 批量并发 fetch (market_weather_max_concurrent 控制)
   └── bulk_upsert 持久化
```

### 3.5 关键方法

| 方法 | 说明 |
|------|------|
| `fetch_one(trade_date)` | 获取单个交易日的晴雨表数据 |
| `store_record(record)` | 存储单条记录 |
| `list_history(days=30)` | 列出历史记录（按 trade_date 正序） |
| `sync_trade_dates(trade_dates, overwrite)` | 批量同步指定日期（支持去重和并发控制） |
| `sync_recent(days=30, overwrite)` | 同步最近 days 个交易日 |
| `rebuild_signal_for_record(record)` | 对已有记录重新计算信号（可用于调整公式后回溯） |

### 3.6 配置项

| 配置项 | 说明 |
|--------|------|
| `COZE_MARKET_INDICATOR_WORKFLOW_ID` | 晴雨表工作流 ID |
| `data_sync.market_weather_max_concurrent` | 并发获取数（默认从 settings 读取） |

---

## 4. Coze 工作流客户端 (`src/analysis/coze_workflow_client.py`)

### 4.1 `CozeWorkflowClient` 类

轻量级 Coze Workflow HTTP 客户端，用于调用与股票插件无关的独立 Coze 工作流。

**区别于 `CozeWorkflowAdapter`:**
- `CozeWorkflowAdapter`: 数据源适配器，通过统一工作流调用多个股票插件
- `CozeWorkflowClient`: 通用 HTTP 客户端，用于调用独立工作流（如市场晴雨表）

### 4.2 核心方法

#### `run(workflow_id, parameters)`

**流程:**
1. 构建 `POST {api_base}/v1/workflow/run` 请求
2. 请求体: `{"workflow_id": "...", "parameters": {...}}`
3. 验证响应: `code > 0` 时抛出 `RuntimeError`
4. 返回完整 JSON payload

**超时配置:** 使用 `settings.coze.timeout`（默认 30 秒）

#### `decode_json_like(value)` (classmethod)

递归解析嵌套 JSON 字符串。Coze 工作流返回的数据中，某些字段的值是 JSON 字符串而非 JSON 对象，此方法递归展开所有层级的 JSON 字符串。

示例:
- `'{"key": "value"}'` -> `{"key": "value"}`
- `'[1, 2, 3]'` -> `[1, 2, 3]`
- 非 JSON 字符串保持原样
