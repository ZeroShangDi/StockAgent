<template>
  <div class="stock-pool-session">
    <section class="session-shell" v-loading="loading">
      <header class="session-header">
        <div class="title-block">
          <p class="eyebrow">Pool Review</p>
        </div>
        <div class="header-right">
          <div class="header-actions">
            <el-button plain @click="toggleFocusMode">
              {{ isFocusMode ? '退出专注' : '专注模式' }}
            </el-button>
            <el-button @click="backToPool">返回股池</el-button>
            <el-button :disabled="!context?.navigation.previous_ts_code" @click="jumpToPrevious">上一只</el-button>
            <el-button
              type="success"
              :disabled="!context?.navigation.next_ts_code"
              @click="jumpToNext"
            >
              下一只
            </el-button>
          </div>
        </div>
        <div class="header-footer">
          <p class="subtitle">
            {{ context?.pool.name || '股池' }}
            <span v-if="context?.navigation.position">· 第 {{ context.navigation.position }} / {{ context.navigation.total }} 只</span>
            <span v-if="context?.stock.latest_trade_date">· {{ formatTradeDate(context.stock.latest_trade_date) }}</span>
          </p>
          <div class="shortcut-inline-note">
            快捷键：<kbd>←</kbd>/<kbd>→</kbd> 切换，<kbd>↑</kbd>/<kbd>↓</kbd> 缩放，<kbd>W</kbd> 自选，<kbd>A</kbd> 监听，<kbd>X</kbd> 移除，<kbd>C</kbd> 复制，<kbd>M</kbd> 移动。
          </div>
        </div>
      </header>

      <section v-if="context" class="content-grid">
        <div class="left-panel">
          <div class="chart-card">
            <div class="chart-meta">
              <div>
                <strong>{{ context.stock.name }}</strong>
                <span>{{ context.stock.ts_code }}</span>
              </div>
              <div class="stock-chip-group">
                <span class="stock-chip">{{ context.stock.industry || '未知行业' }}</span>
                <span class="stock-chip" :class="getPnlClass(context.stock.latest_pct_chg)">
                  {{ formatSignedPct(context.stock.latest_pct_chg) }}
                </span>
                <span class="stock-chip">{{ context.stock.latest_price ? context.stock.latest_price.toFixed(2) : '--' }}</span>
                <span class="stock-chip">{{ getSourceModuleLabel(context.stock.source_module) }}</span>
              </div>
            </div>
            <div class="chart-wrap">
              <StockChart
                ref="chartRef"
                :data="chartDaily"
                :ts-code="context.stock.ts_code"
                preserve-zoom
                :initial-zoom-start="70"
                :initial-zoom-end="100"
                :reset-zoom-on-ts-code-change="false"
              />
            </div>
          </div>

        </div>

        <aside class="right-panel">
          <div class="action-card">
            <div class="info-grid">
              <div class="info-item">
                <span>最新价</span>
                <strong>{{ context.stock.latest_price ? context.stock.latest_price.toFixed(2) : '--' }}</strong>
              </div>
              <div class="info-item" :class="getPnlClass(context.stock.latest_pct_chg)">
                <span>最新涨跌</span>
                <strong>{{ formatSignedPct(context.stock.latest_pct_chg) }}</strong>
              </div>
              <div class="info-item">
                <span>加入时间</span>
                <strong>{{ context.stock.added_at ? formatDateTime(context.stock.added_at) : '-' }}</strong>
              </div>
              <div class="info-item">
                <span>上市日期</span>
                <strong>{{ formatTradeDate(context.stock.list_date) }}</strong>
              </div>
            </div>

            <div class="block">
              <label>快捷操作</label>
              <div class="block-actions">
                <el-button type="primary" plain :loading="watchlistLoading" @click="addCurrentToWatchlist">
                  加入自选
                </el-button>
                <el-button
                  type="warning"
                  plain
                  :loading="repairLoading"
                  @click="startRepairTask"
                >
                  单股补数更新
                </el-button>
                <el-button type="danger" plain :loading="removeLoading" @click="removeCurrentFromPool">
                  从当前股池移除
                </el-button>
              </div>
              <div v-if="repairTask" class="task-inline-status" :class="repairTask.status">
                <span class="task-status-pill">{{ getRepairStatusLabel(repairTask.status) }}</span>
                <span>{{ repairTask.current_step || repairTask.message || '处理中' }}</span>
                <span>{{ repairTask.progress ?? 0 }}%</span>
              </div>
            </div>

            <div class="block">
              <label>加入监听</label>
              <el-select
                v-model="selectedStrategyType"
                class="full-width"
                placeholder="请选择监听策略"
                :loading="strategyLoading"
              >
                <el-option
                  v-for="item in strategyTypes"
                  :key="item.type"
                  :label="item.name"
                  :value="item.type"
                />
              </el-select>
              <div class="block-actions">
                <el-button
                  type="primary"
                  :disabled="!selectedStrategyType"
                  :loading="listenerLoading"
                  @click="addCurrentToStrategy"
                >
                  添加到该策略
                </el-button>
              </div>
            </div>

            <div class="block">
              <label>流转到其他股池</label>
              <el-select
                v-model="selectedTargetPoolId"
                class="full-width"
                placeholder="请选择目标股池"
                :loading="targetPoolsLoading"
              >
                <el-option
                  v-for="pool in targetPools"
                  :key="pool.pool_id"
                  :label="`${pool.name}（${pool.pool_type}）`"
                  :value="pool.pool_id"
                />
              </el-select>
              <div class="block-actions">
                <el-button
                  type="primary"
                  plain
                  :disabled="!selectedTargetPoolId"
                  :loading="moveLoading"
                  @click="copyToTargetPool"
                >
                  复制到目标池
                </el-button>
                <el-button
                  type="warning"
                  :disabled="!selectedTargetPoolId"
                  :loading="moveLoading"
                  @click="moveToTargetPool"
                >
                  移动到目标池
                </el-button>
              </div>
            </div>

            <div class="block">
              <label>来源线索</label>
              <div class="source-box">
                <p><strong>来源模块：</strong>{{ getSourceModuleLabel(context.stock.source_module) }}</p>
                <p><strong>来源股池：</strong>{{ context.stock.source_pool_name || '暂无记录' }}</p>
                <p><strong>来源条件：</strong>{{ context.stock.source_query || '暂无记录' }}</p>
              </div>
            </div>
          </div>
        </aside>
      </section>

      <el-empty v-else description="暂无股池上下文数据" />
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { stockApi, stockPickerApi, subscriptionApi } from '@/api'
import { useUserStore } from '@/stores/user'
import StockChart from '@/components/charts/StockChart.vue'
import type { StockDaily } from '@/api'
import type { StrategyTypeInfo } from '@/api/types'
import type { StockPoolReviewContext, StockPoolSummary } from '@/api/modules/stock-picker'
import type { StockRepairTaskStatus } from '@/api/modules/stock'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const loading = ref(false)
const strategyLoading = ref(false)
const targetPoolsLoading = ref(false)
const listenerLoading = ref(false)
const watchlistLoading = ref(false)
const moveLoading = ref(false)
const removeLoading = ref(false)
const repairLoading = ref(false)

