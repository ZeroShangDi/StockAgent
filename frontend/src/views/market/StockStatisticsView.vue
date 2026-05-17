<template>
  <div class="stock-statistics-page">
    <section class="hero-card">
      <div class="hero-copy">
        <p class="eyebrow">Post-Market Atlas</p>
        <h1>股票统计面板</h1>
        <p class="hero-description">
          以盘后静态数据为主，左侧切专题，右侧集中看打板结构、情绪温度和趋势统计。当前先把页面交互和展示口径收稳，聚合接口后续再逐步替换。
        </p>
      </div>

      <div class="hero-metrics">
        <article class="hero-metric accent">
          <span>最新交易日</span>
          <strong>{{ latestTradeDate }}</strong>
          <small>{{ tradeCalendarSource === 'backend' ? '来自后端交易日接口' : '本地回退到最近工作日' }}</small>
        </article>
        <article class="hero-metric">
          <span>当前专题</span>
          <strong>{{ currentPage.title }}</strong>
          <small>{{ currentPage.groupTitle }}</small>
        </article>
        <article class="hero-metric">
          <span>样本说明</span>
          <strong>{{ stockUniverse.length }} 只</strong>
          <small>统计口径待明天再核实接真实聚合</small>
        </article>
      </div>
    </section>

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
          <div>
            <p class="toolbar-tag">{{ currentPage.groupTitle }}</p>
            <h2>{{ currentPage.title }}</h2>
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

        <div class="context-bar">
          <span class="context-pill">{{ currentPage.context }}</span>
          <span class="context-pill">
            {{ currentPage.filterMode === 'date' ? `当前交易日 ${selectedDate}` : currentPage.filterMode === 'period' ? `当前周期 ${selectedPeriodLabel}` : '最近一年统计' }}
          </span>
          <span class="context-pill">交易日列表已优先改为后端接口</span>
          <span v-if="loadingSection" class="context-pill">后端数据加载中</span>
          <span v-for="warning in activeWarnings" :key="warning" class="context-pill warning">
            {{ warning }}
          </span>
        </div>

        <section v-if="selectedPage === 'limit-fleet'" class="panel-stack">
          <div class="table-card">
            <div class="section-head">
              <div>
                <h3>涨停雁阵图</h3>
                <p>改为更接近打板网站的分层表格视图，按连板高度从高到低铺开，而不是树图。</p>
              </div>
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
                  <el-empty v-else description="当前层级暂无样本" />
                </div>
              </div>
            </div>
          </div>

          <div class="table-card">
            <div class="section-head">
              <div>
                <h3>涨停明细</h3>
                <p>保留明细表，方便按题材、时间和封单额二次观察。</p>
              </div>
            </div>
            <el-table :data="selectedLimitRecords" stripe height="420">
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
            <div class="section-head">
              <div>
                <h3>涨停类型统计</h3>
                <p>同样改成表格式结构浏览，优先看每类数量、占比和个股分布。</p>
              </div>
            </div>

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
                  <el-empty v-else description="当前类型暂无样本" />
                </div>
              </div>
            </div>
          </div>

          <div class="table-card">
            <div class="section-head">
              <div>
                <h3>类型明细列表</h3>
                <p>把各类涨停样本并排展开，便于核对一字、T 字、换手等分布。</p>
              </div>
            </div>
            <el-table :data="limitTypeDetailRows" stripe height="460">
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
            <el-table :data="leaderCountRanking" stripe height="420">
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
            <VChart class="chart-canvas tall-chart" :option="promotionRateOption" autoresize />
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
              <div>
                <h3>情绪趋势</h3>
                <p>右上角只保留周期切换，底部趋势范围跟随周期变化，默认锚定最新交易日。</p>
              </div>
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
            <VChart class="chart-canvas" :option="sentimentTrendOption" autoresize />
          </div>
        </section>

        <section v-else-if="selectedPage === 'stage-gainers'" class="panel-stack">
          <div class="table-card">
            <div class="section-head">
              <div>
                <h3>涨幅雁阵图</h3>
                <p>不再做单纯榜单，改为分层统计。按 `20-40 / 40-60 / 60-80 / 80-100 / 100+` 分层看周期强势股分布。</p>
              </div>
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
                  <el-empty v-else description="当前层级暂无样本" />
                </div>
              </div>
            </div>
          </div>

          <div class="table-card">
            <div class="section-head">
              <div>
                <h3>涨幅明细</h3>
                <p>保留涨幅、题材和最大回撤，方便继续做强弱对比。</p>
              </div>
            </div>
            <el-table :data="stageGainRanking" stripe height="430">
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
          <div class="section-head">
            <div>
              <h3>次日胜率榜</h3>
              <p>和是否涨停解绑，按自定义样本事件统计“次日收盘为红”的概率，默认展示前 30。</p>
            </div>
            <label class="toggle-chip">
              <input v-model="nextDayQualifiedOnly" type="checkbox">
              <span>仅看样本次数 ≥ 3</span>
            </label>
          </div>
          <el-table :data="nextDayWinRanking" stripe height="640">
            <el-table-column prop="rank" label="排名" width="80" />
            <el-table-column prop="code" label="代码" width="110" />
            <el-table-column prop="name" label="名称" width="120" />
            <el-table-column prop="sampleCount" label="样本次数" width="110" sortable />
            <el-table-column prop="nextDayUpCount" label="次日上涨次数" width="130" sortable />
            <el-table-column prop="winRate" label="胜率" width="100" sortable>
              <template #default="{ row }">{{ formatPercent(row.winRate) }}</template>
            </el-table-column>
            <el-table-column prop="avgNextDayReturn" label="次日均涨幅" width="120" sortable>
              <template #default="{ row }">{{ formatSignedPercent(row.avgNextDayReturn) }}</template>
            </el-table-column>
            <el-table-column prop="signalSource" label="样本口径" width="140" />
            <el-table-column prop="theme" label="题材" min-width="150" />
          </el-table>
        </section>

        <section v-else-if="selectedPage === 'streak-board'" class="panel-stack">
          <div class="section-head with-inline-tabs">
            <div>
              <h3>连涨 / 连跌榜</h3>
              <p>默认扩到前 30，只保留上涨和下跌两个标签页切换。</p>
            </div>
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

          <div class="table-card compact">
            <el-table :data="streakRanking" stripe>
              <el-table-column prop="rank" label="排名" width="80" />
              <el-table-column prop="code" label="代码" width="110" />
              <el-table-column prop="name" label="名称" width="130" />
              <el-table-column :label="streakTab === 'up' ? '最长连涨天数' : '最长连跌天数'" width="140">
                <template #default="{ row }">{{ row.days }}</template>
              </el-table-column>
              <el-table-column prop="dateRange" label="发生时间段" min-width="220" />
              <el-table-column prop="theme" label="题材" min-width="160" />
            </el-table>
          </div>
        </section>

        <section v-else class="table-card">
          <div class="section-head">
            <div>
              <h3>高低点策略榜</h3>
              <p>默认缩到前 30，保留低点日期、最低价、当前价和反弹涨幅四个核心观察维度。</p>
            </div>
            <span class="section-badge">当前展示 {{ reboundRanking.length }} 只</span>
          </div>
          <el-table :data="reboundRanking" stripe height="640">
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
type PeriodValue = '1w' | '1m' | '3m' | '1y'
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

