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
            <el-tab-pane label="盈亏热力图" name="heatmap">
              <TradeReviewPnLHeatmap
                :ranking="stats?.stock_pnl_ranking || []"
                :loading="loading"
                @open-stock="openHeatmapStockReview"
              />
            </el-tab-pane>

            <el-tab-pane label="交易分析" name="analysis">
              <div v-if="stats" class="analysis-tab">
                <section class="analysis-hero">
                  <div>
                    <p class="analysis-kicker">Performance Analysis</p>
                    <h3>{{ analysisSummary.verdict }}</h3>
                    <p>{{ analysisSummary.description }}</p>
                  </div>
                  <div class="analysis-score" :class="analysisSummary.scoreClass">
                    <span>综合评分</span>
                    <strong>{{ analysisSummary.score }}</strong>
                    <small>{{ analysisSummary.level }}</small>
                  </div>
                </section>

                <section class="analysis-metrics">
                  <article
                    v-for="metric in analysisMetricCards"
                    :key="metric.label"
                    class="analysis-metric-card"
                    :class="metric.tone"
                  >
                    <span>{{ metric.label }}</span>
                    <strong>{{ metric.value }}</strong>
                    <small>{{ metric.hint }}</small>
                  </article>
                </section>

                <section class="analysis-columns">
                  <article class="analysis-panel">
                    <header>
                      <h4>收益质量</h4>
                      <span>参考回测收益 / 风险口径</span>
                    </header>
                    <div class="analysis-rows">
                      <div v-for="item in returnQualityRows" :key="item.label" class="analysis-row">
                        <span>{{ item.label }}</span>
                        <strong :class="item.className">{{ item.value }}</strong>
                      </div>
                    </div>
                  </article>

                  <article class="analysis-panel">
                    <header>
                      <h4>交易质量</h4>
                      <span>参考交割单常用复盘口径</span>
                    </header>
                    <div class="analysis-rows">
                      <div v-for="item in tradeQualityRows" :key="item.label" class="analysis-row">
                        <span>{{ item.label }}</span>
                        <strong :class="item.className">{{ item.value }}</strong>
                      </div>
                    </div>
                  </article>

                  <article class="analysis-panel">
                    <header>
                      <h4>持仓风险</h4>
                      <span>当前未了结风险暴露</span>
                    </header>
                    <div class="analysis-rows">
                      <div v-for="item in positionRiskRows" :key="item.label" class="analysis-row">
                        <span>{{ item.label }}</span>
                        <strong :class="item.className">{{ item.value }}</strong>
                      </div>
                    </div>
                  </article>
                </section>

                <section class="analysis-columns two">
                  <article class="analysis-panel">
                    <header>
                      <h4>个股贡献榜</h4>
                      <span>盈利来源是否集中</span>
                    </header>
                    <div class="analysis-ranking">
                      <button
                        v-for="item in topProfitStocks"
                        :key="`profit-${item.ts_code}`"
                        type="button"
                        class="analysis-rank-item"
                        @click="openStockSummaryReview(item)"
                      >
                        <span>
                          <strong>{{ item.name || item.code }}</strong>
                          <small>{{ item.ts_code }}</small>
                        </span>
                        <b :class="pnlClass(item.net_pnl)">{{ formatSignedAmount(item.net_pnl) }}</b>
                      </button>
                    </div>
                  </article>

                  <article class="analysis-panel">
                    <header>
                      <h4>亏损来源榜</h4>
                      <span>优先复盘最大拖累项</span>
                    </header>
                    <div class="analysis-ranking">
                      <button
                        v-for="item in topLossStocks"
                        :key="`loss-${item.ts_code}`"
                        type="button"
                        class="analysis-rank-item"
                        @click="openStockSummaryReview(item)"
                      >
                        <span>
                          <strong>{{ item.name || item.code }}</strong>
                          <small>{{ item.ts_code }}</small>
                        </span>
                        <b :class="pnlClass(item.net_pnl)">{{ formatSignedAmount(item.net_pnl) }}</b>
                      </button>
                    </div>
                  </article>
                </section>

                <section class="analysis-panel diagnosis-panel">
                  <header>
                    <h4>复盘诊断</h4>
                    <span>根据当前交割单数据自动生成</span>
                  </header>
                  <div class="diagnosis-list">
                    <div v-for="item in analysisDiagnostics" :key="item.title" class="diagnosis-item" :class="item.tone">
                      <strong>{{ item.title }}</strong>
                      <p>{{ item.description }}</p>
                    </div>
                  </div>
                </section>
              </div>
              <el-empty v-else description="暂无分析数据，请先导入交割单或刷新统计。" />
            </el-tab-pane>

            <el-tab-pane label="持仓股" name="holdings">
              <div class="holdings-tab">
                <template v-if="positions">
                  <div class="holdings-header">
                    <div>
                      <h3>持仓股工作台</h3>
                      <p>基于交割单自动推导当前未卖出的股票持仓，并支持加入自选或批量加入监听。</p>
                    </div>
                    <div class="holdings-header-actions">
                      <el-button :loading="positionsRefreshing" @click="refreshPositions">重算持仓</el-button>
                      <el-button
                        type="primary"
                        plain
                        :disabled="selectedPositions.length === 0"
                        @click="addSelectedToWatchlist"
                      >
                        加入自选
                      </el-button>
                      <el-button
                        type="primary"
                        plain
                        :disabled="selectedPositions.length === 0"
                        @click="openBatchDialog"
                      >
                        批量加入监听
                      </el-button>
                    </div>
                  </div>

                  <div class="holdings-meta">
                    <span>股票持仓 {{ stockPositions.length }} 只</span>
                    <span v-if="otherPositions.length > 0">另有 {{ otherPositions.length }} 只非股票资产未在此页展示</span>
                    <span v-if="positions.summary.latest_valuation_date">估值日 {{ formatTradeDate(positions.summary.latest_valuation_date) }}</span>
                    <span v-if="positions.summary.updated_at">更新于 {{ formatDateTime(positions.summary.updated_at) }}</span>
                  </div>

                  <template v-if="stockPositions.length > 0">
                    <section class="summary-grid">
                      <article class="summary-card">
                        <span>持仓数量</span>
                        <strong>{{ stockPositions.length }}</strong>
                      </article>
                      <article class="summary-card">
                        <span>持仓成本</span>
                        <strong>{{ formatAmount(positionStockSummary.total_cost) }}</strong>
                      </article>
                      <article class="summary-card">
                        <span>持仓市值</span>
                        <strong>{{ formatAmount(positionStockSummary.total_market_value) }}</strong>
                      </article>
                      <article class="summary-card" :class="pnlClass(positionStockSummary.total_unrealized_pnl)">
                        <span>浮盈浮亏</span>
                        <strong>{{ formatSignedAmount(positionStockSummary.total_unrealized_pnl) }}</strong>
                        <small>{{ formatSignedPct(positionStockSummary.total_unrealized_pnl_pct) }}</small>
                      </article>
                    </section>

                    <div class="toolbar">
                      <el-input
                        v-model="holdingsKeyword"
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
                          <span :class="pnlClass(row.unrealized_pnl)">{{ formatSignedAmount(row.unrealized_pnl) }}</span>
                        </template>
                      </el-table-column>
                      <el-table-column prop="unrealized_pnl_pct" label="盈亏比" width="110">
                        <template #default="{ row }">
                          <span :class="pnlClass(row.unrealized_pnl)">{{ formatSignedPct(row.unrealized_pnl_pct) }}</span>
                        </template>
                      </el-table-column>
                      <el-table-column prop="buy_count" label="买入笔数" width="100" />
                      <el-table-column prop="sell_count" label="卖出笔数" width="100" />
                      <el-table-column prop="last_trade_date" label="最后交易日" width="120">
                        <template #default="{ row }">{{ row.last_trade_date ? formatTradeDate(row.last_trade_date) : '-' }}</template>
                      </el-table-column>
                      <el-table-column label="操作" width="140" fixed="right">
                        <template #default="{ row }">
                          <el-button link type="primary" @click="openPositionReview(row.ts_code)">复盘</el-button>
                        </template>
                      </el-table-column>
                    </el-table>
                  </template>
                  <el-empty v-else description="当前分组暂时没有股票持仓，可能已经全部卖出，或剩余的是 ETF / 基金类资产。" />
                </template>
                <el-empty v-else description="持仓快照暂未生成" />
              </div>
            </el-tab-pane>

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

    <el-dialog
      v-model="batchDialogVisible"
      title="批量加入 V2 监听任务"
      width="500px"
      :close-on-click-modal="false"
    >
      <div class="dialog-body">
        <div class="batch-summary-card">
          <strong>已选持仓</strong>
          <span>{{ selectedPositions.length }} 只</span>
        </div>

        <div class="field-block">
          <label>V2 监听任务</label>
          <el-select
            v-model="selectedMonitorTaskId"
            class="dialog-select"
            placeholder="请选择监听任务"
            :loading="strategyTypeLoading"
          >
            <el-option
              v-for="item in monitorTasks"
              :key="item.task_id"
              :label="item.name"
              :value="item.task_id"
            >
              <div class="strategy-option">
                <span>{{ item.name }}</span>
                <small>{{ item.strategy_name }} · {{ item.target_scope_summary || item.target_scope?.summary }}</small>
              </div>
            </el-option>
          </el-select>
        </div>

        <p v-if="monitorTasks.length === 0" class="batch-hint">
          暂无可用的 V2 自定义股票列表监听任务，请先到策略中心创建监听任务。
        </p>
        <p v-else class="batch-hint">
          持仓股会加入所选任务的自定义股票列表；股票级参数后续保存在该任务配置中。
        </p>
      </div>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="batchDialogVisible = false">取消</el-button>
          <el-button
            type="primary"
            :loading="batchAdding"
            :disabled="!selectedMonitorTaskId"
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
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { tradeReviewApi } from '@/api'
import { addStockToStrategySceneTask, listStrategySceneTasks } from '@/api/modules/strategy-v2'
import TradeReviewPnLHeatmap from '@/components/review/TradeReviewPnLHeatmap.vue'
import { useUserStore } from '@/stores/user'
import type { StrategySceneTask } from '@/types/strategy-v2'
import type {
  TradeReviewGroupSummary,
  TradeReviewPositionItem,
  TradeReviewPositionResult,
  TradeReviewRecord,
  TradeReviewRecordListResult,
  TradeReviewStatsResult,
} from '@/api/modules/trade-review'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const loading = ref(false)
const groups = ref<TradeReviewGroupSummary[]>([])
const activeGroupId = ref('')
const activeTab = ref<'heatmap' | 'analysis' | 'holdings' | 'records' | 'stocks'>('records')
const category = ref('trade')
const keyword = ref('')
const holdingsKeyword = ref('')
const pageSize = ref(100)
const currentPage = ref(1)
const records = ref<TradeReviewRecordListResult>({ items: [], total: 0, skip: 0, limit: 100 })
const stats = ref<TradeReviewStatsResult | null>(null)
const positions = ref<TradeReviewPositionResult | null>(null)
const stockPage = ref(1)
const stockPageSize = ref(50)
const stockSortProp = ref<keyof TradeReviewStatsResult['stock_pnl_ranking'][number] | ''>('net_pnl')
const stockSortOrder = ref<'ascending' | 'descending' | null>('descending')
const positionsRefreshing = ref(false)
const selectedPositions = ref<TradeReviewPositionItem[]>([])

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
const batchDialogVisible = ref(false)
const monitorTasks = ref<StrategySceneTask[]>([])
const strategyTypeLoading = ref(false)
const batchAdding = ref(false)
const selectedMonitorTaskId = ref('')

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
const stockPositions = computed(() => {
  return (positions.value?.items || []).filter((item) => item.security_type !== 'other')
})
const otherPositions = computed(() => {
  return (positions.value?.items || []).filter((item) => item.security_type === 'other')
})
const profitableStockCount = computed(() => stockPositions.value.filter((item) => Number(item.unrealized_pnl || 0) > 0).length)
const lossStockCount = computed(() => stockPositions.value.filter((item) => Number(item.unrealized_pnl || 0) < 0).length)
const positionStockSummary = computed(() => {
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
  const text = holdingsKeyword.value.trim().toLowerCase()
  if (!text) return stockPositions.value
  return stockPositions.value.filter((item) => {
    return item.ts_code.toLowerCase().includes(text)
      || item.code.toLowerCase().includes(text)
      || (item.name || '').toLowerCase().includes(text)
  })
})
type StockPnlItem = TradeReviewStatsResult['stock_pnl_ranking'][number]
interface AnalysisRow {
  label: string
  value: string
  className?: string
}

