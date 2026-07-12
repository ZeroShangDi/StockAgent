# Strategy V2 功能说明

## 概述

Strategy V2 是 StockAgent 的第二代策略框架，旨在以统一的"策略纯函数 + 任务调度执行"范式替代旧版 `strategy_subscriptions` 体系。核心设计原则：

- **策略是纯函数**：策略只输出 `1`（正向）/ `0`（中性）/ `-1`（负向）信号和原因，不直接发通知、不直接写股池、不直接生成交割单。
- **任务是配置载体**：用户通过任务（`scene_tasks`）绑定策略、目标范围、调度方式和触发动作。
- **动作由执行器处理**：通知、股池流转、临时清单、模拟成交等动作由统一的动作审计引擎处理。
- **与旧系统并行**：V2 使用独立的 `strategy_v2_*` 集合，不修改旧表；旧 `strategy_subscriptions` 继续服务旧版页面。

## 文件结构

### 后端 API
```
AgentServer/nodes/web/api/strategy_v2.py   # 1935 行: 任务 CRUD、运行生命周期、调度器、动作审计
```

### 策略引擎
```
AgentServer/src/strategy_v2/
├── __init__.py           # 模块导出
├── evaluator.py          # 策略评估器：3 个内置策略 + 评估调度器
└── rules.py              # 任务创建规则：14 个内置策略定义 + 校验引擎
```

### 数据模型
```
AgentServer/common/models/strategy_v2.py   # Pydantic 模型：请求/响应/枚举类型
```

### 参考文档
```
docs/STRATEGY_V2_DATA_MODEL.md    # 核心数据模型草图
docs/STRATEGY_V2_PLAN.md          # 开发排期与任务拆解
docs/STRATEGY_V2_TASK_RULES.md    # 任务创建规则
```

---

## 1. 四类场景类型

| 场景 | code | 说明 | 支持的目标范围 |
|------|------|------|----------------|
| 选股 | `scan` | 筛选符合策略的股票，进入候选链路 | 自选股、持仓股、股池分组、全市场排除ST |
| 监听 | `listen` | 按频率持续监听目标，触发通知/流转 | 自选股、持仓股、股池分组、全市场排除ST、自定义股票列表、指数 |
| 回测 | `backtest` | 对历史区间执行策略，输出运行结果 | 全市场排除ST |
| 模拟 | `sim_trade` | 基于实盘/准实盘数据更新模拟账户 | 全市场排除ST |

## 2. 目标范围

| 范围 | code | 说明 |
|------|------|------|
| 自选股 | `watchlist` | 当前用户自选股列表 |
| 持仓股/交易账户 | `trade_account` | 从交割单分组推导当前持仓 |
| 股池分组 | `stock_pool` | 选择现有股池作为标的 |
| 全市场排除ST | `all_market` | 全A市场，默认排除ST（max 6000 只） |
| 自定义股票列表 | `custom_stock_list` | 任务内维护的股票列表（仅监听场景） |
| 指数 | `index` | 上证/深证/创业板指数（仅监听场景） |

## 3. 调度方式

| 调度 | code | 说明 |
|------|------|------|
| 一次性运行 | `once` | 创建后执行一次（选股/回测） |
| 定时运行 | `scheduled` | 按时间槽或轮询频率自动执行 |
| 手动运行 | `manual` | 仅保存任务，用户手动触发 |

### 3.1 定时运行时间槽（7 个 Slots）

| 名称 | slot | 时间 |
|------|------|------|
| 盘前 | `pre_market_0900` | 09:00 |
| 集合竞价 | `call_auction_0925` | 09:25 |
| 上午变盘 | `morning_turn_1000` | 10:00 |
| 中午收盘 | `midday_close_1130` | 11:30 |
| 下午变盘 | `afternoon_turn_1400` | 14:00 |
| 盘后 | `post_market_1505` | 15:05 |
| 每周六 | `weekly_sat_1200` | 周六 12:00 |

每个槽位有 10 分钟宽限期（`SCHEDULE_SLOT_GRACE_SECONDS = 600s`）。

### 3.2 轮询间隔（3 个 Intervals）

| 名称 | slot | 间隔 |
|------|------|------|
| 1 分钟 | `intraday_1m` | 60s |
| 5 分钟 | `intraday_5m` | 300s |
| 30 分钟 | `intraday_30m` | 1800s |

仅交易时段（9:15-11:30, 13:00-15:05）内生效。

