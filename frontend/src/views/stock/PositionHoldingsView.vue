<template>
  <div class="positions-page">
    <section class="hero-card">
      <div>
        <p class="eyebrow">Positions</p>
        <h1>持仓股工作台</h1>
        <p class="description">
          基于交割单自动推导当前未卖出的持仓股票，按本地最新日线估值，并支持直接加入自选或监听。
        </p>
      </div>
      <div class="hero-actions">
        <el-button :disabled="!activeGroupId" @click="refreshPositions">重算持仓</el-button>
        <el-button :loading="loading" @click="loadGroups">刷新分组</el-button>
      </div>
    </section>

    <section class="body-grid">
      <aside class="group-list-card">
        <header>
          <h2>交割单分组</h2>
          <span>{{ groups.length }} 个</span>
        </header>
        <div v-if="groups.length === 0" class="empty-state">
          还没有交割单分组，请先到“交割单复盘”页面导入一份交割单。
        </div>
        <button
          v-for="group in groups"
          :key="group.group_id"
          type="button"
          :class="['group-item', { active: activeGroupId === group.group_id }]"
          @click="selectGroup(group.group_id)"
        >
          <strong>{{ group.name }}</strong>
          <span>{{ group.trade_record_count }} 笔成交</span>
        </button>
      </aside>

      <section class="positions-card">
        <template v-if="activeGroup && positions">
          <header class="detail-header">
            <div>
              <p class="detail-type">持仓来源分组</p>
              <h2>{{ activeGroup.name }}</h2>
              <p class="detail-desc">
                {{ activeGroup.description || '当前持仓由该交割单分组内的买卖流水自动推导得出。' }}
              </p>
            </div>
            <div class="detail-meta">
              <div class="detail-actions">
                <el-button
                  type="primary"
                  plain
                  size="small"
                  :disabled="selectedPositions.length === 0"
                  @click="addSelectedToWatchlist"
                >
                  加入自选
                </el-button>
                <el-button
                  type="primary"
                  plain
                  size="small"
                  :disabled="selectedPositions.length === 0"
                  @click="openBatchDialog"
                >
                  批量加入监听
                </el-button>
              </div>
              <span>股票持仓 {{ stockPositions.length }} 只</span>
              <span v-if="otherPositions.length > 0">另有 {{ otherPositions.length }} 只非股票资产未在此页展示</span>
              <span v-if="positions.summary.latest_valuation_date">估值日 {{ formatTradeDate(positions.summary.latest_valuation_date) }}</span>
              <span v-if="positions.summary.updated_at">更新于 {{ formatDateTime(positions.summary.updated_at) }}</span>
            </div>
          </header>

          <section class="summary-grid">
            <article class="summary-card">
              <span>持仓数量</span>
              <strong>{{ stockPositions.length }}</strong>
            </article>
            <article class="summary-card">
              <span>持仓成本</span>
              <strong>{{ formatAmount(stockSummary.total_cost) }}</strong>
            </article>
            <article class="summary-card">
              <span>持仓市值</span>
              <strong>{{ formatAmount(stockSummary.total_market_value) }}</strong>
            </article>
            <article class="summary-card" :class="getPnlClass(stockSummary.total_unrealized_pnl)">
              <span>浮盈浮亏</span>
              <strong>{{ formatSignedAmount(stockSummary.total_unrealized_pnl) }}</strong>
              <small>{{ formatSignedPct(stockSummary.total_unrealized_pnl_pct) }}</small>
            </article>
          </section>

          <div class="toolbar">
            <el-input
              v-model="keyword"
              class="toolbar-search"
              placeholder="按股票名称或代码筛选持仓"
              clearable
            />
            <span class="toolbar-meta">
              盈利 {{ profitableStockCount }} 只 · 亏损 {{ lossStockCount }} 只
            </span>
          </div>

          <el-table :data="filteredPositions" stripe @selection-change="handleSelectionChange">
            <el-table-column type="selection" width="52" />
            <el-table-column prop="code" label="代码" width="110" />
            <el-table-column prop="name" label="名称" min-width="140" />
            <el-table-column prop="quantity" label="持仓数量" width="100" />
            <el-table-column prop="avg_cost" label="持仓成本" width="110">
              <template #default="{ row }">{{ formatNumber(row.avg_cost) }}</template>
            </el-table-column>
            <el-table-column prop="latest_price" label="最新价" width="110">
              <template #default="{ row }">{{ row.latest_price ? formatNumber(row.latest_price) : '-' }}</template>
            </el-table-column>
            <el-table-column prop="market_value" label="市值" width="120">
              <template #default="{ row }">{{ formatAmount(row.market_value) }}</template>
            </el-table-column>
            <el-table-column prop="unrealized_pnl" label="浮盈亏" width="120">
              <template #default="{ row }">
                <span :class="getPnlClass(row.unrealized_pnl)">{{ formatSignedAmount(row.unrealized_pnl) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="unrealized_pnl_pct" label="盈亏比" width="110">
              <template #default="{ row }">
                <span :class="getPnlClass(row.unrealized_pnl)">{{ formatSignedPct(row.unrealized_pnl_pct) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="buy_count" label="买入笔数" width="100" />
            <el-table-column prop="sell_count" label="卖出笔数" width="100" />
            <el-table-column prop="last_trade_date" label="最后交易日" width="120">
              <template #default="{ row }">{{ row.last_trade_date ? formatTradeDate(row.last_trade_date) : '-' }}</template>
            </el-table-column>
            <el-table-column label="操作" width="140" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="viewDetail(row.ts_code)">详情</el-button>
              </template>
            </el-table-column>
          </el-table>
        </template>
        <template v-else-if="activeGroupId && positions && stockPositions.length === 0">
          <el-empty description="当前分组暂时没有股票持仓，可能已经全部卖出，或剩余的是 ETF / 基金类资产。" />
        </template>
        <template v-else>
          <el-empty description="请选择一个交割单分组查看持仓快照" />
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
          <strong>已选持仓</strong>
          <span>{{ selectedPositions.length }} 只</span>
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
        <p v-else-if="selectedStrategyType === 'fixed_stop_loss'" class="batch-hint">
          固定止损策略批量加入后，会按最新本地收盘价初始化止损基准，后续可逐只调整。
        </p>
        <p v-else-if="selectedStrategyType === 'trailing_stop_loss'" class="batch-hint">
          移动止损策略批量加入后，会按最新本地收盘价初始化入场价与最高价，后续可逐只调整。
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
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { subscriptionApi, tradeReviewApi } from '@/api'
import { useUserStore } from '@/stores/user'
import type { StrategyTypeInfo } from '@/api/types'
import type { TradeReviewGroupSummary, TradeReviewPositionItem, TradeReviewPositionResult } from '@/api/modules/trade-review'

const router = useRouter()
const userStore = useUserStore()

const loading = ref(false)
const groups = ref<TradeReviewGroupSummary[]>([])
const activeGroupId = ref('')
const positions = ref<TradeReviewPositionResult | null>(null)
const keyword = ref('')
const selectedPositions = ref<TradeReviewPositionItem[]>([])

const batchDialogVisible = ref(false)
const strategyTypes = ref<StrategyTypeInfo[]>([])
const strategyTypeLoading = ref(false)
const batchAdding = ref(false)
const selectedStrategyType = ref('')

const activeGroup = computed(() => groups.value.find((item) => item.group_id === activeGroupId.value) || null)
const stockPositions = computed(() => {
  return (positions.value?.items || []).filter((item) => item.security_type !== 'other')
})
const otherPositions = computed(() => {
  return (positions.value?.items || []).filter((item) => item.security_type === 'other')
})
const profitableStockCount = computed(() => stockPositions.value.filter((item) => Number(item.unrealized_pnl || 0) > 0).length)
const lossStockCount = computed(() => stockPositions.value.filter((item) => Number(item.unrealized_pnl || 0) < 0).length)
const stockSummary = computed(() => {
  const totalCost = stockPositions.value.reduce((sum, item) => sum + Number(item.total_cost || 0), 0)
  const totalMarketValue = stockPositions.value.reduce((sum, item) => sum + Number(item.market_value || 0), 0)
  const totalUnrealizedPnl = totalMarketValue - totalCost
  return {
    total_cost: totalCost,
    total_market_value: totalMarketValue,
    total_unrealized_pnl: totalUnrealizedPnl,
    total_unrealized_pnl_pct: totalCost > 0 ? totalUnrealizedPnl / totalCost * 100 : 0,
  }
})
const filteredPositions = computed(() => {
  const items = stockPositions.value
  const text = keyword.value.trim().toLowerCase()
  if (!text) return items
  return items.filter((item) => {
    return item.ts_code.toLowerCase().includes(text)
      || item.code.toLowerCase().includes(text)
      || (item.name || '').toLowerCase().includes(text)
  })
})

function formatTradeDate(value?: string | null): string {
  if (!value) return '-'
  return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`
}

function formatDateTime(value?: string | null): string {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function formatNumber(value: number): string {
  return Number(value || 0).toFixed(2)
}

function formatAmount(value: number): string {
  const amount = Number(value || 0)
  return amount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatSignedAmount(value: number): string {
  const amount = Number(value || 0)
  const prefix = amount > 0 ? '+' : ''
  return `${prefix}${formatAmount(amount)}`
}

function formatSignedPct(value: number): string {
  const amount = Number(value || 0)
  const prefix = amount > 0 ? '+' : ''
  return `${prefix}${amount.toFixed(2)}%`
}

function getPnlClass(value: number): string {
  if (value > 0) return 'up'
  if (value < 0) return 'down'
  return 'flat'
}

async function loadGroups(): Promise<void> {
  loading.value = true
  try {
    const response = await tradeReviewApi.listGroups()
    groups.value = response.items || []
    if (groups.value.length > 0) {
      await selectGroup(activeGroupId.value || groups.value[0].group_id)
    } else {
      activeGroupId.value = ''
      positions.value = null
    }
  } finally {
    loading.value = false
  }
}

async function selectGroup(groupId: string): Promise<void> {
  activeGroupId.value = groupId
  selectedPositions.value = []
  positions.value = await tradeReviewApi.getPositions(groupId, true)
}

async function refreshPositions(): Promise<void> {
  if (!activeGroupId.value) return
  positions.value = await tradeReviewApi.rebuildPositions(activeGroupId.value)
  selectedPositions.value = []
  ElMessage.success('持仓快照已重算')
}

function handleSelectionChange(rows: TradeReviewPositionItem[]): void {
  selectedPositions.value = rows
}

function viewDetail(tsCode: string): void {
  router.push(`/stock/${tsCode}`)
}

async function addSelectedToWatchlist(): Promise<void> {
  if (selectedPositions.value.length === 0) return
  let added = 0
  for (const item of selectedPositions.value) {
    if (userStore.watchlist.includes(item.ts_code)) continue
    const success = await userStore.addToWatchlist(item.ts_code)
    if (success) added += 1
  }
  ElMessage.success(added > 0 ? `已加入 ${added} 只持仓到自选股` : '选中的持仓已在自选股中')
}

async function loadStrategyTypes(): Promise<void> {
  if (strategyTypes.value.length > 0) return
  strategyTypeLoading.value = true
  try {
    strategyTypes.value = await subscriptionApi.getStrategyTypes()
  } finally {
    strategyTypeLoading.value = false
  }
}

async function openBatchDialog(): Promise<void> {
  if (selectedPositions.value.length === 0) {
    ElMessage.warning('请先选择至少一只持仓股')
    return
  }
  await loadStrategyTypes()
  selectedStrategyType.value = ''
  batchDialogVisible.value = true
}

async function handleBatchAddStrategy(): Promise<void> {
  if (!selectedStrategyType.value || selectedPositions.value.length === 0) return
  batchAdding.value = true
  try {
    const tsCodes = selectedPositions.value.map((item) => item.ts_code)
    const result = await subscriptionApi.batchAddStocksToStrategy(selectedStrategyType.value, tsCodes)
    batchDialogVisible.value = false
    ElMessage.success(result.message || `已处理 ${tsCodes.length} 只持仓股`)
  } finally {
    batchAdding.value = false
  }
}

onMounted(() => {
  loadGroups()
})
</script>

<style scoped lang="scss">
.positions-page {
  display: flex;
  padding: 1.5rem;
  flex-direction: column;
  gap: 20px;
}

.hero-card,
.group-list-card,
.positions-card {
  background: var(--el-bg-color);
  border-radius: 20px;
  border: 1px solid rgba(15, 23, 42, 0.08);
}

.hero-card {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding: 24px;
}

.eyebrow {
  margin: 0;
  font-size: 12px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--el-color-primary);
}

.hero-card h1,
.detail-header h2 {
  margin: 6px 0 10px;
}

.description,
.detail-desc {
  margin: 0;
  color: var(--el-text-color-secondary);
  line-height: 1.7;
}

.hero-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.body-grid {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 20px;
  min-width: 0;
}

.group-list-card {
  padding: 20px;
}

.group-list-card header,
.detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.group-list-card header h2 {
  margin: 0;
}

.empty-state {
  padding: 18px 0;
  color: var(--el-text-color-secondary);
  line-height: 1.7;
}

.group-item {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  margin-top: 12px;
  padding: 14px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 16px;
  background: transparent;
  cursor: pointer;
  text-align: left;
}

.group-item.active {
  border-color: rgba(59, 130, 246, 0.28);
  background: rgba(59, 130, 246, 0.06);
}

.group-item span,
.detail-type,
.detail-meta,
.toolbar-meta {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.positions-card {
  padding: 20px;
  min-width: 0;
}

.detail-meta {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.detail-actions {
  display: inline-flex;
  gap: 8px;
  flex-wrap: wrap;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  margin: 18px 0;
}

.summary-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 18px;
  border-radius: 18px;
  background: rgba(15, 23, 42, 0.03);
}

.summary-card strong {
  font-size: 24px;
}

.summary-card small {
  color: var(--el-text-color-secondary);
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.toolbar-search {
  width: min(320px, 100%);
}

.up {
  color: #dc2626;
}

.down {
  color: #059669;
}

.flat {
  color: var(--el-text-color-primary);
}

.dialog-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.batch-summary-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-radius: 14px;
  background: rgba(59, 130, 246, 0.08);
}

.field-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.field-block label {
  font-weight: 600;
}

.dialog-select {
  width: 100%;
}

.strategy-option {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.strategy-option small,
.batch-hint {
  color: var(--el-text-color-secondary);
}

@media (max-width: 1200px) {
  .body-grid,
  .summary-grid {
    grid-template-columns: 1fr;
  }
}
</style>
