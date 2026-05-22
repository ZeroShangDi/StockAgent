<template>
  <div class="task-center-page">
    <section class="hero-card">
      <div>
        <p class="eyebrow">Strategy Tasks V2</p>
        <h1>场景任务中心 V2</h1>
        <p class="description">
          任务才是 V2 的业务主对象。策略保持纯函数，任务负责目标范围、调度、动作与运行结果。
        </p>
      </div>
      <div class="hero-actions">
        <el-button @click="router.push({ name: 'StrategyCenterV2' })">策略中心</el-button>
        <el-button type="primary" @click="openCreateDialog()">新建任务</el-button>
      </div>
    </section>

    <section class="stats-grid">
      <article class="stat-card">
        <span>任务总数</span>
        <strong>{{ tasks.length }}</strong>
      </article>
      <article class="stat-card">
        <span>运行中任务</span>
        <strong>{{ activeTaskCount }}</strong>
      </article>
      <article class="stat-card">
        <span>最近运行数</span>
        <strong>{{ recentRunCount }}</strong>
      </article>
      <article class="stat-card">
        <span>高优先动作</span>
        <strong>{{ priorityActionCount }}</strong>
      </article>
    </section>

    <section class="control-bar">
      <el-tabs v-model="activeScene">
        <el-tab-pane v-for="scene in sceneTabs" :key="scene.value" :label="scene.label" :name="scene.value" />
      </el-tabs>
      <div class="control-actions">
        <el-input v-model="keyword" clearable placeholder="搜索任务名称 / 策略 / 标签" />
      </div>
    </section>

    <section class="task-grid">
      <article v-for="task in filteredTasks" :key="task.task_id" class="task-card">
        <div class="task-head">
          <div>
            <div class="task-title-row">
              <h3>{{ task.name }}</h3>
              <el-tag :type="statusTagType(task.status)" effect="plain" round>
                {{ statusLabels[task.status] }}
              </el-tag>
            </div>
            <p class="task-subtitle">{{ sceneLabels[task.scene_type] }} · {{ task.strategy_name }}</p>
          </div>
          <div class="task-score">
            <span>最近信号</span>
            <strong>{{ task.last_signal_count }}</strong>
          </div>
        </div>

        <div class="task-body">
          <div class="meta-row">
            <span class="meta-label">目标范围</span>
            <strong>{{ task.target_scope_summary }}</strong>
          </div>
          <div class="meta-row">
            <span class="meta-label">调度</span>
            <strong>{{ task.schedule_label }}</strong>
          </div>
          <div class="meta-row">
            <span class="meta-label">动作</span>
            <div class="tag-row">
              <span v-for="action in task.actions" :key="action.action_id" class="tag-chip">
                {{ action.label }}
              </span>
            </div>
          </div>
          <p class="task-notes">{{ task.notes || '当前未填写任务说明。' }}</p>
        </div>

        <div class="task-footer">
          <div class="footer-meta">
            <span>更新于 {{ task.updated_at }}</span>
            <span v-if="task.last_run_status">最近运行 {{ runStatusLabel(task.last_run_status) }}</span>
          </div>
          <div class="footer-actions">
            <el-button size="small" @click="goDetail(task.task_id)">详情</el-button>
            <el-button
              size="small"
              type="primary"
              plain
              @click="handleRun(task.task_id)"
            >
              手动运行
            </el-button>
            <el-dropdown trigger="click" @command="(value: string) => handleStatusCommand(task.task_id, value)">
              <el-button size="small">
                更多
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="active">启用</el-dropdown-item>
                  <el-dropdown-item command="paused">暂停</el-dropdown-item>
                  <el-dropdown-item command="draft">设为草稿</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>
      </article>
    </section>

    <el-empty v-if="filteredTasks.length === 0" description="当前筛选条件下还没有任务，可以先创建一条 V2 任务。" />

    <el-dialog v-model="createDialogVisible" title="新建场景任务 V2" width="680px" :close-on-click-modal="false">
      <div class="dialog-grid">
        <el-form label-position="top">
          <el-form-item label="任务名称">
            <el-input v-model="taskForm.name" placeholder="例如：盘口异动监听 V2" />
          </el-form-item>
          <el-form-item label="场景类型">
            <el-select v-model="taskForm.scene_type" style="width: 100%">
              <el-option v-for="scene in sceneTabs" :key="scene.value" :label="scene.label" :value="scene.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="策略">
            <el-select v-model="taskForm.strategy_key" style="width: 100%">
              <el-option v-for="strategy in strategyOptions" :key="strategy.strategy_key" :label="strategy.name" :value="strategy.strategy_key">
                <div class="strategy-option">
                  <span>{{ strategy.name }}</span>
                  <small>{{ strategy.description }}</small>
                </div>
              </el-option>
            </el-select>
          </el-form-item>
          <el-form-item label="目标范围">
            <el-input v-model="taskForm.target_scope_summary" placeholder="例如：观察池 + 自选股" />
          </el-form-item>
          <el-form-item label="调度方式">
            <el-input v-model="taskForm.schedule_label" placeholder="例如：交易时段每 1 分钟轮询" />
          </el-form-item>
          <el-form-item label="任务说明">
            <el-input v-model="taskForm.notes" type="textarea" :rows="3" placeholder="说明这个任务在策略链路中的角色。" />
          </el-form-item>
        </el-form>

        <section class="action-section">
          <div class="section-header">
            <h3>任务动作</h3>
            <span>场景来解释策略信号并执行动作</span>
          </div>
          <el-checkbox-group v-model="taskForm.actions" class="action-grid">
            <el-checkbox v-for="item in actionOptions" :key="item.value" :label="item.value">
              <div class="action-option">
                <strong>{{ item.label }}</strong>
                <small>{{ item.description }}</small>
              </div>
            </el-checkbox>
          </el-checkbox-group>
        </section>
      </div>

      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitCreateTask">创建任务</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import {
  createStrategySceneTask,
  getStrategyV2Overview,
  listStrategyDefinitions,
  listStrategySceneTasks,
  runStrategySceneTask,
  STRATEGY_ACTION_LABELS,
  STRATEGY_SCENE_LABELS,
  STRATEGY_TASK_STATUS_LABELS,
  updateStrategySceneTaskStatus,
} from '@/mocks/strategyV2'
import type {
  CreateStrategySceneTaskInput,
  StrategyActionType,
  StrategyDefinition,
  StrategyRunStatus,
  StrategySceneTask,
  StrategySceneType,
  StrategyTaskStatus,
} from '@/types/strategy-v2'

