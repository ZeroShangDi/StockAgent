import { api } from '../client'
import type { StockDaily } from '../types'
import type { StockSectorTag } from './stock'

export const TRADE_REVIEW_REASON_OPTIONS = {
  success: ['顺势而为', '板块共振', '买点前置', '纪律执行', '仓位合适', '止盈及时', '逻辑充分', '情绪稳定'],
  failure: ['追高买入', '逆势交易', '仓位过重', '卖点滞后', '止损不坚决', '逻辑不清', '受情绪影响', '节奏错误'],
} as const

export interface TradeReviewGroupSummary {
  group_id: string
  name: string
  description?: string | null
  record_count: number
  trade_record_count: number
  last_imported_at?: string | null
  created_at?: string
  updated_at?: string
}

export interface TradeReviewRecord {
  record_id: string
  group_id: string
  batch_id?: string
  trade_date: string
  business_type: string
  shareholder_account?: string | null
  code: string
  ts_code: string
  security_name?: string | null
  quantity: number
  price: number
  commission: number
  stamp_tax: number
  other_fee: number
  transfer_fee: number
  clearing_fee: number
  amount: number
  balance: number
  currency?: string | null
  remark?: string | null
  source_label?: string | null
  category: string
  side?: 'buy' | 'sell' | null
  is_trade_record: boolean
  reviewed: boolean
  operation_reason: string
  mindset: string
  market_context: string
  result_reasons: {
    verdict: '' | 'success' | 'failure'
    reasons: string[]
  }
  updated_at?: string
  created_at?: string
}

export interface TradeReviewRecordListResult {
  items: TradeReviewRecord[]
  total: number
  skip: number
  limit: number
}

export interface TradeReviewStatsResult {
  summary: {
    total_records: number
    trade_records: number
    buy_count: number
    sell_count: number
    reviewed_count: number
    review_coverage_pct: number
    total_buy_amount: number
    total_sell_amount: number
    total_fee: number
    net_cash_flow: number
  }
  category_counts: Array<{ name: string; count: number }>
  business_type_counts: Array<{ name: string; count: number }>
  top_stocks: Array<{ name: string; count: number }>
  monthly_trade_counts: Array<{ month: string; count: number }>
  reason_counts: {
    success: Array<{ name: string; count: number }>
    failure: Array<{ name: string; count: number }>
  }
}

export interface TradeReviewPositionItem {
  position_id: string
  group_id: string
  ts_code: string
  code: string
  name?: string | null
  quantity: number
  avg_cost: number
  total_cost: number
  latest_price?: number | null
  latest_trade_date?: string | null
  market_value: number
  unrealized_pnl: number
  unrealized_pnl_pct: number
  buy_count: number
  sell_count: number
  total_buy_amount: number
  total_sell_amount: number
  first_trade_date?: string | null
  last_trade_date?: string | null
  price_source?: string
  security_type?: 'stock' | 'other'
  updated_at?: string
}

export interface TradeReviewPositionResult {
  group: TradeReviewGroupSummary
  summary: {
    position_count: number
    total_cost: number
    total_market_value: number
    total_unrealized_pnl: number
    total_unrealized_pnl_pct: number
    profitable_count: number
    loss_count: number
    latest_valuation_date?: string | null
    updated_at?: string
  }
  items: TradeReviewPositionItem[]
}

export interface TradeReviewKlineMarker {
  record_id: string
  trade_date: string
  price: number
  side?: 'buy' | 'sell' | null
  label: string
  is_current: boolean
}

export interface TradeReviewKlineContext {
  record: TradeReviewRecord
  stock: {
    ts_code: string
    name?: string | null
    industry?: string | null
    market?: string | null
    list_date?: string | null
    latest_trade_date?: string | null
    latest_price?: number | null
    latest_pct_chg?: number | null
    recent_30d_pct_chg?: number | null
    concepts?: StockSectorTag[]
    sectors?: StockSectorTag[]
  }
  daily: StockDaily[]
  weekly: StockDaily[]
  monthly: StockDaily[]
  markers: TradeReviewKlineMarker[]
  related_records: TradeReviewRecord[]
  navigation: {
    anchor_record_id: string
    previous_record_id?: string | null
    next_record_id?: string | null
    position: number
    total: number
  }
  zoom: {
    start: number
    end: number
    window: number
  }
}

export const tradeReviewApi = {
  listGroups(): Promise<{ items: TradeReviewGroupSummary[] }> {
    return api.get('/trade-review/groups')
  },

  createGroup(data: { name: string; description?: string }): Promise<TradeReviewGroupSummary> {
    return api.post('/trade-review/groups', data)
  },

  importCsv(groupId: string, file: File): Promise<{
    batch_id: string
    group: TradeReviewGroupSummary
    total_rows: number
    imported_rows: number
    duplicate_rows: number
    trade_rows: number
  }> {
    const formData = new FormData()
    formData.append('file', file)
    return api.post(`/trade-review/groups/${groupId}/import`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  listRecords(
    groupId: string,
    params?: { category?: string; skip?: number; limit?: number; keyword?: string },
  ): Promise<TradeReviewRecordListResult> {
    return api.get(`/trade-review/groups/${groupId}/records`, { params })
  },

  updateRecord(
    recordId: string,
    data: {
      operation_reason: string
      mindset: string
      market_context: string
      result_reasons: { verdict: '' | 'success' | 'failure'; reasons: string[] }
    },
  ): Promise<TradeReviewRecord> {
    return api.patch(`/trade-review/records/${recordId}`, data)
  },

  getStats(groupId: string): Promise<TradeReviewStatsResult> {
    return api.get(`/trade-review/groups/${groupId}/stats`)
  },

  getPositions(groupId: string, forceRefresh = false): Promise<TradeReviewPositionResult> {
    return api.get(`/trade-review/groups/${groupId}/positions`, { params: { force_refresh: forceRefresh } })
  },

  rebuildPositions(groupId: string): Promise<TradeReviewPositionResult> {
    return api.post(`/trade-review/groups/${groupId}/positions/rebuild`)
  },

  getKline(
    recordId: string,
    params?: { window?: number; category?: string; keyword?: string; anchor_record_id?: string },
  ): Promise<TradeReviewKlineContext> {
    return api.get(`/trade-review/records/${recordId}/kline`, { params })
  },
}

export default tradeReviewApi
