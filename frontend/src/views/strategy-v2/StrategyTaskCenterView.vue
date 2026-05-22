<template>
  <div class="task-center-page">
    <section class="hero-card">
      <div>
        <p class="eyebrow">Strategy Tasks V2</p>
        <h1>任务控制台</h1>
        <p class="description">
          这里不是“策略展示页”，而是日常工作台。你在这里决定哪个策略挂到哪个场景、扫什么范围、触发后要做什么动作。
        </p>
      </div>
      <div class="hero-actions">
        <el-button @click="router.push({ name: 'StrategyCenterV2' })">查看策略定义</el-button>
        <el-button type="primary" @click="openCreateDialog()">创建任务</el-button>
      </div>
    </section>

    <section class="top-stats">
      <article class="stat-card">
        <span>全部任务</span>
        <strong>{{ tasks.length }}</strong>
      </article>
      <article class="stat-card">
        <span>运行中</span>
        <strong>{{ activeTaskCount }}</strong>
      </article>
      <article class="stat-card">
        <span>有最近运行</span>
        <strong>{{ recentRunCount }}</strong>
      </article>
      <article class="stat-card">
        <span>动作密度</span>
        <strong>{{ priorityActionCount }}</strong>
      </article>
    </section>

    <section class="workspace-shell">
      <aside class="scene-rail">
        <div class="rail-head">
          <span class="rail-kicker">场景视图</span>
          <h2>Scenes</h2>
        </div>
        <button
          v-for="scene in sceneTabs"
          :key="scene.value"
          type="button"
          :class="['scene-button', { active: activeScene === scene.value }]"
          @click="activeScene = scene.value"
        >
          <div>
            <strong>{{ scene.label }}</strong>
            <small>{{ sceneHint(scene.value) }}</small>
          </div>
          <span>{{ taskCountByScene(scene.value) }}</span>
        </button>
      </aside>

      <section class="board-panel">
        <div class="board-toolbar">
          <div class="toolbar-main">
            <span class="panel-kicker">当前场景</span>
            <h2>{{ sceneLabels[activeScene] }}</h2>
          </div>
          <div class="toolbar-actions">
            <el-input v-model="keyword" clearable placeholder="搜索任务 / 策略 / 标签" />
            <el-button type="primary" @click="openCreateDialog()">新建任务</el-button>
          </div>
        </div>

        <div class="board-strip">
          <div class="strip-chip">
            <span>当前场景任务</span>
            <strong>{{ filteredTasks.length }}</strong>
          </div>
          <div class="strip-chip">
            <span>激活任务</span>
            <strong>{{ filteredTasks.filter(item => item.status === 'active').length }}</strong>
          </div>
          <div class="strip-chip">
            <span>平均动作数</span>
            <strong>{{ avgActionCount }}</strong>
          </div>
          <div class="strip-chip muted">
            <span>工作建议</span>
            <strong>{{ sceneSuggestion }}</strong>
          </div>
        </div>

        <div class="task-list">
          <button
            v-for="task in filteredTasks"
            :key="task.task_id"
            type="button"
            :class="['task-row', { active: task.task_id === selectedTaskId }]"
            @click="selectedTaskId = task.task_id"
          >
            <div class="task-row-main">
              <div class="task-title-line">
                <strong>{{ task.name }}</strong>
                <el-tag :type="statusTagType(task.status)" effect="plain" round>
                  {{ statusLabels[task.status] }}
                </el-tag>
              </div>
              <div class="task-sub-line">
                <span>{{ task.strategy_name }}</span>
                <span>·</span>
                <span>{{ task.target_scope_summary }}</span>
              </div>
              <div class="task-action-line">
                <span v-for="action in task.actions" :key="action.action_id" class="action-chip">
                  {{ action.label }}
                </span>
              </div>
            </div>

            <div class="task-row-side">
              <div class="metric-block">
                <span>最近信号</span>
                <strong>{{ task.last_signal_count }}</strong>
              </div>
              <div class="meta-stack">
                <span>{{ task.schedule_label }}</span>
                <span v-if="task.last_run_status">最近运行 {{ runStatusLabel(task.last_run_status) }}</span>
              </div>
              <div class="row-actions">
                <el-button size="small" @click.stop="goDetail(task.task_id)">详情</el-button>
                <el-button size="small" plain @click.stop="openEditDialog(task.task_id)">编辑</el-button>
                <el-button
                  size="small"
                  :type="task.status === 'active' ? 'warning' : 'success'"
                  plain
                  @click.stop="toggleTaskStatus(task)"
                >
                  {{ statusActionLabel(task.status) }}
                </el-button>
                <el-button size="small" type="primary" plain @click.stop="handleRun(task.task_id)">运行</el-button>
              </div>
            </div>
          </button>

          <el-empty v-if="filteredTasks.length === 0" description="当前场景下还没有任务，可以先新建一条任务。" />
        </div>
      </section>

      <aside class="inspector-panel">
        <div class="panel-block">
          <span class="panel-kicker">工作上下文</span>
          <h2>{{ sceneLabels[activeScene] }}</h2>
          <p>{{ sceneDetail(activeScene) }}</p>
        </div>

        <div v-if="selectedTask" class="panel-block emphasis">
          <div class="inspector-head">
            <div>
              <span class="panel-kicker">当前聚焦</span>
              <h3>{{ selectedTask.name }}</h3>
            </div>
            <el-tag :type="statusTagType(selectedTask.status)" effect="plain" round>
              {{ statusLabels[selectedTask.status] }}
            </el-tag>
          </div>
          <div class="inspector-meta">
            <div>
              <span>策略</span>
              <strong>{{ selectedTask.strategy_name }}</strong>
            </div>
            <div>
              <span>范围</span>
              <strong>{{ selectedTask.target_scope_summary }}</strong>
            </div>
            <div>
              <span>调度</span>
              <strong>{{ selectedTask.schedule_label }}</strong>
            </div>
          </div>
          <p class="inspector-notes">{{ selectedTask.notes || '当前没有额外说明。' }}</p>
          <div class="quick-actions">
            <el-button type="primary" @click="goDetail(selectedTask.task_id)">查看详情</el-button>
            <el-button plain @click="openEditDialog(selectedTask.task_id)">编辑任务</el-button>
            <el-button :type="selectedTask.status === 'active' ? 'warning' : 'success'" plain @click="toggleTaskStatus(selectedTask)">
              {{ statusActionLabel(selectedTask.status) }}
            </el-button>
            <el-button @click="handleRun(selectedTask.task_id)">立即运行</el-button>
          </div>
        </div>

        <div class="panel-block">
          <span class="panel-kicker">任务原则</span>
          <div class="principle-list">
            <article class="principle-card">
              <strong>策略负责判断</strong>
              <p>不要在策略定义里直接写通知、入池、流转。</p>
            </article>
            <article class="principle-card">
              <strong>任务负责动作</strong>
              <p>任务把同一策略挂到不同目标范围和动作上。</p>
            </article>
            <article class="principle-card">
              <strong>运行负责反馈</strong>
              <p>最终要回到运行结果页复盘，而不是停留在配置本身。</p>
            </article>
          </div>
        </div>
      </aside>
    </section>

    <el-dialog v-model="createDialogVisible" :title="dialogTitle" width="860px" :close-on-click-modal="false">
      <div class="dialog-shell">
        <section class="form-panel">
          <div class="wizard-steps">
            <button
              v-for="(step, index) in createStepItems"
              :key="step.title"
              type="button"
              :class="['wizard-step', { active: createStepIndex === index, done: index < createStepIndex }]"
              @click="jumpToCreateStep(index)"
            >
              <span>{{ index + 1 }}</span>
              <div>
                <strong>{{ step.title }}</strong>
                <small>{{ step.description }}</small>
              </div>
            </button>
          </div>

          <el-form label-position="top">
            <template v-if="createStepIndex === 0">
              <el-form-item label="任务名称">
                <el-input v-model="taskForm.name" placeholder="例如：主线盘口监听 / MA5 候选入池" />
              </el-form-item>
              <el-form-item label="场景类型">
                <el-select v-model="taskForm.scene_type" style="width: 100%">
                  <el-option v-for="scene in sceneTabs" :key="scene.value" :label="scene.label" :value="scene.value" />
                </el-select>
              </el-form-item>
              <el-form-item label="策略">
                <el-select v-model="taskForm.strategy_key" style="width: 100%">
                  <el-option
                    v-for="strategy in strategyOptions"
                    :key="strategy.strategy_key"
                    :label="strategy.name"
                    :value="strategy.strategy_key"
                  >
                    <div class="strategy-option">
                      <span>{{ strategy.name }}</span>
                      <small>{{ strategy.description }}</small>
                    </div>
                  </el-option>
                </el-select>
              </el-form-item>
            </template>

            <template v-else-if="createStepIndex === 1">
              <el-form-item label="目标范围">
                <el-input v-model="taskForm.target_scope_summary" placeholder="例如：观察池 + 自选股 / 全市场 · 排除 ST" />
              </el-form-item>
              <el-form-item label="任务说明">
                <el-input
                  v-model="taskForm.notes"
                  type="textarea"
                  :rows="4"
                  placeholder="说明这个任务在链路中的角色，例如入池前筛选、盘中确认、历史回放。"
                />
              </el-form-item>
            </template>

            <template v-else-if="createStepIndex === 2">
              <el-form-item label="调度方式">
                <el-input v-model="taskForm.schedule_label" placeholder="例如：交易时段每 1 分钟轮询" />
              </el-form-item>
              <div class="schedule-hints">
                <article class="hint-card">
                  <span>建议节奏</span>
                  <strong>{{ defaultSchedule(taskForm.scene_type) }}</strong>
                </article>
                <article class="hint-card">
                  <span>目标范围模板</span>
                  <strong>{{ defaultScope(taskForm.scene_type) }}</strong>
                </article>
              </div>
            </template>

            <template v-else-if="createStepIndex === 3">
              <el-checkbox-group v-model="taskForm.actions" class="action-grid">
                <el-checkbox v-for="item in actionOptions" :key="item.value" :label="item.value">
                  <div class="action-option">
                    <strong>{{ item.label }}</strong>
                    <small>{{ item.description }}</small>
                  </div>
                </el-checkbox>
              </el-checkbox-group>
            </template>

            <template v-else>
              <div class="review-sheet">
                <article class="review-row">
                  <span>任务名称</span>
                  <strong>{{ taskForm.name || '未填写' }}</strong>
                </article>
                <article class="review-row">
                  <span>场景 / 策略</span>
                  <strong>{{ sceneLabels[taskForm.scene_type] }} · {{ selectedFormStrategy?.name || '未选择策略' }}</strong>
                </article>
                <article class="review-row">
                  <span>目标范围</span>
                  <strong>{{ taskForm.target_scope_summary || '未填写目标范围' }}</strong>
                </article>
                <article class="review-row">
                  <span>调度方式</span>
                  <strong>{{ taskForm.schedule_label || '未填写调度方式' }}</strong>
                </article>
                <article class="review-row">
                  <span>动作链</span>
                  <strong>{{ reviewActionSummary }}</strong>
                </article>
              </div>
            </template>
          </el-form>
        </section>

        <section class="action-panel">
          <div class="panel-block compact">
            <span class="panel-kicker">创建向导</span>
            <h3>{{ currentCreateStep.title }}</h3>
            <p>{{ currentCreateStep.description }}</p>
          </div>

          <div class="wizard-side-list">
            <article class="wizard-side-card">
              <span>当前场景</span>
              <strong>{{ sceneLabels[taskForm.scene_type] }}</strong>
              <p>{{ sceneDetail(taskForm.scene_type) }}</p>
            </article>
            <article class="wizard-side-card">
              <span>当前策略</span>
              <strong>{{ selectedFormStrategy?.name || '未选择策略' }}</strong>
              <p>{{ selectedFormStrategy?.description || '先选择策略，再决定怎么挂到任务里。' }}</p>
            </article>
            <article class="wizard-side-card">
              <span>当前动作</span>
              <strong>{{ reviewActionSummary }}</strong>
              <p>动作不属于策略，而属于场景任务，后续真实接口也会沿用这层拆分。</p>
            </article>
          </div>
        </section>
      </div>

      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button v-if="createStepIndex > 0" @click="prevCreateStep">上一步</el-button>
        <el-button v-if="createStepIndex < createStepItems.length - 1" type="primary" @click="nextCreateStep">下一步</el-button>
        <el-button v-else type="primary" :loading="submitting" @click="submitCreateTask">{{ dialogSubmitLabel }}</el-button>
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
  updateStrategySceneTask,
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
const selectedTaskId = ref('')
const createDialogVisible = ref(false)
const createStepIndex = ref(0)
const dialogMode = ref<'create' | 'edit'>('create')
const editingTaskId = ref('')
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

