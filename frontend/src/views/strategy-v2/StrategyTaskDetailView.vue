<template>
  <div class="task-detail-page">
    <section class="detail-toolbar">
      <el-button size="small" @click="router.push({ name: 'StrategyTaskCenterV2', query: task ? { scene: task.scene_type } : {} })">
        返回任务列表
      </el-button>
      <div class="toolbar-actions">
        <el-button size="small" @click="loadTask">刷新</el-button>
        <el-button
          v-if="task"
          size="small"
          type="primary"
          :loading="running"
          :disabled="hasRunningRun"
          @click="runTaskNow"
        >
          {{ hasRunningRun ? '运行中' : '立即运行' }}
        </el-button>
      </div>
    </section>

    <el-skeleton v-if="loading" :rows="8" animated />

    <el-empty v-else-if="!task" description="任务不存在或没有权限访问" />

    <template v-else>
      <section class="summary-card">
        <div class="summary-main">
          <div>
            <div class="title-line">
              <h1>{{ task.name }}</h1>
              <el-tag :type="statusTagType(task.status)" effect="plain" round>
                {{ statusLabel(task.status) }}
              </el-tag>
            </div>
            <p>{{ task.notes || '暂无任务说明' }}</p>
          </div>
          <div class="summary-actions">
            <el-button size="small" type="primary" plain @click="router.push({ name: 'StrategyCenterV2', query: { strategy: task.strategy_key } })">
              查看策略
            </el-button>
            <el-button v-if="task.last_run_id" size="small" plain @click="openRun(task.last_run_id)">
              最近结果
            </el-button>
          </div>
        </div>
      </section>

      <section class="metric-grid">
        <article class="metric-card">
          <span>场景</span>
          <strong>{{ sceneLabel(task.scene_type) }}</strong>
        </article>
        <article class="metric-card">
          <span>策略</span>
          <strong>{{ task.strategy_name }}</strong>
        </article>
        <article class="metric-card">
          <span>调度</span>
          <strong>{{ task.schedule_label || task.schedule?.label || '-' }}</strong>
        </article>
        <article class="metric-card">
          <span>最近信号</span>
          <strong>{{ task.last_signal_count || 0 }}</strong>
        </article>
      </section>

      <section class="detail-grid">
        <article class="detail-card span-2">
          <div class="card-head">
            <h2>目标范围</h2>
          </div>
          <div class="scope-summary">
            <strong>{{ task.target_scope_summary || task.target_scope?.summary || '-' }}</strong>
            <pre v-if="task.target_scope">{{ formatJson(task.target_scope) }}</pre>
          </div>
        </article>

        <article class="detail-card">
          <div class="card-head">
            <h2>策略参数</h2>
          </div>
          <div v-if="paramEntries.length > 0" class="key-value-list">
            <div v-for="item in paramEntries" :key="item.key" class="key-value-row">
              <span>{{ item.key }}</span>
              <strong>{{ item.value }}</strong>
            </div>
          </div>
          <el-empty v-else description="使用策略默认参数" :image-size="64" />
        </article>

        <article class="detail-card">
          <div class="card-head">
            <h2>运行信息</h2>
          </div>
          <div class="key-value-list">
            <div class="key-value-row">
              <span>最近运行</span>
              <strong>
                <button v-if="task.last_run_id" class="text-button" type="button" @click="openRun(task.last_run_id)">
                  {{ task.last_run_status ? runStatusLabel(task.last_run_status) : '查看结果' }}
                </button>
                <template v-else>未运行</template>
              </strong>
            </div>
            <div class="key-value-row">
              <span>创建时间</span>
              <strong>{{ formatDateTime(task.created_at) }}</strong>
            </div>
            <div class="key-value-row">
              <span>更新时间</span>
              <strong>{{ formatDateTime(task.updated_at) }}</strong>
            </div>
          </div>
        </article>

        <article class="detail-card span-2">
          <div class="card-head">
            <h2>动作规则</h2>
          </div>
          <el-table v-if="task.actions.length > 0" :data="task.actions" size="small" stripe>
            <el-table-column label="动作" min-width="140">
              <template #default="{ row }">
                {{ row.label || actionLabel(row.action_type) }}
              </template>
            </el-table-column>
            <el-table-column label="触发信号" width="140">
              <template #default="{ row }">
                {{ Array.isArray(row.trigger_signals) ? row.trigger_signals.join(' / ') : '-' }}
              </template>
            </el-table-column>
            <el-table-column label="启用" width="90">
              <template #default="{ row }">
                {{ row.enabled ? '是' : '否' }}
              </template>
            </el-table-column>
            <el-table-column label="说明" min-width="220" prop="summary" show-overflow-tooltip />
          </el-table>
          <el-empty v-else description="当前任务没有动作规则" :image-size="64" />
        </article>

        <article class="detail-card span-2">
          <div class="card-head">
            <h2>运行记录</h2>
            <el-button size="small" text @click="loadRuns">刷新记录</el-button>
          </div>
          <el-table v-if="runs.length > 0" :data="runs" size="small" stripe>
            <el-table-column label="运行" min-width="180">
              <template #default="{ row }">
                <button class="text-button strong" type="button" @click="openRun(row.run_id)">
                  {{ row.title }}
                </button>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="runStatusTagType(row.run_status)" effect="plain" round>
                  {{ runStatusLabel(row.run_status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="信号" width="150">
              <template #default="{ row }">
                +{{ row.signal_breakdown?.positive || 0 }} / 0 {{ row.signal_breakdown?.neutral || 0 }} / -{{ row.signal_breakdown?.negative || 0 }}
              </template>
            </el-table-column>
            <el-table-column label="产物" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.related_pool_name || row.related_trade_review_group_name || '-' }}
              </template>
            </el-table-column>
            <el-table-column label="开始时间" width="170">
              <template #default="{ row }">
                {{ formatDateTime(row.started_at) }}
              </template>
            </el-table-column>
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="{ row }">
                <el-button v-if="row.run_status === 'running'" size="small" text type="danger" @click="cancelRun(row)">
                  取消
                </el-button>
                <el-button v-else size="small" text type="primary" @click="retryRun(row)">
                  重试
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="暂无运行记录" :image-size="64" />
        </article>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  cancelTaskRun,
  getStrategySceneTask,
  listStrategySceneTasks,
  listTaskRuns,
  retryTaskRun,
  runStrategySceneTask,
} from '@/api/modules/strategy-v2'
import {
  STRATEGY_ACTION_LABELS,
  STRATEGY_SCENE_LABELS,
  STRATEGY_TASK_STATUS_LABELS,
} from '@/mocks/strategyV2'
import type {
  StrategyActionType,
  StrategyRunStatus,
  StrategySceneTask,
  StrategySceneType,
  StrategyTaskRun,
  StrategyTaskStatus,
} from '@/types/strategy-v2'