interface StockProfile {
  tsCode: string
  code: string
  name: string
  theme: string
  basePrice: number
  momentum: number
}

interface LimitRecord {
  tsCode: string
  code: string
  name: string
  theme: string
  boardCount: number
  limitType: string
  limitTime: string
  sealAmount: number
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

const stockUniverse: StockProfile[] = [
  { tsCode: '000001.SZ', code: '000001', name: '云图科技', theme: 'AI 应用', basePrice: 18.62, momentum: 0.84 },
  { tsCode: '000002.SZ', code: '000002', name: '海拓能源', theme: '可控核聚变', basePrice: 12.18, momentum: 0.73 },
  { tsCode: '000004.SZ', code: '000004', name: '星河机器人', theme: '人形机器人', basePrice: 26.35, momentum: 0.92 },
  { tsCode: '000006.SZ', code: '000006', name: '凌越通信', theme: '6G 通信', basePrice: 15.47, momentum: 0.58 },
  { tsCode: '000008.SZ', code: '000008', name: '中锐医药', theme: '创新药', basePrice: 22.71, momentum: 0.49 },
  { tsCode: '000010.SZ', code: '000010', name: '华景算力', theme: '算力租赁', basePrice: 31.24, momentum: 0.95 },
  { tsCode: '600101.SH', code: '600101', name: '金桥新材', theme: '先进封装', basePrice: 17.53, momentum: 0.66 },
  { tsCode: '600188.SH', code: '600188', name: '东岭化工', theme: '磷化工', basePrice: 9.86, momentum: 0.37 },
  { tsCode: '600256.SH', code: '600256', name: '国芯设备', theme: '半导体设备', basePrice: 28.43, momentum: 0.88 },
  { tsCode: '600318.SH', code: '600318', name: '长空航空', theme: '低空经济', basePrice: 13.68, momentum: 0.69 },
  { tsCode: '600399.SH', code: '600399', name: '瑞丰消费', theme: '新零售', basePrice: 11.42, momentum: 0.33 },
  { tsCode: '600512.SH', code: '600512', name: '盛海港航', theme: '航运物流', basePrice: 7.98, momentum: 0.51 },
  { tsCode: '600666.SH', code: '600666', name: '西岭文旅', theme: '旅游演艺', basePrice: 10.73, momentum: 0.47 },
  { tsCode: '300001.SZ', code: '300001', name: '逐日电池', theme: '固态电池', basePrice: 34.9, momentum: 0.79 },
  { tsCode: '300233.SZ', code: '300233', name: '清源软件', theme: '工业软件', basePrice: 25.16, momentum: 0.72 },
  { tsCode: '300451.SZ', code: '300451', name: '天穹卫星', theme: '商业航天', basePrice: 19.84, momentum: 0.63 },
  { tsCode: '301188.SZ', code: '301188', name: '嘉禾零碳', theme: '储能电网', basePrice: 21.12, momentum: 0.54 },
  { tsCode: '688008.SH', code: '688008', name: '芯岳光电', theme: 'CPO 光模块', basePrice: 43.6, momentum: 0.91 },
  { tsCode: '688111.SH', code: '688111', name: '景曜芯片', theme: 'HBM 存储', basePrice: 39.15, momentum: 0.78 },
  { tsCode: '002261.SZ', code: '002261', name: '拓界电驱', theme: '智能汽车', basePrice: 24.52, momentum: 0.71 },
]

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
  { label: '近一年', value: '1y' as PeriodValue, days: 250 },
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
        description: '展示最近一年最长连涨和最长连跌排行，默认扩到前 30。',
        groupTitle: '趋势组',
        context: '无筛选器，直接以标签页切换方向',
        filterMode: 'none',
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
const tradeCalendarSource = ref<'backend' | 'fallback'>('fallback')
const selectedDate = ref(fallbackLatestTradeDate)
const selectedPeriod = ref<PeriodValue>('1m')
const sentimentTrendTab = ref<SentimentTrendKey>('promotion')
const nextDayQualifiedOnly = ref(true)
const streakTab = ref<StreakTabKey>('up')
const loadingSection = ref('')

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
  if (selectedPage.value === 'limit-fleet' || selectedPage.value === 'limit-types') {
    return limitSnapshotData.value?.warnings || []
  }
  if (selectedPage.value === 'leader-cycle') {
    return leaderCycleData.value?.warnings || []
  }
  if (selectedPage.value === 'market-sentiment') {
    return sentimentData.value?.warnings || []
  }
  if (selectedPage.value === 'stage-gainers') {
    return stageGainersData.value?.warnings || []
  }
  if (selectedPage.value === 'nextday-win-rate') {
    return nextdayWinRateData.value?.warnings || []
  }
  if (selectedPage.value === 'streak-board') {
    return streakBoardData.value?.warnings || []
  }
  if (selectedPage.value === 'rebound-board') {
    return reboundData.value?.warnings || []
  }
  return []
})