const analysisBase = computed(() => {
  const ranking = stats.value?.stock_pnl_ranking || []
  const totalBuyAmount = Number(stats.value?.summary.total_buy_amount || 0)
  const totalSellAmount = Number(stats.value?.summary.total_sell_amount || 0)
  const totalFee = Number(stats.value?.summary.total_fee || 0)
  const totalNetPnl = ranking.reduce((sum, item) => sum + Number(item.net_pnl || 0), 0)
  const realizedPnl = ranking.reduce((sum, item) => sum + Number(item.realized_pnl || 0), 0)
  const unrealizedPnl = ranking.reduce((sum, item) => sum + Number(item.unrealized_pnl || 0), 0)
  const profitStocks = ranking.filter((item) => Number(item.net_pnl || 0) > 0)
  const lossStocks = ranking.filter((item) => Number(item.net_pnl || 0) < 0)
  const flatStocks = ranking.filter((item) => Number(item.net_pnl || 0) === 0)
  const grossProfit = profitStocks.reduce((sum, item) => sum + Number(item.net_pnl || 0), 0)
  const grossLoss = Math.abs(lossStocks.reduce((sum, item) => sum + Number(item.net_pnl || 0), 0))
  const investedBase = totalBuyAmount > 0 ? totalBuyAmount : ranking.reduce((sum, item) => sum + Number(item.total_buy_amount || 0), 0)
  const returnPct = investedBase > 0 ? totalNetPnl / investedBase * 100 : 0
  const realizedRatio = Math.abs(totalNetPnl) > 0 ? realizedPnl / totalNetPnl * 100 : 0
  const winRate = ranking.length > 0 ? profitStocks.length / ranking.length * 100 : 0
  const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : (grossProfit > 0 ? Infinity : 0)
  const avgPnl = ranking.length > 0 ? totalNetPnl / ranking.length : 0
  const topAbsPnl = [...ranking].sort((a, b) => Math.abs(Number(b.net_pnl || 0)) - Math.abs(Number(a.net_pnl || 0))).slice(0, 3)
  const totalAbsPnl = ranking.reduce((sum, item) => sum + Math.abs(Number(item.net_pnl || 0)), 0)
  const top3ContributionPct = totalAbsPnl > 0
    ? topAbsPnl.reduce((sum, item) => sum + Math.abs(Number(item.net_pnl || 0)), 0) / totalAbsPnl * 100
    : 0
  const feeRatePct = investedBase > 0 ? totalFee / investedBase * 100 : 0
  const reviewCoveragePct = Number(stats.value?.summary.review_coverage_pct || 0)
  const buySellRatio = stats.value?.summary.sell_count
    ? Number(stats.value.summary.buy_count || 0) / Number(stats.value.summary.sell_count || 1)
    : 0
  const monthlyCounts = stats.value?.monthly_trade_counts || []
  const busiestMonth = [...monthlyCounts].sort((a, b) => Number(b.count || 0) - Number(a.count || 0))[0]
  const avgMonthlyTrades = monthlyCounts.length > 0
    ? monthlyCounts.reduce((sum, item) => sum + Number(item.count || 0), 0) / monthlyCounts.length
    : 0

  return {
    ranking,
    totalBuyAmount,
    totalSellAmount,
    totalFee,
    totalNetPnl,
    realizedPnl,
    unrealizedPnl,
    profitStocks,
    lossStocks,
    flatStocks,
    grossProfit,
    grossLoss,
    investedBase,
    returnPct,
    realizedRatio,
    winRate,
    profitFactor,
    avgPnl,
    top3ContributionPct,
    feeRatePct,
    reviewCoveragePct,
    buySellRatio,
    busiestMonth,
    avgMonthlyTrades,
  }
})

