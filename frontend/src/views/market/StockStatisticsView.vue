<template>
  <div class="stock-statistics-page">
    <section class="workspace-shell">
      <aside class="secondary-nav">
        <div class="nav-head">
          <span>专题导航</span>
          <small>盘后统计</small>
        </div>

        <div
          v-for="group in navGroups"
          :key="group.key"
          class="nav-group"
        >
          <button class="nav-group-toggle" type="button" @click="toggleGroup(group.key)">
            <div>
              <strong>{{ group.title }}</strong>
              <span>{{ group.items.length }} 个页面</span>
            </div>
            <span class="nav-group-arrow">{{ expandedGroups.includes(group.key) ? '−' : '+' }}</span>
          </button>

          <div v-if="expandedGroups.includes(group.key)" class="nav-group-items">
            <button
              v-for="item in group.items"
              :key="item.key"
              type="button"
              class="nav-item"
              :class="{ active: selectedPage === item.key }"
              @click="selectedPage = item.key"
            >
              <span class="nav-item-index">{{ item.index }}</span>
              <span class="nav-item-text">
                <strong>{{ item.title }}</strong>
                <small>{{ item.shortDescription }}</small>
              </span>
            </button>
          </div>
        </div>
      </aside>

      <div class="content-shell">
        <header class="content-toolbar">
          <div class="toolbar-main">
            <div class="toolbar-title-row">
              <p class="toolbar-tag">{{ currentPage.groupTitle }}</p>
              <h2>{{ currentPage.title }}</h2>
              <span class="toolbar-meta">{{ currentPage.filterMode === 'date' ? selectedDate : currentPage.filterMode === 'period' ? selectedPeriodLabel : '最近一年' }}</span>
            </div>
            <p class="toolbar-description">{{ currentPage.description }}</p>
          </div>

          <div class="toolbar-actions">
            <template v-if="currentPage.filterMode === 'date'">
              <div class="filter-block">
                <span class="filter-label">交易日</span>
                <el-date-picker
                  v-model="selectedDate"
                  type="date"
                  format="YYYY-MM-DD"
                  value-format="YYYY-MM-DD"
                  :disabled-date="disabledDate"
                  :clearable="false"
                  style="width: 180px"
                />
              </div>
            </template>

            <template v-else-if="currentPage.filterMode === 'period'">
              <div class="filter-block">
                <span class="filter-label">统计周期</span>
                <el-select v-model="selectedPeriod" style="width: 180px">
                  <el-option
                    v-for="item in periodOptions"
                    :key="item.value"
                    :label="item.label"
                    :value="item.value"
                  />
                </el-select>
              </div>
            </template>

            <div v-else class="filter-block filter-static">
              <span class="filter-label">统计范围</span>
              <strong>最近一年</strong>
              <small>无需额外切换</small>
            </div>
          </div>
        </header>

        <div v-if="loadingSection || activeWarnings.length" class="context-bar">
          <span v-if="loadingSection" class="context-pill">后端数据加载中</span>
          <span v-for="warning in activeWarnings" :key="warning" class="context-pill warning">
            {{ warning }}
          </span>
        </div>

        <section v-if="selectedPage === 'limit-fleet'" class="panel-stack">
          <div class="table-card">
            <div class="section-head minimal">
              <span class="section-badge">{{ selectedLimitRecords.length }} 只涨停股</span>
            </div>

            <div class="ladder-table">
              <div
                v-for="group in limitFleetGroups"
                :key="group.key"
                class="ladder-row"
              >
                <div class="ladder-level">
                  <strong>{{ group.label }}</strong>
                  <span>{{ group.items.length }} 只</span>
                </div>
                <div class="ladder-content">
                  <div v-if="group.items.length" class="stock-strip-grid">
                    <article
                      v-for="item in group.items"
                      :key="item.tsCode"
                      class="stock-strip-card"
                    >
                      <div class="stock-strip-head">
                        <strong>{{ item.name }}</strong>
                        <span>{{ item.code }}</span>
                      </div>
                      <div class="stock-strip-meta">
                        <span>{{ item.theme }}</span>
                        <span>{{ item.limitType }}</span>
                        <span>{{ item.limitTime }}</span>
                        <span>{{ formatMoney(item.sealAmount) }}</span>
                      </div>
                    </article>
                  </div>
                  <div v-else class="ladder-empty">当前层级暂无样本</div>
                </div>
              </div>
            </div>
          </div>

          <div class="table-card">
            <div class="section-head">
              <h3>涨停明细</h3>
            </div>
            <el-table :data="selectedLimitRecords" class="dense-table" stripe size="small" height="420">
              <el-table-column prop="boardCount" label="连板高度" width="90">
                <template #default="{ row }">{{ formatBoardBand(row.boardCount) }}</template>
              </el-table-column>
              <el-table-column prop="code" label="代码" width="110" />
              <el-table-column prop="name" label="名称" width="120" />
              <el-table-column prop="theme" label="题材" min-width="150" />
              <el-table-column prop="limitType" label="涨停类型" width="110" />
              <el-table-column prop="limitTime" label="涨停时间" width="110" />
              <el-table-column prop="sealAmount" label="封单额" width="120">
                <template #default="{ row }">{{ formatMoney(row.sealAmount) }}</template>
              </el-table-column>
            </el-table>
          </div>
        </section>

        <section v-else-if="selectedPage === 'limit-types'" class="panel-stack">
          <div class="table-card">
            <div class="ladder-table">
              <div
                v-for="item in limitTypeStats"
                :key="item.type"
                class="ladder-row"
              >
                <div class="ladder-level neutral">
                  <strong>{{ item.type }}</strong>
                  <span>{{ item.count }} 只 · {{ formatPercent(item.share) }}</span>
                </div>
                <div class="ladder-content">
                  <div v-if="item.items.length" class="stock-strip-grid">
                    <article
                      v-for="stock in item.items"
                      :key="stock.tsCode"
                      class="stock-strip-card neutral"
                    >
                      <div class="stock-strip-head">
                        <strong>{{ stock.name }}</strong>
                        <span>{{ stock.code }}</span>
                      </div>
                      <div class="stock-strip-meta">
                        <span>{{ stock.theme }}</span>
                        <span>{{ formatBoardBand(stock.boardCount) }}</span>
                        <span>{{ stock.limitTime }}</span>
                        <span>{{ formatMoney(stock.sealAmount) }}</span>
                      </div>
                    </article>
                  </div>
                  <div v-else class="ladder-empty">当前类型暂无样本</div>
                </div>
              </div>
            </div>
          </div>

          <div class="table-card">
            <div class="section-head">
              <h3>类型明细</h3>
            </div>
            <el-table :data="limitTypeDetailRows" class="dense-table" stripe size="small" height="460">
              <el-table-column prop="type" label="类型" width="110" />
              <el-table-column prop="code" label="代码" width="110" />
              <el-table-column prop="name" label="名称" width="120" />
              <el-table-column prop="theme" label="题材" min-width="150" />
              <el-table-column prop="boardBandLabel" label="连板高度" width="100" />
              <el-table-column prop="limitTime" label="涨停时间" width="110" />
              <el-table-column prop="sealAmount" label="封单额" width="120">
                <template #default="{ row }">{{ formatMoney(row.sealAmount) }}</template>
              </el-table-column>
            </el-table>
          </div>
        </section>

        <section v-else-if="selectedPage === 'leader-cycle'" class="panel-stack">
          <div class="table-card">
            <div class="section-head">
              <div>
                <h3>模块 A：涨停次数排名</h3>
                <p>默认扩到前 30 只，便于直接看更长的龙头序列。</p>
              </div>
            </div>
            <el-table :data="leaderCountRanking" class="dense-table" stripe size="small" height="420">
              <el-table-column prop="rank" label="排名" width="80" />
              <el-table-column prop="code" label="代码" width="110" />
              <el-table-column prop="name" label="名称" width="120" />
              <el-table-column prop="theme" label="题材" min-width="150" />
              <el-table-column prop="limitCount" label="周期涨停次数" width="130" sortable />
              <el-table-column prop="maxBoard" label="最高连板" width="110" sortable>
                <template #default="{ row }">{{ formatBoardBand(row.maxBoard) }}</template>
              </el-table-column>
            </el-table>
          </div>

          <div class="chart-card">
            <div class="section-head">
              <div>
                <h3>模块 B：连板晋级率</h3>
                <p>晋级维度改为 `1-2 / 2-3 / 3-4 / 4-5 / 5-6 / 6-7 / 7+`，并额外增加“昨日涨停今日仍涨停”的总晋级率。</p>
              </div>
            </div>
            <VChart class="chart-canvas tall-chart compact-chart" :option="promotionRateOption" autoresize />
          </div>
        </section>

        <section v-else-if="selectedPage === 'market-sentiment'" class="panel-stack">
          <div class="metric-grid">
            <article class="metric-card highlight">
              <span>昨日涨停今日晋级率</span>
              <strong>{{ formatPercent(latestSentiment.promotionRate) }}</strong>
              <small>总晋级口径：昨日涨停今日仍涨停</small>
            </article>
            <article class="metric-card">
              <span>今日炸板率</span>
              <strong>{{ formatPercent(latestSentiment.explosionRate) }}</strong>
              <small>炸板 {{ latestSentiment.explodedCount }} / 尝试涨停 {{ latestSentiment.tryLimitCount }}</small>
            </article>
            <article class="metric-card">
              <span>昨日涨停股今日平均涨跌幅</span>
              <strong>{{ formatSignedPercent(latestSentiment.avgFollowReturn) }}</strong>
              <small>更接近“昨天买入后今天收盘表现”</small>
            </article>
            <article class="metric-card">
              <span>昨日涨停股今日开盘溢价</span>
              <strong>{{ formatSignedPercent(latestSentiment.openPremium) }}</strong>
              <small>更接近“隔夜持有后开盘兑现空间”</small>
            </article>
            <article class="metric-card">
              <span>昨日涨停股今日盘中最高溢价</span>
              <strong>{{ formatSignedPercent(latestSentiment.highPremium) }}</strong>
              <small>用于和收盘平均涨跌幅形成对比</small>
            </article>
            <article class="metric-card">
              <span>今日涨停家数 / 昨日涨停家数</span>
              <strong>{{ latestSentiment.limitCount }} / {{ latestSentiment.prevLimitCount }}</strong>
              <small>最新交易日 {{ latestTradeDate }}</small>
            </article>
          </div>

          <div class="chart-card">
            <div class="section-head with-inline-tabs">
              <h3>情绪趋势</h3>
              <div class="inline-tabs">
                <button
                  v-for="tab in sentimentTrendTabs"
                  :key="tab.value"
                  type="button"
                  class="inline-tab"
                  :class="{ active: sentimentTrendTab === tab.value }"
                  @click="sentimentTrendTab = tab.value"
                >
                  {{ tab.label }}
                </button>
              </div>
            </div>
            <VChart class="chart-canvas compact-chart" :option="sentimentTrendOption" autoresize />
          </div>
        </section>

        <section v-else-if="selectedPage === 'stage-gainers'" class="panel-stack">
          <div class="table-card">
            <div class="section-head minimal">
              <span class="section-badge">默认展示前 30 只</span>
            </div>

            <div class="ladder-table">
              <div
                v-for="group in stageGainGroups"
                :key="group.label"
                class="ladder-row"
              >
                <div class="ladder-level warm">
                  <strong>{{ group.label }}</strong>
                  <span>{{ group.items.length }} 只</span>
                </div>
                <div class="ladder-content">
                  <div v-if="group.items.length" class="stock-strip-grid">
                    <article
                      v-for="item in group.items"
                      :key="item.code"
                      class="stock-strip-card warm"
                    >
                      <div class="stock-strip-head">
                        <strong>{{ item.name }}</strong>
                        <span>{{ item.code }}</span>
                      </div>
                      <div class="stock-strip-meta">
                        <span>{{ item.theme }}</span>
                        <span>{{ formatPercent(item.gainPct) }}</span>
                        <span>回撤 {{ formatSignedPercent(item.maxDrawdownPct) }}</span>
                        <span>{{ formatPrice(item.currentPrice) }}</span>
                      </div>
                    </article>
                  </div>
                  <div v-else class="ladder-empty">当前层级暂无样本</div>
                </div>
              </div>
            </div>
          </div>

          <div class="table-card">
            <div class="section-head">
              <h3>涨幅明细</h3>
            </div>
            <el-table :data="stageGainRanking" class="dense-table" stripe size="small" height="430">
              <el-table-column prop="rank" label="排名" width="80" />
              <el-table-column prop="code" label="代码" width="110" />
              <el-table-column prop="name" label="名称" width="130" />
              <el-table-column prop="theme" label="题材" min-width="150" />
              <el-table-column prop="startPrice" label="周期起始价" width="120">
                <template #default="{ row }">{{ formatPrice(row.startPrice) }}</template>
              </el-table-column>
              <el-table-column prop="currentPrice" label="当前价" width="110">
                <template #default="{ row }">{{ formatPrice(row.currentPrice) }}</template>
              </el-table-column>
              <el-table-column prop="gainPct" label="涨幅%" width="110">
                <template #default="{ row }">{{ formatPercent(row.gainPct) }}</template>
              </el-table-column>
              <el-table-column prop="maxDrawdownPct" label="最大回撤" width="120">
                <template #default="{ row }">{{ formatSignedPercent(row.maxDrawdownPct) }}</template>
              </el-table-column>
            </el-table>
          </div>
        </section>

        <section v-else-if="selectedPage === 'nextday-win-rate'" class="table-card">
          <div class="section-head controls-only">
            <label class="toggle-chip">
              <input v-model="nextDayQualifiedOnly" type="checkbox">
              <span>仅看交易日数 ≥ 3</span>
            </label>
          </div>
          <el-table :data="nextDayWinRanking" class="dense-table" stripe size="small" height="640">
            <el-table-column prop="rank" label="排名" width="80" />
            <el-table-column prop="code" label="代码" width="110" />
            <el-table-column prop="name" label="名称" width="120" />
            <el-table-column prop="tradeDays" label="交易日数" width="110" sortable />
            <el-table-column prop="upDays" label="红盘天数" width="110" sortable />
            <el-table-column prop="winRate" label="胜率" width="100" sortable>
              <template #default="{ row }">{{ formatPercent(row.winRate) }}</template>
            </el-table-column>
            <el-table-column prop="avgReturn" label="平均涨幅" width="120" sortable>
              <template #default="{ row }">{{ formatSignedPercent(row.avgReturn) }}</template>
            </el-table-column>
            <el-table-column prop="theme" label="题材" min-width="150" />
          </el-table>
        </section>

        <section v-else-if="selectedPage === 'streak-board'" class="table-card">
          <div class="section-head controls-only">
            <div class="inline-tabs">
              <button
                v-for="tab in streakTabs"
                :key="tab.value"
                type="button"
                class="inline-tab"
                :class="{ active: streakTab === tab.value }"
                @click="streakTab = tab.value"
              >
                {{ tab.label }}
              </button>
            </div>
          </div>

          <el-table :data="streakRanking" class="dense-table" stripe size="small">
            <el-table-column prop="rank" label="排名" width="80" />
            <el-table-column prop="code" label="代码" width="110" />
            <el-table-column prop="name" label="名称" width="130" />
            <el-table-column :label="streakTab === 'up' ? '最长连涨天数' : '最长连跌天数'" width="140">
              <template #default="{ row }">{{ row.days }}</template>
            </el-table-column>
            <el-table-column prop="dateRange" label="发生时间段" min-width="220" />
            <el-table-column prop="theme" label="题材" min-width="160" />
          </el-table>
        </section>

        <section v-else class="table-card">
          <div class="section-head minimal">
            <span class="section-badge">当前展示 {{ reboundRanking.length }} 只</span>
          </div>
          <el-table :data="reboundRanking" class="dense-table" stripe size="small" height="640">
            <el-table-column prop="rank" label="排名" width="80" sortable />
            <el-table-column prop="code" label="股票代码" width="110" />
            <el-table-column prop="name" label="股票名称" width="130" />
            <el-table-column prop="lowestDate" label="最低点日期" width="130" />
            <el-table-column prop="lowestPrice" label="最低价" width="110" sortable>
              <template #default="{ row }">{{ formatPrice(row.lowestPrice) }}</template>
            </el-table-column>
            <el-table-column prop="currentPrice" label="当前价" width="110" sortable>
              <template #default="{ row }">{{ formatPrice(row.currentPrice) }}</template>
            </el-table-column>
            <el-table-column prop="reboundPct" label="反弹涨幅%" width="130" sortable>
              <template #default="{ row }">{{ formatPercent(row.reboundPct) }}</template>
            </el-table-column>
            <el-table-column prop="periodLowLabel" label="周期区间" min-width="180" />
          </el-table>
        </section>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'

