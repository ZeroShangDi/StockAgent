<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { CandlestickChart, LineChart, BarChart, ScatterChart } from 'echarts/charts'
import {
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent,
  DataZoomComponent,
} from 'echarts/components'
import { useThemeStore } from '@/stores'
import type { StockDaily } from '@/api'

interface StockChartMarker {
  record_id?: string
  trade_date: string
  price: number
  side?: string | null
  label?: string
  is_current?: boolean
}

// 注册 ECharts 组件
use([
  CanvasRenderer,
  CandlestickChart,
  LineChart,
  BarChart,
  ScatterChart,
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent,
  DataZoomComponent,
])

const props = defineProps<{
  data: StockDaily[]
  tsCode: string
  preserveZoom?: boolean
  initialZoomStart?: number
  initialZoomEnd?: number
  markers?: StockChartMarker[]
  resetZoomOnTsCodeChange?: boolean
}>()

const themeStore = useThemeStore()
const chartRef = ref<InstanceType<typeof VChart> | null>(null)
const zoomRange = ref<{ start: number; end: number } | null>(null)
const axisPointerTradeDate = ref<string | null>(null)

const sortedData = computed(() => {
  return [...(props.data || [])].sort((a, b) => a.trade_date.localeCompare(b.trade_date))
})

const tradeDates = computed(() => sortedData.value.map((item) => item.trade_date))

watch(
  () => props.tsCode,
  () => {
    axisPointerTradeDate.value = null
    if (props.resetZoomOnTsCodeChange !== false) {
      zoomRange.value = null
    }
  }
)

function handleDataZoom(event: { start?: number; end?: number; batch?: Array<{ start?: number; end?: number }> }): void {
  if (!props.preserveZoom) {
    return
  }

  const payload = event?.batch?.[0] ?? event
  if (typeof payload?.start === 'number' && typeof payload?.end === 'number') {
    zoomRange.value = {
      start: payload.start,
      end: payload.end,
    }
  }
}

function handleAxisPointer(event: { axesInfo?: Array<{ value?: string | number }> }): void {
  const axisValue = event?.axesInfo?.[0]?.value
  axisPointerTradeDate.value = axisValue == null ? null : String(axisValue)
}

function handleGlobalOut(): void {
  axisPointerTradeDate.value = null
}

function getChartInstance(): any {
  return (chartRef.value as any)?.chart
}

function bindChartEvents(): void {
  const chart = getChartInstance()
  if (!chart) return

  chart.off('updateAxisPointer', handleAxisPointer)
  chart.off('globalout', handleGlobalOut)
  chart.on('updateAxisPointer', handleAxisPointer)
  chart.on('globalout', handleGlobalOut)
}

onMounted(async () => {
  await nextTick()
  bindChartEvents()
})

watch(
  () => props.data,
  async () => {
    await nextTick()
    bindChartEvents()
  }
)

onBeforeUnmount(() => {
  const chart = getChartInstance()
  if (!chart) return
  chart.off('updateAxisPointer', handleAxisPointer)
  chart.off('globalout', handleGlobalOut)
})

function getDefaultZoom(): { start: number; end: number } {
  return {
    start: props.initialZoomStart ?? 70,
    end: props.initialZoomEnd ?? 100,
  }
}

function normalizeZoom(range: { start: number; end: number }): { start: number; end: number } {
  let start = Math.max(0, Math.min(100, Number(range.start)))
  let end = Math.max(0, Math.min(100, Number(range.end)))

  if (end <= start) {
    end = Math.min(100, start + 5)
    start = Math.max(0, end - 5)
  }

  return { start, end }
}

function setZoom(range: { start: number; end: number }): void {
  zoomRange.value = normalizeZoom(range)
}

function zoomByFactor(factor: number): void {
  const dates = tradeDates.value
  if (!props.preserveZoom || dates.length === 0) return

  const base = zoomRange.value ?? getDefaultZoom()
  const currentSpan = Math.max(5, Math.min(100, base.end - base.start))
  const targetSpan = Math.max(5, Math.min(100, Number((currentSpan * factor).toFixed(2))))

  if (!axisPointerTradeDate.value) {
    setZoom({
      start: Math.max(0, 100 - targetSpan),
      end: 100,
    })
    return
  }

  const focusIndex = dates.findIndex((item) => item === axisPointerTradeDate.value)
  if (focusIndex === -1 || dates.length === 1) {
    setZoom({
      start: Math.max(0, 100 - targetSpan),
      end: 100,
    })
    return
  }

  const anchorPct = (focusIndex / (dates.length - 1)) * 100
  let start = anchorPct - targetSpan / 2
  let end = anchorPct + targetSpan / 2

  if (start < 0) {
    end = Math.min(100, end - start)
    start = 0
  }
  if (end > 100) {
    start = Math.max(0, start - (end - 100))
    end = 100
  }

  setZoom({ start, end })
}

