<template>
  <div class="practice-page">
    <section class="studio-shell">
      <header class="studio-topbar">
        <div class="title-stack">
          <p class="eyebrow">Blind K-Line Studio</p>
          <div class="title-row">
            <h1>盘感练习</h1>
            <el-tag :type="session?.is_revealed ? 'success' : 'info'">
              {{ session?.is_revealed ? '已揭晓' : '双盲进行中' }}
            </el-tag>
            <el-tag v-if="session" effect="plain">{{ session.label }}</el-tag>
          </div>
        </div>

        <div class="topbar-actions">
          <div class="mode-switch">
            <el-button size="small" @click="goHistory">历史战绩</el-button>
            <el-button size="small" disabled>沉浸模式</el-button>
            <el-button type="primary" plain size="small" @click="goClassic">经典模式</el-button>
          </div>
          <el-button
            :loading="starting"
            :disabled="actionBusy"
            type="primary"
            @click="startSessionAndReset(true)"
          >
            新开一局
          </el-button>
          <el-button
            v-if="session"
            :loading="finishing"
            :disabled="!session || session.status !== 'active' || actionBusy"
            type="danger"
            plain
            @click="finishSession"
          >
            揭晓答案
          </el-button>
          <el-button
            :disabled="actionBusy"
            @click="detailsVisible = true"
          >
            详情
          </el-button>
        </div>
      </header>

      <section v-if="!session" class="empty-shell">
        <el-empty description="还没有进行中的练习，开始一局就能进入沉浸模式。">
          <el-button
            :loading="starting"
            :disabled="actionBusy"
            type="primary"
            @click="startSessionAndReset(false)"
          >
            开始练习
          </el-button>
        </el-empty>
      </section>

      <template v-else>
        <section class="status-ribbon">
          <article class="status-pill">
            <span>当前价</span>
            <strong>{{ session.latest_close ? session.latest_close.toFixed(2) : '--' }}</strong>
            <small>{{ session.current_trade_date || '--' }}</small>
          </article>
          <article class="status-pill" :class="pnlClass(currentPositionReturnPct)">
            <span>当前操作盈亏</span>
            <strong>{{ formatPct(currentPositionReturnPct) }}</strong>
            <small>{{ session.position_shares > 0 ? `当前仓位 ${formatPct(session.position_pct)}` : '当前空仓' }}</small>
          </article>
          <article class="status-pill" :class="pnlClass(session.total_return_pct)">
            <span>总盈亏</span>
            <strong>{{ formatPct(session.total_return_pct) }}</strong>
            <small>{{ session.position_shares > 0 ? '含浮动盈亏' : '已全部落袋' }}</small>
          </article>
          <article class="status-pill">
            <span>进度</span>
            <strong>{{ session.step }} / {{ session.total_steps }}</strong>
            <div class="progress-line">
              <div class="progress-fill" :style="{ width: `${progressPct}%` }"></div>
            </div>
          </article>
        </section>

        <section class="action-ribbon">
          <div class="allocation-switch">
            <span class="action-label">仓位</span>
            <el-radio-group v-model="tradeAllocation" size="small">
              <el-radio-button :label="1">满仓</el-radio-button>
              <el-radio-button :label="0.5">半仓</el-radio-button>
              <el-radio-button :label="0.25">轻仓</el-radio-button>
            </el-radio-group>
          </div>

          <div class="action-cluster">
            <el-button
              :disabled="!session.can_step || actionBusy"
              :loading="stepping"
              type="primary"
              @click="stepSession(1)"
            >
              下一根
              <span class="shortcut-hint">Space</span>
            </el-button>
            <el-button
              :disabled="!session.can_step || actionBusy"
              :loading="stepping"
              @click="stepSession(5)"
            >
              快进 5 根
              <span class="shortcut-hint">Shift+Space</span>
            </el-button>
            <el-button
              :disabled="!session.can_buy || actionBusy"
              :loading="tradingAction === `buy-${tradeAllocation}`"
              type="success"
              @click="trade('buy', tradeAllocation)"
            >
              买入
              <span class="shortcut-hint">B</span>
            </el-button>
            <el-button
              :disabled="!session.can_sell || actionBusy"
              :loading="tradingAction === `sell-${tradeAllocation}`"
              type="warning"
              @click="trade('sell', tradeAllocation)"
            >
              卖出
              <span class="shortcut-hint">S</span>
            </el-button>
            <el-button
              :disabled="!session.can_sell || actionBusy"
              :loading="tradingAction === 'close-1'"
              type="danger"
              @click="trade('close', 1)"
            >
              平仓
              <span class="shortcut-hint">C</span>
            </el-button>
          </div>
        </section>

        <section class="chart-shell">
          <div class="chart-toolbar">
            <div class="chart-toolbar-title">
              <strong>盲练 K 线</strong>
              <span>支持日线、周线、月线切换，交易点会直接标在图上。</span>
            </div>
            <el-radio-group v-model="selectedPeriod" size="small">
              <el-radio-button label="daily">日K</el-radio-button>
              <el-radio-button label="weekly">周K</el-radio-button>
              <el-radio-button label="monthly">月K</el-radio-button>
            </el-radio-group>
          </div>
          <div class="chart-stage">
            <StockChart
              :key="session.session_id"
              :data="selectedChartData"
              :ts-code="session.label"
              :markers="chartMarkers"
              :preserve-zoom="true"
              :initial-zoom-start="0"
              :initial-zoom-end="100"
            />
          </div>
        </section>

        <footer class="shortcut-bar">
          <span>快捷键</span>
          <span>Space 下一根</span>
          <span>Shift+Space 快进 5 根</span>
          <span>B 买入</span>
          <span>S 卖出</span>
          <span>C 平仓</span>
          <span>N 新开一局</span>
          <span>R 揭晓</span>
          <span>D 详情</span>
        </footer>
      </template>
    </section>

    <el-drawer
      v-model="detailsVisible"
      size="460px"
      title="练习详情"
      append-to-body
      destroy-on-close
    >
      <template v-if="session">
        <section class="drawer-section">
          <div class="drawer-grid">
            <div class="drawer-card">
              <span>可用资金</span>
              <strong>{{ formatCurrency(session.cash) }}</strong>
            </div>
            <div class="drawer-card">
              <span>当前仓位</span>
              <strong>{{ session.position_shares > 0 ? formatPct(session.position_pct) : '0.00%' }}</strong>
            </div>
            <div class="drawer-card">
              <span>持仓成本</span>
              <strong>{{ session.avg_cost ? session.avg_cost.toFixed(2) : '--' }}</strong>
            </div>
            <div class="drawer-card">
              <span>已实现盈亏</span>
              <strong :class="pnlClass(session.realized_pnl)">{{ formatCurrency(session.realized_pnl) }}</strong>
            </div>
          </div>
        </section>

        <section v-if="session.is_revealed && session.reveal" class="drawer-section">
          <header class="drawer-header">
            <h3>样本揭晓</h3>
          </header>
          <div class="drawer-grid">
            <div class="drawer-card wide">
              <span>真实股票</span>
              <strong>{{ session.reveal.name }}（{{ session.reveal.ts_code }}）</strong>
            </div>
            <div class="drawer-card">
              <span>所属行业</span>
              <strong>{{ session.reveal.industry || '未知' }}</strong>
            </div>
            <div class="drawer-card">
              <span>市场板块</span>
              <strong>{{ session.reveal.market || '未知' }}</strong>
            </div>
            <div class="drawer-card wide">
              <span>练习区间</span>
              <strong>{{ session.reveal.segment_start_date }} ~ {{ session.reveal.segment_end_date }}</strong>
            </div>
          </div>
        </section>

        <section class="drawer-section">
          <header class="drawer-header">
            <h3>交易记录</h3>
            <span>{{ session.trades.length }} 笔</span>
          </header>
          <div class="table-scroll">
            <el-table :data="session.trades.slice().reverse()" stripe empty-text="还没有交易记录">
              <el-table-column prop="trade_date" label="日期" width="110" />
              <el-table-column label="动作" width="90">
                <template #default="{ row }">
                  <el-tag :type="tagType(row.action)">{{ actionLabel(row.action) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="shares" label="股数" width="90" />
              <el-table-column prop="allocation_pct" label="仓位" width="90">
                <template #default="{ row }">{{ formatPct((row.allocation_pct || 0) * 100) }}</template>
              </el-table-column>
              <el-table-column prop="price" label="价格" width="90">
                <template #default="{ row }">{{ row.price.toFixed(2) }}</template>
              </el-table-column>
              <el-table-column prop="realized_pnl" label="盈亏" width="110">
                <template #default="{ row }">
                  <span :class="pnlClass(row.realized_pnl)">{{ formatCurrency(row.realized_pnl) }}</span>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </section>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import StockChart from '@/components/charts/StockChart.vue'
import { usePracticeSession } from './usePracticeSession'
import type { StockDaily } from '@/api'

const route = useRoute()
const router = useRouter()
const detailsVisible = ref(false)
const tradeAllocation = ref<0.25 | 0.5 | 1>(1)
const selectedPeriod = ref<'daily' | 'weekly' | 'monthly'>('daily')
const {
  session,
  starting,
  stepping,
  finishing,
  tradingAction,
  actionBusy,
  loadLatestSession,
  loadSession,
  startSession,
  stepSession,
  trade,
  finishSession,
} = usePracticeSession()

const currentPositionReturnPct = computed(() => {
  if (!session.value || session.value.position_shares <= 0 || !session.value.avg_cost || !session.value.latest_close) {
    return 0
  }
  return ((session.value.latest_close - session.value.avg_cost) / session.value.avg_cost) * 100
})

const progressPct = computed(() => {
  if (!session.value || session.value.total_steps <= 0) {
    return 0
  }
  return (session.value.step / session.value.total_steps) * 100
})

const selectedChartData = computed<StockDaily[]>(() => {
  if (!session.value) return []
  if (selectedPeriod.value === 'weekly') return session.value.visible_weekly_candles
  if (selectedPeriod.value === 'monthly') return session.value.visible_monthly_candles
  return session.value.visible_candles
})

const chartMarkers = computed(() => {
  return (session.value?.trade_markers || []).map((item) => ({
    trade_date: item.trade_date,
    price: item.price,
    side: item.side,
    label: item.label,
  }))
})

function goClassic(): void {
  router.push('/kline-practice/classic')
}

function goHistory(): void {
  router.push({ name: 'KlinePracticeHistory' })
}

async function startSessionAndReset(forceConfirm = true): Promise<void> {
  await startSession(forceConfirm)
  if (session.value) {
    await router.replace({ name: 'KlinePractice' })
  }
}

function formatCurrency(value: number): string {
  return `${value >= 0 ? '' : '-'}¥${Math.abs(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`
}

function formatPct(value: number): string {
  const prefix = value > 0 ? '+' : ''
  return `${prefix}${value.toFixed(2)}%`
}

function pnlClass(value: number): string {
  if (value > 0) return 'is-profit'
  if (value < 0) return 'is-loss'
  return ''
}

function actionLabel(action: string): string {
  if (action === 'buy') return '买入'
  if (action === 'sell') return '卖出'
  if (action === 'auto_close') return '自动平仓'
  return '平仓'
}

function tagType(action: string): 'success' | 'warning' | 'danger' | 'info' {
  if (action === 'buy') return 'success'
  if (action === 'sell') return 'warning'
  if (action === 'auto_close') return 'info'
  return 'danger'
}

function canHandleKey(event: KeyboardEvent): boolean {
  const target = event.target as HTMLElement | null
  if (!target) return true
  const tagName = target.tagName
  return tagName !== 'INPUT' && tagName !== 'TEXTAREA' && !target.isContentEditable
}

async function handleKeydown(event: KeyboardEvent): Promise<void> {
  if (!canHandleKey(event) || actionBusy.value) {
    return
  }

  if (event.code === 'Space') {
    event.preventDefault()
    await stepSession(event.shiftKey ? 5 : 1)
    return
  }

  const key = event.key.toLowerCase()
  if (key === 'arrowright') {
    event.preventDefault()
    await stepSession(1)
    return
  }
  if (key === 'b' && session.value?.can_buy) {
    event.preventDefault()
    await trade('buy', tradeAllocation.value)
    return
  }
  if (key === 's' && session.value?.can_sell) {
    event.preventDefault()
    await trade('sell', tradeAllocation.value)
    return
  }
  if (key === 'c' && session.value?.can_sell) {
    event.preventDefault()
    await trade('close', 1)
    return
  }
  if (key === 'n') {
    event.preventDefault()
    await startSessionAndReset(true)
    return
  }
  if (key === 'r' && session.value?.status === 'active') {
    event.preventDefault()
    await finishSession()
    return
  }
  if (key === 'd') {
    event.preventDefault()
    detailsVisible.value = !detailsVisible.value
  }
}

async function loadByRoute(): Promise<void> {
  const targetSessionId = typeof route.query.sessionId === 'string' ? route.query.sessionId : ''
  if (targetSessionId) {
    await loadSession(targetSessionId)
    return
  }
  await loadLatestSession()
}

watch(
  () => route.query.sessionId,
  async () => {
    await loadByRoute()
  },
)

onMounted(async () => {
  await loadByRoute()
  window.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<style scoped lang="scss">
.practice-page {
  padding: 1rem;
}

.studio-shell {
  display: grid;
  gap: 12px;
  min-height: calc(100vh - 150px);
  padding: 16px;
  border-radius: 24px;
  background:
    radial-gradient(circle at top left, rgba(56, 189, 248, 0.12), transparent 26%),
    linear-gradient(180deg, rgba(248, 250, 252, 0.96), rgba(255, 255, 255, 0.92));
  border: 1px solid rgba(148, 163, 184, 0.18);
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.08);
}

.studio-topbar,
.status-ribbon,
.action-ribbon,
.chart-shell,
.shortcut-bar,
.empty-shell {
  min-width: 0;
}

.studio-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.title-stack,
.topbar-actions {
  min-width: 0;
}

.eyebrow {
  margin: 0 0 6px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  font-size: 11px;
  color: #64748b;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.title-row h1 {
  margin: 0;
  font-size: 28px;
}

.topbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.mode-switch {
  display: inline-flex;
  gap: 8px;
}

.status-ribbon {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.status-pill,
.drawer-card {
  padding: 14px 16px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.84);
  border: 1px solid rgba(148, 163, 184, 0.16);
}

.status-pill span,
.drawer-card span,
.drawer-header span {
  color: #64748b;
  font-size: 12px;
}

.status-pill strong,
.drawer-card strong {
  display: block;
  margin-top: 6px;
  font-size: 24px;
  line-height: 1.1;
}

.status-pill small {
  display: block;
  margin-top: 6px;
  color: #94a3b8;
}

.progress-line {
  margin-top: 8px;
  height: 6px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.18);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #0ea5e9, #2563eb);
}

.action-ribbon {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 12px 14px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(148, 163, 184, 0.14);
}

.allocation-switch,
.action-cluster {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.action-label {
  color: #64748b;
  font-size: 13px;
}

.shortcut-hint {
  margin-left: 6px;
  font-size: 11px;
  color: inherit;
  opacity: 0.72;
}

.chart-shell {
  min-height: 0;
  flex: 1;
  padding: 12px;
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.84);
  border: 1px solid rgba(148, 163, 184, 0.16);
}

.chart-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 14px;
}

.chart-toolbar-title {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.chart-toolbar-title span {
  color: #64748b;
  font-size: 12px;
}

.chart-stage {
  min-width: 0;
  min-height: calc(100vh - 360px);
}

.chart-stage :deep(.stock-chart) {
  height: calc(100vh - 360px);
  min-height: 420px;
}

.shortcut-bar {
  display: flex;
  gap: 10px 16px;
  flex-wrap: wrap;
  padding: 0 4px;
  color: #64748b;
  font-size: 12px;
}

.empty-shell {
  display: grid;
  place-items: center;
  min-height: calc(100vh - 280px);
  padding: 16px;
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.78);
  border: 1px dashed rgba(148, 163, 184, 0.26);
}

.drawer-section + .drawer-section {
  margin-top: 18px;
}

.drawer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.drawer-header h3 {
  margin: 0;
}

.drawer-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.drawer-card.wide {
  grid-column: 1 / -1;
}

.table-scroll {
  width: 100%;
  overflow-x: auto;
}

.table-scroll :deep(.el-table) {
  min-width: 520px;
}

.is-profit {
  color: #dc2626;
}

.is-loss {
  color: #089981;
}

@media (max-width: 1180px) {
  .status-ribbon {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .chart-toolbar,
  .action-ribbon,
  .studio-topbar {
    flex-direction: column;
    align-items: stretch;
  }

  .topbar-actions {
    justify-content: flex-start;
  }

  .chart-stage {
    min-height: calc(100vh - 470px);
  }

  .chart-stage :deep(.stock-chart) {
    height: calc(100vh - 470px);
  }
}

@media (max-width: 768px) {
  .practice-page {
    padding: 0.75rem;
  }

  .studio-shell {
    padding: 12px;
    min-height: auto;
  }

  .status-ribbon,
  .drawer-grid {
    grid-template-columns: 1fr;
  }

  .chart-stage {
    min-height: 420px;
  }

  .chart-stage :deep(.stock-chart) {
    height: 420px;
    min-height: 420px;
  }
}
</style>