---

## 4. 五大动作类型

| 动作 | code | 可用条件 | 处理逻辑 |
|------|------|----------|----------|
| 通知 | `notify` | 仅监听场景 | 通过 `notification_manager.send_alert()` 发送，支持频率控制（daily_once / once_then_disable / unlimited） |
| 加入股池 | `add_to_pool` | 目标范围为股票范围 | `_upsert_stock_into_pool()`，支持 skip/refresh_reason 重复策略 |
| 股池流转 | `pool_transition` | 目标范围为股池分组 | 支持 copy（复制到目标）/ move（复制+删除源）/ delete（仅删除源）三种模式 |
| 临时清单 | `temp_list` | 仅一次性运行 | 自动创建候选池股池，默认 TTL 1 天 |
| 模拟成交 | `paper_trade` | 仅回测/模拟场景 | 预留执行器接口，当前标记为 planned |

每个动作可配置 `trigger_signals`（触发条件：`[1]` / `[-1]` / `[1, -1]` 等），只有匹配的信号才触发该动作。

---

## 5. 14 个内置策略定义

策略定义在 `src/strategy_v2/rules.py` 的 `BUILTIN_STRATEGY_DEFINITIONS` 中，其中 3 个已有完整评估器实现：

### 5.1 已实现的策略（含评估器代码）

| 策略 | strategy_key | 说明 | 支持场景 |
|------|-------------|------|----------|
| 一句话选股 | `one_line_stock_picker` | 复用原一句话选股服务，逐股匹配候选代码 | scan, listen |
| 双响炮 | `double_cannon` | 近一个月内两根涨幅超阈值的大阳线形态 | scan, listen, backtest, sim_trade |
| 海龟通道突破 | `turtle_trading` | 唐奇安通道突破（入场/退出/ATR/成交量确认） | scan, listen, backtest, sim_trade |

### 5.2 已定义的策略（待实现评估器）

| 策略 | strategy_key | 说明 | 支持场景 |
|------|-------------|------|----------|
| 5日线低吸 | `ma5_buy` | 股价回落到均线附近后重新企稳 | scan, listen, backtest, sim_trade |
| 涨跌幅阈值 | `price_change` | 盘中达到指定涨跌幅阈值触发 | listen, scan, backtest |
| 指数指标预警 | `market_index_alert` | 围绕指数涨跌幅、涨跌家数、北向资金 | listen |
| 涨跌停打开 | `limit_open` | 涨停/跌停封板后打开的异动检测 | listen |
| 分钟异动 | `intraday_price_move` | 最近N分钟内涨跌幅超阈值 | listen |
| 撑压线 | `support_resistance` | 支撑/压力线接近、跌破、突破监听 | listen |
| 固定止损 | `fixed_stop_loss` | 基于参考价和止损比例的持仓风控 | listen, sim_trade, backtest |
| 移动止损 | `trailing_stop_loss` | 跟踪最高价，回撤达阈值触发 | listen, sim_trade, backtest |
| 持仓盈亏阈值 | `position_pnl` | 按交割单账户持仓总浮盈/浮亏触发 | listen |
| 盘中持仓盈亏变化 | `position_intraday_pnl` | 昨收到当前价的盘中收益波动 | listen |
| 市场涨跌比脉冲 | `breadth_pulse` | 观察涨跌家数比和涨停家数 | listen, scan |

---

## 6. 策略评估器架构 (`evaluator.py`)

### 6.1 `StrategyV2EvaluationContext`
单股评估上下文，包含 `user_id`、`code`、`ts_code`、`stock`（股票基础信息）、`now`（当前时间）。

### 6.2 `StrategyV2EvaluationResult`
统一输出结构：`signal` (int: 1/0/-1)、`reason` (str)、`meta` (dict)。

### 6.3 已实现的评估器类

**`OneLineStockPickerStrategy`:**
- 缓存机制：`_cache: dict[(user_id, query, date), _CandidateCacheEntry]`
- 缓存 TTL：可配置 `cache_ttl_days`（默认 1 天，最大 `MAX_ONE_LINE_PICKER_CACHE_TTL_DAYS=2`）
- 最大缓存条目：`MAX_ONE_LINE_PICKER_CACHE_ENTRIES=64`
- 流程：调用 `stock_picker_service.query(query_text)` → 提取候选 code/ts_code 集合 → 逐股匹配

