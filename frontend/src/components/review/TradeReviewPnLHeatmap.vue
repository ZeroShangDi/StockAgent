<template>
  <section class="treemap-panel" v-loading="loading">
    <header class="treemap-header">
      <div>
        <p class="eyebrow">PnL Map</p>
        <h3>股票盈亏矩形地图</h3>
        <p class="description">
          用类似 webpack-bundle-analyzer 的矩形树图展示全部股票盈亏。每个矩形代表一只股票，面积越大代表影响越大，颜色越深代表盈亏越强。
        </p>
      </div>

      <div class="treemap-controls">
        <el-segmented
          v-model="scopeMode"
          :options="scopeOptions"
        />
        <el-select v-model="sizeMetric" class="control-select">
          <el-option
            v-for="option in sizeMetricOptions"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
      </div>
    </header>

    <div v-if="ranking.length" class="treemap-meta-row">
      <span class="meta-pill">股票 {{ filteredRanking.length }} 只</span>
      <span class="meta-pill">盈利 {{ filteredProfitCount }} 只</span>
      <span class="meta-pill">亏损 {{ filteredLossCount }} 只</span>
      <span class="meta-pill">净盈亏 {{ formatSignedAmount(filteredNetTotal) }}</span>
      <span class="meta-pill">面积 {{ currentSizeMetricLabel }}</span>
    </div>

    <div v-if="filteredRanking.length" class="treemap-card">
      <VChart
        class="treemap-chart"
        :option="chartOption"
        autoresize
        @click="handleChartClick"
      />
    </div>

    <div v-if="filteredRanking.length" class="treemap-hint">
      <span>提示：鼠标滚轮可缩放，拖动画布可平移；点击单个股票矩形可直接进入该股沉浸式复盘。</span>
    </div>

    <el-empty v-else description="当前范围暂无股票盈亏数据" />
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { TreemapChart } from 'echarts/charts'
import {
  TooltipComponent,
  TitleComponent,
} from 'echarts/components'

import { useThemeStore } from '@/stores'
import type { TradeReviewStatsResult } from '@/api/modules/trade-review'

use([
  CanvasRenderer,
  TreemapChart,
  TooltipComponent,
  TitleComponent,
])

type RankingItem = TradeReviewStatsResult['stock_pnl_ranking'][number]
type SizeMetric = 'abs_net_pnl' | 'trade_count' | 'market_value'
type ScopeMode = 'all' | 'profit' | 'loss'

const props = withDefaults(defineProps<{
  ranking: RankingItem[]
  loading?: boolean
}>(), {
  loading: false,
})

const emit = defineEmits<{
  (e: 'open-stock', payload: { item: RankingItem; summaryTsCodes: string[] }): void
}>()

const themeStore = useThemeStore()

const sizeMetric = ref<SizeMetric>('abs_net_pnl')
const scopeMode = ref<ScopeMode>('all')

const sizeMetricOptions = [
  { label: '面积按总盈亏绝对值', value: 'abs_net_pnl' },
  { label: '面积按成交笔数', value: 'trade_count' },
  { label: '面积按持仓市值', value: 'market_value' },
]
const scopeOptions = [
  { label: '全部', value: 'all' },
  { label: '只看盈利', value: 'profit' },
  { label: '只看亏损', value: 'loss' },
]

const currentSizeMetricLabel = computed(() => {
  return sizeMetricOptions.find((item) => item.value === sizeMetric.value)?.label || '-'
})

const filteredRanking = computed(() => {
  if (scopeMode.value === 'profit') {
    return props.ranking.filter((item) => Number(item.net_pnl || 0) > 0)
  }
  if (scopeMode.value === 'loss') {
    return props.ranking.filter((item) => Number(item.net_pnl || 0) < 0)
  }
  return props.ranking
})

