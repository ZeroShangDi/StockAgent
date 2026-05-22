<template>
  <div v-if="task" class="task-detail-page">
    <section class="hero-card">
      <div>
        <p class="eyebrow">Task Detail V2</p>
        <h1>{{ task.name }}</h1>
        <p class="description">
          {{ sceneLabels[task.scene_type] }} · {{ task.strategy_name }} · {{ task.target_scope_summary }}
        </p>
      </div>
      <div class="hero-actions">
        <el-button @click="router.push({ name: 'StrategyTaskCenterV2', query: { scene: task.scene_type } })">返回任务台</el-button>
        <el-button plain @click="editTask">编辑任务</el-button>
        <el-button type="primary" plain @click="runNow">立即运行</el-button>
        <el-button v-if="latestRun" type="primary" @click="openLatestRun">查看最近运行</el-button>
      </div>
    </section>

    <section class="top-strip">
      <article class="strip-card">
        <span>任务状态</span>
        <strong>{{ statusLabels[task.status] }}</strong>
      </article>
      <article class="strip-card">
        <span>最近信号数</span>
        <strong>{{ task.last_signal_count }}</strong>
      </article>
      <article class="strip-card">
        <span>调度方式</span>
        <strong>{{ task.schedule_label }}</strong>
      </article>
      <article class="strip-card emphasis" v-if="latestRun">
        <span>最近运行</span>
        <strong>{{ latestRun.title }}</strong>
      </article>
    </section>

    <section class="workspace-shell">
      <main class="operations-column">
        <section class="console-panel">
          <div class="section-title-row">
            <div>
              <span class="section-kicker">运行视角</span>
              <h2>当前任务不只是配置，而是一个持续运行的场景容器</h2>
            </div>
            <el-tag effect="plain" round>{{ sceneLabels[task.scene_type] }}</el-tag>
          </div>

          <div class="status-grid">
            <article class="status-card">
              <span>策略</span>
              <strong>{{ task.strategy_name }}</strong>
            </article>
            <article class="status-card">
              <span>目标范围</span>
              <strong>{{ task.target_scope_summary }}</strong>
            </article>
            <article class="status-card">
              <span>动作数量</span>
              <strong>{{ task.actions.length }}</strong>
            </article>
          </div>

          <div v-if="latestRun" class="run-brief">
            <div class="run-brief-head">
              <div>
                <span class="section-kicker">最近运行摘要</span>
                <h3>{{ latestRun.title }}</h3>
              </div>
              <el-tag :type="runStatusTagType(latestRun.run_status)" effect="plain" round>
                {{ runStatusLabel(latestRun.run_status) }}
              </el-tag>
            </div>
            <p>{{ latestRun.summary }}</p>
            <div class="metric-list">
              <article v-for="metric in latestRun.summary_metrics" :key="metric.label" class="mini-metric" :class="metric.tone || 'default'">
                <span>{{ metric.label }}</span>
                <strong>{{ metric.value }}</strong>
              </article>
            </div>
            <div v-if="latestRun.next_action_hint" class="next-action-card">
              <strong>后续建议</strong>
              <p>{{ latestRun.next_action_hint }}</p>
            </div>
          </div>
        </section>

        <section class="console-panel">
          <div class="section-title-row compact">
            <div>
              <span class="section-kicker">运行历史</span>
              <h3>最近运行记录</h3>
            </div>
            <span class="panel-tip">{{ runs.length }} 条</span>
          </div>

          <el-table :data="runs" stripe>
            <el-table-column prop="title" label="运行标题" min-width="180" />
            <el-table-column prop="run_status" label="状态" width="120">
              <template #default="{ row }">
                {{ runStatusLabel(row.run_status) }}
              </template>
            </el-table-column>
            <el-table-column prop="started_at" label="开始时间" width="160" />
            <el-table-column label="信号" width="110">
              <template #default="{ row }">
                {{ row.signal_breakdown.positive + row.signal_breakdown.negative }}
              </template>
            </el-table-column>
            <el-table-column label="操作" width="120" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openRun(row.run_id)">查看</el-button>
              </template>
            </el-table-column>
          </el-table>
        </section>

        <section v-if="latestRunItems.length > 0" class="console-panel">
          <div class="section-title-row compact">
            <div>
              <span class="section-kicker">最新明细预览</span>
              <h3>本轮最值得复核的对象</h3>
            </div>
          </div>

          <div class="item-grid">
            <article v-for="item in latestRunItems" :key="item.item_id" class="item-card">
              <div class="item-head">
                <div>
                  <strong>{{ item.entity_name }}</strong>
                  <span>{{ item.entity_key }}</span>
                </div>
                <span :class="['signal-pill', signalClass(item.signal)]">{{ signalLabel(item.signal) }}</span>
              </div>
              <p>{{ item.reason }}</p>
              <div class="item-meta">
                <span>强度 {{ Math.round(item.score * 100) }}%</span>
                <span>{{ item.action_result }}</span>
              </div>
            </article>
          </div>
        </section>

        <section v-if="focusCards.length > 0" class="console-panel">
          <div class="section-title-row compact">
            <div>
              <span class="section-kicker">场景焦点</span>
              <h3>{{ focusSectionTitle }}</h3>
            </div>
          </div>

          <div class="focus-grid">
            <article v-for="card in focusCards" :key="card.title" class="focus-card">
              <span>{{ card.kicker }}</span>
              <strong>{{ card.title }}</strong>
              <p>{{ card.description }}</p>
            </article>
          </div>
        </section>
      </main>

      <aside class="inspector-column">
        <section class="console-panel">
          <div class="section-title-row compact">
            <div>
              <span class="section-kicker">任务定义</span>
              <h3>配置快照</h3>
            </div>
          </div>

          <div class="config-list">
            <div class="config-row">
              <span>创建时间</span>
              <strong>{{ task.created_at }}</strong>
            </div>
            <div class="config-row">
              <span>最后更新</span>
              <strong>{{ task.updated_at }}</strong>
            </div>
            <div class="config-row">
              <span>任务说明</span>
              <strong>{{ task.notes || '暂无说明' }}</strong>
            </div>
          </div>
        </section>

        <section class="console-panel">
          <div class="section-title-row compact">
            <div>
              <span class="section-kicker">参数快照</span>
              <h3>当前任务层默认值</h3>
            </div>
          </div>
          <div class="param-list">
            <article v-for="item in paramsEntries" :key="item.key" class="param-chip">
              <span>{{ item.key }}</span>
              <strong>{{ item.value }}</strong>
            </article>
          </div>
        </section>

        <section class="console-panel">
          <div class="section-title-row compact">
            <div>
              <span class="section-kicker">动作链</span>
              <h3>信号触发后将发生什么</h3>
            </div>
          </div>
          <div class="action-list">
            <article v-for="action in task.actions" :key="action.action_id" class="action-card">
              <strong>{{ action.label }}</strong>
              <p>{{ action.summary }}</p>
            </article>
          </div>
        </section>

        <section class="console-panel">
          <div class="section-title-row compact">
            <div>
              <span class="section-kicker">结果去向</span>
              <h3>这个任务下一步会流到哪里</h3>
            </div>
          </div>

          <div class="destination-list">
            <article v-for="item in destinationCards" :key="item.title" class="destination-card">
              <span>{{ item.kicker }}</span>
              <strong>{{ item.title }}</strong>
              <p>{{ item.description }}</p>
              <el-button v-if="item.routeName" size="small" @click="openRoute(item.routeName)">{{ item.actionLabel }}</el-button>
            </article>
          </div>
        </section>
      </aside>
    </section>
  </div>
  <el-empty v-else description="任务不存在或尚未初始化" />
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import {
  getRunItems,
  getStrategySceneTask,
  listTaskRuns,
  runStrategySceneTask,
  STRATEGY_SCENE_LABELS,
  STRATEGY_TASK_STATUS_LABELS,
} from '@/mocks/strategyV2'
import type { StrategySignalValue, StrategySceneTask, StrategyTaskRun, StrategyTaskRunItem, StrategyRunStatus } from '@/types/strategy-v2'