function zoomIn(): void {
  zoomByFactor(0.8)
}

function zoomOut(): void {
  zoomByFactor(1.25)
}

defineExpose({
  zoomIn,
  zoomOut,
  resetZoom: () => {
    zoomRange.value = null
  },
})

// 主题相关颜色
const themeColors = computed(() => {
  const isDark = themeStore.isDark
  
  return {
    // 涨跌色
    upColor: isDark ? '#ff5a6a' : '#f23645',
    downColor: isDark ? '#26a69a' : '#089981',
    // 背景和文字
    tooltipBg: isDark ? 'rgba(30, 41, 59, 0.96)' : 'rgba(255, 255, 255, 0.96)',
    tooltipBorder: isDark ? '#475569' : '#e2e8f0',
    tooltipText: isDark ? '#f1f5f9' : '#1e293b',
    // 坐标轴
    axisLine: isDark ? '#334155' : '#e2e8f0',
    axisLabel: isDark ? '#94a3b8' : '#64748b',
    splitLine: isDark ? '#1e293b' : '#f1f5f9',
    // 图例
    legendText: isDark ? '#cbd5e1' : '#475569',
    // DataZoom
    zoomBg: isDark ? '#1e293b' : '#f1f5f9',
    zoomDataLine: isDark ? '#64748b' : '#94a3b8',
    zoomHandleBorder: isDark ? '#60a5fa' : '#3b82f6',
    zoomHandleShadow: isDark ? 'rgba(96, 165, 250, 0.4)' : 'rgba(59, 130, 246, 0.3)',
    zoomText: isDark ? '#94a3b8' : '#64748b',
    zoomMoveHandle: isDark ? '#64748b' : '#94a3b8',
  }
})