**`DoubleCannonStrategy`:**
- 从 MongoDB `stock_daily` 加载 K 线（最多 `MAX_STRATEGY_KLINE_ROWS=260` 条）
- 参数：`lookback_days`(默认22)、`min_bull_pct`(默认5%)、`max_second_age_days`(默认5)
- 可选过滤：第二炮放量、均线多头排列、调整缩量
- 输出：signal=1（形态成立）、0（未成立）、-1（结构破坏）

**`TurtleTradingStrategy`:**
- 从 MongoDB `stock_daily` 加载 K 线
- 参数：`entry_window`(默认20)、`exit_window`(默认10)、`atr_period`(默认20)
- 可选过滤：收盘价确认、ATR 波动率范围、成交量确认
- 输出：signal=1（突破入场）、0（震荡）、-1（跌破退出）

### 6.4 `evaluate_strategy_v2()` 调度函数
```python
async def evaluate_strategy_v2(
    strategy_key: str,
    context: StrategyV2EvaluationContext,
    params: dict | None = None,
) -> StrategyV2EvaluationResult
```
从 `STRATEGY_V2_EVALUATORS` 字典查找评估器并调用，未找到则抛出 `KeyError`。

---

## 7. 任务创建规则与校验 (`rules.py`)

### 7.1 规则矩阵

`SCENE_TARGETS`: 每个场景允许的目标范围集合
`SCENE_SCHEDULES`: 每个场景允许的调度方式集合
`BUILTIN_STRATEGY_SCENES`: 每个策略支持的场景类型

### 7.2 `validate_task_config(body) -> list[str]`

校验项：
1. 策略是否支持所选场景
2. 必填参数是否为空
3. 目标范围是否被场景支持
4. 调度方式是否被场景支持
5. 回测/模拟是否填写交割单账户
6. 自定义股票列表不能为空
7. 每个动作至少需要一个 trigger_signal
8. 通知动作仅支持监听场景
9. 加入股池仅支持股票范围
10. 股池流转仅支持股池分组范围
11. 临时清单仅支持一次性运行
12. 模拟成交仅支持回测/模拟场景

### 7.3 `build_rule_dictionary() -> StrategyV2RuleDictionary`

返回前端可用的完整字典，包含 scenes、target_scopes、schedules、actions 四类枚举值及其互斥关系。

---

## 8. API 端点概览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/strategy-v2/rules` | 获取创建规则字典 |
| GET | `/strategy-v2/strategies` | 获取内置策略列表 |
| GET | `/strategy-v2/tasks` | 列出当前用户任务 |
| POST | `/strategy-v2/tasks` | 创建任务 |
| GET | `/strategy-v2/tasks/{task_id}` | 获取任务详情 |
| DELETE | `/strategy-v2/tasks/{task_id}` | 删除任务及关联数据 |
| GET | `/strategy-v2/tasks/{task_id}/runs` | 列出任务运行记录 |
| POST | `/strategy-v2/tasks/{task_id}/runs` | 手动触发运行 |
| GET | `/strategy-v2/runs/{run_id}` | 获取运行详情 |
| GET | `/strategy-v2/runs/{run_id}/items` | 获取运行明细（最多6000条） |
| GET | `/strategy-v2/runs/{run_id}/logs` | 获取运行日志 |
| GET | `/strategy-v2/runs/{run_id}/action-audits` | 获取动作审计记录 |
| POST | `/strategy-v2/runs/{run_id}/cancel` | 取消运行 |
| POST | `/strategy-v2/runs/{run_id}/retry` | 重试运行 |
| POST | `/strategy-v2/tasks/{task_id}/stocks` | 向监听任务添加股票 |
| PUT | `/strategy-v2/tasks/{task_id}/stocks/{ts_code}/config` | 更新股票级配置 |
| DELETE | `/strategy-v2/tasks/{task_id}/stocks/{ts_code}` | 从任务移除股票 |

---

## 9. 运行生命周期

