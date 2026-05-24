import { generateCompactId } from '@/utils/id'

import type {
  CreateStrategySceneTaskInput,
  StrategyActionType,
  StrategyDefinition,
  StrategySceneTask,
  StrategySceneType,
  StrategySignalValue,
  StrategyTaskAction,
  StrategyTaskActionInput,
  StrategyTaskRun,
  StrategyTaskRunItem,
  StrategyTaskStatus,
} from '@/types/strategy-v2'

const CURRENT_USER_ID = 'demo-user'

export const STRATEGY_SCENE_LABELS: Record<StrategySceneType, string> = {
  scan: '选股任务',
  listen: '监听任务',
  backtest: '回测任务',
  sim_trade: '模拟交易任务',
}

export const STRATEGY_TASK_STATUS_LABELS: Record<StrategyTaskStatus, string> = {
  draft: '草稿',
  active: '运行中',
  paused: '已暂停',
  archived: '已归档',
}

export const STRATEGY_ACTION_LABELS: Record<StrategyActionType, string> = {
  notify: '通知',
  add_to_pool: '加入股池',
  pool_transition: '股池流转',
  temp_list: '临时清单',
  paper_trade: '模拟成交',
  persist_result: '数据入库',
}

const strategyDefinitions: StrategyDefinition[] = [
  {
    strategy_key: 'double_cannon',
    name: '双响炮',
    description: '近一个月内出现两根涨幅超阈值的大阳线，第二根收盘价高于第一根；中间调整不跌破第一根最低价，且第二根距离最新交易日较近。',
    impl_type: 'builtin_code',
    supported_scenes: ['scan', 'listen', 'backtest', 'sim_trade'],
    supports_state: false,
    version: 1,
    tags: ['形态', '双响炮', '强势'],
    param_schema: [
      { key: 'lookback_days', label: '回看交易日', type: 'number', default: 22, description: '用于寻找两根大阳线的最近交易日数量，默认约一个月。' },
      { key: 'min_bull_pct', label: '大阳涨幅阈值(%)', type: 'float', default: 5, description: '单根阳线涨幅达到该阈值才视为有效大阳线。' },
      { key: 'max_second_age_days', label: '第二炮距今天数', type: 'number', default: 5, description: '第二根大阳线距离最新交易日不能超过该交易日数。' },
      { key: 'require_second_volume_gt_first', label: '第二炮放量', type: 'boolean', default: false, description: '启用后要求第二根大阳线成交量大于第一根。' },
      { key: 'require_bullish_ma', label: '均线多头排列', type: 'boolean', default: false, description: '启用后要求最新交易日均线满足短期 > 中期 > 长期。' },
      { key: 'ma_short', label: '短期均线', type: 'number', default: 5, description: '均线多头排列中的短期均线周期。' },
      { key: 'ma_mid', label: '中期均线', type: 'number', default: 10, description: '均线多头排列中的中期均线周期。' },
      { key: 'ma_long', label: '长期均线', type: 'number', default: 20, description: '均线多头排列中的长期均线周期。' },
      { key: 'require_pullback_shrink_volume', label: '调整缩量', type: 'boolean', default: false, description: '启用后要求两根大阳线之间的平均成交量小于两根大阳线均量。' },
    ],
    sample_outputs: [
      { signal: 1, title: '双响炮形态成立', summary: '可进入候选池、临时清单或监听后续确认。' },
      { signal: 0, title: '形态未完整成立', summary: '未找到有效两根大阳线，或可选过滤条件未满足。' },
      { signal: -1, title: '形态结构破坏', summary: '两根大阳线之间存在收盘价跌破第一根最低价的 K 线。' },
    ],
  },
  {
    strategy_key: 'ma5_buy',
    name: '5日线低吸',
    description: '股价回落到均线附近后，等待重新企稳并输出正向信号，适合做候选入池与低吸观察。',
    impl_type: 'builtin_code',
    supported_scenes: ['scan', 'listen', 'backtest', 'sim_trade'],
    supports_state: true,
    version: 2,
    tags: ['均线', '低吸', '企稳'],
    param_schema: [
      { key: 'ma_period', label: '均线周期', type: 'number', default: 5, description: '用于计算企稳参考的均线周期。' },
      { key: 'touch_range', label: '接触阈值(%)', type: 'float', default: 2, description: '价格接近均线的允许偏差范围。' },
      { key: 'stable_periods', label: '企稳轮数', type: 'number', default: 2, description: '连续站稳的最小轮数。' },
    ],
    sample_outputs: [
      { signal: 1, title: '回落后重新站稳', summary: '适合进入候选池，后续在股池中继续筛。' },
      { signal: 0, title: '仍在震荡观察', summary: '条件未充分，不触发动作。' },
      { signal: -1, title: '跌破均线失效', summary: '观察条件被破坏，可移出当前观察路径。' },
    ],
  },
  {
    strategy_key: 'price_change',
    name: '涨跌幅阈值',
    description: '监控单只股票或一个范围在盘中达到指定涨跌幅阈值后的触发情况。',
    impl_type: 'builtin_code',
    supported_scenes: ['listen', 'scan', 'backtest'],
    supports_state: true,
    version: 2,
    tags: ['阈值', '异动', '盘中'],
    param_schema: [
      {
        key: 'direction',
        label: '方向',
        type: 'select',
        default: 'both',
        description: '决定监控上涨、下跌还是双向异动。',
        options: [
          { label: '双向', value: 'both' },
          { label: '向上', value: 'up' },
          { label: '向下', value: 'down' },
        ],
      },
      { key: 'threshold', label: '阈值(%)', type: 'float', default: 5, description: '触发信号的涨跌幅阈值。' },
    ],
    sample_outputs: [
      { signal: 1, title: '向上突破阈值', summary: '适合发通知，或推动从信号池流转到确认池。' },
      { signal: 0, title: '未触发', summary: '没有明显异动，维持观察。' },
      { signal: -1, title: '向下触发阈值', summary: '可用于风险提醒或候选剔除。' },
    ],
  },
  {
    strategy_key: 'fixed_stop_loss',
    name: '固定止损',
    description: '以参考价和止损比例为核心，适合持仓组或模拟交易任务做风险提醒。',
    impl_type: 'builtin_code',
    supported_scenes: ['listen', 'sim_trade', 'backtest'],
    supports_state: true,
    version: 2,
    tags: ['止损', '持仓', '风控'],
    param_schema: [
      { key: 'reference_price', label: '参考价', type: 'float', default: 10.2, description: '止损线的基准价格。' },
      { key: 'stop_loss_pct', label: '止损比例(%)', type: 'float', default: 8, description: '参考价向下的止损幅度。' },
    ],
    sample_outputs: [
      { signal: 1, title: '止损触发', summary: '任务层通常会执行通知或模拟卖出。' },
      { signal: 0, title: '持仓正常', summary: '还未触发止损。' },
      { signal: -1, title: '跌势恶化', summary: '可作为更强的负向风险信号。' },
    ],
  },
  {
    strategy_key: 'breadth_pulse',
    name: '市场涨跌比脉冲',
    description: '观察指数与涨跌家数结构，适合做市场情绪监听和训练时段筛选。',
    impl_type: 'builtin_code',
    supported_scenes: ['listen', 'scan'],
    supports_state: false,
    version: 1,
    tags: ['情绪', '市场', '宽度'],
    param_schema: [
      { key: 'up_down_ratio', label: '涨跌比阈值', type: 'float', default: 2.2, description: '市场偏强所需的涨跌家数比。' },
      { key: 'limit_up_threshold', label: '涨停家数', type: 'number', default: 55, description: '辅助确认市场强度。' },
    ],
    sample_outputs: [
      { signal: 1, title: '市场宽度强化', summary: '适合推动强势模式池的自动加仓观察。' },
      { signal: 0, title: '市场中性', summary: '等待进一步确认。' },
      { signal: -1, title: '市场退潮', summary: '用于提醒缩容或降低进攻性。' },
    ],
  },
]