// 图表选项
const option = computed(() => {
  if (!props.data || props.data.length === 0) {
    return {}
  }
  
  const colors = themeColors.value
  
  // 日期
  const dates = tradeDates.value
  const dailyData = sortedData.value
  
  // K线数据 [开, 收, 低, 高]
  const klineData = dailyData.map((d) => [d.open, d.close, d.low, d.high])
  
  // 成交量
  const volumes = dailyData.map((d) => ({
    value: d.vol,
    itemStyle: {
      color: d.close >= d.open ? colors.upColor : colors.downColor,
    },
  }))
  
  // MA 计算
  const ma5 = calculateMA(dailyData, 5)
  const ma10 = calculateMA(dailyData, 10)
  const ma20 = calculateMA(dailyData, 20)
  const ma60 = calculateMA(dailyData, 60)
  const ma260 = calculateMA(dailyData, 260)
  const macd = calculateMACD(dailyData)
  const markers = (props.markers || [])
    .filter((item) => item.trade_date && typeof item.price === 'number')
    .map((item) => ({
      name: item.label || (item.side === 'buy' ? '买点' : item.side === 'sell' ? '卖点' : '标记'),
      value: [item.trade_date, item.price],
      symbol: 'circle',
      symbolSize: item.is_current ? 10 : 8,
      itemStyle: {
        color: item.is_current ? (item.side === 'buy' ? '#ef4444' : item.side === 'sell' ? '#10b981' : '#3b82f6') : '#ffffff',
        borderColor: item.side === 'buy' ? '#ef4444' : item.side === 'sell' ? '#10b981' : '#3b82f6',
        borderWidth: item.is_current ? 2.5 : 2,
        shadowBlur: item.is_current ? 8 : 4,
        shadowColor: item.side === 'buy' ? 'rgba(239, 68, 68, 0.4)' : item.side === 'sell' ? 'rgba(16, 185, 129, 0.4)' : 'rgba(59, 130, 246, 0.35)',
      },
      label: {
        show: true,
        formatter: item.label || (item.side === 'buy' ? '买' : item.side === 'sell' ? '卖' : '标'),
        position: item.side === 'buy' ? 'top' : 'bottom',
        distance: 6,
        fontSize: item.is_current ? 11 : 10,
        fontWeight: item.is_current ? 600 : 500,
        color: item.side === 'buy' ? '#b91c1c' : item.side === 'sell' ? '#047857' : colors.tooltipText,
        backgroundColor: 'rgba(255,255,255,0.88)',
        borderColor: item.side === 'buy' ? 'rgba(239, 68, 68, 0.28)' : item.side === 'sell' ? 'rgba(16, 185, 129, 0.28)' : colors.tooltipBorder,
        borderWidth: 1,
        borderRadius: 6,
        padding: [2, 5],
      },
      tooltip: {
        valueFormatter: () => `${item.label || ''} ${item.price}`,
      },
      emphasis: {
        scale: 1.4,
      },
    }))
  const defaultZoom = getDefaultZoom()
  const zoom = props.preserveZoom && zoomRange.value
    ? zoomRange.value
    : defaultZoom
  
  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        type: 'cross',
        crossStyle: {
          color: colors.axisLabel,
        },
      },
      backgroundColor: colors.tooltipBg,
      borderColor: colors.tooltipBorder,
      textStyle: {
        color: colors.tooltipText,
      },
    },
    legend: {
      data: ['K线', 'MA5', 'MA10', 'MA20', 'MA60', 'MA260', 'DIF', 'DEA', 'MACD'],
      top: 10,
      textStyle: {
        color: colors.legendText,
      },
    },
    grid: [
      {
        left: 60,
        right: 20,
        top: 50,
        height: '46%',
      },
      {
        left: 60,
        right: 20,
        top: '60%',
        height: '12%',
      },
      {
        left: 60,
        right: 20,
        top: '78%',
        height: '12%',
      },
    ],
    xAxis: [
      {
        type: 'category',
        data: dates,
        boundaryGap: false,
        axisLine: { lineStyle: { color: colors.axisLine } },
        axisTick: { show: false },
        axisLabel: { color: colors.axisLabel },
        splitLine: { show: false },
      },
      {
        type: 'category',
        gridIndex: 1,
        data: dates,
        boundaryGap: false,
        axisLabel: { show: false },
        axisTick: { show: false },
        axisLine: { lineStyle: { color: colors.axisLine } },
        splitLine: { show: false },
      },
      {
        type: 'category',
        gridIndex: 2,
        data: dates,
        boundaryGap: false,
        axisLabel: { color: colors.axisLabel },
        axisTick: { show: false },
        axisLine: { lineStyle: { color: colors.axisLine } },
        splitLine: { show: false },
      },
    ],
    yAxis: [
      {
        scale: true,
        splitArea: { show: false },
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: colors.axisLabel },
        splitLine: { lineStyle: { color: colors.splitLine } },
      },
      {
        scale: true,
        gridIndex: 1,
        splitNumber: 2,
        axisLabel: { show: false },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
      },
      {
        scale: true,
        gridIndex: 2,
        splitNumber: 3,
        axisLabel: { color: colors.axisLabel },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { lineStyle: { color: colors.splitLine } },
      },
    ],
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: [0, 1, 2],
        start: zoom.start,
        end: zoom.end,
      },
      {
        show: true,
        xAxisIndex: [0, 1, 2],
        type: 'slider',
        bottom: 8,
        start: zoom.start,
        end: zoom.end,
        height: 28,
        borderColor: 'transparent',
        backgroundColor: colors.zoomBg,
        borderRadius: 6,
        // 数据阴影
        dataBackground: {
          lineStyle: {
            color: colors.zoomDataLine,
            width: 1,
          },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(59, 130, 246, 0.3)' },
                { offset: 1, color: 'rgba(59, 130, 246, 0.05)' },
              ],
            },
          },
        },
        // 选中区域
        selectedDataBackground: {
          lineStyle: {
            color: colors.zoomHandleBorder,
            width: 1.5,
          },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(59, 130, 246, 0.5)' },
                { offset: 1, color: 'rgba(59, 130, 246, 0.1)' },
              ],
            },
          },
        },
        // 填充色
        fillerColor: 'rgba(59, 130, 246, 0.15)',
        // 左右手柄
        handleIcon: 'path://M-9.5,0a9.5,9.5,0,1,0,19,0a9.5,9.5,0,1,0,-19,0M-5,0a5,5,0,1,0,10,0a5,5,0,1,0,-10,0M-2,0a2,2,0,1,0,4,0a2,2,0,1,0,-4,0',
        handleSize: '120%',
        handleStyle: {
          color: themeStore.isDark ? '#1e293b' : '#fff',
          borderColor: colors.zoomHandleBorder,
          borderWidth: 2,
          shadowBlur: 6,
          shadowColor: colors.zoomHandleShadow,
          shadowOffsetX: 0,
          shadowOffsetY: 2,
        },
        // 两端样式
        brushStyle: {
          color: 'rgba(59, 130, 246, 0.2)',
        },
        // 移动时的样式
        moveHandleSize: 6,
        moveHandleStyle: {
          color: colors.zoomMoveHandle,
          borderColor: 'transparent',
        },
        // 强调样式
        emphasis: {
          handleStyle: {
            borderColor: '#2563eb',
            shadowBlur: 10,
            shadowColor: 'rgba(59, 130, 246, 0.5)',
          },
          moveHandleStyle: {
            color: '#3b82f6',
          },
        },
        // 文本样式
        textStyle: {
          color: colors.zoomText,
          fontSize: 11,
        },
        // 边框
        brushSelect: false,
      },
    ],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: klineData,
        itemStyle: {
          color: colors.upColor,
          color0: colors.downColor,
          borderColor: colors.upColor,
          borderColor0: colors.downColor,
        },
      },
      {
        name: 'MA5',
        type: 'line',
        data: ma5,
        smooth: true,
        lineStyle: { width: 1.5 },
        symbol: 'none',
        itemStyle: { color: '#3b82f6' },
      },
      {
        name: 'MA10',
        type: 'line',
        data: ma10,
        smooth: true,
        lineStyle: { width: 1.5 },
        symbol: 'none',
        itemStyle: { color: '#22c55e' },
      },
      {
        name: 'MA20',
        type: 'line',
        data: ma20,
        smooth: true,
        lineStyle: { width: 1.5 },
        symbol: 'none',
        itemStyle: { color: '#f59e0b' },
      },
      {
        name: 'MA60',
        type: 'line',
        data: ma60,
        smooth: true,
        lineStyle: { width: 1.3 },
        symbol: 'none',
        itemStyle: { color: '#8b5cf6' },
      },
      {
        name: 'MA260',
        type: 'line',
        data: ma260,
        smooth: true,
        lineStyle: { width: 1.3 },
        symbol: 'none',
        itemStyle: { color: '#14b8a6' },
      },
      {
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumes,
      },
      {
        name: 'DIF',
        type: 'line',
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: macd.dif,
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 1.4 },
        itemStyle: { color: '#2563eb' },
      },
      {
        name: 'DEA',
        type: 'line',
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: macd.dea,
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 1.4 },
        itemStyle: { color: '#f97316' },
      },
      {
        name: 'MACD',
        type: 'bar',
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: macd.bar.map((value) => ({
          value,
          itemStyle: {
            color: value >= 0 ? colors.upColor : colors.downColor,
          },
        })),
      },
      {
        name: '买卖点',
        type: 'scatter',
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: markers,
        z: 20,
        zlevel: 2,
        tooltip: {
          trigger: 'item',
        },
      },
    ],
  }
})