const filteredProfitCount = computed(() => filteredRanking.value.filter((item) => Number(item.net_pnl || 0) > 0).length)
const filteredLossCount = computed(() => filteredRanking.value.filter((item) => Number(item.net_pnl || 0) < 0).length)
const filteredNetTotal = computed(() => filteredRanking.value.reduce((sum, item) => sum + Number(item.net_pnl || 0), 0))
const summaryTsCodes = computed(() => filteredRanking.value.map((item) => item.ts_code))

const maxAbsPnl = computed(() => {
  return Math.max(1, ...filteredRanking.value.map((item) => Math.abs(Number(item.net_pnl || 0))))
})

const palette = computed(() => {
  const isDark = themeStore.isDark
  return {
    text: isDark ? '#e2e8f0' : '#172033',
    subText: isDark ? '#94a3b8' : '#5b6475',
    border: isDark ? '#0f172a' : '#ffffff',
    cardBg: isDark ? 'rgba(15, 23, 42, 0.92)' : 'rgba(255, 255, 255, 0.94)',
    tooltipBg: isDark ? 'rgba(15, 23, 42, 0.96)' : 'rgba(255, 255, 255, 0.98)',
    tooltipBorder: isDark ? '#334155' : '#dbe4f0',
    profitBase: isDark ? [251, 113, 133] : [220, 38, 38],
    lossBase: isDark ? [16, 185, 129] : [5, 150, 105],
    flatBase: isDark ? [71, 85, 105] : [203, 213, 225],
    panelGradient: isDark
      ? 'radial-gradient(circle at top right, rgba(59, 130, 246, 0.12), transparent 28%), linear-gradient(180deg, rgba(15, 23, 42, 0.96), rgba(15, 23, 42, 0.88))'
      : 'radial-gradient(circle at top right, rgba(59, 130, 246, 0.08), transparent 28%), linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.98))',
  }
})

const treemapData = computed(() => {
  return filteredRanking.value
    .map((item) => {
      const pnl = Number(item.net_pnl || 0)
      return {
        name: item.name || item.code || item.ts_code,
        value: getNodeValue(item),
        pnl,
        item,
        itemStyle: {
          color: getNodeColor(pnl),
        },
        label: {
          color: '#ffffff',
        },
      }
    })
    .sort((left, right) => Number(right.value || 0) - Number(left.value || 0))
})

const chartOption = computed(() => {
  const showDenseLabel = filteredRanking.value.length <= 90
  return {
    animation: false,
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      backgroundColor: palette.value.tooltipBg,
      borderColor: palette.value.tooltipBorder,
      borderWidth: 1,
      textStyle: {
        color: palette.value.text,
      },
      formatter: (params: any) => {
        const stock = params?.data?.item as RankingItem | undefined
        if (!stock) {
          return `<strong>${params?.name || ''}</strong>`
        }
        return [
          `<strong>${stock.name || stock.code}</strong>`,
          `${stock.ts_code}`,
          `总盈亏：${formatSignedAmount(stock.net_pnl)}`,
          `已实现：${formatSignedAmount(stock.realized_pnl)}`,
          `浮动：${formatSignedAmount(stock.unrealized_pnl)}`,
          `收益率：${formatPercent(stock.net_pnl_pct)}`,
          `成交笔数：${stock.trade_count}`,
          `剩余持仓：${stock.position_quantity}`,
        ].join('<br/>')
      },
    },
    series: [
      {
        type: 'treemap',
        roam: true,
        nodeClick: false,
        breadcrumb: {
          show: false,
        },
        visibleMin: 1,
        sort: 'desc',
        left: 8,
        right: 8,
        top: 8,
        bottom: 8,
        data: treemapData.value,
        label: {
          show: true,
          formatter: (params: any) => {
            const stock = params?.data?.item as RankingItem | undefined
            if (!stock) return params.name
            if (!showDenseLabel) return `${stock.name || stock.code}`
            return `${stock.name || stock.code}\n${stock.ts_code}\n${formatCompactAmount(stock.net_pnl)}`
          },
          overflow: 'truncate',
          fontSize: showDenseLabel ? 13 : 12,
          fontWeight: 600,
        },
        itemStyle: {
          borderColor: palette.value.border,
          borderWidth: 2,
          gapWidth: 2,
        },
        emphasis: {
          itemStyle: {
            borderColor: '#f8fafc',
            borderWidth: 3,
            shadowBlur: 12,
            shadowColor: 'rgba(15, 23, 42, 0.22)',
          },
        },
      },
    ],
  }
})

