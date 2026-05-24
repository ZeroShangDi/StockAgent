<template>
  <div class="review-chart-panel">
    <div class="chart-meta">
      <div class="chart-toolbar">
        <div v-if="showTitleBlock" class="chart-title-block">
          <strong>{{ stock.name || stock.ts_code }}</strong>
          <span v-if="stock.ts_code">{{ stock.ts_code }}</span>
        </div>

        <div class="toolbar-right">
          <div class="toolbar-actions">
            <slot name="toolbarActions" />
            <el-button
              v-if="showNavigation"
              size="default"
              type="primary"
              round
              class="nav-button"
              :disabled="previousDisabled"
              @click="emit('previous')"
            >
              <span>{{ previousLabel }}</span>
              <span class="shortcut-hint">←</span>
            </el-button>
            <el-button
              v-if="showNavigation"
              size="default"
              type="primary"
              round
              class="nav-button"
              :disabled="nextDisabled"
              @click="emit('next')"
            >
              <span>{{ nextLabel }}</span>
              <span class="shortcut-hint">→</span>
            </el-button>
            <el-radio-group v-model="selectedKlinePeriod" size="small" class="period-switch">
              <el-radio-button
                v-for="option in klinePeriodOptions"
                :key="option.value"
                :label="option.value"
                :disabled="!option.available"
              >
                <span class="period-button-label">
                  <span>{{ option.label }}</span>
                  <span class="shortcut-hint">{{ option.shortcut }}</span>
                </span>
              </el-radio-button>
            </el-radio-group>
          </div>

          <div class="quote-meta" v-if="showCommonMeta">
            <span class="meta-item">{{ stock.industry || '未知行业' }}</span>
            <span class="meta-item" :class="getPnlClass(stock.latest_pct_chg)">
              {{ formatSignedPct(stock.latest_pct_chg) }}
            </span>
            <span class="meta-item" :class="getPnlClass(stock.recent_30d_pct_chg)">
              30日 {{ formatSignedPct(stock.recent_30d_pct_chg) }}
            </span>
            <span class="meta-item">{{ stock.latest_price ? formatNumber(stock.latest_price) : '--' }}</span>
          </div>
        </div>
      </div>

      <div v-if="$slots.extraChips" class="extra-chip-group">
        <slot name="extraChips" />
      </div>
    </div>

    <div class="chart-wrap">
      <StockChart
        ref="chartRef"
        :data="selectedChartData"
        :ts-code="stock.ts_code"
        :markers="selectedChartMarkers"
        :preserve-zoom="preserveZoom"
        :initial-zoom-start="initialZoomStart"
        :initial-zoom-end="initialZoomEnd"
        :reset-zoom-on-ts-code-change="resetZoomOnTsCodeChange"
      />
    </div>

    <div v-if="$slots.footer" class="panel-footer">
      <slot name="footer" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import StockChart from '@/components/charts/StockChart.vue'
import type { StockDaily } from '@/api/types'

type KlinePeriod = 'daily' | 'weekly' | 'monthly'

interface ReviewChartStock {
  ts_code: string
  name?: string | null
  industry?: string | null
  latest_pct_chg?: number | null
  recent_30d_pct_chg?: number | null
  latest_price?: number | null
}

interface ReviewChartMarker {
  trade_date: string
  price?: number | null
  side?: string | null
  label?: string
  is_current?: boolean
}

const props = withDefaults(defineProps<{
  stock: ReviewChartStock
  daily: StockDaily[]
  weekly: StockDaily[]
  monthly: StockDaily[]
  markers?: ReviewChartMarker[]
  chartKey?: string
  preserveZoom?: boolean
  initialZoomStart?: number
  initialZoomEnd?: number
  resetZoomOnTsCodeChange?: boolean
  showCommonMeta?: boolean
  showNavigation?: boolean
  previousDisabled?: boolean
  nextDisabled?: boolean
  previousLabel?: string
  nextLabel?: string
  enableKeyboardShortcuts?: boolean
  showTitleBlock?: boolean
}>(), {
  markers: () => [],
  chartKey: '',
  preserveZoom: true,
  initialZoomStart: 70,
  initialZoomEnd: 100,
  resetZoomOnTsCodeChange: false,
  showCommonMeta: true,
  showNavigation: false,
  previousDisabled: false,
  nextDisabled: false,
  previousLabel: '上一只',
  nextLabel: '下一只',
  enableKeyboardShortcuts: true,
  showTitleBlock: true,
})

