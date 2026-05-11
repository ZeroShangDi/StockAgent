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
              <kbd>←</kbd>
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
              <kbd>→</kbd>
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
                  <kbd>{{ option.shortcut }}</kbd>
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

const selectedChartMarkers = computed(() => {
  const candles = selectedChartData.value || []
  if (!props.markers?.length || !candles.length) return []

  return props.markers
    .map((marker) => {
      const normalizedTradeDate = normalizeTradeDateString(marker.trade_date)
      if (!normalizedTradeDate) return null

      const matched =
        candles.find((item) => item.trade_date >= normalizedTradeDate)
        || [...candles].reverse().find((item) => item.trade_date <= normalizedTradeDate)
        || null

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

.period-button-label kbd,
.nav-button kbd {
  min-width: 18px;
  padding: 0 4px;
  border-radius: 6px;
  background: rgba(15, 23, 42, 0.06);
  color: var(--el-text-color-secondary);
  font-size: 11px;
  line-height: 18px;
  text-align: center;
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
  min-height: 40px;
  padding: 0 16px;
  border-radius: 999px;
  font-weight: 600;
  border: none;
  box-shadow: 0 8px 18px rgba(37, 99, 235, 0.18);
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease, background 0.18s ease;
}

:deep(.toolbar-top-button:hover),
.nav-button:hover {
  transform: translateY(-1px);
  box-shadow: 0 12px 24px rgba(37, 99, 235, 0.24);
}

:deep(.toolbar-top-button.is-disabled),
.nav-button.is-disabled {
  box-shadow: none;
}

:deep(.toolbar-top-button.el-button--primary),
.nav-button.el-button--primary {
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  color: #fff;
}

:deep(.toolbar-top-button.el-button--primary:hover),
.nav-button.el-button--primary:hover {
  background: linear-gradient(135deg, #4f8df7, #2d6df0);
}

:deep(.toolbar-top-button.el-button--primary.is-disabled),
.nav-button.el-button--primary.is-disabled {
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.45), rgba(37, 99, 235, 0.45));
  box-shadow: none;
}

:deep(.toolbar-top-button .el-button__text),
.nav-button .el-button__text {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

:deep(.toolbar-top-button .button-shortcut),
.nav-button kbd,
.period-button-label kbd {
  background: rgba(255, 255, 255, 0.18);
  color: inherit;
}

:deep(.period-switch .el-radio-button__inner) {
  min-height: 40px;
  padding: 0 14px;
  border: none;
  border-radius: 999px !important;
  background: rgba(255, 255, 255, 0.82);
  box-shadow: 0 6px 14px rgba(15, 23, 42, 0.06) !important;
  color: #475569;
  font-weight: 600;
}

:deep(.period-switch .el-radio-button__inner:hover) {
  color: #0f172a;
}

:deep(.period-switch .el-radio-button:first-child .el-radio-button__inner),
:deep(.period-switch .el-radio-button:last-child .el-radio-button__inner) {
  border-radius: 999px !important;
}

:deep(.period-switch .el-radio-button__original-radio:checked + .el-radio-button__inner) {
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  border-color: transparent;
  color: #fff;
  box-shadow: 0 10px 22px rgba(37, 99, 235, 0.24);
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