const topProfitStocks = computed<StockPnlItem[]>(() => {
  return [...analysisBase.value.ranking]
    .filter((item) => Number(item.net_pnl || 0) > 0)
    .sort((a, b) => Number(b.net_pnl || 0) - Number(a.net_pnl || 0))
    .slice(0, 5)
})

const topLossStocks = computed<StockPnlItem[]>(() => {
  return [...analysisBase.value.ranking]
    .filter((item) => Number(item.net_pnl || 0) < 0)
    .sort((a, b) => Number(a.net_pnl || 0) - Number(b.net_pnl || 0))
    .slice(0, 5)
})

const analysisSummary = computed(() => {
  const base = analysisBase.value
  let score = 50
  if (base.totalNetPnl > 0) score += 15
  if (base.returnPct > 5) score += 10
  if (base.winRate >= 55) score += 10
  if (base.profitFactor >= 1.5) score += 10
  if (base.reviewCoveragePct >= 70) score += 8
  if (base.top3ContributionPct > 75) score -= 8
  if (base.returnPct < 0) score -= 15
  if (base.winRate < 40 && base.ranking.length >= 5) score -= 8
  score = Math.max(0, Math.min(100, Math.round(score)))

  if (score >= 80) {
    return {
      score,
      level: '较强',
      scoreClass: 'is-good',
      verdict: '收益结构相对健康',
      description: '当前交割单同时具备正收益、较好的盈利覆盖和较可控的集中度，后续重点复盘可复制的买卖模式。',
    }
  }
  if (score >= 60) {
    return {
      score,
      level: '中性',
      scoreClass: 'is-neutral',
      verdict: '收益质量仍需继续验证',
      description: '当前结果有可用信号，但还需要继续检查盈利来源、亏损拖累和复盘覆盖，避免偶然收益被误判为稳定模式。',
    }
  }
  return {
    score,
    level: '偏弱',
    scoreClass: 'is-risk',
    verdict: '交易质量需要优先复盘',
    description: '当前交割单暴露出收益、胜率、集中度或复盘覆盖中的一项或多项问题，建议先从最大亏损来源和未复盘记录开始处理。',
  }
})

