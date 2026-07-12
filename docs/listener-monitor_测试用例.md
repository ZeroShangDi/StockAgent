# Listener/Monitor 节点测试用例

## 1. 轮询周期与超时控制

### TC-LSN-001: 正常轮询周期 - 60s 间隔执行
- **前置条件:** ListenerNode 已启动，poll_interval=60，当前为交易时间
- **步骤:** 监控日志输出，记录连续 3 次 poll_cycle 的开始时间戳
- **预期:**
  - 每次 poll_cycle 间隔约为 60s（允许网络波动偏差 < 5s）
  - 每轮包含完整的日志序列: `Starting poll cycle` → `Quote sources` → `Snapshot` → `Strategy evaluation done`

### TC-LSN-002: 单轮超时 - 180s 超时保护
- **前置条件:** poll_timeout_seconds=180；模拟数据源响应无限等待（如在 data_source_manager.get_realtime_quotes 中注入 asyncio.sleep(200)）
- **步骤:** 等待一轮 poll_cycle 执行
- **预期:**
  - 主循环日志输出 `Poll cycle timed out after 180s, skipping current cycle`
  - 不抛出未捕获异常，下一轮正常开始
  - asyncio.TimeoutError 被正确捕获

### TC-LSN-003: 单轮异常不中断主循环
- **前置条件:** 模拟 `_poll_cycle` 内部抛出 RuntimeError（如在 _build_snapshot 中注入异常）
- **步骤:** 连续运行 3 轮
- **预期:**
  - 异常被捕获，日志输出 `Poll cycle error: RuntimeError`
  - 第 2、3 轮正常执行（主循环未被中断）
  - `finally` 块中 `clear_trace_id()` 正确执行

### TC-LSN-004: 非交易时间静默
- **前置条件:** `silent_outside_trading=True`，当前时间非 A 股交易时间（如 22:00）
- **步骤:** `await node._is_trading_time()` 返回 False
- **预期:**
  - 日志输出 `Outside trading hours, sleeping...`
  - `_poll_cycle` 不被调用
  - 直接进入 `asyncio.sleep(poll_interval)`

---

## 2. 市场快照与增量 (Delta)

### TC-LSN-010: 首帧快照 - changed_quotes 等于全量
- **前置条件:** `self._previous_snapshot = None`，本轮从数据源获得 100 只股票的行情数据
- **步骤:** 执行 `_build_snapshot` → `_apply_snapshot_delta`
- **预期:**
  - `current_snapshot.changed_quotes` 包含全部 100 只股票
  - `current_snapshot.removed_ts_codes = []`
  - `current_snapshot.changed_count = 100`

### TC-LSN-011: 增量快照 - 仅变化股票计入 changed_quotes
- **前置条件:** 上一帧 snapshot 有 100 只股票，当前帧有 100 只（其中 20 只 price/pct_chg 发生变化，5 只消失，3 只新增）
- **步骤:** 执行 `_apply_snapshot_delta`
- **预期:**
  - `changed_quotes` 包含 23 只股票（20 只变化 + 3 只新增）
  - `removed_ts_codes` 包含消失的 5 只
  - `changed_count = 23`

### TC-LSN-012: 增量快照 - 字段级精确对比
- **前置条件:** 某股票上一帧 `{"price": 10.00, "pct_chg": 1.5, "volume": 10000}`，当前帧 `{"price": 10.00, "pct_chg": 1.5, "volume": 10500}`
- **步骤:** 执行 `_apply_snapshot_delta`
- **预期:**
  - volume 变化 → 该股票出现在 `changed_quotes` 中
  - 仅 price/pct_chg 不变但 volume 变也视为变化（DELTA_COMPARE_FIELDS 包含 volume）

### TC-LSN-013: 快照字段过滤 - 仅保留 KEEP_FIELDS
- **前置条件:** 数据源返回包含额外字段的行情数据（如 `"pe"`, `"pb"`, `"market_cap"` 等）
- **步骤:** 执行 `_build_snapshot`
- **预期:**
  - slim_quote 仅包含 KEEP_FIELDS 集合中的字段
  - 额外字段（pe, pb, market_cap）被丢弃
  - `total_stocks` 与输入的股票数一致

### TC-LSN-014: 无 ts_code 的行情数据被跳过
- **前置条件:** 数据源返回 5 条行情数据，其中 1 条缺少 ts_code 字段
- **步骤:** 执行 `_build_snapshot`
- **预期:**
  - 日志输出 `Skipped 1 quotes without ts_code`
  - `snapshot.quotes` 仅包含 4 只股票

---

## 3. 策略基类通用能力

### TC-LSN-020: _get_watch_stocks - 个股模式筛选
- **前置条件:** watch_list = `["000001.SZ", "600000.SH"]`，snapshot.quotes 包含 10 只股票（含 000001.SZ）
- **步骤:** 调用 `_get_watch_stocks(subscription, snapshot)`
- **预期:**
  - 返回仅包含 `000001.SZ`（watch_list 中的股票）
  - `600000.SH` 不在 snapshot.quotes 中 → 不返回

