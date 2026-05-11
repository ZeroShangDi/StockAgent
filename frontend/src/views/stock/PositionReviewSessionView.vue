<template>
  <div class="position-review-session">
    <section class="session-shell" v-loading="loading">
      <header class="session-header">
        <div class="title-block">
          <p class="eyebrow">Position Review</p>
          <h1>{{ currentPosition?.name || reviewContext?.stock.name || currentTsCode || '持仓沉浸复盘' }}</h1>
          <p class="subtitle">
            {{ groupName || '持仓股' }}
            <span v-if="navigation.total">· 第 {{ navigation.position }} / {{ navigation.total }} 只</span>
            <span v-if="reviewContext?.stock.latest_trade_date">· {{ formatTradeDate(reviewContext.stock.latest_trade_date) }}</span>
          </p>
        </div>
        <div class="header-actions">
          <el-button @click="backToHoldings">返回持仓</el-button>
        </div>
      </header>

      <section v-if="reviewContext && currentPosition" class="content-grid">
        <div class="left-panel">
          <div class="chart-card">
            <StockReviewChartPanel
              :chart-key="`${currentPosition.ts_code}-position-review`"
              :stock="reviewContext.stock"
              :daily="reviewContext.daily"
              :weekly="reviewContext.weekly"
              :monthly="reviewContext.monthly"
              :initial-zoom-start="70"
              :initial-zoom-end="100"
              :show-navigation="true"
              :previous-disabled="!navigation.previousTsCode"
              :next-disabled="!navigation.nextTsCode"
              previous-label="上一只"
              next-label="下一只"
              @previous="jumpTo(navigation.previousTsCode)"
              @next="jumpTo(navigation.nextTsCode)"
            >
              <template #toolbarActions>
                <el-button type="primary" class="toolbar-top-button" :loading="watchlistLoading" @click="addCurrentToWatchlist">
                  加自选
                  <span class="button-shortcut">W</span>
                </el-button>
              </template>
            </StockReviewChartPanel>
          </div>
        </div>

        <aside class="right-panel">
          <div class="summary-card">
            <div class="info-grid">
              <div class="info-item">
                <span>持仓数量</span>
                <strong>{{ currentPosition.quantity }}</strong>
              </div>
              <div class="info-item">
                <span>持仓成本</span>
                <strong>{{ formatNumber(currentPosition.avg_cost) }}</strong>
              </div>
              <div class="info-item">
                <span>持仓市值</span>
                <strong>{{ formatAmount(currentPosition.market_value) }}</strong>
              </div>
              <div class="info-item">
                <span>盈亏比</span>
                <strong :class="getPnlClass(currentPosition.unrealized_pnl)">{{ formatSignedPct(currentPosition.unrealized_pnl_pct) }}</strong>
              </div>
            </div>

            <div class="block">
              <label>持仓快照</label>
              <div class="source-box">
                <p><strong>浮盈浮亏：</strong><span :class="getPnlClass(currentPosition.unrealized_pnl)">{{ formatSignedAmount(currentPosition.unrealized_pnl) }}</span></p>
                <p><strong>首次买入：</strong>{{ formatTradeDate(currentPosition.first_trade_date) }}</p>
                <p><strong>最后交易日：</strong>{{ formatTradeDate(currentPosition.last_trade_date) }}</p>
                <p><strong>估值日：</strong>{{ formatTradeDate(currentPosition.latest_trade_date) }}</p>
              </div>
            </div>

            <div class="block">
              <label>板块概念</label>
              <div class="source-box">
                <p><strong>所属行业：</strong>{{ reviewContext.stock.industry || '暂无行业信息' }}</p>
                <div v-if="reviewContext.stock.concepts?.length" class="tag-flow">
                  <span
                    v-for="item in reviewContext.stock.concepts"
                    :key="`concept-${item.ts_code}`"
                    class="sector-tag"
                  >
                    {{ item.name }}
                  </span>
                </div>
                <p v-else>暂无个股概念映射</p>
              </div>
            </div>

            <div class="block">
              <label>快捷操作</label>
              <div class="block-actions">
                <el-button @click="openStockDetail">打开个股详情</el-button>
              </div>
            </div>
          </div>
        </aside>
      </section>

      <el-empty v-else description="暂无持仓复盘数据" />
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import StockReviewChartPanel from '@/components/review/StockReviewChartPanel.vue'
import { stockApi, tradeReviewApi } from '@/api'
import { useUserStore } from '@/stores/user'
import type { StockReviewContext } from '@/api/modules/stock'
import type { TradeReviewPositionItem } from '@/api/modules/trade-review'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const loading = ref(false)
const watchlistLoading = ref(false)
const reviewContext = ref<StockReviewContext | null>(null)
const positions = ref<TradeReviewPositionItem[]>([])
const groupName = ref('')

const currentGroupId = computed(() => String(route.params.groupId || ''))
const currentTsCode = computed(() => String(route.params.tsCode || '').toUpperCase())

const currentPosition = computed(() => positions.value.find((item) => item.ts_code === currentTsCode.value) || null)
const navigation = computed(() => {
  const index = positions.value.findIndex((item) => item.ts_code === currentTsCode.value)
  return {
    position: index >= 0 ? index + 1 : 0,
    total: positions.value.length,
    previousTsCode: index > 0 ? positions.value[index - 1].ts_code : '',
    nextTsCode: index >= 0 && index < positions.value.length - 1 ? positions.value[index + 1].ts_code : '',
  }
})

