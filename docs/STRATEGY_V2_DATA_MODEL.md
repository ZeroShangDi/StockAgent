# Strategy V2 核心数据模型草图

## 1. 文档目的

本文档定义 `Strategy V2` 的核心数据对象与边界。

原则：

- 新建“策略、任务、状态、运行记录”核心对象
- 复用现有“股池、交割单、通知、多用户”等外围能力
- 保持与旧系统并行，不直接改旧表为新中心

## 2. 模型总览

V2 核心建议拆成以下对象：

- `strategy_definitions`
- `scene_tasks`
- `strategy_state_store`
- `task_runs`
- `task_run_items`
- `signal_events`

复用现有集合：

- `stock_pools`
- `listener_trigger_events`
- `pool_transition_logs`
- `trade_review_groups`
- `trade_review_records`

## 3. 核心新模型

### 3.1 strategy_definitions

用途：

- 定义内置策略目录
- 不是用户实例
- 不承担运行状态

建议字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `strategy_key` | string | 策略唯一标识 |
| `name` | string | 策略名称 |
| `description` | string | 策略说明 |
| `impl_type` | string | 当前固定为 `builtin_code` |
| `impl_ref` | string | 策略实现引用，如模块路径 |
| `supported_scenes` | string[] | 支持的场景类型 |
| `param_schema` | object[] | 参数定义 |
| `supports_state` | bool | 是否支持跨日状态 |
| `result_schema_version` | string | 输出结构版本 |
| `status` | string | `active` / `deprecated` |
| `version` | int | 策略版本 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |

说明：

- 后续如果接入 AI 策略或 Skill 策略，可以扩展 `impl_type`
- 本期只做内置代码策略

### 3.2 scene_tasks

用途：

- 作为 V2 业务主对象
- 负责把“策略”绑定到“运行场景”

