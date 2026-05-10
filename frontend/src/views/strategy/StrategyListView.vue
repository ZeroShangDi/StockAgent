<script setup lang="ts">
/**
 * 策略订阅列表
 * 
 * 简化架构：
 * - 每种策略类型只有一条策略数据
 * - 普通用户只能添加/移除个股
 * - 管理员可修改策略参数和激活状态
 */

import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Refresh, Edit } from '@element-plus/icons-vue'
import { subscriptionApi, stockApi, stockPickerApi, tradeReviewApi } from '@/api'
import { useUserStore } from '@/stores/user'
import { StrategyType } from '@/api/types'
import type {
  StrategySubscription,
  StockBasic,
  StrategyTypeInfo,
  StrategyParamDef,
  StockInfoBrief,
  StrategyStockConfig,
  StrategyStockPoint,
  StrategyTransitionRule,
} from '@/api/types'
import type { StockPoolSummary } from '@/api/modules/stock-picker'
import type { TradeReviewGroupSummary } from '@/api/modules/trade-review'

// ==================== 状态 ====================

const userStore = useUserStore()

const subscriptions = ref<StrategySubscription[]>([])
const loading = ref(true)
const viewMode = ref<'compact' | 'detail' | 'table'>('compact')

// 可用策略类型（从服务端加载）
const availableStrategyTypes = ref<StrategyTypeInfo[]>([])

// 添加个股弹窗
const addStockDialogVisible = ref(false)
const currentStrategyType = ref<string>('')
const selectedStock = ref<string>('')
const stockOptions = ref<StockBasic[]>([])
const stockSearchLoading = ref(false)
const addingStock = ref(false)

// 展开的监听列表
const expandedLists = ref<Set<string>>(new Set())

// 编辑参数弹窗
const editParamsDialogVisible = ref(false)
const editingStrategyType = ref<string>('')
const editingParams = ref<Record<string, unknown>>({})
const savingParams = ref(false)
const transitionRulesDialogVisible = ref(false)
const editingTransitionStrategyType = ref('')
const availablePools = ref<StockPoolSummary[]>([])
const poolLoading = ref(false)
const editingTransitionRules = ref<StrategyTransitionRule[]>([])
const tradeReviewGroups = ref<TradeReviewGroupSummary[]>([])
const tradeReviewGroupLoading = ref(false)

// 单股撑压线配置弹窗
const stockConfigDialogVisible = ref(false)
const editingStockStrategyType = ref('')
const editingStockTsCode = ref('')
const editingStockName = ref('')
const editingStockConfig = ref<StrategyStockConfig>(createEmptyStockConfig())
const savingStockConfig = ref(false)

const trendTypeOptions = [
  { label: '上升趋势', value: 'uptrend' },
  { label: '下降趋势', value: 'downtrend' },
  { label: '盘整趋势', value: 'range' },
  { label: '自定义', value: 'custom' },
]

const lineModeOptions = [
  { label: '斜线', value: 'trend' },
  { label: '水平线', value: 'horizontal' },
]

const transitionModeOptions = [
  { label: '移动到目标池', value: 'move' },
  { label: '复制到目标池', value: 'copy' },
]

const viewModeOptions = [
  { label: '紧凑卡片', value: 'compact' },
  { label: '详细卡片', value: 'detail' },
  { label: '表格模式', value: 'table' },
]

// ==================== 方法 ====================

/** 加载可用策略类型 */
async function loadStrategyTypes(): Promise<void> {
  try {
    availableStrategyTypes.value = await subscriptionApi.getStrategyTypes()
  } catch (error) {
    console.error('加载策略类型失败:', error)
  }
}

/** 加载订阅列表 */
async function loadSubscriptions(): Promise<void> {
  loading.value = true
  try {
    subscriptions.value = await subscriptionApi.getSubscriptions()
  } catch (error) {
    ElMessage.error('加载订阅列表失败')
    console.error(error)
  } finally {
    loading.value = false
  }
}

/** 获取显示的股票列表（包含名称） */
function getDisplayStockInfos(sub: StrategySubscription): StockInfoBrief[] {
  const stocks = sub.watch_list_info || []
  if (expandedLists.value.has(sub.strategy_type)) {
    return stocks
  }
  return stocks.slice(0, 5)
}

/** 获取策略显示名称 */
function getStrategyName(strategyType: string): string {
  const st = availableStrategyTypes.value.find(s => s.type === strategyType)
  return st?.name || strategyType
}

function getParamDisplayValue(strategyType: string, key: string, fallback: unknown): string {
  if (key === 'position_group_id') {
    const sub = getSubscription(strategyType)
    const groupName = sub?.params?.position_group_name
    if (typeof groupName === 'string' && groupName.trim()) {
      return groupName
    }
  }
  const strategy = availableStrategyTypes.value.find(s => s.type === strategyType)
  const param = strategy?.param_schema?.find(item => item.key === key)
  if (param?.options?.length) {
    const matched = param.options.find(option => option.value === fallback)
    if (matched) return matched.label
  }
  if (typeof fallback === 'boolean') {
    return fallback ? '是' : '否'
  }
  if (fallback == null || fallback === '') {
    return '-'
  }
  return String(fallback)
}

function getStrategyMeta(strategyType: string): StrategyTypeInfo | undefined {
  return availableStrategyTypes.value.find(s => s.type === strategyType)
}

function getBasicParamDefs(strategyType: string): StrategyParamDef[] {
  const strategy = getStrategyMeta(strategyType)
  const basicKeys = new Set(strategy?.basic_param_keys || [])
  return (strategy?.param_schema || []).filter(param => basicKeys.has(param.key))
}

function getStrategyParamDefs(strategyType: string): StrategyParamDef[] {
  const strategy = getStrategyMeta(strategyType)
  const basicKeys = new Set(strategy?.basic_param_keys || [])
  return (strategy?.param_schema || []).filter(param => !basicKeys.has(param.key))
}

/** 获取策略订阅数据 */
function getSubscription(strategyType: string): StrategySubscription | undefined {
  return subscriptions.value.find(s => s.strategy_type === strategyType)
}

function isStrategyActive(strategyType: string): boolean {
  return getSubscription(strategyType)?.is_active !== false
}

function getWatchCount(strategyType: string): number {
  const sub = getSubscription(strategyType)
  return sub?.effective_watch_count ?? sub?.watch_list_info?.length ?? 0
}

function getWatchCountSummary(strategyType: string): string {
  const sub = getSubscription(strategyType)
  if (!sub) return '暂无监听'
  const effective = sub.effective_watch_count ?? sub.watch_list_info?.length ?? 0
  const manual = sub.manual_watch_count ?? sub.watch_list_info?.length ?? 0
  const positionGroup = sub.effective_watch_breakdown?.position_group || 0
  const sourcePools = sub.effective_watch_breakdown?.source_pools || 0

  const segments = [`实际 ${effective} 只`, `手动 ${manual} 只`]
  if (positionGroup > 0) {
    segments.push(`持仓分组 ${positionGroup} 只`)
  }
  if (sourcePools > 0) {
    segments.push(`来源股池 ${sourcePools} 只`)
  }
  return segments.join(' · ')
}

function getEnabledTransitionRuleCount(strategyType: string): number {
  return getTransitionRules(strategyType).filter(rule => rule.enabled).length
}

function getStrategyParamSummary(strategyType: string): string {
  const defs = getStrategyParamDefs(strategyType)
  if (!defs.length) return '无额外参数'
  const subscription = getSubscription(strategyType)
  const preview = defs.slice(0, 2).map((param) => {
    const value = subscription?.params[param.key] ?? param.default
    return `${param.label}：${getParamDisplayValue(strategyType, param.key, value)}`
  })
  return defs.length > 2 ? `${preview.join(' · ')} 等 ${defs.length} 项` : preview.join(' · ')
}

function getCompactBasicSummary(strategyType: string): string {
  const meta = getStrategyMeta(strategyType)
  const parts = [`监听频率：${meta?.schedule_label || '盘中轮询'}`]
  const basicDefs = getBasicParamDefs(strategyType)
  const subscription = getSubscription(strategyType)
  for (const param of basicDefs) {
    const value = subscription?.params[param.key] ?? param.default
    parts.push(`${param.label}：${getParamDisplayValue(strategyType, param.key, value)}`)
  }
  return parts.join(' · ')
}

function isSupportResistanceStrategy(strategyType: string): boolean {
  return strategyType === StrategyType.SUPPORT_RESISTANCE
}

function isMaBuyStrategy(strategyType: string): boolean {
  return strategyType === StrategyType.MA5_BUY
}

function isFixedStopLossStrategy(strategyType: string): boolean {
  return strategyType === StrategyType.FIXED_STOP_LOSS
}

function isTrailingStopLossStrategy(strategyType: string): boolean {
  return strategyType === StrategyType.TRAILING_STOP_LOSS
}

function isPerStockConfigStrategy(strategyType: string): boolean {
  return (
    isMaBuyStrategy(strategyType) ||
    isSupportResistanceStrategy(strategyType) ||
    isFixedStopLossStrategy(strategyType) ||
    isTrailingStopLossStrategy(strategyType)
  )
}