import {
  stockStatisticsApi,
  type StockStatisticsLeaderCycle,
  type StockStatisticsLimitItem,
  type StockStatisticsLimitSnapshot,
  type StockStatisticsNextdayWinRate,
  type StockStatisticsRebound,
  type StockStatisticsSentiment,
  type StockStatisticsStageGainers,
  type StockStatisticsStreakBoard,
} from '@/api/modules/stock-statistics'

use([
  CanvasRenderer,
  LineChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
])

type NavGroupKey = 'limit' | 'trend'
type PageKey =
  | 'limit-fleet'
  | 'limit-types'
  | 'leader-cycle'
  | 'market-sentiment'
  | 'stage-gainers'
  | 'nextday-win-rate'
  | 'streak-board'
  | 'rebound-board'
type FilterMode = 'date' | 'period' | 'none'
type PeriodValue = '1w' | '1m' | '3m'
type SentimentTrendKey = 'promotion' | 'explosion' | 'closeReturn' | 'openPremium' | 'highPremium'
type StreakTabKey = 'up' | 'down'

interface PageDefinition {
  key: PageKey
  title: string
  shortDescription: string
  description: string
  groupTitle: string
  context: string
  filterMode: FilterMode
  index: string
}

interface SentimentSnapshot {
  date: string
  promotionRate: number
  totalPromotionRate: number
  explosionRate: number
  explodedCount: number
  tryLimitCount: number
  avgFollowReturn: number
  openPremium: number
  highPremium: number
  limitCount: number
  prevLimitCount: number
}

