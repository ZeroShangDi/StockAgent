import { api } from '../client'

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
  added_at?: string
}

export interface StockPoolDetail extends StockPoolSummary {
  stocks: StockPoolStock[]
  source_module?: string
  created_at?: string
}

export interface StockPoolListResult {
  items: StockPoolSummary[]
}

export interface CreateStockPoolRequest {
  name: string
  pool_type: string
  description?: string
}

export interface AddStocksToPoolRequest {
  stocks: Array<{ ts_code: string; code: string; name?: string }>
  source_run_id?: string
  source_query?: string
  source_module?: string
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