function createEmptyPoint(): StrategyStockPoint {
  return { date: '', price: null }
}

function createEmptyStockConfig(): StrategyStockConfig {
  return {
    trend_type: 'uptrend',
    support_enabled: true,
    resistance_enabled: true,
    support_mode: 'trend',
    resistance_mode: 'trend',
    support_points: [createEmptyPoint(), createEmptyPoint()],
    resistance_points: [createEmptyPoint(), createEmptyPoint()],
    support_price: null,
    resistance_price: null,
    note: '',
  }
}

function createMABuyConfig(): StrategyStockConfig {
  return {
    enabled: true,
    ma_period: 5,
    touch_range: 2,
    stable_periods: 2,
    note: '',
  }
}

function createFixedStopLossConfig(): StrategyStockConfig {
  return {
    enabled: true,
    reference_price: null,
    reference_date: '',
    stop_loss_pct: 8,
    note: '',
  }
}

function createTrailingStopLossConfig(): StrategyStockConfig {
  return {
    enabled: true,
    entry_price: null,
    entry_date: '',
    highest_price: null,
    highest_price_date: '',
    trail_pct: 6,
    note: '',
  }
}

function clonePoint(point?: StrategyStockPoint): StrategyStockPoint {
  return {
    date: point?.date || '',
    price: point?.price ?? null,
  }
}

function cloneStockConfig(config?: Partial<StrategyStockConfig>): StrategyStockConfig {
  const fallback = createEmptyStockConfig()
  return {
    trend_type: config?.trend_type || fallback.trend_type,
    support_enabled: config?.support_enabled ?? fallback.support_enabled,
    resistance_enabled: config?.resistance_enabled ?? fallback.resistance_enabled,
    support_mode: config?.support_mode || fallback.support_mode,
    resistance_mode: config?.resistance_mode || fallback.resistance_mode,
    support_points: [
      clonePoint(config?.support_points?.[0]),
      clonePoint(config?.support_points?.[1]),
    ],
    resistance_points: [
      clonePoint(config?.resistance_points?.[0]),
      clonePoint(config?.resistance_points?.[1]),
    ],
    support_price: config?.support_price ?? fallback.support_price,
    resistance_price: config?.resistance_price ?? fallback.resistance_price,
    note: config?.note || '',
  }
}

function cloneMABuyConfig(config?: Partial<StrategyStockConfig>): StrategyStockConfig {
  const fallback = createMABuyConfig()
  return {
    enabled: config?.enabled ?? fallback.enabled,
    ma_period: config?.ma_period ?? fallback.ma_period,
    touch_range: config?.touch_range ?? fallback.touch_range,
    stable_periods: config?.stable_periods ?? fallback.stable_periods,
    note: config?.note || '',
    last_triggered_date: config?.last_triggered_date || '',
  }
}

function cloneFixedStopLossConfig(config?: Partial<StrategyStockConfig>): StrategyStockConfig {
  const fallback = createFixedStopLossConfig()
  return {
    enabled: config?.enabled ?? fallback.enabled,
    reference_price: config?.reference_price ?? fallback.reference_price,
    reference_date: config?.reference_date || fallback.reference_date,
    stop_loss_pct: config?.stop_loss_pct ?? fallback.stop_loss_pct,
    note: config?.note || '',
    last_triggered_date: config?.last_triggered_date || '',
  }
}

function cloneTrailingStopLossConfig(config?: Partial<StrategyStockConfig>): StrategyStockConfig {
  const fallback = createTrailingStopLossConfig()
  return {
    enabled: config?.enabled ?? fallback.enabled,
    entry_price: config?.entry_price ?? fallback.entry_price,
    entry_date: config?.entry_date || fallback.entry_date,
    highest_price: config?.highest_price ?? fallback.highest_price,
    highest_price_date: config?.highest_price_date || fallback.highest_price_date,
    trail_pct: config?.trail_pct ?? fallback.trail_pct,
    note: config?.note || '',
    last_triggered_date: config?.last_triggered_date || '',
  }
}

function getStockConfig(strategyType: string, tsCode: string): StrategyStockConfig | null {
  const params = getSubscription(strategyType)?.params as Record<string, unknown> | undefined
  const stockConfigs = params?.stock_configs as Record<string, StrategyStockConfig> | undefined
  return stockConfigs?.[tsCode] || null
}

function getStockConfigSummary(strategyType: string, tsCode: string): string {
  const config = getStockConfig(strategyType, tsCode)
  if (!config) {
    if (isMaBuyStrategy(strategyType)) {
      return '使用默认均线配置'
    }
    if (isFixedStopLossStrategy(strategyType)) {
      return '未初始化固定止损'
    }
    if (isTrailingStopLossStrategy(strategyType)) {
      return '未初始化移动止损'
    }
    return '未配置撑压线'
  }

  if (isMaBuyStrategy(strategyType)) {
    const maPeriod = Number(config.ma_period || 0)
    const touchRange = Number(config.touch_range || 0)
    const stablePeriods = Number(config.stable_periods || 0)
    if (!maPeriod || !touchRange || !stablePeriods) {
      return '均线低吸配置未完整'
    }
    return `MA${maPeriod} / 触及 ${touchRange.toFixed(2)}% / 企稳 ${stablePeriods} 次`
  }

  if (isFixedStopLossStrategy(strategyType)) {
    if (!config.reference_price || !config.stop_loss_pct) {
      return '止损基准未配置完整'
    }
    return `基准 ${Number(config.reference_price).toFixed(2)} / 止损 ${Number(config.stop_loss_pct).toFixed(2)}%`
  }

  if (isTrailingStopLossStrategy(strategyType)) {
    if (!config.highest_price || !config.trail_pct) {
      return '移动止损配置未完整'
    }
    return `最高 ${Number(config.highest_price).toFixed(2)} / 回撤 ${Number(config.trail_pct).toFixed(2)}%`
  }

  const parts: string[] = []
  if (config.support_enabled) {
    if (config.support_mode === 'horizontal' && config.support_price) {
      parts.push('支撑水平线')
    } else if ((config.support_points || []).length === 2 && (config.support_points || []).every(point => point.date)) {
      parts.push('支撑趋势线')
    }
  }
  if (config.resistance_enabled) {
    if (config.resistance_mode === 'horizontal' && config.resistance_price) {
      parts.push('压力水平线')
    } else if ((config.resistance_points || []).length === 2 && (config.resistance_points || []).every(point => point.date)) {
      parts.push('压力趋势线')
    }
  }

  if (parts.length === 0) {
    return '点位未配置完整'
  }

  return `${parts.join(' / ')} 已配置`
}

function getStockConfigActionLabel(strategyType: string): string {
  if (isMaBuyStrategy(strategyType)) {
    return '配置均线低吸'
  }
  if (isFixedStopLossStrategy(strategyType)) {
    return '配置固定止损'
  }
  if (isTrailingStopLossStrategy(strategyType)) {
    return '配置移动止损'
  }
  return '配置撑压线'
}

function createDialogStockConfig(strategyType: string, config?: Partial<StrategyStockConfig>): StrategyStockConfig {
  if (isMaBuyStrategy(strategyType)) {
    return cloneMABuyConfig(config)
  }
  if (isFixedStopLossStrategy(strategyType)) {
    return cloneFixedStopLossConfig(config)
  }
  if (isTrailingStopLossStrategy(strategyType)) {
    return cloneTrailingStopLossConfig(config)
  }
  return cloneStockConfig(config)
}

function createTransitionRule(): StrategyTransitionRule {
  const defaultPool = availablePools.value[0]
  return {
    rule_id: crypto.randomUUID().replace(/-/g, ''),
    enabled: true,
    target_pool_id: defaultPool?.pool_id || '',
    target_pool_name: defaultPool?.name || '',
    source_pool_ids: [],
    source_pool_names: [],
    mode: 'move',
    cooldown_days: 1,
    note: '',
  }
}

function cloneTransitionRule(rule?: Partial<StrategyTransitionRule>): StrategyTransitionRule {
  return {
    rule_id: rule?.rule_id || crypto.randomUUID().replace(/-/g, ''),
    enabled: rule?.enabled ?? true,
    target_pool_id: rule?.target_pool_id || '',
    target_pool_name: rule?.target_pool_name || '',
    source_pool_ids: [...(rule?.source_pool_ids || [])],
    source_pool_names: [...(rule?.source_pool_names || [])],
    mode: rule?.mode === 'copy' ? 'copy' : 'move',
    cooldown_days: Number(rule?.cooldown_days || 1),
    note: rule?.note || '',
  }
}

function getTransitionRules(strategyType: string): StrategyTransitionRule[] {
  const params = getSubscription(strategyType)?.params as Record<string, unknown> | undefined
  const rules = params?.transition_rules
  if (!Array.isArray(rules)) {
    return []
  }
  return rules.map((rule) => cloneTransitionRule(rule as Partial<StrategyTransitionRule>))
}

