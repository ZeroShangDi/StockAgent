<template>
  <div class="pools-page">
    <section class="hero-card">
      <div>
        <p class="eyebrow">Stock Pools</p>
        <h1>股池工作台</h1>
        <p class="description">
          按股池类型管理不同来源的观察名单，快速浏览池内涨跌表现，并进入沉浸式复盘与流转操作。
        </p>
      </div>
      <div class="hero-actions">
        <el-button type="primary" @click="openCreateDialog">新建股池</el-button>
        <el-button :loading="loading" @click="loadPools">刷新股池</el-button>
      </div>
    </section>

    <section class="body-grid">
      <aside class="pool-list-card">
        <header>
          <h2>我的股池</h2>
        </header>
        <div v-if="pools.length === 0" class="empty-state">
          还没有股池，可以先去“一句话选股”里把结果加入某个池。
        </div>
        <div v-else class="pool-groups">
          <section
            v-for="group in groupedPools"
            :key="group.type"
            class="pool-group"
          >
            <div class="pool-group-header">
              <strong>{{ group.type }}</strong>
            </div>
            <button
              v-for="pool in group.items"
              :key="pool.pool_id"
              type="button"
              :class="['pool-item', { active: activePoolId === pool.pool_id }]"
              @click="selectPool(pool.pool_id)"
            >
              <div class="pool-item-main">
                <strong>{{ pool.name }}</strong>
                <span>{{ pool.latest_trade_date ? formatTradeDate(pool.latest_trade_date) : '待估值' }}</span>
              </div>
              <span
                class="pool-item-pct"
                :class="getPnlClass(pool.avg_pct_chg)"
              >
                {{ formatSignedPct(pool.avg_pct_chg) }}
              </span>
            </button>
          </section>
        </div>
      </aside>

      <section class="pool-detail-card">
        <template v-if="activePool">
          <header class="detail-header">
            <div>
              <p class="detail-type">{{ activePool.pool_type }}</p>
              <h2>{{ activePool.name }}</h2>
              <p class="detail-desc">{{ activePool.description || '暂无备注' }}</p>
            </div>
            <div class="detail-side">
              <div class="detail-actions">
                <el-button
                  type="primary"
                  plain
                  size="small"
                  :disabled="!activePool.stocks.length"
                  @click="() => openPoolReview()"
                >
                  沉浸复盘
                </el-button>
                <el-button
                  type="primary"
                  plain
                  size="small"
                  :disabled="selectedPoolStocks.length === 0"
                  @click="openBatchDialog"
                >
                  批量加入监听
                </el-button>
                <el-button
                  type="danger"
                  plain
                  size="small"
                  :disabled="selectedPoolStocks.length === 0"
                  @click="handleRemoveSelectedStocks"
                >
                  移除已选股票
                </el-button>
                <el-button
                  type="danger"
                  size="small"
                  :disabled="!activePool"
                  @click="handleDeletePool"
                >
                  删除股池
                </el-button>
              </div>
              <div class="detail-meta-row">
                <span>股票数 {{ activePool.stock_count }}</span>
                <span v-if="activePool.avg_pct_chg != null" :class="getPnlClass(activePool.avg_pct_chg)">
                  平均涨跌 {{ formatSignedPct(activePool.avg_pct_chg) }}
                </span>
                <span v-if="selectedPoolStocks.length > 0">已勾选 {{ selectedPoolStocks.length }} 只</span>
                <span v-if="activePool.latest_trade_date">估值日 {{ formatTradeDate(activePool.latest_trade_date) }}</span>
                <span v-if="activePool.updated_at">更新于 {{ formatDateTime(activePool.updated_at) }}</span>
              </div>
              <p v-if="activePool.pool_type === '候选池'" class="detail-expire-note">
                候选池里来自一句话选股的股票，超过 5 个交易日会自动移出。
              </p>
            </div>
          </header>

          <div class="detail-table-wrap">
            <el-table :data="paginatedPoolStocks" stripe height="100%" @selection-change="handleSelectionChange">
              <el-table-column type="selection" width="52" />
              <el-table-column prop="code" label="代码" width="120" />
              <el-table-column prop="ts_code" label="TS 代码" width="150" />
              <el-table-column prop="name" label="名称" min-width="140" />
              <el-table-column label="最新涨跌" width="110">
                <template #default="{ row }">
                  <span :class="getPnlClass(row.latest_pct_chg)">{{ formatSignedPct(row.latest_pct_chg) }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="status" label="状态" width="100" />
              <el-table-column label="来源模块" width="140">
                <template #default="{ row }">
                  {{ getSourceModuleLabel(row.source_module) }}
                </template>
              </el-table-column>
              <el-table-column label="来源股池" width="160">
                <template #default="{ row }">
                  <span>{{ row.source_pool_name || '-' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="来源条件" min-width="260">
                <template #default="{ row }">
                  <el-tooltip
                    v-if="row.source_query"
                    effect="light"
                    placement="top-start"
                    :show-after="100"
                  >
                    <template #content>
                      <div class="source-query-tooltip">{{ row.source_query }}</div>
                    </template>
                    <div class="source-query-text">{{ row.source_query }}</div>
                  </el-tooltip>
                  <span v-else>-</span>
                </template>
              </el-table-column>
              <el-table-column prop="added_at" label="加入时间" width="180">
                <template #default="{ row }">{{ row.added_at ? formatDateTime(row.added_at) : '-' }}</template>
              </el-table-column>
              <el-table-column label="操作" width="170" fixed="right">
                <template #default="{ row }">
                  <div class="row-actions">
                    <el-button link type="primary" @click="openPoolReview(row.ts_code)">沉浸复盘</el-button>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <div v-if="activePool.stock_count > pageSize" class="detail-pagination">
            <el-pagination
              v-model:current-page="currentPage"
              :page-size="pageSize"
              layout="prev, pager, next, jumper, total"
              :total="activePool.stock_count"
              small
            />
          </div>
        </template>
        <template v-else>
          <el-empty description="请选择一个股池查看详情" />
        </template>
      </section>
    </section>

    <el-dialog
      v-model="batchDialogVisible"
      title="批量加入策略监听"
      width="500px"
      :close-on-click-modal="false"
    >
      <div class="dialog-body">
        <div class="batch-summary-card">
          <strong>已选股票</strong>
          <span>{{ selectedPoolStocks.length }} 只</span>
        </div>

        <div class="field-block">
          <label>V2 监听任务</label>
          <el-select
            v-model="selectedMonitorTaskId"
            class="dialog-select"
            placeholder="请选择监听任务"
            :loading="strategyTypeLoading"
          >
            <el-option
              v-for="item in monitorTasks"
              :key="item.task_id"
              :label="item.name"
              :value="item.task_id"
            >
              <div class="strategy-option">
                <span>{{ item.name }}</span>
                <small>{{ item.strategy_name }} · {{ item.target_scope_summary || item.target_scope?.summary }}</small>
              </div>
            </el-option>
          </el-select>
        </div>

        <p v-if="monitorTasks.length === 0" class="batch-hint">
          暂无可用的 V2 自定义股票列表监听任务，请先到策略中心创建监听任务。
        </p>
        <p v-else class="batch-hint">
          股票会加入所选任务的自定义股票列表；股票级策略参数后续会保存在该任务的参数配置中。
        </p>
      </div>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="batchDialogVisible = false">取消</el-button>
          <el-button
            type="primary"
            :loading="batchAdding"
            :disabled="!selectedMonitorTaskId"
            @click="handleBatchAddStrategy"
          >
            确认加入
          </el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="createDialogVisible"
      title="新建股池"
      width="520px"
      :close-on-click-modal="false"
    >
      <div class="dialog-body">
        <div class="field-block">
          <label>股池名称</label>
          <el-input v-model="createForm.name" maxlength="50" placeholder="例如：异动确认池" />
        </div>

        <div class="field-block">
          <label>股池类型</label>
          <el-select v-model="createForm.pool_type" class="dialog-select" placeholder="请选择股池类型">
            <el-option
              v-for="type in STOCK_POOL_TYPE_OPTIONS"
              :key="type"
              :label="type"
              :value="type"
            />
          </el-select>
        </div>

        <div class="field-block">
          <label>备注说明</label>
          <el-input
            v-model="createForm.description"
            type="textarea"
            :rows="3"
            maxlength="200"
            show-word-limit
            placeholder="可选，记录该股池的用途和筛选标准"
          />
        </div>
      </div>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="createDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="creatingPool" @click="handleCreatePool">
            创建股池
          </el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { stockPickerApi } from '@/api'
import { addStockToStrategySceneTask, listStrategySceneTasks } from '@/api/modules/strategy-v2'
import { STOCK_POOL_TYPE_OPTIONS } from '@/api/modules/stock-picker'
import type { StockPoolDetail, StockPoolSummary, StockPoolStock } from '@/api/modules/stock-picker'
import type { StrategySceneTask } from '@/types/strategy-v2'

const router = useRouter()
const route = useRoute()

const loading = ref(false)
const pools = ref<StockPoolSummary[]>([])
const activePoolId = ref('')
const activePool = ref<StockPoolDetail | null>(null)
const selectedPoolStocks = ref<StockPoolStock[]>([])
const batchDialogVisible = ref(false)
const monitorTasks = ref<StrategySceneTask[]>([])
const strategyTypeLoading = ref(false)
const batchAdding = ref(false)
const selectedMonitorTaskId = ref('')
const createDialogVisible = ref(false)
const creatingPool = ref(false)
const currentPage = ref(1)
const pageSize = 20
const createForm = reactive({
  name: '',
  pool_type: STOCK_POOL_TYPE_OPTIONS[0],
  description: '',
})

const SOURCE_MODULE_LABELS: Record<string, string> = {
  one_line_picker: '一句话选股',
  listener_transition: '监听流转',
  manual: '手动添加',
  market_weather: '市场晴雨表',
}

const groupedPools = computed(() => {
  const groups = new Map<string, StockPoolSummary[]>()
  for (const type of STOCK_POOL_TYPE_OPTIONS) {
    groups.set(type, [])
  }
  const extra: StockPoolSummary[] = []
  for (const pool of pools.value) {
    if (groups.has(pool.pool_type)) {
      groups.get(pool.pool_type)!.push(pool)
    } else {
      extra.push(pool)
    }
  }
  const result = Array.from(groups.entries())
    .map(([type, items]) => ({ type, items }))
    .filter((group) => group.items.length > 0)
  if (extra.length > 0) {
    result.push({ type: '其他', items: extra })
  }
  return result
})

const paginatedPoolStocks = computed(() => {
  const stocks = activePool.value?.stocks || []
  const start = (currentPage.value - 1) * pageSize
  return stocks.slice(start, start + pageSize)
})

function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

function formatTradeDate(value?: string | null): string {
  if (!value) return '-'
  return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`
}

function formatSignedPct(value?: number | null): string {
  if (value == null || Number.isNaN(Number(value))) return '-'
  const numeric = Number(value)
  return `${numeric > 0 ? '+' : ''}${numeric.toFixed(2)}%`
}

function getPnlClass(value?: number | null): string {
  const numeric = Number(value || 0)
  if (numeric > 0) return 'is-profit'
  if (numeric < 0) return 'is-loss'
  return ''
}

function getSourceModuleLabel(sourceModule?: string): string {
  if (!sourceModule) return '-'
  return SOURCE_MODULE_LABELS[sourceModule] || sourceModule
}

async function loadPools(): Promise<void> {
  loading.value = true
  try {
    const response = await stockPickerApi.listPools()
    pools.value = response.items || []
    if (pools.value.length > 0) {
      const routePoolId = String(route.query.pool || '').trim()
      const targetPool = pools.value.find((item) => item.pool_id === routePoolId)
      await selectPool(targetPool?.pool_id || activePoolId.value || pools.value[0].pool_id)
    } else {
      activePoolId.value = ''
      activePool.value = null
    }
  } finally {
    loading.value = false
  }
}

async function selectPool(poolId: string): Promise<void> {
  activePoolId.value = poolId
  currentPage.value = 1
  activePool.value = await stockPickerApi.getPoolDetail(poolId)
  selectedPoolStocks.value = []
}

function handleSelectionChange(rows: StockPoolStock[]): void {
  selectedPoolStocks.value = rows
}

async function ensureMonitorTasksLoaded(): Promise<void> {
  if (monitorTasks.value.length > 0) return

  strategyTypeLoading.value = true
  try {
    monitorTasks.value = (await listStrategySceneTasks()).filter(
      (item) => item.scene_type === 'listen' && item.target_scope?.scope_type === 'custom_stock_list',
    )
    if (!selectedMonitorTaskId.value && monitorTasks.value.length > 0) {
      selectedMonitorTaskId.value = monitorTasks.value[0].task_id
    }
  } finally {
    strategyTypeLoading.value = false
  }
}

async function openBatchDialog(): Promise<void> {
  if (selectedPoolStocks.value.length === 0) {
    ElMessage.warning('请先勾选要加入监听的股票')
    return
  }

  await ensureMonitorTasksLoaded()
  batchDialogVisible.value = true
}

async function handleBatchAddStrategy(): Promise<void> {
  if (!selectedMonitorTaskId.value) {
    ElMessage.warning('请选择监听任务')
    return
  }

  batchAdding.value = true
  try {
    const results = await Promise.allSettled(
      selectedPoolStocks.value.map((item) => addStockToStrategySceneTask(selectedMonitorTaskId.value, item.ts_code)),
    )
    const successCount = results.filter((item) => item.status === 'fulfilled').length
    const failedCount = results.length - successCount
    if (successCount > 0) {
      ElMessage.success(`已加入 ${successCount} 只股票到 V2 监听任务${failedCount > 0 ? `，失败 ${failedCount} 只` : ''}`)
    } else {
      ElMessage.warning('没有股票成功加入监听任务')
    }
    batchDialogVisible.value = false
  } finally {
    batchAdding.value = false
  }
}

async function handleRemoveSelectedStocks(): Promise<void> {
  if (!activePool.value || selectedPoolStocks.value.length === 0) {
    ElMessage.warning('请先勾选要移除的股票')
    return
  }

  try {
    await ElMessageBox.confirm(
      `确认从股池“${activePool.value.name}”中移除已勾选的 ${selectedPoolStocks.value.length} 只股票吗？`,
      '移除股票确认',
      {
        type: 'warning',
        confirmButtonText: '确认移除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }

  const response = await stockPickerApi.removeStocksFromPool(
    activePool.value.pool_id,
    selectedPoolStocks.value.map((item) => item.ts_code),
  )
  ElMessage.success(response.message)
  await selectPool(activePool.value.pool_id)
  await loadPools()
}

async function handleDeletePool(): Promise<void> {
  if (!activePool.value) {
    ElMessage.warning('当前没有可删除的股池')
    return
  }

  const deletingPool = activePool.value
  try {
    await ElMessageBox.confirm(
      `确认删除股池“${deletingPool.name}”吗？删除后池内股票记录也会一并移除。`,
      '删除股池确认',
      {
        type: 'warning',
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }

  const response = await stockPickerApi.deletePool(deletingPool.pool_id)
  ElMessage.success(response.message)
  activePoolId.value = ''
  activePool.value = null
  selectedPoolStocks.value = []
  await loadPools()
}

function resetCreateForm(): void {
  createForm.name = ''
  createForm.pool_type = STOCK_POOL_TYPE_OPTIONS[0]
  createForm.description = ''
}

function openCreateDialog(): void {
  resetCreateForm()
  createDialogVisible.value = true
}

async function handleCreatePool(): Promise<void> {
  const name = createForm.name.trim()
  const poolType = createForm.pool_type.trim()
  const description = createForm.description.trim()

  if (!name) {
    ElMessage.warning('请输入股池名称')
    return
  }

  if (!poolType) {
    ElMessage.warning('请输入股池类型')
    return
  }

  creatingPool.value = true
  try {
    const pool = await stockPickerApi.createPool({
      name,
      pool_type: poolType,
      description: description || undefined,
    })
    ElMessage.success(`已创建股池 ${pool.name}`)
    createDialogVisible.value = false
    await loadPools()
    await selectPool(pool.pool_id)
  } finally {
    creatingPool.value = false
  }
}

function openPoolReview(tsCode?: string): void {
  if (!activePool.value || activePool.value.stocks.length === 0) {
    ElMessage.warning('当前股池没有可复盘的股票')
    return
  }
  const targetCode = tsCode || activePool.value.stocks[0].ts_code
  router.push({
    name: 'StockPoolSession',
    params: {
      poolId: activePool.value.pool_id,
      tsCode: targetCode,
    },
  })
}

onMounted(() => {
  loadPools()
})
</script>

<style scoped lang="scss">
.pools-page {
  display: grid;
  gap: 20px;
  padding: 1.5rem;
}

.hero-card,
.pool-list-card,
.pool-detail-card {
  border-radius: 24px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  background:
    radial-gradient(circle at top right, rgba(16, 185, 129, 0.12), transparent 30%),
    linear-gradient(145deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.98));
  box-shadow: 0 20px 60px rgba(15, 23, 42, 0.07);
}

.hero-card {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding: 28px 32px;
}

.hero-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.eyebrow {
  margin: 0 0 8px;
  color: #047857;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

h1,
h2 {
  margin: 0;
  color: #0f172a;
}

.description,
.detail-desc {
  margin: 10px 0 0;
  color: #475569;
  line-height: 1.7;
}

.body-grid {
  display: grid;
  grid-template-columns: 340px 1fr;
  gap: 20px;
}

.pool-list-card,
.pool-detail-card {
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: 24px 26px;
}

.pool-list-card header,
.detail-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.pool-groups {
  display: grid;
  gap: 18px;
}

.pool-group {
  display: grid;
  gap: 10px;
}

.pool-group-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: #475569;
  font-size: 13px;
}

.pool-item {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  text-align: left;
  padding: 14px 16px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.84);
  cursor: pointer;
}

.pool-item.active {
  border-color: rgba(16, 185, 129, 0.36);
  background: rgba(236, 253, 245, 0.95);
}

.pool-item-main {
  display: grid;
  gap: 6px;
}

.pool-item-main span,
.detail-type,
.detail-meta-row {
  color: #64748b;
  font-size: 13px;
}

.pool-item-pct {
  font-size: 14px;
  font-weight: 700;
}

.detail-side {
  display: grid;
  gap: 10px;
  justify-items: end;
}

.detail-actions,
.detail-meta-row {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}

.detail-expire-note {
  margin: 0;
  color: #0f766e;
  font-size: 12px;
  line-height: 1.5;
}

.detail-table-wrap {
  flex: 1;
  min-width: 0;
  overflow: auto;
}

.detail-pagination {
  display: flex;
  justify-content: flex-end;
  padding-top: 12px;
}

.dialog-body {
  display: grid;
  gap: 18px;
}

.batch-summary-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-radius: 12px;
  background: rgba(16, 185, 129, 0.08);
  color: #0f172a;
}

.field-block {
  display: grid;
  gap: 8px;

  label {
    font-size: 14px;
    font-weight: 600;
    color: #0f172a;
  }
}

.dialog-select {
  width: 100%;
}

.strategy-option {
  display: grid;
  gap: 4px;

  small {
    color: #64748b;
    font-size: 12px;
    line-height: 1.5;
  }
}

.batch-hint {
  margin: 0;
  color: #92400e;
  font-size: 13px;
  line-height: 1.6;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.empty-state {
  color: #64748b;
  line-height: 1.7;
}

.is-profit {
  color: #dc2626;
}

.is-loss {
  color: #059669;
}

.source-query-text {
  display: -webkit-box;
  overflow: hidden;
  text-overflow: ellipsis;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  line-height: 1.5;
  cursor: help;
}

.source-query-tooltip {
  max-width: 320px;
  white-space: pre-wrap;
  line-height: 1.7;
}

.row-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

@media (max-width: 960px) {
  .hero-card,
  .body-grid {
    grid-template-columns: 1fr;
    flex-direction: column;
  }

  .detail-header {
    flex-direction: column;
  }

  .detail-side {
    justify-items: start;
  }

  .detail-actions,
  .detail-meta-row {
    justify-content: flex-start;
  }

  .hero-actions {
    width: 100%;
  }
}
</style>