const context = ref<StockPoolReviewContext | null>(null)
const strategyTypes = ref<StrategyTypeInfo[]>([])
const targetPools = ref<StockPoolSummary[]>([])
const selectedStrategyType = ref('')
const selectedTargetPoolId = ref('')
const chartRef = ref<InstanceType<typeof StockChart> | null>(null)
const repairTask = ref<StockRepairTaskStatus | null>(null)
let repairTaskTimer: number | null = null

const currentPoolId = computed(() => String(route.params.poolId || ''))
const currentTsCode = computed(() => String(route.params.tsCode || '').toUpperCase())
const isFocusMode = ref(false)
const chartDaily = computed<StockDaily[]>(() => {
  return (context.value?.daily || []).map((item) => ({
    ts_code: item.ts_code,
    trade_date: item.trade_date,
    open: Number(item.open || 0),
    high: Number(item.high || 0),
    low: Number(item.low || 0),
    close: Number(item.close || 0),
    pre_close: Number(item.pre_close || 0),
    change: Number(item.change || 0),
    pct_chg: Number(item.pct_chg || 0),
    vol: Number(item.vol || 0),
    amount: Number(item.amount || 0),
  }))
})

function formatTradeDate(value?: string | null): string {
  if (!value) return '-'
  return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`
}

function formatDateTime(value?: string): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

function formatSignedPct(value?: number | null): string {
  if (value == null || Number.isNaN(Number(value))) return '-'
  const numeric = Number(value)
  return `${numeric > 0 ? '+' : ''}${numeric.toFixed(2)}%`
}

function getPnlClass(value?: number | null): string {
  const numeric = Number(value || 0)
  if (numeric > 0) return 'is-profit'
  if (numeric < 0) return 'is-loss'
  return ''
}

function getSourceModuleLabel(sourceModule?: string): string {
  const mapping: Record<string, string> = {
    one_line_picker: '一句话选股',
    listener_transition: '监听流转',
    manual: '手动添加',
    market_weather: '市场晴雨表',
  }
  if (!sourceModule) return '-'
  return mapping[sourceModule] || sourceModule
}

function getRepairStatusLabel(status?: string): string {
  const mapping: Record<string, string> = {
    queued: '排队中',
    running: '进行中',
    completed: '已完成',
    failed: '失败',
  }
  return mapping[status || ''] || status || '未知'
}

function stopRepairTaskPolling(): void {
  if (repairTaskTimer != null) {
    window.clearTimeout(repairTaskTimer)
    repairTaskTimer = null
  }
}

async function pollRepairTask(taskId: string): Promise<void> {
  try {
    const status = await stockApi.getStockRepairTask(taskId)
    repairTask.value = status
    if (status.status === 'completed') {
      ElMessage.success(`${context.value?.stock.name || context.value?.stock.ts_code} 补数完成`)
      await loadContext()
      stopRepairTaskPolling()
      return
    }
    if (status.status === 'failed') {
      ElMessage.error(status.error_message || '单股补数失败')
      stopRepairTaskPolling()
      return
    }
    stopRepairTaskPolling()
    repairTaskTimer = window.setTimeout(() => {
      void pollRepairTask(taskId)
    }, 2000)
  } catch (error) {
    stopRepairTaskPolling()
    ElMessage.error('查询单股补数状态失败')
  }
}

async function startRepairTask(): Promise<void> {
  if (!context.value) return
  repairLoading.value = true
  try {
    const response = await stockApi.createStockRepairTask(context.value.stock.ts_code)
    ElMessage.success(response.message || '已创建单股补数任务')
    stopRepairTaskPolling()
    await pollRepairTask(response.task_id)
  } finally {
    repairLoading.value = false
  }
}

async function loadContext(): Promise<void> {
  if (!currentPoolId.value || !currentTsCode.value) return
  loading.value = true
  try {
    context.value = await stockPickerApi.getPoolReviewContext(currentPoolId.value, currentTsCode.value)
  } catch (error) {
    context.value = null
    ElMessage.error('加载股池沉浸复盘数据失败，通常是股池已变更或本地日线数据还不完整')
  } finally {
    loading.value = false
  }
}

async function ensureStrategyTypesLoaded(): Promise<void> {
  if (strategyTypes.value.length > 0) return
  strategyLoading.value = true
  try {
    strategyTypes.value = await subscriptionApi.getStrategyTypes()
    if (!selectedStrategyType.value && strategyTypes.value.length > 0) {
      selectedStrategyType.value = strategyTypes.value[0].type
    }
  } finally {
    strategyLoading.value = false
  }
}

async function ensureTargetPoolsLoaded(): Promise<void> {
  targetPoolsLoading.value = true
  try {
    const response = await stockPickerApi.listPools()
    targetPools.value = (response.items || []).filter((item) => item.pool_id !== currentPoolId.value)
    if (!selectedTargetPoolId.value && targetPools.value.length > 0) {
      selectedTargetPoolId.value = targetPools.value[0].pool_id
    }
  } finally {
    targetPoolsLoading.value = false
  }
}

function pushStock(tsCode: string): void {
  router.push({
    name: 'StockPoolSession',
    params: {
      poolId: currentPoolId.value,
      tsCode,
    },
  })
}

function jumpToPrevious(): void {
  const previous = context.value?.navigation.previous_ts_code
  if (!previous) return
  pushStock(previous)
}

function jumpToNext(): void {
  const next = context.value?.navigation.next_ts_code
  if (!next) return
  pushStock(next)
}

function backToPool(): void {
  router.push({ name: 'StockPools' })
}

function toggleFocusMode(): void {
  isFocusMode.value = !isFocusMode.value
  window.localStorage.setItem('stockagent.focus_mode', isFocusMode.value ? '1' : '0')
  window.dispatchEvent(new Event('stockagent-focus-mode-change'))
}

async function addCurrentToWatchlist(): Promise<void> {
  if (!context.value) return
  watchlistLoading.value = true
  try {
    const success = await userStore.addToWatchlist(context.value.stock.ts_code)
    if (success) {
      ElMessage.success(`已将 ${context.value.stock.name} 加入自选`)
    } else {
      ElMessage.warning('加入自选失败，可能已存在')
    }
  } finally {
    watchlistLoading.value = false
  }
}

async function addCurrentToStrategy(): Promise<void> {
  if (!context.value || !selectedStrategyType.value) return
  listenerLoading.value = true
  try {
    const response = await subscriptionApi.addStockToStrategy(selectedStrategyType.value, context.value.stock.ts_code)
    ElMessage.success(response.message)
  } finally {
    listenerLoading.value = false
  }
}

async function removeCurrentFromPool(): Promise<void> {
  if (!context.value) return
  try {
    await ElMessageBox.confirm(
      `确认从股池“${context.value.pool.name}”中移除 ${context.value.stock.name} 吗？`,
      '移除股票确认',
      {
        type: 'warning',
        confirmButtonText: '确认移除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }

  removeLoading.value = true
  try {
    await stockPickerApi.removeStocksFromPool(currentPoolId.value, [context.value.stock.ts_code])
    ElMessage.success(`已从股池中移除 ${context.value.stock.name}`)
    const nextTsCode = context.value.navigation.next_ts_code || context.value.navigation.previous_ts_code
    if (nextTsCode) {
      pushStock(nextTsCode)
      return
    }
    backToPool()
  } finally {
    removeLoading.value = false
  }
}

async function copyToTargetPool(): Promise<void> {
  if (!context.value || !selectedTargetPoolId.value) return
  moveLoading.value = true
  try {
    const response = await stockPickerApi.addStocksToPool(selectedTargetPoolId.value, {
      stocks: [{
        ts_code: context.value.stock.ts_code,
        code: context.value.stock.code,
        name: context.value.stock.name,
      }],
      source_module: 'manual',
      source_query: `从股池「${context.value.pool.name}」复制`,
      source_pool_name: context.value.pool.name,
    })
    ElMessage.success(response.message)
    await ensureTargetPoolsLoaded()
  } finally {
    moveLoading.value = false
  }
}

async function moveToTargetPool(): Promise<void> {
  if (!context.value || !selectedTargetPoolId.value) return
  moveLoading.value = true
  try {
    await stockPickerApi.addStocksToPool(selectedTargetPoolId.value, {
      stocks: [{
        ts_code: context.value.stock.ts_code,
        code: context.value.stock.code,
        name: context.value.stock.name,
      }],
      source_module: 'manual',
      source_query: `从股池「${context.value.pool.name}」移动`,
      source_pool_name: context.value.pool.name,
    })
    await stockPickerApi.removeStocksFromPool(currentPoolId.value, [context.value.stock.ts_code])
    ElMessage.success(`已将 ${context.value.stock.name} 移动到目标股池`)
    const nextTsCode = context.value.navigation.next_ts_code || context.value.navigation.previous_ts_code
    if (nextTsCode) {
      pushStock(nextTsCode)
      return
    }
    backToPool()
  } finally {
    moveLoading.value = false
  }
}

function isTypingElement(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null
  if (!element) return false
  const tagName = element.tagName?.toLowerCase()
  return tagName === 'input' || tagName === 'textarea' || !!element.closest('.el-input, .el-textarea, .el-select') || element.isContentEditable
}

function handleKeydown(event: KeyboardEvent): void {
  if (isTypingElement(event.target)) return
  if (event.key === 'ArrowLeft') {
    event.preventDefault()
    jumpToPrevious()
    return
  }
  if (event.key === 'ArrowRight') {
    event.preventDefault()
    jumpToNext()
    return
  }
  if (event.key === 'ArrowUp') {
    event.preventDefault()
    chartRef.value?.zoomIn?.()
    return
  }
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    chartRef.value?.zoomOut?.()
    return
  }
  if (event.key.toLowerCase() === 'w') {
    event.preventDefault()
    void addCurrentToWatchlist()
    return
  }
  if (event.key.toLowerCase() === 'a') {
    event.preventDefault()
    void addCurrentToStrategy()
    return
  }
  if (event.key.toLowerCase() === 'c') {
    event.preventDefault()
    void copyToTargetPool()
    return
  }
  if (event.key.toLowerCase() === 'm') {
    event.preventDefault()
    void moveToTargetPool()
    return
  }
  if (event.key.toLowerCase() === 'x') {
    event.preventDefault()
    void removeCurrentFromPool()
  }
}

watch(
  () => [route.params.poolId, route.params.tsCode],
  () => {
    loadContext()
    ensureTargetPoolsLoaded()
  },
)

onMounted(() => {
  isFocusMode.value = typeof window !== 'undefined' && window.localStorage.getItem('stockagent.focus_mode') === '1'
  window.addEventListener('keydown', handleKeydown)
  loadContext()
  ensureStrategyTypesLoaded()
  ensureTargetPoolsLoaded()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
  stopRepairTaskPolling()
})
</script>

<style scoped lang="scss">
.stock-pool-session {
  padding: 1rem 1.25rem 1.25rem;
  min-width: 0;
}

.session-shell {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: calc(100vh - 140px);
  min-width: 0;
}

.session-header,
.chart-card,
.action-card {
  background: var(--el-bg-color);
  border-radius: 20px;
  border: 1px solid rgba(15, 23, 42, 0.08);
}

.session-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: start;
  gap: 10px 16px;
  padding: 14px 18px;
}

.eyebrow {
  margin: 0;
  font-size: 12px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--el-color-primary);
}

.title-block h1 {
  margin: 6px 0 8px;
}

.subtitle {
  margin: 0;
  color: var(--el-text-color-secondary);
}

.header-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.header-right {
  display: flex;
  justify-content: flex-start;
}

.header-footer {
  grid-column: 1 / -1;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.shortcut-inline-note {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.7;
  text-align: right;
  align-self: flex-end;
}

.content-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.7fr) minmax(320px, 0.85fr);
  gap: 12px;
  flex: 1;
  min-width: 0;
  align-items: stretch;
}

.left-panel,
.right-panel {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
}

.chart-card,
.action-card {
  padding: 14px 16px;
  min-width: 0;
  overflow: hidden;
}

.chart-card {
  flex: 1;
  min-height: 700px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.chart-meta {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.chart-meta strong {
  display: block;
  margin-bottom: 4px;
}

.chart-meta span {
  color: var(--el-text-color-secondary);
}

.stock-chip-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.stock-chip {
  padding: 5px 9px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.05);
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.chart-wrap {
  flex: 1;
  min-height: 600px;
  min-width: 0;
  overflow: hidden;
}

.action-card {
  display: flex;
  flex-direction: column;
  gap: 14px;
  flex: 1;
  min-height: 700px;
}

.info-grid {
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.info-item {
  display: grid;
  gap: 4px;
  padding: 10px 12px;
  border-radius: 14px;
  background: rgba(15, 23, 42, 0.04);
}

.info-item span {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.block {
  display: grid;
  gap: 8px;
}

.block label {
  font-size: 13px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}

.block-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.task-inline-status {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.task-status-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(59, 130, 246, 0.1);
  color: var(--el-color-primary);
  font-weight: 600;
}

.task-inline-status.completed .task-status-pill {
  background: rgba(16, 185, 129, 0.12);
  color: #047857;
}

.task-inline-status.failed .task-status-pill {
  background: rgba(239, 68, 68, 0.12);
  color: #b91c1c;
}

.full-width {
  width: 100%;
}

.source-box {
  display: grid;
  gap: 6px;
  padding: 10px 12px;
  border-radius: 14px;
  background: rgba(15, 23, 42, 0.04);
  min-width: 0;
}

.source-box p {
  margin: 0;
  line-height: 1.7;
  color: var(--el-text-color-secondary);
  white-space: pre-wrap;
  word-break: break-word;
}

kbd {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 24px;
  padding: 2px 6px;
  margin: 0 2px;
  border-radius: 6px;
  border: 1px solid rgba(15, 23, 42, 0.12);
  background: rgba(255, 255, 255, 0.82);
  color: var(--el-text-color-primary);
  font-family: inherit;
}

.is-profit {
  color: #dc2626;
}

.is-loss {
  color: #059669;
}

@media (max-width: 1100px) {
  .content-grid {
    grid-template-columns: 1fr;
  }

  .chart-card {
    min-height: 560px;
  }

  .action-card {
    min-height: 0;
  }
}

@media (max-width: 768px) {
  .chart-meta {
    flex-direction: column;
  }

  .header-actions,
  .stock-chip-group {
    justify-content: flex-start;
  }

  .subtitle-row {
    align-items: flex-start;
  }

  .header-right,
  .shortcut-inline-note {
    text-align: left;
  }

  .header-footer {
    align-items: flex-start;
  }

  .info-grid {
    grid-template-columns: 1fr;
  }
}
</style>