```
create_task()                     # 创建任务（draft/active）
  │
  ▼
_start_strategy_v2_run()          # 启动运行（manual/schedule/retry）
  │
  ├── 获取 active_run_id 锁       # 原子 CAS 操作，防止并发
  ├── 创建 run_doc (running)
  ├── 创建 asyncio.create_task()  # 异步执行
  │
  ▼
_execute_strategy_v2_run_inner()  # 核心执行（受 Semaphore 控制）
  │
  ├── _resolve_task_targets()     # 解析目标范围 → List[stock]
  │     ├── custom_stock_list → 查询 stock_basic
  │     ├── stock_pool → 查询股池成员 → 查询 stock_basic
  │     ├── watchlist → 查询用户自选股 → 查询 stock_basic
  │     └── all_market → 查询 stock_basic (排除ST)
  │
  ├── 逐股评估循环:
  │     for stock in targets:
  │         result = await evaluate_strategy_v2(strategy_key, context, params)
  │         每 25 只检查一次取消信号
  │         每 25 只更新一次进度
  │
  ├── _create_temp_stock_pool()   # 生成临时清单（仅正向信号）
  │
  ├── _build_action_audits_for_item()  # 逐股审计动作
  │     ├── notify → send_alert + 频率控制 + 状态记录
  │     ├── add_to_pool → _upsert_stock_into_pool
  │     ├── pool_transition → 复制/移动/删除
  │     ├── temp_list → 标记已执行（pool 已在前面创建）
  │     └── paper_trade → 标记 planned
  │
  ├── 批量写入 run_items + action_audits
  │     ├── insert_many(RUN_ITEM_COLLECTION)
  │     └── insert_many(ACTION_AUDIT_COLLECTION)
  │
  └── _release_task_run_lock()    # 释放 active_run_id 锁
       └── 更新 task.last_run_status / last_signal_count
```

### 9.1 并发控制

- `_RUN_SEMAPHORE = asyncio.Semaphore(STRATEGY_V2_MAX_CONCURRENT_RUNS)`（默认 1，可通过环境变量配置）
- `active_run_id` 锁：通过 MongoDB CAS 原子操作确保同一任务同时只有一个运行实例

### 9.2 取消机制

- 用户调用 `POST /runs/{run_id}/cancel` → MongoDB 更新 `run_status=cancelled`
- `_is_run_cancelled()` 在每只股票评估后检查（每 25 只），抛出 `StrategyV2RunCancelled` 异常
- `_mark_stale_running_runs()` 在查询时自动标记超时运行（30 分钟无更新 → failed）

### 9.3 调度器

`_strategy_v2_scheduler_loop()`: 每 30 秒扫描一次 `status=active, schedule.mode=scheduled` 的任务，解析时间槽/轮询间隔，通过 Firebase key 去重，触发 `_start_strategy_v2_run(trigger_source="schedule")`。

---

## 10. 通知频率控制

| 频率模式 | code | 行为 |
|----------|------|------|
| 每日一次 | `daily_once` | 同一股票每天最多通知一次 |
| 通知后关闭 | `once_then_disable` | 发送一次后将个股配置 `enabled=False` |
| 不限次数 | `unlimited` | 每次触发都通知 |

通知状态记录在 `task.params.stock_configs[ts_code]` 中（`last_notified_date`、`notify_count`、`enabled`）。

---

## 11. 配置依赖

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `STRATEGY_V2_MAX_CONCURRENT_RUNS` | 最大并发运行数 | 1 |
| `RUN_STALE_AFTER_SECONDS` | 运行超时阈值 | 1800 (30分钟) |
| `SCHEDULER_POLL_SECONDS` | 调度器轮询间隔 | 30 |
| `SCHEDULE_SLOT_GRACE_SECONDS` | 时间槽宽限期 | 600 (10分钟) |
| `MAX_TARGET_STOCKS` | 最大目标股票数 | 6000 |
| `MAX_TASK_LIST_ITEMS` | 任务列表最大返回数 | 500 |
| `MAX_RUN_RESULT_ITEMS` | 运行结果最大返回数 | 6000 |
| `STRATEGY_V2_ONE_LINE_CACHE_MAX_ENTRIES` | 一句话选股缓存最大条目 | 64 |
| `STRATEGY_V2_ONE_LINE_CACHE_MAX_TTL_DAYS` | 一句话选股缓存最大天数 | 2 |
| `MAX_STRATEGY_KLINE_ROWS` | 策略最大 K 线加载行数 | 260 |

## 12. MongoDB 集合

| 集合 | 说明 |
|------|------|
| `strategy_v2_scene_tasks` | 任务主表 |
| `strategy_v2_task_runs` | 运行记录 |
| `strategy_v2_task_run_items` | 运行明细（每只股票结果） |
| `strategy_v2_task_run_logs` | 运行日志 |
| `strategy_v2_action_audits` | 动作审计记录 |
