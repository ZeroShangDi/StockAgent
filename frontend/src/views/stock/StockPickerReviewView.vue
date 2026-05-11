<template>
  <div class="picker-review-page" v-loading="loading">
    <template v-if="context">
      <section class="review-shell">
        <header class="review-header">
          <div class="title-block">
            <p class="eyebrow">Deep Review</p>
            <h1>一句话选股深度复盘</h1>
            <p class="subtitle">
              {{ context.run.query_condition || context.run.input }}
              <span>· 第 {{ context.navigation.position }} / {{ context.navigation.total }} 只</span>
              <span v-if="context.stock.latest_trade_date">· {{ formatTradeDate(context.stock.latest_trade_date) }}</span>
            </p>
          </div>
          <div class="header-actions">
            <el-button @click="backToPicker">返回选股结果</el-button>
          </div>
        </header>

        <section class="content-grid">
          <div class="left-panel">
            <div class="chart-card">
              <StockReviewChartPanel
                :chart-key="`${context.stock.ts_code}-picker`"
                :stock="context.stock"
                :daily="chartDaily"
                :weekly="chartWeekly"
                :monthly="chartMonthly"
                :initial-zoom-start="70"
                :initial-zoom-end="100"
                :show-navigation="true"
                :previous-disabled="!context.navigation.previous_ts_code"
                :next-disabled="!context.navigation.next_ts_code"
                previous-label="上一只"
                next-label="下一只"
                @previous="jumpTo(context.navigation.previous_ts_code)"
                @next="jumpTo(context.navigation.next_ts_code)"
              >
                <template #footer>
                  <div class="block">
                    <label>本次结果导航</label>
                    <div class="related-list">
                      <button
                        v-for="item in context.related_stocks"
                        :key="item.ts_code"
                        type="button"
                        :class="['related-item', { active: item.is_current }]"
                        @click="jumpTo(item.ts_code)"
                      >
                        <div>
                          <strong>{{ item.name || item.ts_code }}</strong>
                          <span>{{ item.ts_code }}</span>
                        </div>
                        <span :class="['pct-text', getPnlClass(item.latest_pct_chg)]">
                          {{ formatSignedPct(item.latest_pct_chg) }}
                        </span>
                      </button>
                    </div>
                  </div>
                </template>
              </StockReviewChartPanel>
            </div>
          </div>

          <aside class="right-panel">
            <div class="info-card">
              <div class="info-grid">
                <div class="info-item">
                  <span>上市日期</span>
                  <strong>{{ formatTradeDate(context.stock.list_date) }}</strong>
                </div>
                <div class="info-item">
                  <span>结果总数</span>
                  <strong>{{ context.run.total }}</strong>
                </div>
              </div>

              <div class="block">
                <label>快捷操作</label>
                <div class="block-actions">
                  <el-button type="primary" plain :loading="watchlistLoading" @click="addCurrentToWatchlist">
                    加入自选
                  </el-button>
                  <el-button @click="openStockDetail">
                    打开个股详情
                  </el-button>
                </div>
              </div>

              <div class="block">
                <label>板块概念</label>
                <div class="source-box">
                  <p><strong>所属行业：</strong>{{ context.stock.industry || '暂无行业信息' }}</p>
                  <div v-if="context.stock.concepts?.length" class="tag-flow">
                    <span v-for="item in context.stock.concepts" :key="item.ts_code" class="sector-tag">
                      {{ item.name }}
                    </span>
                  </div>
                  <p v-else>暂无个股概念映射</p>
                </div>
              </div>

              <div class="block">
                <label>本次选股线索</label>
                <div class="source-box">
                  <p><strong>选股条件：</strong>{{ context.run.query_condition || context.run.input }}</p>
                  <p><strong>结果总数：</strong>{{ context.run.total }}</p>
                  <p><strong>生成时间：</strong>{{ formatDateTime(context.run.created_at) }}</p>
                </div>
              </div>
            </div>
          </aside>
        </section>
      </section>
    </template>
    <el-empty v-else description="暂无深度复盘数据" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import StockReviewChartPanel from '@/components/review/StockReviewChartPanel.vue'
import { stockPickerApi } from '@/api'
import { useUserStore } from '@/stores/user'
import type { StockDaily } from '@/api'
import type { StockPickerRunReviewContext } from '@/api/modules/stock-picker'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const loading = ref(false)
const watchlistLoading = ref(false)
const context = ref<StockPickerRunReviewContext | null>(null)

const currentRunId = computed(() => String(route.params.runId || ''))
const currentTsCode = computed(() => String(route.params.tsCode || '').toUpperCase())

function normalizeChartSeries(items: Array<{
  ts_code: string
  trade_date: string
  open: number
  high: number
  low: number
  close: number
  pre_close?: number | null
  change?: number | null
  pct_chg?: number | null
  vol?: number | null
  amount?: number | null
}> = []): StockDaily[] {
  return items.map((item) => ({
    ts_code: item.ts_code,
    trade_date: item.trade_date,
    open: Number(item.open || 0),
    high: Number(item.high || 0),
    low: Number(item.low || 0),
    close: Number(item.close || 0),
    pre_close: Number(item.pre_close || 0),
    change: Number(item.change || 0),
    pct_chg: Number(item.pct_chg || 0),
    vol: Number(item.vol || 0),
    amount: Number(item.amount || 0),
  }))
}

