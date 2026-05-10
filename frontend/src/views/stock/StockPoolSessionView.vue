<template>
  <div class="stock-pool-session">
    <section class="session-shell" v-loading="loading">
      <header class="session-header">
        <div class="title-block">
          <p class="eyebrow">Pool Review</p>
        </div>
        <div class="header-right">
          <div class="header-actions">
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

      <template v-if="context">
      <section class="content-grid">
        <div class="left-panel">
          <div class="chart-card">
            <div class="chart-meta">
              <div class="chart-title-block">
                <div>
                  <strong>{{ context.stock.name }}</strong>
                  <span>{{ context.stock.ts_code }}</span>
                </div>
                <el-radio-group v-model="selectedKlinePeriod" size="small" class="period-switch">
                  <el-radio-button
                    v-for="option in klinePeriodOptions"
                    :key="option.value"
                    :label="option.value"
                  >
                    {{ option.label }}
                  </el-radio-button>
                </el-radio-group>
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
                :data="selectedChartData"
                :ts-code="context.stock.ts_code"
                :markers="chartMarkers"
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
              <div class="info-item" :class="getPnlClass(context.stock.recent_30d_pct_chg)">
                <span>近30日涨幅</span>
                <strong>{{ formatSignedPct(context.stock.recent_30d_pct_chg) }}</strong>
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
              <div v-if="selectedStrategyMeta && isPerStockConfigStrategy(selectedStrategyType)" class="listener-config-hint">
                {{ selectedStrategyMeta.name }} 支持单股特殊配置，添加后会在当前页直接继续配置。
              </div>
              <div class="block-actions">
                <el-button
                  type="primary"
                  :disabled="!selectedStrategyType"
                  :loading="listenerLoading"
                  @click="addCurrentToStrategy"
                >
                  {{ isPerStockConfigStrategy(selectedStrategyType) ? '添加并配置' : '添加到该策略' }}
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
              <label>板块概念</label>
              <div class="source-box">
                <p><strong>所属行业：</strong>{{ context.stock.industry || '暂无行业信息' }}</p>
                <div v-if="context.stock.concepts?.length" class="tag-flow">
                  <span
                    v-for="item in context.stock.concepts"
                    :key="`concept-${item.ts_code}`"
                    class="sector-tag"
                  >
                    {{ item.name }}
                  </span>
                </div>
                <p v-else>暂无个股概念映射</p>
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

      <el-dialog
        v-model="stockConfigDialogVisible"
        :title="getStockConfigActionLabel(selectedStrategyType)"
        width="720px"
        :close-on-click-modal="false"
      >
        <div v-if="context" class="stock-config-dialog">
          <p class="form-hint">
            为 <strong>{{ context.stock.name }}</strong>
            <span class="stock-code-inline">({{ context.stock.ts_code }})</span>
            <template v-if="isMaBuyStrategy(selectedStrategyType)">
              配置这只股票自己的均线低吸参数；如果不单独配置，会继续使用策略默认参数。
            </template>
            <template v-else-if="isSupportResistanceStrategy(selectedStrategyType)">
              配置支撑线与压力线；可选水平线或斜线。斜线模式下价格留空时，会自动取对应日期 K 线的最低价或最高价。
            </template>
            <template v-else-if="isFixedStopLossStrategy(selectedStrategyType)">
              配置固定止损基准。若参考日期留空，后端会继续使用当前已保存的加入基准。
            </template>
            <template v-else-if="isTrailingStopLossStrategy(selectedStrategyType)">
              配置移动止损基准与回撤比例。最高价默认会在监听运行中持续自动抬升并持久化。
            </template>
          </p>

          <div v-if="isMaBuyStrategy(selectedStrategyType)" class="params-form-grid">
            <div class="param-form-item">
              <label class="param-form-label">是否启用</label>
              <el-switch v-model="editingStockConfig.enabled" active-text="启用" inactive-text="关闭" />
            </div>
            <div class="param-form-item">
              <label class="param-form-label">均线周期</label>
              <el-input-number v-model="editingStockConfig.ma_period" :min="2" :max="250" :step="1" controls-position="right" />
            </div>
            <div class="param-form-item">
              <label class="param-form-label">触及范围 (%)</label>
              <el-input-number v-model="editingStockConfig.touch_range" :min="0.01" :precision="2" :step="0.1" controls-position="right" />
            </div>
            <div class="param-form-item">
              <label class="param-form-label">企稳周期数</label>
              <el-input-number v-model="editingStockConfig.stable_periods" :min="1" :max="20" :step="1" controls-position="right" />
            </div>
          </div>

          <div v-if="isSupportResistanceStrategy(selectedStrategyType)" class="stock-config-form-grid">
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

          <div v-if="isSupportResistanceStrategy(selectedStrategyType) && editingStockConfig.support_enabled" class="line-config-card">
            <div class="line-config-header">
              <h4>支撑线</h4>
              <span>可配置水平支撑价，或用两个点位画支撑趋势线</span>
            </div>
            <div class="param-form-item line-mode-item">
              <label class="param-form-label">支撑线类型</label>
              <el-radio-group v-model="editingStockConfig.support_mode">
                <el-radio-button
                  v-for="option in lineModeOptions"
                  :key="`pool-support-${option.value}`"
                  :label="option.value"
                >
                  {{ option.label }}
                </el-radio-button>
              </el-radio-group>
            </div>
            <div v-if="editingStockConfig.support_mode === 'horizontal'" class="param-form-item line-price-item">
              <label class="param-form-label">支撑价</label>
              <el-input-number v-model="editingStockConfig.support_price" :min="0" :precision="2" :step="0.01" controls-position="right" />
            </div>
            <div v-if="editingStockConfig.support_mode === 'trend'" class="line-points-grid">
              <div
                v-for="(point, index) in editingStockConfig.support_points"
                :key="`pool-support-point-${index}`"
                class="line-point-item"
              >
                <label class="param-form-label">支撑点 {{ index + 1 }}</label>
                <el-date-picker v-model="point.date" type="date" value-format="YYYYMMDD" format="YYYY-MM-DD" placeholder="选择日期" />
                <el-input-number v-model="point.price" :min="0" :precision="2" :step="0.01" controls-position="right" placeholder="留空自动取低点" />
              </div>
            </div>
          </div>

          <div v-if="isSupportResistanceStrategy(selectedStrategyType) && editingStockConfig.resistance_enabled" class="line-config-card">
            <div class="line-config-header">
              <h4>压力线</h4>
              <span>可配置水平压力价，或用两个点位画压力趋势线</span>
            </div>
            <div class="param-form-item line-mode-item">
              <label class="param-form-label">压力线类型</label>
              <el-radio-group v-model="editingStockConfig.resistance_mode">
                <el-radio-button
                  v-for="option in lineModeOptions"
                  :key="`pool-resistance-${option.value}`"
                  :label="option.value"
                >
                  {{ option.label }}
                </el-radio-button>
              </el-radio-group>
            </div>
            <div v-if="editingStockConfig.resistance_mode === 'horizontal'" class="param-form-item line-price-item">
              <label class="param-form-label">压力价</label>
              <el-input-number v-model="editingStockConfig.resistance_price" :min="0" :precision="2" :step="0.01" controls-position="right" />
            </div>
            <div v-if="editingStockConfig.resistance_mode === 'trend'" class="line-points-grid">
              <div
                v-for="(point, index) in editingStockConfig.resistance_points"
                :key="`pool-resistance-point-${index}`"
                class="line-point-item"
              >
                <label class="param-form-label">压力点 {{ index + 1 }}</label>
                <el-date-picker v-model="point.date" type="date" value-format="YYYYMMDD" format="YYYY-MM-DD" placeholder="选择日期" />
                <el-input-number v-model="point.price" :min="0" :precision="2" :step="0.01" controls-position="right" placeholder="留空自动取高点" />
              </div>
            </div>
          </div>

          <div v-if="isFixedStopLossStrategy(selectedStrategyType)" class="params-form-grid">
            <div class="param-form-item">
              <label class="param-form-label">是否启用</label>
              <el-switch v-model="editingStockConfig.enabled" active-text="启用" inactive-text="关闭" />
            </div>
            <div class="param-form-item">
              <label class="param-form-label">参考日期</label>
              <el-date-picker v-model="editingStockConfig.reference_date" type="date" value-format="YYYYMMDD" format="YYYY-MM-DD" placeholder="选择参考日期" />
            </div>
            <div class="param-form-item">
              <label class="param-form-label">参考价格</label>
              <el-input-number v-model="editingStockConfig.reference_price" :min="0" :precision="2" :step="0.01" controls-position="right" />
            </div>
            <div class="param-form-item">
              <label class="param-form-label">止损比例 (%)</label>
              <el-input-number v-model="editingStockConfig.stop_loss_pct" :min="0.01" :precision="2" :step="0.1" controls-position="right" />
            </div>
          </div>

          <div v-if="isTrailingStopLossStrategy(selectedStrategyType)" class="params-form-grid">
            <div class="param-form-item">
              <label class="param-form-label">是否启用</label>
              <el-switch v-model="editingStockConfig.enabled" active-text="启用" inactive-text="关闭" />
            </div>
            <div class="param-form-item">
              <label class="param-form-label">入场日期</label>
              <el-date-picker v-model="editingStockConfig.entry_date" type="date" value-format="YYYYMMDD" format="YYYY-MM-DD" placeholder="选择入场日期" />
            </div>
            <div class="param-form-item">
              <label class="param-form-label">入场价格</label>
              <el-input-number v-model="editingStockConfig.entry_price" :min="0" :precision="2" :step="0.01" controls-position="right" />
            </div>
            <div class="param-form-item">
              <label class="param-form-label">当前最高价</label>
              <el-input-number v-model="editingStockConfig.highest_price" :min="0" :precision="2" :step="0.01" controls-position="right" />
            </div>
            <div class="param-form-item">
              <label class="param-form-label">最高价日期</label>
              <el-date-picker v-model="editingStockConfig.highest_price_date" type="date" value-format="YYYYMMDD" format="YYYY-MM-DD" placeholder="选择最高价日期" />
            </div>
            <div class="param-form-item">
              <label class="param-form-label">回撤比例 (%)</label>
              <el-input-number v-model="editingStockConfig.trail_pct" :min="0.01" :precision="2" :step="0.1" controls-position="right" />
            </div>
          </div>

          <div class="param-form-item">
            <label class="param-form-label">备注</label>
            <el-input
              v-model="editingStockConfig.note"
              type="textarea"
              :rows="2"
              :placeholder="isMaBuyStrategy(selectedStrategyType)
                ? '可选，记录这只股票为什么使用特殊均线'
                : isSupportResistanceStrategy(selectedStrategyType)
                  ? '可选，记录点位含义或趋势说明'
                  : '可选，记录止损逻辑或建仓背景'"
            />
          </div>
        </div>

        <template #footer>
          <el-button @click="stockConfigDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="savingStockConfig" @click="saveListenerStockConfig">
            保存配置
          </el-button>
        </template>
      </el-dialog>
      </template>

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
import { StrategyType } from '@/api/types'
import type { StrategyStockConfig, StrategyStockPoint, StrategyTypeInfo } from '@/api/types'
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
const stockConfigDialogVisible = ref(false)
const editingStockConfig = ref<StrategyStockConfig>({})
const savingStockConfig = ref(false)
let repairTaskTimer: number | null = null

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