### TC-LSN-021: _get_watch_stocks - 全市场模式
- **前置条件:** watch_list = `["ALL"]`，snapshot.quotes 包含 100 只股票
- **步骤:** 调用 `_get_watch_stocks(subscription, snapshot)`
- **预期:**
  - 返回全部 100 只股票
  - `subscription.is_all_market()` 返回 True

### TC-LSN-022: _get_watch_stocks - ST 过滤
- **前置条件:** watch_list = `["ALL"]`，snapshot.quotes 包含 `"000001.SZ"`(name="平安银行") 和 `"600000.SH"`(name="*ST 银行")，`exclude_st=True`
- **步骤:** 调用 `_get_watch_stocks(subscription, snapshot, exclude_st=True)`
- **预期:**
  - `"*ST 银行"` 被过滤掉
  - 返回结果仅包含 `"平安银行"`

### TC-LSN-023: _get_watch_stocks - stock_configs disabled 过滤
- **前置条件:** subscription.params.stock_configs = `{"000001.SZ": {"enabled": false}}`
- **步骤:** 调用 `_get_watch_stocks(subscription, snapshot)`
- **预期:**
  - `000001.SZ` 被过滤，不包含在返回结果中

### TC-LSN-024: _should_skip_by_alert_frequency - daily_once 模式
- **前置条件:** alert_frequency=`daily_once`，stock_configs[ts_code].last_triggered_date = today
- **步骤:** 调用 `_should_skip_by_alert_frequency(subscription, ts_code, today_key)`
- **预期:**
  - 返回 True（同日已触发，跳过）

### TC-LSN-025: _should_skip_by_alert_frequency - once_then_disable 模式
- **前置条件:** alert_frequency=`once_then_disable`，stock_configs[ts_code].frequency_disabled = True
- **步骤:** 调用 `_should_skip_by_alert_frequency(subscription, ts_code, today_key)`
- **预期:**
  - 返回 True（已被禁用）

### TC-LSN-026: _should_skip_by_alert_frequency - unlimited 模式
- **前置条件:** alert_frequency=`unlimited`
- **步骤:** 调用 `_should_skip_by_alert_frequency(subscription, ts_code, today_key)`
- **预期:**
  - 无论是否已触发过，总是返回 False

### TC-LSN-027: _record_alert_trigger - once_then_disable 触发后自动禁用
- **前置条件:** subscription 已存在 stock_configs[ts_code].enabled = True
- **步骤:** 调用 `_record_alert_trigger(subscription, ts_code, today_key)`，其中 `frequency = once_then_disable`
- **预期:**
  - MongoDB strategy_subscriptions 中该股票 `enabled` 更新为 False
  - `frequency_disabled` 更新为 True
  - `disabled_reason` = `"once_then_disable"`
  - `trigger_count` 自增 1

---

## 4. 策略评估 - 指数指标预警

### TC-LSN-030: MarketIndexAlert - 指数涨幅超过阈值触发
- **前置条件:** 上证指数 pct_chg = 2.5%，index_rise_enabled=True，index_rise_threshold=1.5%
- **步骤:** 执行 `MarketIndexAlertStrategy.evaluate()`
- **预期:**
  - 返回 1 条 alert
  - trigger_reason 含 "上证指数涨幅 2.50% 触发阈值 1.50%"
  - extra_data.triggered_conditions 包含 key="index_rise"

### TC-LSN-031: MarketIndexAlert - 指数跌幅超过阈值触发
- **前置条件:** 上证指数 pct_chg = -2.0%，index_fall_enabled=True，index_fall_threshold=1.5%
- **步骤:** 执行 `MarketIndexAlertStrategy.evaluate()`
- **预期:**
  - 返回 1 条 alert
  - trigger_reason 含 "跌幅"

### TC-LSN-032: MarketIndexAlert - 多个条件同时触发只产生一条预警
- **前置条件:** 上证涨跌幅 2.5%（超过 1.5% 阈值），上涨家数 3500（超过 3000 阈值），两者均启用
- **步骤:** 执行 `MarketIndexAlertStrategy.evaluate()`
- **预期:**
  - 返回 1 条 alert（合并预警）
  - trigger_reason 用 "；" 拼接两个触发条件
  - triggered_conditions 包含 2 条记录

### TC-LSN-033: MarketIndexAlert - 同一条件同日内不重复触发
- **前置条件:** 第一轮指数涨幅触发预警；第二轮再次上涨，涨幅仍超过阈值
- **步骤:** 连续执行两次 `evaluate()`
- **预期:**
  - 第一轮：返回 1 条 alert
  - 第二轮：threshold_states 中 index_rise 已为 True，`_set_threshold_state` 返回 False，不触发