const chartDaily = computed<StockDaily[]>(() => normalizeChartSeries(context.value?.daily || []))
const chartWeekly = computed<StockDaily[]>(() => normalizeChartSeries(context.value?.weekly || []))
const chartMonthly = computed<StockDaily[]>(() => normalizeChartSeries(context.value?.monthly || []))

async function loadContext(): Promise<void> {
  if (!currentRunId.value || !currentTsCode.value) {
    context.value = null
    return
  }
  loading.value = true
  try {
    context.value = await stockPickerApi.getRunReviewContext(currentRunId.value, currentTsCode.value)
  } catch {
    context.value = null
    ElMessage.error('加载深度复盘数据失败')
  } finally {
    loading.value = false
  }
}

function jumpTo(tsCode?: string | null): void {
  if (!tsCode || !currentRunId.value) return
  router.push({
    name: 'StockPickerReview',
    params: {
      runId: currentRunId.value,
      tsCode,
    },
  })
}

function backToPicker(): void {
  router.push({ name: 'StockPicker' })
}

async function addCurrentToWatchlist(): Promise<void> {
  if (!context.value) return
  watchlistLoading.value = true
  try {
    const success = await userStore.addToWatchlist(context.value.stock.ts_code)
    if (success) {
      ElMessage.success(`已将 ${context.value.stock.name} 加入自选`)
    } else {
      ElMessage.warning('加入自选失败，可能已存在')
    }
  } finally {
    watchlistLoading.value = false
  }
}

function openStockDetail(): void {
  if (!context.value) return
  router.push({
    name: 'StockDetail',
    params: { code: context.value.stock.code },
  })
}

function formatTradeDate(value?: string | null): string {
  if (!value || value.length !== 8) return value || '-'
  return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`
}

function formatDateTime(value?: string | null): string {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function formatSignedPct(value?: number | null): string {
  if (value == null || Number.isNaN(Number(value))) return '--'
  const numeric = Number(value)
  const prefix = numeric > 0 ? '+' : ''
  return `${prefix}${numeric.toFixed(2)}%`
}

function getPnlClass(value?: number | null): string {
  if (value == null || Number.isNaN(Number(value))) return ''
  if (Number(value) > 0) return 'is-up'
  if (Number(value) < 0) return 'is-down'
  return ''
}

watch(
  () => [currentRunId.value, currentTsCode.value],
  () => {
    loadContext()
  },
  { immediate: true },
)
</script>

<style scoped lang="scss">
.picker-review-page {
  padding: 1.5rem;
}

.review-shell {
  display: grid;
  gap: 20px;
}

.review-header,
.chart-card,
.info-card {
  background: var(--el-bg-color);
  border-radius: 20px;
  border: 1px solid rgba(15, 23, 42, 0.08);
}

.review-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 24px;
}

.eyebrow {
  margin: 0 0 6px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  font-size: 12px;
  color: var(--el-color-primary);
}

.review-header h1 {
  margin: 0;
}

.subtitle {
  margin: 8px 0 0;
  color: var(--el-text-color-secondary);
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.header-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.content-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(320px, 0.95fr);
  gap: 20px;
  align-items: start;
}

.chart-card {
  padding: 18px;
}

.chart-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.chart-meta strong,
.related-item strong {
  display: block;
  font-size: 20px;
}

.chart-meta span,
.related-item span {
  color: var(--el-text-color-secondary);
}

.stock-chip-group {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.stock-chip {
  padding: 6px 12px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.12);
  color: var(--el-text-color-regular);
  font-size: 13px;
}

.chart-wrap {
  min-height: 680px;
}

.info-card {
  display: grid;
  gap: 18px;
  padding: 18px;
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.info-item {
  padding: 14px;
  border-radius: 16px;
  background: rgba(248, 250, 252, 0.9);
}

.info-item span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.info-item strong {
  display: block;
  margin-top: 8px;
  font-size: 22px;
}

.block {
  display: grid;
  gap: 10px;
}

.block label {
  font-weight: 600;
}

.block-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.source-box,
.related-list {
  display: grid;
  gap: 10px;
}

.source-box p {
  margin: 0;
  line-height: 1.7;
  color: var(--el-text-color-regular);
}

.tag-flow {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.sector-tag {
  padding: 6px 12px;
  border-radius: 999px;
  background: rgba(59, 130, 246, 0.1);
  color: #1d4ed8;
  font-size: 12px;
}

.related-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  padding: 12px 14px;
  border-radius: 16px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: transparent;
  cursor: pointer;
  text-align: left;
}

.related-item.active {
  border-color: rgba(59, 130, 246, 0.3);
  background: rgba(59, 130, 246, 0.06);
}

.pct-text {
  font-weight: 600;
}

.is-up {
  color: #dc2626;
}

.is-down {
  color: #16a34a;
}

@media (max-width: 1200px) {
  .content-grid {
    grid-template-columns: 1fr;
  }

  .chart-wrap {
    min-height: 560px;
  }
}

@media (max-width: 768px) {
  .picker-review-page {
    padding: 1rem;
  }

  .review-header,
  .chart-meta {
    grid-template-columns: 1fr;
    display: grid;
  }

  .info-grid {
    grid-template-columns: 1fr;
  }
}
</style>
