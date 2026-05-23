<template>
  <div class="strategy-center-page">
    <section class="page-toolbar">
      <div class="toolbar-filters">
        <el-input v-model="keyword" clearable placeholder="搜索策略名 / 描述" class="toolbar-search" />
        <el-select v-model="sceneFilter" class="toolbar-select">
          <el-option label="全部场景" value="all" />
          <el-option v-for="scene in sceneOptions" :key="scene.value" :label="scene.label" :value="scene.value" />
        </el-select>
        <span class="toolbar-count">共 {{ filteredStrategies.length }} 条</span>
      </div>
      <el-button type="primary" size="small" @click="openCreateDialog">创建策略</el-button>
    </section>

    <section class="page-body">
      <el-table :data="filteredStrategies" row-key="strategy_key" stripe size="small" class="strategy-table" empty-text="暂时还没有策略">
        <el-table-column label="策略名" min-width="220">
          <template #default="{ row }">
            <div class="strategy-name-cell">
              <strong>{{ row.name }}</strong>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="策略描述" min-width="420">
          <template #default="{ row }">
            <div class="strategy-description-cell">
              {{ row.description }}
            </div>
          </template>
        </el-table-column>

        <el-table-column label="跨日记忆" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="row.supports_state ? 'success' : 'info'" effect="plain" round>
              {{ row.supports_state ? '是' : '否' }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="应用场景" width="180" align="center">
          <template #default="{ row }">
            <div class="scene-button-list">
              <el-tooltip
                v-for="scene in row.supported_scenes"
                :key="scene"
                :content="sceneLabel(scene)"
                placement="top"
              >
                <button type="button" class="scene-mini-button" @click="openViewDialog(row.strategy_key)">
                  {{ sceneShortLabel(scene) }}
                </button>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="140" align="right">
          <template #default="{ row }">
            <el-dropdown trigger="click" @command="(command) => handleCommand(command, row.strategy_key)">
              <el-button size="small">
                操作
                <el-icon class="el-icon--right"><ArrowDown /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="view">查看</el-dropdown-item>
                  <el-dropdown-item command="edit">编辑</el-dropdown-item>
                  <el-dropdown-item command="delete">删除</el-dropdown-item>
                  <el-dropdown-item command="tasks">查看在运行任务</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="formDialogVisible" :title="formDialogMode === 'create' ? '创建策略' : '编辑策略'" width="640px">
      <el-form label-position="top">
        <el-form-item label="策略名">
          <el-input v-model="formState.name" placeholder="请输入策略名" />
        </el-form-item>

        <el-form-item label="策略描述">
          <el-input v-model="formState.description" type="textarea" :rows="4" placeholder="请输入策略描述" />
        </el-form-item>

        <el-form-item label="是否跨日记忆">
          <el-switch v-model="formState.supports_state" />
        </el-form-item>

        <el-form-item label="应用场景">
          <el-checkbox-group v-model="formState.supported_scenes">
            <el-checkbox v-for="scene in sceneOptions" :key="scene.value" :label="scene.value">
              {{ scene.label }}
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
      </el-form>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="formDialogVisible = false">取消</el-button>
          <el-button type="primary" @click="submitFormDialog">
            {{ formDialogMode === 'create' ? '创建' : '保存' }}
          </el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog v-model="viewDialogVisible" :title="selectedStrategy?.name || '查看策略'" width="760px" class="strategy-view-dialog">
      <template v-if="selectedStrategy">
        <div class="strategy-dialog-shell">
          <el-tabs v-model="viewActiveTab" class="strategy-detail-tabs">
            <el-tab-pane label="主要信息" name="overview">
              <section class="tab-section">
                <div class="tab-section-head">
                  <div>
                    <strong>策略信息</strong>
                  </div>
                  <button type="button" class="tab-action-button" @click="openEditDialog(selectedStrategy.strategy_key)">
                    编辑主要信息
                  </button>
                </div>

                <div class="overview-grid">
                  <div class="detail-block span-2">
                    <span>策略名称</span>
                    <p>{{ selectedStrategy.name }}</p>
                  </div>
                  <div class="detail-block span-2">
                    <span>策略描述</span>
                    <p>{{ selectedStrategy.description }}</p>
                  </div>
                  <div class="detail-block detail-pair-block">
                    <div class="detail-pair-row">
                      <span>跨日记忆</span>
                      <strong>{{ selectedStrategy.supports_state ? '支持' : '不支持' }}</strong>
                    </div>
                    <div class="detail-pair-row">
                      <span>当前版本</span>
                      <strong>v{{ selectedStrategy.version }}</strong>
                    </div>
                  </div>
                  <div class="detail-block detail-pair-block">
                    <div class="detail-pair-row">
                      <span>策略类型</span>
                      <strong>{{ strategyTypeLabel(selectedStrategy.impl_type) }}</strong>
                    </div>
                    <div class="detail-pair-row">
                      <span>内部标识</span>
                      <strong>{{ selectedStrategy.strategy_key }}</strong>
                    </div>
                  </div>
                  <div class="detail-block span-2">
                    <span>应用场景</span>
                    <div class="info-tab-list">
                      <span v-for="scene in selectedStrategy.supported_scenes" :key="scene" class="info-tab-item">
                        {{ sceneLabelMap[scene] }}
                      </span>
                    </div>
                  </div>
                  <div class="detail-block span-2" v-if="selectedStrategy.tags.length > 0">
                    <span>标签</span>
                    <div class="info-tab-list">
                      <span v-for="tag in selectedStrategy.tags" :key="tag" class="info-tab-item info-tab-item-muted">
                        {{ tag }}
                      </span>
                    </div>
                  </div>
                </div>
              </section>
            </el-tab-pane>

            <el-tab-pane label="参数信息" name="params">
              <section class="tab-section">
                <div class="tab-section-head">
                  <div>
                    <strong>参数信息</strong>
                  </div>
                  <button type="button" class="tab-action-button" @click="saveViewStrategy">
                    保存参数信息
                  </button>
                </div>

                <el-table v-if="selectedStrategy.param_schema.length > 0" :data="selectedStrategy.param_schema" size="small" stripe class="param-table">
                  <el-table-column label="参数" min-width="180">
                    <template #default="{ row }">
                      <div class="param-name-cell">
                        <strong>{{ row.label }}</strong>
                        <small>{{ row.key }}</small>
                      </div>
                    </template>
                  </el-table-column>
                  <el-table-column label="类型" width="100">
                    <template #default="{ row }">
                      {{ paramTypeLabel(row.type) }}
                    </template>
                  </el-table-column>
                  <el-table-column prop="description" label="说明" min-width="220" show-overflow-tooltip />
                  <el-table-column label="默认值" width="240">
                    <template #default="{ row }">
                      <el-select
                        v-if="row.type === 'select' && row.options"
                        :model-value="String(row.default)"
                        style="width: 100%"
                        @update:model-value="(value) => updateViewParamDefault(row.key, value)"
                      >
                        <el-option
                          v-for="option in row.options"
                          :key="String(option.value)"
                          :label="option.label"
                          :value="option.value"
                        />
                      </el-select>
                      <el-switch
                        v-else-if="row.type === 'boolean'"
                        :model-value="Boolean(row.default)"
                        @update:model-value="(value) => updateViewParamDefault(row.key, value)"
                      />
                      <el-input
                        v-else
                        :model-value="String(row.default)"
                        @update:model-value="(value) => updateViewParamDefault(row.key, castParamValue(row.type, value))"
                      />
                    </template>
                  </el-table-column>
                </el-table>
                <el-empty v-else description="当前没有参数信息" :image-size="72" />
              </section>
            </el-tab-pane>

            <el-tab-pane label="相关任务" name="tasks">
              <section class="tab-section">
                <div class="tab-section-head">
                  <div>
                    <strong>相关任务列表</strong>
                  </div>
                  <button type="button" class="tab-action-button" @click="createRelatedTask">
                    创建任务
                  </button>
                </div>

                <el-table v-if="selectedRelatedTasks.length > 0" :data="selectedRelatedTasks" size="small" stripe class="related-task-table">
                  <el-table-column prop="name" label="任务名" min-width="180" />
                  <el-table-column label="场景" width="100">
                    <template #default="{ row }">
                      {{ sceneLabel(row.scene_type) }}
                    </template>
                  </el-table-column>
                  <el-table-column prop="target_scope_summary" label="范围" min-width="220" show-overflow-tooltip />
                  <el-table-column label="状态" width="100">
                    <template #default="{ row }">
                      <el-tag size="small" effect="plain" round>{{ taskStatusLabel(row.status) }}</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column prop="schedule_label" label="调度" min-width="180" show-overflow-tooltip />
                  <el-table-column prop="last_signal_count" label="最近信号" width="90" align="center" />
                  <el-table-column label="操作" width="90" align="right">
                    <template #default="{ row }">
                      <el-button size="small" plain @click="openRelatedTask(row.task_id)">查看</el-button>
                    </template>
                  </el-table-column>
                </el-table>
                <el-empty v-else description="当前没有关联任务" :image-size="72" />
              </section>
            </el-tab-pane>
          </el-tabs>
        </div>
      </template>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="viewDialogVisible = false">关闭</el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="taskDialogVisible"
      title="创建任务"
      append-to-body
      width="720px"
      class="task-create-dialog"
      :close-on-click-modal="false"
    >
      <div class="task-dialog-shell">
        <el-steps :active="taskStepIndex" finish-status="success" align-center class="task-steps">
          <el-step
            v-for="step in taskStepItems"
            :key="step.title"
            :title="step.title"
            :description="step.description"
          />
        </el-steps>

        <section class="task-step-card">
          <div class="task-step-head">
            <strong>{{ currentTaskStep.title }}</strong>
            <p>{{ currentTaskStep.description }}</p>
          </div>

          <el-form label-position="top">
            <template v-if="taskStepIndex === 0">
              <el-form-item label="策略">
                <el-input :model-value="selectedStrategy?.name || ''" disabled />
              </el-form-item>
              <el-form-item label="任务名称">
                <el-input v-model="taskForm.name" placeholder="例如：5日线低吸候选入池" />
              </el-form-item>
              <el-form-item label="场景类型">
                <el-select v-model="taskForm.scene_type" style="width: 100%">
                  <el-option v-for="scene in taskSceneOptions" :key="scene.value" :label="scene.label" :value="scene.value" />
                </el-select>
              </el-form-item>
            </template>

            <template v-else-if="taskStepIndex === 1">
              <el-form-item label="目标范围">
                <el-select v-model="taskForm.target_scope_summary" style="width: 100%">
                  <el-option
                    v-for="option in taskScopeOptions"
                    :key="option.value"
                    :label="option.label"
                    :value="option.value"
                  >
                    <div class="task-option-line">
                      <span>{{ option.label }}</span>
                      <small>{{ option.description }}</small>
                    </div>
                  </el-option>
                </el-select>
              </el-form-item>
              <el-form-item label="任务说明">
                <el-input
                  v-model="taskForm.notes"
                  type="textarea"
                  :rows="4"
                  placeholder="说明这个任务在链路中的职责，例如盘中监听、候选入池、历史回放。"
                />
              </el-form-item>
            </template>

            <template v-else-if="taskStepIndex === 2">
              <el-form-item label="调度方式">
                <el-select v-model="taskForm.schedule_label" style="width: 100%">
                  <el-option
                    v-for="option in taskScheduleOptions"
                    :key="option.value"
                    :label="option.label"
                    :value="option.value"
                  >
                    <div class="task-option-line">
                      <span>{{ option.label }}</span>
                      <small>{{ option.description }}</small>
                    </div>
                  </el-option>
                </el-select>
              </el-form-item>
              <el-form-item label="动作">
                <el-checkbox-group v-model="taskForm.actions" class="task-action-grid">
                  <el-checkbox v-for="item in taskActionOptions" :key="item.value" :label="item.value">
                    <div class="task-action-option">
                      <strong>{{ item.label }}</strong>
                      <small>{{ item.description }}</small>
                    </div>
                  </el-checkbox>
                </el-checkbox-group>
              </el-form-item>
            </template>

            <template v-else>
              <div class="task-review-list">
                <article class="task-review-row">
                  <span>策略</span>
                  <strong>{{ selectedStrategy?.name || '-' }}</strong>
                </article>
                <article class="task-review-row">
                  <span>任务名称</span>
                  <strong>{{ taskForm.name || '未填写' }}</strong>
                </article>
                <article class="task-review-row">
                  <span>场景类型</span>
                  <strong>{{ sceneLabel(taskForm.scene_type) }}</strong>
                </article>
                <article class="task-review-row">
                  <span>目标范围</span>
                  <strong>{{ taskForm.target_scope_summary || '未选择' }}</strong>
                </article>
                <article class="task-review-row">
                  <span>调度方式</span>
                  <strong>{{ taskForm.schedule_label || '未选择' }}</strong>
                </article>
                <article class="task-review-row">
                  <span>动作</span>
                  <strong>{{ taskActionSummary }}</strong>
                </article>
              </div>
            </template>
          </el-form>
        </section>
      </div>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="taskDialogVisible = false">取消</el-button>
          <el-button v-if="taskStepIndex > 0" @click="prevTaskStep">上一步</el-button>
          <el-button v-if="taskStepIndex < taskStepItems.length - 1" type="primary" @click="nextTaskStep">下一步</el-button>
          <el-button v-else type="primary" :loading="taskSubmitting" @click="submitTaskDialog">创建任务</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowDown } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  createStrategySceneTask,
  STRATEGY_ACTION_LABELS,
  STRATEGY_SCENE_LABELS,
  STRATEGY_TASK_STATUS_LABELS,
  listStrategyDefinitions,
  listStrategySceneTasks,
} from '@/mocks/strategyV2'
import type {
  CreateStrategySceneTaskInput,
  StrategyActionType,
  StrategyDefinition,
  StrategySceneTask,
  StrategySceneType,
} from '@/types/strategy-v2'