const limitTypes = ['一字板', 'T字板', '换手板', '回封板', '尾盘板']
const boardBands = [
  { label: '7板+', match: (count: number) => count >= 7 },
  { label: '6板', match: (count: number) => count === 6 },
  { label: '5板', match: (count: number) => count === 5 },
  { label: '4板', match: (count: number) => count === 4 },
  { label: '3板', match: (count: number) => count === 3 },
  { label: '2板', match: (count: number) => count === 2 },
  { label: '首板', match: (count: number) => count <= 1 },
]
const stageGainBands = [
  { label: '100%+', min: 100, max: Number.POSITIVE_INFINITY },
  { label: '80-100%', min: 80, max: 100 },
  { label: '60-80%', min: 60, max: 80 },
  { label: '40-60%', min: 40, max: 60 },
  { label: '20-40%', min: 20, max: 40 },
]
const periodOptions = [
  { label: '近一周', value: '1w' as PeriodValue, days: 5 },
  { label: '近一个月', value: '1m' as PeriodValue, days: 22 },
  { label: '近三个月', value: '3m' as PeriodValue, days: 66 },
]
const sentimentTrendTabs = [
  { label: '晋级率', value: 'promotion' as SentimentTrendKey },
  { label: '炸板率', value: 'explosion' as SentimentTrendKey },
  { label: '平均涨跌幅', value: 'closeReturn' as SentimentTrendKey },
  { label: '开盘溢价', value: 'openPremium' as SentimentTrendKey },
  { label: '最高溢价', value: 'highPremium' as SentimentTrendKey },
]
const streakTabs = [
  { label: '连涨天数排名', value: 'up' as StreakTabKey },
  { label: '连跌天数排名', value: 'down' as StreakTabKey },
]

