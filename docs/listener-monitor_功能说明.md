# Listener/Monitor 节点功能说明

## 概述

Listener 节点（`AgentServer/nodes/listener/`）是 StockAgent 的实时行情监听与策略检测模块。通过每 60 秒轮询市场数据，评估 10 种内置策略的触发条件，生成预警通知，并根据流转规则自动执行股池迁移操作。

## 文件结构

```
AgentServer/nodes/listener/
├── node.py                       # ListenerNode 主节点 (1359行)
│
└── strategies/                   # 策略执行器目录
    ├── __init__.py               # 策略导出与注册
    ├── base.py                   # 策略基类 BaseStrategy (357行)
    ├── market_index_alert.py     # 指数指标预警策略
    ├── limit_open.py             # 涨跌停打开策略
    ├── price_change.py           # 涨跌幅阈值策略
    ├── intraday_price_move.py    # 盘中异动策略
    ├── ma5_buy.py                # 均线低吸策略
    ├── support_resistance.py     # 撑压线策略
    ├── fixed_stop_loss.py        # 固定止损策略
    ├── trailing_stop_loss.py     # 移动止损策略
    ├── position_pnl.py           # 持仓总盈亏策略
    └── position_intraday_pnl.py  # 盘中持仓盈亏变动策略
```

---

## 1. ListenerNode 主节点 (`node.py`)

### 1.1 核心配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `poll_interval` | 60s | 轮询间隔（最小 30s） |
| `poll_timeout_seconds` | 180s | 单次轮询超时（不低于 poll_interval） |
| `large_watch_batch` | 400 | 大批量分批拉取每批数量 |
| `large_watch_threshold` | 600 | 全市场模式切换为分批的阈值 |
| `limit_fetch_time` | 09:15 | 每日最早拉取涨跌停价格的时间 |
| `silent_outside_trading` | True | 非交易时间自动静默 |

### 1.2 节点启动流程 (`start`)

```
1. 初始化 Redis / MongoDB / DataSource / Notification Managers
2. 启动 RPC 服务器（默认端口 50053）
3. 注册 10 个内置策略执行器到 self._strategies
4. 从 MongoDB strategy_subscriptions 集合加载活跃订阅（is_active=True）
5. 输出启动日志：poll_interval, strategies_count, subscriptions_count
```

### 1.3 主循环 (`run`)

```
while _running:
    1. 生成 trace_id（uuid4 hex）
    2. 检查交易时间（silent_outside_trading 开启时非交易时间跳过）
    3. 执行 poll_cycle，外层用 asyncio.wait_for(timeout=poll_timeout) 包裹
    4. 捕获 TimeoutError → 记录超时日志，跳过当前轮次
    5. 捕获 Exception → 记录错误日志，继续下一轮
    6. 清理 trace_id
    7. sleep(poll_interval)
```

**关键设计：单轮错误不会中断主循环**，超时和异常均被独立捕获。

### 1.4 单次轮询循环 (`_poll_cycle`)

