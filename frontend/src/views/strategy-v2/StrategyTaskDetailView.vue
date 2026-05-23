<template>
  <div class="task-detail-page">
    <section class="detail-toolbar">
      <el-button size="small" @click="router.push({ name: 'StrategyTaskCenterV2', query: task ? { scene: task.scene_type } : {} })">
        返回任务列表
      </el-button>
      <el-button size="small" @click="loadTask">刷新</el-button>
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
              <strong>{{ task.last_run_status ? runStatusLabel(task.last_run_status) : '未运行' }}</strong>
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
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { getStrategySceneTask, listStrategySceneTasks } from '@/api/modules/strategy-v2'
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

const task = ref<StrategySceneTask | null>(null)
const loading = ref(false)

const paramEntries = computed(() => {
  if (!task.value) return []
  return Object.entries(task.value.params || {}).map(([key, value]) => ({
    key,
    value: formatValue(value),
  }))
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
  return '运行中'
}

function statusTagType(status: StrategyTaskStatus): 'success' | 'warning' | 'info' | 'primary' {
  if (status === 'active') return 'success'
  if (status === 'paused') return 'warning'
  if (status === 'draft') return 'info'
  return 'primary'
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
  padding: 12px;
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