// 计算移动平均线
function calculateMA(data: StockDaily[], period: number): (number | '-')[] {
  const result: (number | '-')[] = []
  
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) {
      result.push('-')
    } else {
      let sum = 0
      for (let j = 0; j < period; j++) {
        sum += data[i - j].close
      }
      result.push(Number((sum / period).toFixed(2)))
    }
  }
  
  return result
}

function calculateMACD(data: StockDaily[]): {
  dif: number[]
  dea: number[]
  bar: number[]
} {
  const dif: number[] = []
  const dea: number[] = []
  const bar: number[] = []

  let ema12 = 0
  let ema26 = 0
  let signal = 0

  data.forEach((item, index) => {
    const close = Number(item.close || 0)
    if (index === 0) {
      ema12 = close
      ema26 = close
      signal = 0
    } else {
      ema12 = ema12 * (11 / 13) + close * (2 / 13)
      ema26 = ema26 * (25 / 27) + close * (2 / 27)
    }

    const currentDif = ema12 - ema26
    signal = index === 0 ? currentDif : signal * (8 / 10) + currentDif * (2 / 10)
    const currentBar = (currentDif - signal) * 2

    dif.push(Number(currentDif.toFixed(4)))
    dea.push(Number(signal.toFixed(4)))
    bar.push(Number(currentBar.toFixed(4)))
  })

  return { dif, dea, bar }
}
</script>

<template>
  <div class="stock-chart">
    <VChart
      v-if="data.length > 0"
      ref="chartRef"
      :option="option"
      autoresize
      @datazoom="handleDataZoom"
    />
    <el-empty v-else description="暂无K线数据" />
  </div>
</template>

<style lang="scss" scoped>
.stock-chart {
  width: 100%;
  height: 100%;
  min-height: 520px;
  min-width: 0;
  overflow: hidden;
}

.stock-chart :deep(.echarts),
.stock-chart :deep(canvas) {
  max-width: 100%;
}
</style>