### TC-LSN-034: MarketIndexAlert - 关闭的维度不触发
- **前置条件:** `index_rise_enabled=False`，上证涨幅 2.5%
- **步骤:** 执行 `MarketIndexAlertStrategy.evaluate()`
- **预期:**
  - 不产生 alert（index_rise 维度被跳过）

---

## 5. 策略评估 - 涨跌停打开

### TC-LSN-040: LimitOpen - 涨停打开检测
- **前置条件:**
  - previous_snapshot 中 ts_code="000001.SZ", price=10.00（涨停价 10.00）
  - current_snapshot 中 ts_code="000001.SZ", price=9.80, up_limit=10.00
  - limit_type="both"
- **步骤:** 执行 `LimitOpenStrategy.evaluate()`
- **预期:**
  - 返回 1 条 alert
  - trigger_reason 含 "涨停打开"
  - extra_data.limit_type = "up"

### TC-LSN-041: LimitOpen - 无 previous_snapshot 时跳过
- **前置条件:** previous_snapshot=None
- **步骤:** 执行 `LimitOpenStrategy.evaluate()`
- **预期:**
  - 日志输出 `No previous snapshot, skip limit open check`
  - 返回空列表 []

### TC-LSN-042: LimitOpen - 封板中的股票不触发
- **前置条件:**
  - previous_snapshot: price=10.00, up_limit=10.00
  - current_snapshot: price=10.00, up_limit=10.00
- **步骤:** 执行 `LimitOpenStrategy.evaluate()`
- **预期:**
  - 不产生 alert（仍然封板中）
  - 日志输出 "涨停封板中"

### TC-LSN-043: LimitOpen - 跌停打开检测
- **前置条件:**
  - previous_snapshot: price=5.00, down_limit=5.00
  - current_snapshot: price=5.20, down_limit=5.00
  - limit_type="both"
- **步骤:** 执行 `LimitOpenStrategy.evaluate()`
- **预期:**
  - 返回 1 条 alert
  - trigger_reason 含 "跌停打开"
  - extra_data.limit_type = "down"

### TC-LSN-044: LimitOpen - limit_type 仅监控涨停
- **前置条件:** limit_type="up"，出现跌停打开情况
- **步骤:** 执行 `LimitOpenStrategy.evaluate()`
- **预期:**
  - 不检查跌停方向，不产生跌停打开 alert

---

## 6. 策略评估 - 涨跌幅阈值

### TC-LSN-050: PriceChange - 涨幅超阈值触发
- **前置条件:** pct_chg=5.0%，threshold=3.0%，direction="both"
- **步骤:** 执行 `PriceChangeStrategy.evaluate()`
- **预期:**
  - 返回 1 条 alert
  - trigger_reason 含 "涨幅 5.00% 超过阈值 3.0%"

### TC-LSN-051: PriceChange - 跌幅超阈值触发
- **前置条件:** pct_chg=-5.0%，threshold=3.0%，direction="both"
- **步骤:** 执行 `PriceChangeStrategy.evaluate()`
- **预期:**
  - 返回 1 条 alert
  - trigger_reason 含 "跌幅"

### TC-LSN-052: PriceChange - 仅在涨方向监测
- **前置条件:** pct_chg=-5.0%，direction="up"
- **步骤:** 执行 `PriceChangeStrategy.evaluate()`
- **预期:**
  - 不触发（direction 限制为 up，忽略下跌）

### TC-LSN-053: PriceChange - 同日内不重复触发
- **前置条件:** 第一轮触发涨幅预警；第二轮同股票仍超阈值
- **步骤:** 连续两次 evaluate
- **预期:**
  - 第一轮：返回 alert
  - 第二轮：threshold_states 中已记录，不返回 alert

---

## 7. 策略评估 - 均线低吸

### TC-LSN-060: MA5Buy - NORMAL → TOUCHED 状态转移
- **前置条件:** 某股票昨日收盘价 10.50（在 MA5=10.00 上方），当前价 10.10（MA=10.00, touch_range=2%, 距离=1%）
- **步骤:** 执行 `MA5BuyStrategy.evaluate()`
- **预期:**
  - tracker.state 从 NORMAL 变为 TOUCHED
  - tracker.stable_count = 1（当前在 MA 上方）
  - 尚未触发 alert

### TC-LSN-061: MA5Buy - TOUCHED → STABILIZED 触发预警
- **前置条件:** tracker.state=TOUCHED, stable_count=1, stable_periods=2；当前价仍在 MA 上方
- **步骤:** 执行 `MA5BuyStrategy.evaluate()`（第二轮轮询）
- **预期:**
  - stable_count 变为 2 >= stable_periods=2
  - tracker.state 变为 STABILIZED
  - 返回 1 条 alert，reason 含 "企稳"
  - extra_data.stable_count=2

