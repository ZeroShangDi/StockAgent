<template>
  <div class="weather-page">
    <section class="hero-card">
      <div class="hero-copy">
        <p class="eyebrow">Market Weather</p>
        <div class="hero-headline">
          <div>
            <h1>市场晴雨表</h1>
            <p class="description">
              优先看当下建议和历史回测对照，低优先级覆盖信息收在页面底部。
            </p>
          </div>
          <div class="hero-actions">
            <el-button :loading="syncing" type="primary" @click="syncRecentHistory">
              同步近 30 个交易日
            </el-button>
            <el-button :loading="loading" @click="loadAll">
              刷新
            </el-button>
          </div>
        </div>
      </div>

      <div v-if="latestPoint" class="hero-grid">
        <article class="focus-card primary">
          <span class="focus-label">当前建议</span>
          <strong>{{ latestRecord?.signal['做不做'] || latestPoint.action || '-' }}</strong>
          <small>{{ latestRecord?.signal['做什么'] || latestPoint.strategy || '-' }}</small>
        </article>
        <article class="focus-card">
          <span class="focus-label">推荐仓位</span>
          <strong>{{ formatPlainPercent(latestRecord?.signal['做多少'] ?? latestPoint.position_pct) }}</strong>
          <small>截止 {{ latestRecord?.display_trade_date || latestPoint.display_trade_date }}</small>
        </article>
        <article class="focus-card">
          <span class="focus-label">本周期超额</span>
          <strong>{{ formatPercent(periodSummary.excess_return_pct) }}</strong>
          <small>策略 {{ formatPercent(periodSummary.strategy_return_pct) }} / 基准 {{ formatPercent(periodSummary.benchmark_return_pct) }}</small>
        </article>
        <article class="focus-card">
          <span class="focus-label">本周期准确率</span>
          <strong>{{ formatPercent(periodSummary.high_position_win_rate_5d_pct) }}</strong>
          <small>高仓位后 5 日胜率</small>
        </article>
      </div>
    </section>

    <section v-if="latestRecord" class="summary-card">
      <header>
        <h2>最新解读</h2>
        <span>{{ latestRecord.display_trade_date }}</span>
      </header>
      <p>{{ latestRecord.signal['说明'] }}</p>
    </section>

    <section v-if="loadError" class="error-card">
      <strong>页面加载异常</strong>
      <p>{{ loadError }}</p>
    </section>

    <section class="workspace-card">
      <header class="workspace-head">
        <div>
          <h2>结果工作区</h2>
          <p>{{ selectedPeriodLabel }}视角下，只保留推荐仓位和策略/基准两条净值曲线。</p>
        </div>
        <div class="workspace-actions">
          <div class="period-switch">
            <button
              v-for="item in periodOptions"
              :key="item.value"
              type="button"
              class="period-btn"
              :class="{ active: selectedPeriod === item.value }"
              @click="selectedPeriod = item.value"
            >
              {{ item.label }}
            </button>
          </div>
          <el-button @click="backtestDialogVisible = true">
            查看回测对照
          </el-button>
        </div>
      </header>

      <el-tabs v-model="activeView" class="workspace-tabs">
        <el-tab-pane label="图表" name="chart">
          <div v-if="chartHistory.length" ref="chartRef" class="chart-canvas"></div>
          <el-empty v-else description="当前周期没有可展示的数据" />
        </el-tab-pane>

        <el-tab-pane label="表格" name="table">
          <el-table :data="pagedRows" stripe>
            <el-table-column prop="display_trade_date" label="日期" width="120" />
            <el-table-column prop="action" label="建议" width="90" />
            <el-table-column prop="strategy" label="策略" width="90" />
            <el-table-column prop="position_pct" label="仓位" width="90">
              <template #default="{ row }">{{ formatPlainPercent(row.position_pct) }}</template>
            </el-table-column>
            <el-table-column prop="benchmark_return_pct" label="基准日收益" width="110">
              <template #default="{ row }">{{ formatPercent(row.benchmark_return_pct) }}</template>
            </el-table-column>
            <el-table-column prop="strategy_return_pct" label="策略日收益" width="110">
              <template #default="{ row }">{{ formatPercent(row.strategy_return_pct) }}</template>
            </el-table-column>
            <el-table-column prop="benchmark_nav" label="基准净值" width="110">
              <template #default="{ row }">{{ row.benchmark_nav.toFixed(3) }}</template>
            </el-table-column>
            <el-table-column prop="strategy_nav" label="策略净值" width="110">
              <template #default="{ row }">{{ row.strategy_nav.toFixed(3) }}</template>
            </el-table-column>
            <el-table-column prop="temperature_index" label="温度" width="90">
              <template #default="{ row }">{{ formatNumber(row.temperature_index) }}</template>
            </el-table-column>
          </el-table>

          <div class="table-footer">
            <el-pagination
              v-model:current-page="tablePage"
              :page-size="tablePageSize"
              :total="tableRows.length"
              layout="total, prev, pager, next"
              background
            />
          </div>
        </el-tab-pane>
      </el-tabs>
    </section>

    <section class="coverage-card">
      <div class="coverage-copy">
        <h2>覆盖情况</h2>
        <p>晴雨表本地覆盖 {{ coverageText }}，共 {{ dashboard?.coverage.count || 0 }} 个交易日。</p>
        <p class="subtle">{{ coverageHint }}</p>
      </div>
      <div class="coverage-badges">
        <span v-for="item in benchmarkCoverageList" :key="item.label" class="coverage-badge">
          {{ item.label }} {{ item.range }}
        </span>
      </div>
    </section>

    <el-dialog
      v-model="backtestDialogVisible"
      title="回测对照"
      width="920px"
      class="backtest-dialog"
    >
      <div class="dialog-grid">
        <article class="dialog-metric">
          <span>策略累计收益</span>
          <strong>{{ formatPercent(periodSummary.strategy_return_pct) }}</strong>
        </article>
        <article class="dialog-metric">
          <span>基准累计收益</span>
          <strong>{{ formatPercent(periodSummary.benchmark_return_pct) }}</strong>
        </article>
        <article class="dialog-metric">
          <span>超额收益</span>
          <strong>{{ formatPercent(periodSummary.excess_return_pct) }}</strong>
        </article>
        <article class="dialog-metric">
          <span>策略最大回撤</span>
          <strong>{{ formatPercent(periodSummary.strategy_max_drawdown_pct) }}</strong>
        </article>
        <article class="dialog-metric">
          <span>基准最大回撤</span>
          <strong>{{ formatPercent(periodSummary.benchmark_max_drawdown_pct) }}</strong>
        </article>
        <article class="dialog-metric">
          <span>策略日胜率</span>
          <strong>{{ formatPercent(periodSummary.strategy_win_rate_pct) }}</strong>
        </article>
      </div>

      <div class="compare-table">
        <div class="compare-row compare-head">
          <span>指标</span>
          <span>策略</span>
          <span>基准/对照</span>
        </div>
        <div class="compare-row">
          <span>累计收益</span>
          <span>{{ formatPercent(periodSummary.strategy_return_pct) }}</span>
          <span>{{ formatPercent(periodSummary.benchmark_return_pct) }}</span>
        </div>
        <div class="compare-row">
          <span>最大回撤</span>
          <span>{{ formatPercent(periodSummary.strategy_max_drawdown_pct) }}</span>
          <span>{{ formatPercent(periodSummary.benchmark_max_drawdown_pct) }}</span>
        </div>
        <div class="compare-row">
          <span>平均仓位</span>
          <span>{{ formatPercent(periodSummary.average_position_pct) }}</span>
          <span>-</span>
        </div>
        <div class="compare-row">
          <span>高仓位后 5 日胜率</span>
          <span>{{ formatPercent(periodSummary.high_position_win_rate_5d_pct) }}</span>
          <span>样本 {{ periodSummary.high_position_signal_count }}</span>
        </div>
        <div class="compare-row">
          <span>低仓位后 5 日胜率</span>
          <span>{{ formatPercent(periodSummary.low_position_win_rate_5d_pct) }}</span>
          <span>样本 {{ periodSummary.low_position_signal_count }}</span>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'

