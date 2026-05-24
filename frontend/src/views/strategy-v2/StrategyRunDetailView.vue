<template>
  <div v-if="run" class="run-detail-page">
    <section class="hero-card">
      <div>
        <p class="eyebrow">Run Detail V2</p>
        <h1>{{ run.title }}</h1>
        <p class="description">{{ run.summary }}</p>
      </div>
      <div class="hero-actions">
        <el-tag :type="runStatusTagType(run.run_status)" effect="plain" round>
          {{ runStatusLabel(run.run_status) }}
        </el-tag>
        <el-button v-if="run.run_status === 'running'" type="danger" plain @click="cancelCurrentRun">
          取消运行
        </el-button>
        <el-button v-else-if="canRetry" type="primary" plain @click="retryCurrentRun">
          重试运行
        </el-button>
        <el-button @click="openTask">返回任务</el-button>
        <el-button v-if="run.related_pool_id" type="primary" plain @click="router.push({ name: 'StockPools', query: { pool: run.related_pool_id } })">
          打开临时清单
        </el-button>
        <el-button v-if="run.related_trade_review_group_name" type="primary" plain @click="router.push('/trade-review')">
          打开交割单分析
        </el-button>
      </div>
    </section>

    <section class="summary-strip">
      <article v-for="metric in run.summary_metrics" :key="metric.label" class="strip-card" :class="metric.tone || 'default'">
        <span>{{ metric.label }}</span>
        <strong>{{ metric.value }}</strong>
      </article>
    </section>

    <section v-if="showProgress" class="progress-card">
      <div class="progress-head">
        <div>
          <span class="section-kicker">运行进度</span>
          <strong>{{ run.progress_label || runStatusLabel(run.run_status) }}</strong>
        </div>
        <span>{{ progressCurrent }} / {{ progressTotal }}，{{ progressPercent }}%</span>
      </div>
      <el-progress :percentage="progressPercent" :status="progressStatus" :stroke-width="10" />
    </section>

    <section class="workspace-shell">
      <main class="results-column">
        <section class="console-panel">
          <div class="section-title-row">
            <div>
              <span class="section-kicker">信号全景</span>
              <h2>这次运行最后给出了什么判断</h2>
            </div>
          </div>

          <div class="signal-grid">
            <article class="signal-card positive">
              <span>正向信号</span>
              <strong>{{ run.signal_breakdown.positive }}</strong>
            </article>
            <article class="signal-card neutral">
              <span>中性信号</span>
              <strong>{{ run.signal_breakdown.neutral }}</strong>
            </article>
            <article class="signal-card negative">
              <span>负向信号</span>
              <strong>{{ run.signal_breakdown.negative }}</strong>
            </article>
          </div>

          <div class="landing-strip">
            <article v-for="card in resultDestinationCards" :key="card.label" class="landing-card" :class="card.tone || 'default'">
              <span>{{ card.label }}</span>
              <strong>{{ card.value }}</strong>
              <p>{{ card.description }}</p>
            </article>
          </div>

          <div class="table-filters">
            <button type="button" :class="['filter-pill', { active: itemFilter === 'all' }]" @click="itemFilter = 'all'">全部</button>
            <button type="button" :class="['filter-pill', { active: itemFilter === 'positive' }]" @click="itemFilter = 'positive'">正向</button>
            <button type="button" :class="['filter-pill', { active: itemFilter === 'review' }]" @click="itemFilter = 'review'">待复核</button>
            <button type="button" :class="['filter-pill', { active: itemFilter === 'skipped' }]" @click="itemFilter = 'skipped'">无动作/跳过</button>
          </div>

          <el-table :data="filteredItems" stripe class="result-table">
            <el-table-column prop="entity_key" label="标的代码" width="140" />
            <el-table-column prop="entity_name" label="名称" min-width="140" />
            <el-table-column label="信号" width="100">
              <template #default="{ row }">
                <span :class="['signal-pill', signalClass(row.signal)]">{{ signalLabel(row.signal) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="强度" width="100">
              <template #default="{ row }">
                {{ Math.round(row.score * 100) }}%
              </template>
            </el-table-column>
            <el-table-column label="标签" min-width="160">
              <template #default="{ row }">
                <div class="tag-cloud">
                  <span v-for="tag in row.tags" :key="tag" class="mini-tag">{{ tag }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="reason" label="原因" min-width="260" show-overflow-tooltip />
            <el-table-column prop="action_result" label="动作结果" min-width="180" />
            <el-table-column label="状态写回" width="110">
              <template #default="{ row }">
                {{ row.state_writeback ? '已写回' : '未写回' }}
              </template>
            </el-table-column>
          </el-table>
        </section>
      </main>

      <aside class="inspector-column">
        <section class="console-panel">
          <div class="section-title-row compact">
            <div>
              <span class="section-kicker">运行上下文</span>
              <h3>{{ sceneLabels[run.scene_type] }}</h3>
            </div>
          </div>
          <div class="context-list">
            <div class="context-row">
              <span>策略</span>
              <strong>{{ run.strategy_name }}</strong>
            </div>
            <div class="context-row">
              <span>触发来源</span>
              <strong>{{ triggerSourceLabel(run.trigger_source) }}</strong>
            </div>
            <div class="context-row">
              <span>开始时间</span>
              <strong>{{ formatDateTime(run.started_at) }}</strong>
            </div>
            <div class="context-row" v-if="run.finished_at">
              <span>完成时间</span>
              <strong>{{ formatDateTime(run.finished_at) }}</strong>
            </div>
            <div class="context-row" v-if="run.related_pool_name">
              <span>临时清单</span>
              <strong>{{ run.related_pool_name }}</strong>
            </div>
            <div class="context-row" v-if="run.related_trade_review_group_name">
              <span>关联交割单</span>
              <strong>{{ run.related_trade_review_group_name }}</strong>
            </div>
          </div>
        </section>

        <section class="console-panel">
          <div class="section-title-row compact">
            <div>
              <span class="section-kicker">动作复核</span>
              <h3>这轮执行留下了什么</h3>
            </div>
          </div>
          <div class="review-grid">
            <article class="review-card">
              <span>状态写回</span>
              <strong>{{ stateWritebackCount }}</strong>
              <small>个对象已写入跨日状态</small>
            </article>
            <article class="review-card">
              <span>需复核对象</span>
              <strong>{{ reviewNeededCount }}</strong>
              <small>动作结果里带人工确认意味</small>
            </article>
            <article class="review-card">
              <span>无动作 / 跳过</span>
              <strong>{{ skippedCount }}</strong>
              <small>便于核对冷却、过滤和未命中情况</small>
            </article>
          </div>
          <div v-if="run.next_action_hint" class="next-action-card">
            <strong>下一步建议</strong>
            <p>{{ run.next_action_hint }}</p>
          </div>
        </section>

        <section class="console-panel">
          <div class="section-title-row compact">
            <div>
              <span class="section-kicker">重点对象</span>
              <h3>适合先看的明细</h3>
            </div>
          </div>
          <div class="focus-list">
            <article v-for="item in prioritizedItems" :key="item.item_id" class="focus-card">
              <div class="focus-head">
                <strong>{{ item.entity_name }}</strong>
                <span :class="['signal-pill', signalClass(item.signal)]">{{ signalLabel(item.signal) }}</span>
              </div>
              <p>{{ item.reason }}</p>
              <small>{{ item.action_result }}</small>
            </article>
          </div>
        </section>

        <section class="console-panel">
          <div class="section-title-row compact">
            <div>
              <span class="section-kicker">后续动作</span>
              <h3>{{ followupTitle }}</h3>
            </div>
          </div>
          <div class="followup-grid">
            <article v-for="card in followupCards" :key="card.title" class="followup-card">
              <span>{{ card.kicker }}</span>
              <strong>{{ card.title }}</strong>
              <p>{{ card.description }}</p>
              <el-button size="small" @click="openFollowup(card.routeName)">{{ card.actionLabel }}</el-button>
            </article>
          </div>
        </section>
      </aside>
    </section>
  </div>
  <el-empty v-else description="运行记录不存在或尚未生成" />
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { cancelTaskRun, getRunItems, getTaskRun, retryTaskRun } from '@/api/modules/strategy-v2'
import { STRATEGY_SCENE_LABELS } from '@/mocks/strategyV2'
import type { StrategyRunStatus, StrategySignalValue, StrategyTaskRun, StrategyTaskRunItem } from '@/types/strategy-v2'

const route = useRoute()
const router = useRouter()

const run = ref<StrategyTaskRun | null>(null)
const items = ref<StrategyTaskRunItem[]>([])
const itemFilter = ref<'all' | 'positive' | 'review' | 'skipped'>('all')
const sceneLabels = STRATEGY_SCENE_LABELS
let refreshTimer: ReturnType<typeof window.setTimeout> | undefined

const progressCurrent = computed(() => Number(run.value?.progress_current || 0))
const progressTotal = computed(() => Number(run.value?.progress_total || 0))
const progressPercent = computed(() => {
  if (typeof run.value?.progress_pct === 'number') return Math.min(100, Math.max(0, Math.round(run.value.progress_pct)))
  if (!progressTotal.value) return run.value?.run_status === 'success' ? 100 : 0
  return Math.min(100, Math.max(0, Math.round((progressCurrent.value / progressTotal.value) * 100)))
})
const showProgress = computed(() => run.value?.run_status === 'running' || progressTotal.value > 0)
const canRetry = computed(() => Boolean(run.value && ['failed', 'cancelled', 'partial_success', 'success'].includes(run.value.run_status)))
const progressStatus = computed(() => {
  if (run.value?.run_status === 'success') return 'success'
  if (run.value?.run_status === 'failed') return 'exception'
  if (run.value?.run_status === 'cancelled') return 'warning'
  return undefined
})
const stateWritebackCount = computed(() => items.value.filter((item) => item.state_writeback).length)
const reviewNeededCount = computed(() => items.value.filter((item) => item.action_result.includes('待') || item.action_result.includes('建议')).length)
const skippedCount = computed(() => items.value.filter((item) => item.action_result.includes('无动作') || item.action_result.includes('跳过')).length)
const notifiedCount = computed(() => items.value.filter((item) => item.action_result.includes('通知')).length)
const poolLandingCount = computed(() => items.value.filter((item) => item.action_result.includes('池') && !item.action_result.includes('未入池')).length)
const tempListCount = computed(() => items.value.filter((item) => item.action_result.includes('临时清单') || item.action_result.includes('临时列表')).length)
const cooledDownCount = computed(() => items.value.filter((item) => item.action_result.includes('冷却')).length)
const tradeReviewLandingCount = computed(() => items.value.filter((item) => item.action_result.includes('交割单')).length)
const simulatedTradeCount = computed(() => items.value.filter((item) => item.action_result.includes('模拟卖出') || item.action_result.includes('模拟成交')).length)
const holdCount = computed(() => items.value.filter((item) => item.action_result.includes('保持持仓')).length)
const filteredItems = computed(() => {
  if (itemFilter.value === 'positive') return items.value.filter((item) => item.signal === 1)
  if (itemFilter.value === 'review') return items.value.filter((item) => item.action_result.includes('待') || item.action_result.includes('建议'))
  if (itemFilter.value === 'skipped') return items.value.filter((item) => item.action_result.includes('无动作') || item.action_result.includes('跳过'))
  return items.value
})
const prioritizedItems = computed(() => {
  return [...items.value]
    .sort((a, b) => b.score - a.score)
    .slice(0, 4)
})
const followupTitle = computed(() => {
  if (!run.value) return '这次运行之后去哪里'
  if (run.value.scene_type === 'scan') return '候选承接与人工复核'
  if (run.value.scene_type === 'listen') return '流转复核与任务回看'
  if (run.value.scene_type === 'backtest') return '交割单分析与样本对照'
  return '模拟结果分析与持仓复盘'
})
const followupCards = computed(() => {
  if (!run.value) return []
  if (run.value.scene_type === 'scan') {
    return [
      {
        kicker: '候选承接',
        title: '去现有股池继续筛',
        description: '扫描结果的重点不是直接交易，而是把高质量候选先放进股池继续流转和复盘。',
        routeName: 'StockPools',
        actionLabel: '打开股池',
      },
      {
        kicker: '运行回看',
        title: `${run.value.signal_breakdown.positive} 个正向候选待复核`,
        description: '结合强度、标签和动作结果，先确认哪些应该保留在临时列表里继续看。',
        routeName: 'StrategyTaskDetailV2',
        actionLabel: '返回任务',
      },
    ]
  }
  if (run.value.scene_type === 'listen') {
    return [
      {
        kicker: '业务落点',
        title: '检查池内流转结果',
        description: '监听任务最重要的是触发之后有没有真的落到池内变化或提醒动作。',
        routeName: 'StockPools',
        actionLabel: '查看股池',
      },
      {
        kicker: '回到任务',
        title: `${reviewNeededCount.value} 个对象建议复核`,
        description: '优先检查被冷却拦下或需要人工确认的对象，避免只看通知数量。',
        routeName: 'StrategyTaskDetailV2',
        actionLabel: '返回任务',
      },
    ]
  }
  if (run.value.scene_type === 'backtest') {
    return [
      {
        kicker: '分析闭环',
        title: run.value.related_trade_review_group_name || '打开交割单分析',
        description: '回测的价值在于继续看盈亏分布、胜率和模式归因，而不是停留在这页摘要。',
        routeName: 'TradeReview',
        actionLabel: '打开交割单',
      },
      {
        kicker: '任务回放',
        title: `${skippedCount.value} 个中性样本可做对照`,
        description: '未触发样本也很重要，它们能帮助判断当前策略阈值是否过宽或过严。',
        routeName: 'StrategyTaskDetailV2',
        actionLabel: '返回任务',
      },
    ]
  }
  return [
    {
      kicker: '结果分析',
      title: run.value.related_trade_review_group_name || '进入模拟交易分析',
      description: '模拟交易最终还是要进入交割单分析页，才有后续复盘和归因价值。',
      routeName: 'TradeReview',
      actionLabel: '打开交割单',
    },
    {
      kicker: '持仓复核',
      title: `${reviewNeededCount.value} 个风险或待确认对象`,
      description: '优先处理预警对象和模拟卖出结果，再决定是否同步加入后续复盘链路。',
      routeName: 'StrategyTaskDetailV2',
      actionLabel: '返回任务',
    },
  ]
})
const resultDestinationCards = computed(() => {
  if (!run.value) return []
  if (run.value.scene_type === 'scan') {
    return [
      {
        label: '加入股池',
        value: `${poolLandingCount.value}`,
        description: '命中后已经明确落入候选池或确认池的对象。',
        tone: 'positive',
      },
      {
        label: '临时列表',
        value: `${tempListCount.value}`,
        description: '暂时不直接流转，等人工复核后再决定去向。',
        tone: 'warning',
      },
      {
        label: '未入池',
        value: `${items.value.filter((item) => item.action_result.includes('未入池')).length}`,
        description: '本轮被淘汰或明确不承接的对象。',
        tone: 'negative',
      },
    ]
  }
  if (run.value.scene_type === 'listen') {
    return [
      {
        label: '已通知',
        value: `${notifiedCount.value}`,
        description: '已经推送到通知链路的监听结果。',
        tone: 'positive',
      },
      {
        label: '已流转',
        value: `${items.value.filter((item) => item.action_result.includes('流转')).length}`,
        description: '触发后已经推动股池或分组状态变化的对象。',
        tone: 'positive',
      },
      {
        label: '冷却拦下',
        value: `${cooledDownCount.value}`,
        description: '避免重复提醒或频繁流转而被本轮跳过的对象。',
        tone: 'warning',
      },
    ]
  }
  if (run.value.scene_type === 'backtest') {
    return [
      {
        label: '交割单落地',
        value: `${tradeReviewLandingCount.value}`,
        description: '已经写入当前交割单分组，后续直接去分析页复盘。',
        tone: 'positive',
      },
      {
        label: '保持持仓',
        value: `${holdCount.value}`,
        description: '区间内未触发交易动作，作为对照样本保留。',
      },
      {
        label: '中性样本',
        value: `${items.value.filter((item) => item.signal === 0).length}`,
        description: '帮助判断当前止损阈值是偏宽还是偏严。',
      },
    ]
  }
  return [
    {
      label: '模拟卖出',
      value: `${simulatedTradeCount.value}`,
      description: '已落成模拟成交，用于后续交割单分析和持仓复盘。',
      tone: 'negative',
    },
    {
      label: '风险提醒',
      value: `${notifiedCount.value}`,
      description: '优先处理需要人工确认的风险对象和异常持仓。',
      tone: 'warning',
    },
    {
      label: '维持持仓',
      value: `${items.value.filter((item) => item.action_result.includes('无动作') || item.action_result.includes('保持持仓')).length}`,
      description: '没有触发处理动作的对象，继续纳入下一轮监控。',
    },
  ]
})

onMounted(async () => {
  const runId = String(route.params.runId || '')
  await loadRun(runId)
})

onBeforeUnmount(() => {
  if (refreshTimer) window.clearTimeout(refreshTimer)
})

async function loadRun(runId: string): Promise<void> {
  if (!runId) {
    run.value = null
    items.value = []
    return
  }
  run.value = await getTaskRun(runId)
  items.value = await getRunItems(runId)
  if (run.value?.run_status === 'running') {
    if (refreshTimer) window.clearTimeout(refreshTimer)
    refreshTimer = window.setTimeout(() => {
      void loadRun(runId)
    }, 2500)
  }
}

async function cancelCurrentRun(): Promise<void> {
  if (!run.value) return
  try {
    await ElMessageBox.confirm('取消后本次运行会停止继续扫描，已产生的运行明细会保留用于排查。', '取消运行', {
      type: 'warning',
      confirmButtonText: '确认取消',
      cancelButtonText: '先不取消',
    })
    run.value = await cancelTaskRun(run.value.run_id)
    ElMessage.success('已请求取消运行')
    items.value = await getRunItems(run.value.run_id)
  }
  catch (error) {
    if (error === 'cancel') return
    console.error(error)
    ElMessage.error('取消运行失败')
  }
}

async function retryCurrentRun(): Promise<void> {
  if (!run.value) return
  try {
    const nextRun = await retryTaskRun(run.value.run_id)
    ElMessage.success('已开始重试')
    router.push({ name: 'StrategyRunDetailV2', params: { runId: nextRun.run_id } })
    await loadRun(nextRun.run_id)
  }
  catch (error) {
    console.error(error)
    ElMessage.error('重试启动失败')
  }
}

function openTask(): void {
  if (!run.value) return
  router.push({ name: 'StrategyTaskDetailV2', params: { taskId: run.value.task_id } })
}

function openFollowup(routeName: string): void {
  if (!run.value) return
  if (routeName === 'StrategyTaskDetailV2') {
    router.push({ name: routeName, params: { taskId: run.value.task_id } })
    return
  }
  router.push({ name: routeName })
}

function runStatusLabel(status: StrategyRunStatus): string {
  if (status === 'success') return '成功'
  if (status === 'partial_success') return '部分成功'
  if (status === 'failed') return '失败'
  if (status === 'cancelled') return '已取消'
  return '运行中'
}

function runStatusTagType(status: StrategyRunStatus): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'success') return 'success'
  if (status === 'partial_success') return 'warning'
  if (status === 'failed') return 'danger'
  if (status === 'cancelled') return 'warning'
  return 'info'
}

function formatDateTime(value?: string): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function triggerSourceLabel(value: string): string {
  if (value === 'manual') return '手动触发'
  if (value === 'schedule') return '定时触发'
  if (value === 'retry') return '重试触发'
  return '历史回放'
}

function signalLabel(value: StrategySignalValue): string {
  if (value > 0) return '1'
  if (value < 0) return '-1'
  return '0'
}

function signalClass(value: StrategySignalValue): string {
  if (value > 0) return 'positive'
  if (value < 0) return 'negative'
  return 'neutral'
}
</script>

<style scoped>
.run-detail-page {
  --surface-1: linear-gradient(180deg, rgba(252, 253, 255, 0.98), rgba(246, 248, 252, 0.95));
  --line-soft: rgba(15, 23, 42, 0.08);
  --line-strong: rgba(42, 82, 190, 0.22);
  --accent: #2f5fd0;
  --ink-soft: #5b6473;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.hero-card,
.strip-card,
.signal-card,
.progress-card,
.console-panel,
.review-card,
.focus-card,
.landing-card {
  border: 1px solid var(--line-soft);
  background: var(--surface-1);
  box-shadow: 0 18px 38px rgba(15, 23, 42, 0.07);
}

.hero-card {
  border-radius: 28px;
  padding: 28px;
  display: flex;
  justify-content: space-between;
  gap: 24px;
}

.eyebrow,
.section-kicker {
  margin: 0 0 10px;
  font-size: 11px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: #6274b7;
}

.hero-card h1,
.section-title-row h2 {
  margin: 0;
  font-size: 34px;
}

.description,
.next-action-card p,
.focus-card p {
  line-height: 1.7;
  color: var(--ink-soft);
}

.hero-actions {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  flex-wrap: wrap;
}

.summary-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.strip-card,
.signal-card,
.review-card {
  border-radius: 20px;
  padding: 16px 18px;
}

.strip-card span,
.signal-card span,
.context-row span,
.review-card span,
.focus-card small {
  display: block;
  color: var(--ink-soft);
  font-size: 12px;
}

.strip-card strong,
.signal-card strong,
.review-card strong {
  display: block;
  margin-top: 8px;
  font-size: 24px;
}

.strip-card.positive strong,
.signal-card.positive strong {
  color: #16a34a;
}

.strip-card.negative strong,
.signal-card.negative strong {
  color: #dc2626;
}

.strip-card.warning strong {
  color: #d97706;
}

.progress-card {
  border-radius: 20px;
  padding: 16px 18px;
}

.progress-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
  color: var(--ink-soft);
}

.progress-head strong {
  display: block;
  color: #0f172a;
}

.workspace-shell {
  display: grid;
  grid-template-columns: 1.15fr 0.85fr;
  gap: 18px;
}

.console-panel {
  border-radius: 28px;
  padding: 20px;
}

.section-title-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 16px;
}

