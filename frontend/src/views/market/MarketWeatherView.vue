<template>
  <div class="weather-page">
    <section class="hero-card">
      <div class="hero-copy">
        <p class="eyebrow">Market Weather</p>
        <h1>市场晴雨表</h1>
        <p class="description">
          将 Coze 工作流返回的市场因子落库后，按交易日追踪市场温度、仓位建议和操作风格变化。
        </p>
      </div>
      <div class="hero-actions">
        <el-button :loading="syncing" type="primary" @click="syncRecentHistory">
          同步近 30 个交易日
        </el-button>
        <el-button :loading="loading" @click="loadAll">
          刷新页面
        </el-button>
      </div>
    </section>

    <section v-if="latestRecord" class="signal-grid">
      <article class="signal-card">
        <span class="signal-label">操作建议</span>
        <strong>{{ latestRecord.signal['做不做'] }}</strong>
        <small>数据截止 {{ latestRecord.display_trade_date }}</small>
      </article>
      <article class="signal-card accent">
        <span class="signal-label">建议仓位</span>
        <strong>{{ latestRecord.signal['做多少'] }}%</strong>
        <small>{{ latestRecord.signal['做什么'] }}</small>
      </article>
      <article class="signal-card">
        <span class="signal-label">市场温度</span>
        <strong>{{ latestRecord.temperature_index.toFixed(0) }}</strong>
        <small>温度越高，试错窗口通常越大</small>
      </article>
    </section>

    <section v-if="latestRecord" class="summary-card">
      <header>
        <h2>今日解读</h2>
        <span>{{ latestRecord.display_trade_date }}</span>
      </header>
      <p>{{ latestRecord.signal['说明'] }}</p>
    </section>

    <section class="chart-card">
      <header class="section-header">
        <div>
          <h2>近一个月变化</h2>
          <p>温度指数、建议仓位与五大因子同屏观察</p>
        </div>
        <span v-if="history.length" class="meta">{{ history.length }} 个交易日</span>
      </header>
      <div ref="chartRef" class="chart-canvas"></div>
    </section>

    <section class="table-card">
      <header class="section-header">
        <div>
          <h2>历史记录</h2>
          <p>已落库的市场晴雨表原始因子与策略结论</p>
        </div>
      </header>
      <el-table :data="history.slice().reverse()" stripe>
        <el-table-column prop="display_trade_date" label="日期" width="120" />
        <el-table-column prop="temperature_index" label="温度" width="90">
          <template #default="{ row }">{{ row.temperature_index.toFixed(0) }}</template>
        </el-table-column>
        <el-table-column prop="signal.做不做" label="操作建议" width="110" />
        <el-table-column prop="signal.做多少" label="仓位" width="90">
          <template #default="{ row }">{{ row.signal['做多少'] }}%</template>
        </el-table-column>
        <el-table-column prop="signal.做什么" label="策略" width="90" />
        <el-table-column label="涨停溢价" width="100">
          <template #default="{ row }">{{ formatFactor(row.limit_premium_factor) }}</template>
        </el-table-column>
        <el-table-column label="趋势惯性" width="100">
          <template #default="{ row }">{{ formatFactor(row.trend_factor) }}</template>
        </el-table-column>
        <el-table-column label="量价共振" width="100">
          <template #default="{ row }">{{ formatFactor(row.volume_factor) }}</template>
        </el-table-column>
        <el-table-column label="市场广度" width="100">
          <template #default="{ row }">{{ formatFactor(row.breadth_factor) }}</template>
        </el-table-column>
        <el-table-column label="多空动能" width="100">
          <template #default="{ row }">{{ formatFactor(row.momentum_factor) }}</template>
        </el-table-column>
        <el-table-column prop="signal.说明" label="说明" min-width="380" show-overflow-tooltip />
      </el-table>
    </section>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'

import { marketApi } from '@/api'
import type { MarketWeatherRecord } from '@/api/modules/market'

const loading = ref(false)
const syncing = ref(false)
const latestRecord = ref<MarketWeatherRecord | null>(null)
const history = ref<MarketWeatherRecord[]>([])
const chartRef = ref<HTMLElement | null>(null)
const attemptedBootstrap = ref(false)

let chart: echarts.ECharts | null = null

function formatFactor(value: number): string {
  return Number.isFinite(value) ? value.toFixed(3) : '-'
}