const emit = defineEmits<{
  previous: []
  next: []
}>()

const chartRef = ref<InstanceType<typeof StockChart> | null>(null)
const selectedKlinePeriod = ref<KlinePeriod>('daily')
const periodAvailability = computed<Record<KlinePeriod, boolean>>(() => ({
  daily: (props.daily?.length || 0) > 0,
  weekly: (props.weekly?.length || 0) > 0,
  monthly: (props.monthly?.length || 0) > 0,
}))

const klinePeriodOptions = computed(() => [
  { label: '日K', value: 'daily' as const, available: periodAvailability.value.daily, shortcut: 'R' },
  { label: '周K', value: 'weekly' as const, available: periodAvailability.value.weekly, shortcut: 'Z' },
  { label: '月K', value: 'monthly' as const, available: periodAvailability.value.monthly, shortcut: 'Y' },
])

const selectedChartData = computed<StockDaily[]>(() => {
  if (selectedKlinePeriod.value === 'weekly') return props.weekly || []
  if (selectedKlinePeriod.value === 'monthly') return props.monthly || []
  return props.daily || []
})

function pickFirstAvailablePeriod(): KlinePeriod {
  if (periodAvailability.value.daily) return 'daily'
  if (periodAvailability.value.weekly) return 'weekly'
  if (periodAvailability.value.monthly) return 'monthly'
  return 'daily'
}

function ensureValidSelectedPeriod(): void {
  if (periodAvailability.value[selectedKlinePeriod.value]) return
  selectedKlinePeriod.value = pickFirstAvailablePeriod()
}

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

function toTimestamp(value: string): number {
  const year = Number(value.slice(0, 4))
  const month = Number(value.slice(4, 6)) - 1
  const date = Number(value.slice(6, 8))
  return new Date(year, month, date).getTime()
}

function resolveMarkerCandle(
  candles: StockDaily[],
  normalizedTradeDate: string,
  period: KlinePeriod,
): StockDaily | null {
  if (!candles.length) return null

  const firstTradeDate = candles[0]?.trade_date
  const lastTradeDate = candles[candles.length - 1]?.trade_date
  if (!firstTradeDate || !lastTradeDate) return null

  // 超出当前可见区间的点不再强行吸附到边界 K 线上，避免多个点挤在一起。
  if (normalizedTradeDate < firstTradeDate || normalizedTradeDate > lastTradeDate) {
    return null
  }

  const exactMatch = candles.find((item) => item.trade_date === normalizedTradeDate)
  if (exactMatch) return exactMatch

  const nextCandle = candles.find((item) => item.trade_date >= normalizedTradeDate) || null
  if (!nextCandle) return null

  if (period !== 'daily') {
    return nextCandle
  }

  const nextIndex = candles.findIndex((item) => item.trade_date === nextCandle.trade_date)
  const previousCandle = nextIndex > 0 ? candles[nextIndex - 1] : null
  if (!previousCandle) return nextCandle

  const targetTs = toTimestamp(normalizedTradeDate)
  const previousDiff = Math.abs(targetTs - toTimestamp(previousCandle.trade_date))
  const nextDiff = Math.abs(toTimestamp(nextCandle.trade_date) - targetTs)

  return previousDiff <= nextDiff ? previousCandle : nextCandle
}

const selectedChartMarkers = computed(() => {
  const candles = [...(selectedChartData.value || [])].sort((a, b) => {
    return String(a.trade_date || '').localeCompare(String(b.trade_date || ''))
  })
  if (!props.markers?.length || !candles.length) return []

  return props.markers
    .map((marker) => {
      const normalizedTradeDate = normalizeTradeDateString(marker.trade_date)
      if (!normalizedTradeDate) return null

      const matched = resolveMarkerCandle(candles, normalizedTradeDate, selectedKlinePeriod.value)
      if (!matched) return null

      const markerPrice = Number(marker.price || matched.close || matched.open || 0)
      if (!markerPrice) return null

      return {
        trade_date: matched.trade_date,
        price: markerPrice,
        side: marker.side,
        label: marker.label,
        is_current: marker.is_current,
      }
    })
    .filter((item): item is NonNullable<typeof item> => item != null)
})

function formatNumber(value?: number | null): string {
  return Number(value || 0).toFixed(2)
}