const taskStore: StrategySceneTask[] = [
  {
    task_id: 'task_scan_ma5',
    user_id: CURRENT_USER_ID,
    name: 'MA5 候选入池',
    scene_type: 'scan',
    strategy_key: 'ma5_buy',
    strategy_name: '5日线低吸',
    target_scope_summary: '全市场 · 排除 ST · 最近 120 日有交易',
    params: { ma_period: 5, touch_range: 2, stable_periods: 2 },
    actions: [
      makeAction('add_to_pool', '加入候选池', '命中后写入现有候选池'),
      makeAction('temp_list', '生成临时清单', '保留本次扫描结果供人工复核'),
    ],
    schedule_label: '交易日 09:45 / 10:30 / 13:45',
    status: 'active',
    tags: ['候选池', '主线模式'],
    notes: '作为入池前置扫描，不直接形成交易指令。',
    last_run_id: 'run_scan_ma5_1',
    last_run_status: 'success',
    last_signal_count: 18,
    created_at: '2026-05-18 09:20',
    updated_at: '2026-05-22 09:47',
  },
  {
    task_id: 'task_listen_pulse',
    user_id: CURRENT_USER_ID,
    name: '盘口异动监听',
    scene_type: 'listen',
    strategy_key: 'price_change',
    strategy_name: '涨跌幅阈值',
    target_scope_summary: '观察池 + 自选股 · 共 63 只',
    params: { direction: 'both', threshold: 4.8 },
    actions: [
      makeAction('notify', '推送提醒', '企业微信 + 站内提醒'),
      makeAction('pool_transition', '流转到确认池', '仅对向上信号触发'),
    ],
    schedule_label: '交易时段每 1 分钟轮询',
    status: 'active',
    tags: ['异动', '观察池'],
    notes: '作为盘中强弱确认的第一层监听。',
    last_run_id: 'run_listen_pulse_1',
    last_run_status: 'partial_success',
    last_signal_count: 6,
    created_at: '2026-05-17 21:10',
    updated_at: '2026-05-22 10:31',
  },
  {
    task_id: 'task_backtest_stop',
    user_id: CURRENT_USER_ID,
    name: '固定止损历史回放',
    scene_type: 'backtest',
    strategy_key: 'fixed_stop_loss',
    strategy_name: '固定止损',
    target_scope_summary: '交割单分组：训练样本 A · 2025Q4 - 2026Q1',
    params: { stop_loss_pct: 8 },
    actions: [
      makeAction('paper_trade', '生成模拟成交', '按统一交易配置写入回测结果'),
    ],
    schedule_label: '手动运行',
    status: 'paused',
    tags: ['回测', '止损'],
    notes: '用于验证固定止损阈值对历史样本的影响。',
    last_run_id: 'run_backtest_stop_1',
    last_run_status: 'success',
    last_signal_count: 24,
    created_at: '2026-05-16 14:00',
    updated_at: '2026-05-21 17:28',
  },
  {
    task_id: 'task_sim_hold',
    user_id: CURRENT_USER_ID,
    name: '持仓组模拟交易',
    scene_type: 'sim_trade',
    strategy_key: 'fixed_stop_loss',
    strategy_name: '固定止损',
    target_scope_summary: '持仓组：实盘训练账户',
    params: { stop_loss_pct: 7.5 },
    actions: [
      makeAction('notify', '风险提醒', '盘中止损触发时优先提醒'),
      makeAction('paper_trade', '模拟卖出', '生成模拟成交与持仓变化'),
    ],
    schedule_label: '交易日收盘后 + 盘中异常补轮',
    status: 'active',
    tags: ['模拟交易', '持仓'],
    notes: '先走模拟链路，后续再评估是否接实盘。',
    last_run_id: 'run_sim_hold_1',
    last_run_status: 'success',
    last_signal_count: 3,
    created_at: '2026-05-19 08:50',
    updated_at: '2026-05-22 15:02',
  },
]