function renderChart(): void {
  if (!chartRef.value || history.value.length === 0) {
    return
  }
  if (!chart) {
    chart = echarts.init(chartRef.value)
  }

  const dates = history.value.map((item) => item.display_trade_date.slice(5))
  chart.setOption({
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#0f172a',
      borderColor: '#334155',
      textStyle: { color: '#e2e8f0' },
    },
    legend: {
      top: 12,
      textStyle: { color: '#475569' },
    },
    grid: {
      top: 48,
      right: 20,
      bottom: 30,
      left: 40,
    },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { color: '#64748b' },
    },
    yAxis: [
      {
        type: 'value',
        min: 0,
        max: 100,
        axisLabel: { color: '#64748b' },
        splitLine: { lineStyle: { color: '#e2e8f0', type: 'dashed' } },
      },
      {
        type: 'value',
        min: 0,
        max: 1,
        axisLabel: { color: '#94a3b8' },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '市场温度',
        type: 'line',
        smooth: true,
        data: history.value.map((item) => item.temperature_index),
        lineStyle: { width: 3, color: '#d97706' },
        itemStyle: { color: '#d97706' },
      },
      {
        name: '建议仓位',
        type: 'line',
        smooth: true,
        data: history.value.map((item) => item.signal['做多少']),
        lineStyle: { width: 3, color: '#0f766e' },
        itemStyle: { color: '#0f766e' },
      },
      {
        name: '涨停溢价',
        type: 'bar',
        yAxisIndex: 1,
        data: history.value.map((item) => item.limit_premium_factor),
        itemStyle: { color: '#ef4444' },
      },
      {
        name: '趋势惯性',
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        data: history.value.map((item) => item.trend_factor),
        lineStyle: { width: 2, color: '#3b82f6' },
        itemStyle: { color: '#3b82f6' },
      },
      {
        name: '量价共振',
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        data: history.value.map((item) => item.volume_factor),
        lineStyle: { width: 2, color: '#8b5cf6' },
        itemStyle: { color: '#8b5cf6' },
      },
    ],
  })
}

async function loadAll(): Promise<void> {
  loading.value = true
  try {
    const [latest, historyRes] = await Promise.all([
      marketApi.getMarketWeatherLatest(),
      marketApi.getMarketWeatherHistory(30),
    ])
    latestRecord.value = latest
    history.value = historyRes.history || []
    if (history.value.length === 0 && !attemptedBootstrap.value) {
      attemptedBootstrap.value = true
      await syncRecentHistory()
      return
    }
    await nextTick()
    renderChart()
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
  } finally {
    syncing.value = false
  }
}

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
  gap: 20px;
  padding: 1.5rem;
}

.hero-card,
.summary-card,
.chart-card,
.table-card {
  background:
    radial-gradient(circle at top right, rgba(234, 179, 8, 0.12), transparent 28%),
    linear-gradient(145deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.98));
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 24px;
  box-shadow: 0 20px 60px rgba(15, 23, 42, 0.07);
}

.hero-card {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  padding: 28px 32px;
}

.eyebrow {
  margin: 0 0 8px;
  color: #b45309;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.hero-copy h1,
.section-header h2 {
  margin: 0;
  color: #0f172a;
}

.description,
.section-header p,
.summary-card p {
  margin: 10px 0 0;
  color: #475569;
  line-height: 1.7;
}

.hero-actions {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
}

.signal-grid {
  display: grid;
  gap: 16px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.signal-card {
  border-radius: 22px;
  padding: 22px 24px;
  background: linear-gradient(160deg, #fff7ed, #ffffff);
  border: 1px solid rgba(251, 146, 60, 0.18);
  display: grid;
  gap: 8px;
}

.signal-card.accent {
  background: linear-gradient(160deg, #ecfeff, #ffffff);
  border-color: rgba(45, 212, 191, 0.2);
}

.signal-card strong {
  font-size: 30px;
  color: #0f172a;
}

.signal-label {
  font-size: 13px;
  color: #64748b;
}

.signal-card small,
.meta,
.summary-card span {
  color: #64748b;
}

.summary-card,
.chart-card,
.table-card {
  padding: 24px 28px;
}

.summary-card header,
.section-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.chart-canvas {
  width: 100%;
  height: 440px;
  margin-top: 12px;
}

@media (max-width: 960px) {
  .hero-card,
  .summary-card header,
  .section-header {
    flex-direction: column;
  }

  .signal-grid {
    grid-template-columns: 1fr;
  }

  .chart-canvas {
    height: 360px;
  }
}
</style>
