<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { systemApi } from '@/api'
import type {
  SystemCozePluginStatusResponse,
  SystemDataSyncBackfillJob,
  SystemDataSyncBackfillJobAction,
  SystemDataSourceMatrix,
  SystemDataSourceMatrixRow,
  SystemDataSyncStatusPanel,
  SystemDatasetStatus,
  SystemManualSyncTask,
  SystemStatusItem,
  SystemStatusLevel,
  SystemStatusOverview,
} from '@/api/types'

type SectionKey = 'services' | 'data_sources' | 'datasets' | 'features'

const overviewLoading = ref(true)
const refreshing = ref(false)
const cozeRefreshing = ref(false)
const manualSyncLoading = ref(false)
const datasyncLoading = ref(false)
const backfillJobLoading = ref<Record<string, boolean>>({})
const backfillJobActionLoading = ref<Record<string, boolean>>({})
const manualSyncTask = ref<SystemManualSyncTask | null>(null)
const datasyncStatus = ref<SystemDataSyncStatusPanel | null>(null)
const overview = ref<SystemStatusOverview | null>(null)
const cozePlugins = ref<SystemCozePluginStatusResponse | null>(null)
let manualSyncPollTimer: number | null = null
const sectionItems = ref<Record<SectionKey, (SystemStatusItem | SystemDatasetStatus)[]>>({
  services: [],
  data_sources: [],
  datasets: [],
  features: [],
})
const sectionMeta = ref<Record<SectionKey, Record<string, unknown>>>({
  services: {},
  data_sources: {},
  datasets: {},
  features: {},
})
const sectionLoading = ref<Record<SectionKey, boolean>>({
  services: true,
  data_sources: true,
  datasets: true,
  features: true,
})

const sections = computed(() => [
  { key: 'services' as SectionKey, title: '基础服务', items: sectionItems.value.services },
  { key: 'data_sources' as SectionKey, title: '数据源', items: sectionItems.value.data_sources },
  { key: 'datasets' as SectionKey, title: '数据准备', items: sectionItems.value.datasets },
  { key: 'features' as SectionKey, title: '功能接口', items: sectionItems.value.features },
])

const combinedSummary = computed(() => {
  const items = Object.values(sectionItems.value).flat()
  if (items.length === 0) {
    return overview.value?.summary ?? { available: 0, degraded: 0, unavailable: 0 }
  }
  return {
    available: items.filter((item) => item.status === 'available').length,
    degraded: items.filter((item) => item.status === 'degraded').length,
    unavailable: items.filter((item) => item.status === 'unavailable').length,
  }
})

const isManualSyncRunning = computed(() =>
  manualSyncTask.value?.status === 'queued' || manualSyncTask.value?.status === 'running'
)

const manualSyncLookbackDays = computed(() => {
  const value = manualSyncTask.value?.params?.lookback_days
  return typeof value === 'number' ? value : 3
})

async function loadOverview(forceRefresh = false) {
  overviewLoading.value = true
  try {
    overview.value = await systemApi.getSystemStatusOverview(forceRefresh)
  } catch (error) {
    console.error('加载系统概览失败', error)
    ElMessage.error('加载系统概览失败')
  } finally {
    overviewLoading.value = false
  }
}

async function loadSection(section: SectionKey, forceRefresh = false) {
  sectionLoading.value[section] = true
  try {
    const response = await systemApi.getSystemStatusSection(section, forceRefresh)
    sectionItems.value[section] = response.items
    sectionMeta.value[section] = response.metadata ?? {}
  } catch (error) {
    console.error(`加载 ${section} 失败`, error)
    ElMessage.error(`加载 ${section} 失败`)
  } finally {
    sectionLoading.value[section] = false
  }
}

async function loadCozePlugins(forceRefresh = false) {
  cozeRefreshing.value = true
  try {
    cozePlugins.value = await systemApi.getCozePluginStatus(forceRefresh)
  } catch (error) {
    console.error('加载 Coze 插件状态失败', error)
    ElMessage.error('加载 Coze 插件状态失败')
  } finally {
    cozeRefreshing.value = false
  }
}

async function loadDataSyncStatus() {
  datasyncLoading.value = true
  try {
    datasyncStatus.value = await systemApi.getDataSyncStatus()
  } catch (error) {
    console.error('加载 DataSync 状态失败', error)
    ElMessage.error('加载 DataSync 状态失败')
  } finally {
    datasyncLoading.value = false
  }
}

async function loadStatus(forceRefresh = false) {
  refreshing.value = true
  await Promise.all([
    loadOverview(forceRefresh),
    loadCozePlugins(forceRefresh),
    loadDataSyncStatus(),
    ...sections.value.map((section) => loadSection(section.key, forceRefresh)),
  ])
  refreshing.value = false
}

function getTaskStatusLabel(status?: string | null): string {
  switch (status) {
    case 'queued':
      return '排队中'
    case 'running':
      return '执行中'
    case 'completed':
      return '已完成'
    case 'failed':
      return '失败'
    default:
      return status || '未知'
  }
}

function getTaskStatusType(status?: string | null): 'info' | 'warning' | 'success' | 'danger' {
  switch (status) {
    case 'queued':
      return 'info'
    case 'running':
      return 'warning'
    case 'completed':
      return 'success'
    case 'failed':
    default:
      return 'danger'
  }
}