const analysisMetricCards = computed(() => {
  const base = analysisBase.value
  return [
    {
      label: '总盈亏',
      value: formatSignedAmount(base.totalNetPnl),
      hint: `已实现 ${formatSignedAmount(base.realizedPnl)} / 浮动 ${formatSignedAmount(base.unrealizedPnl)}`,
      tone: pnlTone(base.totalNetPnl),
    },
    {
      label: '投入收益率',
      value: formatSignedPct(base.returnPct),
      hint: `按累计买入金额 ${formatAmount(base.investedBase)} 估算`,
      tone: pnlTone(base.returnPct),
    },
    {
      label: '胜率',
      value: formatSignedPct(base.winRate).replace('+', ''),
      hint: `盈利 ${base.profitStocks.length} 只 / 亏损 ${base.lossStocks.length} 只 / 持平 ${base.flatStocks.length} 只`,
      tone: base.winRate >= 50 ? 'is-good' : 'is-risk',
    },
    {
      label: '盈亏比',
      value: formatRatio(base.profitFactor),
      hint: `总盈利 ${formatAmount(base.grossProfit)} / 总亏损 ${formatAmount(base.grossLoss)}`,
      tone: base.profitFactor >= 1.2 ? 'is-good' : 'is-risk',
    },
    {
      label: 'Top3 集中度',
      value: formatSignedPct(base.top3ContributionPct).replace('+', ''),
      hint: '按绝对盈亏贡献估算，过高说明收益依赖少数股票',
      tone: base.top3ContributionPct > 70 ? 'is-risk' : 'is-neutral',
    },
    {
      label: '复盘覆盖',
      value: formatSignedPct(base.reviewCoveragePct).replace('+', ''),
      hint: `${stats.value?.summary.reviewed_count || 0} / ${stats.value?.summary.trade_records || 0} 笔成交已复盘`,
      tone: base.reviewCoveragePct >= 70 ? 'is-good' : 'is-risk',
    },
  ]
})

