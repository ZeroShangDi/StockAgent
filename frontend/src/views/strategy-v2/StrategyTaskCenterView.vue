<template>
  <div class="task-center-page">
    <section class="task-toolbar">
      <div class="toolbar-main">
        <el-input
          v-model="keyword"
          clearable
          placeholder="搜索任务名 / 策略 / 目标范围"
          class="toolbar-search"
        />
        <el-select v-model="sceneFilter" class="toolbar-select">
          <el-option label="全部场景" value="all" />
          <el-option v-for="scene in sceneOptions" :key="scene.value" :label="scene.label" :value="scene.value" />
        </el-select>
        <el-select v-model="statusFilter" class="toolbar-select">
          <el-option label="全部状态" value="all" />
          <el-option v-for="status in statusOptions" :key="status.value" :label="status.label" :value="status.value" />
        </el-select>
      </div>
      <div class="toolbar-actions">
        <el-button size="small" @click="refreshTasks">刷新</el-button>
        <el-button size="small" @click="router.push({ name: 'StrategyCenterV2' })">策略中心</el-button>
      </div>
    </section>

    <section class="status-strip">
      <article v-for="item in statusStats" :key="item.value" class="status-card">
        <span>{{ item.label }}</span>
        <strong>{{ item.count }}</strong>
      </article>
    </section>

    <section class="task-table-card">
      <el-table
        v-loading="loading"
        :data="filteredTasks"
        row-key="task_id"
        stripe
        size="small"
        class="task-table"
        empty-text="暂无任务"
      >
        <el-table-column label="任务" min-width="230" fixed>
          <template #default="{ row }">
            <div class="task-name-cell">
              <strong>{{ row.name }}</strong>
              <small v-if="row.notes">{{ row.notes }}</small>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" effect="plain" round>
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="场景" width="110">
          <template #default="{ row }">
            {{ sceneLabel(row.scene_type) }}
          </template>
        </el-table-column>

        <el-table-column label="策略" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.strategy_name }}
          </template>
        </el-table-column>

        <el-table-column label="目标范围" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.target_scope_summary || row.target_scope?.summary || '-' }}
          </template>
        </el-table-column>

        <el-table-column label="调度" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.schedule_label || row.schedule?.label || '-' }}
          </template>
        </el-table-column>

        <el-table-column label="动作" min-width="180">
          <template #default="{ row }">
            <div class="action-list">
              <el-tag
                v-for="action in row.actions"
                :key="action.action_id"
                size="small"
                effect="plain"
              >
                {{ action.label || actionLabel(action.action_type) }}
              </el-tag>
              <span v-if="row.actions.length === 0" class="muted-text">无动作</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="最近运行" min-width="140">
          <template #default="{ row }">
            <div class="run-cell">
              <span v-if="row.last_run_status">{{ runStatusLabel(row.last_run_status) }}</span>
              <span v-else class="muted-text">未运行</span>
              <small>信号 {{ row.last_signal_count || 0 }}</small>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="更新时间" width="170">
          <template #default="{ row }">
            {{ formatDateTime(row.updated_at || row.created_at) }}
          </template>
        </el-table-column>

        <el-table-column label="操作" width="110" align="right" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" link @click="goDetail(row.task_id)">
              查看详情
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { listStrategySceneTasks } from '@/api/modules/strategy-v2'
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
  StrategyTaskStatus,
} from '@/types/strategy-v2'

const route = useRoute()
const router = useRouter()

const tasks = ref<StrategySceneTask[]>([])
const keyword = ref('')
const sceneFilter = ref<'all' | StrategySceneType>('all')
const statusFilter = ref<'all' | StrategyTaskStatus>('all')
const loading = ref(false)