const router = useRouter()

const sceneLabelMap = STRATEGY_SCENE_LABELS
const taskStatusLabelMap = STRATEGY_TASK_STATUS_LABELS
const sceneShortLabelMap: Record<StrategySceneType, string> = {
  scan: '选',
  listen: '监',
  backtest: '回',
  sim_trade: '模',
}

const sceneOptions = [
  { label: STRATEGY_SCENE_LABELS.scan, value: 'scan' as const },
  { label: STRATEGY_SCENE_LABELS.listen, value: 'listen' as const },
  { label: STRATEGY_SCENE_LABELS.backtest, value: 'backtest' as const },
  { label: STRATEGY_SCENE_LABELS.sim_trade, value: 'sim_trade' as const },
]

const strategies = ref<StrategyDefinition[]>([])
const tasks = ref<StrategySceneTask[]>([])
const selectedStrategy = ref<StrategyDefinition | null>(null)
const keyword = ref('')
const sceneFilter = ref<'all' | StrategySceneType>('all')
const formDialogVisible = ref(false)
const viewDialogVisible = ref(false)
const taskDialogVisible = ref(false)
const formDialogMode = ref<'create' | 'edit'>('create')
const editingStrategyKey = ref('')
const viewActiveTab = ref<'overview' | 'params' | 'tasks'>('overview')
const taskStepIndex = ref(0)
const taskSubmitting = ref(false)