function getReadinessStatusLabel(status?: string | null): string {
  switch (status) {
    case 'ready':
      return '核心就绪'
    case 'degraded':
      return '降级可用'
    case 'building':
      return '生成中'
    case 'waiting_window':
      return '等待窗口'
    case 'missing':
      return '未生成'
    case 'failed':
      return '失败'
    default:
      return status || '未知'
  }
}

function getReadinessStatusType(status?: string | null): 'info' | 'warning' | 'success' | 'danger' {
  switch (status) {
    case 'ready':
      return 'success'
    case 'degraded':
    case 'building':
    case 'waiting_window':
      return 'warning'
    case 'missing':
      return 'info'
    case 'failed':
    default:
      return 'danger'
  }
}

function getRecoverabilityLabel(mode?: string | null): string {
  switch (mode) {
    case 'full':
      return '可补'
    case 'best_effort':
      return '尽力补'
    case 'none':
      return '不可还原'
    default:
      return '未知'
  }
}

function getRecoverabilityTagType(mode?: string | null): 'success' | 'warning' | 'danger' | 'info' {
  switch (mode) {
    case 'full':
      return 'success'
    case 'best_effort':
      return 'warning'
    case 'none':
      return 'danger'
    default:
      return 'info'
  }
}

function canEnqueueBackfill(mode?: string | null): boolean {
  return mode === 'full' || mode === 'best_effort'
}

function getBackfillLoadingKey(dataset: string): string {
  const tradeDate = datasyncStatus.value?.core_status.trade_date || 'unknown'
  return `${dataset}:${tradeDate}`
}

async function enqueueMissingDatasetBackfill(dataset: string) {
  const tradeDate = datasyncStatus.value?.core_status.trade_date
  if (!tradeDate) {
    ElMessage.warning('当前没有可用于补缺的核心交易日')
    return
  }

  const loadingKey = getBackfillLoadingKey(dataset)
  backfillJobLoading.value = {
    ...backfillJobLoading.value,
    [loadingKey]: true,
  }
  try {
    const job = await systemApi.enqueueDataSyncBackfillJob(dataset, tradeDate)
    ElMessage.success(job.already_exists ? '补缺任务已在队列中' : '已加入夜间补缺队列')
    await loadDataSyncStatus()
  } catch (error) {
    console.error('创建 DataSync 补缺任务失败', error)
    ElMessage.error('创建补缺任务失败')
  } finally {
    backfillJobLoading.value = {
      ...backfillJobLoading.value,
      [loadingKey]: false,
    }
  }
}

function getBackfillJobStatusLabel(status?: string | null): string {
  switch (status) {
    case 'pending':
      return '待处理'
    case 'running':
      return '执行中'
    case 'failed':
      return '失败'
    case 'paused':
      return '已暂停'
    case 'done':
      return '已完成'
    default:
      return status || '未知'
  }
}

function getBackfillJobActions(job: SystemDataSyncBackfillJob): SystemDataSyncBackfillJobAction[] {
  switch (job.status) {
    case 'pending':
      return ['pause']
    case 'failed':
      return ['retry', 'pause']
    case 'paused':
      return ['resume']
    default:
      return []
  }
}

function getBackfillJobActionLabel(action: SystemDataSyncBackfillJobAction): string {
  switch (action) {
    case 'pause':
      return '暂停'
    case 'resume':
      return '恢复'
    case 'retry':
      return '重试'
  }
}

function getOpsSeverityType(severity?: string | null): 'info' | 'warning' | 'success' | 'danger' {
  switch (severity) {
    case 'critical':
    case 'error':
      return 'danger'
    case 'warning':
      return 'warning'
    case 'info':
      return 'info'
    default:
      return 'info'
  }
}

function getOpsSeverityLabel(severity?: string | null): string {
  switch (severity) {
    case 'critical':
      return '严重'
    case 'error':
      return '错误'
    case 'warning':
      return '告警'
    case 'info':
      return '信息'
    default:
      return severity || '未知'
  }
}

function getOpsDetailValue(details: Record<string, unknown> | undefined, key: string): string {
  const value = details?.[key]
  return value === null || value === undefined || value === '' ? '' : String(value)
}

async function operateBackfillJob(job: SystemDataSyncBackfillJob, action: SystemDataSyncBackfillJobAction) {
  if (!job.job_id) return
  const loadingKey = `${job.job_id}:${action}`
  backfillJobActionLoading.value = {
    ...backfillJobActionLoading.value,
    [loadingKey]: true,
  }
  try {
    await systemApi.operateDataSyncBackfillJob(job.job_id, action)
    ElMessage.success(`补缺任务已${getBackfillJobActionLabel(action)}`)
    await loadDataSyncStatus()
  } catch (error) {
    console.error('操作 DataSync 补缺任务失败', error)
    ElMessage.error('操作补缺任务失败')
  } finally {
    backfillJobActionLoading.value = {
      ...backfillJobActionLoading.value,
      [loadingKey]: false,
    }
  }
}

function stopManualSyncPolling() {
  if (manualSyncPollTimer !== null) {
    window.clearInterval(manualSyncPollTimer)
    manualSyncPollTimer = null
  }
}

function startManualSyncPolling(taskId: string) {
  stopManualSyncPolling()
  manualSyncPollTimer = window.setInterval(() => {
    loadManualSyncTask(taskId)
  }, 4000)
}