const runStore: StrategyTaskRun[] = [
  {
    run_id: 'run_scan_ma5_1',
    task_id: 'task_scan_ma5',
    user_id: CURRENT_USER_ID,
    scene_type: 'scan',
    strategy_key: 'ma5_buy',
    strategy_name: '5日线低吸',
    trigger_source: 'schedule',
    run_status: 'success',
    title: '09:45 日内扫描',
    summary: '从全市场筛出 18 只候选，14 只进入候选池，4 只保留在临时列表等待人工复核。',
    started_at: '2026-05-22 09:45',
    finished_at: '2026-05-22 09:46',
    signal_breakdown: { positive: 18, neutral: 144, negative: 9 },
    summary_metrics: [
      { label: '候选数', value: '18' },
      { label: '入池数', value: '14', tone: 'positive' },
      { label: '人工复核', value: '4', tone: 'warning' },
    ],
    next_action_hint: '优先在候选池中查看 3 连阳后的回踩样本。',
  },
  {
    run_id: 'run_listen_pulse_1',
    task_id: 'task_listen_pulse',
    user_id: CURRENT_USER_ID,
    scene_type: 'listen',
    strategy_key: 'price_change',
    strategy_name: '涨跌幅阈值',
    trigger_source: 'schedule',
    run_status: 'partial_success',
    title: '10:30 盘中监听',
    summary: '触发 6 个异动信号，其中 4 个已通知，2 个因冷却限制跳过流转。',
    started_at: '2026-05-22 10:30',
    finished_at: '2026-05-22 10:31',
    signal_breakdown: { positive: 4, neutral: 52, negative: 2 },
    summary_metrics: [
      { label: '通知发送', value: '4', tone: 'positive' },
      { label: '流转成功', value: '2', tone: 'positive' },
      { label: '冷却跳过', value: '2', tone: 'warning' },
    ],
    next_action_hint: '确认池中新增的 2 只标的建议进入沉浸复盘。',
  },
  {
    run_id: 'run_backtest_stop_1',
    task_id: 'task_backtest_stop',
    user_id: CURRENT_USER_ID,
    scene_type: 'backtest',
    strategy_key: 'fixed_stop_loss',
    strategy_name: '固定止损',
    trigger_source: 'manual',
    run_status: 'success',
    title: '训练样本回放',
    summary: '完成 24 次止损判断，生成 9 笔模拟卖出记录，并写入交割单分组“止损回放-2026W20”。',
    started_at: '2026-05-21 16:48',
    finished_at: '2026-05-21 16:53',
    signal_breakdown: { positive: 9, neutral: 15, negative: 0 },
    summary_metrics: [
      { label: '模拟卖出', value: '9', tone: 'positive' },
      { label: '命中率', value: '37.5%' },
      { label: '关联交割单', value: '已创建' },
    ],
    related_trade_review_group_name: '止损回放-2026W20',
    next_action_hint: '下一步适合去交割单分析页查看盈亏分布和模式归因。',
  },
  {
    run_id: 'run_sim_hold_1',
    task_id: 'task_sim_hold',
    user_id: CURRENT_USER_ID,
    scene_type: 'sim_trade',
    strategy_key: 'fixed_stop_loss',
    strategy_name: '固定止损',
    trigger_source: 'schedule',
    run_status: 'success',
    title: '收盘后模拟更新',
    summary: '更新 11 只持仓，3 只触发风险提醒，其中 1 只生成模拟卖出。',
    started_at: '2026-05-22 15:00',
    finished_at: '2026-05-22 15:02',
    signal_breakdown: { positive: 1, neutral: 8, negative: 2 },
    summary_metrics: [
      { label: '持仓更新', value: '11' },
      { label: '风险提醒', value: '3', tone: 'warning' },
      { label: '模拟卖出', value: '1', tone: 'negative' },
    ],
    related_trade_review_group_name: '实盘训练账户-模拟交易',
    next_action_hint: '检查模拟卖出的 300059.SZ 是否需要同步加入后续复盘标签。',
  },
]