const returnQualityRows = computed<AnalysisRow[]>(() => {
  const base = analysisBase.value
  return [
    { label: '累计买入金额', value: formatAmount(base.totalBuyAmount) },
    { label: '累计卖出金额', value: formatAmount(base.totalSellAmount) },
    { label: '总费用', value: formatAmount(base.totalFee), className: base.totalFee > 0 ? 'is-loss' : '' },
    { label: '费用拖累', value: formatSignedPct(base.feeRatePct).replace('+', '') },
    { label: '平均单股盈亏', value: formatSignedAmount(base.avgPnl), className: pnlClass(base.avgPnl) },
    { label: '已实现占比', value: Number.isFinite(base.realizedRatio) ? formatSignedPct(base.realizedRatio).replace('+', '') : '--' },
  ]
})

const tradeQualityRows = computed<AnalysisRow[]>(() => {
  const base = analysisBase.value
  return [
    { label: '买入笔数', value: String(stats.value?.summary.buy_count || 0) },
    { label: '卖出笔数', value: String(stats.value?.summary.sell_count || 0) },
    { label: '买卖笔数比', value: formatRatio(base.buySellRatio) },
    { label: '月均交易笔数', value: base.avgMonthlyTrades.toFixed(1) },
    { label: '交易最密集月份', value: base.busiestMonth ? `${base.busiestMonth.month} · ${base.busiestMonth.count} 笔` : '--' },
    { label: '交易股票数', value: String(base.ranking.length) },
  ]
})

const positionRiskRows = computed<AnalysisRow[]>(() => {
  const summary = positionStockSummary.value
  return [
    { label: '当前股票持仓', value: `${stockPositions.value.length} 只` },
    { label: '持仓成本', value: formatAmount(summary.total_cost) },
    { label: '持仓市值', value: formatAmount(summary.total_market_value) },
    { label: '浮动盈亏', value: formatSignedAmount(summary.total_unrealized_pnl), className: pnlClass(summary.total_unrealized_pnl) },
    { label: '浮动收益率', value: formatSignedPct(summary.total_unrealized_pnl_pct), className: pnlClass(summary.total_unrealized_pnl_pct) },
    { label: '盈利 / 亏损持仓', value: `${profitableStockCount.value} / ${lossStockCount.value}` },
  ]
})