async function loadManualSyncTask(taskId?: string) {
  try {
    manualSyncTask.value = taskId
      ? await systemApi.getManualGapFillSyncTask(taskId)
      : await systemApi.getLatestManualGapFillSync()

    if (isManualSyncRunning.value) {
      startManualSyncPolling(manualSyncTask.value.task_id)
      return
    }

    if (manualSyncPollTimer !== null) {
      stopManualSyncPolling()
      await loadStatus(true)
    }
  } catch (error) {
    if (taskId) {
      console.error('加载补漏同步任务失败', error)
    }
    if (manualSyncPollTimer !== null) {
      stopManualSyncPolling()
    }
  }
}

async function startManualSync() {
  manualSyncLoading.value = true
  try {
    const task = await systemApi.startManualGapFillSync(3)
    manualSyncTask.value = task
    ElMessage.success(task.message || `已开始补最近 ${manualSyncLookbackDays.value} 个交易日数据`)
    if (task.task_id) {
      startManualSyncPolling(task.task_id)
      await loadManualSyncTask(task.task_id)
    }
  } catch (error) {
    console.error('启动补漏同步失败', error)
    ElMessage.error('启动补漏同步失败')
  } finally {
    manualSyncLoading.value = false
  }
}

function getStatusLabel(status: SystemStatusLevel): string {
  return {
    available: '正常可用',
    degraded: '可用但降级',
    unavailable: '不可用',
  }[status]
}

function getStatusType(status: SystemStatusLevel): 'success' | 'warning' | 'danger' {
  switch (status) {
    case 'available':
      return 'success'
    case 'degraded':
      return 'warning'
    case 'unavailable':
    default:
      return 'danger'
  }
}

function formatDetails(item: SystemStatusItem): string[] {
  const lines: string[] = []

  if ('count' in item) {
    lines.push(`数据量：${item.count}`)
  }
  if ('latest_value' in item && item.latest_value) {
    lines.push(`最新值：${item.latest_value}`)
  }
  if (item.endpoint) {
    lines.push(`接口：${item.endpoint}`)
  }

  Object.entries(item.details || {}).forEach(([key, value]) => {
    if (key === 'interfaces' || key === 'description') return
    if (value === null || value === undefined || value === '') return
    lines.push(`${key}：${String(value)}`)
  })

  return lines
}

function getDataSourceMatrix(): SystemDataSourceMatrix | null {
  const matrix = sectionMeta.value.data_sources?.matrix
  if (!matrix || typeof matrix !== 'object') return null
  return matrix as SystemDataSourceMatrix
}

function getCurrentSourceLabel(row: SystemDataSourceMatrixRow): string {
  if (!row.current_source) return '未探测到默认源'
  return row.current_source_has_data
    ? `当前默认：${row.current_source}`
    : `默认路由：${row.current_source}（本次探测未拿到数据）`
}

function formatCozeParams(params: Record<string, unknown>): string {
  const entries = Object.entries(params || {})
  if (entries.length === 0) return '无需参数'
  return entries
    .map(([key, value]) => `${key}=${String(value)}`)
    .join(', ')
}

onMounted(() => {
  loadStatus()
  loadManualSyncTask()
})

onBeforeUnmount(() => {
  stopManualSyncPolling()
})
</script>