import { marketApi } from '@/api'
import type {
  MarketWeatherDashboardPoint,
  MarketWeatherDashboardResult,
  MarketWeatherRecord,
} from '@/api/modules/market'

type PeriodKey = 'week' | 'month' | 'quarter' | 'year' | 'all'
type ViewKey = 'chart' | 'table'

const periodOptions: Array<{ label: string; value: PeriodKey }> = [
  { label: '周', value: 'week' },
  { label: '月', value: 'month' },
  { label: '季', value: 'quarter' },
  { label: '年', value: 'year' },
  { label: '全部', value: 'all' },
]

const periodDays: Record<Exclude<PeriodKey, 'all'>, number> = {
  week: 7,
  month: 31,
  quarter: 93,
  year: 366,
}

const loading = ref(false)
const syncing = ref(false)
const loadError = ref('')
const latestRecord = ref<MarketWeatherRecord | null>(null)
const dashboard = ref<MarketWeatherDashboardResult | null>(null)
const attemptedBootstrap = ref(false)
const chartRef = ref<HTMLElement | null>(null)
const selectedPeriod = ref<PeriodKey>('quarter')
const activeView = ref<ViewKey>('chart')
const tablePage = ref(1)
const tablePageSize = 20
const backtestDialogVisible = ref(false)