const navGroups: Array<{ key: NavGroupKey; title: string; items: PageDefinition[] }> = [
  {
    key: 'limit',
    title: '打板组',
    items: [
      {
        key: 'limit-fleet',
        index: '01',
        title: '涨停雁阵图',
        shortDescription: '分层表格',
        description: '按连板高度分层展示当日涨停股结构，优先看高度、题材和封单密度。',
        groupTitle: '打板组',
        context: '日期切换后同步刷新雁阵层级和明细表',
        filterMode: 'date',
      },
      {
        key: 'limit-types',
        index: '02',
        title: '涨停类型统计',
        shortDescription: '类型结构',
        description: '按一字板、T 字板、换手板、回封板、尾盘板拆开看当天的封板结构。',
        groupTitle: '打板组',
        context: '更偏向结构复盘，不强调花哨图形',
        filterMode: 'date',
      },
      {
        key: 'leader-cycle',
        index: '03',
        title: '龙头周期榜',
        shortDescription: '前 30 + 晋级率',
        description: '模块 A 展示周期内涨停次数前 30，模块 B 追踪各层级晋级率和总晋级率。',
        groupTitle: '打板组',
        context: '两个模块改为上下布局，便于同屏阅读',
        filterMode: 'period',
      },
      {
        key: 'market-sentiment',
        index: '04',
        title: '市场情绪概览',
        shortDescription: '最新日 + 周期趋势',
        description: '顶部固定显示最新交易日核心指标，右上角只切换下方趋势范围。',
        groupTitle: '打板组',
        context: '默认锚定最新交易日，周期切换只影响趋势范围',
        filterMode: 'period',
      },
    ],
  },
  {
    key: 'trend',
    title: '趋势组',
    items: [
      {
        key: 'stage-gainers',
        index: '05',
        title: '涨幅雁阵图',
        shortDescription: '涨幅分层',
        description: '按区间涨幅分层展示强势股群体，同时保留题材和回撤等附加信息。',
        groupTitle: '趋势组',
        context: '默认按前 30 只强势股做分层统计',
        filterMode: 'period',
      },
      {
        key: 'nextday-win-rate',
        index: '06',
        title: '次日胜率榜',
        shortDescription: '与涨停解绑',
        description: '围绕样本事件统计次日上涨概率，不再绑定“涨停次日”口径。',
        groupTitle: '趋势组',
        context: '默认展示前 30，支持最小样本过滤',
        filterMode: 'period',
      },
      {
        key: 'streak-board',
        index: '07',
        title: '连涨/连跌榜',
        shortDescription: 'Top 30',
        description: '展示当前周期内最长连涨和最长连跌排行，默认扩到前 30。',
        groupTitle: '趋势组',
        context: '按周期切换当前统计窗口，并以标签页切换方向',
        filterMode: 'period',
      },
      {
        key: 'rebound-board',
        index: '08',
        title: '高低点策略榜',
        shortDescription: '低点反弹',
        description: '从周期起点到当前日，计算区间最低点反弹幅度并按前 30 排名。',
        groupTitle: '趋势组',
        context: '默认看前 30，突出最低点和反弹幅度',
        filterMode: 'period',
      },
    ],
  },
]

const fallbackLatestTradeDate = getLatestWeekday()
const fallbackTradeDates = generateTradeDates(fallbackLatestTradeDate, 30)

const selectedPage = ref<PageKey>('limit-fleet')
const expandedGroups = ref<NavGroupKey[]>(['limit', 'trend'])
const latestTradeDate = ref(fallbackLatestTradeDate)
const availableTradeDates = ref<string[]>(fallbackTradeDates)
const selectedDate = ref(fallbackLatestTradeDate)
const selectedPeriod = ref<PeriodValue>('1m')
const sentimentTrendTab = ref<SentimentTrendKey>('promotion')
const nextDayQualifiedOnly = ref(true)
const streakTab = ref<StreakTabKey>('up')
const loadingSection = ref('')
const loadFailureMessage = ref('')

const limitSnapshotData = ref<StockStatisticsLimitSnapshot | null>(null)
const leaderCycleData = ref<StockStatisticsLeaderCycle | null>(null)
const sentimentData = ref<StockStatisticsSentiment | null>(null)
const stageGainersData = ref<StockStatisticsStageGainers | null>(null)
const nextdayWinRateData = ref<StockStatisticsNextdayWinRate | null>(null)
const streakBoardData = ref<StockStatisticsStreakBoard | null>(null)
const reboundData = ref<StockStatisticsRebound | null>(null)

const currentPage = computed(() => {
  for (const group of navGroups) {
    const page = group.items.find((item) => item.key === selectedPage.value)
    if (page) return page
  }
  return navGroups[0].items[0]
})

const selectedPeriodLabel = computed(() => {
  return periodOptions.find((item) => item.value === selectedPeriod.value)?.label || ''
})

const availableTradeDateSet = computed(() => new Set(availableTradeDates.value))
const activeWarnings = computed(() => {
  const warnings: string[] = []
  if (selectedPage.value === 'limit-fleet' || selectedPage.value === 'limit-types') {
    warnings.push(...(limitSnapshotData.value?.warnings || []))
  }
  if (selectedPage.value === 'leader-cycle') {
    warnings.push(...(leaderCycleData.value?.warnings || []))
  }
  if (selectedPage.value === 'market-sentiment') {
    warnings.push(...(sentimentData.value?.warnings || []))
  }
  if (selectedPage.value === 'stage-gainers') {
    warnings.push(...(stageGainersData.value?.warnings || []))
  }
  if (selectedPage.value === 'nextday-win-rate') {
    warnings.push(...(nextdayWinRateData.value?.warnings || []))
  }
  if (selectedPage.value === 'streak-board') {
    warnings.push(...(streakBoardData.value?.warnings || []))
  }
  if (selectedPage.value === 'rebound-board') {
    warnings.push(...(reboundData.value?.warnings || []))
  }
  if (loadFailureMessage.value) {
    warnings.push(loadFailureMessage.value)
  }
  return warnings
})

