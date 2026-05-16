<template>
  <div class="trade-review-session">
    <section class="session-shell" v-loading="loading">
      <header class="session-header">
        <div class="title-block">
          <p class="eyebrow">Immersive Review</p>
          <h1>{{ context?.stock.name || context?.record.security_name || context?.record.code || '沉浸式复盘' }}</h1>
          <p class="subtitle">
            第 {{ displayPosition }} / {{ displayTotal }} {{ navigationUnit }}
            <span v-if="context?.record.trade_date">· {{ formatTradeDate(context.record.trade_date) }}</span>
            <span v-if="context?.record.side">· {{ context.record.side === 'buy' ? '买入' : '卖出' }}</span>
          </p>
        </div>
        <div class="header-actions">
          <el-button @click="backToList">返回列表</el-button>
          <el-button type="primary" :loading="saving" @click="() => saveReview()">保存</el-button>
        </div>
      </header>

      <section class="content-grid" v-if="context">
        <div class="left-panel">
          <div v-if="hasRenderableKline" class="chart-card">
            <StockReviewChartPanel
              :chart-key="`${context.record.record_id}-trade-review`"
              :stock="context.stock"
              :daily="context.daily"
              :weekly="context.weekly"
              :monthly="context.monthly"
              :initial-zoom-start="context.zoom.start"
              :initial-zoom-end="context.zoom.end"
              :show-navigation="true"
              :previous-disabled="previousDisabled"
              :next-disabled="nextDisabled"
              :markers="chartMarkers"
              :previous-label="previousLabel"
              :next-label="nextLabel"
              @previous="jumpToPrevious"
              @next="jumpToNext"
            >
              <template #footer>
                <div class="related-card">
                  <div class="related-header">
                    <h2>同股其他交易</h2>
                    <span>{{ context.related_records.length }} 条</span>
                  </div>
                  <div class="related-table-wrap">
                    <el-table :data="context.related_records" height="100%" stripe :row-class-name="getRelatedRowClassName">
                      <el-table-column prop="trade_date" label="日期" width="108">
                        <template #default="{ row }">{{ formatTradeDate(row.trade_date) }}</template>
                      </el-table-column>
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
                      <el-table-column prop="price" label="价格" width="100">
                        <template #default="{ row }">{{ formatNumber(row.price) }}</template>
                      </el-table-column>
                      <el-table-column prop="quantity" label="数量" width="96" />
                      <el-table-column prop="reviewed" label="复盘" width="86">
                        <template #default="{ row }">
                          <el-tag :type="row.reviewed ? 'success' : 'info'" effect="plain" round size="small">
                            {{ row.reviewed ? '已写' : '未写' }}
                          </el-tag>
                        </template>
                      </el-table-column>
                      <el-table-column label="操作" min-width="100" fixed="right">
                        <template #default="{ row }">
                          <el-button
                            link
                            type="primary"
                            :disabled="row.record_id === context.record.record_id"
                            @click="switchRelatedRecord(row.record_id)"
                          >
                            切换
                          </el-button>
                        </template>
                      </el-table-column>
                    </el-table>
                  </div>
                </div>
              </template>
            </StockReviewChartPanel>
          </div>
          <div v-else class="chart-card fallback-card">
            <div class="fallback-header">
              <div>
                <h2>K 线暂不可用</h2>
                <p>{{ context.load_error || '当前记录暂时无法加载图表数据，但你仍然可以保存复盘并切换下一条。' }}</p>
              </div>
              <el-tag
                v-if="context.record.security_type === 'other'"
                size="small"
                effect="plain"
                type="info"
              >
                非股票
              </el-tag>
            </div>

            <div class="fallback-info-grid">
              <div class="summary-item">
                <span>证券名称</span>
                <strong>{{ context.record.security_name || context.record.code || '-' }}</strong>
              </div>
              <div class="summary-item">
                <span>证券代码</span>
                <strong>{{ context.record.ts_code || context.record.code || '-' }}</strong>
              </div>
              <div class="summary-item">
                <span>成交日期</span>
                <strong>{{ formatTradeDate(context.record.trade_date) }}</strong>
              </div>
              <div class="summary-item">
                <span>当前进度</span>
                <strong>{{ displayPosition }} / {{ displayTotal }} {{ navigationUnit }}</strong>
              </div>
            </div>

            <div class="fallback-actions">
              <el-button
                :disabled="previousDisabled"
                @click="jumpToPrevious"
              >
                {{ previousLabel }}
              </el-button>
              <el-button
                type="primary"
                :disabled="nextDisabled"
                @click="jumpToNext"
              >
                {{ nextLabel }}
              </el-button>
              <el-button
                v-if="showRepairButton"
                :loading="repairLoading"
                @click="startRepairTask"
              >
                补充数据
              </el-button>
            </div>

            <div v-if="repairTask" class="repair-status">
              补数任务：{{ getRepairStatusLabel(repairTask.status) }}
              <span v-if="repairTask.message">· {{ repairTask.message }}</span>
            </div>
          </div>

          <div v-if="context && !hasRenderableKline" class="related-card">
            <div class="related-header">
              <h2>同股其他交易</h2>
              <span>{{ context.related_records.length }} 条</span>
            </div>
            <div class="related-table-wrap">
              <el-table :data="context.related_records" height="100%" stripe :row-class-name="getRelatedRowClassName">
                <el-table-column prop="trade_date" label="日期" width="108">
                  <template #default="{ row }">{{ formatTradeDate(row.trade_date) }}</template>
                </el-table-column>
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
                <el-table-column prop="price" label="价格" width="100">
                  <template #default="{ row }">{{ formatNumber(row.price) }}</template>
                </el-table-column>
                <el-table-column prop="quantity" label="数量" width="96" />
                <el-table-column prop="reviewed" label="复盘" width="86">
                  <template #default="{ row }">
                    <el-tag :type="row.reviewed ? 'success' : 'info'" effect="plain" round size="small">
                      {{ row.reviewed ? '已写' : '未写' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="操作" min-width="100" fixed="right">
                  <template #default="{ row }">
                    <el-button
                      link
                      type="primary"
                      :disabled="row.record_id === context.record.record_id"
                      @click="switchRelatedRecord(row.record_id)"
                    >
                      切换
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </div>
        </div>

        <aside class="right-panel">
          <div class="summary-card">
            <div class="summary-grid minimal">
              <div class="summary-item">
                <span>上市日期</span>
                <strong>{{ formatTradeDate(context.stock.list_date) }}</strong>
              </div>
              <div class="summary-item">
                <span>成交金额</span>
                <strong>{{ formatNumber(context.record.amount) }}</strong>
              </div>
            </div>

            <div class="summary-block">
              <label>板块概念</label>
              <div v-if="context.stock.concepts?.length" class="tag-flow">
                <span
                  v-for="item in context.stock.concepts || []"
                  :key="`concept-${item.ts_code}`"
                  class="sector-tag"
                >
                  {{ item.name }}
                </span>
              </div>
              <p v-else class="summary-empty">暂无个股概念映射</p>
            </div>
          </div>

          <div class="review-card">
            <div class="review-block">
              <label>操作理由</label>
              <el-input
                v-model="reviewForm.operation_reason"
                type="textarea"
                :rows="5"
                placeholder="为什么做这笔交易，计划是什么。"
              />
            </div>

            <div class="review-block">
              <label>心路历程</label>
              <el-input
                v-model="reviewForm.mindset"
                type="textarea"
                :rows="5"
                placeholder="当时的情绪、预期、执行状态。"
              />
            </div>

            <div class="review-block">
              <label>市场环境</label>
              <el-input
                v-model="reviewForm.market_context"
                type="textarea"
                :rows="5"
                placeholder="指数、板块、情绪、题材环境。"
              />
            </div>

            <div class="review-block">
              <label>结果判定</label>
              <el-radio-group v-model="reviewForm.verdict">
                <el-radio-button label="">未判定</el-radio-button>
                <el-radio-button label="success">成功</el-radio-button>
                <el-radio-button label="failure">失败</el-radio-button>
              </el-radio-group>
            </div>

            <div class="review-block">
              <label>成败原因</label>
              <el-select
                v-model="reviewForm.reasons"
                multiple
                collapse-tags
                collapse-tags-tooltip
                class="reason-select"
                :placeholder="reviewForm.verdict ? '请选择原因标签' : '先选择结果判定'"
                :disabled="!reviewForm.verdict"
              >
                <el-option
                  v-for="item in currentReasonOptions"
                  :key="item"
                  :label="item"
                  :value="item"
                />
              </el-select>
            </div>

            <div class="review-note">
              快捷键：<kbd>Ctrl/Cmd + S</kbd> 保存，<kbd>←</kbd> 上一条，<kbd>→</kbd> 下一条，<kbd>1</kbd> 成功，<kbd>2</kbd> 失败。
            </div>
          </div>
        </aside>
      </section>

      <el-empty v-else description="暂无复盘数据" />
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { stockApi, tradeReviewApi } from '@/api'
import StockReviewChartPanel from '@/components/review/StockReviewChartPanel.vue'
import type { TradeReviewKlineContext } from '@/api/modules/trade-review'
import { TRADE_REVIEW_REASON_OPTIONS } from '@/api/modules/trade-review'
import type { StockRepairTaskStatus } from '@/api/modules/stock'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const saving = ref(false)
const savingAndMoving = ref(false)
const repairLoading = ref(false)
const context = ref<TradeReviewKlineContext | null>(null)
const initialReviewSnapshot = ref('')
const repairTask = ref<StockRepairTaskStatus | null>(null)
let repairTaskTimer: number | null = null

const reviewForm = reactive<{
  operation_reason: string
  mindset: string
  market_context: string
  verdict: '' | 'success' | 'failure'
  reasons: string[]
}>({
  operation_reason: '',
  mindset: '',
  market_context: '',
  verdict: '',
  reasons: [],
})

const currentReasonOptions = computed<string[]>(() => {
  if (reviewForm.verdict === 'success') return [...TRADE_REVIEW_REASON_OPTIONS.success]
  if (reviewForm.verdict === 'failure') return [...TRADE_REVIEW_REASON_OPTIONS.failure]
  return []
})

function getQueryString(key: string, fallback = ''): string {
  const value = route.query[key]
  return typeof value === 'string' ? value : fallback
}

function getReturnTab(): 'records' | 'stocks' | 'heatmap' {
  const tab = getQueryString('tab', '')
  if (tab === 'stocks' || tab === 'heatmap' || tab === 'records') return tab
  return isStockSummaryMode.value ? 'stocks' : 'records'
}

function formatTradeDate(value?: string | null): string {
  if (!value) return '-'
  return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`
}

function formatNumber(value: number): string {
  return Number(value || 0).toFixed(2)
}

function syncReviewForm(): void {
  if (!context.value) return
  reviewForm.operation_reason = context.value.record.operation_reason || ''
  reviewForm.mindset = context.value.record.mindset || ''
  reviewForm.market_context = context.value.record.market_context || ''
  reviewForm.verdict = context.value.record.result_reasons?.verdict || ''
  reviewForm.reasons = [...(context.value.record.result_reasons?.reasons || [])]
  initialReviewSnapshot.value = getReviewSnapshot()
}

const isDirty = computed(() => getReviewSnapshot() !== initialReviewSnapshot.value)
const chartMarkers = computed(() => {
  if (!context.value) return []

  const quantityMap = new Map<string, number>()
  for (const item of [context.value.record, ...context.value.related_records]) {
    if (item?.record_id) {
      quantityMap.set(item.record_id, Number(item.quantity || 0))
    }
  }

  return (context.value.markers || []).map((item) => {
    const quantity = quantityMap.get(item.record_id)
    const sideLabel = item.side === 'buy' ? '买' : item.side === 'sell' ? '卖' : '标'
    return {
      ...item,
      label: quantity && quantity > 0 ? `${sideLabel} ${quantity}股` : item.label,
    }
  })
})

const hasRenderableKline = computed(() => {
  return !!context.value && !context.value.load_error && (context.value.daily?.length || 0) > 0
})
const stockSummaryTsCodes = computed<string[]>(() => {
  const raw = route.query.summaryTsCodes
  if (typeof raw !== 'string') return []
  return raw.split(',').map((item) => item.trim().toUpperCase()).filter(Boolean)
})
const isStockSummaryMode = computed(() => route.query.navigationMode === 'stock-summary' && stockSummaryTsCodes.value.length > 0)
const stockSummaryNavigation = computed(() => {
  const currentTsCode = String(context.value?.record.ts_code || '').toUpperCase()
  const index = stockSummaryTsCodes.value.findIndex((item) => item === currentTsCode)
  return {
    position: index >= 0 ? index + 1 : 0,
    total: stockSummaryTsCodes.value.length,
    previousTsCode: index > 0 ? stockSummaryTsCodes.value[index - 1] : '',
    nextTsCode: index >= 0 && index < stockSummaryTsCodes.value.length - 1 ? stockSummaryTsCodes.value[index + 1] : '',
  }
})
const displayPosition = computed(() => {
  if (isStockSummaryMode.value) return stockSummaryNavigation.value.position
  return context.value?.navigation.position || 0
})
const displayTotal = computed(() => {
  if (isStockSummaryMode.value) return stockSummaryNavigation.value.total
  return context.value?.navigation.total || 0
})
const navigationUnit = computed(() => (isStockSummaryMode.value ? '只' : '条'))
const previousDisabled = computed(() => {
  if (saving.value || savingAndMoving.value) return true
  if (isStockSummaryMode.value) return !stockSummaryNavigation.value.previousTsCode
  return !context.value?.navigation.previous_record_id
})
const nextDisabled = computed(() => {
  if (saving.value || savingAndMoving.value) return true
  if (isStockSummaryMode.value) return !stockSummaryNavigation.value.nextTsCode
  return !context.value?.navigation.next_record_id
})
const previousLabel = computed(() => (isStockSummaryMode.value ? '上一只' : '上一条'))
const nextLabel = computed(() => (isStockSummaryMode.value ? '下一只' : '下一条'))
const showRepairButton = computed(() => {
  if (!context.value?.load_error) return false
  if (context.value.record.security_type === 'other') return false
  return !!context.value.record.ts_code
})

function getReviewSnapshot(): string {
  return JSON.stringify({
    operation_reason: reviewForm.operation_reason,
    mindset: reviewForm.mindset,
    market_context: reviewForm.market_context,
    verdict: reviewForm.verdict,
    reasons: [...reviewForm.reasons].sort(),
  })
}

async function loadContext(): Promise<void> {
  const recordId = String(route.params.recordId || '')
  if (!recordId) return
  loading.value = true
  try {
    context.value = await tradeReviewApi.getKline(recordId, {
      window: 50,
      category: getQueryString('category', 'trade'),
      keyword: getQueryString('keyword') || undefined,
      anchor_record_id: getQueryString('anchor', recordId),
    })
    repairTask.value = null
    stopRepairTaskPolling()
    syncReviewForm()
  } catch (error) {
    context.value = null
    ElMessage.error('打开复盘详情失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

async function saveReview(showMessage = true): Promise<boolean> {
  if (!context.value) return false
  saving.value = true
  try {
    const updated = await tradeReviewApi.updateRecord(context.value.record.record_id, {
      operation_reason: reviewForm.operation_reason,
      mindset: reviewForm.mindset,
      market_context: reviewForm.market_context,
      result_reasons: {
        verdict: reviewForm.verdict,
        reasons: reviewForm.reasons,
      },
    })
    context.value.record = updated
    context.value.related_records = context.value.related_records.map((item) =>
      item.record_id === updated.record_id ? updated : item,
    )
    initialReviewSnapshot.value = getReviewSnapshot()
    if (showMessage) ElMessage.success('复盘内容已保存')
    return true
  } finally {
    saving.value = false
  }
}

async function confirmLeaveIfDirty(): Promise<boolean> {
  if (!isDirty.value) return true
  try {
    await ElMessageBox.confirm('当前复盘内容尚未保存，是否继续切换？', '未保存提醒', {
      type: 'warning',
      confirmButtonText: '继续切换',
      cancelButtonText: '留下继续编辑',
    })
    return true
  } catch {
    return false
  }
}

function pushRecord(recordId: string, anchorId?: string): void {
  router.push({
    name: 'TradeReviewSession',
    params: {
      groupId: route.params.groupId,
      recordId,
    },
    query: {
      ...route.query,
      anchor: anchorId || getQueryString('anchor', recordId),
    },
  })
}

async function switchRelatedRecord(recordId: string): Promise<void> {
  if (!(await confirmLeaveIfDirty())) return
  pushRecord(recordId, getQueryString('anchor', context.value?.navigation.anchor_record_id || recordId))
}

async function openSummaryNeighbor(tsCode?: string | null): Promise<void> {
  if (!tsCode || !route.params.groupId) return
  const response = await tradeReviewApi.listRecords(String(route.params.groupId), {
    category: 'trade',
    keyword: tsCode,
    limit: 1,
    skip: 0,
  })
  const target = response.items[0]
  if (!target) {
    ElMessage.warning(`没有找到 ${tsCode} 对应的成交记录`)
    return
  }
  pushRecord(target.record_id, target.record_id)
}

async function jumpToNext(): Promise<void> {
  if (isStockSummaryMode.value) {
    if (!stockSummaryNavigation.value.nextTsCode) return
    savingAndMoving.value = true
    try {
      await saveReview(false)
      await openSummaryNeighbor(stockSummaryNavigation.value.nextTsCode)
    } finally {
      savingAndMoving.value = false
    }
    return
  }
  if (!context.value?.navigation.next_record_id) return
  savingAndMoving.value = true
  try {
    await saveReview(false)
    pushRecord(context.value.navigation.next_record_id, context.value.navigation.next_record_id)
  } finally {
    savingAndMoving.value = false
  }
}

async function jumpToPrevious(): Promise<void> {
  if (isStockSummaryMode.value) {
    if (!stockSummaryNavigation.value.previousTsCode) return
    savingAndMoving.value = true
    try {
      await saveReview(false)
      await openSummaryNeighbor(stockSummaryNavigation.value.previousTsCode)
    } finally {
      savingAndMoving.value = false
    }
    return
  }
  if (!context.value?.navigation.previous_record_id) return
  savingAndMoving.value = true
  try {
    await saveReview(false)
    pushRecord(context.value.navigation.previous_record_id, context.value.navigation.previous_record_id)
  } finally {
    savingAndMoving.value = false
  }
}

async function backToList(): Promise<void> {
  if (!(await confirmLeaveIfDirty())) return
  router.push({
    name: 'TradeReview',
    query: {
      groupId: String(route.params.groupId || ''),
      tab: getReturnTab(),
      category: getQueryString('category', 'trade'),
      keyword: getQueryString('keyword'),
      page: getQueryString('page', '1'),
      pageSize: getQueryString('pageSize', '100'),
      stockPage: getQueryString('stockPage', '1'),
      stockPageSize: getQueryString('stockPageSize', '50'),
    },
  })
}

function getRelatedRowClassName({ row }: { row: { record_id: string } }): string {
  return row.record_id === context.value?.record.record_id ? 'current-related-row' : ''
}

function isTypingElement(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null
  if (!element) return false
  const tagName = element.tagName?.toLowerCase()
  return tagName === 'input' || tagName === 'textarea' || !!element.closest('.el-input, .el-textarea, .el-select') || element.isContentEditable
}

function handleKeydown(event: KeyboardEvent): void {
  if (isTypingElement(event.target)) {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
      event.preventDefault()
      void saveReview()
    }
    return
  }

  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {
    event.preventDefault()
    void saveReview()
    return
  }

  if (event.key === 'ArrowLeft') {
    event.preventDefault()
    void jumpToPrevious()
    return
  }

  if (event.key === 'ArrowRight') {
    event.preventDefault()
    void jumpToNext()
    return
  }

  if (event.key === '1') {
    reviewForm.verdict = 'success'
    reviewForm.reasons = reviewForm.reasons.filter((item) => currentReasonOptions.value.includes(item))
    return
  }

  if (event.key === '2') {
    reviewForm.verdict = 'failure'
    reviewForm.reasons = reviewForm.reasons.filter((item) => currentReasonOptions.value.includes(item))
  }
}

function getRepairStatusLabel(status?: string): string {
  const mapping: Record<string, string> = {
    queued: '排队中',
    running: '进行中',
    completed: '已完成',
    failed: '失败',
  }
  return mapping[status || ''] || status || '未知'
}

function stopRepairTaskPolling(): void {
  if (repairTaskTimer != null) {
    window.clearTimeout(repairTaskTimer)
    repairTaskTimer = null
  }
}

async function pollRepairTask(taskId: string): Promise<void> {
  try {
    const status = await stockApi.getStockRepairTask(taskId)
    repairTask.value = status
    if (status.status === 'completed') {
      ElMessage.success(`${context.value?.stock.name || context.value?.record.security_name || context.value?.record.ts_code} 补数完成`)
      await loadContext()
      stopRepairTaskPolling()
      return
    }
    if (status.status === 'failed') {
      ElMessage.error(status.error_message || '单股补数失败')
      stopRepairTaskPolling()
      return
    }
    stopRepairTaskPolling()
    repairTaskTimer = window.setTimeout(() => {
      void pollRepairTask(taskId)
    }, 2000)
  } catch (error) {
    stopRepairTaskPolling()
    ElMessage.error('查询单股补数状态失败')
  }
}

async function startRepairTask(): Promise<void> {
  const tsCode = context.value?.record.ts_code
  if (!tsCode) return
  repairLoading.value = true
  try {
    const response = await stockApi.createStockRepairTask(tsCode)
    ElMessage.success(response.message || '已创建单股补数任务')
    stopRepairTaskPolling()
    await pollRepairTask(response.task_id)
  } catch (error) {
    ElMessage.error('发起单股补数失败')
  } finally {
    repairLoading.value = false
  }
}

watch(
  () => reviewForm.verdict,
  (value) => {
    if (!value) {
      reviewForm.reasons = []
      return
    }
    reviewForm.reasons = reviewForm.reasons.filter((item) => currentReasonOptions.value.includes(item))
  },
)

watch(
  () => [route.params.recordId, route.query.anchor, route.query.category, route.query.keyword],
  () => {
    loadContext()
  },
)

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
  loadContext()
})

onBeforeRouteLeave(async (_to, _from, next) => {
  if (await confirmLeaveIfDirty()) {
    next()
  } else {
    next(false)
  }
})

onBeforeUnmount(() => {
  stopRepairTaskPolling()
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<style scoped lang="scss">
.trade-review-session {
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
.related-card,
.review-card {
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
}

.header-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.content-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(360px, 0.9fr);
  gap: 16px;
  flex: 1;
  min-width: 0;
}

.left-panel,
.right-panel {
  min-width: 0;
}

.right-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.left-panel {
  display: grid;
  grid-template-rows: minmax(420px, 1fr) 260px;
  gap: 16px;
}

.chart-card,
.related-card,
.review-card {
  min-width: 0;
}

.chart-card {
  display: flex;
  flex-direction: column;
  padding: 18px;
  min-height: 0;
}

.fallback-card {
  justify-content: space-between;
  gap: 18px;
}

.fallback-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.fallback-header h2 {
  margin: 0 0 8px;
}

.fallback-header p {
  margin: 0;
  color: var(--el-text-color-secondary);
  line-height: 1.7;
}

.fallback-info-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.fallback-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.repair-status {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.chart-meta {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 12px;
  color: var(--el-text-color-secondary);
}

.chart-title-block {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
}

.trade-chip-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.trade-chip {
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(59, 130, 246, 0.08);
}

.price-up {
  color: #dc2626;
}

.price-down {
  color: #059669;
}

.chart-wrap {
  flex: 1;
  min-height: 0;
}

.related-card {
  display: flex;
  flex-direction: column;
  padding: 16px;
  min-height: 0;
}

.related-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.related-header h2 {
  margin: 0;
  font-size: 16px;
}

.related-table-wrap {
  flex: 1;
  min-height: 0;
}

.review-card {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 20px;
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.summary-card {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 18px;
  background: var(--el-bg-color);
  border-radius: 20px;
  border: 1px solid rgba(15, 23, 42, 0.08);
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.summary-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(59, 130, 246, 0.05);
}

.summary-item span {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.summary-item strong {
  font-size: 16px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}

.summary-block {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.summary-block label {
  font-weight: 600;
}

.tag-flow {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.sector-tag {
  display: inline-flex;
  align-items: center;
  padding: 6px 12px;
  border-radius: 999px;
  background: rgba(59, 130, 246, 0.08);
  color: var(--el-color-primary);
  font-size: 13px;
  font-weight: 500;
}

.summary-empty {
  margin: 0;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.review-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.review-block label {
  font-weight: 600;
}

.reason-select {
  width: 100%;
}

.review-note {
  color: var(--el-text-color-secondary);
  line-height: 1.7;
}

:deep(.current-related-row) {
  --el-table-tr-bg-color: rgba(59, 130, 246, 0.08);
}

kbd {
  padding: 2px 6px;
  border-radius: 6px;
  border: 1px solid rgba(15, 23, 42, 0.12);
  background: rgba(15, 23, 42, 0.04);
}

@media (max-width: 1280px) {
  .content-grid {
    grid-template-columns: 1fr;
  }

  .left-panel {
    grid-template-rows: minmax(420px, 1fr) 280px;
  }
}

@media (max-width: 720px) {
  .summary-grid {
    grid-template-columns: 1fr;
  }
}
</style>
