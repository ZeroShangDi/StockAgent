/**
 * 股票数据 API
 */

import { api } from '../client'
import type { StockBasic, StockDaily, StockQuote, MarketOverview } from '../types'

export interface StockSectorTag {
  ts_code: string
  name: string
  sector_type?: string | null
  type_name?: string | null
}

export interface StockReviewContext {
  stock: {
    ts_code: string
    symbol?: string
    name: string
    area?: string | null
    industry?: string | null
    market?: string | null
    list_date?: string | null
    latest_trade_date?: string | null
    latest_price?: number | null
    latest_pct_chg?: number | null
    recent_30d_pct_chg?: number | null
    concepts: StockSectorTag[]
    sectors: StockSectorTag[]
  }
  daily: StockDaily[]
  weekly: StockDaily[]
  monthly: StockDaily[]
}

export interface StockRepairTaskStartResponse {
  task_id: string
  status: string
  message: string
}

export interface StockRepairTaskStatus {
  task_id: string
  task_type: string
  ts_code: string
  status: string
  progress: number
  current_step: string
  message?: string
  created_at: string
  started_at?: string | null
  completed_at?: string | null
  result?: Record<string, any> | null
  error_message?: string | null
}

export const stockApi = {
  /** 搜索股票 */
  searchStocks(keyword: string, limit = 20): Promise<StockBasic[]> {
    return api.get('/stocks/search', { params: { keyword, limit } })
  },
  
  /** 获取股票基本信息 */
  getStockBasic(tsCode: string): Promise<StockBasic> {
    return api.get(`/stocks/${tsCode}/basic`)
  },
  
  /** 获取日线数据 */
  getStockDaily(tsCode: string, params?: { start_date?: string; end_date?: string; limit?: number }): Promise<StockDaily[]> {
    return api.get(`/stocks/${tsCode}/daily`, { params })
  },

  /** 获取个股详情沉浸上下文 */
  getStockReviewContext(tsCode: string): Promise<StockReviewContext> {
    return api.get(`/stocks/${tsCode}/review-context`)
  },

  /** 发起单股数据补数任务 */
  createStockRepairTask(tsCode: string): Promise<StockRepairTaskStartResponse> {
    return api.post(`/stocks/${tsCode}/repair-sync`)
  },

  /** 查询单股数据补数任务状态 */
  getStockRepairTask(taskId: string): Promise<StockRepairTaskStatus> {
    return api.get(`/stocks/repair-tasks/${taskId}`)
  },
  
  /** 获取实时行情 */
  getRealtimeQuotes(tsCodes: string[]): Promise<StockQuote[]> {
    return api.post('/stocks/realtime', { ts_codes: tsCodes })
  },
  
  /** 获取大盘概览 */
  getMarketOverview(tradeDate?: string): Promise<MarketOverview> {
    return api.get('/market/overview', { params: { trade_date: tradeDate } })
  },
  
  /** 获取行业列表 */
  getIndustries(): Promise<string[]> {
    return api.get('/stocks/industries')
  },
  
  /** 按行业获取股票 */
  getStocksByIndustry(industry: string, limit = 50): Promise<StockBasic[]> {
    return api.get(`/stocks/by-industry/${industry}`, { params: { limit } })
  },
}
