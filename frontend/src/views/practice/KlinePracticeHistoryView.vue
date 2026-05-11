<template>
  <div class="practice-history-page">
    <section class="hero-card">
      <div>
        <p class="eyebrow">Practice History</p>
        <h1>盘感练习历史战绩</h1>
        <p class="description">
          回看每一局的收益、交易次数和揭晓结果。点击“回看本局”会回到沉浸式练习页，按当时的 K 线和交易记录复盘整局过程。
        </p>
      </div>
      <div class="hero-actions">
        <el-button @click="router.push({ name: 'KlinePractice' })">返回练习</el-button>
        <el-button :loading="loading" type="primary" @click="loadHistory">刷新</el-button>
      </div>
    </section>

    <section class="history-card" v-loading="loading">
      <template v-if="history.items.length">
        <el-table :data="history.items" stripe>
          <el-table-column prop="label" label="练习局" min-width="170" />
          <el-table-column label="样本揭晓" min-width="220">
            <template #default="{ row }">
              <span v-if="row.reveal">{{ row.reveal.name }}（{{ row.reveal.ts_code }}）</span>
              <span v-else>未揭晓</span>
            </template>
          </el-table-column>
          <el-table-column prop="trade_count" label="交易笔数" width="100" />
          <el-table-column prop="total_return_pct" label="总收益率" width="120">
            <template #default="{ row }">
              <strong :class="pnlClass(row.total_return_pct)">{{ formatPct(row.total_return_pct) }}</strong>
            </template>
          </el-table-column>
          <el-table-column prop="realized_pnl" label="已实现盈亏" width="140">
            <template #default="{ row }">
              <span :class="pnlClass(row.realized_pnl)">{{ formatCurrency(row.realized_pnl) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="completed_at" label="结束时间" width="180">
            <template #default="{ row }">{{ formatDateTime(row.completed_at || row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="140" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openSession(row.session_id)">
                回看本局
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="pagination-wrap">
          <el-pagination
            background
            layout="total, prev, pager, next"
            :total="history.total"
            :current-page="currentPage"
            :page-size="pageSize"
            @current-change="handlePageChange"
          />
        </div>
      </template>
      <el-empty v-else description="还没有历史练习记录" />
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { practiceApi } from '@/api'
import type { PracticeSessionHistoryResult } from '@/api/modules/practice'

const router = useRouter()

const loading = ref(false)
const currentPage = ref(1)
const pageSize = 20
const history = reactive<PracticeSessionHistoryResult>({
  items: [],
  total: 0,
  skip: 0,
  limit: pageSize,
})

async function loadHistory(): Promise<void> {
  loading.value = true
  try {
    const response = await practiceApi.getHistory({
      skip: (currentPage.value - 1) * pageSize,
      limit: pageSize,
    })
    history.items = response.items || []
    history.total = response.total || 0
    history.skip = response.skip || 0
    history.limit = response.limit || pageSize
  } finally {
    loading.value = false
  }
}

function handlePageChange(page: number): void {
  currentPage.value = page
  loadHistory()
}

function openSession(sessionId: string): void {
  router.push({
    name: 'KlinePractice',
    query: {
      sessionId,
    },
  })
}

function formatDateTime(value?: string | null): string {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function formatCurrency(value: number): string {
  return `${value >= 0 ? '' : '-'}¥${Math.abs(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`
}

function formatPct(value: number): string {
  const prefix = value > 0 ? '+' : ''
  return `${prefix}${value.toFixed(2)}%`
}

function pnlClass(value: number): string {
  if (value > 0) return 'is-profit'
  if (value < 0) return 'is-loss'
  return ''
}

onMounted(() => {
  loadHistory()
})
</script>

<style scoped lang="scss">
.practice-history-page {
  display: grid;
  gap: 20px;
  padding: 1.5rem;
}

.hero-card,
.history-card {
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

.hero-card h1 {
  margin: 6px 0 10px;
}

.description {
  margin: 0;
  color: var(--el-text-color-secondary);
  line-height: 1.7;
}

.hero-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.history-card {
  padding: 20px;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.is-profit {
  color: #dc2626;
}

.is-loss {
  color: #089981;
}

@media (max-width: 900px) {
  .practice-history-page {
    padding: 1rem;
  }

  .hero-card {
    flex-direction: column;
  }
}
</style>