<template>
  <div class="system-status-page">
    <section class="hero card">
      <div class="hero-copy">
        <p class="eyebrow">运行态总览</p>
        <h1>项目能力状态</h1>
        <p class="description">
          这里会直接探测当前项目依赖的数据、节点和接口，把能用、降级和不可用的地方一次性列清楚；页面现在会优先显示概览，再分区块加载明细。
        </p>
        <p v-if="overview" class="generated-at">
          最近检测时间：{{ new Date(overview.generated_at).toLocaleString('zh-CN') }}
        </p>
      </div>

      <div class="hero-actions">
        <button class="sync-btn" @click="startManualSync" :disabled="manualSyncLoading || isManualSyncRunning">
          {{ manualSyncLoading ? '启动中...' : isManualSyncRunning ? '补漏任务进行中' : '补最近 3 个交易日核心数据' }}
        </button>
        <button class="refresh-btn" @click="loadStatus(true)">
          <el-icon><Refresh /></el-icon>
          {{ refreshing ? '刷新中...' : '重新检测' }}
        </button>
      </div>
    </section>

    <section v-if="manualSyncTask" class="manual-sync-card card">
      <div class="manual-sync-top">
        <div>
          <p class="eyebrow">补漏同步</p>
          <h2>最近 {{ manualSyncLookbackDays }} 个交易日核心数据</h2>
          <p class="manual-sync-copy">
            轻量补齐 `stock_daily / daily_basic / index_daily / limit_list / daily_stats / market_analysis / stock_relations`，
            适合服务器断档后的快速修复。
          </p>
        </div>
        <el-tag :type="getTaskStatusType(manualSyncTask.status)" effect="dark" round>
          {{ getTaskStatusLabel(manualSyncTask.status) }}
        </el-tag>
      </div>

      <div class="manual-sync-progress">
        <el-progress
          :percentage="manualSyncTask.progress"
          :status="manualSyncTask.status === 'failed' ? 'exception' : undefined"
          :indeterminate="manualSyncTask.status === 'queued'"
          :duration="3"
          :stroke-width="10"
        />
      </div>

      <div class="manual-sync-meta">
        <span>当前步骤：{{ manualSyncTask.current_step || '等待中' }}</span>
        <span>创建时间：{{ new Date(manualSyncTask.created_at).toLocaleString('zh-CN') }}</span>
        <span v-if="manualSyncTask.completed_at">
          完成时间：{{ new Date(manualSyncTask.completed_at).toLocaleString('zh-CN') }}
        </span>
      </div>

      <p v-if="manualSyncTask.message" class="manual-sync-message">
        {{ manualSyncTask.message }}
      </p>
      <p v-if="manualSyncTask.error_message" class="manual-sync-error">
        {{ manualSyncTask.error_message }}
      </p>
    </section>

    <section v-if="datasyncStatus" class="datasync-card card">
      <div class="datasync-header">
        <div>
          <p class="eyebrow">DataSync</p>
          <h2>数据能力状态</h2>
          <p class="datasync-copy">
            以独立 DataSync 的能力目录、核心 ready marker、任务失败记录和补缺队列为准。
          </p>
        </div>
        <div class="datasync-actions">
          <el-tag
            :type="getReadinessStatusType(datasyncStatus.core_status.status)"
            effect="dark"
            round
          >
            {{ getReadinessStatusLabel(datasyncStatus.core_status.status) }}
          </el-tag>
          <button class="refresh-btn ghost" @click="loadDataSyncStatus">
            <el-icon><Refresh /></el-icon>
            {{ datasyncLoading ? '刷新中...' : '刷新 DataSync' }}
          </button>
        </div>
      </div>

      <div class="datasync-metrics">
        <div class="datasync-metric">
          <span>核心交易日</span>
          <strong>{{ datasyncStatus.core_status.trade_date || '暂无' }}</strong>
        </div>
        <div class="datasync-metric">
          <span>已就绪 / 应就绪</span>
          <strong>
            {{ datasyncStatus.core_status.ready_datasets.length }} /
            {{ datasyncStatus.core_status.expected_datasets.length }}
          </strong>
        </div>
        <div class="datasync-metric">
          <span>缺失数据集</span>
          <strong>{{ datasyncStatus.core_status.missing_datasets.length }}</strong>
        </div>
        <div class="datasync-metric">
          <span>不可完整后补</span>
          <strong>
            {{ datasyncStatus.recoverability_summary.mode_counts.none || 0 }}
            <small v-if="datasyncStatus.recoverability_summary.mode_counts.best_effort">
              / {{ datasyncStatus.recoverability_summary.mode_counts.best_effort }} 尽力补
            </small>
          </strong>
        </div>
        <div class="datasync-metric">
          <span>补缺队列</span>
          <strong>
            {{ datasyncStatus.backfill_queue.pending_total }} 待处理
            <small v-if="datasyncStatus.backfill_queue.failed_total">
              / {{ datasyncStatus.backfill_queue.failed_total }} 失败
            </small>
          </strong>
        </div>
      </div>

      <div class="datasync-content">
        <div class="datasync-panel">
          <div class="datasync-panel-title">
            <h3>缺失与告警</h3>
            <span>{{ datasyncStatus.capability_catalog.count }} 项能力</span>
          </div>
          <div v-if="datasyncStatus.core_status.missing_datasets.length" class="dataset-tags">
            <el-tag
              v-for="dataset in datasyncStatus.core_status.missing_datasets"
              :key="dataset"
              type="warning"
              effect="plain"
              round
            >
              {{ dataset }}
            </el-tag>
          </div>
          <p v-else class="datasync-empty">当前核心数据集没有缺失项。</p>
          <div
            v-if="datasyncStatus.recoverability_summary.missing_datasets.length"
            class="recoverability-list"
          >
            <div
              v-for="item in datasyncStatus.recoverability_summary.missing_datasets"
              :key="item.dataset"
              class="recoverability-row"
            >
              <div class="recoverability-main">
                <span>{{ item.dataset }}</span>
                <el-tag :type="getRecoverabilityTagType(item.mode)" effect="plain" round size="small">
                  {{ getRecoverabilityLabel(item.mode) }}
                </el-tag>
              </div>
              <button
                class="mini-action-btn"
                :disabled="
                  !canEnqueueBackfill(item.mode) ||
                  !datasyncStatus.core_status.trade_date ||
                  backfillJobLoading[getBackfillLoadingKey(item.dataset)]
                "
                @click="enqueueMissingDatasetBackfill(item.dataset)"
              >
                {{
                  backfillJobLoading[getBackfillLoadingKey(item.dataset)]
                    ? '入队中...'
                    : canEnqueueBackfill(item.mode)
                      ? '加入补缺队列'
                      : '不可入队'
                }}
              </button>
            </div>
          </div>
          <p v-if="!datasyncStatus.capability_catalog.success" class="datasync-warning">
            能力目录读取失败：{{ datasyncStatus.capability_catalog.error || '未知错误' }}
          </p>
        </div>

        <div class="datasync-panel">
          <div class="datasync-panel-title">
            <h3>最近失败任务</h3>
            <span>{{ datasyncStatus.recent_failures.length }} 条</span>
          </div>
          <div v-if="datasyncStatus.recent_failures.length" class="compact-list">
            <div
              v-for="failure in datasyncStatus.recent_failures"
              :key="`${failure.job_name}-${failure.started_at}`"
              class="compact-row"
            >
              <strong>{{ failure.job_name || '未知任务' }}</strong>
              <span>
                {{ failure.target_trade_date || '无交易日' }}
                <template v-if="failure.recoverability?.mode">
                  · {{ getRecoverabilityLabel(failure.recoverability.mode) }}
                </template>
              </span>
              <p>{{ failure.error || '未记录错误详情' }}</p>
            </div>
          </div>
          <p v-else class="datasync-empty">最近 7 天没有失败任务。</p>
        </div>

        <div class="datasync-panel">
          <div class="datasync-panel-title">
            <h3>补缺队列</h3>
            <span>
              pending {{ datasyncStatus.backfill_queue.status_counts.pending || 0 }}
              · running {{ datasyncStatus.backfill_queue.status_counts.running || 0 }}
              · done {{ datasyncStatus.backfill_queue.status_counts.done || 0 }}
            </span>
          </div>
          <div v-if="datasyncStatus.backfill_queue.recent_jobs.length" class="compact-list">
            <div
              v-for="job in datasyncStatus.backfill_queue.recent_jobs"
              :key="job.job_id || `${job.dataset}-${job.target_trade_date}`"
              class="compact-row"
            >
              <strong>{{ job.dataset || '未知数据集' }}</strong>
              <span>{{ job.target_trade_date || '无交易日' }} · {{ getBackfillJobStatusLabel(job.status) }}</span>
              <p v-if="job.error">{{ job.error }}</p>
              <div v-if="getBackfillJobActions(job).length" class="compact-actions">
                <button
                  v-for="action in getBackfillJobActions(job)"
                  :key="action"
                  class="mini-action-btn"
                  :disabled="!job.job_id || Boolean(backfillJobActionLoading[`${job.job_id}:${action}`])"
                  @click="operateBackfillJob(job, action)"
                >
                  {{
                    backfillJobActionLoading[`${job.job_id}:${action}`]
                      ? '处理中...'
                      : getBackfillJobActionLabel(action)
                  }}
                </button>
              </div>
            </div>
          </div>
          <p v-else class="datasync-empty">补缺队列暂无任务。</p>
        </div>

        <div class="datasync-panel">
          <div class="datasync-panel-title">
            <h3>运维事件</h3>
            <span>{{ datasyncStatus.recent_ops_events.length }} 条</span>
          </div>
          <div v-if="datasyncStatus.recent_ops_events.length" class="compact-list">
            <div
              v-for="event in datasyncStatus.recent_ops_events"
              :key="event.event_id || `${event.event_type}-${event.created_at}`"
              class="compact-row"
            >
              <strong>{{ event.event_type || '未知事件' }}</strong>
              <span>
                <el-tag :type="getOpsSeverityType(event.severity)" effect="plain" round size="small">
                  {{ getOpsSeverityLabel(event.severity) }}
                </el-tag>
                {{ event.source || '未知来源' }}
                <template v-if="event.created_at">
                  · {{ new Date(event.created_at).toLocaleString('zh-CN') }}
                </template>
              </span>
              <p v-if="event.message">{{ event.message }}</p>
              <p v-if="event.details">
                <template v-if="getOpsDetailValue(event.details, 'dataset')">
                  {{ getOpsDetailValue(event.details, 'dataset') }}
                </template>
                <template v-if="getOpsDetailValue(event.details, 'target_trade_date')">
                  · {{ getOpsDetailValue(event.details, 'target_trade_date') }}
                </template>
                <template v-if="getOpsDetailValue(event.details, 'action')">
                  · {{ getOpsDetailValue(event.details, 'action') }}
                </template>
                <template v-if="getOpsDetailValue(event.details, 'previous_status')">
                  · {{ getOpsDetailValue(event.details, 'previous_status') }}
                  -> {{ getOpsDetailValue(event.details, 'next_status') }}
                </template>
              </p>
            </div>
          </div>
          <p v-else class="datasync-empty">最近没有 DataSync 运维事件。</p>
        </div>
      </div>
    </section>

    <section v-if="overview" class="summary-grid">
      <article class="summary-card success">
        <span class="summary-label">正常可用</span>
        <strong>{{ combinedSummary.available }}</strong>
      </article>
      <article class="summary-card warning">
        <span class="summary-label">可用但降级</span>
        <strong>{{ combinedSummary.degraded }}</strong>
      </article>
      <article class="summary-card danger">
        <span class="summary-label">不可用</span>
        <strong>{{ combinedSummary.unavailable }}</strong>
      </article>
      <article class="summary-card neutral">
        <span class="summary-label">在线节点</span>
        <strong>{{ Object.values(overview.nodes || {}).reduce((sum, count) => sum + count, 0) }}</strong>
      </article>
    </section>

    <section v-if="overview" class="node-strip card">
      <div class="node-item" v-for="(count, nodeType) in overview.nodes" :key="nodeType">
        <span class="node-name">{{ nodeType }}</span>
        <span class="node-count">{{ count }}</span>
      </div>
      <p v-if="Object.keys(overview.nodes || {}).length === 0" class="empty-tip">
        当前没有检测到任何在线节点。
      </p>
    </section>

    <section v-if="overviewLoading" class="loading-grid">
      <div class="loading-card card" v-for="idx in 2" :key="idx" />
    </section>

    <section v-else class="sections">
      <div v-for="section in sections" :key="section.key" class="section-block">
        <div class="section-header">
          <h2>{{ section.title }}</h2>
          <span class="section-count">
            {{ sectionLoading[section.key] ? '加载中...' : `${section.items.length} 项` }}
          </span>
        </div>

        <div v-if="sectionLoading[section.key]" class="loading-grid">
          <div class="loading-card card" v-for="idx in 2" :key="`${section.key}-${idx}`" />
        </div>

        <div v-else class="status-grid">
          <article
            v-for="item in section.items"
            :key="item.key"
            class="status-card card"
            :class="item.status"
          >
            <div class="status-top">
              <div>
                <h3>{{ item.name }}</h3>
                <p class="status-key">{{ item.key }}</p>
              </div>
              <el-tag :type="getStatusType(item.status)" effect="dark" round>
                {{ getStatusLabel(item.status) }}
              </el-tag>
            </div>

            <p class="status-reason">
              {{ item.reason || '当前没有发现已知问题。' }}
            </p>

            <ul v-if="formatDetails(item).length > 0" class="details-list">
              <li v-for="line in formatDetails(item)" :key="line">
                {{ line }}
              </li>
            </ul>

          </article>
        </div>

        <div
          v-if="section.key === 'data_sources' && getDataSourceMatrix() && getDataSourceMatrix()!.rows.length > 0"
          class="matrix-block card"
        >
          <div class="matrix-header">
            <div>
              <h3>接口矩阵</h3>
              <p>每个接口只展示一次，同时对比四种数据源的可用状态，并标出当前默认路由源。</p>
            </div>
          </div>

          <div class="matrix-table">
            <div class="matrix-row matrix-head">
              <div class="matrix-col interface">接口</div>
              <div
                v-for="adapter in getDataSourceMatrix()!.adapters"
                :key="adapter.key"
                class="matrix-col source"
              >
                <strong>{{ adapter.name }}</strong>
                <span>优先级 {{ adapter.priority ?? '-' }}</span>
              </div>
            </div>

            <div
              v-for="row in getDataSourceMatrix()!.rows"
              :key="row.key"
              class="matrix-row"
            >
              <div class="matrix-col interface">
                <strong>{{ row.name }}</strong>
                <p>{{ row.description }}</p>
                <el-tag
                  v-if="row.current_source"
                  size="small"
                  round
                  effect="dark"
                  type="success"
                >
                  {{ getCurrentSourceLabel(row) }}
                </el-tag>
                <span v-else class="matrix-empty">{{ getCurrentSourceLabel(row) }}</span>
              </div>

              <div
                v-for="cell in row.cells"
                :key="`${row.key}-${cell.source_key}`"
                class="matrix-col source"
              >
                <el-tag :type="getStatusType(cell.status)" effect="plain" round size="small">
                  {{ getStatusLabel(cell.status) }}
                </el-tag>
                <p>{{ cell.reason }}</p>
              </div>
            </div>
          </div>
        </div>

        <div
          v-if="section.key === 'data_sources' && cozePlugins"
          class="coze-block card"
        >
          <div class="matrix-header">
            <div>
              <h3>Coze 插件状态</h3>
              <p>
                这里会逐个探测扣子工作流当前挂载的全部 20 个股票插件；你可以单独刷新这一块，判断它们是持续失败还是偶发失败。
              </p>
            </div>

            <div class="coze-actions">
              <div class="coze-summary">
                <el-tag type="success" round effect="dark">正常 {{ cozePlugins.summary.available }}</el-tag>
                <el-tag type="warning" round effect="dark">降级 {{ cozePlugins.summary.degraded }}</el-tag>
                <el-tag type="danger" round effect="dark">失败 {{ cozePlugins.summary.unavailable }}</el-tag>
              </div>
              <button class="refresh-btn ghost" @click="loadCozePlugins(true)">
                <el-icon><Refresh /></el-icon>
                {{ cozeRefreshing ? '刷新中...' : '只刷新 Coze' }}
              </button>
            </div>
          </div>

          <p class="coze-meta">
            检测时间：{{ new Date(cozePlugins.generated_at).toLocaleString('zh-CN') }}
            · 单独接口：<code>/api/v1/system/status/coze?force_refresh=true</code>
          </p>

          <div class="coze-table">
            <div class="coze-row coze-head">
              <div class="coze-col plugin">插件</div>
              <div class="coze-col status">状态</div>
              <div class="coze-col usage">项目中是否使用</div>
              <div class="coze-col result">探测结果</div>
            </div>

            <div
              v-for="plugin in cozePlugins.plugins"
              :key="plugin.key"
              class="coze-row"
            >
              <div class="coze-col plugin">
                <strong>{{ plugin.name }}</strong>
                <p>{{ plugin.key }}</p>
                <span>{{ plugin.description }}</span>
              </div>

              <div class="coze-col status">
                <el-tag :type="getStatusType(plugin.status)" effect="dark" round>
                  {{ getStatusLabel(plugin.status) }}
                </el-tag>
                <span v-if="plugin.latency_ms !== null && plugin.latency_ms !== undefined">
                  {{ plugin.latency_ms }} ms
                </span>
              </div>

              <div class="coze-col usage">
                <el-tag :type="plugin.used_in_project ? 'success' : 'info'" effect="plain" round>
                  {{ plugin.used_in_project ? '已接入项目' : '暂未接入' }}
                </el-tag>
                <p>{{ plugin.usage_description }}</p>
              </div>

              <div class="coze-col result">
                <p class="coze-reason">{{ plugin.reason }}</p>
                <ul class="coze-details">
                  <li>参数：{{ formatCozeParams(plugin.params) }}</li>
                  <li v-if="plugin.data_key">主数据字段：{{ plugin.data_key }}</li>
                  <li>返回记录数：{{ plugin.data_count ?? 0 }}</li>
                  <li v-if="plugin.top_level_keys.length > 0">顶层字段：{{ plugin.top_level_keys.join(', ') }}</li>
                  <li v-if="plugin.sample_keys.length > 0">样本字段：{{ plugin.sample_keys.join(', ') }}</li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped lang="scss">
