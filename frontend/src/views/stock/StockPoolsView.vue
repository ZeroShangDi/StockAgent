<template>
  <div class="pools-page">
    <section class="hero-card">
      <div>
        <p class="eyebrow">Stock Pools</p>
        <h1>股池工作台</h1>
        <p class="description">
          查看一句话选股、自定义观察等来源沉淀下来的本地股池，并快速浏览池内股票与来源线索。
        </p>
      </div>
      <el-button :loading="loading" @click="loadPools">刷新股池</el-button>
    </section>

    <section class="body-grid">
      <aside class="pool-list-card">
        <header>
          <h2>我的股池</h2>
          <span>{{ pools.length }} 个</span>
        </header>
        <div v-if="pools.length === 0" class="empty-state">
          还没有股池，可以先去“一句话选股”里把结果加入某个池。
        </div>
        <button
          v-for="pool in pools"
          :key="pool.pool_id"
          type="button"
          :class="['pool-item', { active: activePoolId === pool.pool_id }]"
          @click="selectPool(pool.pool_id)"
        >
          <strong>{{ pool.name }}</strong>
          <span>{{ pool.pool_type }} · {{ pool.stock_count }} 只</span>
        </button>
      </aside>

      <section class="pool-detail-card">
        <template v-if="activePool">
          <header class="detail-header">
            <div>
              <p class="detail-type">{{ activePool.pool_type }}</p>
              <h2>{{ activePool.name }}</h2>
              <p class="detail-desc">{{ activePool.description || '暂无备注' }}</p>
            </div>
            <div class="detail-meta">
              <div class="detail-actions">
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
              <span>股票数 {{ activePool.stock_count }}</span>
              <span v-if="selectedPoolStocks.length > 0">已勾选 {{ selectedPoolStocks.length }} 只</span>
              <span v-if="activePool.updated_at">更新于 {{ formatDateTime(activePool.updated_at) }}</span>
            </div>
          </header>

          <el-table :data="activePool.stocks" stripe @selection-change="handleSelectionChange">
            <el-table-column type="selection" width="52" />
            <el-table-column prop="code" label="代码" width="120" />
            <el-table-column prop="ts_code" label="TS 代码" width="150" />
            <el-table-column prop="name" label="名称" width="140" />
            <el-table-column prop="status" label="状态" width="100" />
            <el-table-column prop="source_module" label="来源模块" width="140" />
            <el-table-column prop="source_query" label="来源条件" min-width="260" show-overflow-tooltip />
            <el-table-column prop="added_at" label="加入时间" width="180">
              <template #default="{ row }">{{ row.added_at ? formatDateTime(row.added_at) : '-' }}</template>
            </el-table-column>
          </el-table>
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
          <label>监听策略</label>
          <el-select
            v-model="selectedStrategyType"
            class="dialog-select"
            placeholder="请选择策略"
            :loading="strategyTypeLoading"
          >
            <el-option
              v-for="item in strategyTypes"
              :key="item.type"
              :label="item.name"
              :value="item.type"
            >
              <div class="strategy-option">
                <span>{{ item.name }}</span>
                <small>{{ item.description }}</small>
              </div>
            </el-option>
          </el-select>
        </div>

        <p v-if="selectedStrategyType === 'support_resistance'" class="batch-hint">
          撑压线策略批量加入后，还需要到市场监听页面逐只补充点位配置。
        </p>
      </div>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="batchDialogVisible = false">取消</el-button>
          <el-button
            type="primary"
            :loading="batchAdding"
            :disabled="!selectedStrategyType"
            @click="handleBatchAddStrategy"
          >
            确认加入
          </el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { stockPickerApi, subscriptionApi } from '@/api'
import type { StockPoolDetail, StockPoolSummary } from '@/api/modules/stock-picker'
import type { StockPoolStock } from '@/api/modules/stock-picker'
import type { StrategyTypeInfo } from '@/api/types'

const loading = ref(false)
const pools = ref<StockPoolSummary[]>([])
const activePoolId = ref('')
const activePool = ref<StockPoolDetail | null>(null)
const selectedPoolStocks = ref<StockPoolStock[]>([])
const batchDialogVisible = ref(false)
const strategyTypes = ref<StrategyTypeInfo[]>([])
const strategyTypeLoading = ref(false)
const batchAdding = ref(false)
const selectedStrategyType = ref('')

function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

async function loadPools(): Promise<void> {
  loading.value = true
  try {
    const response = await stockPickerApi.listPools()
    pools.value = response.items || []
    if (pools.value.length > 0) {
      await selectPool(activePoolId.value || pools.value[0].pool_id)
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
  activePool.value = await stockPickerApi.getPoolDetail(poolId)
  selectedPoolStocks.value = []
}

function handleSelectionChange(rows: StockPoolStock[]): void {
  selectedPoolStocks.value = rows
}

async function ensureStrategyTypesLoaded(): Promise<void> {
  if (strategyTypes.value.length > 0) return

  strategyTypeLoading.value = true
  try {
    strategyTypes.value = await subscriptionApi.getStrategyTypes()
    if (!selectedStrategyType.value && strategyTypes.value.length > 0) {
      selectedStrategyType.value = strategyTypes.value[0].type
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

  await ensureStrategyTypesLoaded()
  batchDialogVisible.value = true
}

async function handleBatchAddStrategy(): Promise<void> {
  if (!selectedStrategyType.value) {
    ElMessage.warning('请选择监听策略')
    return
  }

  batchAdding.value = true
  try {
    const response = await subscriptionApi.batchAddStocksToStrategy(
      selectedStrategyType.value,
      selectedPoolStocks.value.map((item) => item.ts_code),
    )
    if (response.added.length > 0) {
      ElMessage.success(response.message)
    } else {
      ElMessage.warning(response.message)
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

loadPools()
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
  grid-template-columns: 320px 1fr;
  gap: 20px;
}

.pool-list-card,
.pool-detail-card {
  padding: 24px 26px;
}

.pool-list-card header,
.detail-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.pool-item {
  width: 100%;
  display: grid;
  gap: 6px;
  text-align: left;
  padding: 14px 16px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.84);
  cursor: pointer;
  margin-top: 12px;
}

.pool-item.active {
  border-color: rgba(16, 185, 129, 0.36);
  background: rgba(236, 253, 245, 0.95);
}

.pool-item span,
.detail-type,
.detail-meta {
  color: #64748b;
  font-size: 13px;
}

.detail-meta {
  display: grid;
  gap: 6px;
  text-align: right;
}

.detail-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
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

@media (max-width: 960px) {
  .hero-card,
  .detail-header,
  .body-grid {
    grid-template-columns: 1fr;
    flex-direction: column;
  }

  .detail-meta {
    text-align: left;
  }

  .detail-actions {
    justify-content: flex-start;
  }
}
</style>