.section-title-row h2,
.section-title-row h3 {
  margin: 0;
}

.section-title-row h3 {
  font-size: 20px;
}

.table-filters,
.tag-cloud {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.table-filters {
  margin: 0 0 16px;
}

.filter-pill,
.mini-tag {
  border-radius: 999px;
  border: 1px solid var(--line-soft);
  background: rgba(255, 255, 255, 0.82);
  padding: 6px 10px;
  font-size: 12px;
  color: var(--ink-soft);
}

.filter-pill.active {
  border-color: var(--line-strong);
  background: rgba(47, 95, 208, 0.1);
  color: var(--accent);
}

.signal-grid,
.review-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}

.landing-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin: 0 0 18px;
}

.landing-card {
  border-radius: 20px;
  padding: 16px 18px;
}

.landing-card span,
.landing-card p {
  color: var(--ink-soft);
}

.landing-card span {
  display: block;
  font-size: 12px;
}

.landing-card strong {
  display: block;
  margin: 8px 0;
  font-size: 24px;
}

.landing-card p {
  margin: 0;
  line-height: 1.7;
  font-size: 13px;
}

.landing-card.positive strong {
  color: #16a34a;
}

.landing-card.negative strong {
  color: #dc2626;
}

.landing-card.warning strong {
  color: #d97706;
}