const route = useRoute()
const router = useRouter()

const task = ref<StrategySceneTask | null>(null)
const runs = ref<StrategyTaskRun[]>([])
const loading = ref(false)
const running = ref(false)

const paramEntries = computed(() => {
  if (!task.value) return []
  return Object.entries(task.value.params || {}).map(([key, value]) => ({
    key,
    value: formatValue(value),
  }))
})
const hasRunningRun = computed(() => {
  return Boolean(task.value?.active_run_id || runs.value.some((run) => run.run_status === 'running'))
})

onMounted(async () => {
  await loadTask()
})

async function loadTask(): Promise<void> {
  const taskId = String(route.params.taskId || '').trim()
  if (!taskId) {
    task.value = null
    return
  }

  loading.value = true
  try {
    task.value = await getStrategySceneTask(taskId)
    await loadRuns()
  }
  catch (error) {
    try {
      const tasks = await listStrategySceneTasks()
      task.value = tasks.find((item) => item.task_id === taskId) || null
      if (!task.value) {
        ElMessage.error('任务详情加载失败')
      }
    }
    catch (fallbackError) {
      console.error(error, fallbackError)
      task.value = null
      ElMessage.error('任务详情加载失败')
    }
  }
  finally {
    loading.value = false
  }
}

async function loadRuns(): Promise<void> {
  if (!task.value) {
    runs.value = []
    return
  }
  try {
    runs.value = await listTaskRuns(task.value.task_id)
  }
  catch (error) {
    console.error(error)
    runs.value = []
  }
}

async function runTaskNow(): Promise<void> {
  if (!task.value) return
  if (hasRunningRun.value) {
    ElMessage.warning('当前任务已有运行中的记录，请先等待完成或取消')
    return
  }
  running.value = true
  try {
    const run = await runStrategySceneTask(task.value.task_id)
    ElMessage.success('任务已开始运行')
    await loadTask()
    router.push({ name: 'StrategyRunDetailV2', params: { runId: run.run_id } })
  }
  catch (error) {
    console.error(error)
    ElMessage.error('任务运行启动失败')
  }
  finally {
    running.value = false
  }
}

