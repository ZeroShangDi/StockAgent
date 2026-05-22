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
        <el-button @click="router.push({ name: 'StrategyTaskCenterV2', query: { scene: task.scene_type } })">返回任务中心</el-button>
        <el-button type="primary" plain @click="runNow">手动运行</el-button>
        <el-button v-if="latestRun" type="primary" @click="openLatestRun">查看最近运行</el-button>
      </div>
    </section>

    <section class="summary-grid">
      <article class="summary-card">
        <span>任务状态</span>
        <strong>{{ statusLabels[task.status] }}</strong>
      </article>
      <article class="summary-card">
        <span>策略</span>
        <strong>{{ task.strategy_name }}</strong>
      </article>
      <article class="summary-card">
        <span>最近信号</span>
        <strong>{{ task.last_signal_count }}</strong>
      </article>
      <article class="summary-card">
        <span>调度</span>
        <strong>{{ task.schedule_label }}</strong>
      </article>
    </section>

    <section class="body-grid">
      <div class="left-column">
        <section class="panel-card">
          <header class="panel-header">
            <h2>任务配置</h2>
            <el-tag effect="plain" round>{{ sceneLabels[task.scene_type] }}</el-tag>
          </header>
          <div class="config-list">
            <div class="config-item">
              <span>目标范围</span>
              <strong>{{ task.target_scope_summary }}</strong>
            </div>
            <div class="config-item">
              <span>创建时间</span>
              <strong>{{ task.created_at }}</strong>
            </div>
            <div class="config-item">
              <span>最后更新</span>
              <strong>{{ task.updated_at }}</strong>
            </div>
          </div>
          <p class="notes">{{ task.notes || '当前还没有额外的任务说明。' }}</p>
        </section>

        <section class="panel-card">
          <header class="panel-header">
            <h2>参数预览</h2>
            <span class="panel-tip">当前先展示任务层默认参数</span>
          </header>
          <div class="param-grid">
            <article v-for="item in paramsEntries" :key="item.key" class="param-card">
              <span>{{ item.key }}</span>
              <strong>{{ item.value }}</strong>
            </article>
          </div>
        </section>

        <section class="panel-card">
          <header class="panel-header">
            <h2>任务动作</h2>
          </header>
          <div class="action-list">
            <article v-for="action in task.actions" :key="action.action_id" class="action-card">
              <strong>{{ action.label }}</strong>
              <p>{{ action.summary }}</p>
            </article>
          </div>
        </section>
      </div>

      <div class="right-column">
        <section class="panel-card">
          <header class="panel-header">
            <h2>最近运行记录</h2>
            <span class="panel-tip">{{ runs.length }} 条</span>
          </header>
          <el-table :data="runs" stripe>
            <el-table-column prop="title" label="运行标题" min-width="180" />
            <el-table-column prop="run_status" label="状态" width="120">
              <template #default="{ row }">
                {{ runStatusLabel(row.run_status) }}
              </template>
            </el-table-column>
            <el-table-column prop="started_at" label="开始时间" width="160" />
            <el-table-column label="信号" width="120">
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

        <section v-if="latestRunItems.length > 0" class="panel-card">
          <header class="panel-header">
            <h2>最近运行明细预览</h2>
          </header>
          <div class="item-list">
            <article v-for="item in latestRunItems" :key="item.item_id" class="item-card">
              <div class="item-head">
                <strong>{{ item.entity_name }}</strong>
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
      </div>
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

function runStatusLabel(status: StrategyRunStatus): string {
  if (status === 'success') return '成功'
  if (status === 'partial_success') return '部分成功'
  if (status === 'failed') return '失败'
  return '运行中'
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
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.hero-card,
.summary-card,
.panel-card {
  border: 1px solid var(--el-border-color-lighter);
  background:
    radial-gradient(circle at top right, rgba(46, 125, 255, 0.12), transparent 28%),
    linear-gradient(135deg, rgba(255, 255, 255, 0.98), rgba(246, 248, 252, 0.96));
  box-shadow: 0 18px 44px rgba(15, 23, 42, 0.08);
}

.hero-card {
  border-radius: 28px;
  padding: 28px;
  display: flex;
  justify-content: space-between;
  gap: 24px;
}

.eyebrow {
  margin: 0 0 10px;
  font-size: 12px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: #4b6cb7;
}

.hero-card h1 {
  margin: 0;
  font-size: 34px;
}

.description {
  margin: 10px 0 0;
  line-height: 1.7;
  color: var(--el-text-color-secondary);
}

.hero-actions {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.summary-card {
  border-radius: 22px;
  padding: 18px 20px;
}

.summary-card span {
  display: block;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.summary-card strong {
  display: block;
  margin-top: 8px;
  font-size: 24px;
}

.body-grid {
  display: grid;
  grid-template-columns: 1fr 1.1fr;
  gap: 18px;
}

.left-column,
.right-column {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.panel-card {
  border-radius: 24px;
  padding: 20px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  margin-bottom: 16px;
}

.panel-header h2 {
  margin: 0;
  font-size: 20px;
}

.panel-tip {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.config-list {
  display: grid;
  gap: 14px;
}

.config-item span {
  display: block;
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--el-text-color-secondary);
}

.config-item strong {
  display: block;
  margin-top: 6px;
}

.notes {
  margin: 16px 0 0;
  line-height: 1.7;
  color: var(--el-text-color-secondary);
}

.param-grid,
.action-list,
.item-list {
  display: grid;
  gap: 12px;
}

.param-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.param-card,
.action-card,
.item-card {
  border-radius: 18px;
  border: 1px solid var(--el-border-color-lighter);
  background: rgba(255, 255, 255, 0.84);
  padding: 14px;
}

.param-card span,
.item-meta {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.param-card strong {
  display: block;
  margin-top: 6px;
}

.action-card p,
.item-card p {
  margin: 8px 0 0;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}

.item-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
}

.item-meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
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

@media (max-width: 1100px) {
  .summary-grid,
  .body-grid,
  .param-grid {
    grid-template-columns: 1fr;
  }

  .hero-card {
    flex-direction: column;
  }
}
</style>