const limitRecordsByDate = computed<Record<string, LimitRecord[]>>(() => {
  return Object.fromEntries(
    availableTradeDates.value.map((date, index) => [date, buildLimitRecords(index)]),
  )
})

const selectedLimitRecords = computed(() => {
  if (limitSnapshotData.value?.limit_fleet.detail?.length) {
    return limitSnapshotData.value.limit_fleet.detail.map(mapLimitItem)
  }
  return limitRecordsByDate.value[selectedDate.value] || []
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
  return buildLeaderCountRanking(selectedPeriod.value)
})
const promotionTrendSeries = computed(() => {
  if (leaderCycleData.value?.promotion_trend?.length) {
    return leaderCycleData.value.promotion_trend
  }
  return buildPromotionTrend(selectedPeriod.value)
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
  return availableTradeDates.value.map((date, index) => buildSentimentSnapshot(date, index))
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
  return sentimentSnapshots.value.find((item) => item.date === latestTradeDate.value) || sentimentSnapshots.value[sentimentSnapshots.value.length - 1]
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
  return buildStageGainRanking(selectedPeriod.value)
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
      ? nextdayWinRateData.value.rankings.filter((item) => item.sample_count >= 3)
      : nextdayWinRateData.value.rankings
    return filtered.slice(0, 30).map((item, index) => ({
      rank: index + 1,
      code: item.code,
      name: item.name,
      theme: item.theme,
      sampleCount: item.sample_count,
      nextDayUpCount: item.nextday_up_count,
      winRate: item.win_rate,
      avgNextDayReturn: item.avg_nextday_return,
      signalSource: item.signal_source,
    }))
  }
  const rows = buildNextDayWinRanking(selectedPeriod.value)
  const filtered = nextDayQualifiedOnly.value ? rows.filter((item) => item.sampleCount >= 3) : rows
  return filtered.slice(0, 30).map((item, index) => ({ ...item, rank: index + 1 }))
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
  return buildStreakRanking(streakTab.value)
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
  return buildReboundRanking(selectedPeriod.value)
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
    tradeCalendarSource.value = result.source
    if (!availableTradeDates.value.includes(selectedDate.value)) {
      selectedDate.value = result.latestTradeDate
    }
    selectedDate.value = result.latestTradeDate
  } catch (error) {
    ElMessage.warning('交易日接口加载失败，已回退到本地工作日列表')
  }
}