const analysisDiagnostics = computed(() => {
  const base = analysisBase.value
  const items: Array<{ title: string; description: string; tone: string }> = []

  if (base.totalNetPnl >= 0) {
    items.push({
      title: '先沉淀盈利模式',
      description: '当前总盈亏为正，建议优先复盘贡献榜中的股票，提炼共同买点、持仓周期、卖出触发和市场环境。',
      tone: 'is-good',
    })
  } else {
    items.push({
      title: '先处理亏损拖累',
      description: '当前总盈亏为负，建议从亏损来源榜开始，检查追高、逆势、仓位过重、止损延迟等共性问题。',
      tone: 'is-risk',
    })
  }

  if (base.profitFactor < 1) {
    items.push({
      title: '盈亏比不足',
      description: '总盈利无法覆盖总亏损，后续需要提高单笔盈利空间，或压缩亏损交易的平均亏损。',
      tone: 'is-risk',
    })
  } else {
    items.push({
      title: '盈亏比可继续观察',
      description: '当前盈利对亏损的覆盖尚可，下一步可以结合胜率判断是趋势持仓型，还是高胜率短线型。',
      tone: 'is-neutral',
    })
  }

  if (base.top3ContributionPct > 70) {
    items.push({
      title: '收益或亏损来源偏集中',
      description: 'Top3 股票贡献了大部分绝对盈亏，结论可能受少数样本影响，建议扩大样本或单独复盘这些股票。',
      tone: 'is-risk',
    })
  }

  if (base.reviewCoveragePct < 60) {
    items.push({
      title: '复盘覆盖不足',
      description: '已复盘成交占比偏低，交割单分析目前更多是财务统计，还不足以支撑交易模式打磨。',
      tone: 'is-risk',
    })
  }

  if (stockPositions.value.length > 0) {
    items.push({
      title: '关注未了结风险',
      description: '当前仍有持仓未了结，已实现收益不能代表最终结果，需要结合持仓浮盈亏和个股走势继续跟踪。',
      tone: 'is-neutral',
    })
  }

  return items
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

function pnlTone(value?: number | null): string {
  if (value == null || Number.isNaN(Number(value))) return 'is-neutral'
  if (Number(value) > 0) return 'is-good'
  if (Number(value) < 0) return 'is-risk'
  return 'is-neutral'
}

function formatRatio(value: number): string {
  if (!Number.isFinite(value)) return '∞'
  if (Number.isNaN(value)) return '--'
  return value.toFixed(2)
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
      await Promise.all([loadRecords(), loadStats(false), loadPositions()])
    } else {
      activeGroupId.value = ''
      records.value = { items: [], total: 0, skip: 0, limit: pageSize.value }
      stats.value = null
      positions.value = null
    }
  } finally {
    loading.value = false
  }
}

async function selectGroup(groupId: string): Promise<void> {
  activeGroupId.value = groupId
  currentPage.value = 1
  holdingsKeyword.value = ''
  selectedPositions.value = []
  await Promise.all([loadRecords(), loadStats(), loadPositions()])
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

async function loadStats(resetStockPage = true): Promise<void> {
  if (!activeGroupId.value) return
  stats.value = await tradeReviewApi.getStats(activeGroupId.value)
  if (resetStockPage) {
    stockPage.value = 1
  }
}

async function loadPositions(forceRefresh = false): Promise<void> {
  if (!activeGroupId.value) {
    positions.value = null
    return
  }
  positions.value = await tradeReviewApi.getPositions(activeGroupId.value, forceRefresh)
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
      tab: 'records',
      category: category.value,
      keyword: keyword.value.trim() || undefined,
      anchor: record.record_id,
      page: String(currentPage.value),
      pageSize: String(pageSize.value),
    },
  })
}

async function openStockSummaryReview(item: TradeReviewStatsResult['stock_pnl_ranking'][number]): Promise<void> {
  const summaryTsCodes = sortedPagedStockRanking.value.map((row) => row.ts_code)
  await openStockReviewFromCollection(item, {
    tab: 'stocks',
    summaryTsCodes,
    stockPage: String(stockPage.value),
    stockPageSize: String(stockPageSize.value),
  })
}