```
1. 每日获取涨跌停价格 (_fetch_limit_prices_if_needed)
   └── 每日 9:15 后获取 stk_limit，过滤非上市股票和 ST 股票
   
2. 获取三大指数实时行情 (get_realtime_index_quotes)
   └── SH(000001.SH) / SZ(399001.SZ) / CYB(399006.SZ)

3. 构建订阅运行时上下文 (_build_subscription_runtime_contexts)
   ├── 合并各订阅的 watch_list 中的代码
   ├── 关联持仓股票（position_group_id → trade_review_positions）
   └── 关联流转源股池的股票（transition_rules.source_pool_ids → stock_pools）

4. 获取全部监听股票代码 (_get_all_watch_codes)
   ├── 包含 ALL_MARKET 的订阅 → 使用全部 limit_stocks + 个股列表
   └── 纯个股订阅 → 合并所有订阅的 watch_codes

5. 批量拉取实时行情
   ├── total_codes > 600: 按 batch_size=400 分批拉取，合并结果
   └── total_codes <= 600: 单次拉取（内部 batch_size=50）

6. 构建市场快照 (_build_snapshot)
   ├── 仅保留 KEEP_FIELDS: ts_code, name, price, pct_chg, open, high,
   │   low, close, volume, amount, pre_close, change
   ├── 统计 up_count / down_count
   └── 附加 limit_up_count / limit_down_count

7. 计算快照增量 (_apply_snapshot_delta)
   ├── 对比 DELTA_COMPARE_FIELDS: price, pct_chg, open, high, low,
   │   close, volume, amount, pre_close, change
   ├── 无上一帧时: changed_quotes = 全量 quotes
   ├── 新出现的代码 → 记入 changed_quotes
   ├── 字段值发生变化的 → 记入 changed_quotes
   └── 上一帧存在但当前帧消失的 → 记入 removed_ts_codes

8. 存储实时市场数据到 Redis (_store_realtime_market_data)
   ├── 存储分层快照（_build_layered_market_snapshot_payload）
   ├── 存储增量事件（_build_market_delta_event_payload）
   └── 发布 Redis Pub/Sub 增量流

9. 统计封板情况 (_log_limit_stats)

10. 执行策略评估 (_evaluate_strategies)
    ├── 遍历活跃订阅，独立调用对应策略的 evaluate()
    ├── 每个策略使用复制的订阅对象（含运行时参数注入）
    ├── 评估后同步 params 回原始订阅（排除 _runtime_ 开头的临时字段）
    └── 单个策略异常不影响其他策略（独立 try/except）

11. 处理预警 (_process_alert)
    ├── 插入 listener_trigger_events 到 MongoDB
    ├── 发送企业微信通知（notification_manager.send_alert）
    ├── 执行流转规则（_execute_transition_rules）
    └── 更新 listener_trigger_events 状态（notification_sent, transition_results）
```

---

## 2. 市场快照与增量 (`MarketSnapshot`)

### 2.1 快照保留字段 (`_SNAPSHOT_KEEP_FIELDS`)

仅保留策略评估所需字段，舍弃无用字段以减少内存：

```
ts_code, name, price, pct_chg, open, high, low,
close, volume, amount, pre_close, change
```

### 2.2 增量对比 (`_apply_snapshot_delta`)

对比字段（`_DELTA_COMPARE_FIELDS`）：

```
price, pct_chg, open, high, low, close, volume,
amount, pre_close, change
```

**增量逻辑：**
- **首帧**（无 previous_snapshot）：`changed_quotes` = 全量 `quotes`
- **后续帧**：仅当 DELTA_COMPARE_FIELDS 中任一字段值发生变化时，该股票计入 `changed_quotes`
- **消失的股票**：上一帧存在但当前帧不存在的 ts_code 记入 `removed_ts_codes`

### 2.3 Redis 分层存储

每次轮询向 Redis 写入三层数据：

| 层 | Key 前缀 | 内容 |
|----|----------|------|
| 分层快照 | `realtime_market_layered_snapshot` | 摘要 + 三大指数 + 前 50 变化代码 |
| 增量事件 | `realtime_market_delta` | 完整变化代码列表 + 前 100 行情详情 |
| 事件流 | `realtime_market_delta_stream` | Pub/Sub 发布 + 追加到列表 |

---

## 3. 涨跌停价格管理

### 3.1 获取时机 (`_fetch_limit_prices_if_needed`)

- **触发条件**：当前时间 >= `limit_fetch_time`（默认 09:15）且当日尚未获取
- **数据来源**：`data_source_manager.get_stk_limit(trade_date=today)`
- **过滤规则**：
  1. 仅保留 `stock_basic` 中 `list_status="L"` 的上市股票
  2. 排除 ST 股票（名称匹配 `ST`、`*ST`、`S*ST`、`SST` 前缀）
- **存储**：`self._limit_stocks[ts_code] = item`
- **缓存**：同一交易日不重复获取

### 3.2 ST 股票过滤

ST 名称模式匹配（大小写不敏感）：