let chart: echarts.ECharts | null = null

const latestPoint = computed<MarketWeatherDashboardPoint | null>(() => {
  const history = dashboard.value?.history || []
  return history.length ? history[history.length - 1] : null
})

const selectedPeriodLabel = computed(() => {
  return periodOptions.find((item) => item.value === selectedPeriod.value)?.label || '季'
})

const coverageText = computed(() => {
  const coverage = dashboard.value?.coverage
  if (!coverage?.earliest_display_trade_date || !coverage?.latest_display_trade_date) {
    return '暂无历史区间'
  }
  return `${coverage.earliest_display_trade_date} -> ${coverage.latest_display_trade_date}`
})

const coverageHint = computed(() => {
  const coverage = dashboard.value?.coverage
  const earliest = coverage?.earliest_trade_date || ''
  if (!coverage?.count) {
    return '当前本地还没有足够的晴雨表历史，先同步近 30 个交易日后再看。'
  }
  if (earliest && earliest > '20240101') {
    return '当前源历史暂未覆盖到 2024-01-01，现阶段可用区间从 2024-06-20 开始。'
  }
  return '当前展示基于本地完整可用区间，继续补历史后会自动向前延长。'
})

const benchmarkCoverageList = computed(() => {
  const coverage = dashboard.value?.benchmark_coverage || {}
  return [
    { label: '上证', key: '000001.SH' },
    { label: '深成指', key: '399001.SZ' },
    { label: '创业板', key: '399006.SZ' },
  ].map((item) => {
    const current = coverage[item.key]
    const start = current?.earliest_trade_date || '-'
    const end = current?.latest_trade_date || '-'
    return {
      label: item.label,
      range: `${start} -> ${end}`,
    }
  })
})

function tradeDateToTime(value: string): number {
  if (!value || value.length !== 8) return 0
  return new Date(`${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}T00:00:00`).getTime()
}

const filteredHistory = computed<MarketWeatherDashboardPoint[]>(() => {
  const history = dashboard.value?.history || []
  if (selectedPeriod.value === 'all' || history.length === 0) {
    return history
  }
  const latest = history[history.length - 1]
  const latestTime = tradeDateToTime(latest.trade_date)
  const days = periodDays[selectedPeriod.value]
  return history.filter((item) => latestTime - tradeDateToTime(item.trade_date) <= days * 24 * 60 * 60 * 1000)
})