async function openHeatmapStockReview(payload: {
  item: TradeReviewStatsResult['stock_pnl_ranking'][number]
  summaryTsCodes: string[]
}): Promise<void> {
  await openStockReviewFromCollection(payload.item, {
    tab: 'heatmap',
    summaryTsCodes: payload.summaryTsCodes,
  })
}

function openPositionReview(tsCode: string): void {
  if (!activeGroupId.value) return
  router.push({
    name: 'PositionReviewSession',
    params: {
      groupId: activeGroupId.value,
      tsCode,
    },
    query: {
      tab: 'holdings',
    },
  })
}

async function openStockReviewFromCollection(
  item: TradeReviewStatsResult['stock_pnl_ranking'][number],
  options: {
    tab: 'stocks' | 'heatmap'
    summaryTsCodes: string[]
    stockPage?: string
    stockPageSize?: string
  },
): Promise<void> {
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
  router.push({
    name: 'TradeReviewSession',
    params: {
      groupId: activeGroupId.value,
      recordId: target.record_id,
    },
    query: {
      tab: options.tab,
      category: 'trade',
      keyword: item.ts_code,
      anchor: target.record_id,
      page: String(currentPage.value),
      pageSize: String(pageSize.value),
      stockPage: options.stockPage,
      stockPageSize: options.stockPageSize,
      navigationMode: 'stock-summary',
      summaryTsCodes: options.summaryTsCodes.join(','),
    },
  })
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

function handleSelectionChange(rows: TradeReviewPositionItem[]): void {
  selectedPositions.value = rows
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
    await Promise.all([loadRecords(), loadStats(), loadPositions()])
    ElMessage.success(`导入完成：新增 ${result.imported_rows} 条，跳过重复 ${result.duplicate_rows} 条`)
  } finally {
    importing.value = false
  }
}