.system-status-page {
  display: flex;
  padding: 1.5rem;
  flex-direction: column;
  gap: 20px;
}

.hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding: 28px;
  background:
    radial-gradient(circle at top right, rgba(30, 136, 229, 0.18), transparent 36%),
    linear-gradient(135deg, rgba(16, 24, 40, 0.04), rgba(16, 24, 40, 0.01));
}

.hero-copy h1 {
  margin: 4px 0 10px;
  font-size: 30px;
  line-height: 1.15;
}

.eyebrow {
  margin: 0;
  font-size: 12px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--el-color-primary);
}

.description,
.generated-at {
  margin: 0;
  color: var(--el-text-color-secondary);
  line-height: 1.7;
}

.generated-at {
  margin-top: 12px;
  font-size: 13px;
}

.refresh-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: none;
  border-radius: 999px;
  padding: 12px 18px;
  background: linear-gradient(135deg, #0f766e, #0ea5a4);
  color: #fff;
  cursor: pointer;
  font-weight: 600;
}

.hero-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.sync-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(15, 118, 110, 0.18);
  border-radius: 999px;
  padding: 12px 18px;
  background: rgba(15, 118, 110, 0.08);
  color: #0f766e;
  cursor: pointer;
  font-weight: 600;
}

.sync-btn:disabled {
  cursor: not-allowed;
  opacity: 0.72;
}

