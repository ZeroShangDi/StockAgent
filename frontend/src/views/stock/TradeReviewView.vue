<template>
  <div class="trade-review-page">
    <section class="hero-card">
      <div>
        <p class="eyebrow">Trade Review</p>
        <h1>交割单复盘</h1>
        <p class="description">
          按分组沉淀自己的交割单或案例交割单，支持 CSV 去重导入、逐笔补充复盘笔记，并从整体维度做交易统计。
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
                <el-select v-model="category" class="toolbar-select" @change="loadRecords">
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
                  @keyup.enter="loadRecords"
                  @clear="loadRecords"
                />
                <el-button @click="loadRecords">查询</el-button>
                <span class="toolbar-meta">共 {{ records.total }} 条</span>
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
                <el-table-column label="操作" width="210" fixed="right">
                  <template #default="{ row }">
                    <div class="row-actions">
                      <el-button link type="primary" @click="openReviewDrawer(row)">复盘</el-button>
                      <el-button link type="primary" :disabled="!row.ts_code" @click="openKlineDialog(row)">K线</el-button>
                    </div>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>

            <el-tab-pane label="统计总览" name="stats">
              <div v-if="stats" class="stats-panel">
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

    <el-drawer v-model="reviewDrawerVisible" size="560px" :title="selectedRecord ? `复盘：${selectedRecord.security_name || selectedRecord.code}` : '复盘'">
      <template v-if="selectedRecord">
        <div class="review-meta">
          <span>{{ formatTradeDate(selectedRecord.trade_date) }}</span>
          <span>{{ selectedRecord.business_type }}</span>
          <span>{{ selectedRecord.code }}</span>
          <span>{{ formatNumber(selectedRecord.price) }} × {{ selectedRecord.quantity }}</span>
        </div>
        <div class="field-block">
          <label>操作理由</label>
          <el-input v-model="reviewForm.operation_reason" type="textarea" :rows="4" placeholder="这笔交易为什么做？" />
        </div>
        <div class="field-block">
          <label>心路历程</label>
          <el-input v-model="reviewForm.mindset" type="textarea" :rows="4" placeholder="当时的情绪、预期和执行状态" />
        </div>
        <div class="field-block">
          <label>市场环境</label>
          <el-input v-model="reviewForm.market_context" type="textarea" :rows="4" placeholder="大盘、板块、情绪、题材背景" />
        </div>
        <div class="field-block">
          <label>成功原因（每行一个）</label>
          <el-input v-model="reviewForm.successText" type="textarea" :rows="4" placeholder="例如：顺势、板块共振、买点前置" />
        </div>
        <div class="field-block">
          <label>失败原因（每行一个）</label>
          <el-input v-model="reviewForm.failureText" type="textarea" :rows="4" placeholder="例如：追高、仓位重、卖点后置" />
        </div>
        <div class="drawer-actions">
          <el-button :disabled="!selectedRecord.ts_code" @click="openKlineDialog(selectedRecord)">查看 K 线</el-button>
          <el-button type="primary" :loading="savingReview" @click="handleSaveReview">保存复盘</el-button>
        </div>
      </template>
    </el-drawer>

    <el-dialog v-model="klineDialogVisible" title="交易 K 线复盘" width="82%">
      <div v-if="klineContext" class="kline-panel">
        <div class="kline-meta">
          <strong>{{ klineContext.stock.name || klineContext.stock.ts_code }}</strong>
          <span>{{ klineContext.stock.ts_code }}</span>
          <span>{{ formatTradeDate(klineContext.record.trade_date) }}</span>
          <span>{{ klineContext.record.side === 'buy' ? '买入' : '卖出' }} {{ formatNumber(klineContext.record.price) }}</span>
        </div>
        <div class="kline-chart">
          <StockChart
            :data="klineContext.daily"
            :ts-code="klineContext.stock.ts_code"
            :markers="klineContext.markers"
            preserve-zoom
            :initial-zoom-start="klineContext.zoom.start"
            :initial-zoom-end="klineContext.zoom.end"
          />
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { tradeReviewApi } from '@/api'
import StockChart from '@/components/charts/StockChart.vue'
import type {
  TradeReviewGroupSummary,
  TradeReviewKlineContext,
  TradeReviewRecord,
  TradeReviewRecordListResult,
  TradeReviewStatsResult,
} from '@/api/modules/trade-review'