const selectedLimitRecords = computed(() => {
  if (limitSnapshotData.value?.limit_fleet.detail?.length) {
    return limitSnapshotData.value.limit_fleet.detail.map(mapLimitItem)
  }
  return []
})

const limitFleetGroups = computed(() => {
  if (limitSnapshotData.value?.limit_fleet.groups?.length) {
    return limitSnapshotData.value.limit_fleet.groups.map((group) => ({
      key: group.key,
      label: group.label,
      items: group.items.map(mapLimitItem),
    }))
  }
  return boardBands.map((band) => ({
    key: band.label,
    label: band.label,
    items: selectedLimitRecords.value.filter((item) => band.match(item.boardCount)),
  }))
})

const limitTypeStats = computed(() => {
  if (limitSnapshotData.value?.limit_types.groups?.length) {
    return limitSnapshotData.value.limit_types.groups.map((group) => ({
      type: group.type,
      count: group.count,
      share: group.share,
      items: group.items.map(mapLimitItem),
    }))
  }
  const total = Math.max(1, selectedLimitRecords.value.length)
  return limitTypes.map((type) => {
    const items = selectedLimitRecords.value.filter((item) => item.limitType === type)
    return {
      type,
      count: items.length,
      share: (items.length / total) * 100,
      items,
    }
  })
})

const limitTypeDetailRows = computed(() => {
  if (limitSnapshotData.value?.limit_types.detail?.length) {
    return limitSnapshotData.value.limit_types.detail.map((item) => ({
      ...mapLimitItem(item),
      type: item.type,
      boardBandLabel: item.board_band_label,
    }))
  }
  return limitTypeStats.value.flatMap((group) => group.items.map((item) => ({
    ...item,
    type: group.type,
    boardBandLabel: formatBoardBand(item.boardCount),
  })))
})

const leaderCountRanking = computed(() => {
  if (leaderCycleData.value?.rankings?.length) {
    return leaderCycleData.value.rankings.map((item) => ({
      rank: item.rank,
      code: item.code,
      name: item.name,
      theme: item.theme,
      limitCount: item.limit_count,
      maxBoard: item.max_board,
    }))
  }
  return []
})
const promotionTrendSeries = computed(() => {
  if (leaderCycleData.value?.promotion_trend?.length) {
    return leaderCycleData.value.promotion_trend
  }
  return []
})

const promotionRateOption = computed(() => ({
  color: ['#2563eb', '#0f766e', '#f59e0b', '#ef4444', '#7c3aed', '#14b8a6', '#64748b', '#111827'],
  tooltip: {
    trigger: 'axis',
  },
  legend: {
    top: 0,
    type: 'scroll',
  },
  grid: {
    left: 38,
    right: 22,
    top: 56,
    bottom: 36,
    containLabel: true,
  },
  xAxis: {
    type: 'category',
    data: promotionTrendSeries.value.map((item) => item.date),
    axisLabel: { rotate: 35 },
  },
  yAxis: {
    type: 'value',
    min: 0,
    max: 100,
    axisLabel: {
      formatter: (value: number) => `${value}%`,
    },
  },
  series: [
    createPromotionSeries('总晋级率', promotionTrendSeries.value.map((item) => item.total)),
    createPromotionSeries('1-2', promotionTrendSeries.value.map((item) => item.step12)),
    createPromotionSeries('2-3', promotionTrendSeries.value.map((item) => item.step23)),
    createPromotionSeries('3-4', promotionTrendSeries.value.map((item) => item.step34)),
    createPromotionSeries('4-5', promotionTrendSeries.value.map((item) => item.step45)),
    createPromotionSeries('5-6', promotionTrendSeries.value.map((item) => item.step56)),
    createPromotionSeries('6-7', promotionTrendSeries.value.map((item) => item.step67)),
    createPromotionSeries('7+', promotionTrendSeries.value.map((item) => item.step7Plus)),
  ],
}))

const sentimentSnapshots = computed(() => {
  if (sentimentData.value?.trend?.length) {
    return sentimentData.value.trend.map((item) => ({
      date: item.date,
      promotionRate: item.promotion_rate,
      totalPromotionRate: item.total_promotion_rate,
      explosionRate: item.explosion_rate,
      explodedCount: item.exploded_count,
      tryLimitCount: item.try_limit_count,
      avgFollowReturn: item.avg_follow_return,
      openPremium: item.open_premium,
      highPremium: item.high_premium,
      limitCount: item.limit_count,
      prevLimitCount: item.prev_limit_count,
    }))
  }
  return []
})

const latestSentiment = computed(() => {
  if (sentimentData.value?.latest) {
    return {
      date: sentimentData.value.latest.date,
      promotionRate: sentimentData.value.latest.promotion_rate,
      totalPromotionRate: sentimentData.value.latest.total_promotion_rate,
      explosionRate: sentimentData.value.latest.explosion_rate,
      explodedCount: sentimentData.value.latest.exploded_count,
      tryLimitCount: sentimentData.value.latest.try_limit_count,
      avgFollowReturn: sentimentData.value.latest.avg_follow_return,
      openPremium: sentimentData.value.latest.open_premium,
      highPremium: sentimentData.value.latest.high_premium,
      limitCount: sentimentData.value.latest.limit_count,
      prevLimitCount: sentimentData.value.latest.prev_limit_count,
    }
  }
  return {
    date: latestTradeDate.value,
    promotionRate: 0,
    totalPromotionRate: 0,
    explosionRate: 0,
    explodedCount: 0,
    tryLimitCount: 0,
    avgFollowReturn: 0,
    openPremium: 0,
    highPremium: 0,
    limitCount: 0,
    prevLimitCount: 0,
  }
})

const sentimentWindow = computed(() => {
  const days = periodOptions.find((item) => item.value === selectedPeriod.value)?.days || 22
  return sentimentSnapshots.value.slice(-Math.min(sentimentSnapshots.value.length, days))
})