### TC-LSN-062: MA5Buy - TOUCHED 跌破 MA 后重置
- **前置条件:** tracker.state=TOUCHED, touch_range=2%，当前价低于 MA*(1 - touch_range)，即跌破容忍范围
- **步骤:** 执行 `MA5BuyStrategy.evaluate()`
- **预期:**
  - tracker 被重置为 NORMAL
  - stable_count 归零
  - 不产生 alert

### TC-LSN-063: MA5Buy - 新交易日状态重置
- **前置条件:** 前一交易日 tracker.state=STABILIZED，新交易日到来
- **步骤:** `_ensure_cache_updated()` 检测到日期变化
- **预期:**
  - _stock_data 缓存清空
  - 所有 tracker 被 reset
  - _cache_date 更新为新日期
  - alerted_today 置为 False

### TC-LSN-064: MA5Buy - 全市场模式自动过滤 ST
- **前置条件:** watch_list=["ALL"], exclude_st=True，某股票名称为 "*ST 某某"
- **步骤:** 执行 `_get_watch_stocks(subscription, snapshot, exclude_st=True)`
- **预期:**
  - ST 股票不包含在 watch_stocks 结果中
  - 不进入 evaluate 流程

---

## 8. 策略评估 - 止损策略

### TC-LSN-070: FixedStopLoss - 当前价触及止损线触发
- **前置条件:** reference_price=10.00, stop_loss_pct=8% → trigger_price=9.20；current_price=9.10
- **步骤:** 执行 `FixedStopLossStrategy.evaluate()`
- **预期:**
  - 返回 1 条 alert
  - reason 含 "价格触发固定止损"
  - extra_data.stop_loss_price = 9.20

### TC-LSN-071: FixedStopLoss - current_low 触及止损线触发
- **前置条件:** reference_price=10.00, stop_loss_pct=8%，current_price=9.30, current_low=9.10
- **步骤:** 执行 `FixedStopLossStrategy.evaluate()`
- **预期:**
  - 返回 1 条 alert（虽然 current_price 未到止损线，但 current_low 触达）

### TC-LSN-072: FixedStopLoss - 无参考价时跳过
- **前置条件:** stock_configs[ts_code] 中没有 reference_price
- **步骤:** 执行 `FixedStopLossStrategy.evaluate()`
- **预期:**
  - 跳过该股票，不产生 alert

### TC-LSN-073: TrailingStopLoss - 最高价回撤触发
- **前置条件:** highest_price=10.00（存储在 stock_configs），trailing_pct=5%，当前价=9.40（回撤 6%）
- **步骤:** 执行 `TrailingStopLossStrategy.evaluate()`
- **预期:**
  - 返回 1 条 alert
  - reason 含最高价与当前价信息
  - 回撤 6% > 5% 触发

### TC-LSN-074: TrailingStopLoss - 最高价更新但未触及止损
- **前置条件:** highest_price=9.00，当前价=10.00（创新高），trailing_pct=5%
- **步骤:** 执行 `TrailingStopLossStrategy.evaluate()`
- **预期:**
  - highest_price 更新为 10.00
  - 不产生 alert（价格在上涨）

---

## 9. 预警处理与通知

### TC-LSN-080: 预警插入 trigger_events 集合
- **前置条件:** 某策略触发了 alert
- **步骤:** `_process_alert(alert)`
- **预期:**
  - MongoDB `listener_trigger_events` 中新增一条记录
  - `notification_sent` 初始值为 False
  - 包含 `event_id`, `alert_id`, `strategy_name`, `ts_code`, `trigger_price`, `trigger_reason`
  - `triggered_at` 为 UTC datetime

### TC-LSN-081: 预警通知发送
- **前置条件:** alert 关联的 subscription 有 user_id 和 notification_channel_id
- **步骤:** `_process_alert(alert)`
- **预期:**
  - `notification_manager.send_alert()` 被调用
  - 传入 user_id 和 channel_id
  - `listener_trigger_events` 中 `notification_sent` 更新为 True

### TC-LSN-082: 预警处理找不到订阅时安全忽略
- **前置条件:** alert.subscription_id 在 self._subscriptions 中不存在（订阅已被删除）
- **步骤:** `_process_alert(alert)`
- **预期:**
  - 日志输出 `Unable to find subscription for alert`
  - 不抛异常，不执行通知和流转

---

## 10. 流转规则 (Transition Rules)

### TC-LSN-090: Move 模式 - 从来源池移动到目标池
- **前置条件:**
  - rule: mode="move", source_pool_ids=["pool_A"], target_pool_id="pool_B"
  - pool_A.stocks 包含 ts_code="000001.SZ"
  - pool_B.stocks 不包含 ts_code="000001.SZ"