```
"ST", "*ST", "S*ST", "SST"
```

---

## 4. 策略基类 (`BaseStrategy`)

### 4.1 抽象方法

```python
@abstractmethod
async def evaluate(
    self,
    subscription: StrategySubscription,
    snapshot: MarketSnapshot,
    previous_snapshot: Optional[MarketSnapshot] = None,
) -> List[StrategyAlert]:
```

### 4.2 核心能力

| 方法 | 功能 |
|------|------|
| `_get_watch_stocks()` | 从快照中筛选 watch_list 内/全市场的股票，支持 ST 过滤和单股 enabled 控制 |
| `_create_alert()` | 创建 StrategyAlert 对象 |
| `_get_alert_frequency()` | 读取预警频率: `daily_once` / `once_then_disable` / `unlimited` |
| `_should_skip_by_alert_frequency()` | 频率控制判断 |
| `_record_alert_trigger()` | 持久化触发记录（日期、次数、频率禁用） |
| `_is_st_stock()` | ST 股票名称匹配 |
| `_get_numeric_param()` | 数值参数读取（兼容历史字段别名） |
| `_normalize_percent_value()` | 百分比归一化：>1 时 `/100` |
| `_load_threshold_states()` | 加载当日阈值状态（跨轮次保持） |
| `_set_threshold_state()` | 设置阈值状态，返回是否首次触发 |
| `_persist_stock_runtime_fields()` | 持久化运行时字段到 MongoDB |

### 4.3 增量评估优化

```python
@property
def use_incremental_snapshot(self) -> bool:
    return True  # 默认优先只评估本轮变化过的股票
```

当 `use_incremental_snapshot=True` 且 `snapshot.changed_quotes` 存在时，`_get_watch_stocks()` 从 `changed_quotes` 而非全量 `quotes` 中筛选，大幅减少评估量。

### 4.4 预警频率控制 (Alert Frequency)

| 模式 | 常量 | 行为 |
|------|------|------|
| 每日一次 | `daily_once` | 同股票同日内已有记录则跳过 |
| 一次即禁 | `once_then_disable` | 触发后将 stock_configs[ts_code].enabled 设为 False |
| 无限制 | `unlimited` | 每次都触发 |

频率控制在 `_should_skip_by_alert_frequency()` 中实现，在策略评估前调用。

---

## 5. 十大内置策略

### 5.1 MarketIndexAlertStrategy（指数指标预警）

**类型标识**: `market_index_alert`

**监控维度**（可独立开关）:

| 维 度 | 参数键 | 默认阈值 | 说明 |
|--------|--------|----------|------|
| 指数涨幅 | `index_rise_enabled` / `index_rise_threshold` | 1.5% | SH/SZ/CYB 可选 |
| 指数跌幅 | `index_fall_enabled` / `index_fall_threshold` | 1.5% | |
| 上涨家数 | `up_count_enabled` / `up_count_threshold` | 3000 | 默认关闭 |
| 下跌家数 | `down_count_enabled` / `down_count_threshold` | 3000 | 默认关闭 |
| 涨停家数 | `limit_up_enabled` / `limit_up_threshold` | 80 | 默认关闭 |
| 跌停家数 | `limit_down_enabled` / `limit_down_threshold` | 20 | 默认关闭 |
| 北向净流入 | `north_money_in_enabled` / `north_money_in_threshold` | 20 亿 | 默认关闭 |
| 北向净流出 | `north_money_out_enabled` / `north_money_out_threshold` | 20 亿 | 默认关闭 |

**触发逻辑**：使用 `_load_threshold_states` / `_set_threshold_state` 机制，任一条件首次越线时合并触发一条预警。同日内同一条件不会重复触发。

**数据来源**：Redis 实时市场数据 + MongoDB daily_stats（北向资金）。

### 5.2 LimitOpenStrategy（涨跌停打开）

**类型标识**: `limit_open`

**策略逻辑**：通过快照增量对比检测封板开板：

