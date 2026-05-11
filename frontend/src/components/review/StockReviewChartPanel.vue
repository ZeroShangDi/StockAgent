<template>
  <div class="review-chart-panel">
    <div class="chart-meta">
      <div class="chart-toolbar">
        <div class="chart-title-block">
          <strong>{{ stock.name || stock.ts_code }}</strong>
          <span>{{ stock.ts_code }}</span>
        </div>

        <div class="toolbar-right">
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

          <div class="toolbar-actions">
            <el-button
              v-if="showNavigation"
              size="small"
              text
              :disabled="previousDisabled"
              @click="emit('previous')"
            >
              {{ previousLabel }}
            </el-button>
            <el-button
              v-if="showNavigation"
              size="small"
              text
              :disabled="nextDisabled"
              @click="emit('next')"
            >
              {{ nextLabel }}
            </el-button>
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
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

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
})

const emit = defineEmits<{
  previous: []
  next: []
}>()

const chartRef = ref<InstanceType<typeof StockChart> | null>(null)
const selectedKlinePeriod = ref<KlinePeriod>('daily')
const klinePeriodOptions = [
  { label: '日K', value: 'daily' },
  { label: '周K', value: 'weekly' },
  { label: '月K', value: 'monthly' },
] as const

const selectedChartData = computed<StockDaily[]>(() => {
  if (selectedKlinePeriod.value === 'weekly') return props.weekly || []
  if (selectedKlinePeriod.value === 'monthly') return props.monthly || []
  return props.daily || []
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
  window.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
})

defineExpose({
  zoomIn,
  zoomOut,
})
</script>

<style scoped lang="scss">
.review-chart-panel {
  display: flex;
  flex-direction: column;
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
  gap: 6px;
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

.meta-item {
  font-size: 12px;
  line-height: 1.2;
  white-space: nowrap;
}

.extra-chip-group {
  min-height: 0;
}

.period-switch {
  flex-shrink: 0;
}

.price-up {
  color: #dc2626;
}

.price-down {
  color: #059669;
}

.chart-wrap {
  flex: 1;
  min-height: 0;
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