const route = useRoute()
const router = useRouter()

const tasks = ref<StrategySceneTask[]>([])
const strategyOptions = ref<StrategyDefinition[]>([])
const keyword = ref('')
const activeScene = ref<StrategySceneType>('listen')
const createDialogVisible = ref(false)
const submitting = ref(false)
const overview = ref({
  strategyCount: 0,
  statefulCount: 0,
  taskCount: 0,
  activeTaskCount: 0,
  runCount: 0,
})

const sceneLabels = STRATEGY_SCENE_LABELS
const statusLabels = STRATEGY_TASK_STATUS_LABELS

const sceneTabs = [
  { label: STRATEGY_SCENE_LABELS.listen, value: 'listen' as const },
  { label: STRATEGY_SCENE_LABELS.scan, value: 'scan' as const },
  { label: STRATEGY_SCENE_LABELS.backtest, value: 'backtest' as const },
  { label: STRATEGY_SCENE_LABELS.sim_trade, value: 'sim_trade' as const },
]

const actionOptions: Array<{ value: StrategyActionType; label: string; description: string }> = [
  { value: 'notify', label: STRATEGY_ACTION_LABELS.notify, description: '发送提醒，用于监听与风险提示。' },
  { value: 'add_to_pool', label: STRATEGY_ACTION_LABELS.add_to_pool, description: '把正向候选送进现有股池。' },
  { value: 'pool_transition', label: STRATEGY_ACTION_LABELS.pool_transition, description: '在多个股池之间自动流转。' },
  { value: 'temp_list', label: STRATEGY_ACTION_LABELS.temp_list, description: '保留临时候选结果供人工筛选。' },
  { value: 'paper_trade', label: STRATEGY_ACTION_LABELS.paper_trade, description: '写入回测或模拟交易结果。' },
]

const taskForm = reactive<CreateStrategySceneTaskInput>({
  name: '',
  scene_type: 'listen',
  strategy_key: '',
  target_scope_summary: '',
  schedule_label: '',
  notes: '',
  actions: ['notify'],
})