const route = useRoute()
const router = useRouter()

const task = ref<StrategySceneTask | null>(null)
const runs = ref<StrategyTaskRun[]>([])
const latestRunItems = ref<StrategyTaskRunItem[]>([])

const sceneLabels = STRATEGY_SCENE_LABELS
const statusLabels = STRATEGY_TASK_STATUS_LABELS

const paramsEntries = computed(() => {
  if (!task.value) return []
  return Object.entries(task.value.params || {}).map(([key, value]) => ({
    key,
    value: String(value),
  }))
})

const latestRun = computed(() => runs.value[0] || null)
const skippedItems = computed(() => latestRunItems.value.filter((item) => item.action_result.includes('无动作') || item.action_result.includes('跳过')))
const negativeItems = computed(() => latestRunItems.value.filter((item) => item.signal === -1))
const focusSectionTitle = computed(() => {
  if (!task.value) return '当前场景重点'
  if (task.value.scene_type === 'scan') return '候选去留与人工复核'
  if (task.value.scene_type === 'listen') return '触发、冷却与流转结果'
  if (task.value.scene_type === 'backtest') return '交割单写入与回放摘要'
  return '持仓变化与风险结果'
})
const focusCards = computed(() => {
  if (!task.value || !latestRun.value) return []
  if (task.value.scene_type === 'scan') {
    return [
      {
        kicker: '候选数量',
        title: `${latestRun.value.signal_breakdown.positive} 个正向候选`,
        description: '优先把高强度候选送进股池，再决定哪些保留在临时列表中继续观察。',
      },
      {
        kicker: '人工复核',
        title: `${skippedItems.value.length} 个待继续确认`,
        description: '扫描任务的重点不是立即交易，而是把不确定但有价值的对象先承接住。',
      },
    ]
  }
  if (task.value.scene_type === 'listen') {
    return [
      {
        kicker: '触发结果',
        title: `${latestRun.value.signal_breakdown.positive + latestRun.value.signal_breakdown.negative} 个有效触发`,
        description: '监听任务要重点核对已通知、已流转以及被冷却机制拦下的对象。',
      },
      {
        kicker: '跳过与冷却',
        title: `${skippedItems.value.length} 个无动作或跳过`,
        description: '这些对象最适合检查频率控制、动作条件或池内流转规则是否过严。',
      },
    ]
  }
  if (task.value.scene_type === 'backtest') {
    return [
      {
        kicker: '回放结果',
        title: latestRun.value.related_trade_review_group_name || '等待交割单结果',
        description: '回测任务最终价值在于把结果送进交割单分析，而不是停留在本页摘要。',
      },
      {
        kicker: '中性样本',
        title: `${skippedItems.value.length} 个未触发保持样本`,
        description: '这类未触发样本适合后面做分组对照，判断策略是否过于宽松或严格。',
      },
    ]
  }
  return [
    {
      kicker: '风险对象',
      title: `${negativeItems.value.length} 个负向或预警对象`,
      description: '模拟交易任务要优先看预警对象和模拟卖出结果，再决定是否要同步复盘。',
    },
    {
      kicker: '结果落点',
      title: latestRun.value.related_trade_review_group_name || '模拟结果待分析',
      description: '持仓演进的价值在于把每日动作沉淀到分析链路里，便于后续复盘归因。',
    },
  ]
})
const destinationCards = computed(() => {
  if (!task.value) return []
  if (task.value.scene_type === 'scan') {
    return [
      {
        kicker: '候选承接',
        title: '进入现有股池',
        description: '选股结果先承接到股池，再做流转、复盘和人工确认。',
        routeName: 'StockPools',
        actionLabel: '打开股池',
      },
      {
        kicker: '运行复核',
        title: '查看本轮候选',
        description: '先到运行结果里看强度、原因和是否值得继续观察。',
        routeName: latestRun.value ? 'StrategyRunDetailV2' : '',
        actionLabel: '查看最近运行',
      },
    ]
  }
  if (task.value.scene_type === 'listen') {
    return [
      {
        kicker: '触发留痕',
        title: '回看最近信号',
        description: '重点复核已通知、已流转和被冷却跳过的对象。',
        routeName: latestRun.value ? 'StrategyRunDetailV2' : '',
        actionLabel: '打开运行结果',
      },
      {
        kicker: '业务落点',
        title: '检查池内流转',
        description: '监听结果最终要落到池内变化或提醒动作，而不是停留在任务本身。',
        routeName: 'StockPools',
        actionLabel: '查看股池',
      },
    ]
  }
  return [
    {
      kicker: '分析闭环',
      title: '进入交割单分析',
      description: '回测和模拟交易的价值在于进入交割单分析页继续看收益与模式归因。',
      routeName: 'TradeReview',
      actionLabel: '打开交割单',
    },
    {
      kicker: '结果复核',
      title: '查看最新运行',
      description: '先确认模拟成交、风险信号和状态写回是否符合预期。',
      routeName: latestRun.value ? 'StrategyRunDetailV2' : '',
      actionLabel: '查看运行结果',
    },
  ]
})

