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
          type="danger"
          plain
          :disabled="hasRunningRun"
          @click="deleteCurrentTask"
        >
          删除任务
        </el-button>
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

        <article v-if="isCustomStockListenTask" class="detail-card span-2">
          <div class="card-head">
            <div>
              <h2>监听股票</h2>
              <p class="card-subtitle">沿用旧市场监听的股票列表逻辑，股票保存在当前任务下，可单独维护股票级参数。</p>
            </div>
            <div class="stock-add-box">
              <el-select
                v-model="selectedStock"
                filterable
                remote
                clearable
                reserve-keyword
                placeholder="搜索代码或名称添加"
                :remote-method="searchStocks"
                :loading="stockSearchLoading"
                size="small"
                class="stock-search-select"
              >
                <el-option
                  v-for="stock in stockOptions"
                  :key="stock.ts_code"
                  :label="`${stock.name} (${stock.ts_code})`"
                  :value="stock.ts_code"
                >
                  <div class="stock-option">
                    <span>{{ stock.name }}</span>
                    <small>{{ stock.ts_code }}</small>
                  </div>
                </el-option>
              </el-select>
              <el-button size="small" type="primary" :loading="stockAdding" :disabled="!selectedStock" @click="addSelectedStock">
                添加
              </el-button>
            </div>
          </div>
          <el-table v-if="listenStocks.length > 0" :data="listenStocks" size="small" stripe>
            <el-table-column label="股票" min-width="180">
              <template #default="{ row }">
                <div class="stock-name-cell">
                  <strong>{{ row.name || row.ts_code }}</strong>
                  <small>{{ row.ts_code }}</small>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="启用" width="90">
              <template #default="{ row }">
                <el-switch
                  :model-value="row.config.enabled !== false"
                  size="small"
                  :loading="stockConfigSaving === row.ts_code"
                  @change="(value) => toggleStockEnabled(row.ts_code, Boolean(value))"
                />
              </template>
            </el-table-column>
            <el-table-column label="股票级参数" min-width="260" show-overflow-tooltip>
              <template #default="{ row }">
                {{ stockConfigSummary(row.config) }}
              </template>
            </el-table-column>
            <el-table-column label="备注" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.config.note || '-' }}
              </template>
            </el-table-column>
            <el-table-column label="操作" width="170" fixed="right">
              <template #default="{ row }">
                <el-button size="small" text type="primary" @click="openStockConfig(row)">
                  配置
                </el-button>
                <el-button size="small" text type="danger" @click="removeListenStock(row)">
                  移除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty v-else description="暂无监听股票，可从这里搜索添加，也可从股票详情、自选股、股池或交割单加入" :image-size="64" />
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

    <el-dialog
      v-model="stockConfigDialogVisible"
      :title="editingStock ? `配置监听股票：${editingStock.name || editingStock.ts_code}` : '配置监听股票'"
      width="520px"
      :close-on-click-modal="false"
    >
      <el-form v-if="editingStock" label-position="top" class="stock-config-form">
        <el-form-item label="是否启用">
          <el-switch v-model="editingStockConfig.enabled" active-text="启用" inactive-text="关闭" />
        </el-form-item>
        <el-row :gutter="12">
          <el-col v-for="param in editableStockParamSchema" :key="param.key" :span="12">
            <el-form-item :label="param.label">
              <el-select
                v-if="param.type === 'select' && param.options"
                v-model="editingStockConfig[param.key]"
                style="width: 100%"
              >
                <el-option
                  v-for="option in param.options"
                  :key="String(option.value)"
                  :label="option.label"
                  :value="option.value"
                />
              </el-select>
              <el-switch
                v-else-if="param.type === 'boolean'"
                v-model="editingStockConfig[param.key]"
                active-text="是"
                inactive-text="否"
              />
              <el-input-number
                v-else-if="param.type === 'number' || param.type === 'float'"
                v-model="editingStockConfig[param.key]"
                :precision="param.type === 'float' ? 4 : 0"
                :step="param.type === 'float' ? 0.1 : 1"
                :controls="false"
                style="width: 100%"
              />
              <el-input v-else v-model="editingStockConfig[param.key]" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="备注">
          <el-input v-model="editingStockConfig.note" type="textarea" :rows="3" placeholder="记录这只股票为什么加入监听，或参数特殊原因" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="stockConfigDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="stockConfigSaving === editingStock?.ts_code" @click="saveStockConfig">
          保存配置
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  addStockToStrategySceneTask,
  cancelTaskRun,
  deleteStrategySceneTask,
  getStrategySceneTask,
  listStrategyDefinitions,
  listStrategySceneTasks,
  listTaskRuns,
  removeStockFromStrategySceneTask,
  retryTaskRun,
  runStrategySceneTask,
  updateStrategySceneTaskStockConfig,
} from '@/api/modules/strategy-v2'
import { stockApi } from '@/api/modules/stock'
import {
  STRATEGY_ACTION_LABELS,
  STRATEGY_SCENE_LABELS,
  STRATEGY_TASK_STATUS_LABELS,
} from '@/mocks/strategyV2'
import type { StockBasic } from '@/api/types'
import type {
  StrategyDefinition,
  StrategyActionType,
  StrategyParamSchemaItem,
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
const strategyDefinitions = ref<StrategyDefinition[]>([])
const loading = ref(false)
const running = ref(false)
const selectedStock = ref('')
const stockOptions = ref<StockBasic[]>([])
const stockSearchLoading = ref(false)
const stockAdding = ref(false)
const stockConfigSaving = ref('')
const stockConfigDialogVisible = ref(false)
const editingStock = ref<ListenStockRow | null>(null)
const editingStockConfig = ref<Record<string, any>>({})

interface ListenStockRow {
  ts_code: string
  code: string
  name: string
  config: Record<string, any>
}

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
const isCustomStockListenTask = computed(() => {
  return task.value?.scene_type === 'listen' && task.value.target_scope?.scope_type === 'custom_stock_list'
})
const currentStrategyDefinition = computed(() => {
  if (!task.value) return null
  return strategyDefinitions.value.find((item) => item.strategy_key === task.value?.strategy_key) || null
})
const editableStockParamSchema = computed<StrategyParamSchemaItem[]>(() => {
  return (currentStrategyDefinition.value?.param_schema || []).filter((item) => !['stock_configs', 'query_text', 'cache_ttl_days'].includes(item.key))
})
const listenStocks = computed<ListenStockRow[]>(() => {
  const scope = task.value?.target_scope
  const tsCodes = scope?.scope_type === 'custom_stock_list' ? (scope.ts_codes || []) : []
  const stockConfigs = ((task.value?.params?.stock_configs || {}) as Record<string, Record<string, any>>)
  return tsCodes.map((tsCode) => {
    const config = stockConfigs[tsCode] || {}
    return {
      ts_code: tsCode,
      code: tsCode.split('.')[0],
      name: String(config.name || config.stock_name || tsCode),
      config,
    }
  })
})

onMounted(async () => {
  await loadStrategyDefinitions()
  await loadTask()
})

async function loadStrategyDefinitions(): Promise<void> {
  try {
    strategyDefinitions.value = await listStrategyDefinitions()
  }
  catch (error) {
    console.error(error)
    strategyDefinitions.value = []
  }
}

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

async function deleteCurrentTask(): Promise<void> {
  if (!task.value) return
  if (hasRunningRun.value) {
    ElMessage.warning('任务正在运行，请先取消或等待完成后再删除')
    return
  }
  try {
    await ElMessageBox.confirm(
      `删除后会同时清理任务运行记录、运行明细、日志和动作审计。确认删除「${task.value.name}」吗？`,
      '删除场景任务',
      {
        type: 'warning',
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
      },
    )
    const response = await deleteStrategySceneTask(task.value.task_id)
    ElMessage.success(response.message || '任务已删除')
    router.push({ name: 'StrategyTaskCenterV2', query: { scene: task.value.scene_type } })
  }
  catch (error) {
    if (error === 'cancel') return
    console.error(error)
    ElMessage.error('删除任务失败')
  }
}

async function searchStocks(query: string): Promise<void> {
  if (!query.trim()) {
    stockOptions.value = []
    return
  }
  stockSearchLoading.value = true
  try {
    stockOptions.value = await stockApi.searchStocks(query.trim(), 10)
  }
  catch (error) {
    console.error(error)
    stockOptions.value = []
  }
  finally {
    stockSearchLoading.value = false
  }
}

async function addSelectedStock(): Promise<void> {
  if (!task.value || !selectedStock.value) return
  stockAdding.value = true
  try {
    const updated = await addStockToStrategySceneTask(task.value.task_id, selectedStock.value)
    task.value = updated
    selectedStock.value = ''
    stockOptions.value = []
    ElMessage.success('监听股票已添加')
  }
  catch (error) {
    console.error(error)
    ElMessage.error('添加监听股票失败')
  }
  finally {
    stockAdding.value = false
  }
}

function openStockConfig(row: ListenStockRow): void {
  editingStock.value = row
  editingStockConfig.value = {
    enabled: row.config.enabled ?? true,
    note: row.config.note || '',
  }
  for (const param of editableStockParamSchema.value) {
    editingStockConfig.value[param.key] = row.config[param.key] ?? param.default
  }
  stockConfigDialogVisible.value = true
}

async function toggleStockEnabled(tsCode: string, enabled: boolean): Promise<void> {
  const row = listenStocks.value.find((item) => item.ts_code === tsCode)
  if (!task.value || !row) return
  stockConfigSaving.value = tsCode
  try {
    const updated = await updateStrategySceneTaskStockConfig(task.value.task_id, tsCode, {
      ...row.config,
      enabled,
    })
    task.value = updated
    ElMessage.success(enabled ? '已启用监听' : '已关闭监听')
  }
  catch (error) {
    console.error(error)
    ElMessage.error('更新监听状态失败')
  }
  finally {
    stockConfigSaving.value = ''
  }
}

async function saveStockConfig(): Promise<void> {
  if (!task.value || !editingStock.value) return
  const tsCode = editingStock.value.ts_code
  stockConfigSaving.value = tsCode
  try {
    const updated = await updateStrategySceneTaskStockConfig(task.value.task_id, tsCode, editingStockConfig.value)
    task.value = updated
    stockConfigDialogVisible.value = false
    ElMessage.success('股票级参数已保存')
  }
  catch (error) {
    console.error(error)
    ElMessage.error('保存股票级参数失败')
  }
  finally {
    stockConfigSaving.value = ''
  }
}

async function removeListenStock(row: ListenStockRow): Promise<void> {
  if (!task.value) return
  try {
    await ElMessageBox.confirm(
      `确认从「${task.value.name}」中移除 ${row.name || row.ts_code} 吗？股票级参数也会一并删除。`,
      '移除监听股票',
      {
        type: 'warning',
        confirmButtonText: '确认移除',
        cancelButtonText: '取消',
      },
    )
    const updated = await removeStockFromStrategySceneTask(task.value.task_id, row.ts_code)
    task.value = updated
    ElMessage.success('监听股票已移除')
  }
  catch (error) {
    if (error === 'cancel') return
    console.error(error)
    ElMessage.error('移除监听股票失败')
  }
}

function stockConfigSummary(config: Record<string, any>): string {
  const entries = editableStockParamSchema.value
    .map((param) => {
      const value = config[param.key]
      if (value === undefined || value === null || value === '') return ''
      return `${param.label}: ${formatValue(value)}`
    })
    .filter(Boolean)
  return entries.length > 0 ? entries.join('；') : '使用任务默认参数'
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

.card-subtitle {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.6;
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

.stock-add-box {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 320px;
}

.stock-search-select {
  width: 240px;
}

.stock-option,
.stock-name-cell {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.stock-option small,
.stock-name-cell small {
  color: #94a3b8;
  font-size: 12px;
}

.stock-name-cell {
  justify-content: flex-start;
  align-items: baseline;
}

.stock-config-form {
  padding-top: 4px;
}

@media (max-width: 1080px) {
  .summary-main,
  .detail-toolbar,
  .card-head {
    flex-direction: column;
  }

  .stock-add-box,
  .stock-search-select {
    width: 100%;
    min-width: 0;
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