const formState = reactive<{
  name: string
  description: string
  supports_state: boolean
  supported_scenes: StrategySceneType[]
}>({
  name: '',
  description: '',
  supports_state: false,
  supported_scenes: [],
})

const taskStepItems = [
  { title: '基础信息', description: '先确定任务名和使用场景。' },
  { title: '目标范围', description: '选择这个任务要处理的对象范围。' },
  { title: '调度动作', description: '选择运行节奏和触发后的动作。' },
  { title: '确认创建', description: '最后确认生成的数据。' },
]

const taskScopeOptionsByScene: Record<StrategySceneType, Array<{ label: string; value: string; description: string }>> = {
  scan: [
    { label: '全市场 · 排除 ST', value: '全市场 · 排除 ST · 最近 120 日有交易', description: '适合做日内候选扫描。' },
    { label: '候选池回看区间', value: '候选池 · 最近 20 个交易日回看', description: '适合训练时段筛选与复盘。' },
  ],
  listen: [
    { label: '观察池 + 自选股', value: '观察池 + 自选股 · 共 63 只', description: '盘中监听最常用范围。' },
    { label: '持仓组', value: '持仓组：实盘训练账户', description: '适合盈亏、止盈止损与持仓异动监听。' },
    { label: '指数与市场宽度', value: '指数组 + 市场涨跌家数', description: '适合指数和市场情绪监听。' },
  ],
  backtest: [
    { label: '训练样本 A', value: '交割单分组：训练样本 A · 2025Q4 - 2026Q1', description: '历史样本分组回放。' },
    { label: '候选模式回放', value: '候选池样本 · 最近 60 个交易日', description: '适合检验候选模式表现。' },
  ],
  sim_trade: [
    { label: '实盘训练账户', value: '持仓组：实盘训练账户', description: '按每日数据持续更新模拟持仓。' },
    { label: '模拟观察账户', value: '持仓组：模拟观察账户', description: '适合较轻量的策略跟踪。' },
  ],
}