const sceneOptions = [
  { label: STRATEGY_SCENE_LABELS.scan, value: 'scan' as const },
  { label: STRATEGY_SCENE_LABELS.listen, value: 'listen' as const },
  { label: STRATEGY_SCENE_LABELS.backtest, value: 'backtest' as const },
  { label: STRATEGY_SCENE_LABELS.sim_trade, value: 'sim_trade' as const },
]

const statusOptions = [
  { label: STRATEGY_TASK_STATUS_LABELS.active, value: 'active' as const },
  { label: STRATEGY_TASK_STATUS_LABELS.paused, value: 'paused' as const },
  { label: STRATEGY_TASK_STATUS_LABELS.draft, value: 'draft' as const },
  { label: STRATEGY_TASK_STATUS_LABELS.archived, value: 'archived' as const },
]

const filteredTasks = computed(() => {
  const text = keyword.value.trim().toLowerCase()
  return tasks.value.filter((task) => {
    const matchesScene = sceneFilter.value === 'all' || task.scene_type === sceneFilter.value
    const matchesStatus = statusFilter.value === 'all' || task.status === statusFilter.value
    const targetSummary = task.target_scope_summary || task.target_scope?.summary || ''
    const matchesText = !text
      || task.name.toLowerCase().includes(text)
      || task.strategy_name.toLowerCase().includes(text)
      || targetSummary.toLowerCase().includes(text)
      || task.tags.some((tag) => tag.toLowerCase().includes(text))
    return matchesScene && matchesStatus && matchesText
  })
})

const statusStats = computed(() => [
  { label: '全部任务', value: 'all', count: tasks.value.length },
  ...statusOptions.map((status) => ({
    ...status,
    count: tasks.value.filter((task) => task.status === status.value).length,
  })),
])

onMounted(async () => {
  hydrateFromQuery()
  await refreshTasks()
})

watch(
  () => route.query,
  () => {
    hydrateFromQuery()
  },
)

function hydrateFromQuery(): void {
  const scene = String(route.query.scene || '').trim()
  if (isSceneType(scene)) {
    sceneFilter.value = scene
  }

  const strategy = String(route.query.strategy || '').trim()
  if (strategy) {
    keyword.value = strategy
  }
}

async function refreshTasks(): Promise<void> {
  loading.value = true
  try {
    tasks.value = await listStrategySceneTasks()
  }
  catch (error) {
    console.error(error)
    ElMessage.error('任务列表加载失败')
  }
  finally {
    loading.value = false
  }
}

function goDetail(taskId: string): void {
  router.push({ name: 'StrategyTaskDetailV2', params: { taskId } })
}

function isSceneType(value: string): value is StrategySceneType {
  return ['scan', 'listen', 'backtest', 'sim_trade'].includes(value)
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
  if (status === 'cancelled') return '已取消'
  return '运行中'
}

function formatDateTime(value?: string): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
</script>

<style scoped>
.task-center-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.task-toolbar,
.task-table-card,
.status-card {
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: #fff;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.04);
}

.task-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 14px;
  border-radius: 14px;
}

.toolbar-main,
.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.toolbar-search {
  width: 320px;
}

.toolbar-select {
  width: 150px;
}

.status-strip {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
}

.status-card {
  border-radius: 12px;
  padding: 12px 14px;
}

.status-card span,
.task-name-cell small,
.run-cell small,
.muted-text {
  color: #64748b;
}

.status-card span,
.run-cell small {
  display: block;
  font-size: 12px;
}

.status-card strong {
  display: block;
  margin-top: 4px;
  color: #0f172a;
  font-size: 22px;
}

.task-table-card {
  border-radius: 14px;
  padding: 8px;
}

.task-table {
  width: 100%;
}

.task-name-cell,
.run-cell {
  display: grid;
  gap: 4px;
}

.task-name-cell strong {
  color: #0f172a;
}

.action-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

@media (max-width: 1080px) {
  .task-toolbar,
  .toolbar-main,
  .toolbar-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .toolbar-search,
  .toolbar-select {
    width: 100%;
  }

  .status-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