.refresh-btn.ghost {
  background: rgba(15, 118, 110, 0.08);
  color: #0f766e;
  border: 1px solid rgba(15, 118, 110, 0.16);
}

.manual-sync-card {
  padding: 20px 22px;
  border: 1px solid rgba(15, 118, 110, 0.14);
  background: linear-gradient(135deg, rgba(15, 118, 110, 0.05), rgba(14, 165, 164, 0.03));
}

.manual-sync-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.manual-sync-top h2 {
  margin: 4px 0 0;
  font-size: 22px;
}

.manual-sync-copy,
.manual-sync-message,
.manual-sync-error {
  margin: 10px 0 0;
  line-height: 1.7;
}

.manual-sync-copy,
.manual-sync-message {
  color: var(--el-text-color-secondary);
}

.manual-sync-error {
  color: var(--el-color-danger);
}

.manual-sync-progress {
  margin-top: 18px;
}

.manual-sync-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 18px;
  margin-top: 14px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.datasync-card {
  padding: 22px;
  border: 1px solid rgba(37, 99, 235, 0.14);
  background: linear-gradient(135deg, rgba(37, 99, 235, 0.05), rgba(14, 165, 164, 0.03));
}

.datasync-header,
.datasync-actions,
.datasync-panel-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}

.datasync-header h2 {
  margin: 4px 0 0;
  font-size: 22px;
}