const sentimentTrendOption = computed(() => {
  const tabMeta = {
    promotion: {
      name: '总晋级率',
      color: '#2563eb',
      getValue: (item: SentimentSnapshot) => item.totalPromotionRate,
    },
    explosion: {
      name: '炸板率',
      color: '#ef4444',
      getValue: (item: SentimentSnapshot) => item.explosionRate,
    },
    closeReturn: {
      name: '昨日涨停股今日平均涨跌幅',
      color: '#0f766e',
      getValue: (item: SentimentSnapshot) => item.avgFollowReturn,
    },
    openPremium: {
      name: '昨日涨停股今日开盘溢价',
      color: '#f59e0b',
      getValue: (item: SentimentSnapshot) => item.openPremium,
    },
    highPremium: {
      name: '昨日涨停股今日盘中最高溢价',
      color: '#7c3aed',
      getValue: (item: SentimentSnapshot) => item.highPremium,
    },
  }[sentimentTrendTab.value]

  return {
    color: [tabMeta.color],
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: number) => `${value}%`,
    },
    grid: {
      left: 36,
      right: 18,
      top: 26,
      bottom: 28,
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      data: sentimentWindow.value.map((item) => item.date),
      axisLabel: { rotate: 35 },
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        formatter: (value: number) => `${value}%`,
      },
    },
    series: [
      {
        name: tabMeta.name,
        type: 'line',
        smooth: true,
        lineStyle: { width: 3 },
        areaStyle: { opacity: 0.12 },
        data: sentimentWindow.value.map((item) => tabMeta.getValue(item)),
      },
    ],
  }
})

const stageGainRanking = computed(() => {
  if (stageGainersData.value?.rankings?.length) {
    return stageGainersData.value.rankings.map((item) => ({
      rank: item.rank,
      code: item.code,
      name: item.name,
      theme: item.theme,
      startPrice: item.start_price,
      currentPrice: item.current_price,
      gainPct: item.gain_pct,
      maxDrawdownPct: item.max_drawdown_pct,
    }))
  }
  return []
})
const stageGainGroups = computed(() => {
  return stageGainBands.map((band) => ({
    label: band.label,
    items: stageGainRanking.value.filter((item) => item.gainPct >= band.min && item.gainPct < band.max),
  }))
})

const nextDayWinRanking = computed(() => {
  if (nextdayWinRateData.value?.rankings?.length) {
    const filtered = nextDayQualifiedOnly.value
      ? nextdayWinRateData.value.rankings.filter((item) => item.trade_days >= 3)
      : nextdayWinRateData.value.rankings
    return filtered.slice(0, 30).map((item, index) => ({
      rank: index + 1,
      code: item.code,
      name: item.name,
      theme: item.theme,
      tradeDays: item.trade_days,
      upDays: item.up_days,
      winRate: item.win_rate,
      avgReturn: item.avg_return,
    }))
  }
  return []
})

const streakRanking = computed(() => {
  if (streakBoardData.value) {
    const rows = streakTab.value === 'up' ? streakBoardData.value.up : streakBoardData.value.down
    if (rows.length) {
      return rows.map((item) => ({
        rank: item.rank,
        code: item.code,
        name: item.name,
        theme: item.theme,
        days: item.days,
        dateRange: item.date_range,
      }))
    }
  }
  return []
})
const reboundRanking = computed(() => {
  if (reboundData.value?.rankings?.length) {
    return reboundData.value.rankings.map((item) => ({
      rank: item.rank,
      code: item.code,
      name: item.name,
      lowestDate: item.lowest_date,
      lowestPrice: item.lowest_price,
      currentPrice: item.current_price,
      reboundPct: item.rebound_pct,
      periodLowLabel: item.period_low_label,
    }))
  }
  return []
})

onMounted(async () => {
  await loadTradeCalendar()
  await loadCurrentViewData()
})

watch([selectedPage, selectedDate, selectedPeriod], async () => {
  await loadCurrentViewData()
})

async function loadTradeCalendar(): Promise<void> {
  try {
    const result = await stockStatisticsApi.getTradeCalendar()
    latestTradeDate.value = result.latestTradeDate
    availableTradeDates.value = result.tradeDates
    if (!availableTradeDates.value.includes(selectedDate.value)) {
      selectedDate.value = result.latestTradeDate
    }
    selectedDate.value = result.latestTradeDate
  } catch (error) {
    ElMessage.warning('交易日接口加载失败，已回退到本地工作日列表')
  }
}

async function loadCurrentViewData(): Promise<void> {
  loadFailureMessage.value = ''
  try {
    if (selectedPage.value === 'limit-fleet' || selectedPage.value === 'limit-types') {
      loadingSection.value = 'limit'
      limitSnapshotData.value = null
      limitSnapshotData.value = await stockStatisticsApi.getLimitSnapshot(selectedDate.value)
      return
    }
    if (selectedPage.value === 'leader-cycle') {
      loadingSection.value = 'leader'
      leaderCycleData.value = null
      leaderCycleData.value = await stockStatisticsApi.getLeaderCycle(selectedPeriod.value)
      return
    }
    if (selectedPage.value === 'market-sentiment') {
      loadingSection.value = 'sentiment'
      sentimentData.value = null
      sentimentData.value = await stockStatisticsApi.getSentiment(selectedPeriod.value)
      return
    }
    if (selectedPage.value === 'stage-gainers') {
      loadingSection.value = 'stage'
      stageGainersData.value = null
      stageGainersData.value = await stockStatisticsApi.getStageGainers(selectedPeriod.value)
      return
    }
    if (selectedPage.value === 'nextday-win-rate') {
      loadingSection.value = 'nextday'
      nextdayWinRateData.value = null
      nextdayWinRateData.value = await stockStatisticsApi.getNextdayWinRate(selectedPeriod.value)
      return
    }
    if (selectedPage.value === 'streak-board') {
      loadingSection.value = 'streak'
      streakBoardData.value = null
      streakBoardData.value = await stockStatisticsApi.getStreakBoard(selectedPeriod.value)
      return
    }
    if (selectedPage.value === 'rebound-board') {
      loadingSection.value = 'rebound'
      reboundData.value = null
      reboundData.value = await stockStatisticsApi.getRebound(selectedPeriod.value)
    }
  } catch (error) {
    loadFailureMessage.value = '统计后端数据加载失败，当前页未再回退到本地演示样本'
    ElMessage.warning(loadFailureMessage.value)
  } finally {
    loadingSection.value = ''
  }
}

function mapLimitItem(item: StockStatisticsLimitItem) {
  return {
    tsCode: item.ts_code,
    code: item.code,
    name: item.name,
    theme: item.theme,
    boardCount: item.board_count,
    limitType: item.limit_type,
    limitTime: item.limit_time,
    sealAmount: item.seal_amount,
  }
}

function toggleGroup(groupKey: NavGroupKey): void {
  expandedGroups.value = expandedGroups.value.includes(groupKey)
    ? expandedGroups.value.filter((item) => item !== groupKey)
    : [...expandedGroups.value, groupKey]
}

function disabledDate(date: Date): boolean {
  return !availableTradeDateSet.value.has(formatDate(date))
}