async function loadContext(): Promise<void> {
  if (!currentGroupId.value || !currentTsCode.value) {
    reviewContext.value = null
    positions.value = []
    groupName.value = ''
    return
  }

  loading.value = true
  try {
    const [positionResult, stockContext] = await Promise.all([
      tradeReviewApi.getPositions(currentGroupId.value, false),
      stockApi.getStockReviewContext(currentTsCode.value),
    ])
    groupName.value = positionResult.group.name
    positions.value = (positionResult.items || []).filter((item) => item.security_type !== 'other')
    reviewContext.value = stockContext
  } catch (error) {
    console.error('加载持仓复盘数据失败:', error)
    reviewContext.value = null
    ElMessage.error('加载持仓复盘失败')
  } finally {
    loading.value = false
  }
}

function jumpTo(tsCode?: string | null): void {
  if (!tsCode) return
  router.push({
    name: 'PositionReviewSession',
    params: {
      groupId: currentGroupId.value,
      tsCode,
    },
  })
}

function backToHoldings(): void {
  router.push({
    name: 'PositionHoldings',
    query: currentGroupId.value ? { groupId: currentGroupId.value } : undefined,
  })
}

function openStockDetail(): void {
  if (!currentTsCode.value) return
  router.push({
    name: 'StockDetail',
    params: { code: currentTsCode.value },
  })
}

async function addCurrentToWatchlist(): Promise<void> {
  if (!currentTsCode.value || !reviewContext.value) return
  watchlistLoading.value = true
  try {
    const success = await userStore.addToWatchlist(currentTsCode.value)
    if (success) {
      ElMessage.success(`已将 ${reviewContext.value.stock.name} 加入自选`)
    } else {
      ElMessage.warning('加入自选失败，可能已存在')
    }
  } finally {
    watchlistLoading.value = false
  }
}

function formatTradeDate(value?: string | null): string {
  if (!value || value.length !== 8) return value || '-'
  return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`
}

function formatNumber(value?: number | null): string {
  return Number(value || 0).toFixed(2)
}

function formatAmount(value?: number | null): string {
  return Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatSignedAmount(value?: number | null): string {
  const amount = Number(value || 0)
  return `${amount > 0 ? '+' : ''}${formatAmount(amount)}`
}

function formatSignedPct(value?: number | null): string {
  const amount = Number(value || 0)
  return `${amount > 0 ? '+' : ''}${amount.toFixed(2)}%`
}

function getPnlClass(value?: number | null): string {
  const amount = Number(value || 0)
  if (amount > 0) return 'is-up'
  if (amount < 0) return 'is-down'
  return ''
}

function isTypingElement(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null
  if (!element) return false
  const tagName = element.tagName?.toLowerCase()
  return tagName === 'input'
    || tagName === 'textarea'
    || !!element.closest('.el-input, .el-textarea, .el-select')
    || element.isContentEditable
}

function handleKeydown(event: KeyboardEvent): void {
  if (isTypingElement(event.target)) return

  if (event.key.toLowerCase() === 'w') {
    event.preventDefault()
    void addCurrentToWatchlist()
  }
}

watch(
  () => [currentGroupId.value, currentTsCode.value],
  () => {
    loadContext()
  },
  { immediate: true },
)

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<style scoped lang="scss">
.position-review-session {
  padding: 1.5rem;
  min-width: 0;
}

.session-shell {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: calc(100vh - 140px);
}

.session-header,
.chart-card,
.summary-card {
  background: var(--el-bg-color);
  border-radius: 20px;
  border: 1px solid rgba(15, 23, 42, 0.08);
}

.session-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 22px;
}

.eyebrow {
  margin: 0;
  font-size: 12px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--el-color-primary);
}

.title-block h1 {
  margin: 6px 0 8px;
}

.subtitle {
  margin: 0;
  color: var(--el-text-color-secondary);
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.content-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(320px, 0.85fr);
  gap: 20px;
  min-width: 0;
}

.left-panel,
.right-panel {
  min-width: 0;
}

.chart-card {
  padding: 18px;
  min-height: 720px;
  display: flex;
  height: clamp(720px, 80vh, 1020px);
}

.chart-card :deep(.review-chart-panel) {
  flex: 1;
  min-height: 0;
}

.chart-card :deep(.chart-wrap),
.chart-card :deep(.stock-chart) {
  height: 100%;
  min-height: 620px;
}

.summary-card {
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

.source-box {
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

.toolbar-top-button,
.button-shortcut {
  display: inline-flex;
  align-items: center;
}

.button-shortcut {
  margin-left: 8px;
  min-width: 18px;
  justify-content: center;
  padding: 0 5px;
  border-radius: 6px;
  background: rgba(15, 23, 42, 0.06);
  font-size: 11px;
  line-height: 18px;
  color: var(--el-text-color-secondary);
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
}

@media (max-width: 768px) {
  .position-review-session {
    padding: 1rem;
  }

  .session-header {
    flex-direction: column;
  }

  .info-grid {
    grid-template-columns: 1fr;
  }
}
</style>