.datasync-copy,
.datasync-empty,
.datasync-warning {
  margin: 10px 0 0;
  line-height: 1.7;
}

.datasync-copy,
.datasync-empty {
  color: var(--el-text-color-secondary);
}

.datasync-warning {
  color: var(--el-color-warning);
}

.datasync-actions {
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.datasync-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-top: 18px;
}

.datasync-metric {
  padding: 14px 16px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(15, 23, 42, 0.06);
}

.datasync-metric span {
  display: block;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.datasync-metric strong {
  display: block;
  margin-top: 8px;
  color: #0f172a;
  font-size: 20px;
  line-height: 1.2;
}

.datasync-metric small {
  color: var(--el-color-danger);
  font-size: 13px;
  font-weight: 600;
}

.datasync-content {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin-top: 16px;
}

.datasync-panel {
  min-width: 0;
  padding: 16px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.76);
  border: 1px solid rgba(15, 23, 42, 0.06);
}

.datasync-panel-title h3 {
  margin: 0;
  font-size: 16px;
}

.datasync-panel-title span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  white-space: nowrap;
}

.dataset-tags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 12px;
}

.recoverability-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 12px;
}

.recoverability-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 12px;
  background: rgba(15, 23, 42, 0.035);
  color: var(--el-text-color-regular);
  font-size: 13px;
}

.recoverability-main {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  gap: 8px;
}

.recoverability-main span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mini-action-btn {
  flex: 0 0 auto;
  border: 1px solid rgba(37, 99, 235, 0.16);
  border-radius: 999px;
  padding: 6px 10px;
  background: rgba(37, 99, 235, 0.08);
  color: #2563eb;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
}

