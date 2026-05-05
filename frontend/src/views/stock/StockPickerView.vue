<template>
  <div class="picker-page">
    <section class="hero-card">
      <div>
        <p class="eyebrow">One-Line Picker</p>
        <h1>一句话选股</h1>
        <p class="description">
          用自然语言快速筛一批候选股，并把结果直接送进你的本地股池，作为后续观察和流转的起点。
        </p>
      </div>
      <div class="hero-note">
        <span>结果源自独立 Coze 工作流</span>
        <strong>支持导出 code / 加入股池</strong>
      </div>
    </section>

    <section class="query-card">
      <div class="query-bar">
        <el-input
          v-model="queryText"
          size="large"
          clearable
          placeholder="请输入选股条件，例如：最近5天涨幅靠前的科技股"
          @keyup.enter="runQuery"
        />
        <el-button type="primary" size="large" :loading="loading" @click="runQuery">
          开始选股
        </el-button>
      </div>
      <div class="examples">
        <span>示例：</span>
        <button v-for="item in quickExamples" :key="item" type="button" @click="useExample(item)">
          {{ item }}
        </button>
      </div>
    </section>

    <section v-if="result" class="result-toolbar">
      <div class="toolbar-main">
        <div class="pill">
          <span>条件</span>
          <strong>{{ result.query_condition || result.input }}</strong>
        </div>
        <div class="pill">
          <span>结果数</span>
          <strong>{{ result.total }}</strong>
        </div>
        <div class="pill">
          <span>已选</span>
          <strong>{{ selectedRows.length }}</strong>
        </div>
      </div>
      <div class="toolbar-actions">
        <el-button @click="copyCodes">复制 code</el-button>
        <el-button @click="downloadCodes">下载 code</el-button>
        <el-button type="primary" :disabled="selectedRows.length === 0" @click="openPoolDialog">
          加入股池
        </el-button>
      </div>
    </section>

    <section class="result-card">
      <template v-if="loading">
        <div class="loading-state">
          <el-skeleton animated :rows="8" />
        </div>
      </template>
      <template v-else-if="result">
        <el-table :data="result.data_list" stripe @selection-change="handleSelectionChange">
          <el-table-column type="selection" width="50" fixed="left" />
          <el-table-column label="代码" min-width="120" fixed="left">
            <template #default="{ row }">
              <div class="stock-meta">
                <strong>{{ row.__meta.code }}</strong>
                <span>{{ row.__meta.ts_code }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="名称" min-width="120" fixed="left">
            <template #default="{ row }">
              {{ row.__meta.name || row['名称'] || '-' }}
            </template>
          </el-table-column>
          <el-table-column
            v-for="column in visibleColumns"
            :key="column"
            :prop="column"
            :label="column"
            min-width="130"
            show-overflow-tooltip
          >
            <template #default="{ row }">
              <span :class="valueClass(column, row[column])">
                {{ formatCell(column, row[column]) }}
              </span>
            </template>
          </el-table-column>
        </el-table>
      </template>
      <template v-else>
        <el-empty description="先输入一句选股条件，再把结果送进股池。" />
      </template>
    </section>

    <el-dialog v-model="poolDialogVisible" title="加入股池" width="560px">
      <div class="pool-dialog">
        <el-radio-group v-model="poolMode">
          <el-radio-button label="existing">加入已有股池</el-radio-button>
          <el-radio-button label="new">新建股池并加入</el-radio-button>
        </el-radio-group>

        <div v-if="poolMode === 'existing'" class="dialog-block">
          <el-select v-model="selectedPoolId" placeholder="请选择一个股池" style="width: 100%">
            <el-option
              v-for="pool in pools"
              :key="pool.pool_id"
              :label="`${pool.name} · ${pool.pool_type}（${pool.stock_count}）`"
              :value="pool.pool_id"
            />
          </el-select>
          <p class="hint" v-if="pools.length === 0">你还没有股池，切换到“新建股池并加入”即可。</p>
        </div>

        <div v-else class="dialog-block">
          <el-form label-position="top">
            <el-form-item label="股池名称">
              <el-input v-model="newPool.name" placeholder="例如：一句话选股-科技观察池" />
            </el-form-item>
            <el-form-item label="股池类型">
              <el-select v-model="newPool.pool_type" placeholder="请选择类型" style="width: 100%">
                <el-option v-for="type in poolTypeOptions" :key="type" :label="type" :value="type" />
              </el-select>
            </el-form-item>
            <el-form-item label="备注">
              <el-input v-model="newPool.description" type="textarea" :rows="3" placeholder="可填写这个池的用途，例如用于 3-5 天观察。" />
            </el-form-item>
          </el-form>
        </div>

        <p class="selection-summary">本次将加入 {{ selectedRows.length }} 只股票。</p>
      </div>
      <template #footer>
        <el-button @click="poolDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submittingPool" @click="submitToPool">
          确认加入
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { stockPickerApi } from '@/api'
import type { StockPickerQueryResult, StockPickerRow, StockPoolSummary } from '@/api/modules/stock-picker'

const quickExamples = [
  '今日强势银行股',
  '最近5天涨幅靠前的科技股',
  '低位放量的医药股',
]

const poolTypeOptions = ['候选池', '观察池', '监控池', '自选池']

const loading = ref(false)
const queryText = ref('')
const result = ref<StockPickerQueryResult | null>(null)
const selectedRows = ref<StockPickerRow[]>([])

const poolDialogVisible = ref(false)
const poolMode = ref<'existing' | 'new'>('existing')
const pools = ref<StockPoolSummary[]>([])
const selectedPoolId = ref('')
const submittingPool = ref(false)
const newPool = reactive({
  name: '',
  pool_type: '候选池',
  description: '',
})

const visibleColumns = computed(() => {
  if (!result.value) return []
  const preferred = result.value.headers?.length ? result.value.headers : Object.keys(result.value.data_list[0] || {})
  return preferred.filter((key) => !['代码', '名称'].includes(key) && !key.startsWith('__'))
})

function useExample(example: string): void {
  queryText.value = example
  runQuery()
}

async function runQuery(): Promise<void> {
  if (!queryText.value.trim()) {
    ElMessage.warning('请输入选股条件')
    return
  }
  loading.value = true
  selectedRows.value = []
  try {
    result.value = await stockPickerApi.query(queryText.value.trim())
    if (result.value.total === 0) {
      ElMessage.info('本次没有筛出股票，可以换个条件试试')
    }
  } finally {
    loading.value = false
  }
}

function handleSelectionChange(rows: StockPickerRow[]): void {
  selectedRows.value = rows
}

function formatCell(column: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'number') return String(value)
  const text = String(value)
  if (column.includes('涨跌幅') || column.includes('涨幅') || column.includes('跌幅') || column.includes('换手率')) {
    const numeric = Number(text)
    if (!Number.isNaN(numeric)) {
      return `${numeric > 0 ? '+' : ''}${numeric}%`
    }
  }
  return text
}