const taskScheduleOptionsByScene: Record<StrategySceneType, Array<{ label: string; value: string; description: string }>> = {
  scan: [
    { label: '交易日分时扫描', value: '交易日 09:45 / 10:30 / 13:45', description: '兼顾上午与下午。' },
    { label: '收盘后补扫', value: '交易日 15:10 收盘后补扫', description: '适合盘后统一整理候选。' },
  ],
  listen: [
    { label: '每 1 分钟轮询', value: '交易时段每 1 分钟轮询', description: '适合高频异动与风控监听。' },
    { label: '每 5 分钟轮询', value: '交易时段每 5 分钟轮询', description: '适合低频市场情绪监听。' },
  ],
  backtest: [
    { label: '手动运行', value: '手动运行', description: '适合调参数后逐次验证。' },
    { label: '每日批量回放', value: '每日 20:30 批量回放', description: '适合夜间统一跑一批样本。' },
  ],
  sim_trade: [
    { label: '收盘后更新', value: '交易日收盘后自动更新', description: '适合每日准实盘更新。' },
    { label: '收盘后 + 异常补轮', value: '交易日收盘后 + 盘中异常补轮', description: '适合带异常提醒的模拟链路。' },
  ],
}

const taskActionOptionsByScene: Record<StrategySceneType, StrategyActionType[]> = {
  scan: ['add_to_pool', 'temp_list', 'notify', 'pool_transition'],
  listen: ['notify', 'pool_transition', 'add_to_pool', 'temp_list'],
  backtest: ['paper_trade', 'notify'],
  sim_trade: ['paper_trade', 'notify'],
}

