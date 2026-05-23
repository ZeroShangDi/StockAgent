# Strategy V2 旧市场监听策略迁移清单

## 迁移原则

- 旧“市场监听”里的策略统一转为 Strategy V2 内置策略定义。
- 尽量保留旧 `strategy_type` 作为 V2 `strategy_key`，便于后续数据迁移、运行器复用和前端股票级参数配置对齐。
- 旧订阅的 `watch_list` 对应 V2 监听任务的目标范围；手工添加股票优先落到 `custom_stock_list`，股池复盘落到 `stock_pool`。
- 旧订阅的 `params.stock_configs[ts_code]` 对应 V2 任务的 `params.stock_configs[ts_code]`。
- 通知渠道和通知频率不再作为策略参数，归入 V2 任务动作 `notify` 的动作参数。

## 已转为 V2 策略

| 旧策略 | V2 strategy_key | V2 名称 | 场景 | 说明 |
| --- | --- | --- | --- | --- |
| `market_index_alert` | `market_index_alert` | 指数指标预警 | 监听 | 指数、涨跌家数、涨跌停家数、北向资金阈值监听 |
| `ma5_buy` | `ma5_buy` | 5日线低吸 | 选股、监听、回测、模拟 | 已存在，保留为核心低吸策略 |
| `limit_open` | `limit_open` | 涨跌停打开 | 监听 | 依赖实时快照和前一快照，先只开放监听 |
| `price_change` | `price_change` | 涨跌幅阈值 | 监听、选股、回测 | 已存在，保留原 key |
| `intraday_price_move` | `intraday_price_move` | 分钟异动 | 监听 | 依赖分钟窗口，先只开放监听 |
| `support_resistance` | `support_resistance` | 撑压线 | 监听 | 依赖股票级线位配置 |
| `fixed_stop_loss` | `fixed_stop_loss` | 固定止损 | 监听、回测、模拟 | 已存在，股票级参数继续写入 `stock_configs` |
| `trailing_stop_loss` | `trailing_stop_loss` | 移动止损 | 监听、回测、模拟 | 依赖最高价状态记忆 |
| `position_pnl` | `position_pnl` | 持仓盈亏阈值 | 监听 | 依赖交割单账户/持仓上下文 |
| `position_intraday_pnl` | `position_intraday_pnl` | 盘中持仓盈亏变化 | 监听 | 依赖持仓与盘中快照 |

## 下线旧模块前还需要做

- V2 监听运行器读取 `strategy_v2_scene_tasks`，不再读取 `strategy_subscriptions`。
- V2 监听运行器支持 `custom_stock_list`、`stock_pool`、`trade_account`、`index` 等目标范围展开。
- V2 监听运行器执行 `notify` 动作，并复用现有通知机器人发送逻辑。
- V2 运行器读取并写回 `params.stock_configs[ts_code]`，覆盖旧策略中的股票级状态持久化能力。
- 提供一次性迁移脚本，把旧 `strategy_subscriptions` 转成 V2 监听任务。