const runItemStore: Record<string, StrategyTaskRunItem[]> = {
  run_scan_ma5_1: [
    makeRunItem('run_scan_ma5_1', '002594.SZ', '比亚迪', 1, 0.91, '回踩 5 日线后重新放量企稳', ['候选池', '趋势延续'], '已加入候选池', true),
    makeRunItem('run_scan_ma5_1', '300308.SZ', '中际旭创', 1, 0.87, '分时回踩后二次站上均线', ['人工复核'], '保留在临时列表', true),
    makeRunItem('run_scan_ma5_1', '603019.SH', '中科曙光', 0, 0.43, '接近均线但企稳轮数不足', ['观察'], '无动作', false),
    makeRunItem('run_scan_ma5_1', '600536.SH', '中国软件', -1, 0.71, '跌破均线并放量转弱', ['淘汰'], '未入池', true),
  ],
  run_listen_pulse_1: [
    makeRunItem('run_listen_pulse_1', '300750.SZ', '宁德时代', 1, 0.89, '涨幅突破 4.8%，量能同步放大', ['异动', '确认池'], '已通知并流转到确认池', true),
    makeRunItem('run_listen_pulse_1', '002371.SZ', '北方华创', 1, 0.76, '盘中快速拉升超过阈值', ['异动'], '已通知，流转受冷却限制', true),
    makeRunItem('run_listen_pulse_1', '601012.SH', '隆基绿能', -1, 0.73, '跌幅触发负向阈值', ['风险'], '已通知', true),
  ],
  run_backtest_stop_1: [
    makeRunItem('run_backtest_stop_1', '000977.SZ', '浪潮信息', 1, 0.82, '跌破固定止损线后触发模拟卖出', ['回测', '卖出'], '已写入交割单分组', true),
    makeRunItem('run_backtest_stop_1', '603986.SH', '兆易创新', 0, 0.28, '区间内未触发止损', ['回测'], '保持持仓', false),
  ],
  run_sim_hold_1: [
    makeRunItem('run_sim_hold_1', '300059.SZ', '东方财富', 1, 0.9, '盘中最低价穿透止损线', ['模拟交易', '卖出'], '已生成模拟卖出', true),
    makeRunItem('run_sim_hold_1', '600519.SH', '贵州茅台', -1, 0.64, '浮盈回撤超预警阈值', ['风险提醒'], '已通知待人工确认', true),
    makeRunItem('run_sim_hold_1', '002230.SZ', '科大讯飞', 0, 0.37, '仍处于安全范围', ['持仓'], '无动作', false),
  ],
}

