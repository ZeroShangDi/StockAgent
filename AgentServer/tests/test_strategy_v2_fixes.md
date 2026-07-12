# Strategy V2 全面测试用例

## 测试环境
- Docker Compose 环境 (stock-agent-web, stock-agent-mongo, stock-agent-redis)
- 测试账户: admin / admin123
- 测试时间: 2026-06-24/25

---

## 一、调度器基础

### T1.1 固定时间点调度触发
- 创建 pre_market_0900 任务，确认 09:00 触发
- 创建 post_market_1505 任务，确认 15:05 触发
- 验证 fire_key 去重：同时间窗口内不重复触发
- 验证 last_scheduled_fire_key 和 last_scheduled_run_at 更新

### T1.2 日内间隔调度触发
- 创建 intraday_5m 任务，确认每 5 分钟触发（仅交易时段）
- 创建 intraday_30m 任务，确认每 30 分钟触发
- 非交易时段不触发（9:15 前、11:30-13:00、15:05 后）
- 周末不触发

### T1.3 信号量串行化
- 同时触发 2 个 all_market 任务，确认顺序执行
- 验证 started_at 在信号量获取后刷新（不会被误判超时）
- 确认 _MAX_CONCURRENT_RUNS=1 生效

### T1.4 超时机制
- 验证 RUN_STALE_AFTER_SECONDS=1800 (30分钟)
- 模拟长时间运行不更新 → 应被标记为 failed
- 验证正在正常执行的任务不会被误杀

---

## 二、评估器正确性（核心）

### T2.1 IntradayPriceMoveStrategy - 实时行情
- 用已知 ts_code 调用，验证返回 price/open/high/low/pre_close 为实时数据
- 验证 data_source 字段不为 stock_daily
- 验证 timestamp 字段为当前评估时间
- 振幅 < threshold → signal=0
- 振幅 >= threshold 且 pct_chg > 0 → signal=1
- 振幅 >= threshold 且 pct_chg < 0 → signal=-1
- 方向过滤（direction=up/down/both）正确
- 实时行情不可用时返回 signal=0 + reason 说明

### T2.2 PositionIntradayPnlStrategy - 实时行情
- 验证使用实时 close/pre_close 计算 swing_pct
- 验证包含 avg_cost/quantity/cost_pnl_pct（从 context.stock 获取）
- swing_pct >= threshold 触发正确信号
- 方向过滤正确
- 实时行情不可用时返回 signal=0

### T2.3 PriceChangeStrategy - 实时行情优先
- 实时行情可用时使用实时数据
- 实时行情不可用时 fallback 到 stock_daily
- pct_chg >= threshold 触发正确信号
- 方向过滤正确

### T2.4 OneLineStockPickerStrategy - Coze
- 验证 Coze API 调用成功返回候选列表
- 匹配的股票返回 signal=1
- 不匹配的股票返回 signal=0
- 缓存机制：同一 query+date 不重复调 Coze

### T2.5 Ma5BuyStrategy - 日线数据
- 验证 MA5 计算正确
- 回踩企稳触发 signal=1
- 跌破触发 signal=-1
- 需要足够历史 K 线

---

## 三、目标解析

### T3.1 all_market 范围
- 返回最多 MAX_TARGET_STOCKS (5000) 支股票
- 使用 stock_daily 最新数据作为 stock 上下文
- 分批执行（200/批，60s 冷却）

### T3.2 trade_account 范围
- 查询 trade_review_positions 获取持仓列表
- 返回正确数量的持仓股票 + avg_cost/quantity 信息
- group_id 不存在时返回空列表

### T3.3 stock_pool 范围
- 从 stock_pool_items 查询池中股票
- 空池返回 0 targets
- 返回股票代码和名称

### T3.4 custom_stock_list 范围
- 使用用户自定义股票列表
- 数量受 MAX_STOCKS_PER_SCHEDULE 限制

---

## 四、批次执行

### T4.1 分段执行
- all_market + 非 intraday → STRATEGY_BATCH_SIZE (200)
- intraday slot → 不分段（batch_size = total）
- batch_size 至少为 1（防止 range 参数为 0）

### T4.2 批次间冷却
- 每批完成后 sleep STRATEGY_BATCH_COOLDOWN_SEC (60s)
- 最后一批不 sleep
- 冷却期间可接收取消信号

### T4.3 取消机制
- 冷却期间取消 → _ensure_run_can_continue 抛出异常
- 取消后 run_status = cancelled
- 取消后锁被释放

---

## 五、通知系统

### T5.1 通知触发
- signal != 0 且 action_type=notify 且 trigger_signals 匹配 → 发送通知
- signal = 0 → 跳过通知

### T5.2 频率控制
- daily_once: 同日同股票不重复通知
- once_then_disable: 通知一次后禁用
- unlimited: 每次都通知

### T5.3 通知内容
- 包含正确的股票代码、名称、触发价格
- 包含正确的触发原因
- 包含时间戳

### T5.4 WeCom Webhook
- 企业微信机器人正常接收消息
- 消息格式可读
- rate limiting 生效

---

## 六、动作执行

### T6.1 pool_transition (move)
- signal 匹配时股票从源池移动到目标池
- 验证股票在目标池中出现

### T6.2 pool_transition (delete)
- signal 匹配时股票从池中删除
- 验证股票已从池中消失

### T6.3 temp_list
- 正向信号股票加入临时股池
- 验证 temp_list 包含正确股票

### T6.4 审计记录
- 每个 action 执行结果记录到 strategy_v2_action_audits
- 状态为 executed/skipped/failed

---

## 七、数据完整性

### T7.1 Run 记录
- run 创建时 status=running
- 执行完成 status=success
- 执行失败 status=failed + error 信息
- 取消 status=cancelled
- 无 ObjectId 序列化错误

### T7.2 进度更新
- 批次完成后 progress_current/progress_total 更新
- progress_label 反映当前阶段

### T7.3 任务锁
- 同任务同时间只能有一个 run
- run 完成后锁释放
- 异常退出也释放锁

---

## 八、端到端场景

### T8.1 完整 intraday_5m 流程
1. 创建 trade_account + intraday_price_move + intraday_5m 任务
2. 等待下一个 5 分钟窗口触发
3. 验证：调度触发 → 目标解析 → 实时行情评估 → 通知发送 → 审计记录

### T8.2 完整 all_market 流程
1. 创建 all_market + one_line_stock_picker + pre_market_0900 任务
2. 手动触发执行
3. 验证：分批执行 → Coze 匹配 → 正向信号 → 通知 → 完成

### T8.3 多个 all_market 任务串行
1. 创建 2 个 all_market 任务，同一时间触发
2. 验证：顺序执行，第二个不超时

### T8.4 空池处理
1. 创建 stock_pool 范围任务，池为空
2. 验证：targets=0，run 正常完成，不报错

---

## 九、回归检查

### T9.1 现有 7 个任务全部正常
- 选股-趋势: 不超时，正常完成
- 选股-连涨: 不超时，正常完成
- 确认-涨幅异动: 池非空时正常评估
- 交易-持仓异动: 使用实时行情
- 交易-盈亏变化: 使用实时行情
- 择时-趋势低吸: 池非空时正常评估
- 测试-双炮池流转: 正常评估