async function cancelRun(row: StrategyTaskRun): Promise<void> {
  try {
    await ElMessageBox.confirm('取消后本次运行会停止继续扫描，已产生的运行明细会保留用于排查。', '取消运行', {
      type: 'warning',
      confirmButtonText: '确认取消',
      cancelButtonText: '先不取消',
    })
    await cancelTaskRun(row.run_id)
    ElMessage.success('已请求取消运行')
    await loadTask()
  }
  catch (error) {
    if (error === 'cancel') return
    console.error(error)
    ElMessage.error('取消运行失败')
  }
}

async function retryRun(row: StrategyTaskRun): Promise<void> {
  if (hasRunningRun.value) {
    ElMessage.warning('当前任务已有运行中的记录，暂时不能重试')
    return
  }
  try {
    const nextRun = await retryTaskRun(row.run_id)
    ElMessage.success('已开始重试')
    await loadTask()
    router.push({ name: 'StrategyRunDetailV2', params: { runId: nextRun.run_id } })
  }
  catch (error) {
    console.error(error)
    ElMessage.error('重试启动失败')
  }
}

function openRun(runId: string): void {
  router.push({ name: 'StrategyRunDetailV2', params: { runId } })
}

function sceneLabel(scene: StrategySceneType): string {
  return STRATEGY_SCENE_LABELS[scene]
}

function statusLabel(status: StrategyTaskStatus): string {
  return STRATEGY_TASK_STATUS_LABELS[status]
}

function actionLabel(action: StrategyActionType): string {
  return STRATEGY_ACTION_LABELS[action]
}

function runStatusLabel(status: StrategyRunStatus): string {
  if (status === 'success') return '成功'
  if (status === 'partial_success') return '部分成功'
  if (status === 'failed') return '失败'
  if (status === 'cancelled') return '已取消'
  return '运行中'
}

function statusTagType(status: StrategyTaskStatus): 'success' | 'warning' | 'info' | 'primary' {
  if (status === 'active') return 'success'
  if (status === 'paused') return 'warning'
  if (status === 'draft') return 'info'
  return 'primary'
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

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function formatJson(value: unknown): string {
  return JSON.stringify(value, null, 2)
}
</script>

<style scoped>
.task-detail-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.detail-toolbar,
.summary-card,
.metric-card,
.detail-card {
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.04);
}

.detail-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 12px;
}

.toolbar-actions {
  display: flex;
  gap: 8px;
}

.summary-card {
  padding: 18px;
}

.summary-main,
.title-line,
.card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.title-line {
  align-items: center;
  justify-content: flex-start;
}

.title-line h1,
.card-head h2 {
  margin: 0;
  color: #0f172a;
}

.title-line h1 {
  font-size: 22px;
}

.card-head h2 {
  font-size: 16px;
}

.summary-card p {
  margin: 8px 0 0;
  color: #64748b;
  line-height: 1.7;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.metric-card,
.detail-card {
  padding: 14px;
}

.metric-card span,
.key-value-row span {
  display: block;
  color: #64748b;
  font-size: 12px;
}

.metric-card strong {
  display: block;
  margin-top: 6px;
  color: #0f172a;
  font-size: 18px;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.span-2 {
  grid-column: 1 / -1;
}

.scope-summary {
  display: grid;
  gap: 10px;
  margin-top: 12px;
}

.scope-summary pre {
  max-height: 240px;
  margin: 0;
  padding: 12px;
  overflow: auto;
  border-radius: 10px;
  background: #f8fafc;
  color: #334155;
  font-size: 12px;
  line-height: 1.6;
}

.key-value-list {
  display: grid;
  gap: 10px;
  margin-top: 12px;
}

.text-button {
  margin: 0;
  padding: 0;
  border: 0;
  background: transparent;
  color: #2563eb;
  cursor: pointer;
  font: inherit;
}

.text-button.strong {
  font-weight: 700;
}

.text-button:hover {
  color: #1d4ed8;
  text-decoration: underline;
}

.key-value-row {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 10px;
  border-bottom: 1px solid #eef2f7;
}

.key-value-row:last-child {
  padding-bottom: 0;
  border-bottom: none;
}

.key-value-row strong {
  color: #0f172a;
  text-align: right;
  word-break: break-all;
}

@media (max-width: 1080px) {
  .summary-main,
  .detail-toolbar {
    flex-direction: column;
  }

  .metric-grid,
  .detail-grid {
    grid-template-columns: 1fr;
  }

  .span-2 {
    grid-column: auto;
  }
}
</style>
