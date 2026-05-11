<template>
  <div class="trade-review-page">
    <section class="hero-card">
      <div>
        <p class="eyebrow">Trade Review</p>
        <h1>交割单复盘</h1>
        <p class="description">
          先按分组管理交割单，再按时间顺序逐笔进入沉浸式复盘。统计口径当前由后端基于分组全量数据计算，后续会继续细化。
        </p>
      </div>
      <div class="hero-actions">
        <el-button type="primary" @click="openCreateDialog">新建分组</el-button>
        <el-button :disabled="!activeGroupId" @click="openImportDialog">导入 CSV</el-button>
        <el-button :loading="loading" @click="loadGroups">刷新</el-button>
      </div>
    </section>

    <section class="body-grid">
      <aside class="group-list-card">
        <header>
          <h2>交割单分组</h2>
          <span>{{ groups.length }} 个</span>
        </header>
        <div v-if="groups.length === 0" class="empty-state">
          还没有交割单分组，可以先创建一个，例如“我的交割单”或“XX大神交割单”。
        </div>
        <button
          v-for="group in groups"
          :key="group.group_id"
          type="button"
          :class="['group-item', { active: activeGroupId === group.group_id }]"
          @click="selectGroup(group.group_id)"
        >
          <strong>{{ group.name }}</strong>
          <span>{{ group.trade_record_count }} 笔成交 · {{ group.record_count }} 条记录</span>
        </button>
      </aside>

      <section class="main-card">
        <template v-if="activeGroup">
          <header class="detail-header">
            <div>
              <p class="detail-type">交割单分组</p>
              <h2>{{ activeGroup.name }}</h2>
              <p class="detail-desc">{{ activeGroup.description || '暂无说明' }}</p>
            </div>
            <div class="detail-meta">
              <span>总记录 {{ activeGroup.record_count }}</span>
              <span>成交记录 {{ activeGroup.trade_record_count }}</span>
              <span v-if="activeGroup.last_imported_at">最近导入 {{ formatDateTime(activeGroup.last_imported_at) }}</span>
            </div>
          </header>

          <el-tabs v-model="activeTab">
            <el-tab-pane label="逐笔复盘" name="records">
              <div class="toolbar">
                <el-select v-model="category" class="toolbar-select" @change="handleFilterChange">
                  <el-option
                    v-for="option in categoryOptions"
                    :key="option.value"
                    :label="option.label"
                    :value="option.value"
                  />
                </el-select>
                <el-input
                  v-model="keyword"
                  class="toolbar-search"
                  placeholder="按股票、代码、业务类型搜索"
                  clearable
                  @keyup.enter="handleFilterChange"
                  @clear="handleFilterChange"
                />
                <el-button @click="handleFilterChange">查询</el-button>
                <span class="toolbar-meta">
                  共 {{ records.total }} 条 · 当前第 {{ currentPage }} / {{ totalPages }} 页
                </span>
              </div>

              <el-table :data="records.items" stripe class="records-table">
                <el-table-column prop="trade_date" label="日期" width="110">
                  <template #default="{ row }">{{ formatTradeDate(row.trade_date) }}</template>
                </el-table-column>
                <el-table-column prop="business_type" label="业务类型" width="120" />
                <el-table-column prop="security_name" label="证券名称" min-width="140" />
                <el-table-column prop="code" label="代码" width="100" />
                <el-table-column prop="side" label="方向" width="80">
                  <template #default="{ row }">
                    <el-tag
                      v-if="row.side"
                      :type="row.side === 'buy' ? 'danger' : 'success'"
                      effect="plain"
                      round
                      size="small"
                    >
                      {{ row.side === 'buy' ? '买入' : '卖出' }}
                    </el-tag>
                    <span v-else>-</span>
                  </template>
                </el-table-column>
                <el-table-column prop="quantity" label="数量" width="100" />
                <el-table-column prop="price" label="均价" width="100">
                  <template #default="{ row }">{{ formatNumber(row.price) }}</template>
                </el-table-column>
                <el-table-column prop="amount" label="发生金额" width="120">
                  <template #default="{ row }">{{ formatAmount(row.amount) }}</template>
                </el-table-column>
                <el-table-column prop="reviewed" label="复盘状态" width="110">
                  <template #default="{ row }">
                    <el-tag :type="row.reviewed ? 'success' : 'info'" effect="plain" round size="small">
                      {{ row.reviewed ? '已补充' : '未补充' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="150" fixed="right">
                  <template #default="{ row }">
                    <el-button link type="primary" @click="openReviewSession(row)">
                      进入复盘
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>

              <div class="pagination-wrap">
                <el-pagination
                  background
                  layout="total, sizes, prev, pager, next, jumper"
                  :total="records.total"
                  :current-page="currentPage"
                  :page-size="pageSize"
                  :page-sizes="[50, 100, 200, 500]"
                  @current-change="handlePageChange"
                  @size-change="handlePageSizeChange"
                />
              </div>
            </el-tab-pane>

            <el-tab-pane label="统计总览" name="stats">
              <div v-if="stats" class="stats-panel">
                <div class="stats-note">
                  当前统计由后端基于分组内全量数据聚合，不受当前表格分页影响。更细维度的交割单分析已记录到待办，后续会继续扩展。
                </div>
                <section class="summary-grid">
                  <article class="summary-card">
                    <span>总记录</span>
                    <strong>{{ stats.summary.total_records }}</strong>
                  </article>
                  <article class="summary-card">
                    <span>成交记录</span>
                    <strong>{{ stats.summary.trade_records }}</strong>
                  </article>
                  <article class="summary-card">
                    <span>复盘覆盖率</span>
                    <strong>{{ stats.summary.review_coverage_pct }}%</strong>
                  </article>
                  <article class="summary-card">
                    <span>总手续费</span>
                    <strong>{{ formatAmount(stats.summary.total_fee) }}</strong>
                  </article>
                </section>

                <section class="stats-grid">
                  <article class="stats-card">
                    <h3>交易概览</h3>
                    <ul class="stats-list">
                      <li>买入笔数：{{ stats.summary.buy_count }}</li>
                      <li>卖出笔数：{{ stats.summary.sell_count }}</li>
                      <li>买入总额：{{ formatAmount(stats.summary.total_buy_amount) }}</li>
                      <li>卖出总额：{{ formatAmount(stats.summary.total_sell_amount) }}</li>
                      <li>净现金流：{{ formatAmount(stats.summary.net_cash_flow) }}</li>
                    </ul>
                  </article>

                  <article class="stats-card">
                    <h3>业务类型</h3>
                    <ul class="stats-list">
                      <li v-for="item in stats.business_type_counts.slice(0, 8)" :key="item.name">
                        {{ item.name }}：{{ item.count }}
                      </li>
                    </ul>
                  </article>

                  <article class="stats-card">
                    <h3>高频交易标的</h3>
                    <ul class="stats-list">
                      <li v-for="item in stats.top_stocks.slice(0, 8)" :key="item.name">
                        {{ item.name }}：{{ item.count }}
                      </li>
                    </ul>
                  </article>

                  <article class="stats-card">
                    <h3>成功原因标签</h3>
                    <ul class="stats-list">
                      <li v-for="item in stats.reason_counts.success.slice(0, 8)" :key="`s-${item.name}`">
                        {{ item.name }}：{{ item.count }}
                      </li>
                      <li v-if="stats.reason_counts.success.length === 0">还没有成功原因统计</li>
                    </ul>
                  </article>

                  <article class="stats-card">
                    <h3>失败原因标签</h3>
                    <ul class="stats-list">
                      <li v-for="item in stats.reason_counts.failure.slice(0, 8)" :key="`f-${item.name}`">
                        {{ item.name }}：{{ item.count }}
                      </li>
                      <li v-if="stats.reason_counts.failure.length === 0">还没有失败原因统计</li>
                    </ul>
                  </article>

                  <article class="stats-card">
                    <h3>按月成交笔数</h3>
                    <ul class="stats-list">
                      <li v-for="item in stats.monthly_trade_counts.slice(-8)" :key="item.month">
                        {{ formatMonth(item.month) }}：{{ item.count }}
                      </li>
                    </ul>
                  </article>
                </section>

              </div>
              <el-empty v-else description="暂无统计数据" />
            </el-tab-pane>

            <el-tab-pane label="按股汇总" name="stocks">
              <div v-if="stats" class="stock-pnl-section">
                <div class="stock-pnl-header">
                  <div>
                    <h3>按股票统计盈亏</h3>
                    <p>排序只作用于当前页，打开详情会直接进入这只股票的沉浸式复盘。</p>
                  </div>
                  <span>当前第 {{ stockPage }} / {{ stockTotalPages }} 页</span>
                </div>

                <el-table
                  :data="sortedPagedStockRanking"
                  stripe
                  class="stock-pnl-table"
                  @sort-change="handleStockSortChange"
                >
                  <el-table-column label="股票" min-width="180">
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
                      <span :class="pnlClass(row.realized_pnl)">{{ formatAmount(row.realized_pnl) }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column prop="unrealized_pnl" label="浮动盈亏" min-width="130" sortable="custom">
                    <template #default="{ row }">
                      <span :class="pnlClass(row.unrealized_pnl)">{{ formatAmount(row.unrealized_pnl) }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column prop="net_pnl" label="总盈亏" min-width="130" sortable="custom">
                    <template #default="{ row }">
                      <span :class="pnlClass(row.net_pnl)">{{ formatAmount(row.net_pnl) }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column prop="net_pnl_pct" label="收益率" min-width="110" sortable="custom">
                    <template #default="{ row }">
                      <span :class="pnlClass(row.net_pnl_pct)">{{ formatPercent(row.net_pnl_pct) }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column prop="latest_price" label="最新价" width="100" sortable="custom">
                    <template #default="{ row }">{{ formatNumber(row.latest_price || 0) }}</template>
                  </el-table-column>
                  <el-table-column prop="last_trade_date" label="最后交易日" width="110" sortable="custom">
                    <template #default="{ row }">{{ formatTradeDate(row.last_trade_date || '') }}</template>
                  </el-table-column>
                  <el-table-column label="操作" width="130" fixed="right">
                    <template #default="{ row }">
                      <el-button link type="primary" @click="openStockSummaryReview(row)">
                        深度复盘
                      </el-button>
                    </template>
                  </el-table-column>
                </el-table>

                <div class="pagination-wrap">
                  <el-pagination
                    background
                    layout="total, sizes, prev, pager, next, jumper"
                    :total="stats.stock_pnl_ranking.length"
                    :current-page="stockPage"
                    :page-size="stockPageSize"
                    :page-sizes="[20, 50, 100, 200]"
                    @current-change="handleStockPageChange"
                    @size-change="handleStockPageSizeChange"
                  />
                </div>
              </div>
              <el-empty v-else description="暂无股票汇总数据" />
            </el-tab-pane>
          </el-tabs>
        </template>
        <template v-else>
          <el-empty description="请选择交割单分组" />
        </template>
      </section>
    </section>

    <el-dialog v-model="createDialogVisible" title="新建交割单分组" width="480px">
      <div class="dialog-body">
        <div class="field-block">
          <label>分组名称</label>
          <el-input v-model="createForm.name" maxlength="80" placeholder="例如：我的交割单 / XX大神交割单" />
        </div>
        <div class="field-block">
          <label>分组说明</label>
          <el-input
            v-model="createForm.description"
            type="textarea"
            :rows="3"
            maxlength="200"
            show-word-limit
            placeholder="可选，记录这组交割单的来源或用途"
          />
        </div>
      </div>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="creatingGroup" @click="handleCreateGroup">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="importDialogVisible" title="导入交割单 CSV" width="500px">
      <div class="dialog-body">
        <div class="batch-summary-card">
          <strong>当前分组</strong>
          <span>{{ activeGroup?.name || '-' }}</span>
        </div>
        <div class="field-block">
          <label>选择 CSV 文件</label>
          <input ref="fileInputRef" class="file-input" type="file" accept=".csv,text/csv" @change="handleFileSelected" />
          <p v-if="selectedImportFile" class="file-name">{{ selectedImportFile.name }}</p>
          <p class="field-tip">支持重复导入，系统会按业务唯一键自动去重，已存在记录会跳过。</p>
        </div>
      </div>
      <template #footer>
        <el-button @click="closeImportDialog">取消</el-button>
        <el-button type="primary" :loading="importing" :disabled="!selectedImportFile" @click="handleImportCsv">
          开始导入
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { tradeReviewApi } from '@/api'
import type {
  TradeReviewGroupSummary,
  TradeReviewRecord,
  TradeReviewRecordListResult,
  TradeReviewStatsResult,
} from '@/api/modules/trade-review'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const groups = ref<TradeReviewGroupSummary[]>([])
const activeGroupId = ref('')
const activeTab = ref<'records' | 'stats' | 'stocks'>('records')
const category = ref('trade')
const keyword = ref('')
const pageSize = ref(100)
const currentPage = ref(1)
const records = ref<TradeReviewRecordListResult>({ items: [], total: 0, skip: 0, limit: 100 })
const stats = ref<TradeReviewStatsResult | null>(null)
const stockPage = ref(1)
const stockPageSize = ref(50)
const stockSortProp = ref<keyof TradeReviewStatsResult['stock_pnl_ranking'][number] | ''>('net_pnl')
const stockSortOrder = ref<'ascending' | 'descending' | null>('descending')

const createDialogVisible = ref(false)
const creatingGroup = ref(false)
const createForm = reactive({
  name: '',
  description: '',
})

const importDialogVisible = ref(false)
const importing = ref(false)
const selectedImportFile = ref<File | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)

const activeGroup = computed(() => groups.value.find((item) => item.group_id === activeGroupId.value) || null)
const totalPages = computed(() => Math.max(1, Math.ceil((records.value.total || 0) / pageSize.value)))
const stockTotalPages = computed(() => {
  const total = stats.value?.stock_pnl_ranking.length || 0
  return Math.max(1, Math.ceil(total / stockPageSize.value))
})
const pagedStockRanking = computed(() => {
  const items = stats.value?.stock_pnl_ranking || []
  const start = (stockPage.value - 1) * stockPageSize.value
  return items.slice(start, start + stockPageSize.value)
})
const sortedPagedStockRanking = computed(() => {
  const items = [...pagedStockRanking.value]
  const prop = stockSortProp.value
  const order = stockSortOrder.value
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

const categoryOptions = [
  { label: '成交记录', value: 'trade' },
  { label: '资金流水', value: 'cash' },
  { label: '收益入账', value: 'income' },
  { label: '申购相关', value: 'subscription' },
  { label: '回购相关', value: 'repo' },
  { label: '其他记录', value: 'other' },
  { label: '全部记录', value: 'all' },
]

function formatTradeDate(value: string): string {
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

function formatMonth(value: string): string {
  if (!value || value.length !== 6) return value
  return `${value.slice(0, 4)}-${value.slice(4, 6)}`
}

function formatPercent(value?: number | null): string {
  if (value == null || Number.isNaN(Number(value))) return '--'
  const numeric = Number(value)
  return `${numeric > 0 ? '+' : ''}${numeric.toFixed(2)}%`
}

function pnlClass(value?: number | null): string {
  if (value == null || Number.isNaN(Number(value))) return ''
  if (Number(value) > 0) return 'is-profit'
  if (Number(value) < 0) return 'is-loss'
  return ''
}

async function loadGroups(): Promise<void> {
  loading.value = true
  try {
    const response = await tradeReviewApi.listGroups()
    groups.value = response.items || []
    if (groups.value.length > 0) {
      if (!activeGroupId.value || !groups.value.some((item) => item.group_id === activeGroupId.value)) {
        activeGroupId.value = groups.value[0].group_id
      }
      await Promise.all([loadRecords(), loadStats()])
    } else {
      activeGroupId.value = ''
      records.value = { items: [], total: 0, skip: 0, limit: pageSize.value }
      stats.value = null
    }
  } finally {
    loading.value = false
  }
}

async function selectGroup(groupId: string): Promise<void> {
  activeGroupId.value = groupId
  currentPage.value = 1
  await Promise.all([loadRecords(), loadStats()])
}

async function loadRecords(): Promise<void> {
  if (!activeGroupId.value) return
  records.value = await tradeReviewApi.listRecords(activeGroupId.value, {
    category: category.value,
    keyword: keyword.value.trim() || undefined,
    limit: pageSize.value,
    skip: (currentPage.value - 1) * pageSize.value,
  })
}

async function loadStats(): Promise<void> {
  if (!activeGroupId.value) return
  stats.value = await tradeReviewApi.getStats(activeGroupId.value)
  stockPage.value = 1
}

function handleFilterChange(): void {
  currentPage.value = 1
  loadRecords()
}

function handlePageChange(page: number): void {
  currentPage.value = page
  loadRecords()
}

function handlePageSizeChange(size: number): void {
  pageSize.value = size
  currentPage.value = 1
  loadRecords()
}

function openReviewSession(record: TradeReviewRecord): void {
  router.push({
    name: 'TradeReviewSession',
    params: {
      groupId: activeGroupId.value,
      recordId: record.record_id,
    },
    query: {
      category: category.value,
      keyword: keyword.value.trim() || undefined,
      anchor: record.record_id,
      page: String(currentPage.value),
      pageSize: String(pageSize.value),
    },
  })
}

async function openStockSummaryReview(item: TradeReviewStatsResult['stock_pnl_ranking'][number]): Promise<void> {
  if (!activeGroupId.value) return
  const response = await tradeReviewApi.listRecords(activeGroupId.value, {
    category: 'trade',
    keyword: item.ts_code,
    limit: 1,
    skip: 0,
  })
  const target = response.items[0]
  if (!target) {
    ElMessage.warning('没有找到该股票对应的成交记录')
    return
  }
  openReviewSession(target)
}

function handleStockPageChange(page: number): void {
  stockPage.value = page
}

function handleStockPageSizeChange(size: number): void {
  stockPageSize.value = size
  stockPage.value = 1
}

function handleStockSortChange(payload: { prop: string; order: 'ascending' | 'descending' | null }): void {
  stockSortProp.value = (payload.prop || '') as keyof TradeReviewStatsResult['stock_pnl_ranking'][number] | ''
  stockSortOrder.value = payload.order
}

function openCreateDialog(): void {
  createForm.name = ''
  createForm.description = ''
  createDialogVisible.value = true
}

async function handleCreateGroup(): Promise<void> {
  if (!createForm.name.trim()) {
    ElMessage.warning('请先输入分组名称')
    return
  }
  creatingGroup.value = true
  try {
    const group = await tradeReviewApi.createGroup({
      name: createForm.name.trim(),
      description: createForm.description.trim() || undefined,
    })
    createDialogVisible.value = false
    await loadGroups()
    await selectGroup(group.group_id)
    ElMessage.success('交割单分组已创建')
  } finally {
    creatingGroup.value = false
  }
}

function openImportDialog(): void {
  selectedImportFile.value = null
  if (fileInputRef.value) fileInputRef.value.value = ''
  importDialogVisible.value = true
}

function closeImportDialog(): void {
  importDialogVisible.value = false
  selectedImportFile.value = null
  if (fileInputRef.value) fileInputRef.value.value = ''
}

function handleFileSelected(event: Event): void {
  const input = event.target as HTMLInputElement
  selectedImportFile.value = input.files?.[0] || null
}

async function handleImportCsv(): Promise<void> {
  if (!activeGroupId.value || !selectedImportFile.value) return
  importing.value = true
  try {
    const result = await tradeReviewApi.importCsv(activeGroupId.value, selectedImportFile.value)
    closeImportDialog()
    await loadGroups()
    await Promise.all([loadRecords(), loadStats()])
    ElMessage.success(`导入完成：新增 ${result.imported_rows} 条，跳过重复 ${result.duplicate_rows} 条`)
  } finally {
    importing.value = false
  }
}

watch(activeTab, async (value) => {
  if ((value === 'stats' || value === 'stocks') && activeGroupId.value) {
    await loadStats()
  }
})

onMounted(() => {
  if (typeof route.query.groupId === 'string') {
    activeGroupId.value = route.query.groupId
  }
  if (typeof route.query.category === 'string') {
    category.value = route.query.category
  }
  if (typeof route.query.keyword === 'string') {
    keyword.value = route.query.keyword
  }
  if (typeof route.query.page === 'string') {
    const page = Number(route.query.page)
    if (page > 0) currentPage.value = page
  }
  if (typeof route.query.pageSize === 'string') {
    const size = Number(route.query.pageSize)
    if (size > 0) pageSize.value = size
  }
  loadGroups()
})
</script>

<style scoped lang="scss">
.trade-review-page {
  display: flex;
  padding: 1.5rem;
  flex-direction: column;
  gap: 20px;
}

.hero-card,
.group-list-card,
.main-card {
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

.main-card {
  padding: 20px;
  min-width: 0;
}

.detail-meta {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.toolbar-select {
  width: 160px;
}

.toolbar-search {
  width: min(320px, 100%);
}

.records-table {
  width: 100%;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.stats-panel {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.stats-note {
  padding: 14px 16px;
  border-radius: 14px;
  color: var(--el-text-color-secondary);
  background: rgba(59, 130, 246, 0.08);
  line-height: 1.7;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.summary-card,
.stats-card {
  padding: 18px;
  border-radius: 18px;
  background: rgba(15, 23, 42, 0.03);
}

.summary-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.summary-card strong {
  font-size: 26px;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.stock-pnl-section {
  padding: 18px;
  border-radius: 18px;
  background: rgba(15, 23, 42, 0.03);
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

.stock-pnl-table :deep(.cell strong) {
  font-weight: 700;
}

.stock-pnl-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.stock-pnl-header h3 {
  margin: 0 0 8px;
}

.stock-pnl-header p {
  margin: 0;
  color: var(--el-text-color-secondary);
  line-height: 1.7;
}

.stats-card h3 {
  margin: 0 0 10px;
}

.stats-list {
  margin: 0;
  padding-left: 18px;
  line-height: 1.8;
}

.dialog-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.field-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.field-block label {
  font-weight: 600;
}

.field-tip,
.file-name {
  margin: 0;
  color: var(--el-text-color-secondary);
}

.is-profit {
  color: #dc2626;
}

.is-loss {
  color: #16a34a;
}

.batch-summary-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-radius: 14px;
  background: rgba(59, 130, 246, 0.08);
}

.file-input {
  display: block;
}

@media (max-width: 1200px) {
  .body-grid,
  .summary-grid,
  .stats-grid {
    grid-template-columns: 1fr;
  }

  .stock-pnl-header {
    flex-direction: column;
  }
}
</style>