function getNodeValue(item: RankingItem): number {
  if (sizeMetric.value === 'trade_count') {
    return Math.max(1, Number(item.trade_count || 0))
  }
  if (sizeMetric.value === 'market_value') {
    return Math.max(1, Number(item.market_value || 0))
  }
  return Math.max(1, Math.abs(Number(item.net_pnl || 0)))
}

function getNodeColor(pnlValue: number): string {
  const maxAbs = maxAbsPnl.value
  const ratio = Math.min(1, Math.abs(Number(pnlValue || 0)) / maxAbs)

  if (pnlValue > 0) {
    return rgbaFromBase(palette.value.profitBase, 0.35 + ratio * 0.55)
  }
  if (pnlValue < 0) {
    return rgbaFromBase(palette.value.lossBase, 0.35 + ratio * 0.55)
  }
  return rgbaFromBase(palette.value.flatBase, 0.55)
}

function rgbaFromBase(base: number[], alpha: number): string {
  return `rgba(${base[0]}, ${base[1]}, ${base[2]}, ${alpha.toFixed(3)})`
}

function handleChartClick(params: any): void {
  const stock = params?.data?.item as RankingItem | undefined
  if (!stock) return
  emit('open-stock', {
    item: stock,
    summaryTsCodes: summaryTsCodes.value,
  })
}

function formatAmount(value?: number | null): string {
  return Number(value || 0).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

function formatSignedAmount(value?: number | null): string {
  const amount = Number(value || 0)
  return `${amount > 0 ? '+' : ''}${formatAmount(amount)}`
}

function formatCompactAmount(value?: number | null): string {
  const amount = Number(value || 0)
  const absAmount = Math.abs(amount)
  if (absAmount >= 100000000) return `${amount > 0 ? '+' : ''}${(amount / 100000000).toFixed(1)}亿`
  if (absAmount >= 10000) return `${amount > 0 ? '+' : ''}${(amount / 10000).toFixed(1)}万`
  return `${amount > 0 ? '+' : ''}${amount.toFixed(0)}`
}

function formatPercent(value?: number | null): string {
  const amount = Number(value || 0)
  return `${amount > 0 ? '+' : ''}${amount.toFixed(2)}%`
}

</script>

<style scoped lang="scss">
.treemap-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.treemap-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 18px;
}

.eyebrow {
  margin: 0 0 6px;
  font-size: 12px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--el-color-primary);
}

.treemap-header h3 {
  margin: 0 0 8px;
  font-size: 24px;
}

.description {
  margin: 0;
  color: var(--el-text-color-secondary);
  line-height: 1.7;
  max-width: 760px;
}

.treemap-controls {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.control-select {
  width: 200px;
}

.treemap-meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.meta-pill {
  padding: 8px 12px;
  border-radius: 999px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: rgba(248, 250, 252, 0.92);
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.treemap-card {
  border-radius: 22px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background:
    radial-gradient(circle at top right, rgba(59, 130, 246, 0.08), transparent 28%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.98));
  padding: 8px;
}

.treemap-chart {
  width: 100%;
  height: min(76vh, 900px);
}

.treemap-hint {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

@media (max-width: 1100px) {
  .treemap-header {
    flex-direction: column;
  }

  .treemap-controls {
    width: 100%;
    justify-content: flex-start;
  }

  .treemap-chart {
    height: 620px;
  }
}

@media (max-width: 720px) {
  .treemap-chart {
    height: 520px;
  }
}
</style>