onMounted(async () => {
  await loadData()
})

async function loadData(): Promise<void> {
  const taskId = String(route.params.taskId || '')
  const taskValue = await getStrategySceneTask(taskId)
  task.value = taskValue || null
  runs.value = await listTaskRuns(taskId)
  if (runs.value[0]) {
    latestRunItems.value = await getRunItems(runs.value[0].run_id)
  }
}

async function runNow(): Promise<void> {
  if (!task.value) return
  const run = await runStrategySceneTask(task.value.task_id)
  if (!run) {
    ElMessage.error('任务运行失败')
    return
  }
  ElMessage.success('已生成新的运行记录')
  await loadData()
  router.push({ name: 'StrategyRunDetailV2', params: { runId: run.run_id } })
}

function openLatestRun(): void {
  if (!latestRun.value) return
  router.push({ name: 'StrategyRunDetailV2', params: { runId: latestRun.value.run_id } })
}

function openRun(runId: string): void {
  router.push({ name: 'StrategyRunDetailV2', params: { runId } })
}

function openRoute(routeName: string): void {
  if (!routeName) return
  if (routeName === 'StrategyRunDetailV2' && latestRun.value) {
    router.push({ name: routeName, params: { runId: latestRun.value.run_id } })
    return
  }
  router.push({ name: routeName })
}