const taskActionCatalog: Array<{ value: StrategyActionType; label: string; description: string }> = [
  { value: 'notify', label: STRATEGY_ACTION_LABELS.notify, description: '发送提醒，用于监听和风险提示。' },
  { value: 'add_to_pool', label: STRATEGY_ACTION_LABELS.add_to_pool, description: '把候选结果送进现有股池。' },
  { value: 'pool_transition', label: STRATEGY_ACTION_LABELS.pool_transition, description: '在多个股池之间自动流转。' },
  { value: 'temp_list', label: STRATEGY_ACTION_LABELS.temp_list, description: '保留临时结果供人工筛选。' },
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

onMounted(async () => {
  strategies.value = await listStrategyDefinitions()
  tasks.value = await listStrategySceneTasks()
})

const filteredStrategies = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  return strategies.value.filter((item) => {
    const matchesText = !text
      || item.name.toLowerCase().includes(text)
      || item.description.toLowerCase().includes(text)
    const matchesScene = sceneFilter.value === 'all' || item.supported_scenes.includes(sceneFilter.value)
    return matchesText && matchesScene
  })
})

const selectedRelatedTasks = computed(() => {
  if (!selectedStrategy.value) return []
  return tasks.value.filter((item) => item.strategy_key === selectedStrategy.value?.strategy_key)
})
const taskSceneOptions = computed(() => {
  if (!selectedStrategy.value) return []
  return sceneOptions.filter((item) => selectedStrategy.value?.supported_scenes.includes(item.value))
})
const currentTaskStep = computed(() => taskStepItems[taskStepIndex.value])
const taskScopeOptions = computed(() => taskScopeOptionsByScene[taskForm.scene_type])
const taskScheduleOptions = computed(() => taskScheduleOptionsByScene[taskForm.scene_type])
const taskActionOptions = computed(() => {
  const allowed = new Set(taskActionOptionsByScene[taskForm.scene_type])
  return taskActionCatalog.filter((item) => allowed.has(item.value))
})
const taskActionSummary = computed(() => {
  if (taskForm.actions.length === 0) return '未选择动作'
  return taskForm.actions.map((item) => STRATEGY_ACTION_LABELS[item]).join(' / ')
})

watch(() => taskForm.scene_type, (scene) => {
  normalizeTaskForm(scene)
})

function handleCommand(command: string, strategyKey: string): void {
  if (command === 'view') {
    openViewDialog(strategyKey)
    return
  }

  if (command === 'edit') {
    openEditDialog(strategyKey)
    return
  }

  if (command === 'tasks') {
    router.push({
      name: 'StrategyTaskCenterV2',
      query: {
        strategy: strategyKey,
      },
    })
    return
  }

  if (command === 'delete') {
    void deleteStrategy(strategyKey)
  }
}

function openCreateDialog(): void {
  formDialogMode.value = 'create'
  editingStrategyKey.value = ''
  resetForm()
  formDialogVisible.value = true
}

function openViewDialog(strategyKey: string): void {
  const strategy = findStrategy(strategyKey)
  if (!strategy) return
  selectedStrategy.value = cloneStrategy(strategy)
  viewActiveTab.value = 'overview'
  viewDialogVisible.value = true
}

function openEditDialog(strategyKey: string): void {
  const strategy = findStrategy(strategyKey)
  if (!strategy) return

  formDialogMode.value = 'edit'
  editingStrategyKey.value = strategyKey
  formState.name = strategy.name
  formState.description = strategy.description
  formState.supports_state = strategy.supports_state
  formState.supported_scenes = [...strategy.supported_scenes]
  formDialogVisible.value = true
  viewDialogVisible.value = false
}