建议字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_id` | string | 任务唯一标识 |
| `user_id` | string | 用户 ID |
| `name` | string | 任务名称 |
| `scene_type` | string | `scan` / `listen` / `backtest` / `sim_trade` |
| `strategy_key` | string | 绑定策略 |
| `target_scope` | object | 目标范围定义 |
| `params` | object | 任务层参数 |
| `actions` | object[] | 触发动作列表 |
| `schedule` | object | 调度配置 |
| `status` | string | `draft` / `active` / `paused` / `archived` |
| `runtime_options` | object | 运行时选项 |
| `last_run_at` | datetime | 最近运行时间 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |

说明：

- 策略是否启停，不再建模
- 启停的是任务

#### target_scope 草图

```json
{
  "scope_type": "all_market",
  "pool_ids": [],
  "group_ids": [],
  "ts_codes": [],
  "index_codes": [],
  "market_codes": []
}
```

常见 `scope_type`：

- `all_market`
- `stock_list`
- `stock_pool`
- `position_group`
- `index`
- `market`

#### actions 草图

```json
[
  {
    "action_type": "notify",
    "enabled": true,
    "params": {
      "channel_id": "xxx"
    }
  },
  {
    "action_type": "pool_transition",
    "enabled": true,
    "params": {
      "target_pool_id": "xxx",
      "mode": "move"
    }
  }
]
```

### 3.3 strategy_state_store

用途：

- 存放策略跨日状态
- 支撑“并非所有策略都需要状态，但系统必须支持”

建议字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `state_id` | string | 状态唯一标识 |
| `user_id` | string | 用户 ID |
| `task_id` | string | 所属任务 |
| `strategy_key` | string | 所属策略 |
| `entity_type` | string | `stock` / `index` / `market` / `group` |
| `entity_key` | string | 例如 `000001.SZ` |
| `state_data` | object | 状态内容 |
| `version` | int | 状态结构版本 |
| `updated_at` | datetime | 更新时间 |

建议唯一键：

- `user_id + task_id + strategy_key + entity_key`

说明：

- 这里天然支持“最低粒度到个股”
- 同一个策略在不同任务里状态隔离

### 3.4 task_runs

用途：

- 记录每次任务运行

建议字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `run_id` | string | 运行唯一标识 |
| `task_id` | string | 所属任务 |
| `user_id` | string | 用户 ID |
| `scene_type` | string | 任务场景 |
| `trigger_source` | string | `manual` / `schedule` / `replay` |
| `run_status` | string | `running` / `success` / `failed` / `partial_success` |
| `context_snapshot` | object | 本次运行环境摘要 |
| `summary` | object | 本次运行摘要 |
| `error_message` | string | 错误信息 |
| `started_at` | datetime | 开始时间 |
| `finished_at` | datetime | 结束时间 |

补充建议字段：

- `trade_review_group_id`
- `linked_pool_ids`
- `result_stats`

### 3.5 task_run_items

用途：

- 记录一次运行中每个目标对象的判断结果

建议字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `item_id` | string | 明细唯一标识 |
| `run_id` | string | 所属运行 |
| `task_id` | string | 所属任务 |
| `user_id` | string | 用户 ID |
| `entity_type` | string | `stock` / `index` / `market` |
| `entity_key` | string | 目标标识 |
| `signal` | int | `1` / `0` / `-1` |
| `score` | number | 信号强度，可选 |
| `reason` | string | 原因摘要 |
| `facts` | object | 关键依据 |
| `tags` | string[] | 标签 |
| `state_patch` | object | 本次需要写回的状态增量 |
| `action_status` | object | 动作执行摘要 |
| `created_at` | datetime | 创建时间 |

### 3.6 signal_events

用途：

- 把“策略输出”与“动作执行”解耦
- 用作统一信号事件层

建议字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `event_id` | string | 事件唯一标识 |
| `run_id` | string | 所属运行 |
| `task_id` | string | 所属任务 |
| `user_id` | string | 用户 ID |
| `strategy_key` | string | 来源策略 |
| `entity_key` | string | 标的 |
| `signal` | int | `1` / `0` / `-1` |
| `score` | number | 强度 |
| `reason` | string | 原因 |
| `payload` | object | 额外上下文 |
| `created_at` | datetime | 创建时间 |

说明：

- 监听触发时，可复用或映射到现有 `listener_trigger_events`
- 不建议把所有动作直接绑死在策略执行内部

## 4. 复用现有模型的方式

### 4.1 stock_pools

继续作为：

- 选股结果承接容器
- 监听来源范围
- 流转目标

V2 不重做主结构，只做轻量增强时优先向后兼容。

### 4.2 listener_trigger_events

当前已存在。

V2 建议：

- 对监听类任务优先继续复用
- 必要时补充 `task_id`、`strategy_key`、`user_id`、`signal` 等字段

### 4.3 pool_transition_logs

继续复用，不重造。

V2 只需保证新监听任务和新动作执行器能写入统一流转日志。

### 4.4 trade_review_groups / trade_review_records

继续复用现有交割单体系。

建议方式：

- `scene_tasks` 中的回测任务和模拟交易任务生成运行结果
- `task_runs` 关联一个 `trade_review_group_id`
- 页面层继续走现有交割单分析页

## 5. 参数优先级规则

建议统一使用以下优先级：

1. 策略默认参数
2. 任务默认参数
3. 任务目标范围参数
4. 单标的覆盖参数
5. 运行时临时参数

说明：

- 单标的覆盖参数是实现“策略-个股”差异化配置的关键
- 股池、监听、回测都走同一套参数解析逻辑

## 6. 策略输出结构草图

虽然对外统一语义是 `1 / 0 / -1`，但内部建议使用统一结构：

```json
{
  "signal": 1,
  "score": 0.82,
  "reason": "回落均线后企稳",
  "facts": {
    "ma_period": 5,
    "distance_to_ma": 0.8
  },
  "tags": ["ma5", "stabilized"],
  "state_patch": {
    "last_triggered_date": "20260522"
  },
  "debug": {}
}
```

这样可以兼容：

- 解释性
- 审计
- 多策略组合
- 后续 AI / Skill 策略输出

## 7. 索引建议

### 7.1 strategy_definitions

- `strategy_key` 唯一

### 7.2 scene_tasks

- `task_id` 唯一
- `user_id + scene_type`
- `user_id + status`
- `updated_at`

### 7.3 strategy_state_store

- `state_id` 唯一
- `user_id + task_id + strategy_key + entity_key` 唯一

### 7.4 task_runs

- `run_id` 唯一
- `task_id + started_at`
- `user_id + started_at`

### 7.5 task_run_items

- `item_id` 唯一
- `run_id + entity_key`
- `task_id + entity_key + created_at`

### 7.6 signal_events

- `event_id` 唯一
- `task_id + created_at`
- `entity_key + created_at`

## 8. 与旧模型的关系

旧模型 `strategy_subscriptions` 当前仍然服务旧监听页和旧 Listener 逻辑。

V2 原则：

- 不直接把 `strategy_subscriptions` 演化成新核心表
- 它在并行期继续存在
- 新系统单独使用 `scene_tasks`
- 等 V2 稳定后，再考虑是否迁移或下线旧链路