function editTask(): void {
  if (!task.value) return
  router.push({
    name: 'StrategyTaskCenterV2',
    query: {
      scene: task.value.scene_type,
      editTask: task.value.task_id,
    },
  })
}

function runStatusLabel(status: StrategyRunStatus): string {
  if (status === 'success') return '成功'
  if (status === 'partial_success') return '部分成功'
  if (status === 'failed') return '失败'
  return '运行中'
}

function runStatusTagType(status: StrategyRunStatus): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'success') return 'success'
  if (status === 'partial_success') return 'warning'
  if (status === 'failed') return 'danger'
  return 'info'
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
.task-detail-page {
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
.console-panel,
.item-card,
.status-card,
.mini-metric {
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

.hero-card h1 {
  margin: 0;
  font-size: 34px;
}

.description,
.run-brief p,
.action-card p,
.item-card p,
.next-action-card p {
  line-height: 1.7;
  color: var(--ink-soft);
}

.hero-actions {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.top-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.strip-card {
  border-radius: 20px;
  padding: 16px 18px;
}

.strip-card.emphasis {
  background: linear-gradient(180deg, rgba(47, 95, 208, 0.08), rgba(255, 255, 255, 0.9));
}

.strip-card span,
.status-card span,
.mini-metric span,
.config-row span,
.param-chip span,
.item-head span,
.item-meta {
  display: block;
  color: var(--ink-soft);
  font-size: 12px;
}

.strip-card strong,
.status-card strong {
  display: block;
  margin-top: 8px;
  font-size: 24px;
}

.workspace-shell {
  display: grid;
  grid-template-columns: 1.15fr 0.85fr;
  gap: 18px;
}

.operations-column,
.inspector-column {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.console-panel {
  border-radius: 28px;
  padding: 20px;
}

.section-title-row,
.run-brief-head,
.item-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.section-title-row h2,
.section-title-row h3,
.run-brief-head h3 {
  margin: 0;
}

.section-title-row h2 {
  font-size: 24px;
}

.section-title-row h3,
.run-brief-head h3 {
  font-size: 20px;
}

.section-title-row.compact .panel-tip {
  color: var(--ink-soft);
  font-size: 12px;
}

.status-grid,
.metric-list,
.param-list,
.item-grid {
  display: grid;
  gap: 12px;
}

.status-grid,
.metric-list {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-top: 16px;
}

.status-card,
.mini-metric,
.param-chip,
.action-card,
.item-card {
  border-radius: 18px;
  padding: 14px;
}

.run-brief {
  margin-top: 18px;
}

.mini-metric.positive strong {
  color: #16a34a;
}

.mini-metric.negative strong {
  color: #dc2626;
}

.mini-metric.warning strong {
  color: #d97706;
}

.mini-metric strong,
.param-chip strong {
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

.config-list,
.action-list,
.destination-list {
  display: grid;
  gap: 12px;
}

.focus-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.config-row {
  padding-bottom: 12px;
  border-bottom: 1px solid var(--line-soft);
}

.config-row:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.config-row strong {
  display: block;
  margin-top: 6px;
  line-height: 1.6;
}

.param-list {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.item-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.destination-card {
  border-radius: 18px;
  border: 1px solid var(--line-soft);
  background: rgba(255, 255, 255, 0.76);
  padding: 14px;
}

.focus-card span,
.destination-card span {
  display: block;
  color: var(--ink-soft);
  font-size: 12px;
}

.focus-card strong,
.destination-card strong {
  display: block;
  margin: 6px 0 8px;
}

.focus-card p,
.destination-card p {
  margin: 0 0 12px;
  color: var(--ink-soft);
  line-height: 1.7;
}

.focus-card {
  border-radius: 18px;
  border: 1px solid var(--line-soft);
  background: rgba(255, 255, 255, 0.76);
  padding: 14px;
}

.item-head strong {
  display: block;
}

.item-meta {
  display: flex;
  justify-content: space-between;
  gap: 10px;
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
  .top-strip,
  .workspace-shell,
  .status-grid,
  .metric-list,
  .param-list,
  .item-grid,
  .focus-grid {
    grid-template-columns: 1fr;
  }

  .hero-card,
  .section-title-row,
  .run-brief-head {
    flex-direction: column;
  }
}
</style>