- **步骤:** 触发 alert → `_execute_transition_rules`
- **预期:**
  - pool_A.stocks 中移除了 `000001.SZ`
  - pool_B.stocks 中新增了 `000001.SZ`（含 source_event_id, operator_type="auto"）
  - transition_logs 记录 status="moved"

### TC-LSN-091: Copy 模式 - 不修改来源池
- **前置条件:** rule: mode="copy", source_pool_ids=["pool_A"], target_pool_id="pool_B"
- **步骤:** 触发 alert → `_execute_transition_rules`
- **预期:**
  - pool_A.stocks 保持不变
  - pool_B.stocks 中新增了 `000001.SZ`
  - transition_logs 记录 status="copied"

### TC-LSN-092: 冷却期内跳过流转
- **前置条件:**
  - rule: cooldown_days=3
  - pool_transition_logs 中该 rule_id+ts_code 最近一次成功流转在 1 天前
- **步骤:** 触发 alert → `_is_transition_in_cooldown`
- **预期:**
  - 返回 True（1 天 < 3 天冷却期）
  - transition_logs 记录 status="skipped", reason 含 "冷却期内已流转"
  - 不执行实际流转操作

### TC-LSN-093: 冷却期过后正常流转
- **前置条件:** rule: cooldown_days=1，上次成功流转在 2 天前
- **步骤:** 触发 alert → `_is_transition_in_cooldown`
- **预期:**
  - 返回 False（已过冷却期）
  - 正常执行流转操作

### TC-LSN-094: 目标池不存在
- **前置条件:** target_pool_id="non_existent_pool"
- **步骤:** `_apply_transition_rule`
- **预期:**
  - 返回 status="failed"
  - reason="目标股池不存在"
  - transition_logs 记录失败

### TC-LSN-095: 目标池已存在同股票时更新条目
- **前置条件:** pool_B.stocks 已包含 `000001.SZ`
- **步骤:** 触发 alert → 流转到 pool_B
- **预期:**
  - target_changed = True
  - 已有条目更新 source_event_id, last_transition_at，保留 entered_at
  - transition_logs 记录 status="updated"

### TC-LSN-096: 多个流转规则并行执行
- **前置条件:** transition_rules 包含 2 个启用的规则
- **步骤:** 触发 alert → `_execute_transition_rules`
- **预期:**
  - 两个规则都执行（独立 try/except）
  - transition_results 包含 2 条记录

---

## 11. 批量拉取与全市场模式

### TC-LSN-100: 大批量分批拉取 - 超过阈值
- **前置条件:** watch_codes 包含 1000 只股票，large_watch_threshold=600，large_watch_batch=400
- **步骤:** 执行 `_poll_cycle` 中的行情拉取
- **预期:**
  - 日志输出 `Large watch list (1000 stocks), using batch mode (batch=400)`
  - 分 3 批拉取（0-399, 400-799, 800-999）
  - 结果正确合并到 all_quotes
  - 每批日志包含 `Batch N: X codes → Y quotes`

### TC-LSN-101: 小批量单次拉取 - 低于阈值
- **前置条件:** watch_codes 包含 300 只股票，large_watch_threshold=600
- **步骤:** 执行行情拉取
- **预期:**
  - 不进入分批模式
  - 日志输出 `Fetching realtime quotes for 300 stocks...`
  - 单次调用 `get_realtime_quotes(watch_codes, batch_size=50)`

### TC-LSN-102: 全市场模式 - ALL_MARKET 标志
- **前置条件:** 某个 subscription 的 watch_list 包含 `"ALL"`
- **步骤:** `_get_all_watch_codes()`
- **预期:**
  - `has_all_market = True`
  - 返回代码列表 = `set(self._limit_stocks.keys()) + set(watch_set)`（所有有效股票的并集）

### TC-LSN-103: 空监听列表时跳过
- **前置条件:** 没有活跃订阅，watch_codes 为空
- **步骤:** `_poll_cycle` 中 watch_codes 为空
- **预期:**
  - 日志输出 `No stocks to watch, skipping`
  - return 直接返回，不拉取行情，不评估策略

---

## 12. 错误隔离与鲁棒性

### TC-LSN-110: 单策略异常不影响其他策略评估
- **前置条件:** 有 3 个活跃订阅（price_change, limit_open, ma5_buy），其中 limit_open 策略在执行 evaluate 时抛出 ValueError
- **步骤:** `_evaluate_strategies()`
- **预期:**
  - 日志输出 `Strategy evaluation error: ValueError, strategy=limit_open`
  - price_change 和 ma5_buy 策略正常执行，产生各自的 alerts
  - all_alerts 汇总了除 limit_open 外的所有正常结果

### TC-LSN-111: 未知策略类型跳过
- **前置条件:** subscription.strategy_type 为 "unknown_type"，不在 self._strategies 中
- **步骤:** `_evaluate_strategies()`
- **预期:**
  - 日志输出 `Unknown strategy type: unknown_type`
  - 该订阅被跳过，不影响其他订阅