function submitFormDialog(): void {
  if (!formState.name.trim()) {
    ElMessage.warning('请先填写策略名')
    return
  }

  if (!formState.description.trim()) {
    ElMessage.warning('请先填写策略描述')
    return
  }

  if (formState.supported_scenes.length === 0) {
    ElMessage.warning('请至少选择一个应用场景')
    return
  }

  if (formDialogMode.value === 'create') {
    const newStrategy: StrategyDefinition = {
      strategy_key: `custom_${Date.now()}`,
      name: formState.name.trim(),
      description: formState.description.trim(),
      impl_type: 'builtin_code',
      supported_scenes: [...formState.supported_scenes],
      supports_state: formState.supports_state,
      version: 1,
      tags: [],
      param_schema: [],
      sample_outputs: [],
    }
    strategies.value = [newStrategy, ...strategies.value]
    ElMessage.success('策略已创建')
  }
  else {
    strategies.value = strategies.value.map((item) => {
      if (item.strategy_key !== editingStrategyKey.value) return item
      return {
        ...item,
        name: formState.name.trim(),
        description: formState.description.trim(),
        supports_state: formState.supports_state,
        supported_scenes: [...formState.supported_scenes],
      }
    })
    ElMessage.success('策略已更新')
  }

  formDialogVisible.value = false
  resetForm()
}

async function deleteStrategy(strategyKey: string): Promise<void> {
  const strategy = findStrategy(strategyKey)
  if (!strategy) return

  try {
    await ElMessageBox.confirm(
      `确认删除策略“${strategy.name}”吗？当前仅做前端演示删除。`,
      '删除策略',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      },
    )

    strategies.value = strategies.value.filter((item) => item.strategy_key !== strategyKey)

    if (selectedStrategy.value?.strategy_key === strategyKey) {
      selectedStrategy.value = null
      viewDialogVisible.value = false
    }

    ElMessage.success('策略已删除')
  }
  catch {
    // User cancelled the confirmation dialog.
  }
}

function resetForm(): void {
  formState.name = ''
  formState.description = ''
  formState.supports_state = false
  formState.supported_scenes = []
}

function findStrategy(strategyKey: string): StrategyDefinition | undefined {
  return strategies.value.find((item) => item.strategy_key === strategyKey)
}

function cloneStrategy(strategy: StrategyDefinition): StrategyDefinition {
  return JSON.parse(JSON.stringify(strategy)) as StrategyDefinition
}

function sceneLabel(scene: StrategySceneType): string {
  return sceneLabelMap[scene]
}

function sceneShortLabel(scene: StrategySceneType): string {
  return sceneShortLabelMap[scene]
}

function paramTypeLabel(type: StrategyDefinition['param_schema'][number]['type']): string {
  if (type === 'number') return '整数'
  if (type === 'float') return '浮点'
  if (type === 'boolean') return '布尔'
  if (type === 'select') return '枚举'
  return '字符串'
}

function castParamValue(type: StrategyDefinition['param_schema'][number]['type'], value: string): string | number | boolean {
  if (type === 'number') return Number.parseInt(value || '0', 10)
  if (type === 'float') return Number.parseFloat(value || '0')
  return value
}

function updateViewParamDefault(key: string, value: string | number | boolean): void {
  if (!selectedStrategy.value) return
  selectedStrategy.value.param_schema = selectedStrategy.value.param_schema.map((item) => {
    if (item.key !== key) return item
    return {
      ...item,
      default: value,
    }
  })
}

function saveViewStrategy(): void {
  if (!selectedStrategy.value) return

  strategies.value = strategies.value.map((item) => {
    if (item.strategy_key !== selectedStrategy.value?.strategy_key) return item
    return cloneStrategy(selectedStrategy.value)
  })

  ElMessage.success('策略参数已保存')
}

function openRelatedTask(taskId: string): void {
  router.push({
    name: 'StrategyTaskDetailV2',
    params: { taskId },
  })
}

function createRelatedTask(): void {
  if (!selectedStrategy.value) return
  resetTaskForm()
  taskForm.strategy_key = selectedStrategy.value.strategy_key
  taskForm.scene_type = selectedStrategy.value.supported_scenes[0] || 'listen'
  normalizeTaskForm(taskForm.scene_type)
  taskDialogVisible.value = true
}

function resetTaskForm(): void {
  taskForm.name = ''
  taskForm.scene_type = 'listen'
  taskForm.strategy_key = ''
  taskForm.target_scope_summary = ''
  taskForm.schedule_label = ''
  taskForm.notes = ''
  taskForm.actions = ['notify']
  taskStepIndex.value = 0
}