function createPromotionSeries(name: string, data: number[]) {
  return {
    name,
    type: 'line',
    smooth: true,
    symbol: 'circle',
    symbolSize: 5,
    lineStyle: { width: name === '总晋级率' ? 3 : 2 },
    data,
  }
}

function formatBoardBand(count: number): string {
  return count >= 7 ? '7板+' : `${count}板`
}

function formatPercent(value: number): string {
  return `${Number(value).toFixed(1)}%`
}

function formatSignedPercent(value: number): string {
  const num = Number(value)
  return `${num > 0 ? '+' : ''}${num.toFixed(1)}%`
}

function formatMoney(value: number): string {
  if (value >= 100000000) {
    return `${(value / 100000000).toFixed(2)}亿`
  }
  return `${(value / 10000).toFixed(0)}万`
}

function formatPrice(value: number): string {
  return value.toFixed(2)
}

function getLatestWeekday(): string {
  const now = new Date()
  const cursor = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  while (cursor.getDay() === 0 || cursor.getDay() === 6) {
    cursor.setDate(cursor.getDate() - 1)
  }
  return formatDate(cursor)
}

function generateTradeDates(endDate: string, count: number): string[] {
  const result: string[] = []
  const cursor = new Date(`${endDate}T12:00:00`)
  while (result.length < count) {
    const weekDay = cursor.getDay()
    if (weekDay !== 0 && weekDay !== 6) {
      result.push(formatDate(cursor))
    }
    cursor.setDate(cursor.getDate() - 1)
  }
  return result.reverse()
}

function formatDate(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}
</script>

<style scoped>
.stock-statistics-page {
  --mac-surface-strong: rgba(255, 255, 255, 0.92);
  --mac-border: rgba(15, 23, 42, 0.08);
  --mac-text: #142033;
  --mac-text-soft: #5d6b80;
  --mac-accent: #2563eb;
  --mac-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
  --mac-radius-lg: 20px;
  --mac-radius-md: 14px;
  display: flex;
  flex-direction: column;
  gap: 0;
  min-height: 100%;
  padding: 12px;
  color: var(--mac-text);
  font-family: 'SF Pro Text', 'PingFang SC', 'Helvetica Neue', sans-serif;
}

.stock-statistics-page,
.workspace-shell,
.secondary-nav,
.content-shell,
.panel-stack,
.table-card,
.chart-card,
.ladder-table,
.ladder-row,
.ladder-content,
.stock-strip-grid,
.stock-strip-card {
  box-sizing: border-box;
  min-width: 0;
}

.content-shell,
.secondary-nav,
.chart-card,
.table-card,
.metric-card {
  border: 1px solid var(--mac-border);
  box-shadow: var(--mac-shadow);
  backdrop-filter: blur(18px);
}

.metric-card {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 14px 15px;
  border-radius: var(--mac-radius-md);
  background: rgba(255, 255, 255, 0.72);
}

.metric-card span {
  font-size: 11px;
  color: #6b778d;
}

.metric-card strong {
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.metric-card small {
  color: #75839a;
  line-height: 1.4;
  font-size: 12px;
}

.metric-card.highlight {
  background: linear-gradient(135deg, #1d365f, #315dca);
  color: #f8fbff;
}

.metric-card.highlight span,
.metric-card.highlight small {
  color: rgba(248, 251, 255, 0.82);
}

.workspace-shell {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: 12px;
  min-height: 700px;
  align-items: stretch;
}

.secondary-nav {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border-radius: var(--mac-radius-lg);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.82), rgba(243, 245, 248, 0.88));
  min-height: 100%;
}

.nav-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 2px 2px 10px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.08);
}

.nav-head span {
  font-size: 14px;
  font-weight: 700;
}

.nav-head small {
  color: #7a889f;
  font-size: 11px;
}

.nav-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.nav-group-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 8px 10px;
  border: 1px solid transparent;
  border-radius: 14px;
  background: rgba(241, 244, 247, 0.9);
  color: var(--mac-text);
  text-align: left;
  cursor: pointer;
}

.nav-group-toggle strong {
  display: block;
  font-size: 12px;
}

.nav-group-toggle span {
  font-size: 11px;
  color: #738198;
}

.nav-group-arrow {
  font-size: 16px;
  color: var(--mac-accent);
}

.nav-group-items {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.nav-item {
  display: flex;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  border: 1px solid transparent;
  border-radius: 14px;
  background: transparent;
  color: #223047;
  text-align: left;
  cursor: pointer;
  transition: transform 0.16s ease, border-color 0.16s ease, background 0.16s ease;
}

.nav-item:hover {
  transform: translateX(1px);
  border-color: rgba(37, 99, 235, 0.16);
  background: rgba(246, 248, 251, 0.95);
}

.nav-item.active {
  border-color: rgba(37, 99, 235, 0.2);
  background: linear-gradient(135deg, rgba(37, 99, 235, 0.1), rgba(255, 255, 255, 0.86));
}

.nav-item-index {
  min-width: 24px;
  font-size: 11px;
  font-weight: 700;
  color: var(--mac-accent);
}

.nav-item-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-item-text strong {
  font-size: 12px;
}

.nav-item-text small {
  color: #7a8798;
  font-size: 10px;
  line-height: 1.3;
}

.content-shell {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 14px 14px;
  border-radius: var(--mac-radius-lg);
  overflow: hidden;
  background:
    radial-gradient(circle at top right, rgba(16, 185, 129, 0.05), transparent 24%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.9), rgba(248, 250, 252, 0.92));
}

.content-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.toolbar-main {
  min-width: 0;
}

.toolbar-title-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.toolbar-tag {
  margin: 0;
  font-size: 11px;
  font-weight: 700;
  color: #0f766e;
}

.content-toolbar h2 {
  margin: 0;
  font-size: 22px;
  letter-spacing: -0.025em;
}

.toolbar-meta {
  display: inline-flex;
  align-items: center;
  padding: 3px 8px;
  border-radius: 999px;
  background: rgba(236, 240, 245, 0.92);
  color: #5d6a80;
  font-size: 11px;
  font-weight: 600;
}

.toolbar-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}

.toolbar-description {
  margin: 4px 0 0;
  max-width: 680px;
  font-size: 12px;
  line-height: 1.45;
  color: var(--mac-text-soft);
}

.filter-block {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 8px 10px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 12px;
  background: rgba(244, 246, 249, 0.92);
}

.filter-label {
  font-size: 11px;
  font-weight: 600;
  color: #6a778e;
  white-space: nowrap;
}

