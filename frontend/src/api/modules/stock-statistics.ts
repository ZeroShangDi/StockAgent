import { api } from '../client'
import { marketApi } from './market'

export interface StockStatisticsTradeCalendar {
  latestTradeDate: string
  tradeDates: string[]
  source: 'backend' | 'fallback'
}

export interface StockStatisticsLimitItem {
  ts_code: string
  code: string
  name: string
  theme: string
  board_count: number
  limit_type: string
  limit_time: string
  seal_amount: number
}

export interface StockStatisticsLimitSnapshot {
  trade_date: string
  source: string
  warnings: string[]
  limit_fleet: {
    total_count: number
    groups: Array<{
      key: string
      label: string
      count: number
      items: StockStatisticsLimitItem[]
    }>
    detail: StockStatisticsLimitItem[]
  }
  limit_types: {
    groups: Array<{
      type: string
      count: number
      share: number
      items: StockStatisticsLimitItem[]
    }>
    detail: Array<StockStatisticsLimitItem & {
      type: string
      board_band_label: string
    }>
  }
}

export interface StockStatisticsLeaderCycle {
  period: string
  source: string
  warnings: string[]
  rankings: Array<{
    rank: number
    ts_code: string
    code: string
    name: string
    theme: string
    limit_count: number
    max_board: number
  }>
  promotion_trend: Array<{
    date: string
    total: number
    step12: number
    step23: number
    step34: number
    step45: number
    step56: number
    step67: number
    step7Plus: number
  }>
}

export interface StockStatisticsSentiment {
  period: string
  latest_trade_date: string
  source: string
  warnings: string[]
  latest: {
    date: string
    promotion_rate: number
    total_promotion_rate: number
    explosion_rate: number
    exploded_count: number
    try_limit_count: number
    avg_follow_return: number
    open_premium: number
    high_premium: number
    limit_count: number
    prev_limit_count: number
  }
  trend: Array<{
    date: string
    promotion_rate: number
    total_promotion_rate: number
    explosion_rate: number
    exploded_count: number
    try_limit_count: number
    avg_follow_return: number
    open_premium: number
    high_premium: number
    limit_count: number
    prev_limit_count: number
  }>
}

export interface StockStatisticsStageGainers {
  period: string
  source: string
  warnings: string[]
  rankings: Array<{
    rank: number
    ts_code: string
    code: string
    name: string
    theme: string
    start_price: number
    current_price: number
    gain_pct: number
    max_drawdown_pct: number
  }>
}

export interface StockStatisticsNextdayWinRate {
  period: string
  sample_definition: string
  source: string
  warnings: string[]
  rankings: Array<{
    rank: number
    ts_code: string
    code: string
    name: string
    theme: string
    sample_count: number
    nextday_up_count: number
    win_rate: number
    avg_nextday_return: number
    signal_source: string
  }>
}

export interface StockStatisticsStreakBoard {
  source: string
  warnings: string[]
  up: Array<{
    rank: number
    ts_code: string
    code: string
    name: string
    theme: string
    days: number
    date_range: string
  }>
  down: Array<{
    rank: number
    ts_code: string
    code: string
    name: string
    theme: string
    days: number
    date_range: string
  }>
}

export interface StockStatisticsRebound {
  period: string
  source: string
  warnings: string[]
  rankings: Array<{
    rank: number
    ts_code: string
    code: string
    name: string
    lowest_date: string
    lowest_price: number
    current_price: number
    rebound_pct: number
    period_low_label: string
  }>
}

export const stockStatisticsApi = {
  async getTradeCalendar(): Promise<StockStatisticsTradeCalendar> {
    try {
      const [latest, statsTable] = await Promise.all([
        marketApi.getLatest(),
        marketApi.getStatsTable(30),
      ])

      const latestTradeDate = normalizeTradeDate(latest.trade_date)
      const tradeDates = Array.from(new Set([
        latestTradeDate,
        ...statsTable.data.map((item) => normalizeTradeDate(item.trade_date)),
      ]))
        .filter(Boolean)
        .sort()

      if (!latestTradeDate || !tradeDates.length) {
        throw new Error('trade calendar unavailable')
      }

      return {
        latestTradeDate,
        tradeDates,
        source: 'backend',
      }
    } catch {
      const latestTradeDate = getLatestWeekdayFromNow()
      return {
        latestTradeDate,
        tradeDates: generateTradeDates(latestTradeDate, 30),
        source: 'fallback',
      }
    }
  },

  getLimitSnapshot(tradeDate?: string): Promise<StockStatisticsLimitSnapshot> {
    return api.get('/market/statistics/limit-snapshot', { params: { trade_date: tradeDate } })
  },

  getLeaderCycle(period: string): Promise<StockStatisticsLeaderCycle> {
    return api.get('/market/statistics/leader-cycle', { params: { period } })
  },

  getSentiment(period: string): Promise<StockStatisticsSentiment> {
    return api.get('/market/statistics/sentiment', { params: { period } })
  },

  getStageGainers(period: string): Promise<StockStatisticsStageGainers> {
    return api.get('/market/statistics/stage-gainers', { params: { period } })
  },

  getNextdayWinRate(period: string): Promise<StockStatisticsNextdayWinRate> {
    return api.get('/market/statistics/nextday-win-rate', { params: { period } })
  },

  getStreakBoard(): Promise<StockStatisticsStreakBoard> {
    return api.get('/market/statistics/streak-board')
  },

  getRebound(period: string): Promise<StockStatisticsRebound> {
    return api.get('/market/statistics/rebound', { params: { period } })
  },
}

function normalizeTradeDate(value?: string | null): string {
  const text = String(value || '').trim()
  if (!text) return ''
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return text
  if (/^\d{8}$/.test(text)) {
    return `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}`
  }
  return text
}

function getLatestWeekdayFromNow(): string {
  const now = new Date()
  const candidate = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const day = candidate.getDay()
  if (day === 6) {
    candidate.setDate(candidate.getDate() - 1)
  } else if (day === 0) {
    candidate.setDate(candidate.getDate() - 2)
  }
  return formatDate(candidate)
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

export default stockStatisticsApi