const chartHistory = computed(() => {
  const history = filteredHistory.value
  if (!history.length) return []
  const firstBenchmark = history[0].benchmark_nav || 1
  const firstStrategy = history[0].strategy_nav || 1
  return history.map((item) => ({
    ...item,
    chartBenchmarkNav: firstBenchmark > 0 ? item.benchmark_nav / firstBenchmark : item.benchmark_nav,
    chartStrategyNav: firstStrategy > 0 ? item.strategy_nav / firstStrategy : item.strategy_nav,
  }))
})

function calcMaxDrawdown(values: number[]): number {
  let peak = 0
  let maxDrawdown = 0
  for (const value of values) {
    peak = Math.max(peak, value)
    if (peak > 0) {
      maxDrawdown = Math.max(maxDrawdown, (peak - value) / peak)
    }
  }
  return maxDrawdown * 100
}

const periodSummary = computed(() => {
  const history = chartHistory.value
  if (!history.length) {
    return {
      strategy_return_pct: null,
      benchmark_return_pct: null,
      excess_return_pct: null,
      strategy_max_drawdown_pct: null,
      benchmark_max_drawdown_pct: null,
      strategy_win_rate_pct: null,
      average_position_pct: null,
      high_position_signal_count: 0,
      high_position_win_rate_5d_pct: null,
      low_position_signal_count: 0,
      low_position_win_rate_5d_pct: null,
    }
  }

  const strategyReturnPct = (history[history.length - 1].chartStrategyNav - 1) * 100
  const benchmarkReturnPct = (history[history.length - 1].chartBenchmarkNav - 1) * 100
  const strategyWinRatePct = (history.filter((item) => item.strategy_return_pct > 0).length / history.length) * 100
  const averagePositionPct = history.reduce((sum, item) => sum + item.position_pct, 0) / history.length
  const strategyMaxDrawdownPct = calcMaxDrawdown(history.map((item) => item.chartStrategyNav))
  const benchmarkMaxDrawdownPct = calcMaxDrawdown(history.map((item) => item.chartBenchmarkNav))

  const benchmarkDailyReturns = history.map((item) => item.benchmark_return_pct / 100)
  let highCount = 0
  let highWins = 0
  let lowCount = 0
  let lowWins = 0

  for (let index = 0; index < history.length - 5; index += 1) {
    let futureReturn = 1
    for (let cursor = index + 1; cursor <= index + 5; cursor += 1) {
      futureReturn *= 1 + benchmarkDailyReturns[cursor]
    }
    futureReturn -= 1

    if (history[index].position_pct >= 60) {
      highCount += 1
      if (futureReturn > 0) highWins += 1
    }
    if (history[index].position_pct <= 30) {
      lowCount += 1
      if (futureReturn > 0) lowWins += 1
    }
  }

  return {
    strategy_return_pct: strategyReturnPct,
    benchmark_return_pct: benchmarkReturnPct,
    excess_return_pct: strategyReturnPct - benchmarkReturnPct,
    strategy_max_drawdown_pct: strategyMaxDrawdownPct,
    benchmark_max_drawdown_pct: benchmarkMaxDrawdownPct,
    strategy_win_rate_pct: strategyWinRatePct,
    average_position_pct: averagePositionPct,
    high_position_signal_count: highCount,
    high_position_win_rate_5d_pct: highCount ? (highWins / highCount) * 100 : null,
    low_position_signal_count: lowCount,
    low_position_win_rate_5d_pct: lowCount ? (lowWins / lowCount) * 100 : null,
  }
})

const tableRows = computed(() => filteredHistory.value.slice().reverse())

const pagedRows = computed(() => {
  const start = (tablePage.value - 1) * tablePageSize
  return tableRows.value.slice(start, start + tablePageSize)
})

function formatPercent(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '-'
  }
  return `${value.toFixed(2)}%`
}

function formatPlainPercent(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '-'
  }
  return `${value.toFixed(0)}%`
}

function formatNumber(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '-'
  }
  return value.toFixed(0)
}

