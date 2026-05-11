import { api } from '../client'

export const STOCK_POOL_TYPE_OPTIONS = ['候选池', '观察池', '监控池', '自选池'] as const

export type StockPoolTypeOption = typeof STOCK_POOL_TYPE_OPTIONS[number]

export interface StockPickerMeta {
  code: string
  ts_code: string
  name: string
  market: string
}

export interface StockPickerRow {
  __row_id: number
  __meta: StockPickerMeta
  [key: string]: any
}

export interface StockPickerQueryResult {
  run_id: string
  input: string
  query_condition: string
  headers: string[]
  data_list: StockPickerRow[]
  statistics: Record<string, any>
  code_list: string[]
  ts_code_list: string[]
  total: number
}

export interface StockPoolSummary {
  pool_id: string
  name: string
  pool_type: string
  description?: string | null
  stock_count: number
  avg_pct_chg?: number | null
  latest_trade_date?: string | null
  updated_at?: string
}

export interface StockPoolStock {
  ts_code: string
  code: string
  name?: string
  status?: string
  source_module?: string
  source_run_id?: string
  source_query?: string
  source_pool_name?: string
  added_at?: string
  latest_pct_chg?: number | null
  latest_price?: number | null
  latest_trade_date?: string | null
}

export interface StockPoolDetail extends StockPoolSummary {
  stocks: StockPoolStock[]
  source_module?: string
  created_at?: string
}

export interface StockPoolReviewContext {
  pool: StockPoolSummary
  stock: {
    ts_code: string
    code: string
    name: string
    status?: string
    source_module?: string
    source_query?: string
    source_pool_name?: string
    latest_pct_chg?: number | null
    latest_price?: number | null
    latest_trade_date?: string | null
    industry?: string | null
    market?: string | null
    list_date?: string | null
    added_at?: string
    recent_30d_pct_chg?: number | null
    concepts?: Array<{
      ts_code: string
      name: string
      sector_type?: string | null
      type_name?: string | null
    }>
    sectors?: Array<{
      ts_code: string
      name: string
      sector_type?: string | null
      type_name?: string | null
    }>
  }
  daily: Array<{
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
  }>
  weekly: Array<{
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
  }>
  monthly: Array<{
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
  }>
  related_stocks: Array<StockPoolStock & { is_current?: boolean }>
  navigation: {
    position: number
    total: number
    previous_ts_code?: string | null
    next_ts_code?: string | null
  }
}

export interface StockPickerRunReviewContext {
  run: {
    run_id: string
    input: string
    query_condition: string
    total: number
    created_at?: string
  }
  stock: StockPoolReviewContext['stock']
  daily: StockPoolReviewContext['daily']
  weekly: StockPoolReviewContext['weekly']
  monthly: StockPoolReviewContext['monthly']
  related_stocks: StockPoolReviewContext['related_stocks']
  navigation: StockPoolReviewContext['navigation']
}

export interface StockPoolListResult {
  items: StockPoolSummary[]
}

export interface CreateStockPoolRequest {
  name: string
  pool_type: StockPoolTypeOption | string
  description?: string
}

export interface AddStocksToPoolRequest {
  stocks: Array<{ ts_code: string; code: string; name?: string }>
  source_run_id?: string
  source_query?: string
  source_module?: string
  source_pool_name?: string
}

export interface AddStocksToPoolResult {
  message: string
  added: number
  pool: StockPoolSummary
}

export interface RemoveStocksFromPoolResult {
  message: string
  removed: number
  pool: StockPoolSummary
}

export const stockPickerApi = {
  query(input: string): Promise<StockPickerQueryResult> {
    return api.post('/stock-picker/query', { input })
  },

  listPools(): Promise<StockPoolListResult> {
    return api.get('/stock-picker/pools')
  },

  getPoolDetail(poolId: string): Promise<StockPoolDetail> {
    return api.get(`/stock-picker/pools/${poolId}`)
  },

  getPoolReviewContext(poolId: string, tsCode: string): Promise<StockPoolReviewContext> {
    return api.get(`/stock-picker/pools/${poolId}/review/${tsCode}`)
  },

  getRunReviewContext(runId: string, tsCode: string): Promise<StockPickerRunReviewContext> {
    return api.get(`/stock-picker/runs/${runId}/review/${tsCode}`)
  },

  createPool(data: CreateStockPoolRequest): Promise<StockPoolSummary> {
    return api.post('/stock-picker/pools', data)
  },

  addStocksToPool(poolId: string, data: AddStocksToPoolRequest): Promise<AddStocksToPoolResult> {
    return api.post(`/stock-picker/pools/${poolId}/stocks`, data)
  },

  removeStocksFromPool(poolId: string, tsCodes: string[]): Promise<RemoveStocksFromPoolResult> {
    return api.delete(`/stock-picker/pools/${poolId}/stocks`, {
      data: { ts_codes: tsCodes },
    })
  },

  deletePool(poolId: string): Promise<{ message: string; pool_id: string }> {
    return api.delete(`/stock-picker/pools/${poolId}`)
  },
}

export default stockPickerApi