function makeAction(
  actionType: StrategyActionType,
  label: string,
  summary: string,
  params?: Record<string, unknown>,
  triggerSignals?: StrategySignalValue[],
): StrategyTaskAction {
  return {
    action_id: generateCompactId().slice(0, 12),
    action_type: actionType,
    label,
    enabled: true,
    summary,
    params,
    trigger_signals: triggerSignals,
  }
}

function normalizeActionInput(input: StrategyActionType | StrategyTaskActionInput): StrategyTaskAction {
  if (typeof input === 'string') {
    return makeAction(input, STRATEGY_ACTION_LABELS[input], `由任务层执行 ${STRATEGY_ACTION_LABELS[input]}`)
  }

  return makeAction(
    input.action_type,
    input.label || STRATEGY_ACTION_LABELS[input.action_type],
    buildActionSummary(input),
    input.params,
    input.trigger_signals,
  )
}

function buildActionSummary(input: StrategyTaskActionInput): string {
  const signalText = input.trigger_signals.length > 0
    ? `信号 ${input.trigger_signals.join('/')}`
    : '全部信号'
  return `${signalText} 时执行 ${STRATEGY_ACTION_LABELS[input.action_type]}`
}

function defaultStrategyParams(strategy?: StrategyDefinition): Record<string, unknown> {
  return Object.fromEntries((strategy?.param_schema || []).map((item) => [item.key, item.default]))
}