function getTransitionSummary(strategyType: string): string {
  const rules = getTransitionRules(strategyType).filter(rule => rule.enabled && rule.target_pool_name)
  if (rules.length === 0) {
    return '未配置自动流转'
  }
  const poolNames = rules.map(rule => rule.target_pool_name || rule.target_pool_id).filter(Boolean)
  const preview = poolNames.slice(0, 2).join('、')
  return rules.length > 2 ? `${preview} 等 ${rules.length} 条规则` : preview
}

/** 打开添加个股弹窗 */
function openAddStockDialog(strategyType: string): void {
  currentStrategyType.value = strategyType
  selectedStock.value = ''
  stockOptions.value = []
  addStockDialogVisible.value = true
}

/** 搜索股票 (远程) */
async function searchStocks(query: string): Promise<void> {
  if (!query || query.length < 1) {
    stockOptions.value = []
    return
  }
  
  stockSearchLoading.value = true
  try {
    stockOptions.value = await stockApi.searchStocks(query, 10)
  } catch (error) {
    console.error('搜索股票失败:', error)
    stockOptions.value = []
  } finally {
    stockSearchLoading.value = false
  }
}

/** 添加个股到策略 */
async function addStockToStrategy(): Promise<void> {
  if (!currentStrategyType.value || !selectedStock.value) {
    ElMessage.warning('请选择股票')
    return
  }
  
  addingStock.value = true
  try {
    const selected = stockOptions.value.find(stock => stock.ts_code === selectedStock.value)
    const response = await subscriptionApi.addStockToStrategy(
      currentStrategyType.value,
      selectedStock.value
    )
    
    if (response.success) {
      // 重新加载订阅以获取最新的 watch_list_info
      await loadSubscriptions()
      ElMessage.success(response.message)
      addStockDialogVisible.value = false
    } else {
      ElMessage.warning(response.message)
    }
    if (isPerStockConfigStrategy(currentStrategyType.value)) {
      addStockDialogVisible.value = false
      openStockConfigDialog(
        currentStrategyType.value,
        selected?.name || selectedStock.value,
        selectedStock.value
      )
    }
  } catch (error) {
    ElMessage.error('添加失败')
    console.error(error)
  } finally {
    addingStock.value = false
  }
}

/** 移除个股 */
async function removeStock(strategyType: string, stockName: string, tsCode: string): Promise<void> {
  try {
    const response = await subscriptionApi.removeStockFromStrategy(
      strategyType,
      tsCode
    )
    
    if (response.success) {
      // 重新加载订阅以获取最新的 watch_list_info
      await loadSubscriptions()
      ElMessage.success(`已移除 ${stockName}`)
    }
  } catch (error) {
    ElMessage.error('移除失败')
    console.error(error)
  }
}

/** 切换展开/收起列表 */
function toggleExpand(strategyType: string): void {
  if (expandedLists.value.has(strategyType)) {
    expandedLists.value.delete(strategyType)
  } else {
    expandedLists.value.add(strategyType)
  }
}

// ==================== 管理员功能 ====================

/** 打开编辑参数弹窗（管理员） */
async function ensurePoolsLoaded(): Promise<void> {
  if (availablePools.value.length > 0) return
  poolLoading.value = true
  try {
    const response = await stockPickerApi.listPools()
    availablePools.value = response.items || []
  } finally {
    poolLoading.value = false
  }
}

async function ensureTradeReviewGroupsLoaded(): Promise<void> {
  if (tradeReviewGroups.value.length > 0) return
  tradeReviewGroupLoading.value = true
  try {
    const response = await tradeReviewApi.listGroups()
    tradeReviewGroups.value = response.items || []
  } finally {
    tradeReviewGroupLoading.value = false
  }
}

/** 打开编辑参数弹窗（管理员） */
async function openEditParamsDialog(strategyType: string): Promise<void> {
  const sub = getSubscription(strategyType)
  if (!sub) return
  
  await ensureTradeReviewGroupsLoaded()
  editingStrategyType.value = strategyType
  // 复制当前参数
  editingParams.value = { ...sub.params }
  editParamsDialogVisible.value = true
}

async function openTransitionRulesDialog(strategyType: string): Promise<void> {
  const sub = getSubscription(strategyType)
  if (!sub) return

  await ensurePoolsLoaded()
  editingTransitionStrategyType.value = strategyType
  editingTransitionRules.value = getTransitionRules(strategyType)
  transitionRulesDialogVisible.value = true
}

/** 保存策略参数（管理员） */
async function saveParams(): Promise<void> {
  if (!userStore.isAdmin) {
    ElMessage.warning('需要管理员权限')
    return
  }
  
  savingParams.value = true
  try {
    await subscriptionApi.updateStrategyParams(
      editingStrategyType.value,
      editingParams.value
    )
    
    // 更新本地状态
    const sub = getSubscription(editingStrategyType.value)
    if (sub) {
      sub.params = { ...editingParams.value }
    }
    
    ElMessage.success('参数已保存')
    editParamsDialogVisible.value = false
  } catch (error) {
    ElMessage.error('保存失败，请检查管理员权限')
    console.error(error)
  } finally {
    savingParams.value = false
  }
}

function openStockConfigDialog(strategyType: string, stockName: string, tsCode: string): void {
  editingStockStrategyType.value = strategyType
  editingStockTsCode.value = tsCode
  editingStockName.value = stockName
  editingStockConfig.value = createDialogStockConfig(strategyType, getStockConfig(strategyType, tsCode) || undefined)
  stockConfigDialogVisible.value = true
}

function normalizePoint(point: StrategyStockPoint): StrategyStockPoint {
  return {
    date: point.date,
    price: point.price === null || point.price === undefined || point.price === 0 ? null : Number(point.price),
  }
}

async function saveTransitionRules(): Promise<void> {
  if (!userStore.isAdmin) {
    ElMessage.warning('需要管理员权限')
    return
  }

  const sub = getSubscription(editingTransitionStrategyType.value)
  if (!sub) return

  savingParams.value = true
  try {
    const nextParams = {
      ...sub.params,
      transition_rules: editingTransitionRules.value.map((rule) => {
        const targetPool = availablePools.value.find((pool) => pool.pool_id === rule.target_pool_id)
        const sourcePools = availablePools.value.filter((pool) => rule.source_pool_ids.includes(pool.pool_id))
        return {
          rule_id: rule.rule_id,
          enabled: rule.enabled,
          target_pool_id: rule.target_pool_id,
          target_pool_name: targetPool?.name || rule.target_pool_name || '',
          source_pool_ids: rule.source_pool_ids,
          source_pool_names: sourcePools.map((pool) => pool.name),
          mode: rule.mode,
          cooldown_days: Math.max(1, Number(rule.cooldown_days || 1)),
          note: rule.note || '',
        }
      }),
    }

    await subscriptionApi.updateStrategyParams(
      editingTransitionStrategyType.value,
      nextParams
    )

    sub.params = { ...nextParams }
    ElMessage.success('自动流转规则已保存')
    transitionRulesDialogVisible.value = false
  } catch (error) {
    ElMessage.error('保存自动流转规则失败')
    console.error(error)
  } finally {
    savingParams.value = false
  }
}

function addTransitionRule(): void {
  editingTransitionRules.value = [...editingTransitionRules.value, createTransitionRule()]
}

function removeTransitionRule(ruleId: string): void {
  editingTransitionRules.value = editingTransitionRules.value.filter((rule) => rule.rule_id !== ruleId)
}

function getBooleanParamValue(key: string, defaultValue: boolean | string | number): boolean {
  const value = editingParams.value[key]
  if (typeof value === 'boolean') {
    return value
  }
  if (typeof defaultValue === 'boolean') {
    return defaultValue
  }
  return Boolean(value)
}