function formatSignedPct(value?: number | null): string {
  if (value == null || Number.isNaN(Number(value))) return '--'
  const numeric = Number(value)
  return `${numeric > 0 ? '+' : ''}${numeric.toFixed(2)}%`
}

function getPnlClass(value?: number | null): string {
  if (value == null || Number.isNaN(Number(value))) return ''
  if (Number(value) > 0) return 'price-up'
  if (Number(value) < 0) return 'price-down'
  return ''
}

function zoomIn(): void {
  chartRef.value?.zoomIn?.()
}

function zoomOut(): void {
  chartRef.value?.zoomOut?.()
}

function isTypingElement(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null
  if (!element) return false
  const tagName = element.tagName?.toLowerCase()
  return tagName === 'input'
    || tagName === 'textarea'
    || !!element.closest('.el-input, .el-textarea, .el-select, .el-date-editor, .el-radio-group')
    || element.isContentEditable
}

function handleKeydown(event: KeyboardEvent): void {
  if (!props.enableKeyboardShortcuts || isTypingElement(event.target)) return

  const lowerKey = event.key.toLowerCase()

  if (lowerKey === 'r' && periodAvailability.value.daily) {
    event.preventDefault()
    selectedKlinePeriod.value = 'daily'
    return
  }

  if (lowerKey === 'z' && periodAvailability.value.weekly) {
    event.preventDefault()
    selectedKlinePeriod.value = 'weekly'
    return
  }

  if (lowerKey === 'y' && periodAvailability.value.monthly) {
    event.preventDefault()
    selectedKlinePeriod.value = 'monthly'
    return
  }

  if (event.key === 'ArrowLeft' && props.showNavigation && !props.previousDisabled) {
    event.preventDefault()
    emit('previous')
    return
  }

  if (event.key === 'ArrowRight' && props.showNavigation && !props.nextDisabled) {
    event.preventDefault()
    emit('next')
    return
  }

  if (event.key === 'ArrowUp') {
    event.preventDefault()
    zoomIn()
    return
  }

  if (event.key === 'ArrowDown') {
    event.preventDefault()
    zoomOut()
  }
}

onMounted(() => {
  ensureValidSelectedPeriod()
  window.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
})

watch(
  () => [
    props.stock.ts_code,
    props.chartKey,
    props.daily?.length || 0,
    props.weekly?.length || 0,
    props.monthly?.length || 0,
  ],
  () => {
    ensureValidSelectedPeriod()
  },
  { immediate: true },
)

defineExpose({
  zoomIn,
  zoomOut,
})
</script>

<style scoped lang="scss">
.review-chart-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.chart-meta {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 8px;
  color: var(--el-text-color-secondary);
}

.chart-toolbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.chart-title-block {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.chart-title-block strong {
  display: block;
  font-size: 20px;
  line-height: 1.2;
  color: var(--el-text-color-primary);
}

.chart-title-block span {
  font-size: 12px;
}

.toolbar-right {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 10px;
  min-width: 0;
}

.quote-meta,
.toolbar-actions,
.extra-chip-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.toolbar-actions {
  align-items: center;
  padding: 0;
}

.meta-item {
  font-size: 12px;
  line-height: 1.2;
  white-space: nowrap;
}

.period-button-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.shortcut-hint {
  margin-left: 6px;
  font-size: 11px;
  color: inherit;
  opacity: 0.72;
}

.extra-chip-group {
  min-height: 0;
}

.period-switch {
  flex-shrink: 0;
}

:deep(.toolbar-top-button),
.nav-button {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

:deep(.toolbar-top-button .el-button__text),
.nav-button .el-button__text {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

:deep(.period-switch .el-radio-button__inner) {
  font-weight: 600;
}

.price-up {
  color: #dc2626;
}

.price-down {
  color: #059669;
}

.chart-wrap {
  flex: 0 0 auto;
  height: clamp(560px, 66vh, 760px);
  min-height: 560px;
  min-width: 0;
  overflow: hidden;
}

.chart-wrap :deep(.stock-chart),
.chart-wrap :deep(.echarts) {
  height: 100%;
}

.panel-footer {
  margin-top: 16px;
  min-height: 0;
}

@media (max-width: 960px) {
  .chart-toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .toolbar-right {
    align-items: flex-start;
  }

  .quote-meta,
  .toolbar-actions,
  .extra-chip-group {
    justify-content: flex-start;
  }
}
</style>