function normalizeTaskForm(scene: StrategySceneType): void {
  const strategy = selectedStrategy.value
  if (!strategy) return

  taskForm.strategy_key = strategy.strategy_key

  if (!strategy.supported_scenes.includes(scene)) {
    taskForm.scene_type = strategy.supported_scenes[0] || 'listen'
  }

  const allowedScopes = taskScopeOptionsByScene[taskForm.scene_type].map((item) => item.value)
  if (!allowedScopes.includes(taskForm.target_scope_summary)) {
    taskForm.target_scope_summary = taskScopeOptionsByScene[taskForm.scene_type][0]?.value || ''
  }

  const allowedSchedules = taskScheduleOptionsByScene[taskForm.scene_type].map((item) => item.value)
  if (!allowedSchedules.includes(taskForm.schedule_label)) {
    taskForm.schedule_label = taskScheduleOptionsByScene[taskForm.scene_type][0]?.value || ''
  }

  const allowedActions = new Set(taskActionOptionsByScene[taskForm.scene_type])
  const nextActions = taskForm.actions.filter((item) => allowedActions.has(item))
  if (nextActions.length === 0) {
    taskForm.actions = defaultTaskActions(taskForm.scene_type)
  }
  else {
    taskForm.actions = nextActions
  }
}

function defaultTaskActions(scene: StrategySceneType): StrategyActionType[] {
  if (scene === 'scan') return ['add_to_pool', 'temp_list']
  if (scene === 'listen') return ['notify', 'pool_transition']
  return ['paper_trade']
}

function validateTaskStep(step = taskStepIndex.value): boolean {
  if (step === 0) {
    if (!taskForm.name.trim()) {
      ElMessage.warning('请先填写任务名称')
      return false
    }
  }
  if (step === 1 && !taskForm.target_scope_summary) {
    ElMessage.warning('请选择目标范围')
    return false
  }
  if (step === 2) {
    if (!taskForm.schedule_label) {
      ElMessage.warning('请选择调度方式')
      return false
    }
    if (taskForm.actions.length === 0) {
      ElMessage.warning('请至少选择一个动作')
      return false
    }
  }
  return true
}

function nextTaskStep(): void {
  if (!validateTaskStep()) return
  taskStepIndex.value = Math.min(taskStepIndex.value + 1, taskStepItems.length - 1)
}

function prevTaskStep(): void {
  taskStepIndex.value = Math.max(taskStepIndex.value - 1, 0)
}

async function submitTaskDialog(): Promise<void> {
  if (!selectedStrategy.value) return
  if (!validateTaskStep(0) || !validateTaskStep(1) || !validateTaskStep(2)) return

  taskSubmitting.value = true
  try {
    const task = await createStrategySceneTask({
      name: taskForm.name.trim(),
      scene_type: taskForm.scene_type,
      strategy_key: selectedStrategy.value.strategy_key,
      target_scope_summary: taskForm.target_scope_summary,
      schedule_label: taskForm.schedule_label,
      notes: taskForm.notes?.trim(),
      actions: [...taskForm.actions],
    })
    tasks.value = await listStrategySceneTasks()
    taskDialogVisible.value = false
    taskStepIndex.value = 0
    ElMessage.success(`任务“${task.name}”已创建`)
    viewActiveTab.value = 'tasks'
  }
  finally {
    taskSubmitting.value = false
  }
}

function strategyTypeLabel(type: StrategyDefinition['impl_type']): string {
  if (type === 'builtin_code') return '内置策略'
  return type
}

function taskStatusLabel(status: StrategySceneTask['status']): string {
  return taskStatusLabelMap[status]
}
</script>

<style scoped>
.strategy-center-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-toolbar,
.page-body {
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 8px;
  background: #fff;
}