async function loadCurrentViewData(): Promise<void> {
  try {
    if (selectedPage.value === 'limit-fleet' || selectedPage.value === 'limit-types') {
      loadingSection.value = 'limit'
      limitSnapshotData.value = await stockStatisticsApi.getLimitSnapshot(selectedDate.value)
      return
    }
    if (selectedPage.value === 'leader-cycle') {
      loadingSection.value = 'leader'
      leaderCycleData.value = await stockStatisticsApi.getLeaderCycle(selectedPeriod.value)
      return
    }
    if (selectedPage.value === 'market-sentiment') {
      loadingSection.value = 'sentiment'
      sentimentData.value = await stockStatisticsApi.getSentiment(selectedPeriod.value)
      return
    }
    if (selectedPage.value === 'stage-gainers') {
      loadingSection.value = 'stage'
      stageGainersData.value = await stockStatisticsApi.getStageGainers(selectedPeriod.value)
      return
    }
    if (selectedPage.value === 'nextday-win-rate') {
      loadingSection.value = 'nextday'
      nextdayWinRateData.value = await stockStatisticsApi.getNextdayWinRate(selectedPeriod.value)
      return
    }
    if (selectedPage.value === 'streak-board') {
      loadingSection.value = 'streak'
      streakBoardData.value = await stockStatisticsApi.getStreakBoard()
      return
    }
    if (selectedPage.value === 'rebound-board') {
      loadingSection.value = 'rebound'
      reboundData.value = await stockStatisticsApi.getRebound(selectedPeriod.value)
    }
  } catch (error) {
    ElMessage.warning('统计后端数据加载失败，已回退到本地样本')
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

function buildLimitRecords(dateIndex: number): LimitRecord[] {
  const count = 10 + (dateIndex % 7)
  const records: LimitRecord[] = []
  const usedCodes = new Set<string>()

  for (let i = 0; i < count; i += 1) {
    const stock = stockUniverse[(dateIndex * 4 + i * 3) % stockUniverse.length]
    if (usedCodes.has(stock.code)) continue
    usedCodes.add(stock.code)
    records.push({
      tsCode: stock.tsCode,
      code: stock.code,
      name: stock.name,
      theme: stock.theme,
      boardCount: buildBoardCount(dateIndex, i, stock.momentum),
      limitType: limitTypes[(dateIndex + i) % limitTypes.length],
      limitTime: buildLimitTime(dateIndex + i),
      sealAmount: Math.round((22000000 + dateIndex * 900000 + i * 2100000) * (1 + stock.momentum * 0.72)),
    })
  }

  return records.sort((left, right) => right.boardCount - left.boardCount || right.sealAmount - left.sealAmount)
}

function buildBoardCount(dateIndex: number, itemIndex: number, momentum: number): number {
  if (itemIndex === 0 && momentum > 0.9) return 7 + (dateIndex % 2)
  if (itemIndex <= 1) return 5 + ((dateIndex + itemIndex) % 2)
  if (itemIndex <= 3) return 4 + ((dateIndex + itemIndex) % 2)
  if (itemIndex <= 6) return 2 + ((dateIndex + itemIndex) % 2)
  return 1
}

function buildLeaderCountRanking(period: PeriodValue) {
  const factor = periodFactorValue(period)
  return stockUniverse
    .map((stock, index) => ({
      rank: 0,
      code: stock.code,
      name: stock.name,
      theme: stock.theme,
      limitCount: Math.round(3 + stock.momentum * 9 + factor * 3 + (index % 5)),
      maxBoard: Math.max(2, Math.round(2 + stock.momentum * 5 + (index % 3))),
    }))
    .sort((left, right) => right.limitCount - left.limitCount || right.maxBoard - left.maxBoard)
    .slice(0, 30)
    .map((item, index) => ({ ...item, rank: index + 1 }))
}

function buildPromotionTrend(period: PeriodValue) {
  const days = Math.min(periodOptions.find((item) => item.value === period)?.days || 22, availableTradeDates.value.length)
  const dates = availableTradeDates.value.slice(-days)
  return dates.map((date, index) => {
    const base = periodFactorValue(period)
    const total = clamp(44 + Math.sin(index * 0.33 + base) * 14 + base * 5, 20, 86)
    return {
      date,
      total: roundNumber(total, 1),
      step12: roundNumber(clamp(total + 8, 22, 92), 1),
      step23: roundNumber(clamp(total - 2 + Math.sin(index * 0.4) * 8, 16, 78), 1),
      step34: roundNumber(clamp(total - 10 + Math.cos(index * 0.35) * 7, 8, 65), 1),
      step45: roundNumber(clamp(total - 16 + Math.sin(index * 0.28) * 7, 6, 55), 1),
      step56: roundNumber(clamp(total - 20 + Math.cos(index * 0.22) * 6, 4, 48), 1),
      step67: roundNumber(clamp(total - 24 + Math.sin(index * 0.18) * 5, 2, 40), 1),
      step7Plus: roundNumber(clamp(total - 28 + Math.cos(index * 0.14) * 5, 1, 32), 1),
    }
  })
}

function buildSentimentSnapshot(date: string, index: number): SentimentSnapshot {
  const currentCount = (limitRecordsByDate.value[date] || []).length
  const previousDate = availableTradeDates.value[index - 1]
  const previousCount = previousDate ? (limitRecordsByDate.value[previousDate] || []).length : Math.max(6, currentCount - 2)
  const tryLimitCount = currentCount + 4 + (index % 3)
  const explodedCount = Math.max(1, Math.round(tryLimitCount * clamp(0.12 + Math.abs(Math.sin(index * 0.27)) * 0.16, 0.1, 0.32)))
  const totalPromotionRate = roundNumber(clamp(46 + Math.sin(index * 0.35 + 0.5) * 16 + currentCount * 0.7, 18, 88), 1)
  const promotionRate = roundNumber(clamp(totalPromotionRate + Math.cos(index * 0.21) * 4, 20, 92), 1)

  return {
    date,
    promotionRate,
    totalPromotionRate,
    explosionRate: roundNumber((explodedCount / tryLimitCount) * 100, 1),
    explodedCount,
    tryLimitCount,
    avgFollowReturn: roundNumber(Math.sin(index * 0.31 + 0.2) * 3.8 + 1.9, 1),
    openPremium: roundNumber(Math.cos(index * 0.24 + 0.3) * 2.9 + 2.6, 1),
    highPremium: roundNumber(Math.sin(index * 0.18 + 0.5) * 3.4 + 5.8, 1),
    limitCount: currentCount,
    prevLimitCount: previousCount,
  }
}

function buildStageGainRanking(period: PeriodValue) {
  const factor = periodFactorValue(period)
  return stockUniverse
    .map((stock, index) => {
      const startPrice = roundNumber(stock.basePrice * (0.96 + Math.sin(index + factor) * 0.04), 2)
      const gainPct = roundNumber(20 + stock.momentum * 72 + factor * 8 + (index % 6) * 4, 1)
      return {
        rank: 0,
        code: stock.code,
        name: stock.name,
        theme: stock.theme,
        startPrice,
        currentPrice: roundNumber(startPrice * (1 + gainPct / 100), 2),
        gainPct,
        maxDrawdownPct: roundNumber(-(4 + (index % 5) * 2.1 + factor * 1.8), 1),
      }
    })
    .sort((left, right) => right.gainPct - left.gainPct)
    .slice(0, 30)
    .map((item, index) => ({ ...item, rank: index + 1 }))
}

function buildNextDayWinRanking(period: PeriodValue) {
  const factor = periodFactorValue(period)
  return stockUniverse
    .map((stock, index) => {
      const sampleCount = Math.max(2, Math.round(2 + stock.momentum * 4 + factor + (index % 4)))
      const winRate = clamp(42 + stock.momentum * 31 + factor * 6 - (index % 5) * 2.2, 24, 90)
      const nextDayUpCount = Math.min(sampleCount, Math.round(sampleCount * winRate / 100))
      return {
        rank: 0,
        code: stock.code,
        name: stock.name,
        theme: stock.theme,
        sampleCount,
        nextDayUpCount,
        winRate: roundNumber((nextDayUpCount / sampleCount) * 100, 1),
        avgNextDayReturn: roundNumber(-0.7 + stock.momentum * 4.8 + factor * 0.7 - (index % 3) * 0.3, 1),
        signalSource: '触发样本',
      }
    })
    .sort((left, right) => right.winRate - left.winRate || right.sampleCount - left.sampleCount)
}

function buildStreakRanking(tab: StreakTabKey) {
  return stockUniverse
    .map((stock, index) => {
      const days = tab === 'up'
        ? Math.round(5 + stock.momentum * 9 + (index % 5))
        : Math.round(4 + (1 - stock.momentum) * 8 + (index % 4))
      const endOffset = 12 + index * 3
      const startOffset = endOffset + days - 1
      return {
        rank: 0,
        code: stock.code,
        name: stock.name,
        theme: stock.theme,
        days,
        dateRange: `${addDays(latestTradeDate.value, -startOffset)} 至 ${addDays(latestTradeDate.value, -endOffset)}`,
      }
    })
    .sort((left, right) => right.days - left.days)
    .slice(0, 30)
    .map((item, index) => ({ ...item, rank: index + 1 }))
}

function buildReboundRanking(period: PeriodValue) {
  const info = periodOptions.find((item) => item.value === period) || periodOptions[1]
  const startDate = addDays(latestTradeDate.value, -info.days * 2)
  return stockUniverse
    .map((stock, index) => {
      const lowestPrice = roundNumber(stock.basePrice * (0.62 + (index % 5) * 0.045), 2)
      const reboundPct = roundNumber(16 + stock.momentum * 38 + (index % 6) * 3 + periodFactorValue(period) * 6, 1)
      return {
        rank: 0,
        code: stock.code,
        name: stock.name,
        lowestDate: addDays(startDate, 2 + (index * 7) % Math.max(8, info.days)),
        lowestPrice,
        currentPrice: roundNumber(lowestPrice * (1 + reboundPct / 100), 2),
        reboundPct,
        periodLowLabel: `${startDate} 起始 · ${selectedPeriodLabel.value}`,
      }
    })
    .sort((left, right) => right.reboundPct - left.reboundPct)
    .slice(0, 30)
    .map((item, index) => ({ ...item, rank: index + 1 }))
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

function buildLimitTime(seed: number): string {
  const hour = seed % 6 === 0 ? 14 : 9 + Math.floor((seed % 10) / 4)
  const minute = (16 + seed * 9) % 60
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`
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

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

function roundNumber(value: number, digits = 2): number {
  return Number(value.toFixed(digits))
}

function periodFactorValue(period: PeriodValue): number {
  const map: Record<PeriodValue, number> = {
    '1w': 0.55,
    '1m': 1,
    '3m': 1.45,
    '1y': 2.1,
  }
  return map[period]
}

function getLatestWeekday(): string {
  const now = new Date()
  const cursor = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  while (cursor.getDay() === 0 || cursor.getDay() === 6) {
    cursor.setDate(cursor.getDate() - 1)
  }
  return formatDate(cursor)
}

function addDays(dateString: string, days: number): string {
  const date = new Date(`${dateString}T12:00:00`)
  date.setDate(date.getDate() + days)
  return formatDate(date)
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
  display: flex;
  flex-direction: column;
  gap: 20px;
  min-height: 100%;
  color: #122033;
}

.hero-card,
.content-shell,
.secondary-nav,
.chart-card,
.table-card,
.metric-card,
.type-card {
  border: 1px solid rgba(148, 163, 184, 0.18);
  box-shadow: 0 18px 42px rgba(15, 23, 42, 0.08);
}

.hero-card {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(360px, 1fr);
  gap: 22px;
  padding: 28px;
  border-radius: 28px;
  background:
    radial-gradient(circle at top right, rgba(37, 99, 235, 0.16), transparent 30%),
    linear-gradient(135deg, rgba(255, 255, 255, 0.98), rgba(239, 246, 255, 0.98));
}

.eyebrow {
  margin: 0 0 10px;
  font-size: 12px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: #2563eb;
}

.hero-copy h1 {
  margin: 0;
  font-size: 34px;
  line-height: 1.05;
}

.hero-description {
  margin: 12px 0 0;
  max-width: 760px;
  font-size: 14px;
  line-height: 1.7;
  color: #55657d;
}

.hero-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.hero-metric,
.metric-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 18px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.9);
}

.hero-metric span,
.metric-card span {
  font-size: 12px;
  color: #60708c;
}

.hero-metric strong,
.metric-card strong {
  font-size: 22px;
  font-weight: 700;
}

.hero-metric small,
.metric-card small {
  color: #6b7a90;
  line-height: 1.5;
}

.hero-metric.accent,
.metric-card.highlight {
  background: linear-gradient(135deg, #102a56, #1d4ed8);
  color: #f8fbff;
}

.hero-metric.accent span,
.hero-metric.accent small,
.metric-card.highlight span,
.metric-card.highlight small {
  color: rgba(248, 251, 255, 0.82);
}

.workspace-shell {
  display: grid;
  grid-template-columns: 270px minmax(0, 1fr);
  gap: 20px;
  min-height: 760px;
}

.secondary-nav {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 18px;
  border-radius: 24px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(244, 247, 251, 0.98));
}

.nav-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding-bottom: 10px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.18);
}

.nav-head span {
  font-size: 16px;
  font-weight: 700;
}

.nav-head small {
  color: #66768e;
}

.nav-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.nav-group-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 14px 16px;
  border: none;
  border-radius: 18px;
  background: rgba(241, 245, 249, 0.95);
  color: #122033;
  text-align: left;
  cursor: pointer;
}

.nav-group-toggle strong {
  display: block;
  font-size: 15px;
}

.nav-group-toggle span {
  font-size: 12px;
  color: #6b7a90;
}

.nav-group-arrow {
  font-size: 24px;
  color: #2563eb;
}

.nav-group-items {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.nav-item {
  display: flex;
  gap: 12px;
  width: 100%;
  padding: 14px;
  border: 1px solid transparent;
  border-radius: 18px;
  background: transparent;
  color: #223047;
  text-align: left;
  cursor: pointer;
  transition: transform 0.18s ease, border-color 0.18s ease, background 0.18s ease;
}

.nav-item:hover {
  transform: translateX(2px);
  border-color: rgba(37, 99, 235, 0.22);
  background: rgba(239, 246, 255, 0.8);
}

.nav-item.active {
  border-color: rgba(37, 99, 235, 0.28);
  background: linear-gradient(135deg, rgba(37, 99, 235, 0.14), rgba(59, 130, 246, 0.06));
}

.nav-item-index {
  min-width: 32px;
  font-size: 12px;
  font-weight: 700;
  color: #2563eb;
}

.nav-item-text {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.nav-item-text strong {
  font-size: 14px;
}

.nav-item-text small {
  color: #68778c;
}

.content-shell {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 22px;
  border-radius: 28px;
  background:
    radial-gradient(circle at top right, rgba(16, 185, 129, 0.07), transparent 24%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.99), rgba(248, 250, 252, 0.99));
}

.content-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
}

.toolbar-tag {
  margin: 0 0 6px;
  font-size: 12px;
  font-weight: 700;
  color: #0f766e;
}

.content-toolbar h2 {
  margin: 0;
  font-size: 28px;
}

.toolbar-description {
  margin: 10px 0 0;
  max-width: 780px;
  line-height: 1.7;
  color: #5d6b80;
}

.toolbar-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 12px;
}

.filter-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 180px;
  padding: 12px 14px;
  border-radius: 18px;
  background: rgba(241, 245, 249, 0.92);
}

.filter-label {
  font-size: 12px;
  font-weight: 600;
  color: #60708c;
}

.filter-static strong {
  font-size: 16px;
}

.context-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.context-pill,
.section-badge {
  display: inline-flex;
  align-items: center;
  padding: 8px 12px;
  border-radius: 999px;
  background: rgba(226, 232, 240, 0.82);
  color: #42526a;
  font-size: 12px;
  font-weight: 600;
}

.context-pill.warning {
  background: rgba(254, 242, 242, 0.92);
  color: #b91c1c;
}

.panel-stack,
.metric-grid {
  display: grid;
  gap: 16px;
}

.metric-grid {
  grid-template-columns: repeat(6, minmax(0, 1fr));
}

.table-card,
.chart-card {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 18px;
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.97);
}

.table-card.compact {
  padding-top: 0;
}

.section-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}

.section-head h3 {
  margin: 0;
  font-size: 20px;
}

.section-head p {
  margin: 8px 0 0;
  line-height: 1.65;
  color: #5d6b80;
}

.section-head.with-inline-tabs {
  align-items: center;
}

.ladder-table {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.ladder-row {
  display: grid;
  grid-template-columns: 110px minmax(0, 1fr);
  gap: 12px;
  align-items: stretch;
}

.ladder-level {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 6px;
  padding: 16px;
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(37, 99, 235, 0.14), rgba(37, 99, 235, 0.04));
}

.ladder-level.warm {
  background: linear-gradient(180deg, rgba(245, 158, 11, 0.16), rgba(245, 158, 11, 0.05));
}

.ladder-level.neutral {
  background: linear-gradient(180deg, rgba(15, 118, 110, 0.14), rgba(15, 118, 110, 0.05));
}

.ladder-level strong {
  font-size: 18px;
}

.ladder-level span {
  color: #68778c;
}

.ladder-content {
  padding: 14px;
  border-radius: 18px;
  background: rgba(248, 250, 252, 0.92);
}

.stock-strip-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 8px;
}

.stock-strip-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.96);
  border: 1px solid rgba(59, 130, 246, 0.12);
}

.stock-strip-card.warm {
  border-color: rgba(245, 158, 11, 0.2);
  background: rgba(255, 251, 235, 0.96);
}

.stock-strip-card.neutral {
  border-color: rgba(15, 118, 110, 0.16);
  background: rgba(240, 253, 250, 0.96);
}

.stock-strip-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  align-items: baseline;
}

.stock-strip-head strong {
  font-size: 15px;
}

.stock-strip-head span {
  color: #475569;
  font-size: 12px;
  font-weight: 600;
}

.stock-strip-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.stock-strip-meta span {
  padding: 4px 8px;
  border-radius: 999px;
  background: rgba(226, 232, 240, 0.85);
  color: #52607a;
  font-size: 12px;
}

.chart-canvas {
  width: 100%;
  height: 360px;
}

.tall-chart {
  height: 420px;
}

.inline-tabs {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 8px;
}

.inline-tab {
  padding: 10px 14px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.92);
  color: #516177;
  cursor: pointer;
}

.inline-tab.active {
  border-color: rgba(37, 99, 235, 0.36);
  background: rgba(37, 99, 235, 0.1);
  color: #1d4ed8;
  font-weight: 700;
}

.toggle-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 12px 14px;
  border-radius: 999px;
  background: rgba(241, 245, 249, 0.92);
  color: #45556d;
  cursor: pointer;
}

.toggle-chip input {
  accent-color: #2563eb;
}

@media (max-width: 1500px) {
  .metric-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 1180px) {
  .hero-card,
  .workspace-shell,
  .ladder-row {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .hero-metrics,
  .metric-grid,
  .type-grid {
    grid-template-columns: 1fr;
  }

  .content-toolbar,
  .section-head,
  .section-head.with-inline-tabs {
    flex-direction: column;
  }

  .toolbar-actions {
    width: 100%;
    justify-content: flex-start;
  }
}
</style>
