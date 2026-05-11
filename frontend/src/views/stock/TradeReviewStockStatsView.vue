<template>
  <div class="trade-review-stock-stats-page" v-loading="loading">
    <section class="hero-card">
      <div>
        <p class="eyebrow">Trade Review</p>
        <h1>股票盈亏汇总</h1>
        <p class="description">
          {{ groupName || '当前交割单分组' }} 的股票级盈亏汇总。排序仅作用于当前页，便于快速横向比对本页股票。
        </p>
      </div>
      <div class="hero-actions">
        <el-button @click="backToTradeReview">返回交割单复盘</el-button>
        <el-button :loading="loading" @click="loadPage">刷新</el-button>
      </div>
    </section>

    <section class="summary-grid" v-if="stats">
      <article class="summary-card">
        <span>股票数量</span>
        <strong>{{ stats.stock_pnl_ranking.length }}</strong>
      </article>
      <article class="summary-card">
        <span>已实现盈亏</span>
        <strong :class="getPnlClass(summaryRealizedPnl)">{{ formatAmount(summaryRealizedPnl) }}</strong>
      </article>
      <article class="summary-card">
        <span>浮动盈亏</span>
        <strong :class="getPnlClass(summaryUnrealizedPnl)">{{ formatAmount(summaryUnrealizedPnl) }}</strong>
      </article>
      <article class="summary-card">
        <span>总盈亏</span>
        <strong :class="getPnlClass(summaryNetPnl)">{{ formatAmount(summaryNetPnl) }}</strong>
      </article>
    </section>

    <section class="table-card">
      <header class="table-header">
        <div>
          <h2>本页股票排行</h2>
          <p>当前第 {{ currentPage }} 页，共 {{ totalPages }} 页，每页 {{ pageSize }} 只。</p>
        </div>
      </header>

      <el-table
        :data="sortedPageItems"
        stripe
        class="stock-pnl-table"
        @sort-change="handleSortChange"
      >
        <el-table-column label="股票" min-width="170">
          <template #default="{ row }">
            <div class="stock-name-cell">
              <strong>{{ row.name || row.code }}</strong>
              <span>{{ row.ts_code }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="trade_count" label="成交笔数" width="96" sortable="custom" />
        <el-table-column prop="position_quantity" label="剩余持仓" width="96" sortable="custom" />
        <el-table-column prop="realized_pnl" label="已实现盈亏" min-width="130" sortable="custom">
          <template #default="{ row }">
            <span :class="getPnlClass(row.realized_pnl)">{{ formatAmount(row.realized_pnl) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="unrealized_pnl" label="浮动盈亏" min-width="130" sortable="custom">
          <template #default="{ row }">
            <span :class="getPnlClass(row.unrealized_pnl)">{{ formatAmount(row.unrealized_pnl) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="net_pnl" label="总盈亏" min-width="130" sortable="custom">
          <template #default="{ row }">
            <span :class="getPnlClass(row.net_pnl)">{{ formatAmount(row.net_pnl) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="net_pnl_pct" label="收益率" min-width="110" sortable="custom">
          <template #default="{ row }">
            <span :class="getPnlClass(row.net_pnl_pct)">{{ formatPercent(row.net_pnl_pct) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="latest_price" label="最新价" width="100" sortable="custom">
          <template #default="{ row }">{{ formatNumber(row.latest_price) }}</template>
        </el-table-column>
        <el-table-column prop="last_trade_date" label="最后交易日" width="110" sortable="custom">
          <template #default="{ row }">{{ formatTradeDate(row.last_trade_date) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openStockDetail(row.code)">
              打开详情
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-wrap" v-if="stats">
        <el-pagination
          background
          layout="total, sizes, prev, pager, next, jumper"
          :total="stats.stock_pnl_ranking.length"
          :current-page="currentPage"
          :page-size="pageSize"
          :page-sizes="[20, 50, 100, 200]"
          @current-change="handlePageChange"
          @size-change="handlePageSizeChange"
        />
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { tradeReviewApi } from '@/api'
import type { TradeReviewStatsResult } from '@/api/modules/trade-review'

type StockPnlItem = TradeReviewStatsResult['stock_pnl_ranking'][number]
type SortOrder = 'ascending' | 'descending' | null

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const stats = ref<TradeReviewStatsResult | null>(null)
const groupName = ref(typeof route.query.groupName === 'string' ? route.query.groupName : '')
const currentPage = ref(1)
const pageSize = ref(50)
const sortProp = ref<keyof StockPnlItem | ''>('net_pnl')
const sortOrder = ref<SortOrder>('descending')

const groupId = computed(() => String(route.params.groupId || ''))
const totalPages = computed(() => {
  const total = stats.value?.stock_pnl_ranking.length || 0
  return Math.max(1, Math.ceil(total / pageSize.value))
})

const pagedItems = computed<StockPnlItem[]>(() => {
  const items = stats.value?.stock_pnl_ranking || []
  const start = (currentPage.value - 1) * pageSize.value
  return items.slice(start, start + pageSize.value)
})

const sortedPageItems = computed<StockPnlItem[]>(() => {
  const items = [...pagedItems.value]
  const prop = sortProp.value
  const order = sortOrder.value
  if (!prop || !order) return items

  return items.sort((left, right) => {
    const a = left[prop]
    const b = right[prop]
    const normalizedA = typeof a === 'string' ? a : Number(a ?? 0)
    const normalizedB = typeof b === 'string' ? b : Number(b ?? 0)

    if (typeof normalizedA === 'string' || typeof normalizedB === 'string') {
      const compare = String(normalizedA ?? '').localeCompare(String(normalizedB ?? ''), 'zh-CN')
      return order === 'ascending' ? compare : -compare
    }

    const compare = normalizedA - normalizedB
    return order === 'ascending' ? compare : -compare
  })
})

const summaryRealizedPnl = computed(() =>
  (stats.value?.stock_pnl_ranking || []).reduce((total, item) => total + Number(item.realized_pnl || 0), 0),
)
const summaryUnrealizedPnl = computed(() =>
  (stats.value?.stock_pnl_ranking || []).reduce((total, item) => total + Number(item.unrealized_pnl || 0), 0),
)
const summaryNetPnl = computed(() =>
  (stats.value?.stock_pnl_ranking || []).reduce((total, item) => total + Number(item.net_pnl || 0), 0),
)

async function loadPage(): Promise<void> {
  if (!groupId.value) return
  loading.value = true
  try {
    stats.value = await tradeReviewApi.getStats(groupId.value)
  } catch {
    stats.value = null
    ElMessage.error('加载股票盈亏汇总失败')
  } finally {
    loading.value = false
  }
}

function backToTradeReview(): void {
  router.push({
    name: 'TradeReview',
    query: {
      groupId: groupId.value,
    },
  })
}

function openStockDetail(code?: string | null): void {
  if (!code) return
  router.push({
    name: 'StockDetail',
    params: { code },
  })
}

function handlePageChange(page: number): void {
  currentPage.value = page
}

function handlePageSizeChange(size: number): void {
  pageSize.value = size
  currentPage.value = 1
}

function handleSortChange(payload: { prop: string; order: SortOrder }): void {
  sortProp.value = (payload.prop || '') as keyof StockPnlItem | ''
  sortOrder.value = payload.order
}

function formatTradeDate(value?: string | null): string {
  if (!value || value.length !== 8) return value || '-'
  return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`
}

function formatNumber(value?: number | null): string {
  if (value == null || Number.isNaN(Number(value))) return '--'
  return Number(value).toFixed(2)
}

function formatAmount(value?: number | null): string {
  const amount = Number(value || 0)
  return amount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatPercent(value?: number | null): string {
  if (value == null || Number.isNaN(Number(value))) return '--'
  const numeric = Number(value)
  return `${numeric > 0 ? '+' : ''}${numeric.toFixed(2)}%`
}

function getPnlClass(value?: number | null): string {
  if (value == null || Number.isNaN(Number(value))) return ''
  if (Number(value) > 0) return 'is-profit'
  if (Number(value) < 0) return 'is-loss'
  return ''
}

onMounted(() => {
  loadPage()
})
</script>

<style scoped lang="scss">
.trade-review-stock-stats-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 1.5rem;
}

.hero-card,
.table-card {
  background: var(--el-bg-color);
  border-radius: 20px;
  border: 1px solid rgba(15, 23, 42, 0.08);
}

.hero-card {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding: 24px;
}

.eyebrow {
  margin: 0 0 6px;
  font-size: 12px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--el-color-primary);
}

.hero-card h1,
.table-header h2 {
  margin: 0;
}

.description,
.table-header p {
  margin: 8px 0 0;
  color: var(--el-text-color-secondary);
  line-height: 1.7;
}

.hero-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 16px;
}

.summary-card {
  padding: 18px 20px;
  border-radius: 18px;
  background: var(--el-bg-color);
  border: 1px solid rgba(15, 23, 42, 0.08);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.summary-card span {
  color: var(--el-text-color-secondary);
}

.summary-card strong {
  font-size: 22px;
}

.table-card {
  padding: 20px;
}

.table-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.stock-name-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stock-name-cell span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.is-profit {
  color: #dc2626;
}

.is-loss {
  color: #059669;
}

.pagination-wrap {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}

@media (max-width: 960px) {
  .hero-card {
    flex-direction: column;
  }
}
</style>
