export type StrategySignalValue = -1 | 0 | 1

export type StrategySceneType = 'scan' | 'listen' | 'backtest' | 'sim_trade'

export type StrategyTaskStatus = 'draft' | 'active' | 'paused' | 'archived'

export type StrategyRunStatus = 'running' | 'success' | 'failed' | 'partial_success'

export type StrategyActionType =
  | 'notify'
  | 'add_to_pool'
  | 'pool_transition'
  | 'temp_list'
  | 'paper_trade'
  | 'persist_result'

export type StrategyTargetScopeType =
  | 'all_market'
  | 'watchlist'
  | 'stock_list'
  | 'custom_stock_list'
  | 'stock_pool'
  | 'trade_account'
  | 'position_group'
  | 'index'
  | 'event'

export type StrategyScheduleMode =
  | 'once'
  | 'manual'
  | 'scheduled'
  | 'trading_interval'
  | 'daily_time'
  | 'custom'

export interface StrategyParamOption {
  label: string
  value: string
}

export interface StrategyParamSchemaItem {
  key: string
  label: string
  type: 'number' | 'float' | 'boolean' | 'string' | 'select'
  default: number | string | boolean
  required?: boolean
  description: string
  options?: StrategyParamOption[]
}

export interface StrategySampleOutput {
  signal: StrategySignalValue
  title: string
  summary: string
}

export interface StrategyDefinition {
  strategy_key: string
  name: string
  description: string
  impl_type: 'builtin_code'
  supported_scenes: StrategySceneType[]
  supports_state: boolean
  version: number
  tags: string[]
  param_schema: StrategyParamSchemaItem[]
  sample_outputs: StrategySampleOutput[]
}

export interface StrategyTaskAction {
  action_id: string
  action_type: StrategyActionType
  label: string
  enabled: boolean
  summary: string
  params?: Record<string, unknown>
  trigger_signals?: StrategySignalValue[]
}

export interface StrategyTargetScope {
  scope_type: StrategyTargetScopeType
  scope_id?: string
  scope_name?: string
  ts_codes?: string[]
  index_codes?: string[]
  event_keywords?: string[]
  filters?: Record<string, unknown>
  params?: Record<string, unknown>
  summary?: string
}

export interface StrategyScheduleConfig {
  mode: StrategyScheduleMode
  label: string
  timezone?: string
  run_once_at?: string
  interval_seconds?: number
  times?: string[]
  slot?: string
  trading_day_only?: boolean
}

export interface StrategyTaskActionInput {
  action_type: StrategyActionType
  enabled: boolean
  trigger_signals: StrategySignalValue[]
  params: Record<string, string | number | boolean | undefined>
  label?: string
}

export interface StrategySceneTask {
  task_id: string
  user_id: string
  name: string
  scene_type: StrategySceneType
  strategy_key: string
  strategy_name: string
  target_scope_summary: string
  target_scope?: StrategyTargetScope
  params: Record<string, unknown>
  actions: StrategyTaskAction[]
  schedule_label: string
  schedule?: StrategyScheduleConfig
  status: StrategyTaskStatus
  tags: string[]
  notes?: string
  last_run_id?: string
  last_run_status?: StrategyRunStatus
  last_signal_count: number
  created_at: string
  updated_at: string
}

export interface StrategySummaryMetric {
  label: string
  value: string
  tone?: 'default' | 'positive' | 'negative' | 'warning'
}

export interface StrategyTaskRun {
  run_id: string
  task_id: string
  user_id: string
  scene_type: StrategySceneType
  strategy_key: string
  strategy_name: string
  trigger_source: 'manual' | 'schedule' | 'replay'
  run_status: StrategyRunStatus
  title: string
  summary: string
  started_at: string
  finished_at?: string
  signal_breakdown: {
    positive: number
    neutral: number
    negative: number
  }
  summary_metrics: StrategySummaryMetric[]
  related_trade_review_group_name?: string
  next_action_hint?: string
}

export interface StrategyTaskRunItem {
  item_id: string
  run_id: string
  entity_key: string
  entity_name: string
  signal: StrategySignalValue
  score: number
  reason: string
  tags: string[]
  action_result: string
  state_writeback: boolean
}

export interface CreateStrategySceneTaskInput {
  name: string
  scene_type: StrategySceneType
  strategy_key: string
  target_scope?: StrategyTargetScope
  target_scope_summary?: string
  params?: Record<string, unknown>
  schedule?: StrategyScheduleConfig
  schedule_label?: string
  notes?: string
  actions: Array<StrategyActionType | StrategyTaskActionInput>
}