async function refreshPositions(): Promise<void> {
  if (!activeGroupId.value) return
  positionsRefreshing.value = true
  try {
    positions.value = await tradeReviewApi.rebuildPositions(activeGroupId.value)
    selectedPositions.value = []
    ElMessage.success('持仓快照已重算')
  } finally {
    positionsRefreshing.value = false
  }
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

async function loadMonitorTasks(): Promise<void> {
  if (monitorTasks.value.length > 0) return
  strategyTypeLoading.value = true
  try {
    monitorTasks.value = (await listStrategySceneTasks()).filter(
      (item) => item.scene_type === 'listen' && item.target_scope?.scope_type === 'custom_stock_list',
    )
  } finally {
    strategyTypeLoading.value = false
  }
}

async function openBatchDialog(): Promise<void> {
  if (selectedPositions.value.length === 0) {
    ElMessage.warning('请先选择至少一只持仓股')
    return
  }
  await loadMonitorTasks()
  selectedMonitorTaskId.value = ''
  batchDialogVisible.value = true
}

async function handleBatchAddStrategy(): Promise<void> {
  if (!selectedMonitorTaskId.value || selectedPositions.value.length === 0) return
  batchAdding.value = true
  try {
    const tsCodes = selectedPositions.value.map((item) => item.ts_code)
    const results = await Promise.allSettled(
      tsCodes.map((tsCode) => addStockToStrategySceneTask(selectedMonitorTaskId.value, tsCode)),
    )
    const successCount = results.filter((item) => item.status === 'fulfilled').length
    const failedCount = results.length - successCount
    batchDialogVisible.value = false
    if (successCount > 0) {
      ElMessage.success(`已加入 ${successCount} 只持仓股到 V2 监听任务${failedCount > 0 ? `，失败 ${failedCount} 只` : ''}`)
    } else {
      ElMessage.warning('没有持仓股成功加入监听任务')
    }
  } finally {
    batchAdding.value = false
  }
}

watch(activeTab, async (value) => {
  if ((value === 'stocks' || value === 'heatmap' || value === 'analysis') && activeGroupId.value) {
    await loadStats(false)
    return
  }
  if (value === 'holdings' && activeGroupId.value && !positions.value) {
    await loadPositions()
  }
})

onMounted(() => {
  if (typeof route.query.groupId === 'string') {
    activeGroupId.value = route.query.groupId
  }
  if (
    route.query.tab === 'stocks'
    || route.query.tab === 'records'
    || route.query.tab === 'heatmap'
    || route.query.tab === 'analysis'
    || route.query.tab === 'holdings'
  ) {
    activeTab.value = route.query.tab
  } else if (route.query.tab === 'stats') {
    activeTab.value = 'heatmap'
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
  if (typeof route.query.stockPage === 'string') {
    const page = Number(route.query.stockPage)
    if (page > 0) stockPage.value = page
  }
  if (typeof route.query.stockPageSize === 'string') {
    const size = Number(route.query.stockPageSize)
    if (size > 0) stockPageSize.value = size
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

.holdings-tab {
  padding: 18px;
  border-radius: 18px;
  background: rgba(15, 23, 42, 0.03);
}

.holdings-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.holdings-header h3 {
  margin: 0 0 8px;
}

.holdings-header p {
  margin: 0;
  color: var(--el-text-color-secondary);
  line-height: 1.7;
}

.holdings-header-actions,
.detail-actions {
  display: inline-flex;
  gap: 8px;
  flex-wrap: wrap;
}

.holdings-meta {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 18px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
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

.analysis-tab {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.analysis-hero,
.analysis-panel,
.analysis-metric-card {
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: rgba(248, 250, 252, 0.82);
}

.analysis-hero {
  display: flex;
  align-items: stretch;
  justify-content: space-between;
  gap: 18px;
  padding: 18px;
  border-radius: 20px;
  background:
    radial-gradient(circle at top right, rgba(59, 130, 246, 0.12), transparent 30%),
    linear-gradient(135deg, rgba(248, 250, 252, 0.92), rgba(255, 255, 255, 0.96));
}

.analysis-kicker {
  margin: 0 0 8px;
  color: var(--el-color-primary);
  font-size: 12px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.analysis-hero h3 {
  margin: 0 0 8px;
  font-size: 22px;
}

.analysis-hero p {
  max-width: 760px;
  margin: 0;
  color: var(--el-text-color-secondary);
  line-height: 1.7;
}

.analysis-score {
  display: grid;
  place-items: center;
  min-width: 140px;
  padding: 16px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.86);
  box-shadow: inset 0 0 0 1px rgba(15, 23, 42, 0.06);
}

.analysis-score span,
.analysis-score small,
.analysis-metric-card span,
.analysis-metric-card small,
.analysis-panel header span,
.analysis-row span,
.analysis-rank-item small,
.diagnosis-item p {
  color: var(--el-text-color-secondary);
}

.analysis-score strong {
  font-size: 36px;
  line-height: 1.1;
}

.analysis-score.is-good strong,
.analysis-metric-card.is-good strong {
  color: #dc2626;
}

.analysis-score.is-risk strong,
.analysis-metric-card.is-risk strong {
  color: #16a34a;
}

.analysis-metrics {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 12px;
}

.analysis-metric-card {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 8px;
  padding: 14px;
  border-radius: 16px;
}

.analysis-metric-card strong {
  font-size: 22px;
  line-height: 1.1;
}

.analysis-metric-card small {
  line-height: 1.5;
}

.analysis-columns {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.analysis-columns.two {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.analysis-panel {
  min-width: 0;
  padding: 16px;
  border-radius: 18px;
}

.analysis-panel header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.analysis-panel h4 {
  margin: 0;
}

.analysis-panel header span {
  font-size: 12px;
}

.analysis-rows,
.analysis-ranking,
.diagnosis-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.analysis-row,
.analysis-rank-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.analysis-row {
  padding: 10px 0;
  border-bottom: 1px dashed rgba(15, 23, 42, 0.08);
}

.analysis-row:last-child {
  border-bottom: 0;
}

.analysis-rank-item {
  width: 100%;
  padding: 12px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.72);
  cursor: pointer;
  text-align: left;
}

.analysis-rank-item span {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.analysis-rank-item b {
  white-space: nowrap;
}

.diagnosis-panel {
  background: rgba(15, 23, 42, 0.03);
}

.diagnosis-item {
  padding: 13px 14px;
  border-radius: 14px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: rgba(255, 255, 255, 0.78);
}

.diagnosis-item p {
  margin: 6px 0 0;
  line-height: 1.7;
}

.diagnosis-item.is-good {
  border-color: rgba(220, 38, 38, 0.16);
  background: rgba(254, 242, 242, 0.7);
}

.diagnosis-item.is-risk {
  border-color: rgba(22, 163, 74, 0.16);
  background: rgba(240, 253, 244, 0.72);
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
  .analysis-metrics,
  .analysis-columns,
  .analysis-columns.two {
    grid-template-columns: 1fr;
  }

  .stock-pnl-header,
  .holdings-header,
  .analysis-hero,
  .analysis-panel header {
    flex-direction: column;
  }

  .analysis-score {
    width: 100%;
  }
}
</style>