const currentPoolId = computed(() => String(route.params.poolId || ''))
const currentTsCode = computed(() => String(route.params.tsCode || '').toUpperCase())
const selectedKlinePeriod = ref<'daily' | 'weekly' | 'monthly'>('daily')
const klinePeriodOptions = [
  { label: '日K', value: 'daily' },
  { label: '周K', value: 'weekly' },
  { label: '月K', value: 'monthly' },
] as const

function normalizeChartSeries(items: Array<{
  ts_code: string
  trade_date: string
  open: number
  high: number
  low: number
  close: number
  pre_close?: number | null
  change?: number | null
  pct_chg?: number | null
  vol?: number | null
  amount?: number | null
}> = []): StockDaily[] {
  return items.map((item) => ({
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
}

const chartDaily = computed<StockDaily[]>(() => normalizeChartSeries(context.value?.daily || []))
const chartWeekly = computed<StockDaily[]>(() => normalizeChartSeries(context.value?.weekly || []))
const chartMonthly = computed<StockDaily[]>(() => normalizeChartSeries(context.value?.monthly || []))

const selectedChartData = computed<StockDaily[]>(() => {
  if (selectedKlinePeriod.value === 'weekly') return chartWeekly.value
  if (selectedKlinePeriod.value === 'monthly') return chartMonthly.value
  return chartDaily.value
})

function normalizeTradeDateString(value?: string | null): string | null {
  if (!value) return null
  if (/^\d{8}$/.test(value)) return value
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return null
  const year = parsed.getFullYear()
  const month = `${parsed.getMonth() + 1}`.padStart(2, '0')
  const date = `${parsed.getDate()}`.padStart(2, '0')
  return `${year}${month}${date}`
}

const chartMarkers = computed(() => {
  const candles = selectedChartData.value
  const addedTradeDate = normalizeTradeDateString(context.value?.stock.added_at)
  if (!candles.length || !addedTradeDate) {
    return []
  }

  const matched =
    candles.find((item) => item.trade_date >= addedTradeDate) ||
    [...candles].reverse().find((item) => item.trade_date <= addedTradeDate) ||
    null

  if (!matched) {
    return []
  }

  const markerPrice = Number(matched.close || matched.open || 0)
  if (!markerPrice) {
    return []
  }

  return [
    {
      trade_date: matched.trade_date,
      price: markerPrice,
      side: 'buy',
      label: '入池',
      is_current: true,
    },
  ]
})

const selectedStrategyMeta = computed(() => {
  return strategyTypes.value.find((item) => item.type === selectedStrategyType.value) || null
})

function isMaBuyStrategy(strategyType?: string): boolean {
  return strategyType === StrategyType.MA5_BUY
}

function isSupportResistanceStrategy(strategyType?: string): boolean {
  return strategyType === StrategyType.SUPPORT_RESISTANCE
}

function isFixedStopLossStrategy(strategyType?: string): boolean {
  return strategyType === StrategyType.FIXED_STOP_LOSS
}

function isTrailingStopLossStrategy(strategyType?: string): boolean {
  return strategyType === StrategyType.TRAILING_STOP_LOSS
}

function isPerStockConfigStrategy(strategyType?: string): boolean {
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

function normalizePoint(point: StrategyStockPoint): StrategyStockPoint {
  return {
    date: point.date,
    price: point.price == null || point.price === 0 ? null : Number(point.price),
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

function createSupportResistanceConfig(): StrategyStockConfig {
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

function cloneSupportResistanceConfig(config?: Partial<StrategyStockConfig>): StrategyStockConfig {
  const fallback = createSupportResistanceConfig()
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

function createDialogStockConfig(strategyType?: string, config?: Partial<StrategyStockConfig>): StrategyStockConfig {
  if (isMaBuyStrategy(strategyType)) return cloneMABuyConfig(config)
  if (isSupportResistanceStrategy(strategyType)) return cloneSupportResistanceConfig(config)
  if (isFixedStopLossStrategy(strategyType)) return cloneFixedStopLossConfig(config)
  if (isTrailingStopLossStrategy(strategyType)) return cloneTrailingStopLossConfig(config)
  return {}
}

function getStockConfigActionLabel(strategyType?: string): string {
  if (isMaBuyStrategy(strategyType)) return '配置均线低吸'
  if (isSupportResistanceStrategy(strategyType)) return '配置撑压线'
  if (isFixedStopLossStrategy(strategyType)) return '配置固定止损'
  if (isTrailingStopLossStrategy(strategyType)) return '配置移动止损'
  return '配置监听'
}

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
    strategyTypes.value = (await subscriptionApi.getStrategyTypes()).filter(
      (item) => item.type !== StrategyType.MARKET_INDEX_ALERT,
    )
    if (!selectedStrategyType.value && strategyTypes.value.length > 0) {
      selectedStrategyType.value = strategyTypes.value[0].type
    }
  } finally {
    strategyLoading.value = false
  }
}

async function openStrategyConfigDialog(strategyType: string): Promise<void> {
  if (!context.value) return
  const subscription = await subscriptionApi.getSubscriptionByType(strategyType)
  const stockConfigs = (subscription.params?.stock_configs as Record<string, StrategyStockConfig> | undefined) || {}
  editingStockConfig.value = createDialogStockConfig(strategyType, stockConfigs[context.value.stock.ts_code] || undefined)
  stockConfigDialogVisible.value = true
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
    if (response.success) {
      ElMessage.success(response.message)
    } else {
      ElMessage.warning(response.message)
    }
    if (isPerStockConfigStrategy(selectedStrategyType.value)) {
      await openStrategyConfigDialog(selectedStrategyType.value)
    }
  } finally {
    listenerLoading.value = false
  }
}

async function saveListenerStockConfig(): Promise<void> {
  if (!context.value || !selectedStrategyType.value) return

  let payload: StrategyStockConfig
  if (isMaBuyStrategy(selectedStrategyType.value)) {
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
  } else if (isSupportResistanceStrategy(selectedStrategyType.value)) {
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
  } else if (isFixedStopLossStrategy(selectedStrategyType.value)) {
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
  } else if (isTrailingStopLossStrategy(selectedStrategyType.value)) {
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
  } else {
    return
  }

  savingStockConfig.value = true
  try {
    await subscriptionApi.updateStockConfig(
      selectedStrategyType.value,
      context.value.stock.ts_code,
      payload,
    )
    ElMessage.success(`${getStockConfigActionLabel(selectedStrategyType.value)}已保存`)
    stockConfigDialogVisible.value = false
  } finally {
    savingStockConfig.value = false
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
  position: relative;
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

.chart-title-block {
  display: grid;
  gap: 10px;
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

.period-switch {
  width: fit-content;
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

.listener-config-hint,
.form-hint {
  font-size: 12px;
  line-height: 1.7;
  color: var(--el-text-color-secondary);
}

.stock-code-inline {
  color: var(--el-text-color-secondary);
}

.stock-config-dialog {
  display: grid;
  gap: 14px;
}

.params-form-grid,
.stock-config-form-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.param-form-item {
  display: grid;
  gap: 8px;
}

.param-form-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.line-config-card {
  display: grid;
  gap: 12px;
  padding: 14px;
  border-radius: 16px;
  background: rgba(15, 23, 42, 0.03);
  border: 1px solid rgba(15, 23, 42, 0.08);
}

.line-config-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.line-config-header h4 {
  margin: 0;
  font-size: 15px;
}

.line-config-header span {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.line-points-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.line-point-item {
  display: grid;
  gap: 8px;
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

.tag-flow {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.sector-tag {
  display: inline-flex;
  align-items: center;
  padding: 4px 9px;
  border-radius: 999px;
  background: rgba(59, 130, 246, 0.08);
  color: var(--el-color-primary);
  font-size: 12px;
  line-height: 1.2;
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

  .params-form-grid,
  .stock-config-form-grid,
  .line-points-grid {
    grid-template-columns: 1fr;
  }
}
</style>