.mini-action-btn:disabled {
  cursor: not-allowed;
  opacity: 0.54;
}

.compact-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 12px;
}

.compact-row {
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(15, 23, 42, 0.04);
}

.compact-row strong {
  display: block;
  font-size: 14px;
}

.compact-row span,
.compact-row p {
  display: block;
  margin: 6px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.compact-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.summary-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 20px;
  border-radius: 20px;
  color: #0f172a;
}

.summary-card strong {
  font-size: 34px;
  line-height: 1;
}

.summary-label {
  font-size: 13px;
  color: rgba(15, 23, 42, 0.72);
}

.summary-card.success {
  background: linear-gradient(135deg, rgba(34, 197, 94, 0.18), rgba(187, 247, 208, 0.72));
}

.summary-card.warning {
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.16), rgba(254, 240, 138, 0.72));
}

.summary-card.danger {
  background: linear-gradient(135deg, rgba(239, 68, 68, 0.16), rgba(254, 202, 202, 0.72));
}

.summary-card.neutral {
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.12), rgba(191, 219, 254, 0.72));
}

.node-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  padding: 18px 20px;
}

.node-item {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.05);
}

.node-name {
  text-transform: uppercase;
  font-size: 12px;
  letter-spacing: 0.08em;
  color: var(--el-text-color-secondary);
}

.node-count {
  font-weight: 700;
}

.empty-tip {
  margin: 0;
  color: var(--el-text-color-secondary);
}

.loading-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.loading-card {
  min-height: 180px;
}

.sections {
  display: flex;
  flex-direction: column;
  gap: 28px;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.section-header h2 {
  margin: 0;
  font-size: 22px;
}

.section-count {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.status-card {
  padding: 20px;
  border: 1px solid rgba(15, 23, 42, 0.08);
}

.status-card.available {
  border-color: rgba(34, 197, 94, 0.22);
}

.status-card.degraded {
  border-color: rgba(245, 158, 11, 0.24);
}

.status-card.unavailable {
  border-color: rgba(239, 68, 68, 0.24);
}

.status-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.status-top h3 {
  margin: 0;
  font-size: 18px;
}

.status-key {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.status-reason {
  margin: 14px 0 0;
  line-height: 1.7;
  color: var(--el-text-color-regular);
}

.details-list {
  margin: 14px 0 0;
  padding-left: 18px;
  color: var(--el-text-color-secondary);
  line-height: 1.7;
}

.matrix-block {
  margin-top: 16px;
  padding: 20px;
}

.matrix-header h3 {
  margin: 0;
  font-size: 18px;
}

.matrix-header p {
  margin: 8px 0 0;
  color: var(--el-text-color-secondary);
  line-height: 1.7;
}

.matrix-table {
  display: flex;
  flex-direction: column;
  margin-top: 16px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 18px;
  overflow: hidden;
}

.matrix-row {
  display: grid;
  grid-template-columns: 1.25fr repeat(4, 1fr);
}

.matrix-row + .matrix-row {
  border-top: 1px solid rgba(15, 23, 42, 0.08);
}

.matrix-head {
  background: rgba(15, 23, 42, 0.04);
}

.matrix-col {
  padding: 14px 16px;
}

.matrix-col.interface strong,
.matrix-col.source strong {
  display: block;
}

.matrix-col.interface p,
.matrix-col.source p,
.matrix-col.source span {
  margin: 8px 0 0;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
  font-size: 13px;
}

.matrix-empty {
  display: inline-block;
  margin-top: 10px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.coze-block {
  margin-top: 16px;
  padding: 22px;
}

.coze-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 12px;
}

.coze-summary {
  display: inline-flex;
  gap: 8px;
  flex-wrap: wrap;
}

.coze-meta {
  margin: 12px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.7;
}

.coze-table {
  display: flex;
  flex-direction: column;
  margin-top: 16px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 18px;
  overflow: hidden;
}

.coze-row {
  display: grid;
  grid-template-columns: minmax(220px, 1.15fr) minmax(140px, 0.5fr) minmax(220px, 0.9fr) minmax(320px, 1.45fr);
}

.coze-row + .coze-row {
  border-top: 1px solid rgba(15, 23, 42, 0.08);
}

.coze-head {
  background: rgba(15, 23, 42, 0.04);
  font-weight: 700;
}

.coze-col {
  min-width: 0;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.coze-col strong {
  display: block;
}

.coze-col p,
.coze-col span {
  margin: 0;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
  font-size: 13px;
}

.coze-reason {
  color: var(--el-text-color-regular) !important;
}

.coze-details {
  margin: 0;
  padding-left: 18px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

@media (max-width: 1100px) {
  .summary-grid,
  .datasync-metrics,
  .datasync-content,
  .status-grid,
  .loading-grid {
    grid-template-columns: 1fr;
  }

  .matrix-row {
    grid-template-columns: 1fr;
  }

  .coze-row {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .hero {
    flex-direction: column;
    padding: 22px;
  }

  .manual-sync-top {
    flex-direction: column;
  }

  .datasync-header,
  .datasync-actions {
    align-items: flex-start;
    flex-direction: column;
  }

  .hero-copy h1 {
    font-size: 26px;
  }
}
</style>