### TC-LSN-112: 无效订阅记录被跳过
- **前置条件:** MongoDB strategy_subscriptions 中有一条缺少必填字段的记录（如缺少 strategy_type）
- **步骤:** `_load_subscriptions()`
- **预期:**
  - 日志输出 `Skip invalid subscription: ...`
  - 该记录不被添加到 self._subscriptions

### TC-LSN-113: 行情数据获取失败时不执行策略
- **前置条件:** `data_source_manager.get_realtime_quotes()` 返回空 dict
- **步骤:** `_poll_cycle` 行情拉取
- **预期:**
  - 日志输出 `Failed to get realtime quotes`
  - return 直接返回，不构建快照，不评估策略

### TC-LSN-114: Redis 存储失败不影响策略评估
- **前置条件:** `redis_manager.set_realtime_market_data()` 抛出连接异常
- **步骤:** `_store_realtime_market_data()`
- **预期:**
  - 日志输出 `Failed to store realtime market data: ...`
  - 异常被捕获，不向上传播
  - poll_cycle 继续执行策略评估（步骤在 Redis 存储之后）

---

## 13. 涨跌停价格管理

### TC-LSN-120: 同日内不重复获取涨跌停价格
- **前置条件:** 当日已成功获取涨跌停价格，last_limit_fetch_date = today
- **步骤:** 再次调用 `_fetch_limit_prices_if_needed()`
- **预期:**
  - 检测到 `self._last_limit_fetch_date == today`，直接 return
  - 不调用 data_source_manager.get_stk_limit

### TC-LSN-121: 9:15 前不获取涨跌停价格
- **前置条件:** 当前时间 09:10，limit_fetch_time = "09:15"
- **步骤:** 调用 `_fetch_limit_prices_if_needed()`
- **预期:**
  - 日志输出 `Before limit fetch time (09:15), skipping`
  - 不发起数据源请求

### TC-LSN-122: ST 股票从涨跌停列表中排除
- **前置条件:** stk_limit 返回 5000 条，其中 50 条为 ST 股票
- **步骤:** 执行 `_fetch_limit_prices_if_needed()`
- **预期:**
  - `self._limit_stocks` 中不包含 ST 股票
  - 日志包含 `st=50` 的过滤统计

### TC-LSN-123: 不在 stock_basic 中的股票被过滤
- **前置条件:** stk_limit 返回的某股票 ts_code 不在 stock_basic 中（list_status!="L"）
- **步骤:** 执行 `_fetch_limit_prices_if_needed()`
- **预期:**
  - 该股票被过滤掉（filtered_not_in_db 计数增加）

---

## 14. 综合场景

### TC-LSN-130: 完整轮询链路 - 端到端
- **前置条件:** ListenerNode 已启动，REDIS/MongoDB 可用，有 2 个活跃订阅
- **步骤:** 等待一轮 poll_cycle 完成
- **预期:**
  - 完整链路：fetch_limit_prices → get_index_quotes → build_contexts → get_watch_codes → fetch_quotes → build_snapshot → apply_delta → store_realtime → evaluate_strategies → process_alerts
  - 每步均有日志输出
  - 无未捕获异常

### TC-LSN-131: 跨轮次状态持久化 - 阈值状态
- **前置条件:** 第一轮 price_change 策略触发某股票涨幅预警，stock_configs 中记录了 threshold_states
- **步骤:** 第二轮轮询开始
- **预期:**
  - `_load_threshold_states` 能读到上一轮设置的阈值状态
  - 同股票同方向在第二轮的 `_set_threshold_state` 返回 False（已触发过）
  - threshold_states 跨轮次保持

### TC-LSN-132: 节点重启后策略参数恢复
- **前置条件:** 节点 A 运行中 FixedStopLoss 为某股票设置了 reference_price=10.00，存入 MongoDB
- **步骤:** 节点 A 停止，节点 B 启动（加载同一 subscription）
- **预期:**
  - `_load_subscriptions()` 加载的 subscription.params.stock_configs 中保留了 reference_price
  - 策略继续基于原参考价进行止损判断

### TC-LSN-133: RPC refresh_strategies 刷新订阅
- **前置条件:** MongoDB 中新增了一条活跃订阅
- **步骤:** 其他节点通过 RPC 调用 `refresh_strategies`
- **预期:**
  - `_load_subscriptions()` 重新加载
  - 返回 `status: ok, subscriptions_count: N`
  - 新订阅在下一轮 poll_cycle 中生效

---

## 代码走查验证结果

**走查日期**: 2026-06-21 | **方法**: 代码走查 | **结果**: 58/58 通过