function makeRunItem(
  runId: string,
  entityKey: string,
  entityName: string,
  signal: -1 | 0 | 1,
  score: number,
  reason: string,
  tags: string[],
  actionResult: string,
  stateWriteback: boolean,
): StrategyTaskRunItem {
  return {
    item_id: generateCompactId().slice(0, 16),
    run_id: runId,
    entity_key: entityKey,
    entity_name: entityName,
    signal,
    score,
    reason,
    tags,
    action_result: actionResult,
    state_writeback: stateWriteback,
  }
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function nowString(): string {
  const now = new Date()
  const year = now.getFullYear()
  const month = `${now.getMonth() + 1}`.padStart(2, '0')
  const day = `${now.getDate()}`.padStart(2, '0')
  const hour = `${now.getHours()}`.padStart(2, '0')
  const minute = `${now.getMinutes()}`.padStart(2, '0')
  return `${year}-${month}-${day} ${hour}:${minute}`
}

function buildGeneratedRun(task: StrategySceneTask): StrategyTaskRun {
  const runId = `run_${task.task_id}_${generateCompactId().slice(0, 6)}`
  const baseSummaryByScene: Record<StrategySceneType, string> = {
    scan: '完成一轮候选扫描，并输出新的候选列表与池内建议。',
    listen: '完成一轮监听评估，并生成通知与流转建议。',
    backtest: '完成一轮历史区间回放，并输出模拟交易结果。',
    sim_trade: '完成一轮模拟交易更新，并更新持仓与风控建议。',
  }

  const metricsByScene: Record<StrategySceneType, StrategyTaskRun['summary_metrics']> = {
    scan: [
      { label: '候选数', value: '12' },
      { label: '入池建议', value: '9', tone: 'positive' },
      { label: '人工复核', value: '3', tone: 'warning' },
    ],
    listen: [
      { label: '通知发送', value: '3', tone: 'positive' },
      { label: '流转建议', value: '2', tone: 'positive' },
      { label: '冷却跳过', value: '1', tone: 'warning' },
    ],
    backtest: [
      { label: '模拟成交', value: '7', tone: 'positive' },
      { label: '胜率', value: '57%' },
      { label: '交割单组', value: '已生成' },
    ],
    sim_trade: [
      { label: '持仓更新', value: '8' },
      { label: '风险提醒', value: '2', tone: 'warning' },
      { label: '模拟卖出', value: '1', tone: 'negative' },
    ],
  }

  return {
    run_id: runId,
    task_id: task.task_id,
    user_id: task.user_id,
    scene_type: task.scene_type,
    strategy_key: task.strategy_key,
    strategy_name: task.strategy_name,
    trigger_source: 'manual',
    run_status: 'success',
    title: `${STRATEGY_SCENE_LABELS[task.scene_type]} · 手动运行`,
    summary: baseSummaryByScene[task.scene_type],
    started_at: nowString(),
    finished_at: nowString(),
    signal_breakdown: {
      positive: task.scene_type === 'backtest' ? 7 : 3,
      neutral: task.scene_type === 'scan' ? 21 : 5,
      negative: task.scene_type === 'listen' || task.scene_type === 'sim_trade' ? 2 : 1,
    },
    summary_metrics: metricsByScene[task.scene_type],
    related_trade_review_group_name:
      task.scene_type === 'backtest' || task.scene_type === 'sim_trade'
        ? `${task.name}-结果组`
        : undefined,
    next_action_hint:
      task.scene_type === 'scan'
        ? '建议把高强度候选送进候选池后继续在股池里复盘。'
        : task.scene_type === 'listen'
          ? '建议优先复核本轮新触发的正向异动标的。'
          : '建议去交割单分析页继续查看收益与模式归因。',
  }
}

function buildGeneratedItems(run: StrategyTaskRun): StrategyTaskRunItem[] {
  if (run.scene_type === 'scan') {
    return [
      makeRunItem(run.run_id, '002938.SZ', '鹏鼎控股', 1, 0.84, '回踩后重新放量站稳', ['候选池'], '建议加入候选池', true),
      makeRunItem(run.run_id, '300502.SZ', '新易盛', 1, 0.79, '趋势延续但需要人工确认时机', ['人工复核'], '加入临时列表', true),
      makeRunItem(run.run_id, '688256.SH', '寒武纪', 0, 0.41, '结构尚未完全确认', ['观察'], '无动作', false),
    ]
  }
  if (run.scene_type === 'listen') {
    return [
      makeRunItem(run.run_id, '601138.SH', '工业富联', 1, 0.83, '盘中涨幅超过阈值并放量', ['异动'], '已通知', true),
      makeRunItem(run.run_id, '000333.SZ', '美的集团', 0, 0.34, '接近阈值但未最终触发', ['观察'], '无动作', false),
      makeRunItem(run.run_id, '601899.SH', '紫金矿业', -1, 0.72, '下跌异动触发负向提醒', ['风险'], '已通知', true),
    ]
  }
  if (run.scene_type === 'backtest') {
    return [
      makeRunItem(run.run_id, '002465.SZ', '海格通信', 1, 0.77, '止损触发后形成模拟卖出', ['回测'], '已写入交割单结果', true),
      makeRunItem(run.run_id, '600036.SH', '招商银行', 0, 0.29, '未触发止损', ['回测'], '保持持仓', false),
    ]
  }
  return [
    makeRunItem(run.run_id, '300024.SZ', '机器人', 1, 0.81, '收盘回顾触发模拟卖出', ['模拟交易'], '已生成模拟成交', true),
    makeRunItem(run.run_id, '600276.SH', '恒瑞医药', -1, 0.67, '回撤超过风险阈值', ['风险提醒'], '已通知待确认', true),
    makeRunItem(run.run_id, '002352.SZ', '顺丰控股', 0, 0.35, '处于正常波动范围', ['持仓'], '无动作', false),
  ]
}

export async function listStrategyDefinitions(): Promise<StrategyDefinition[]> {
  return clone(strategyDefinitions)
}

export async function getStrategyDefinition(strategyKey: string): Promise<StrategyDefinition | undefined> {
  return clone(strategyDefinitions.find((item) => item.strategy_key === strategyKey))
}

export async function listStrategySceneTasks(sceneType?: StrategySceneType): Promise<StrategySceneTask[]> {
  const items = sceneType ? taskStore.filter((item) => item.scene_type === sceneType) : taskStore
  return clone(items)
}

export async function getStrategySceneTask(taskId: string): Promise<StrategySceneTask | undefined> {
  return clone(taskStore.find((item) => item.task_id === taskId))
}

export async function listTaskRuns(taskId?: string): Promise<StrategyTaskRun[]> {
  const items = taskId ? runStore.filter((item) => item.task_id === taskId) : runStore
  return clone(items.sort((a, b) => b.started_at.localeCompare(a.started_at)))
}

export async function getTaskRun(runId: string): Promise<StrategyTaskRun | undefined> {
  return clone(runStore.find((item) => item.run_id === runId))
}

export async function getRunItems(runId: string): Promise<StrategyTaskRunItem[]> {
  return clone(runItemStore[runId] || [])
}

export async function createStrategySceneTask(input: CreateStrategySceneTaskInput): Promise<StrategySceneTask> {
  const strategy = strategyDefinitions.find((item) => item.strategy_key === input.strategy_key)
  const targetScopeSummary = input.target_scope?.summary || input.target_scope_summary || ''
  const scheduleLabel = input.schedule?.label || input.schedule_label || ''
  const task: StrategySceneTask = {
    task_id: `task_${generateCompactId().slice(0, 10)}`,
    user_id: CURRENT_USER_ID,
    name: input.name,
    scene_type: input.scene_type,
    strategy_key: input.strategy_key,
    strategy_name: strategy?.name || input.strategy_key,
    target_scope_summary: targetScopeSummary,
    target_scope: input.target_scope,
    params: {
      ...defaultStrategyParams(strategy),
      ...(input.params || {}),
    },
    actions: input.actions.map(normalizeActionInput),
    schedule_label: scheduleLabel,
    schedule: input.schedule,
    status: input.scene_type === 'backtest' ? 'draft' : 'active',
    tags: [STRATEGY_SCENE_LABELS[input.scene_type], ...(strategy?.tags.slice(0, 2) || [])],
    notes: input.notes?.trim() || '',
    last_signal_count: 0,
    created_at: nowString(),
    updated_at: nowString(),
  }
  taskStore.unshift(task)
  return clone(task)
}

export async function updateStrategySceneTask(taskId: string, input: CreateStrategySceneTaskInput): Promise<StrategySceneTask | undefined> {
  const task = taskStore.find((item) => item.task_id === taskId)
  if (!task) return undefined

  const strategy = strategyDefinitions.find((item) => item.strategy_key === input.strategy_key)
  const targetScopeSummary = input.target_scope?.summary || input.target_scope_summary || ''
  const scheduleLabel = input.schedule?.label || input.schedule_label || ''

  task.name = input.name.trim()
  task.scene_type = input.scene_type
  task.strategy_key = input.strategy_key
  task.strategy_name = strategy?.name || input.strategy_key
  task.target_scope_summary = targetScopeSummary.trim()
  task.target_scope = input.target_scope
  task.schedule_label = scheduleLabel.trim()
  task.schedule = input.schedule
  task.notes = input.notes?.trim() || ''
  task.actions = input.actions.map(normalizeActionInput)
  task.tags = [STRATEGY_SCENE_LABELS[input.scene_type], ...(strategy?.tags.slice(0, 2) || [])]
  task.params = {
    ...defaultStrategyParams(strategy),
    ...(input.params || {}),
  }
  task.updated_at = nowString()

  return clone(task)
}

export async function updateStrategySceneTaskStatus(taskId: string, status: StrategyTaskStatus): Promise<StrategySceneTask | undefined> {
  const task = taskStore.find((item) => item.task_id === taskId)
  if (!task) return undefined
  task.status = status
  task.updated_at = nowString()
  return clone(task)
}

export async function runStrategySceneTask(taskId: string): Promise<StrategyTaskRun | undefined> {
  const task = taskStore.find((item) => item.task_id === taskId)
  if (!task) return undefined

  const run = buildGeneratedRun(task)
  const runItems = buildGeneratedItems(run)

  runStore.unshift(run)
  runItemStore[run.run_id] = runItems

  task.last_run_id = run.run_id
  task.last_run_status = run.run_status
  task.last_signal_count = run.signal_breakdown.positive + run.signal_breakdown.negative
  task.updated_at = nowString()

  return clone(run)
}

export async function getStrategyV2Overview(): Promise<{
  strategyCount: number
  statefulCount: number
  taskCount: number
  activeTaskCount: number
  runCount: number
}> {
  return {
    strategyCount: strategyDefinitions.length,
    statefulCount: strategyDefinitions.filter((item) => item.supports_state).length,
    taskCount: taskStore.length,
    activeTaskCount: taskStore.filter((item) => item.status === 'active').length,
    runCount: runStore.length,
  }
}