const createStepItems = [
  { title: '选择策略', description: '先定任务名、场景和策略。' },
  { title: '定义范围', description: '明确扫描或监听的目标范围。' },
  { title: '配置调度', description: '决定这个任务以什么节奏运行。' },
  { title: '配置动作', description: '信号触发后到底做什么。' },
  { title: '确认摘要', description: '最后检查整条任务链路。' },
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

const selectedTask = computed(() => {
  return filteredTasks.value.find((item) => item.task_id === selectedTaskId.value)
    || filteredTasks.value[0]
    || null
})

const activeTaskCount = computed(() => tasks.value.filter((item) => item.status === 'active').length)
const recentRunCount = computed(() => tasks.value.filter((item) => !!item.last_run_id).length)
const priorityActionCount = computed(() => tasks.value.reduce((sum, item) => sum + item.actions.length, 0))
const avgActionCount = computed(() => {
  if (filteredTasks.value.length === 0) return '0'
  return (filteredTasks.value.reduce((sum, item) => sum + item.actions.length, 0) / filteredTasks.value.length).toFixed(1)
})
const currentCreateStep = computed(() => createStepItems[createStepIndex.value])
const dialogTitle = computed(() => (dialogMode.value === 'edit' ? '编辑 V2 场景任务' : '新建 V2 场景任务'))
const dialogSubmitLabel = computed(() => (dialogMode.value === 'edit' ? '保存修改' : '创建任务'))
const selectedFormStrategy = computed(() => {
  return strategyOptions.value.find((item) => item.strategy_key === taskForm.strategy_key) || null
})
const reviewActionSummary = computed(() => {
  if (taskForm.actions.length === 0) return '未选择动作'
  return taskForm.actions.map((item) => STRATEGY_ACTION_LABELS[item]).join(' / ')
})
const sceneSuggestion = computed(() => {
  if (activeScene.value === 'listen') return '优先整理异常触发和冷却逻辑'
  if (activeScene.value === 'scan') return '把候选先送池，再做人工确认'
  if (activeScene.value === 'backtest') return '先看结果写入交割单链路是否通'
  return '重点看持仓变化和动作记录'
})

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

watch(filteredTasks, (value) => {
  if (!value.length) {
    selectedTaskId.value = ''
    return
  }
  if (!value.find((item) => item.task_id === selectedTaskId.value)) {
    selectedTaskId.value = value[0].task_id
  }
}, { immediate: true })

async function refreshPage(): Promise<void> {
  tasks.value = await listStrategySceneTasks()
  strategyOptions.value = await listStrategyDefinitions()
  overview.value = await getStrategyV2Overview()
}

function hydrateFromQuery(): void {
  const scene = String(route.query.scene || '').trim() as StrategySceneType
  const strategy = String(route.query.strategy || '').trim()
  const autoCreate = String(route.query.autoCreate || '') === '1'
  const editTaskId = String(route.query.editTask || '').trim()

  if (scene && ['scan', 'listen', 'backtest', 'sim_trade'].includes(scene)) {
    activeScene.value = scene
    taskForm.scene_type = scene
  }
  if (strategy) {
    taskForm.strategy_key = strategy
  }
  if (autoCreate) {
    openCreateDialog({ scene, strategy })
    router.replace({ name: 'StrategyTaskCenterV2', query: { scene, strategy } })
    return
  }
  if (editTaskId) {
    openEditDialog(editTaskId)
    router.replace({ name: 'StrategyTaskCenterV2', query: { scene } })
  }
}

function openCreateDialog(preset?: { scene?: string; strategy?: string }): void {
  dialogMode.value = 'create'
  editingTaskId.value = ''
  taskForm.name = ''
  taskForm.scene_type = (preset?.scene as StrategySceneType) || activeScene.value
  taskForm.strategy_key = preset?.strategy || taskForm.strategy_key || strategyOptions.value[0]?.strategy_key || ''
  taskForm.target_scope_summary = defaultScope(taskForm.scene_type)
  taskForm.schedule_label = defaultSchedule(taskForm.scene_type)
  taskForm.notes = ''
  taskForm.actions = defaultActions(taskForm.scene_type)
  createStepIndex.value = 0
  createDialogVisible.value = true
}

function openEditDialog(taskId: string): void {
  const task = tasks.value.find((item) => item.task_id === taskId)
  if (!task) {
    ElMessage.warning('任务不存在')
    return
  }
  dialogMode.value = 'edit'
  editingTaskId.value = task.task_id
  taskForm.name = task.name
  taskForm.scene_type = task.scene_type
  taskForm.strategy_key = task.strategy_key
  taskForm.target_scope_summary = task.target_scope_summary
  taskForm.schedule_label = task.schedule_label
  taskForm.notes = task.notes || ''
  taskForm.actions = task.actions.map((item) => item.action_type)
  createStepIndex.value = 0
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

function validateCreateStep(stepIndex = createStepIndex.value): boolean {
  if (stepIndex === 0) {
    if (!taskForm.name.trim()) {
      ElMessage.warning('请先填写任务名称')
      return false
    }
    if (!taskForm.strategy_key) {
      ElMessage.warning('请先选择策略')
      return false
    }
  }
  if (stepIndex === 1 && !taskForm.target_scope_summary.trim()) {
    ElMessage.warning('请填写目标范围')
    return false
  }
  if (stepIndex === 2 && !taskForm.schedule_label.trim()) {
    ElMessage.warning('请填写调度方式')
    return false
  }
  if (stepIndex === 3 && taskForm.actions.length === 0) {
    ElMessage.warning('请至少选择一个动作')
    return false
  }
  return true
}

function nextCreateStep(): void {
  if (!validateCreateStep()) return
  createStepIndex.value = Math.min(createStepIndex.value + 1, createStepItems.length - 1)
}

function prevCreateStep(): void {
  createStepIndex.value = Math.max(createStepIndex.value - 1, 0)
}

function jumpToCreateStep(index: number): void {
  if (index <= createStepIndex.value) {
    createStepIndex.value = index
    return
  }
  for (let step = createStepIndex.value; step < index; step += 1) {
    if (!validateCreateStep(step)) return
  }
  createStepIndex.value = index
}

async function submitCreateTask(): Promise<void> {
  if (!validateCreateStep(0) || !validateCreateStep(1) || !validateCreateStep(2) || !validateCreateStep(3)) {
    return
  }
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
    const payload = {
      ...taskForm,
      name: taskForm.name.trim(),
      target_scope_summary: taskForm.target_scope_summary.trim(),
      schedule_label: taskForm.schedule_label.trim(),
      notes: taskForm.notes?.trim(),
      actions: [...taskForm.actions],
    }
    const task =
      dialogMode.value === 'edit' && editingTaskId.value
        ? await updateStrategySceneTask(editingTaskId.value, payload)
        : await createStrategySceneTask(payload)

    if (!task) {
      ElMessage.error(dialogMode.value === 'edit' ? '任务更新失败' : '任务创建失败')
      return
    }

    await refreshPage()
    activeScene.value = task.scene_type
    selectedTaskId.value = task.task_id
    createDialogVisible.value = false
    ElMessage.success(dialogMode.value === 'edit' ? 'V2 任务已更新' : 'V2 任务已创建')
    router.push({ name: 'StrategyTaskDetailV2', params: { taskId: task.task_id } })
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

async function toggleTaskStatus(task: StrategySceneTask): Promise<void> {
  const nextStatus: StrategyTaskStatus = task.status === 'active' ? 'paused' : 'active'
  await updateStrategySceneTaskStatus(task.task_id, nextStatus)
  await refreshPage()
  selectedTaskId.value = task.task_id
  ElMessage.success(`任务已${nextStatus === 'active' ? '启用' : '暂停'}`)
}

function goDetail(taskId: string): void {
  router.push({ name: 'StrategyTaskDetailV2', params: { taskId } })
}

function statusActionLabel(status: StrategyTaskStatus): string {
  if (status === 'active') return '暂停'
  if (status === 'paused') return '启用'
  if (status === 'draft') return '激活'
  return '恢复'
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

function taskCountByScene(scene: StrategySceneType): number {
  return tasks.value.filter((item) => item.scene_type === scene).length
}

function sceneHint(scene: StrategySceneType): string {
  if (scene === 'listen') return '盘中轮询与动作联动'
  if (scene === 'scan') return '候选扫描与入池'
  if (scene === 'backtest') return '历史回放与验证'
  return '持续更新持仓结果'
}

function sceneDetail(scene: StrategySceneType): string {
  if (scene === 'listen') return '监听任务最接近日常盘中操作，应优先体现频率、动作和最近异常。'
  if (scene === 'scan') return '选股任务更像候选生成器，重点不是立即买，而是先形成可流转的观察对象。'
  if (scene === 'backtest') return '回测任务需要强调区间、交易配置与交割单结果的闭环，而不是只看配置。'
  return '模拟交易任务更像持仓演进记录台，重点看每日变化、风险提醒和动作留痕。'
}
</script>

<style scoped>
.task-center-page {
  --surface-1: linear-gradient(180deg, rgba(252, 253, 255, 0.98), rgba(246, 248, 252, 0.95));
  --surface-2: rgba(255, 255, 255, 0.78);
  --line-strong: rgba(42, 82, 190, 0.22);
  --line-soft: rgba(15, 23, 42, 0.08);
  --accent: #2f5fd0;
  --ink-soft: #5b6473;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.hero-card,
.stat-card,
.scene-rail,
.board-panel,
.inspector-panel,
.panel-block,
.task-row {
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
.panel-kicker,
.rail-kicker {
  margin: 0 0 10px;
  font-size: 11px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: #6274b7;
}

.hero-card h1,
.board-toolbar h2,
.rail-head h2 {
  margin: 0;
  font-size: 34px;
}

.description,
.panel-block p,
.principle-card p,
.action-option small,
.strategy-option small {
  line-height: 1.7;
  color: var(--ink-soft);
}

.hero-actions {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.top-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.stat-card {
  border-radius: 22px;
  padding: 16px 18px;
}

.stat-card span {
  display: block;
  color: var(--ink-soft);
}

.stat-card strong {
  display: block;
  margin-top: 8px;
  font-size: 28px;
}

.workspace-shell {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr) 320px;
  gap: 18px;
  align-items: start;
}

.scene-rail,
.board-panel,
.inspector-panel {
  border-radius: 28px;
  padding: 18px;
}

.scene-rail {
  position: sticky;
  top: 84px;
}

.scene-rail,
.inspector-panel {
  display: grid;
  gap: 12px;
}

.scene-button {
  width: 100%;
  padding: 14px;
  border-radius: 18px;
  border: 1px solid var(--line-soft);
  background: rgba(255, 255, 255, 0.72);
  display: flex;
  justify-content: space-between;
  gap: 10px;
  text-align: left;
}

.scene-button strong,
.task-title-line strong,
.inspector-head h3 {
  display: block;
}

.scene-button small,
.task-sub-line,
.meta-stack,
.inspector-notes,
.principle-card p {
  color: var(--ink-soft);
}

.scene-button.active {
  border-color: var(--line-strong);
  background: linear-gradient(180deg, rgba(47, 95, 208, 0.08), rgba(255, 255, 255, 0.88));
}

.scene-button span:last-child {
  min-width: 36px;
  height: 36px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: rgba(47, 95, 208, 0.12);
  color: var(--accent);
  font-weight: 700;
}

.board-toolbar,
.task-title-line,
.task-row,
.inspector-head {
  display: flex;
  justify-content: space-between;
  gap: 14px;
}

.board-toolbar {
  align-items: end;
}

.toolbar-actions {
  display: grid;
  grid-template-columns: 280px auto;
  gap: 10px;
}

.board-strip {
  margin-top: 18px;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.strip-chip {
  padding: 12px 14px;
  border-radius: 16px;
  background: rgba(47, 95, 208, 0.08);
}

.strip-chip.muted {
  background: rgba(15, 23, 42, 0.05);
}

.strip-chip span,
.metric-block span,
.inspector-meta span {
  display: block;
  color: var(--ink-soft);
  font-size: 12px;
}

.strip-chip strong,
.metric-block strong {
  display: block;
  margin-top: 6px;
  font-size: 22px;
}

.task-list {
  display: grid;
  gap: 12px;
  margin-top: 18px;
}

.task-row {
  width: 100%;
  padding: 16px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.76);
  text-align: left;
  align-items: center;
}

.task-row.active {
  border-color: var(--line-strong);
  background: linear-gradient(180deg, rgba(47, 95, 208, 0.08), rgba(255, 255, 255, 0.88));
}

.task-row-main {
  min-width: 0;
  display: grid;
  gap: 10px;
}

.task-title-line {
  align-items: center;
}

.task-sub-line {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.task-action-line,
.quick-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.action-chip {
  padding: 5px 10px;
  border-radius: 999px;
  background: rgba(47, 95, 208, 0.1);
  color: var(--accent);
  font-size: 12px;
}

.task-row-side {
  min-width: 260px;
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr) auto;
  gap: 14px;
  align-items: center;
}

.metric-block {
  padding: 10px;
  border-radius: 14px;
  background: rgba(47, 95, 208, 0.08);
  text-align: center;
}

.meta-stack {
  display: grid;
  gap: 6px;
  font-size: 12px;
}

.row-actions {
  display: flex;
  gap: 8px;
}

.panel-block {
  border-radius: 22px;
  padding: 16px;
  background: rgba(255, 255, 255, 0.76);
}

.panel-block.emphasis {
  background: linear-gradient(180deg, rgba(47, 95, 208, 0.08), rgba(255, 255, 255, 0.82));
}

.panel-block.compact h3,
.inspector-head h3 {
  margin: 0;
  font-size: 20px;
}

.inspector-meta {
  display: grid;
  gap: 10px;
  margin-top: 14px;
}

.inspector-meta strong {
  display: block;
  margin-top: 4px;
}

.inspector-notes {
  margin: 14px 0;
}

.principle-list {
  display: grid;
  gap: 10px;
}

.principle-card {
  padding: 12px 0 0;
  border-top: 1px solid var(--line-soft);
}

.principle-card:first-child {
  border-top: none;
  padding-top: 0;
}

.dialog-shell {
  display: grid;
  grid-template-columns: 1.05fr 0.95fr;
  gap: 20px;
}

.wizard-steps {
  display: grid;
  gap: 10px;
  margin-bottom: 18px;
}

.wizard-step {
  width: 100%;
  padding: 12px 14px;
  border-radius: 18px;
  border: 1px solid var(--line-soft);
  background: rgba(255, 255, 255, 0.74);
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  gap: 12px;
  text-align: left;
}

.wizard-step.active {
  border-color: var(--line-strong);
  background: linear-gradient(180deg, rgba(47, 95, 208, 0.08), rgba(255, 255, 255, 0.86));
}

.wizard-step.done span {
  background: rgba(22, 163, 74, 0.14);
  color: #18884b;
}

.wizard-step span {
  width: 34px;
  height: 34px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: rgba(47, 95, 208, 0.12);
  color: var(--accent);
  font-weight: 700;
}

.wizard-step strong {
  display: block;
}

.wizard-step small,
.wizard-side-card p,
.review-row span {
  color: var(--ink-soft);
}

.action-panel {
  border-radius: 22px;
  border: 1px solid var(--line-soft);
  background: rgba(255, 255, 255, 0.72);
  padding: 18px;
}

.schedule-hints,
.wizard-side-list,
.review-sheet {
  display: grid;
  gap: 12px;
}

.hint-card,
.wizard-side-card,
.review-row {
  border-radius: 18px;
  border: 1px solid var(--line-soft);
  background: rgba(255, 255, 255, 0.76);
  padding: 14px;
}

.hint-card span,
.wizard-side-card span,
.review-row span {
  display: block;
  font-size: 12px;
}

.hint-card strong,
.wizard-side-card strong,
.review-row strong {
  display: block;
  margin-top: 6px;
}

.wizard-side-card p {
  margin: 8px 0 0;
  line-height: 1.7;
}

.action-grid {
  display: grid;
  gap: 14px;
  margin-top: 16px;
}

.action-option {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

@media (max-width: 1280px) {
  .workspace-shell,
  .top-stats,
  .board-strip,
  .dialog-shell {
    grid-template-columns: 1fr;
  }

  .hero-card,
  .board-toolbar,
  .task-row,
  .task-row-side {
    flex-direction: column;
  }

  .toolbar-actions {
    grid-template-columns: 1fr;
    width: 100%;
  }

  .scene-rail {
    position: static;
  }
}
</style>