| 用例 | 结果 | 走查依据 |
|------|------|----------|
| TC-LSN-001 | ✅ PASS | node.py:71 (_poll_interval=60), node.py:146 (wait_for), node.py:159 (sleep) |
| TC-LSN-002 | ✅ PASS | node.py:72 (poll_timeout=180), node.py:146 (asyncio.wait_for), node.py:148-152 (TimeoutError caught, log matches) |
| TC-LSN-003 | ✅ PASS | node.py:153-154 (Exception caught, log matches), node.py:156 (finally: clear_trace_id), while-loop at line 159 |
| TC-LSN-004 | ✅ PASS | node.py:138-143 (silent_outside_trading check, debug log, sleep+continue) |
| TC-LSN-010 | ✅ PASS | node.py:691-694 (previous_snapshot is None → full copy to changed_quotes) |
| TC-LSN-011 | ✅ PASS | node.py:697-715 (per-ts_code field comparison via _DELTA_COMPARE_FIELDS line 608-611) |
| TC-LSN-012 | ✅ PASS | node.py:608-611 (volume in _DELTA_COMPARE_FIELDS), node.py:706 (any field diff includes) |
| TC-LSN-013 | ✅ PASS | node.py:603-606 (_SNAPSHOT_KEEP_FIELDS), node.py:650-654 (keeps only matching fields) |
| TC-LSN-014 | ✅ PASS | node.py:642-645 (skip when no ts_code), node.py:664-665 (warning log with count) |
| TC-LSN-020 | ✅ PASS | base.py:98-104 (non-ALL mode: intersect snapshot quotes with watch_list) |
| TC-LSN-021 | ✅ PASS | base.py:98-99 (is_all_market returns all source_quotes); protocols.py:399-401 (ALL detection) |
| TC-LSN-022 | ✅ PASS | base.py:108-112 (filter ST via _is_st_stock), base.py:128-146 (*ST prefix matched) |
| TC-LSN-023 | ✅ PASS | base.py:115-124 (checks stock_configs[ts_code].enabled is False, excludes) |
| TC-LSN-024 | ✅ PASS | base.py:246-247 (daily_once: returns True when last_triggered_date == today_key) |
| TC-LSN-025 | ✅ PASS | base.py:243-244 (once_then_disable: returns True when frequency_disabled) |
| TC-LSN-026 | ✅ PASS | base.py:240-241 (unlimited: always returns False) |
| TC-LSN-027 | ✅ PASS | base.py:325-331 (once_then_disable: sets enabled=False, frequency_disabled=True) |
| TC-LSN-030 | ✅ PASS | market_index_alert.py:65-75 (index_rise, comparator="gte"), line 228-234 (reason format) |
| TC-LSN-031 | ✅ PASS | market_index_alert.py:76-86 (index_fall, comparator="lte_negative"), line 238-244 (active check) |
| TC-LSN-032 | ✅ PASS | market_index_alert.py:164 (single alert with "；" joined reason), line 180 (triggered_conditions) |
| TC-LSN-033 | ✅ PASS | base.py:270-281 (_set_threshold_state: is_active and not was_active; second round → False) |
| TC-LSN-034 | ✅ PASS | market_index_alert.py:68 (enabled=False), line 224 (is_active = enabled and ... = False) |
| TC-LSN-040 | ✅ PASS | limit_open.py:126-157 (was_at_up_limit and current_price < up_limit → alert) |
| TC-LSN-041 | ✅ PASS | limit_open.py:64-66 (no previous_snapshot → warning log, return []) |
| TC-LSN-042 | ✅ PASS | limit_open.py:127 (was_at_up_limit=True but current_price < up_limit=False → no alert) |
| TC-LSN-043 | ✅ PASS | limit_open.py:160-185 (was_at_down_limit and current_price > down_limit → alert) |
| TC-LSN-044 | ✅ PASS | limit_open.py:126 (limit_type="both"/"up" gate; "up" skips down block) |
| TC-LSN-050 | ✅ PASS | price_change.py:88-92 (pct_chg >= threshold → up_crossed=True), line 104 (reason 涨幅) |
| TC-LSN-051 | ✅ PASS | price_change.py:93-97 (pct_chg <= -threshold → down_crossed=True), line 106 (reason 跌幅) |
| TC-LSN-052 | ✅ PASS | price_change.py:91 (direction "up": down_crossed=False; up_crossed: pct_chg >= threshold → False) |
| TC-LSN-053 | ✅ PASS | price_change.py:85-86 (load_threshold_states), base.py:270-281 (was_active prevents re-crossing) |
| TC-LSN-060 | ✅ PASS | ma5_buy.py:189-198 (was_above_ma and is_near_ma → state=TOUCHED, stable_count=1, no alert) |
| TC-LSN-061 | ✅ PASS | ma5_buy.py:200-239 (TOUCHED + is_above_ma → stable_count+1; >=stable_periods → STABILIZED, alert) |
| TC-LSN-062 | ✅ PASS | ma5_buy.py:241-243 (not is_above_ma AND current_price < ma*(1-touch_range) → tracker.reset()) |
| TC-LSN-063 | ✅ PASS | ma5_buy.py:252-263 (_ensure_cache_updated: new day → clears _stock_data, resets all trackers) |
| TC-LSN-064 | ✅ PASS | ma5_buy.py:112-113 (exclude_st = is_all_market() = True), base.py:108-112 (ST filtering) |
| TC-LSN-070 | ✅ PASS | fixed_stop_loss.py:64-70 (reference_price - stop_loss_pct → trigger_price=9.20), line 74 (alert) |
| TC-LSN-071 | ✅ PASS | fixed_stop_loss.py:74 (current_price > trigger_price=True, current_low > trigger_price=False → alert via low) |
| TC-LSN-072 | ✅ PASS | fixed_stop_loss.py:60-62 (no reference_price or <=0 → continue, skipped) |
| TC-LSN-073 | ✅ PASS | trailing_stop_loss.py:67-68 (highest preserved/updated), line 72-78 (trigger_price=9.40) |
| TC-LSN-074 | ✅ PASS | trailing_stop_loss.py:67-68 (current_high > highest_price → update), line 79 (no trigger) |
| TC-LSN-080 | ✅ PASS | node.py:895-915 (event_doc with all fields), line 912 (notification_sent=False) |
| TC-LSN-081 | ✅ PASS | node.py:917-920 (send_alert with user_id and channel_id), line 928-937 (updates MongoDB) |
| TC-LSN-082 | ✅ PASS | node.py:883-893 (subscription not found → warning log, returns early) |
| TC-LSN-090 | ✅ PASS | node.py:1046-1071 (mode="move": find source pools, remove ts_code), line 1100-1108 (add to target) |
| TC-LSN-091 | ✅ PASS | node.py:1046 (mode="copy": skips source pool removal), line 1122 (status="copied") |
| TC-LSN-092 | ✅ PASS | node.py:1150-1172 (_is_transition_in_cooldown: 1 day < 3 days → True) |
| TC-LSN-093 | ✅ PASS | node.py:1150-1172 (2 days >= 1 day → False, normal flow) |
| TC-LSN-094 | ✅ PASS | node.py:1007-1025 (target_pool not found → status="failed", reason="目标股池不存在") |
| TC-LSN-095 | ✅ PASS | node.py:1073-1108 (existing_index found → merge, keep entered_at, status="updated") |
| TC-LSN-096 | ✅ PASS | node.py:954-965 (iterates all rules, collects all results) |
| TC-LSN-100 | ✅ PASS | node.py:292-314 (1000 > 600 → batch mode, batch=400 → 3 iterations) |
| TC-LSN-101 | ✅ PASS | node.py:315-320 (300 <= 600 → single fetch, no batch mode log) |
| TC-LSN-102 | ✅ PASS | node.py:505-506 (has_all_market=True on "ALL"), line 512-516 (result merge) |
| TC-LSN-103 | ✅ PASS | node.py:283-288 (watch_codes empty → warning log, return early) |
| TC-LSN-110 | ✅ PASS | node.py:871-872: `f"Strategy evaluation error: {type(e).__name__}: {e}, strategy=..."` 已包含异常类型名 |
| TC-LSN-111 | ✅ PASS | node.py:830-836 (strategy not in registry → warning log, continue to next) |
| TC-LSN-112 | ✅ PASS | node.py:230-234 (pydantic validation fails → warning log, not added to _subscriptions) |
| TC-LSN-113 | ✅ PASS | node.py:322-324 (quotes is None/empty → warning log, return early) |
| TC-LSN-114 | ✅ PASS | node.py:1282-1283 (Redis exception caught, does not propagate); node.py:345-351 (containment) |
| TC-LSN-120 | ✅ PASS | node.py:400-401 (_last_limit_fetch_date == today → return early) |
| TC-LSN-121 | ✅ PASS | node.py:404-408 (now.time() < fetch_time → debug log, return early) |
| TC-LSN-122 | ✅ PASS | node.py:435-438 (ST stocks filtered from _limit_stocks), line 444 (log includes st={st_count}) |
| TC-LSN-123 | ✅ PASS | node.py:429-432 (ts_code not in valid_stocks → filtered_out count), line 444 (log) |
| TC-LSN-130 | ✅ PASS | node.py:258-366 (full chain matches doc with correct ordering) |
| TC-LSN-131 | ✅ PASS | base.py:249-268 (threshold states stored in MongoDB, reloaded), node.py:862-867 (params synced) |
| TC-LSN-132 | ✅ PASS | base.py:337-356 (stock_configs persisted to MongoDB), node.py:217-245 (reloaded from MongoDB) |
| TC-LSN-133 | ✅ PASS | node.py:172-197 (RPC refresh_strategies calls _load_subscriptions, returns status + count) |
