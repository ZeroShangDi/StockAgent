import { api } from '../client'
import type { StockDaily } from '../types'

export interface PracticeTrade {
  trade_id: string
  action: 'buy' | 'sell' | 'close' | 'auto_close'
  trade_date: string
  price: number
  shares: number
  amount: number
  allocation_pct: number
  realized_pnl: number
  note?: string | null
}

export interface PracticeTradeMarker {
  trade_date: string
  price: number
  side?: string | null
  label: string
}

export interface PracticeReveal {
  ts_code: string
  name: string
  industry?: string | null
  market?: string | null
  segment_start_date: string
  segment_end_date: string
}

export interface PracticeSessionState {
  session_id: string
  label: string
  status: 'active' | 'completed'
  initial_capital: number
  cash: number
  position_shares: number
  avg_cost: number
  market_value: number
  equity: number
  realized_pnl: number
  unrealized_pnl: number
  position_pct: number
  total_return_pct: number
  step: number
  total_steps: number
  visible_candles: StockDaily[]
  visible_weekly_candles: StockDaily[]
  visible_monthly_candles: StockDaily[]
  trades: PracticeTrade[]
  trade_markers: PracticeTradeMarker[]
  current_trade_date?: string | null
  latest_close?: number | null
  can_step: boolean
  can_buy: boolean
  can_sell: boolean
  is_revealed: boolean
  reveal?: PracticeReveal | null
  created_at?: string | null
  completed_at?: string | null
}

export interface PracticeSessionSummary {
  session_id: string
  label: string
  status: 'active' | 'completed'
  total_return_pct: number
  realized_pnl: number
  trade_count: number
  current_trade_date?: string | null
  created_at?: string | null
  completed_at?: string | null
  reveal?: PracticeReveal | null
}

export interface PracticeSessionHistoryResult {
  items: PracticeSessionSummary[]
  total: number
  skip: number
  limit: number
}

export interface PracticeStartRequest {
  init_bars?: number
  future_bars?: number
  initial_capital?: number
}

export interface PracticeTradeRequest {
  action: 'buy' | 'sell' | 'close'
  allocation_pct?: number
}

export const practiceApi = {
  getActiveSession(): Promise<PracticeSessionState | null> {
    return api.get('/practice/kline/active')
  },

  getLatestSession(): Promise<PracticeSessionState | null> {
    return api.get('/practice/kline/latest')
  },

  getSession(sessionId: string): Promise<PracticeSessionState> {
    return api.get(`/practice/kline/${sessionId}`)
  },

  getHistory(params?: { skip?: number; limit?: number }): Promise<PracticeSessionHistoryResult> {
    return api.get('/practice/kline/history', { params })
  },

  startSession(data?: PracticeStartRequest): Promise<PracticeSessionState> {
    return api.post('/practice/kline/start', data)
  },

  stepSession(sessionId: string, steps = 1): Promise<PracticeSessionState> {
    return api.post(`/practice/kline/${sessionId}/step?steps=${steps}`)
  },

  trade(sessionId: string, data: PracticeTradeRequest): Promise<PracticeSessionState> {
    return api.post(`/practice/kline/${sessionId}/trade`, data)
  },

  finishSession(sessionId: string): Promise<PracticeSessionState> {
    return api.post(`/practice/kline/${sessionId}/finish`)
  },
}

export default practiceApi
