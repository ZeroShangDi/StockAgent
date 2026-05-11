<template>
  <div class="review-chart-panel">
    <div class="chart-meta">
      <div class="chart-title-block">
        <div>
          <strong>{{ stock.name || stock.ts_code }}</strong>
          <span>{{ stock.ts_code }}</span>
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

      <div class="trade-chip-group">
        <span class="trade-chip">{{ stock.industry || '未知行业' }}</span>
        <span class="trade-chip" :class="getPnlClass(stock.latest_pct_chg)">
          {{ formatSignedPct(stock.latest_pct_chg) }}
        </span>
        <span class="trade-chip" :class="getPnlClass(stock.recent_30d_pct_chg)">
          近30日 {{ formatSignedPct(stock.recent_30d_pct_chg) }}
        </span>
        <span class="trade-chip">{{ stock.latest_price ? formatNumber(stock.latest_price) : '--' }}</span>
      </div>

      <div v-if="$slots.extraChips" class="trade-chip-group">
        <slot name="extraChips" />
      </div>
    </div>

    <div class="chart-wrap">
      <StockChart
        ref="chartRef"
        :key="chartKey"
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
import { computed, ref } from 'vue'

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
}>(), {
  markers: () => [],
  chartKey: '',
  preserveZoom: true,
  initialZoomStart: 70,
  initialZoomEnd: 100,
  resetZoomOnTsCodeChange: false,
})

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
  gap: 12px;
  margin-bottom: 12px;
  color: var(--el-text-color-secondary);
}

.chart-title-block {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
}

.chart-title-block strong {
  display: block;
  font-size: 20px;
  color: var(--el-text-color-primary);
}

.trade-chip-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.trade-chip {
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(59, 130, 246, 0.08);
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
</style>