.context-list,
.focus-list,
.followup-grid {
  display: grid;
  gap: 12px;
}

.context-row {
  padding-bottom: 12px;
  border-bottom: 1px solid var(--line-soft);
}

.context-row:last-child {
  padding-bottom: 0;
  border-bottom: none;
}

.context-row strong {
  display: block;
  margin-top: 6px;
  line-height: 1.6;
}

.review-card small {
  display: block;
  margin-top: 6px;
}

.next-action-card {
  margin-top: 14px;
  border-radius: 18px;
  border: 1px solid var(--line-strong);
  background: rgba(47, 95, 208, 0.08);
  padding: 14px 16px;
}

.focus-card {
  border-radius: 18px;
  padding: 14px;
}

.followup-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.followup-card {
  border-radius: 18px;
  border: 1px solid var(--line-soft);
  background: rgba(255, 255, 255, 0.82);
  padding: 14px;
}

.followup-card span,
.followup-card p {
  color: var(--ink-soft);
}

.followup-card span {
  display: block;
  font-size: 12px;
}

.followup-card strong {
  display: block;
  margin: 6px 0 8px;
}

.followup-card p {
  margin: 0 0 12px;
  line-height: 1.7;
}

.focus-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
}

.focus-head strong {
  display: block;
}

.focus-card small {
  margin-top: 10px;
}

.signal-pill {
  min-width: 34px;
  padding: 4px 10px;
  border-radius: 999px;
  text-align: center;
  font-size: 12px;
  font-weight: 700;
}

.signal-pill.positive {
  background: rgba(34, 197, 94, 0.14);
  color: #1f9f57;
}

.signal-pill.neutral {
  background: rgba(148, 163, 184, 0.18);
  color: #526072;
}

.signal-pill.negative {
  background: rgba(239, 68, 68, 0.14);
  color: #d14343;
}

@media (max-width: 1200px) {
  .summary-strip,
  .workspace-shell,
  .signal-grid,
  .review-grid,
  .landing-strip,
  .followup-grid {
    grid-template-columns: 1fr;
  }

  .hero-card,
  .section-title-row {
    flex-direction: column;
  }
}
</style>