const filteredTasks = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  return tasks.value.filter((task) => {
    const matchesScene = task.scene_type === activeScene.value
    const matchesText =
      !text ||
      task.name.toLowerCase().includes(text) ||
      task.strategy_name.toLowerCase().includes(text) ||
      task.tags.some((tag) => tag.toLowerCase().includes(text))
    return matchesScene && matchesText
  })
})

const activeTaskCount = computed(() => tasks.value.filter((item) => item.status === 'active').length)
const recentRunCount = computed(() => tasks.value.filter((item) => !!item.last_run_id).length)
const priorityActionCount = computed(() => tasks.value.reduce((sum, item) => sum + item.actions.length, 0))

onMounted(async () => {
  await refreshPage()
  hydrateFromQuery()
})

watch(
  () => route.query,
  () => {
    hydrateFromQuery()
  },
)

async function refreshPage(): Promise<void> {
  tasks.value = await listStrategySceneTasks()
  strategyOptions.value = await listStrategyDefinitions()
  overview.value = await getStrategyV2Overview()
}

function hydrateFromQuery(): void {
  const scene = String(route.query.scene || '').trim() as StrategySceneType
  const strategy = String(route.query.strategy || '').trim()
  const autoCreate = String(route.query.autoCreate || '') === '1'

  if (scene && ['scan', 'listen', 'backtest', 'sim_trade'].includes(scene)) {
    activeScene.value = scene
    taskForm.scene_type = scene
  }
  if (strategy) {
    taskForm.strategy_key = strategy
  }
  if (autoCreate) {
    openCreateDialog({
      scene,
      strategy,
    })
    router.replace({ name: 'StrategyTaskCenterV2', query: { scene, strategy } })
  }
}

function openCreateDialog(preset?: { scene?: string; strategy?: string }): void {
  taskForm.name = ''
  taskForm.scene_type = (preset?.scene as StrategySceneType) || activeScene.value
  taskForm.strategy_key = preset?.strategy || taskForm.strategy_key || strategyOptions.value[0]?.strategy_key || ''
  taskForm.target_scope_summary = defaultScope(taskForm.scene_type)
  taskForm.schedule_label = defaultSchedule(taskForm.scene_type)
  taskForm.notes = ''
  taskForm.actions = defaultActions(taskForm.scene_type)
  createDialogVisible.value = true
}

function defaultScope(scene: StrategySceneType): string {
  if (scene === 'scan') return '全市场 · 排除 ST'
  if (scene === 'listen') return '观察池 + 自选股'
  if (scene === 'backtest') return '训练样本分组 + 指定回放区间'
  return '持仓组：实盘训练账户'
}

function defaultSchedule(scene: StrategySceneType): string {
  if (scene === 'scan') return '交易日 09:45 / 10:30 / 13:45'
  if (scene === 'listen') return '交易时段每 1 分钟轮询'
  if (scene === 'backtest') return '手动运行'
  return '交易日收盘后自动更新'
}

function defaultActions(scene: StrategySceneType): StrategyActionType[] {
  if (scene === 'scan') return ['add_to_pool', 'temp_list']
  if (scene === 'listen') return ['notify', 'pool_transition']
  return ['paper_trade']
}

async function submitCreateTask(): Promise<void> {
  if (!taskForm.name.trim()) {
    ElMessage.warning('请填写任务名称')
    return
  }
  if (!taskForm.strategy_key) {
    ElMessage.warning('请选择策略')
    return
  }
  if (!taskForm.target_scope_summary.trim()) {
    ElMessage.warning('请填写目标范围')
    return
  }
  if (taskForm.actions.length === 0) {
    ElMessage.warning('请至少选择一个动作')
    return
  }

  submitting.value = true
  try {
    const created = await createStrategySceneTask({
      ...taskForm,
      name: taskForm.name.trim(),
      target_scope_summary: taskForm.target_scope_summary.trim(),
      schedule_label: taskForm.schedule_label.trim(),
      notes: taskForm.notes?.trim(),
      actions: [...taskForm.actions],
    })
    await refreshPage()
    activeScene.value = created.scene_type
    createDialogVisible.value = false
    ElMessage.success('V2 任务已创建')
    router.push({ name: 'StrategyTaskDetailV2', params: { taskId: created.task_id } })
  } finally {
    submitting.value = false
  }
}

