<template>
  <div class="practice-page">
    <section class="hero-card">
      <div>
        <p class="eyebrow">Blind K-Line Practice</p>
        <h1>盘感练习</h1>
        <p class="description">
          从本地历史日线中随机抽取一段样本，隐藏股票身份，只按已揭示的 K 线逐步决策，练买点、卖点和持仓节奏。
        </p>
      </div>
      <div class="hero-actions">
        <el-button
          :loading="starting"
          :disabled="loading || stepping || finishing || tradingAction !== ''"
          type="primary"
          @click="startSession(false)"
        >
          {{ session ? '重新开一局' : '开始练习' }}
        </el-button>
        <el-button
          v-if="session"
          :loading="loading"
          :disabled="starting || stepping || finishing || tradingAction !== ''"
          @click="loadLatestSession"
        >
          刷新状态
        </el-button>
      </div>
    </section>

    <section v-if="!session" class="empty-card">
      <el-empty description="还没有进行中的练习，点上面的按钮直接开一局。">
        <el-button
          :loading="starting"
          :disabled="loading || stepping || finishing || tradingAction !== ''"
          type="primary"
          @click="startSession(false)"
        >
          开始首局练习
        </el-button>
      </el-empty>
    </section>

    <template v-else>
      <section class="summary-grid">
        <article class="metric-card">
          <span class="metric-label">练习编号</span>
          <strong>{{ session.label }}</strong>
          <small>{{ session.is_revealed ? '已揭晓样本' : '双盲进行中' }}</small>
        </article>
        <article class="metric-card">
          <span class="metric-label">推进进度</span>
          <strong>{{ session.step }} / {{ session.total_steps }}</strong>
          <small>当前显示到 {{ session.current_trade_date || '--' }}</small>
        </article>
        <article class="metric-card">
          <span class="metric-label">总资产</span>
          <strong>{{ formatCurrency(session.equity) }}</strong>
          <small>初始资金 {{ formatCurrency(session.initial_capital) }}</small>
        </article>
        <article class="metric-card" :class="pnlClass(session.total_return_pct)">
          <span class="metric-label">总收益率</span>
          <strong>{{ formatPct(session.total_return_pct) }}</strong>
          <small>已实现 {{ formatCurrency(session.realized_pnl) }}</small>
        </article>
      </section>

      <section class="workbench-grid">
        <article class="chart-card">
          <header class="section-header">
            <div>
              <h2>样本走势</h2>
              <p>看得到过去，看不到未来；每次只多揭示一点。</p>
            </div>
            <div class="chart-actions">
              <el-button
                :disabled="!session.can_step || loading"
                :loading="stepping"
                type="primary"
                @click="stepSession(1)"
              >
                下一根
              </el-button>
              <el-button
                :disabled="!session.can_step || loading"
                :loading="stepping"
                @click="stepSession(5)"
              >
                快进 5 根
              </el-button>
              <el-button
                :disabled="session.status !== 'active' || loading"
                :loading="finishing"
                type="danger"
                plain
                @click="finishSession"
              >
                揭晓答案
              </el-button>
            </div>
          </header>
          <div class="chart-stage">
            <StockChart
              :key="session.session_id"
              :data="session.visible_candles"
              :ts-code="session.label"
              :preserve-zoom="true"
            />
          </div>
        </article>

        <article class="control-card">
          <header class="section-header compact">
            <div>
              <h2>交易面板</h2>
              <p>默认按当前收盘价成交，买卖遵循 100 股整数倍。</p>
            </div>
          </header>

          <div class="position-grid">
            <div class="position-item">
              <span>可用资金</span>
              <strong>{{ formatCurrency(session.cash) }}</strong>
            </div>
            <div class="position-item">
              <span>持仓股数</span>
              <strong>{{ session.position_shares }}</strong>
            </div>
            <div class="position-item">
              <span>持仓成本</span>
              <strong>{{ session.avg_cost ? session.avg_cost.toFixed(2) : '--' }}</strong>
            </div>
            <div class="position-item" :class="pnlClass(session.unrealized_pnl)">
              <span>浮动盈亏</span>
              <strong>{{ formatCurrency(session.unrealized_pnl) }}</strong>
            </div>
          </div>

          <div class="spotlight-card">
            <span>当前价格</span>
            <strong>{{ session.latest_close ? session.latest_close.toFixed(2) : '--' }}</strong>
            <small>{{ session.current_trade_date || '等待样本' }}</small>
          </div>

          <div class="trade-group">
            <span class="group-title">买入仓位</span>
            <div class="button-row">
              <el-button
                v-for="pct in [0.25, 0.5, 1]"
                :key="`buy-${pct}`"
                :disabled="!session.can_buy || loading"
                :loading="tradingAction === `buy-${pct}`"
                type="success"
                plain
                @click="trade('buy', pct)"
              >
                买入 {{ Math.round(pct * 100) }}%
              </el-button>
            </div>
          </div>

          <div class="trade-group">
            <span class="group-title">卖出仓位</span>
            <div class="button-row">
              <el-button
                v-for="pct in [0.25, 0.5, 1]"
                :key="`sell-${pct}`"
                :disabled="!session.can_sell || loading"
                :loading="tradingAction === `sell-${pct}`"
                type="warning"
                plain
                @click="trade('sell', pct)"
              >
                卖出 {{ Math.round(pct * 100) }}%
              </el-button>
            </div>
          </div>

          <el-button
            class="full-width"
            :disabled="!session.can_sell || loading"
            :loading="tradingAction === 'close-1'"
            type="danger"
            @click="trade('close', 1)"
          >
            一键平仓
          </el-button>
        </article>
      </section>

      <section v-if="session.is_revealed && session.reveal" class="reveal-card">
        <header class="section-header">
          <div>
            <h2>样本揭晓</h2>
            <p>这一局结束后再看真实股票与练习区间。</p>
          </div>
          <el-tag type="success">已揭晓</el-tag>
        </header>
        <div class="reveal-grid">
          <div>
            <span>真实股票</span>
            <strong>{{ session.reveal.name }}（{{ session.reveal.ts_code }}）</strong>
          </div>
          <div>
            <span>所属行业</span>
            <strong>{{ session.reveal.industry || '未知' }}</strong>
          </div>
          <div>
            <span>市场板块</span>
            <strong>{{ session.reveal.market || '未知' }}</strong>
          </div>
          <div>
            <span>练习区间</span>
            <strong>{{ session.reveal.segment_start_date }} ~ {{ session.reveal.segment_end_date }}</strong>
          </div>
        </div>
      </section>

      <section class="table-card">
        <header class="section-header">
          <div>
            <h2>交易记录</h2>
            <p>每一笔决策都记录下来，方便复盘自己的节奏和错误。</p>
          </div>
          <span class="meta">{{ session.trades.length }} 笔</span>
        </header>
        <div class="table-scroll">
          <el-table :data="session.trades.slice().reverse()" stripe empty-text="还没有交易记录">
            <el-table-column prop="trade_date" label="日期" width="120" />
            <el-table-column label="动作" width="110">
              <template #default="{ row }">
                <el-tag :type="tagType(row.action)">{{ actionLabel(row.action) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="shares" label="股数" width="100" />
            <el-table-column prop="price" label="价格" width="100">
              <template #default="{ row }">{{ row.price.toFixed(2) }}</template>
            </el-table-column>
            <el-table-column prop="amount" label="成交额" width="120">
              <template #default="{ row }">{{ formatCurrency(row.amount) }}</template>
            </el-table-column>
            <el-table-column prop="realized_pnl" label="已实现盈亏" width="130">
              <template #default="{ row }">
                <span :class="pnlClass(row.realized_pnl)">{{ formatCurrency(row.realized_pnl) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="note" label="备注" min-width="180">
              <template #default="{ row }">{{ row.note || '--' }}</template>
            </el-table-column>
          </el-table>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { practiceApi, type PracticeSessionState, type PracticeTradeRequest } from '@/api'
import StockChart from '@/components/charts/StockChart.vue'

const session = ref<PracticeSessionState | null>(null)
const loading = ref(false)
const starting = ref(false)
const stepping = ref(false)
const finishing = ref(false)
const tradingAction = ref('')

const hasActiveSession = computed(() => session.value?.status === 'active')

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

async function loadLatestSession(): Promise<void> {
  loading.value = true
  try {
    session.value = await practiceApi.getLatestSession()
  } catch {
    session.value = null
  } finally {
    loading.value = false
  }
}

async function startSession(forceConfirm = true): Promise<void> {
  if (forceConfirm && hasActiveSession.value) {
    try {
      await ElMessageBox.confirm(
        '开始新的一局会自动结束当前练习并平掉剩余持仓，确定继续吗？',
        '重新开局确认',
        {
          type: 'warning',
          confirmButtonText: '继续',
          cancelButtonText: '取消',
        },
      )
    } catch {
      return
    }
  }

  starting.value = true
  try {
    session.value = await practiceApi.startSession({})
    ElMessage.success('新的练习样本已就绪')
  } catch {
    ElMessage.error('重开失败，请稍后重试')
    await loadLatestSession()
  } finally {
    starting.value = false
  }
}

async function stepSession(steps: number): Promise<void> {
  if (!session.value) return
  stepping.value = true
  try {
    session.value = await practiceApi.stepSession(session.value.session_id, steps)
    if (session.value.status === 'completed') {
      ElMessage.success('练习样本已走完，结果已揭晓')
    }
  } finally {
    stepping.value = false
  }
}

async function trade(action: PracticeTradeRequest['action'], allocationPct: number): Promise<void> {
  if (!session.value) return
  tradingAction.value = `${action}-${allocationPct}`
  try {
    session.value = await practiceApi.trade(session.value.session_id, {
      action,
      allocation_pct: allocationPct,
    })
    ElMessage.success(`${actionLabel(action)}操作已记录`)
  } finally {
    tradingAction.value = ''
  }
}

async function finishSession(): Promise<void> {
  if (!session.value) return
  try {
    await ElMessageBox.confirm(
      '结束后会立即揭晓真实股票，并对剩余持仓自动平仓。确定结束本局吗？',
      '结束练习',
      {
        type: 'warning',
        confirmButtonText: '结束并揭晓',
        cancelButtonText: '继续练习',
      },
    )
  } catch {
    return
  }

  finishing.value = true
  try {
    session.value = await practiceApi.finishSession(session.value.session_id)
    ElMessage.success('本局练习已结束')
  } finally {
    finishing.value = false
  }
}

onMounted(async () => {
  await loadLatestSession()
})
</script>

<style scoped lang="scss">
.practice-page {
  display: grid;
  gap: 20px;
  padding: 1.5rem;
}

.hero-card,
.metric-card,
.chart-card,
.control-card,
.table-card,
.reveal-card,
.empty-card {
  background: var(--el-bg-color-overlay);
  border: 1px solid var(--el-border-color-light);
  border-radius: 20px;
  box-shadow: 0 20px 45px rgba(15, 23, 42, 0.06);
}

.hero-card {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  padding: 28px 30px;
  background:
    radial-gradient(circle at top left, rgba(56, 189, 248, 0.18), transparent 34%),
    radial-gradient(circle at right center, rgba(14, 165, 233, 0.16), transparent 28%),
    linear-gradient(135deg, rgba(15, 23, 42, 0.98), rgba(30, 64, 175, 0.9));
  color: #f8fafc;
}

.hero-card > * {
  min-width: 0;
}

.eyebrow {
  margin: 0 0 10px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  font-size: 12px;
  opacity: 0.7;
}

.hero-card h1,
.section-header h2 {
  margin: 0;
}

.description {
  max-width: 720px;
  margin: 12px 0 0;
  color: rgba(226, 232, 240, 0.88);
  line-height: 1.7;
}

.hero-actions {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  flex-shrink: 0;
}

.summary-grid {
  display: grid;
  gap: 16px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.metric-card {
  display: grid;
  gap: 8px;
  padding: 20px 22px;
}

.metric-card strong {
  font-size: 28px;
  line-height: 1.1;
}

.metric-card small,
.metric-label,
.position-item span,
.spotlight-card span,
.group-title,
.meta,
.reveal-grid span {
  color: var(--el-text-color-secondary);
}

.workbench-grid {
  display: grid;
  gap: 20px;
  grid-template-columns: minmax(0, 1.8fr) minmax(320px, 0.9fr);
}

.workbench-grid > * {
  min-width: 0;
}

.chart-card,
.control-card,
.table-card,
.reveal-card {
  padding: 22px;
  overflow: hidden;
}

.section-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.section-header p {
  margin: 6px 0 0;
  color: var(--el-text-color-secondary);
}

.section-header.compact {
  margin-bottom: 14px;
}

.chart-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.chart-stage {
  min-width: 0;
  overflow: hidden;
  min-height: 520px;
}

.chart-stage :deep(.stock-chart) {
  height: 520px;
  min-height: 520px;
}

.control-card {
  display: grid;
  gap: 18px;
  align-content: start;
}

.position-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.position-item,
.spotlight-card {
  padding: 16px 18px;
  border-radius: 16px;
  background: var(--el-fill-color-extra-light);
}

.position-item strong,
.spotlight-card strong {
  display: block;
  margin-top: 8px;
  font-size: 22px;
}

.spotlight-card {
  background:
    linear-gradient(145deg, rgba(59, 130, 246, 0.14), rgba(14, 165, 233, 0.06)),
    var(--el-fill-color-extra-light);
}

.trade-group {
  display: grid;
  gap: 10px;
}

.button-row {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.full-width {
  width: 100%;
}

.empty-card {
  padding: 28px;
}

.reveal-grid {
  display: grid;
  gap: 16px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.reveal-grid strong {
  display: block;
  margin-top: 6px;
  font-size: 18px;
}

.table-scroll {
  width: 100%;
  overflow-x: auto;
}

.table-scroll :deep(.el-table) {
  min-width: 760px;
}

.is-profit {
  color: #dc2626;
}

.is-loss {
  color: #089981;
}

@media (max-width: 1280px) {
  .summary-grid,
  .reveal-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .workbench-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .hero-card,
  .section-header {
    flex-direction: column;
  }

  .hero-actions {
    width: 100%;
    flex-wrap: wrap;
  }

  .chart-stage {
    min-height: 420px;
  }

  .chart-stage :deep(.stock-chart) {
    height: 420px;
    min-height: 420px;
  }

  .summary-grid,
  .position-grid,
  .button-row,
  .reveal-grid {
    grid-template-columns: 1fr;
  }
}
</style>