.page-toolbar {
  padding: 12px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.page-body {
  padding: 4px 8px 8px;
}

.toolbar-filters {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.toolbar-search {
  width: 260px;
}

.toolbar-select {
  width: 144px;
}

.toolbar-count {
  font-size: 12px;
  color: #64748b;
  white-space: nowrap;
}

.strategy-table {
  width: 100%;
}

.strategy-table :deep(th.el-table__cell) {
  background: #f6f8fa;
  color: #475569;
  font-weight: 600;
}

.strategy-table :deep(td.el-table__cell) {
  padding-top: 8px;
  padding-bottom: 8px;
}

.strategy-name-cell strong {
  font-size: 14px;
  color: #0f172a;
  line-height: 1.4;
}

.strategy-description-cell {
  line-height: 1.6;
  color: #475569;
  white-space: normal;
}

.scene-button-list,
.full-scene-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  justify-content: flex-start;
}

.full-scene-list.align-start {
  justify-content: flex-start;
}

.info-tab-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.info-tab-item {
  display: inline-flex;
  align-items: center;
  height: 30px;
  padding: 0 12px;
  border: 1px solid #d8e1ea;
  border-bottom-color: #b8c6d8;
  border-radius: 8px 8px 0 0;
  background: #f8fbff;
  color: #1f3b63;
  font-size: 13px;
  line-height: 28px;
  white-space: nowrap;
}

.info-tab-item-muted {
  background: #f6f8fa;
  color: #475569;
}

.scene-mini-button {
  width: 26px;
  height: 26px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: #fff;
  color: #334155;
  cursor: pointer;
}

.scene-mini-button:hover {
  border-color: #409eff;
  color: #409eff;
  background: #f8fbff;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.strategy-dialog-shell {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.tab-section {
  padding-top: 4px;
}

.tab-section-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 10px;
}

.tab-section-head strong {
  display: block;
  font-size: 15px;
  color: #0f172a;
}

.tab-action-button {
  min-width: 116px;
  height: 32px;
  padding: 0 14px;
  border: 1px solid #d8e1ea;
  border-radius: 8px 8px 0 0;
  background: #f6f8fa;
  color: #334155;
  font-size: 13px;
  line-height: 30px;
  cursor: pointer;
}

.tab-action-button:hover {
  color: #1d4ed8;
  border-color: #bfd3f2;
  background: #f8fbff;
}

.overview-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.span-2 {
  grid-column: 1 / -1;
}

.detail-block span {
  display: block;
  margin-bottom: 6px;
  font-size: 12px;
  color: #64748b;
}

.detail-block strong {
  font-size: 14px;
  color: #0f172a;
}

.detail-block p {
  margin: 0;
  line-height: 1.6;
  color: #475569;
}

.detail-block,
.param-table,
.related-task-table {
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 8px;
}

.detail-block {
  padding: 12px;
  background: #fff;
}

.detail-pair-block {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.detail-pair-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.detail-pair-row span {
  margin-bottom: 0;
}

.detail-pair-row strong {
  flex: 1;
  text-align: right;
  font-size: 13px;
  color: #334155;
  word-break: break-all;
}

.param-table :deep(th.el-table__cell),
.related-task-table :deep(th.el-table__cell) {
  background: #f6f8fa;
  color: #475569;
  font-weight: 600;
}

.param-table :deep(td.el-table__cell),
.related-task-table :deep(td.el-table__cell) {
  padding-top: 8px;
  padding-bottom: 8px;
}

.param-name-cell strong {
  display: block;
  font-size: 13px;
  color: #0f172a;
}

.param-name-cell small {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  color: #64748b;
}

.task-dialog-shell {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.task-steps {
  margin-bottom: 4px;
}

.task-step-card {
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 8px;
  background: #fff;
  padding: 16px;
}

.task-step-head {
  margin-bottom: 16px;
}

.task-step-head strong {
  display: block;
  font-size: 15px;
  color: #0f172a;
}

.task-step-head p {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.6;
  color: #64748b;
}

.task-option-line,
.task-action-option {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.task-option-line span,
.task-action-option strong {
  color: #0f172a;
}

.task-option-line small,
.task-action-option small {
  color: #64748b;
  line-height: 1.5;
}

.task-action-grid {
  display: grid;
  gap: 12px;
}

.task-review-list {
  display: grid;
  gap: 10px;
}

.task-review-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 12px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 8px;
  background: #fff;
}

.task-review-row span {
  color: #64748b;
  font-size: 12px;
}

.task-review-row strong {
  flex: 1;
  text-align: right;
  font-size: 13px;
  line-height: 1.5;
  color: #0f172a;
}

@media (max-width: 768px) {
  .page-toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .toolbar-filters {
    flex-wrap: wrap;
  }

  .toolbar-search,
  .toolbar-select {
    width: 100%;
  }

  .page-toolbar > :deep(.el-button) {
    width: 100%;
  }

  .overview-grid {
    grid-template-columns: 1fr;
  }

  .tab-section-head {
    flex-direction: column;
    align-items: stretch;
  }

  .tab-action-button {
    width: 100%;
    border-radius: 8px;
  }

  .detail-pair-row {
    align-items: flex-start;
    flex-direction: column;
    gap: 6px;
  }

  .detail-pair-row strong {
    text-align: left;
  }

  .task-review-row {
    flex-direction: column;
    gap: 6px;
  }

  .task-review-row strong {
    text-align: left;
  }
}
</style>