async function handleRun(taskId: string): Promise<void> {
  const run = await runStrategySceneTask(taskId)
  if (!run) {
    ElMessage.error('任务不存在')
    return
  }
  await refreshPage()
  ElMessage.success('已生成一条新的运行记录')
  router.push({ name: 'StrategyRunDetailV2', params: { runId: run.run_id } })
}

async function handleStatusCommand(taskId: string, value: string): Promise<void> {
  const nextStatus = value as StrategyTaskStatus
  await updateStrategySceneTaskStatus(taskId, nextStatus)
  await refreshPage()
  ElMessage.success(`任务已更新为${statusLabels[nextStatus]}`)
}

function goDetail(taskId: string): void {
  router.push({ name: 'StrategyTaskDetailV2', params: { taskId } })
}

function statusTagType(status: StrategyTaskStatus): 'success' | 'warning' | 'info' | 'primary' {
  if (status === 'active') return 'success'
  if (status === 'paused') return 'warning'
  if (status === 'draft') return 'info'
  return 'primary'
}

function runStatusLabel(status: StrategyRunStatus): string {
  if (status === 'success') return '成功'
  if (status === 'partial_success') return '部分成功'
  if (status === 'failed') return '失败'
  return '运行中'
}
</script>

<style scoped>
.task-center-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.hero-card,
.stat-card,
.task-card,
.control-bar {
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
  text-transform: uppercase;
  letter-spacing: 0.18em;
  color: #4b6cb7;
}

.hero-card h1 {
  margin: 0;
  font-size: 34px;
}

.description {
  max-width: 760px;
  margin: 10px 0 0;
  line-height: 1.7;
  color: var(--el-text-color-secondary);
}

.hero-actions {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.stat-card {
  border-radius: 22px;
  padding: 18px 20px;
}

.stat-card span {
  display: block;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.stat-card strong {
  display: block;
  margin-top: 8px;
  font-size: 28px;
}

.control-bar {
  border-radius: 22px;
  padding: 14px 18px 2px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
}

.control-actions {
  width: 320px;
}

.task-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}

.task-card {
  border-radius: 24px;
  padding: 20px;
}

.task-head,
.task-footer {
  display: flex;
  justify-content: space-between;
  gap: 16px;
}

.task-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.task-title-row h3 {
  margin: 0;
  font-size: 22px;
}

.task-subtitle {
  margin: 8px 0 0;
  color: #4f67a9;
  font-size: 13px;
}

.task-score {
  min-width: 92px;
  border-radius: 18px;
  background: rgba(46, 125, 255, 0.08);
  padding: 12px;
  text-align: center;
}

.task-score span {
  display: block;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.task-score strong {
  display: block;
  margin-top: 6px;
  font-size: 28px;
}

.task-body {
  margin: 18px 0;
}

.meta-row + .meta-row {
  margin-top: 12px;
}

.meta-label {
  display: block;
  margin-bottom: 6px;
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--el-text-color-secondary);
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tag-chip {
  padding: 5px 10px;
  border-radius: 999px;
  background: rgba(46, 125, 255, 0.1);
  color: #305ec9;
  font-size: 12px;
}

.task-notes {
  margin: 14px 0 0;
  line-height: 1.7;
  color: var(--el-text-color-secondary);
}

.footer-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.footer-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.dialog-grid {
  display: grid;
  grid-template-columns: 1.15fr 0.85fr;
  gap: 20px;
}

.action-section {
  border-radius: 20px;
  border: 1px solid var(--el-border-color-lighter);
  background: rgba(255, 255, 255, 0.72);
  padding: 18px;
}

.section-header h3 {
  margin: 0;
  font-size: 18px;
}

.section-header span {
  display: block;
  margin-top: 6px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.action-grid {
  display: grid;
  gap: 14px;
  margin-top: 18px;
}

.action-option {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.action-option small,
.strategy-option small {
  color: var(--el-text-color-secondary);
}

@media (max-width: 1100px) {
  .stats-grid,
  .task-grid,
  .dialog-grid {
    grid-template-columns: 1fr;
  }

  .hero-card,
  .control-bar,
  .task-head,
  .task-footer {
    flex-direction: column;
  }

  .control-actions {
    width: 100%;
  }
}
</style>