function getNumberParamValue(key: string, defaultValue: boolean | string | number): number {
  const value = editingParams.value[key]
  if (typeof value === 'number') {
    return value
  }
  if (typeof defaultValue === 'number') {
    return defaultValue
  }
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function getStringParamValue(key: string, defaultValue: boolean | string | number): string {
  const value = editingParams.value[key]
  if (typeof value === 'string') {
    return value
  }
  if (typeof defaultValue === 'string') {
    return defaultValue
  }
  return value == null ? '' : String(value)
}

function setEditingParam(key: string, value: boolean | number | string | undefined): void {
  editingParams.value[key] = value ?? null
}

async function saveStockConfig(): Promise<void> {
  if (!editingStockStrategyType.value || !editingStockTsCode.value) {
    return
  }

  let payload: StrategyStockConfig
  if (isMaBuyStrategy(editingStockStrategyType.value)) {
    if (!editingStockConfig.value.ma_period || !editingStockConfig.value.touch_range || !editingStockConfig.value.stable_periods) {
      ElMessage.warning('请至少填写均线周期、触及范围和企稳周期')
      return
    }
    payload = {
      enabled: editingStockConfig.value.enabled ?? true,
      ma_period: Number(editingStockConfig.value.ma_period),
      touch_range: Number(editingStockConfig.value.touch_range),
      stable_periods: Number(editingStockConfig.value.stable_periods),
      note: editingStockConfig.value.note || '',
      last_triggered_date: editingStockConfig.value.last_triggered_date || '',
    }
  } else if (isSupportResistanceStrategy(editingStockStrategyType.value)) {
    if (!editingStockConfig.value.support_enabled && !editingStockConfig.value.resistance_enabled) {
      ElMessage.warning('至少需要启用支撑线或压力线中的一条')
      return
    }
    payload = {
      trend_type: editingStockConfig.value.trend_type,
      support_enabled: editingStockConfig.value.support_enabled,
      resistance_enabled: editingStockConfig.value.resistance_enabled,
      support_mode: editingStockConfig.value.support_mode || 'trend',
      resistance_mode: editingStockConfig.value.resistance_mode || 'trend',
      support_points: editingStockConfig.value.support_mode === 'trend'
        ? (editingStockConfig.value.support_points || []).map(normalizePoint)
        : [],
      resistance_points: editingStockConfig.value.resistance_mode === 'trend'
        ? (editingStockConfig.value.resistance_points || []).map(normalizePoint)
        : [],
      support_price: editingStockConfig.value.support_mode === 'horizontal'
        ? (editingStockConfig.value.support_price == null ? null : Number(editingStockConfig.value.support_price))
        : null,
      resistance_price: editingStockConfig.value.resistance_mode === 'horizontal'
        ? (editingStockConfig.value.resistance_price == null ? null : Number(editingStockConfig.value.resistance_price))
        : null,
      note: editingStockConfig.value.note || '',
    }
  } else if (isFixedStopLossStrategy(editingStockStrategyType.value)) {
    if (!editingStockConfig.value.reference_price || !editingStockConfig.value.stop_loss_pct) {
      ElMessage.warning('请至少填写参考价格和止损比例')
      return
    }
    payload = {
      enabled: editingStockConfig.value.enabled ?? true,
      reference_price: Number(editingStockConfig.value.reference_price),
      reference_date: editingStockConfig.value.reference_date || '',
      stop_loss_pct: Number(editingStockConfig.value.stop_loss_pct),
      note: editingStockConfig.value.note || '',
      last_triggered_date: editingStockConfig.value.last_triggered_date || '',
    }
  } else {
    if (!editingStockConfig.value.entry_price || !editingStockConfig.value.trail_pct) {
      ElMessage.warning('请至少填写入场价格和回撤比例')
      return
    }
    payload = {
      enabled: editingStockConfig.value.enabled ?? true,
      entry_price: Number(editingStockConfig.value.entry_price),
      entry_date: editingStockConfig.value.entry_date || '',
      highest_price: editingStockConfig.value.highest_price == null ? null : Number(editingStockConfig.value.highest_price),
      highest_price_date: editingStockConfig.value.highest_price_date || '',
      trail_pct: Number(editingStockConfig.value.trail_pct),
      note: editingStockConfig.value.note || '',
      last_triggered_date: editingStockConfig.value.last_triggered_date || '',
    }
  }

  savingStockConfig.value = true
  try {
    await subscriptionApi.updateStockConfig(
      editingStockStrategyType.value,
      editingStockTsCode.value,
      payload
    )
    await loadSubscriptions()
    ElMessage.success(`${getStockConfigActionLabel(editingStockStrategyType.value)}已保存`)
    stockConfigDialogVisible.value = false
  } catch (error) {
    ElMessage.error(`${getStockConfigActionLabel(editingStockStrategyType.value)}失败`)
    console.error(error)
  } finally {
    savingStockConfig.value = false
  }
}

/** 切换策略激活状态（管理员） */
async function toggleSubscription(strategyType: string): Promise<void> {
  if (!userStore.isAdmin) {
    ElMessage.warning('需要管理员权限')
    return
  }
  
  try {
    const response = await subscriptionApi.toggleSubscription(strategyType)
    // 更新本地状态
    const sub = getSubscription(strategyType)
    if (sub) {
      sub.is_active = response.is_active
    }
    ElMessage.success(response.message)
  } catch (error) {
    ElMessage.error('操作失败')
    console.error(error)
  }
}

// ==================== 生命周期 ====================

onMounted(async () => {
  await loadStrategyTypes()
  await loadSubscriptions()
})
</script>

<template>
  <div class="strategy-list-view">
    <!-- 页面标题 -->
    <header class="page-header">
      <div class="header-content">
        <h1 class="page-title">策略监听</h1>
        <p class="page-subtitle">选择策略，添加想要监听的股票</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" @click="loadSubscriptions" :loading="loading">
          刷新
        </el-button>
        <el-tag v-if="userStore.isAdmin" type="warning" effect="dark">
          管理员
        </el-tag>
      </div>
    </header>

    <section v-if="!loading" class="view-toolbar">
      <div class="toolbar-stats">
        <div class="toolbar-stat-card">
          <span class="toolbar-stat-label">策略总数</span>
          <strong class="toolbar-stat-value">{{ availableStrategyTypes.length }}</strong>
        </div>
        <div class="toolbar-stat-card">
          <span class="toolbar-stat-label">已启用</span>
          <strong class="toolbar-stat-value">
            {{ availableStrategyTypes.filter((st) => isStrategyActive(st.type)).length }}
          </strong>
        </div>
        <div class="toolbar-stat-card">
          <span class="toolbar-stat-label">有监听股票</span>
          <strong class="toolbar-stat-value">
            {{ availableStrategyTypes.filter((st) => getWatchCount(st.type) > 0).length }}
          </strong>
        </div>
        <div class="toolbar-stat-card">
          <span class="toolbar-stat-label">配置流转</span>
          <strong class="toolbar-stat-value">
            {{ availableStrategyTypes.filter((st) => getEnabledTransitionRuleCount(st.type) > 0).length }}
          </strong>
        </div>
      </div>
      <el-radio-group v-model="viewMode" size="small" class="view-mode-switch">
        <el-radio-button
          v-for="option in viewModeOptions"
          :key="option.value"
          :label="option.value"
        >
          {{ option.label }}
        </el-radio-button>
      </el-radio-group>
    </section>
    
    <!-- 紧凑卡片 -->
    <div v-if="!loading && viewMode === 'compact'" class="compact-strategy-list">
      <article
        v-for="st in availableStrategyTypes"
        :key="`compact-${st.type}`"
        class="compact-strategy-card"
        :class="{ 'is-inactive': !isStrategyActive(st.type) }"
      >
        <div class="compact-card-main">
          <div class="compact-card-top">
            <div class="compact-card-title-block">
              <h3 class="compact-card-title">{{ st.name }}</h3>
              <p class="compact-card-desc">{{ st.description }}</p>
            </div>
            <div class="compact-card-status">
              <div
                class="status-indicator"
                :class="isStrategyActive(st.type) ? 'active' : 'inactive'"
              >
                <span class="status-dot"></span>
                <span class="status-text">
                  {{ isStrategyActive(st.type) ? '运行中' : '已停用' }}
                </span>
              </div>
              <el-tag size="small" effect="plain">实际监听 {{ getWatchCount(st.type) }} 只</el-tag>
            </div>
          </div>

          <div class="compact-summary-grid">
            <div class="compact-summary-item">
              <span class="compact-summary-label">监听基础配置</span>
              <span class="compact-summary-value">{{ getCompactBasicSummary(st.type) }}</span>
            </div>
            <div class="compact-summary-item">
              <span class="compact-summary-label">策略参数</span>
              <span class="compact-summary-value">{{ getStrategyParamSummary(st.type) }}</span>
            </div>
            <div class="compact-summary-item">
              <span class="compact-summary-label">监听范围</span>
              <span class="compact-summary-value">{{ getWatchCountSummary(st.type) }}</span>
            </div>
            <div class="compact-summary-item">
              <span class="compact-summary-label">自动流转</span>
              <span class="compact-summary-value">{{ getTransitionSummary(st.type) }}</span>
            </div>
          </div>
        </div>

        <div class="compact-card-actions">
          <el-button type="primary" size="small" plain @click="openAddStockDialog(st.type)">
            添加股票
          </el-button>
          <el-button
            v-if="userStore.isAdmin"
            type="primary"
            size="small"
            plain
            @click="openEditParamsDialog(st.type)"
          >
            编辑参数
          </el-button>
          <el-button
            v-if="userStore.isAdmin"
            type="primary"
            size="small"
            plain
            @click="openTransitionRulesDialog(st.type)"
          >
            编辑流转
          </el-button>
          <el-button
            v-if="userStore.isAdmin"
            size="small"
            :type="isStrategyActive(st.type) ? 'warning' : 'success'"
            @click="toggleSubscription(st.type)"
          >
            {{ isStrategyActive(st.type) ? '停用' : '启用' }}
          </el-button>
        </div>
      </article>
    </div>

    <!-- 详细卡片 -->
    <div v-else-if="!loading && viewMode === 'detail'" class="strategies-grid">
      <article
        v-for="st in availableStrategyTypes"
        :key="st.type"
        class="strategy-card"
        :class="{ 'is-inactive': getSubscription(st.type)?.is_active === false }"
      >
        <!-- 卡片头部 -->
        <div class="card-header">
          <div class="header-left">
            <h3 class="strategy-name">{{ st.name }}</h3>
          </div>
          <div class="header-right">
            <!-- 状态指示器 -->
            <div 
              class="status-indicator" 
              :class="getSubscription(st.type)?.is_active !== false ? 'active' : 'inactive'"
            >
              <span class="status-dot"></span>
              <span class="status-text">
                {{ getSubscription(st.type)?.is_active !== false ? '运行中' : '已停用' }}
              </span>
            </div>
            <!-- 管理员操作 -->
            <el-button 
              v-if="userStore.isAdmin"
              size="small"
              :type="getSubscription(st.type)?.is_active !== false ? 'warning' : 'success'"
              @click="toggleSubscription(st.type)"
            >
              {{ getSubscription(st.type)?.is_active !== false ? '停用' : '启用' }}
            </el-button>
          </div>
        </div>
        
        <!-- 策略描述 -->
        <p class="strategy-description">{{ st.description }}</p>
        
        <!-- 卡片主体 -->
        <div class="card-body">
          <div class="params-section">
            <div class="section-header">
              <h4 class="section-title">监听基础配置</h4>
            </div>
            <div class="params-grid">
              <div class="param-item">
                <span class="param-label">监听频率</span>
                <span class="param-value">
                  {{ getStrategyMeta(st.type)?.schedule_label || '盘中轮询' }}
                </span>
              </div>
              <div
                v-for="param in getBasicParamDefs(st.type)"
                :key="`basic-${param.key}`"
                class="param-item"
              >
                <span class="param-label">{{ param.label }}</span>
                <span class="param-value">
                  {{ getParamDisplayValue(st.type, param.key, getSubscription(st.type)?.params[param.key] ?? param.default) }}
                </span>
              </div>
            </div>
          </div>

          <!-- 策略参数 -->
          <div class="params-section">
            <div class="section-header">
              <h4 class="section-title">策略参数</h4>
              <el-button
                v-if="userStore.isAdmin"
                type="primary"
                size="small"
                :icon="Edit"
                plain
                @click="openEditParamsDialog(st.type)"
              >
                编辑
              </el-button>
            </div>
            <div class="params-grid">
              <div 
                v-for="param in getStrategyParamDefs(st.type)" 
                :key="param.key"
                class="param-item"
              >
                <span class="param-label">{{ param.label }}</span>
                <span class="param-value">
                  {{ getParamDisplayValue(st.type, param.key, getSubscription(st.type)?.params[param.key] ?? param.default) }}
                </span>
              </div>
            </div>
          </div>

          <div class="params-section transition-section">
            <div class="section-header">
              <h4 class="section-title">自动流转</h4>
              <el-button
                v-if="userStore.isAdmin"
                type="primary"
                size="small"
                :icon="Edit"
                plain
                @click="openTransitionRulesDialog(st.type)"
              >
                编辑
              </el-button>
            </div>
            <div class="param-item transition-summary-item">
              <span class="param-label">规则概览</span>
              <span class="param-value transition-summary-text">
                {{ getTransitionSummary(st.type) }}
              </span>
            </div>
          </div>
          
          <!-- 监听股票 -->
          <div class="stocks-section">
            <div class="section-header">
              <h4 class="section-title">
                监听股票
                <el-badge 
                  :value="getWatchCount(st.type)" 
                  :max="99"
                  class="stock-count-badge"
                />
              </h4>
              <el-button 
                type="primary" 
                size="small" 
                :icon="Plus"
                @click="openAddStockDialog(st.type)"
              >
                添加
              </el-button>
            </div>
            
            <!-- 股票列表 -->
            <div 
              v-if="getSubscription(st.type)?.watch_list_info?.length"
              :class="isPerStockConfigStrategy(st.type) ? 'stock-config-list' : 'stock-tags'"
            >
              <div class="watch-count-hint">
                {{ getWatchCountSummary(st.type) }}
              </div>
              <template v-if="isPerStockConfigStrategy(st.type)">
                <div
                  v-for="stock in getDisplayStockInfos(getSubscription(st.type)!)"
                  :key="stock.ts_code"
                  class="stock-config-item"
                >
                  <div class="stock-config-main">
                    <div class="stock-config-title-row">
                      <span class="stock-config-name">{{ stock.name }}</span>
                      <span class="stock-config-code">{{ stock.ts_code }}</span>
                    </div>
                    <span class="stock-config-summary">
                      {{ getStockConfigSummary(st.type, stock.ts_code) }}
                    </span>
                  </div>
                  <div class="stock-config-actions">
                    <el-button
                      link
                      type="primary"
                      @click="openStockConfigDialog(st.type, stock.name, stock.ts_code)"
                    >
                      {{ getStockConfigActionLabel(st.type) }}
                    </el-button>
                    <el-button
                      link
                      type="danger"
                      @click="removeStock(st.type, stock.name, stock.ts_code)"
                    >
                      移除
                    </el-button>
                  </div>
                </div>
              </template>
              <template v-else>
                <el-tag
                  v-for="stock in getDisplayStockInfos(getSubscription(st.type)!)"
                  :key="stock.ts_code"
                  closable
                  size="small"
                  class="stock-tag"
                  @close="removeStock(st.type, stock.name, stock.ts_code)"
                >
                  {{ stock.name }}
                </el-tag>
              </template>
              
              <!-- 展开/收起 -->
              <el-button
                v-if="(getSubscription(st.type)?.watch_list_info?.length || 0) > 5"
                link
                type="primary"
                size="small"
                @click="toggleExpand(st.type)"
              >
                {{ expandedLists.has(st.type) ? '收起' : `展开全部 (${getSubscription(st.type)?.watch_list_info?.length})` }}
              </el-button>
            </div>
            
            <!-- 空状态 -->
            <div v-else class="empty-stocks">
              <span class="empty-text">暂无监听股票</span>
              <span class="empty-hint">点击"添加"按钮开始监听</span>
            </div>
          </div>
        </div>
      </article>
    </div>

    <!-- 表格模式 -->
    <div v-else-if="!loading && viewMode === 'table'" class="strategy-table-wrapper">
      <el-table :data="availableStrategyTypes" border stripe class="strategy-table">
        <el-table-column label="策略" min-width="180">
          <template #default="{ row }">
            <div class="table-strategy-cell">
              <strong class="table-strategy-name">{{ row.name }}</strong>
              <span class="table-strategy-desc">{{ row.description }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="isStrategyActive(row.type) ? 'success' : 'info'" size="small">
              {{ isStrategyActive(row.type) ? '运行中' : '已停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="监听基础配置" min-width="240">
          <template #default="{ row }">
            {{ getCompactBasicSummary(row.type) }}
          </template>
        </el-table-column>
        <el-table-column label="策略参数" min-width="240">
          <template #default="{ row }">
            {{ getStrategyParamSummary(row.type) }}
          </template>
        </el-table-column>
        <el-table-column label="监听股票" width="100" align="center">
          <template #default="{ row }">
            {{ getWatchCount(row.type) }}
          </template>
        </el-table-column>
        <el-table-column label="自动流转" min-width="180">
          <template #default="{ row }">
            {{ getTransitionSummary(row.type) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="260" fixed="right">
          <template #default="{ row }">
            <div class="table-action-group">
              <el-button size="small" plain type="primary" @click="openAddStockDialog(row.type)">
                添加股票
              </el-button>
              <el-button
                v-if="userStore.isAdmin"
                size="small"
                plain
                type="primary"
                @click="openEditParamsDialog(row.type)"
              >
                编辑参数
              </el-button>
              <el-button
                v-if="userStore.isAdmin"
                size="small"
                plain
                type="primary"
                @click="openTransitionRulesDialog(row.type)"
              >
                编辑流转
              </el-button>
              <el-button
                v-if="userStore.isAdmin"
                size="small"
                :type="isStrategyActive(row.type) ? 'warning' : 'success'"
                @click="toggleSubscription(row.type)"
              >
                {{ isStrategyActive(row.type) ? '停用' : '启用' }}
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>
    
    <!-- 加载状态 -->
    <div v-else class="loading-state">
      <el-skeleton :rows="3" animated />
    </div>
    
    <!-- 添加个股弹窗 -->
    <el-dialog
      v-model="addStockDialogVisible"
      title="添加监听股票"
      width="400px"
      :close-on-click-modal="false"
    >
      <div class="add-stock-form">
        <p class="form-hint">
          搜索并选择要添加到 
          <strong>{{ getStrategyName(currentStrategyType) }}</strong> 
          策略的股票
        </p>
        
        <el-select
          v-model="selectedStock"
          filterable
          remote
          reserve-keyword
          placeholder="输入股票代码或名称搜索"
          :remote-method="searchStocks"
          :loading="stockSearchLoading"
          class="stock-select"
          size="large"
        >
          <el-option
            v-for="stock in stockOptions"
            :key="stock.ts_code"
            :label="`${stock.name} (${stock.ts_code})`"
            :value="stock.ts_code"
          >
            <div class="stock-option">
              <span class="stock-name">{{ stock.name }}</span>
              <span class="stock-code">{{ stock.ts_code }}</span>
            </div>
          </el-option>
        </el-select>
      </div>
      
      <template #footer>
        <el-button @click="addStockDialogVisible = false">取消</el-button>
        <el-button 
          type="primary" 
          :loading="addingStock"
          :disabled="!selectedStock"
          @click="addStockToStrategy"
        >
          确认添加
        </el-button>
      </template>
    </el-dialog>

    <!-- 单股撑压线配置弹窗 -->
    <el-dialog
      v-model="stockConfigDialogVisible"
      :title="getStockConfigActionLabel(editingStockStrategyType)"
      width="720px"
      :close-on-click-modal="false"
    >
      <div class="stock-config-dialog">
        <p class="form-hint mb-4">
          为 <strong>{{ editingStockName }}</strong>
          <span class="stock-code-inline">({{ editingStockTsCode }})</span>
          <template v-if="isMaBuyStrategy(editingStockStrategyType)">
            配置这只股票自己的均线低吸参数；如果不单独配置，会继续使用策略默认参数。
          </template>
          <template v-else-if="isSupportResistanceStrategy(editingStockStrategyType)">
            配置支撑线与压力线；可选水平线或斜线。斜线模式下价格留空时，会自动取对应日期 K 线的最低价或最高价。
          </template>
          <template v-else-if="isFixedStopLossStrategy(editingStockStrategyType)">
            配置固定止损基准。若参考日期留空，后端会继续使用当前已保存的加入基准。
          </template>
          <template v-else>
            配置移动止损基准与回撤比例。最高价默认会在监听运行中持续自动抬升并持久化。
          </template>
        </p>

        <div v-if="isMaBuyStrategy(editingStockStrategyType)" class="params-form-grid transition-grid">
          <div class="param-form-item">
            <label class="param-form-label">是否启用</label>
            <el-switch v-model="editingStockConfig.enabled" active-text="启用" inactive-text="关闭" />
          </div>

          <div class="param-form-item">
            <label class="param-form-label">均线周期</label>
            <el-input-number
              v-model="editingStockConfig.ma_period"
              :min="2"
              :max="250"
              :step="1"
              controls-position="right"
            />
          </div>

          <div class="param-form-item">
            <label class="param-form-label">触及范围 (%)</label>
            <el-input-number
              v-model="editingStockConfig.touch_range"
              :min="0.01"
              :precision="2"
              :step="0.1"
              controls-position="right"
            />
          </div>

          <div class="param-form-item">
            <label class="param-form-label">企稳周期数</label>
            <el-input-number
              v-model="editingStockConfig.stable_periods"
              :min="1"
              :max="20"
              :step="1"
              controls-position="right"
            />
          </div>
        </div>

        <div v-if="isSupportResistanceStrategy(editingStockStrategyType)" class="stock-config-form-grid">
          <div class="param-form-item">
            <label class="param-form-label">趋势类型</label>
            <el-select v-model="editingStockConfig.trend_type">
              <el-option
                v-for="option in trendTypeOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
          </div>

          <div class="param-form-item">
            <label class="param-form-label">支撑线</label>
            <el-switch v-model="editingStockConfig.support_enabled" active-text="启用" inactive-text="关闭" />
          </div>

          <div class="param-form-item">
            <label class="param-form-label">压力线</label>
            <el-switch v-model="editingStockConfig.resistance_enabled" active-text="启用" inactive-text="关闭" />
          </div>
        </div>

        <div v-if="isSupportResistanceStrategy(editingStockStrategyType) && editingStockConfig.support_enabled" class="line-config-card">
          <div class="line-config-header">
            <h4>支撑线点位</h4>
            <span>可配置水平支撑价，或用两个点位画支撑趋势线</span>
          </div>
          <div class="param-form-item line-mode-item">
            <label class="param-form-label">支撑线类型</label>
            <el-radio-group v-model="editingStockConfig.support_mode">
              <el-radio-button
                v-for="option in lineModeOptions"
                :key="`support-${option.value}`"
                :label="option.value"
              >
                {{ option.label }}
              </el-radio-button>
            </el-radio-group>
          </div>
          <div v-if="editingStockConfig.support_mode === 'horizontal'" class="param-form-item line-price-item">
            <label class="param-form-label">支撑价</label>
            <el-input-number
              v-model="editingStockConfig.support_price"
              :min="0"
              :precision="2"
              :step="0.01"
              controls-position="right"
              placeholder="输入水平支撑价"
            />
          </div>
          <div v-if="editingStockConfig.support_mode === 'trend'" class="line-points-grid">
            <div
              v-for="(point, index) in editingStockConfig.support_points"
              :key="`support-${index}`"
              class="line-point-item"
            >
              <label class="param-form-label">支撑点 {{ index + 1 }}</label>
              <el-date-picker
                v-model="point.date"
                type="date"
                value-format="YYYYMMDD"
                format="YYYY-MM-DD"
                placeholder="选择日期"
              />
              <el-input-number
                v-model="point.price"
                :min="0"
                :precision="2"
                :step="0.01"
                controls-position="right"
                placeholder="留空自动取低点"
              />
            </div>
          </div>
        </div>

        <div v-if="isSupportResistanceStrategy(editingStockStrategyType) && editingStockConfig.resistance_enabled" class="line-config-card">
          <div class="line-config-header">
            <h4>压力线点位</h4>
            <span>可配置水平压力价，或用两个点位画压力趋势线</span>
          </div>
          <div class="param-form-item line-mode-item">
            <label class="param-form-label">压力线类型</label>
            <el-radio-group v-model="editingStockConfig.resistance_mode">
              <el-radio-button
                v-for="option in lineModeOptions"
                :key="`resistance-${option.value}`"
                :label="option.value"
              >
                {{ option.label }}
              </el-radio-button>
            </el-radio-group>
          </div>
          <div v-if="editingStockConfig.resistance_mode === 'horizontal'" class="param-form-item line-price-item">
            <label class="param-form-label">压力价</label>
            <el-input-number
              v-model="editingStockConfig.resistance_price"
              :min="0"
              :precision="2"
              :step="0.01"
              controls-position="right"
              placeholder="输入水平压力价"
            />
          </div>
          <div v-if="editingStockConfig.resistance_mode === 'trend'" class="line-points-grid">
            <div
              v-for="(point, index) in editingStockConfig.resistance_points"
              :key="`resistance-${index}`"
              class="line-point-item"
            >
              <label class="param-form-label">压力点 {{ index + 1 }}</label>
              <el-date-picker
                v-model="point.date"
                type="date"
                value-format="YYYYMMDD"
                format="YYYY-MM-DD"
                placeholder="选择日期"
              />
              <el-input-number
                v-model="point.price"
                :min="0"
                :precision="2"
                :step="0.01"
                controls-position="right"
                placeholder="留空自动取高点"
              />
            </div>
          </div>
        </div>

        <div v-if="isFixedStopLossStrategy(editingStockStrategyType)" class="params-form-grid transition-grid">
          <div class="param-form-item">
            <label class="param-form-label">是否启用</label>
            <el-switch v-model="editingStockConfig.enabled" active-text="启用" inactive-text="关闭" />
          </div>

          <div class="param-form-item">
            <label class="param-form-label">参考日期</label>
            <el-date-picker
              v-model="editingStockConfig.reference_date"
              type="date"
              value-format="YYYYMMDD"
              format="YYYY-MM-DD"
              placeholder="选择参考日期"
            />
          </div>

          <div class="param-form-item">
            <label class="param-form-label">参考价格</label>
            <el-input-number
              v-model="editingStockConfig.reference_price"
              :min="0"
              :precision="2"
              :step="0.01"
              controls-position="right"
            />
          </div>

          <div class="param-form-item">
            <label class="param-form-label">止损比例 (%)</label>
            <el-input-number
              v-model="editingStockConfig.stop_loss_pct"
              :min="0.01"
              :precision="2"
              :step="0.1"
              controls-position="right"
            />
          </div>
        </div>

        <div v-if="isTrailingStopLossStrategy(editingStockStrategyType)" class="params-form-grid transition-grid">
          <div class="param-form-item">
            <label class="param-form-label">是否启用</label>
            <el-switch v-model="editingStockConfig.enabled" active-text="启用" inactive-text="关闭" />
          </div>

          <div class="param-form-item">
            <label class="param-form-label">入场日期</label>
            <el-date-picker
              v-model="editingStockConfig.entry_date"
              type="date"
              value-format="YYYYMMDD"
              format="YYYY-MM-DD"
              placeholder="选择入场日期"
            />
          </div>

          <div class="param-form-item">
            <label class="param-form-label">入场价格</label>
            <el-input-number
              v-model="editingStockConfig.entry_price"
              :min="0"
              :precision="2"
              :step="0.01"
              controls-position="right"
            />
          </div>

          <div class="param-form-item">
            <label class="param-form-label">当前最高价</label>
            <el-input-number
              v-model="editingStockConfig.highest_price"
              :min="0"
              :precision="2"
              :step="0.01"
              controls-position="right"
            />
          </div>

          <div class="param-form-item">
            <label class="param-form-label">最高价日期</label>
            <el-date-picker
              v-model="editingStockConfig.highest_price_date"
              type="date"
              value-format="YYYYMMDD"
              format="YYYY-MM-DD"
              placeholder="选择最高价日期"
            />
          </div>

          <div class="param-form-item">
            <label class="param-form-label">回撤比例 (%)</label>
            <el-input-number
              v-model="editingStockConfig.trail_pct"
              :min="0.01"
              :precision="2"
              :step="0.1"
              controls-position="right"
            />
          </div>
        </div>

        <div class="param-form-item">
          <label class="param-form-label">备注</label>
          <el-input
            v-model="editingStockConfig.note"
            type="textarea"
            :rows="2"
            :placeholder="isMaBuyStrategy(editingStockStrategyType)
              ? '可选，记录这只股票为什么使用特殊均线'
              : isSupportResistanceStrategy(editingStockStrategyType)
                ? '可选，记录点位含义或趋势说明'
                : '可选，记录止损逻辑或建仓背景'"
          />
        </div>
      </div>

      <template #footer>
        <el-button @click="stockConfigDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="savingStockConfig"
          @click="saveStockConfig"
        >
          保存配置
        </el-button>
      </template>
    </el-dialog>
    
    <!-- 编辑参数弹窗（管理员） -->
    <el-dialog
      v-model="editParamsDialogVisible"
      title="编辑策略参数"
      width="450px"
      :close-on-click-modal="false"
    >
      <div class="edit-params-form">
        <p class="form-hint mb-4">
          修改 <strong>{{ getStrategyName(editingStrategyType) }}</strong> 的策略参数
        </p>
        
        <!-- 动态参数表单 -->
        <div class="params-form-grid">
        <div 
            v-for="param in getBasicParamDefs(editingStrategyType)"
            :key="`basic-edit-${param.key}`"
            class="param-form-item"
          >
            <label class="param-form-label">{{ param.label }}</label>

            <el-select
              v-if="param.type === 'string' && param.options?.length"
              :model-value="getStringParamValue(param.key, param.default)"
              @update:model-value="setEditingParam(param.key, $event)"
            >
              <el-option
                v-for="option in param.options"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>

            <el-switch
              v-else-if="param.type === 'boolean'"
              :model-value="getBooleanParamValue(param.key, param.default)"
              @update:model-value="setEditingParam(param.key, $event)"
              :active-text="'是'"
              :inactive-text="'否'"
            />
          </div>

          <div
            v-if="getStrategyParamDefs(editingStrategyType).length"
            class="param-form-section-label"
          >
            策略参数
          </div>

          <div 
            v-for="param in getStrategyParamDefs(editingStrategyType)"
            :key="param.key"
            class="param-form-item"
          >
            <label class="param-form-label">{{ param.label }}</label>
            
            <!-- 布尔类型 -->
            <el-switch
              v-if="param.type === 'boolean'"
              :model-value="getBooleanParamValue(param.key, param.default)"
              @update:model-value="setEditingParam(param.key, $event)"
              :active-text="'是'"
              :inactive-text="'否'"
            />

            <el-select
              v-else-if="param.key === 'position_group_id'"
              :model-value="getStringParamValue(param.key, param.default)"
              :loading="tradeReviewGroupLoading"
              placeholder="请选择交割单分组"
              @update:model-value="setEditingParam(param.key, $event)"
            >
              <el-option
                v-for="group in tradeReviewGroups"
                :key="group.group_id"
                :label="`${group.name} (${group.trade_record_count} 笔成交)`"
                :value="group.group_id"
              />
            </el-select>

            <el-select
              v-else-if="param.type === 'string' && param.options?.length"
              :model-value="getStringParamValue(param.key, param.default)"
              @update:model-value="setEditingParam(param.key, $event)"
            >
              <el-option
                v-for="option in param.options"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
            
            <!-- 数字类型 -->
            <el-input-number
              v-else-if="param.type === 'number' || param.type === 'float'"
              :model-value="getNumberParamValue(param.key, param.default)"
              @update:model-value="setEditingParam(param.key, $event)"
              :step="param.type === 'float' ? 0.01 : 1"
              :precision="param.type === 'float' ? 2 : 0"
              :min="0"
              size="default"
              controls-position="right"
            />

            <el-input
              v-else
              :model-value="getStringParamValue(param.key, param.default)"
              @update:model-value="setEditingParam(param.key, $event)"
            />
          </div>
        </div>

      </div>
      
      <template #footer>
        <el-button @click="editParamsDialogVisible = false">取消</el-button>
        <el-button 
          type="primary" 
          :loading="savingParams"
          @click="saveParams"
        >
          保存
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="transitionRulesDialogVisible"
      title="编辑自动流转规则"
      width="720px"
      :close-on-click-modal="false"
    >
      <div class="edit-params-form">
        <p class="form-hint mb-4">
          为 <strong>{{ getStrategyName(editingTransitionStrategyType) }}</strong> 配置触发后的股池流转动作。
        </p>

        <div class="transition-rules-block">
          <div class="section-header">
            <h4 class="section-title">自动流转规则</h4>
            <el-button
              type="primary"
              size="small"
              plain
              :disabled="poolLoading || availablePools.length === 0"
              @click="addTransitionRule"
            >
              新增规则
            </el-button>
          </div>

          <p v-if="availablePools.length === 0" class="empty-hint">
            当前还没有可用股池，请先到“股池管理”创建股池后再配置自动流转。
          </p>

          <div v-else-if="editingTransitionRules.length === 0" class="empty-hint">
            当前未配置自动流转规则，预警触发后只会发送通知，不会自动进入股池。
          </div>

          <div
            v-for="(rule, index) in editingTransitionRules"
            :key="rule.rule_id"
            class="transition-rule-card"
          >
            <div class="transition-rule-header">
              <strong>规则 {{ index + 1 }}</strong>
              <el-button link type="danger" @click="removeTransitionRule(rule.rule_id)">删除</el-button>
            </div>

            <div class="params-form-grid transition-grid">
              <div class="param-form-item">
                <label class="param-form-label">是否启用</label>
                <el-switch v-model="rule.enabled" active-text="启用" inactive-text="关闭" />
              </div>

              <div class="param-form-item">
                <label class="param-form-label">流转模式</label>
                <el-select v-model="rule.mode">
                  <el-option
                    v-for="option in transitionModeOptions"
                    :key="option.value"
                    :label="option.label"
                    :value="option.value"
                  />
                </el-select>
              </div>

              <div class="param-form-item">
                <label class="param-form-label">目标股池</label>
                <el-select v-model="rule.target_pool_id" placeholder="请选择目标股池">
                  <el-option
                    v-for="pool in availablePools"
                    :key="pool.pool_id"
                    :label="`${pool.name} (${pool.pool_type})`"
                    :value="pool.pool_id"
                  />
                </el-select>
              </div>

              <div class="param-form-item">
                <label class="param-form-label">来源股池（可选）</label>
                <el-select
                  v-model="rule.source_pool_ids"
                  multiple
                  collapse-tags
                  collapse-tags-tooltip
                  placeholder="不限制来源池时可留空"
                >
                  <el-option
                    v-for="pool in availablePools.filter((pool) => pool.pool_id !== rule.target_pool_id)"
                    :key="pool.pool_id"
                    :label="`${pool.name} (${pool.pool_type})`"
                    :value="pool.pool_id"
                  />
                </el-select>
              </div>

              <div class="param-form-item">
                <label class="param-form-label">冷却天数</label>
                <el-input-number
                  v-model="rule.cooldown_days"
                  :min="1"
                  :step="1"
                  :precision="0"
                  controls-position="right"
                />
              </div>

              <div class="param-form-item transition-note-item">
                <label class="param-form-label">备注</label>
                <el-input
                  v-model="rule.note"
                  type="textarea"
                  :rows="2"
                  placeholder="可选，用于说明这条自动流转规则的用途"
                />
              </div>
            </div>
          </div>
        </div>
      </div>

      <template #footer>
        <el-button @click="transitionRulesDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="savingParams"
          @click="saveTransitionRules"
        >
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.strategy-list-view {
  @apply min-h-screen p-6;
  background: var(--bg-base);
  transition: background-color var(--transition-normal);
}

/* 页面头部 */
.page-header {
  @apply flex items-center justify-between mb-8;
}

.page-title {
  @apply text-2xl font-bold mb-1;
  color: var(--text-primary);
}

.page-subtitle {
  @apply text-sm;
  color: var(--text-tertiary);
}

.header-actions {
  @apply flex items-center gap-3;
}

.view-toolbar {
  @apply flex items-end justify-between gap-4 mb-6 flex-wrap;
}

.toolbar-stats {
  @apply grid gap-3;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.toolbar-stat-card {
  @apply rounded-xl px-4 py-3 min-w-[120px];
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
}

.toolbar-stat-label {
  @apply text-xs block mb-1;
  color: var(--text-tertiary);
}

.toolbar-stat-value {
  @apply text-lg font-semibold;
  color: var(--text-primary);
}

.view-mode-switch {
  @apply shrink-0;
}

.compact-strategy-list {
  @apply flex flex-col gap-4;
}

.compact-strategy-card {
  @apply rounded-xl p-4 flex items-start justify-between gap-4 transition-all duration-300;
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
}

.compact-strategy-card:hover {
  border-color: var(--border-muted);
  box-shadow: var(--shadow-md);
}

.compact-strategy-card.is-inactive {
  opacity: 0.66;
}

.compact-card-main {
  @apply flex-1 min-w-0;
}

.compact-card-top {
  @apply flex items-start justify-between gap-4 mb-3;
}

.compact-card-title-block {
  @apply min-w-0;
}

.compact-card-title {
  @apply text-base font-semibold mb-1;
  color: var(--text-primary);
}

.compact-card-desc {
  @apply text-sm leading-5;
  color: var(--text-tertiary);
}

.compact-card-status {
  @apply flex items-center gap-2 shrink-0;
}

.compact-summary-grid {
  @apply grid gap-3;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.compact-summary-item {
  @apply rounded-lg px-3 py-3 min-w-0;
  background: var(--bg-muted);
}

.compact-summary-label {
  @apply text-xs block mb-1;
  color: var(--text-tertiary);
}

.compact-summary-value {
  @apply text-sm leading-5 break-words;
  color: var(--text-primary);
}

.compact-card-actions {
  @apply flex flex-wrap items-center justify-end gap-2 shrink-0;
  max-width: 280px;
}

.strategy-table-wrapper {
  @apply rounded-xl overflow-hidden;
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
}

.strategy-table {
  width: 100%;
}

.table-strategy-cell {
  @apply flex flex-col gap-1 py-1;
}

.table-strategy-name {
  color: var(--text-primary);
}

.table-strategy-desc {
  @apply text-xs leading-5;
  color: var(--text-tertiary);
}

.table-action-group {
  @apply flex flex-wrap gap-2 py-1;
}

/* 策略网格 */
.strategies-grid {
  @apply grid gap-6;
  grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  grid-auto-rows: 1fr;
}

/* 策略卡片 */
.strategy-card {
  @apply rounded-xl p-5 transition-all duration-300 flex flex-col;
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
  height: 100%;
}

.strategy-card:hover {
  border-color: var(--border-muted);
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}

.strategy-card.is-inactive {
  opacity: 0.6;
}

/* 卡片头部 */
.card-header {
  @apply flex items-start justify-between mb-3;
}

.header-left {
  @apply flex items-center gap-3;
}

.strategy-name {
  @apply text-lg font-semibold;
  color: var(--text-primary);
}

.header-right {
  @apply flex items-center gap-3;
}

/* 状态指示器 */
.status-indicator {
  @apply flex items-center gap-1.5 text-xs;
}

.status-dot {
  @apply w-2 h-2 rounded-full;
}

.status-indicator.active .status-dot {
  @apply bg-green-500;
  box-shadow: 0 0 6px rgba(34, 197, 94, 0.6);
}

.status-indicator.active .status-text {
  @apply text-green-400;
}

.status-indicator.inactive .status-dot {
  @apply bg-gray-500;
}

.status-indicator.inactive .status-text {
  @apply text-gray-400;
}

/* 策略描述 */
.strategy-description {
  @apply text-sm text-gray-400 mb-4;
}

/* 卡片主体 */
.card-body {
  @apply flex-1 flex flex-col;
}

/* 参数区域 */
.params-section {
  @apply mb-4;
}

.transition-section {
  @apply mt-2;
}

.section-title {
  @apply text-sm font-medium flex items-center;
  color: var(--text-secondary);
}

.params-grid {
  @apply grid grid-cols-2 gap-2;
}

.param-item {
  @apply flex justify-between items-center px-3 py-2 rounded-lg;
  background: var(--bg-muted);
}

.param-label {
  @apply text-xs;
  color: var(--text-tertiary);
}

.param-value {
  @apply text-sm font-medium;
  color: var(--text-primary);
}

.transition-summary-item {
  @apply mt-2;
}

.transition-summary-text {
  @apply text-right;
  max-width: 220px;
}

/* 股票区域 */
.stocks-section {
  @apply pt-3 mt-auto;
  border-top: 1px solid var(--border-light);
}

.section-header {
  @apply flex items-center justify-between mb-3;
}

.stock-count-badge {
  @apply ml-2;
}

.stock-tags {
  @apply flex flex-wrap gap-2;
}

.watch-count-hint {
  @apply w-full text-xs mb-2;
  color: var(--text-tertiary);
}

.stock-tag {
  @apply font-mono;
}

.stock-config-list {
  @apply flex flex-col gap-3;
}

.stock-config-item {
  @apply flex items-start justify-between gap-4 rounded-lg p-3;
  background: var(--bg-muted);
}

.stock-config-main {
  @apply flex-1 min-w-0;
}

.stock-config-title-row {
  @apply flex items-center gap-2 mb-1;
}

.stock-config-name {
  @apply font-medium;
  color: var(--text-primary);
}

.stock-config-code,
.stock-code-inline {
  @apply text-xs font-mono;
  color: var(--text-tertiary);
}

.stock-config-summary {
  @apply text-xs;
  color: var(--text-secondary);
}

.stock-config-actions {
  @apply flex items-center gap-2 shrink-0;
}

/* 空状态 */
.empty-stocks {
  @apply flex flex-col items-center py-6 text-center;
}

.empty-text {
  @apply text-sm;
  color: var(--text-tertiary);
}

.empty-hint {
  @apply text-xs mt-1;
  color: var(--text-muted);
}

/* 加载状态 */
.loading-state {
  @apply p-8;
}

/* 添加股票表单 */
.add-stock-form {
  @apply py-2;
}

.form-hint {
  @apply text-sm mb-4;
  color: var(--text-muted);
}

.stock-select {
  @apply w-full;
}

.stock-option {
  @apply flex items-center justify-between w-full;
}

.stock-name {
  @apply font-medium;
  color: var(--text-primary);
}

.stock-code {
  @apply text-sm font-mono;
  color: var(--text-tertiary);
}

/* 编辑参数表单 */
.edit-params-form {
  @apply space-y-4;
}

.params-form-grid {
  @apply space-y-4;
}

.transition-rules-block {
  @apply mt-6 space-y-4;
}

.transition-rule-card {
  @apply rounded-lg p-4 space-y-4;
  background: var(--bg-muted);
  border: 1px solid var(--border-light);
}

.transition-rule-header {
  @apply flex items-center justify-between;
  color: var(--text-primary);
}

.transition-grid {
  @apply grid gap-4;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.transition-grid .param-form-item {
  @apply flex-col items-start;
}

.transition-grid :deep(.el-select),
.transition-grid :deep(.el-input-number),
.transition-grid :deep(.el-switch) {
  width: 100%;
}

.transition-note-item {
  grid-column: 1 / -1;
  @apply items-start;
}

.transition-note-item :deep(.el-textarea),
.transition-note-item :deep(.el-select),
.transition-note-item :deep(.el-input-number) {
  width: 100%;
}

.param-form-section-label {
  @apply text-sm font-medium pt-2;
  color: var(--text-secondary);
}

.param-form-item {
  @apply flex items-center justify-between gap-4;
}

.param-form-label {
  @apply text-sm flex-shrink-0;
  color: var(--text-secondary);
}

.stock-config-dialog {
  @apply space-y-5;
}

.stock-config-form-grid {
  @apply grid gap-4;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.line-config-card {
  @apply rounded-lg p-4;
  background: var(--bg-muted);
  border: 1px solid var(--border-light);
}

.line-config-header {
  @apply flex items-center justify-between mb-4;
}

.line-config-header h4 {
  @apply text-sm font-semibold;
  color: var(--text-primary);
}

.line-config-header span {
  @apply text-xs;
  color: var(--text-tertiary);
}

.line-points-grid {
  @apply grid gap-4;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.line-point-item {
  @apply flex flex-col gap-2;
}

@media (max-width: 768px) {
  .toolbar-stats {
    grid-template-columns: 1fr;
  }

  .stock-config-item {
    @apply flex-col;
  }

  .stock-config-actions {
    @apply justify-end w-full;
  }

  .stock-config-form-grid,
  .line-points-grid,
  .transition-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .transition-summary-text {
    max-width: none;
  }
}

@media (max-width: 1100px) {
  .toolbar-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    width: 100%;
  }

  .compact-strategy-card {
    @apply flex-col;
  }

  .compact-summary-grid {
    grid-template-columns: 1fr;
  }

  .compact-card-actions {
    max-width: none;
    width: 100%;
    justify-content: flex-start;
  }
}
</style>