function renderChart(): void {
  const history = chartHistory.value
  if (!chartRef.value || history.length === 0) return
  if (!chart) {
    chart = echarts.init(chartRef.value)
  }

  const labelStep = history.length > 160 ? 24 : history.length > 90 ? 12 : history.length > 45 ? 6 : 0

  chart.setOption({
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#0f172a',
      borderColor: '#334155',
      textStyle: { color: '#e2e8f0' },
    },
    legend: {
      top: 10,
      textStyle: { color: '#475569' },
    },
	    grid: {
	      top: 54,
	      right: 24,
	      bottom: 24,
	      left: 50,
          containLabel: true,
	    },
	    xAxis: {
	      type: 'category',
	      data: history.map((item) => item.display_trade_date.slice(5)),
          boundaryGap: true,
	      axisLabel: {
            color: '#64748b',
            hideOverlap: true,
            interval: labelStep,
            margin: 12,
          },
          axisTick: {
            alignWithLabel: true,
          },
	    },
    yAxis: [
      {
        type: 'value',
        min: 0,
        max: 100,
        axisLabel: {
          color: '#64748b',
          formatter: '{value}%',
        },
        splitLine: { show: false },
      },
      {
        type: 'value',
        axisLabel: { color: '#64748b' },
        splitLine: { lineStyle: { color: '#e2e8f0', type: 'dashed' } },
      },
    ],
    series: [
      {
        name: '推荐仓位',
        type: 'bar',
        yAxisIndex: 0,
        data: history.map((item) => item.position_pct),
        itemStyle: {
          color: '#f59e0b',
          borderRadius: [8, 8, 0, 0],
        },
        barMaxWidth: 18,
      },
      {
        name: '基准净值',
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        data: history.map((item) => Number(item.chartBenchmarkNav.toFixed(4))),
        lineStyle: { width: 3, color: '#2563eb' },
        itemStyle: { color: '#2563eb' },
      },
      {
        name: '策略净值',
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        data: history.map((item) => Number(item.chartStrategyNav.toFixed(4))),
        lineStyle: { width: 3, color: '#0f766e' },
        itemStyle: { color: '#0f766e' },
      },
	    ],
	  })
  chart.resize()
}

async function loadAll(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const [latestResult, dashboardResult] = await Promise.allSettled([
      marketApi.getMarketWeatherLatest(),
      marketApi.getMarketWeatherDashboard(),
    ])

    if (latestResult.status === 'fulfilled') {
      latestRecord.value = latestResult.value
    }
    if (dashboardResult.status === 'fulfilled') {
      dashboard.value = dashboardResult.value
    }

    if (latestResult.status === 'rejected' && dashboardResult.status === 'rejected') {
      throw new Error('市场晴雨表与回测数据都加载失败了')
    }

    if ((!dashboard.value?.history.length || !latestRecord.value) && !attemptedBootstrap.value) {
      attemptedBootstrap.value = true
      await syncRecentHistory()
      return
    }
    await nextTick()
    renderChart()
  } catch (error) {
    console.error('load market weather failed', error)
    loadError.value = error instanceof Error ? error.message : '加载失败'
    ElMessage.error(loadError.value)
  } finally {
    loading.value = false
  }
}

async function syncRecentHistory(): Promise<void> {
  syncing.value = true
  try {
    const result = await marketApi.syncMarketWeather(30, false)
    ElMessage.success(`同步完成：成功 ${result.success}，跳过 ${result.skipped}，失败 ${result.failed}`)
    await loadAll()
  } catch (error) {
    console.error('sync market weather failed', error)
    ElMessage.error('同步市场晴雨表失败')
  } finally {
    syncing.value = false
  }
}

watch(selectedPeriod, () => {
  tablePage.value = 1
})

watch(
  () => [selectedPeriod.value, activeView.value, chartHistory.value.length],
  async () => {
    await nextTick()
    if (activeView.value === 'chart') {
      renderChart()
    }
  },
)

onMounted(() => {
  loadAll()
  window.addEventListener('resize', renderChart)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', renderChart)
  chart?.dispose()
  chart = null
})
</script>

<style scoped lang="scss">
.weather-page {
  display: grid;
  gap: 16px;
  padding: 1.25rem;
}