```
前一帧（previous_snapshot）: price >= up_limit   (封板中)
当前帧（snapshot）:         price <  up_limit   (打开)
```

| 参数 | 可选值 | 说明 |
|------|--------|------|
| `limit_type` | `"up"` / `"down"` / `"both"` | 监控方向 |

**前提条件**：
- 必须有 `previous_snapshot`（首轮跳过）
- `snapshot.limit_stocks` 必须非空
- 该股票在 `limit_stocks` 中有有效的涨跌停价格

**额外信息**：开板方向、涨跌停价格、前一价格、当前涨跌幅。

### 5.3 PriceChangeStrategy（涨跌幅阈值）

**类型标识**: `price_change`

**策略逻辑**：当单只股票涨跌幅超过设定阈值时触发。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `threshold` | 3.0 | 涨跌幅阈值（百分比，如 3.0 = 3%） |
| `direction` | `"both"` | `"up"` / `"down"` / `"both"` |

**特性**：使用阈值状态机，向上穿越和向下穿越独立记录，同日内不重复触发。

### 5.4 IntradayPriceMoveStrategy（盘中异动）

**类型标识**: `intraday_price_move`

**策略逻辑**：追踪最近 N 分钟窗口内的价格变动幅度，超过阈值时触发。

**每只股票维护一个 deque（时间窗口内的价格快照）**，每次轮询追加当前价格和时间戳，定期清理过期数据。

### 5.5 MA5BuyStrategy（均线低吸）

**类型标识**: `ma5_buy`

**策略逻辑**：股价从上方回落到均线附近并企稳时触发。

**状态机**:
```
NORMAL (0) ──[昨天在MA上方 & 当前回落到MA附近]──> TOUCHED (1)
TOUCHED (1) ──[连续N周期在MA上方]──> STABILIZED (2) → 触发预警
TOUCHED (1) ──[跌破MA容忍范围]──> NORMAL (0)   (重置)
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `ma_period` | 5 | 均线周期（可单股覆盖） |
| `touch_range` | 0.02 (2%) | 触及均线的容忍范围 |
| `stable_periods` | 2 | 企稳所需连续周期数 |

**盘中均线估算公式**：`MA(N) = (前 N-1 天收盘价 + 盘中估算收盘价) / N`，其中盘中估算收盘价 = 开盘价 x 1.05。

**每只股票维护**：独立 `StockTracker` 状态追踪器 + 历史数据缓存 (250 条日线)。

**缓存策略**：按交易日缓存，新交易自动重置所有追踪器。

### 5.6 SupportResistanceStrategy（撑压线）

**类型标识**: `support_resistance`

**策略逻辑**：根据自定义支撑线和压力线点位，在最新价格接近或突破线位时触发预警。

**特点**：
- 每只股票单独配置点位
- 线的横轴使用股票实际交易日序列（不含节假日和停牌日）
- 支撑点未填价格时默认取当日最低价
- 压力点未填价格时默认取当日最高价

### 5.7 FixedStopLossStrategy（固定止损）

**类型标识**: `fixed_stop_loss`

**策略逻辑**：从参考价开始，若价格下跌到固定止损比例则触发。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `reference_price` | - | 参考价（基准价） |
| `stop_loss_pct` | 8.0% | 止损比例 |

**计算公式**: `trigger_price = reference_price * (1 - stop_loss_pct)`

**触发条件**: `current_price <= trigger_price OR current_low <= trigger_price`

**状态持久化**：参考价存储在 `stock_configs[ts_code].reference_price`，节点重启后继续有效。

### 5.8 TrailingStopLossStrategy（移动止损）

**类型标识**: `trailing_stop_loss`

**策略逻辑**：追踪持仓以来最高价，从最高价回撤指定比例时触发。

**每只股票维护 `highest_price`**（存储在 `stock_configs` 中），每轮更新。从最高价下跌到止损比例时触发。

### 5.9 PositionPnlStrategy（持仓总盈亏）

**类型标识**: `position_pnl`

**策略逻辑**：监控持仓组合的整体盈亏，当总盈亏（盈亏金额或百分比）超过阈值时触发。

**数据来源**: `trade_review_positions` 集合，通过 `position_group_id` 关联。

**计算方式**: 持仓均价 vs 当前市价的盈亏总和。

### 5.10 PositionIntradayPnlStrategy（盘中持仓盈亏变动）

**类型标识**: `position_intraday_pnl`

**策略逻辑**：监控盘中持仓盈亏相对昨日收盘的变化幅度。

**触发条件**：盘中的实时盈亏变化百分比超过阈值。

---

## 6. 预警处理流程 (`_process_alert`)

```
alert 触发
│
├── 1. 插入 MongoDB listener_trigger_events
│       └── 包含: event_id, alert_id, strategy 信息,
│           ts_code, trigger_price, trigger_reason,
│           extra_data, notification_sent=False
│
├── 2. 发送通知（notification_manager.send_alert）
│       └── 通过企业微信推送给 user_id
│
├── 3. 执行流转规则 (_execute_transition_rules)
│       └── 遍历 subscription.params.transition_rules
│
└── 4. 更新 listener_trigger_events
        └── notification_sent, transition_results