.filter-static strong {
  font-size: 13px;
}

.filter-static small {
  display: none;
}

.context-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.context-pill,
.section-badge {
  display: inline-flex;
  align-items: center;
  padding: 4px 8px;
  border-radius: 999px;
  background: rgba(236, 240, 245, 0.9);
  color: #4d5c72;
  font-size: 10px;
  font-weight: 600;
}

.context-pill.warning {
  background: rgba(254, 242, 242, 0.92);
  color: #b91c1c;
}

.panel-stack,
.metric-grid {
  display: grid;
  gap: 10px;
}

.metric-grid {
  grid-template-columns: repeat(6, minmax(0, 1fr));
}

.table-card,
.chart-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border-radius: 16px;
  background: var(--mac-surface-strong);
}

.table-card.compact {
  padding-top: 0;
}

.section-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: flex-start;
}

.section-head.minimal,
.section-head.controls-only,
.section-head.tabs-only {
  align-items: center;
}

.section-head.minimal,
.section-head.controls-only,
.section-head.tabs-only {
  justify-content: flex-end;
}

.section-head h3 {
  margin: 0;
  font-size: 16px;
  letter-spacing: -0.02em;
}

.section-head p {
  margin: 4px 0 0;
  font-size: 11px;
  line-height: 1.4;
  color: var(--mac-text-soft);
}

.section-head.with-inline-tabs {
  align-items: center;
}

.ladder-table {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.ladder-row {
  display: grid;
  grid-template-columns: 78px minmax(0, 1fr);
  gap: 6px;
  align-items: stretch;
}

.ladder-level {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
  padding: 10px 8px;
  border: 1px solid rgba(37, 99, 235, 0.12);
  border-radius: 14px;
  background: linear-gradient(180deg, rgba(37, 99, 235, 0.08), rgba(255, 255, 255, 0.72));
}

.ladder-level.warm {
  border-color: rgba(245, 158, 11, 0.12);
  background: linear-gradient(180deg, rgba(245, 158, 11, 0.1), rgba(255, 255, 255, 0.72));
}

.ladder-level.neutral {
  border-color: rgba(15, 118, 110, 0.12);
  background: linear-gradient(180deg, rgba(15, 118, 110, 0.08), rgba(255, 255, 255, 0.72));
}

.ladder-level strong {
  font-size: 13px;
}

.ladder-level span {
  color: #738198;
  font-size: 10px;
}

.ladder-content {
  padding: 8px;
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 14px;
  background: rgba(247, 249, 252, 0.92);
  overflow: hidden;
}

.stock-strip-grid {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 5px;
}

.stock-strip-card {
  display: inline-grid;
  grid-template-columns: max-content max-content minmax(0, 1fr);
  align-items: center;
  gap: 6px;
  flex: 0 1 360px;
  max-width: 100%;
  padding: 8px 9px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid rgba(15, 23, 42, 0.08);
}

.stock-strip-card.warm {
  border-color: rgba(245, 158, 11, 0.14);
  background: rgba(255, 251, 235, 0.94);
}

.stock-strip-card.neutral {
  border-color: rgba(15, 118, 110, 0.12);
  background: rgba(240, 253, 250, 0.96);
}

.stock-strip-head {
  display: contents;
}

.stock-strip-head strong {
  font-size: 12px;
  white-space: nowrap;
}

.stock-strip-head span {
  color: #5c6c82;
  font-size: 10px;
  font-weight: 600;
  white-space: nowrap;
}

.stock-strip-meta {
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
  gap: 0;
  min-width: 120px;
  max-width: 100%;
  overflow: hidden;
}

.stock-strip-meta span {
  color: #5b6980;
  font-size: 10px;
  line-height: 1.2;
  white-space: nowrap;
}

.stock-strip-meta span:first-child {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stock-strip-meta span:not(:first-child) {
  flex: 0 0 auto;
}

.stock-strip-meta span:not(:last-child)::after {
  content: '·';
  margin: 0 5px;
  color: #9aa6b6;
}

.ladder-empty {
  display: flex;
  align-items: center;
  min-height: 32px;
  color: #8a97ab;
  font-size: 11px;
}

.chart-canvas {
  width: 100%;
  height: 280px;
}

.tall-chart {
  height: 320px;
}

.compact-chart {
  margin-top: -4px;
}

.inline-tabs {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 5px;
}

.inline-tab {
  padding: 6px 10px;
  border: 1px solid rgba(15, 23, 42, 0.1);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.86);
  color: #56657b;
  font-size: 11px;
  cursor: pointer;
}

.inline-tab.active {
  border-color: rgba(37, 99, 235, 0.2);
  background: rgba(37, 99, 235, 0.08);
  color: #234fb8;
  font-weight: 700;
}

.toggle-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 999px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: rgba(243, 246, 249, 0.92);
  color: #45556d;
  font-size: 11px;
  cursor: pointer;
}

.toggle-chip input {
  accent-color: #2563eb;
}

.dense-table {
  --el-table-border-color: rgba(15, 23, 42, 0.08);
  --el-table-header-bg-color: rgba(245, 247, 250, 0.92);
  --el-table-row-hover-bg-color: rgba(241, 245, 249, 0.78);
  --el-table-text-color: #223047;
  --el-table-header-text-color: #5f6c80;
  --el-table-bg-color: transparent;
  --el-fill-color-lighter: rgba(244, 246, 248, 0.72);
}

.dense-table :deep(.el-table__header th) {
  padding: 6px 0;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.02em;
}

.dense-table :deep(.el-table__cell) {
  padding: 5px 0;
}

.dense-table :deep(.cell) {
  line-height: 1.25;
  font-size: 12px;
}

.filter-block :deep(.el-input__wrapper),
.filter-block :deep(.el-select__wrapper) {
  border-radius: 10px;
  box-shadow: none;
  background: rgba(255, 255, 255, 0.92);
}

.filter-block :deep(.el-date-editor.el-input),
.filter-block :deep(.el-select) {
  width: 148px !important;
}

@media (max-width: 1500px) {
  .metric-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 1180px) {
  .workspace-shell,
  .ladder-row {
    grid-template-columns: 1fr;
  }

  .metric-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .metric-grid,
  .type-grid {
    grid-template-columns: 1fr;
  }

  .content-toolbar,
  .section-head,
  .section-head.with-inline-tabs {
    flex-direction: column;
    align-items: flex-start;
  }

  .toolbar-actions {
    width: 100%;
    justify-content: flex-start;
  }

  .filter-block {
    width: 100%;
    justify-content: space-between;
  }
}
</style>