function valueClass(column: string, value: unknown): string {
  const text = String(value ?? '')
  if (column.includes('涨跌幅') || column.includes('涨幅') || column.includes('跌幅') || column.includes('涨跌额')) {
    const numeric = Number(text)
    if (!Number.isNaN(numeric)) {
      return numeric >= 0 ? 'up' : 'down'
    }
  }
  return ''
}

function buildCodeList(): string {
  const targetRows = selectedRows.value.length > 0 ? selectedRows.value : (result.value?.data_list || [])
  return targetRows.map((row) => row.__meta.code).filter(Boolean).join('\n')
}

async function copyCodes(): Promise<void> {
  if (!result.value) return
  await navigator.clipboard.writeText(buildCodeList())
  ElMessage.success('代码列表已复制')
}

function downloadCodes(): void {
  if (!result.value) return
  const blob = new Blob([buildCodeList()], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `stock-picker-${Date.now()}.txt`
  anchor.click()
  URL.revokeObjectURL(url)
}

async function loadPools(): Promise<void> {
  const response = await stockPickerApi.listPools()
  pools.value = response.items || []
  if (!selectedPoolId.value && pools.value[0]) {
    selectedPoolId.value = pools.value[0].pool_id
  }
  if (pools.value.length === 0) {
    poolMode.value = 'new'
  }
}

async function openPoolDialog(): Promise<void> {
  await loadPools()
  poolDialogVisible.value = true
}

async function submitToPool(): Promise<void> {
  if (!result.value || selectedRows.value.length === 0) {
    ElMessage.warning('请先勾选要加入股池的股票')
    return
  }
  submittingPool.value = true
  try {
    let poolId = selectedPoolId.value
    if (poolMode.value === 'new') {
      if (!newPool.name.trim() || !newPool.pool_type.trim()) {
        ElMessage.warning('请先填写股池名称和类型')
        return
      }
      const pool = await stockPickerApi.createPool({
        name: newPool.name.trim(),
        pool_type: newPool.pool_type.trim(),
        description: newPool.description.trim() || undefined,
      })
      poolId = pool.pool_id
      selectedPoolId.value = poolId
    } else if (!poolId) {
      ElMessage.warning('请选择一个股池')
      return
    }

    const response = await stockPickerApi.addStocksToPool(poolId, {
      stocks: selectedRows.value.map((row) => ({
        ts_code: row.__meta.ts_code,
        code: row.__meta.code,
        name: row.__meta.name,
      })),
      source_run_id: result.value.run_id,
      source_query: result.value.query_condition || result.value.input,
      source_module: 'one_line_picker',
    })
    ElMessage.success(response.message)
    poolDialogVisible.value = false
  } finally {
    submittingPool.value = false
  }
}
</script>

<style scoped lang="scss">
.picker-page {
  display: grid;
  gap: 20px;
  padding: 1.5rem;
}

.hero-card,
.query-card,
.result-toolbar,
.result-card {
  border-radius: 24px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  background:
    radial-gradient(circle at top right, rgba(59, 130, 246, 0.12), transparent 30%),
    linear-gradient(145deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.98));
  box-shadow: 0 20px 60px rgba(15, 23, 42, 0.07);
}