```

---

## 7. 流转规则 (Transition Rules)

### 7.1 规则配置

每条策略订阅可配置 `transition_rules` 数组，每项包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| `rule_id` | str | 规则 ID |
| `enabled` | bool | 是否启用 |
| `mode` | `"move"` / `"copy"` | 流转模式 |
| `source_pool_ids` | list | 来源股池（仅 move 模式生效） |
| `target_pool_id` | str | 目标股池 |
| `cooldown_days` | int | 冷却天数（默认 1） |

### 7.2 Move vs Copy

| 模式 | 行为 |
|------|------|
| `move` | 从 source_pool_ids 中移除，添加到 target_pool_id |
| `copy` | 仅添加到 target_pool_id，不修改来源股池 |

### 7.3 冷却机制 (`_is_transition_in_cooldown`)

查询 `pool_transition_logs` 中同一 `rule_id + ts_code` 的上次成功流转记录。若距上次成功流转不足 `cooldown_days` 天，则跳过本轮流转（status="skipped"）。

### 7.4 流转日志

每次流转操作记录到 `pool_transition_logs` 集合，包含：
- 来源/目标股池
- 触发原因和价格
- 冷却天数
- 流转状态（moved/copied/updated/skipped/failed）

---

## 8. RPC 接口

### 8.1 `refresh_strategies`

**功能**：接收 WebNode 的策略变更通知，重新加载订阅配置。

**参数**：
- `strategy_type` (可选): 指定刷新特定策略类型

**返回**：
```json
{
    "status": "ok",
    "subscriptions_count": 12,
    "message": "Refreshed 12 subscriptions"
}
```

---

## 9. 健康检查 (`health_check`)

```json
{
    "subscriptions": 12,
    "strategies": ["market_index_alert", "limit_open", ...],
    "limit_stocks_loaded": 4500,
    "last_limit_fetch_date": "20240621",
    "has_current_snapshot": true
}
```

---

## 10. 关键设计要点

1. **单轮超时保护**：`asyncio.wait_for(poll_cycle, timeout=180s)`，超时不阻塞主循环
2. **错误隔离**：每个策略评估独立 try/except，单策略异常不影响其他策略
3. **增量评估优化**：`use_incremental_snapshot` + `changed_quotes` 减少大部分策略的无效遍历
4. **参数同步**：策略运行时注入 `_runtime_*` 参数，评估后同步 params 回原始订阅
5. **状态持久化**：阈值状态、止损参考价、最高价等运行时数据持久化到 MongoDB `strategy_subscriptions.params`
6. **分批拉取**：全市场 >600 只股票时自动分批拉取（每批 400 只），降低内存和 API 压力
7. **非交易时间静默**：通过 `silent_outside_trading` 控制，节省 API 调用量
8. **全市场模式**：watch_list 包含 `"ALL"` 时自动扩展为全部 limit_stocks + 所有订阅的个股
