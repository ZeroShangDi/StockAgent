/**
 * API 模块统一导出
 */

// 客户端
export { api, default as client } from './client'

// 类型
export * from './types'

// 模块 API
export { authApi } from './modules/auth'
export { userApi } from './modules/user'
export { taskApi } from './modules/task'
export { stockApi } from './modules/stock'
export { strategyApi, subscriptionApi } from './modules/strategy'
export { marketApi } from './modules/market'
export { stockPickerApi } from './modules/stock-picker'
export { reportApi } from './modules/report'
export { default as backtestApi } from './modules/backtest'
export { systemApi } from './modules/system'
export { practiceApi } from './modules/practice'
export { tradeReviewApi } from './modules/trade-review'
export { assistantApi } from './modules/assistant'
export * from './modules/backtest'
export * from './modules/report'
export * from './modules/stock-picker'
export * from './modules/practice'
export * from './modules/trade-review'
export * from './modules/assistant'