.hero-card {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  padding: 28px 32px;
}

.eyebrow {
  margin: 0 0 8px;
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

h1 {
  margin: 0;
  color: #0f172a;
}

.description {
  margin: 10px 0 0;
  color: #475569;
  line-height: 1.7;
}

.hero-note {
  display: grid;
  gap: 6px;
  align-content: start;
  padding: 18px 20px;
  border-radius: 18px;
  background: linear-gradient(160deg, #eff6ff, #ffffff);
  color: #1e3a8a;
  min-width: 240px;
}

.hero-note strong {
  font-size: 18px;
}

.query-card,
.result-card {
  padding: 24px 28px;
}

.result-card {
  overflow: hidden;
}

.query-bar {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 14px;
}

.examples {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 14px;
  color: #64748b;
}

.examples button {
  border: none;
  background: rgba(226, 232, 240, 0.75);
  color: #334155;
  padding: 8px 12px;
  border-radius: 999px;
  cursor: pointer;
}

.result-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 22px;
}

.toolbar-main,
.toolbar-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.pill {
  display: grid;
  gap: 4px;
  padding: 10px 14px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.72);
}

.pill span {
  font-size: 12px;
  color: #64748b;
}

.pill strong {
  color: #0f172a;
}

.loading-state {
  padding: 16px 0;
}

.result-card :deep(.el-table__body-wrapper),
.result-card :deep(.el-table__header-wrapper),
.result-card :deep(.el-scrollbar__wrap) {
  overflow-x: auto !important;
}

.result-card :deep(.el-table) {
  min-width: 100%;
}

.stock-meta {
  display: grid;
}

.stock-meta strong {
  color: #0f172a;
}

.stock-meta span {
  color: #64748b;
  font-size: 12px;
}

.up {
  color: #dc2626;
}

.down {
  color: #16a34a;
}

.pool-dialog {
  display: grid;
  gap: 18px;
}

.dialog-block {
  display: grid;
  gap: 12px;
}

.hint,
.selection-summary {
  color: #64748b;
  margin: 0;
}

@media (max-width: 960px) {
  .hero-card,
  .result-toolbar {
    flex-direction: column;
  }

  .query-bar {
    grid-template-columns: 1fr;
  }
}
</style>