const loading = ref(false)
const groups = ref<TradeReviewGroupSummary[]>([])
const activeGroupId = ref('')
const activeTab = ref<'records' | 'stats'>('records')
const category = ref('trade')
const keyword = ref('')
const records = ref<TradeReviewRecordListResult>({ items: [], total: 0, skip: 0, limit: 200 })
const stats = ref<TradeReviewStatsResult | null>(null)

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

const reviewDrawerVisible = ref(false)
const selectedRecord = ref<TradeReviewRecord | null>(null)
const savingReview = ref(false)
const reviewForm = reactive({
  operation_reason: '',
  mindset: '',
  market_context: '',
  successText: '',
  failureText: '',
})

const klineDialogVisible = ref(false)
const klineContext = ref<TradeReviewKlineContext | null>(null)

const activeGroup = computed(() => groups.value.find((item) => item.group_id === activeGroupId.value) || null)

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
      records.value = { items: [], total: 0, skip: 0, limit: 200 }
      stats.value = null
    }
  } finally {
    loading.value = false
  }
}

async function selectGroup(groupId: string): Promise<void> {
  activeGroupId.value = groupId
  await Promise.all([loadRecords(), loadStats()])
}

async function loadRecords(): Promise<void> {
  if (!activeGroupId.value) return
  records.value = await tradeReviewApi.listRecords(activeGroupId.value, {
    category: category.value,
    keyword: keyword.value.trim() || undefined,
    limit: 200,
    skip: 0,
  })
}

async function loadStats(): Promise<void> {
  if (!activeGroupId.value) return
  stats.value = await tradeReviewApi.getStats(activeGroupId.value)
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

function openReviewDrawer(record: TradeReviewRecord): void {
  selectedRecord.value = record
  reviewForm.operation_reason = record.operation_reason || ''
  reviewForm.mindset = record.mindset || ''
  reviewForm.market_context = record.market_context || ''
  reviewForm.successText = (record.result_reasons?.success || []).join('\n')
  reviewForm.failureText = (record.result_reasons?.failure || []).join('\n')
  reviewDrawerVisible.value = true
}

async function handleSaveReview(): Promise<void> {
  if (!selectedRecord.value) return
  savingReview.value = true
  try {
    const updated = await tradeReviewApi.updateRecord(selectedRecord.value.record_id, {
      operation_reason: reviewForm.operation_reason,
      mindset: reviewForm.mindset,
      market_context: reviewForm.market_context,
      result_reasons: {
        success: reviewForm.successText.split('\n').map((item) => item.trim()).filter(Boolean),
        failure: reviewForm.failureText.split('\n').map((item) => item.trim()).filter(Boolean),
      },
    })
    selectedRecord.value = updated
    reviewDrawerVisible.value = false
    await Promise.all([loadRecords(), loadStats()])
    ElMessage.success('复盘内容已保存')
  } finally {
    savingReview.value = false
  }
}

async function openKlineDialog(record: TradeReviewRecord): Promise<void> {
  if (!record.ts_code) {
    ElMessage.warning('该记录没有可用股票代码')
    return
  }
  klineContext.value = await tradeReviewApi.getKline(record.record_id, 50)
  klineDialogVisible.value = true
}

watch(activeTab, async (value) => {
  if (value === 'stats' && activeGroupId.value) {
    await loadStats()
  }
})

onMounted(() => {
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
.toolbar-meta,
.review-meta {
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

.row-actions {
  display: inline-flex;
  gap: 8px;
}

.stats-panel {
  display: flex;
  flex-direction: column;
  gap: 18px;
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

.stats-card h3 {
  margin: 0 0 10px;
}

.stats-list {
  margin: 0;
  padding-left: 18px;
  line-height: 1.8;
}

.dialog-body,
.kline-panel {
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

.review-meta {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.drawer-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
}

.kline-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  color: var(--el-text-color-secondary);
}

.kline-chart {
  height: 620px;
  min-width: 0;
}

@media (max-width: 1200px) {
  .body-grid,
  .summary-grid,
  .stats-grid {
    grid-template-columns: 1fr;
  }
}
</style>