.hero-card,
.summary-card,
.workspace-card,
.coverage-card {
  background:
    radial-gradient(circle at top right, rgba(234, 179, 8, 0.12), transparent 28%),
    linear-gradient(145deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.98));
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 24px;
  box-shadow: 0 20px 60px rgba(15, 23, 42, 0.07);
  overflow: hidden;
}

.hero-card,
.summary-card,
.workspace-card,
.coverage-card {
  padding: 24px 28px;
}

.eyebrow {
  margin: 0 0 8px;
  color: #b45309;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.hero-headline,
.workspace-head,
.coverage-card,
.summary-card header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
}

.hero-copy h1,
.workspace-head h2,
.coverage-copy h2 {
  margin: 0;
  color: #0f172a;
}

.description,
.workspace-head p,
.coverage-copy p,
.summary-card p {
  margin: 8px 0 0;
  color: #475569;
  line-height: 1.65;
}

.hero-actions,
.workspace-actions {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  flex-wrap: wrap;
}

.hero-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-top: 18px;
}

.focus-card {
  display: grid;
  gap: 6px;
  padding: 16px 18px;
  border-radius: 18px;
  background: linear-gradient(160deg, #f8fafc, #ffffff);
  border: 1px solid rgba(148, 163, 184, 0.18);
}

.focus-card.primary {
  background: linear-gradient(160deg, #fff7ed, #ffffff);
  border-color: rgba(251, 146, 60, 0.22);
}

.focus-label {
  color: #64748b;
  font-size: 12px;
}

.focus-card strong {
  color: #0f172a;
  font-size: 28px;
  line-height: 1.1;
}

.focus-card small,
.summary-card span,
.subtle,
.coverage-badge {
  color: #64748b;
}

.period-switch {
  display: inline-flex;
  gap: 6px;
  padding: 4px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.05);
}

.period-btn {
  border: none;
  padding: 8px 12px;
  border-radius: 999px;
  background: transparent;
  color: #475569;
  cursor: pointer;
  transition: all 0.18s ease;
}

.period-btn.active {
  background: #0f172a;
  color: #fff;
}

.workspace-tabs :deep(.el-tabs__header) {
  margin-bottom: 16px;
}

.chart-canvas {
  width: 100%;
  height: 460px;
}

.table-footer {
  display: flex;
  justify-content: flex-end;
  padding-top: 16px;
}

.coverage-card {
  align-items: flex-start;
}

.coverage-badges {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;
}

.coverage-badge {
  padding: 9px 12px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.06);
  font-size: 12px;
}

.dialog-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}

.dialog-metric {
  display: grid;
  gap: 6px;
  padding: 16px;
  border-radius: 18px;
  background: #f8fafc;
  border: 1px solid rgba(148, 163, 184, 0.18);
}

.dialog-metric span,
.compare-row {
  color: #64748b;
  font-size: 13px;
}

.dialog-metric strong {
  color: #0f172a;
  font-size: 26px;
}

.compare-table {
  border-radius: 18px;
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.18);
}

.compare-row {
  display: grid;
  grid-template-columns: 1.4fr 1fr 1fr;
  gap: 12px;
  padding: 14px 16px;
  background: #fff;
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
}

.compare-row:last-child {
  border-bottom: none;
}

.compare-head {
  background: #f8fafc;
  color: #334155;
  font-weight: 600;
}

@media (max-width: 1180px) {
  .hero-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 960px) {
  .hero-headline,
  .workspace-head,
  .coverage-card,
  .summary-card header {
    flex-direction: column;
  }

  .dialog-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .weather-page {
    padding: 1rem;
  }

  .hero-card,
  .summary-card,
  .workspace-card,
  .coverage-card {
    padding: 18px;
  }

  .hero-grid {
    grid-template-columns: 1fr;
  }

  .workspace-actions {
    align-items: stretch;
  }

  .chart-canvas {
    height: 340px;
  }

  .compare-row {
    grid-template-columns: 1fr;
  }
}
</style>
