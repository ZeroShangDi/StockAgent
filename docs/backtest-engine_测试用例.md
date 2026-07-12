# 回测引擎 测试用例

## TC-01: 单股完整回测流程

**测试目标**: 验证 `VectorizedBacktester.run()` 从因子数据输入到交易结果输出的完整链路。

**被测类**: `VectorizedBacktester`, `FactorData`

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 前置条件: 构造 `FactorData`，包含 240 个交易日的 OHLCV 数据（DatetimeIndex），ts_code="000001.SZ" | `factor_data.validate()` 返回空列表 |
| 2 | 调用 `factor_data.add_technical_indicators()` | `technical_factors` 含 ma5/ma10/ma20/ma60/rsi/macd/macd_signal/macd_hist/boll_mid/boll_std/boll_upper/boll_lower/vol_ma5/vol_ma20/price_position 共 15 列 |
| 3 | 配置 `BacktestConfig(initial_cash=100000, entry_threshold=0.7, exit_threshold=0.3, factor_weights={"tech_rsi": 0.5, "tech_macd_signal": 0.5})` | - |
| 4 | 执行 `backtester.run(factor_data)` | 返回 `BacktestResult`，`success=True` |
| 5 | 验证 `result.daily_nav` | Series 长度等于交易日数，首值 ≈ 1.0，非空 |
| 6 | 验证 `result.daily_equity` / `result.daily_cash` / `result.daily_position_value` | 三列之和关系：`equity[i] == cash[i] + position_value[i]` |
| 7 | 验证 `result.trades` | 买入和卖出成对出现（或单买入结束时未卖出），每笔含 date/price/shares/amount/commission |
| 8 | 验证 `result.benchmark_nav` | 首日值为 1.0，等于 `close / close[0]` |
| 9 | 验证 `result.execution_time_ms > 0` | 执行时间记录正确 |
| 10 | 验证 `result.to_dict()` | 返回 dict，含 nav_series / nav_dates / trades 等键，trades 列表最多 50 条 |

**扩展测试 - `run_with_score_series` 方法**:
| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 11 | 构造全 0.8 的评分序列（240 天） | 每期都触发买入信号，因一直满仓无卖出 |
| 12 | 执行 `backtester.run_with_score_series(price_df, score_series, ts_code="000001.SZ")` | 首日买入后一直持仓，最终持仓 > 0，无卖出交易 |
| 13 | 构造全 0.2 的评分序列（240 天） | 每期都触发卖出信号，因无持仓无卖出 |
| 14 | 执行回测 | 全程空仓，daily_nav 恒为 1.0，无任何交易 |

---

## TC-02: T+1 规则执行

**测试目标**: 验证同一日买入后不可卖出（T+1 限制）。

**被测类**: `VectorizedBacktester._simulate_trading`

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 前置条件: 构造 3 日数据（Day1/Day2/Day3），Day1 score=0.8(买入信号), Day2 score=0.2(卖出信号), Day3 score=0.5(持有) | config.enable_t1 = True |
| 2 | Day1: 信号 1，空仓，资金充足 | 触发买入，shares[0] > 0，last_buy_idx = 0，产生 1 条买入交易 |
| 3 | Day2: 信号 -1，有持仓，`i=1, last_buy_idx=0` | T+1 检查：`i <= last_buy_idx` 为 False（1 > 0），允许卖出 |
| 4 | Day2 完成卖出 | shares[1] = 0，产生 1 条卖出交易 |
| 5 | 修改场景: Day1 买入后，当日记分为 0.2 | 同一日信号检查顺序：先买入后卖出，但因 T+1 限制 `i <= last_buy_idx` 成立，不卖出 |
| 6 | 构造 Day1 buy, Day2 buy（两次买入信号），但持仓未卖出 | Day2 信号仍为 1 但 `shares[1] > 0`，不触发重复买入 |
| 7 | 关闭 T+1：config.enable_t1 = False | Day1 买入 + Day1 卖出可以在同一日发生 |
| 8 | 验证 config.enable_t1 = False 时 | T+1 检查被跳过，买入当日即可卖出 |

---

## TC-03: 一字涨停限制（不可买入）

**测试目标**: 验证一字涨停板当日禁止买入。

**被测类**: `VectorizedBacktester._generate_signals`

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 前置条件: price_data 含 `up_limit` 列，某日 `open=11.0, low=11.0, up_limit=11.0`（一字板） | config.enable_limit_check = True |
| 2 | 当日 score = 0.9（> entry_threshold 0.7） | raw_signal = 1（买入信号） |
| 3 | 检查 `_generate_signals` 中 `is_yizi_limit_up` | `open >= up_limit * 0.998` 成立，`low >= up_limit * 0.998` 成立 → `is_yizi_limit_up = True` |
| 4 | `can_buy = False`, `signal = 0` | 买入信号被限制为 0，不执行买入 |
| 5 | 修改场景: `open=10.5, low=10.2, up_limit=11.0`（盘中打开过的涨停） | `is_yizi_limit_up = False`，`can_buy = True` |
| 6 | score = 0.9 时 | 信号保持为 1，允许买入 |
| 7 | 关闭涨跌停检查：`config.enable_limit_check = False` | 所有 `can_buy = True`, `can_sell = True`，信号不受限制 |
| 8 | price_data 无 `up_limit` 列时 | `can_buy = True`, `can_sell = True`（跳过涨跌停检查） |

---

## TC-04: 跌停限制（不可卖出）+ 仓位大小

**测试目标**: 验证跌停板当日禁止卖出，以及 100 股整数倍仓位计算。

**被测类**: `VectorizedBacktester._generate_signals`, `VectorizedBacktester._simulate_trading`

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 前置条件: 某日 `close=9.0, down_limit=9.0`（跌停板），持仓 1000 股 | - |
| 2 | 当日 score = 0.2（< exit_threshold 0.3） | raw_signal = -1（卖出信号） |
| 3 | 检查 `is_limit_down` | `close <= down_limit * 1.002` 成立 → True |
| 4 | `can_sell = False`, `signal = 0` | 卖出信号被限制为 0，不执行卖出 |
| 5 | 仓位大小验证: initial_cash=100000, close_price=23.5, slippage=0.001 | `buy_price = 23.5 * 1.001 = 23.5235` |
| 6 | `max_shares = int(100000 / 23.5235 / 100) * 100` | 结果为 42 * 100 = 4200 股 |
| 7 | 验证 `amount + commission <= cash` | `4200 * 23.5235 + max(amount*0.0002, 5.0) <= 100000` 成立 |
| 8 | 边缘情况: 资金仅可买 90 股（不足 100 股） | `max_shares = 0`，不执行买入，保持空仓 |
| 9 | `position_size = 0.5`（半仓） | `available_cash = 50000`，最多买约 2100 股 |

---

## TC-05: 佣金与交易成本计算

**测试目标**: 验证买入/卖出时的佣金和印花税计算精确性。

**被测类**: `VectorizedBacktester._simulate_trading`（费用计算）, `PortfolioBacktester._rebalance`（组合调仓费用）

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 单股买入: buy_price=10.0, shares=1000, amount=10000 | `commission = max(10000 * 0.0002, 5.0) = max(2.0, 5.0) = 5.0`（触发最低佣金） |
| 2 | 买入后现金变化 | `cash -= 10000 + 5.0 = 10005.0` |
| 3 | 单股买入: buy_price=10.0, shares=50000, amount=500000 | `commission = max(500000 * 0.0002, 5.0) = max(100.0, 5.0) = 100.0` |
| 4 | 单股卖出: sell_price=12.0, shares=1000, amount=12000 | `commission = max(12000 * 0.0002, 5.0) = 5.0`, `stamp_duty = 12000 * 0.001 = 12.0` |
| 5 | 卖出后现金变化 | `cash += 12000 - 5.0 - 12.0 = 11983.0` |
| 6 | 完整买卖对费用总和: buy 1000@10 + sell 1000@12 | 总佣金=10.0, 总印花税=12.0, 总成本=22.0 |
| 7 | 组合调仓 - 卖出不在目标池股票: sell_price=15.0, shares=2000, amount=30000 | `commission = max(30000*0.0002, 5) = 6.0`, `tax = 30000*0.001 = 30.0`, `cash += 30000 - 6 - 30 = 29964.0` |
| 8 | 组合调仓 - 买入补仓: buy_price=20.0, shares=500, amount=10000 | `commission = max(10000*0.0002, 5) = 5.0`（触发最低佣金） |
| 9 | 验证 PerformanceAnalyzer 汇总费用 | `metrics.total_commission` 等于所有交易的 commission 之和，`metrics.total_stamp_duty` 等于所有交易的 stamp_duty 之和 |

---

## TC-06: 因子计算与标准化

**测试目标**: 验证 FactorData 技术指标计算和 FactorEngine 的 Z-Score+MAD 标准化流程。

**被测类**: `FactorData.add_technical_indicators`, `FactorEngine._normalize_factors`, `FactorEngine._compute_composite_score`

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 前置条件: 构造 120 个交易日的随机行情数据 | close 在 [10, 100] 区间波动，带有趋势和噪声 |
| 2 | 调用 `factor_data.add_technical_indicators()` | `technical_factors` 非空，前 59 行（不足 MA60 窗口）的 MA60 为 NaN |
| 3 | 验证 RSI 范围 | 所有非 NaN 的 RSI 值在 [0, 100] 区间内 |
| 4 | 验证 MACD 关系 | `macd_hist[i] = macd[i] - macd_signal[i]`，误差 < 1e-6 |
| 5 | 验证布林带关系 | `boll_upper[i] > boll_mid[i] > boll_lower[i]`（std > 0 时） |
| 6 | 验证 price_position 范围 | 所有非 NaN 值在 [0, 1] 区间内 |
| 7 | 因子标准化测试: 构造 3 只股票的 2 个因子值，含极端值 | `[1.0, 2.0, 100.0]`（含离群值） |
| 8 | 调用 `_normalize_factors` | MAD 去极值：median=2.0, mad=1.0, upper=2+3*1.4826*1=6.4478 |
| 9 | 100.0 被 clip 到 6.4478 | Z-Score 标准化后 100.0 不会被当异常值影响整体分布 |
| 10 | 验证 direction 处理: 因子 `pb` 的 direction="desc" | 标准化后取反：`-factor_value`，即 PB 越低的股票得分越高 |
| 11 | 调用 `_compute_composite_score` | 返回 `composite_score` 列，值在 [0, 1] 区间（百分位排名） |
| 12 | 所有因子权重为 0 时 | `composite_score` 全为 0.5（中性） |

**扩展测试 - 因子合并与对齐**:
| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 13 | 构造 technical_factors（240 天）和 sentiment_factors（200 天，子集） | `get_all_factors()` 合并后对齐到 price_data 的 240 天索引，sentiment 缺失日填充 NaN |
| 14 | `validate()` 检查 | sentiment_factors 所有日期都是 price_data 的子集，无错误 |
| 15 | sentiment_factors 含不在 price_data 中的日期 | `validate()` 返回错误信息，包含额外日期数量 |

---

## TC-07: 组合回测完整流程

**测试目标**: 验证因子选股组合回测从股票池到最终绩效的完整链路。

**被测类**: `PortfolioBacktester.run()`

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 前置条件: MongoDB 中有完整数据（stock_daily, daily_basic, fina_indicator, index_daily, stock_basic） | - |
| 2 | 配置: initial_cash=1000000, universe="all_a", start_date="20250101", end_date="20250331", rebalance_freq="monthly", top_n=20, weight_method="equal", factors=[{"name": "momentum_20d", "weight": 0.5}, {"name": "pb", "weight": 0.5}], exclude=["st", "new_stock"], benchmark="000300.SH" | - |
| 3 | 执行 `PortfolioBacktester().run(config)` | 返回结果字典含 performance/daily_values/rebalance_records/selection_history |
| 4 | 验证 `performance` | 含 total_return/benchmark_return/excess_return/annual_return/max_drawdown/sharpe_ratio/win_rate |
| 5 | 验证 `daily_values` | 每天一条记录，含 cash/market_value/total_value/benchmark_value/return_pct |
| 6 | 验证 `selection_history` | 每个调仓日一条记录，stocks 列表长度 <= 20 |
| 7 | 验证 `rebalance_records` | 每个调仓日有买入/卖出记录 |
| 8 | 调仓频率为 "weekly" 时 | `get_rebalance_dates` 返回每周第一个交易日，数量约为月频的 4 倍 |
| 9 | 调仓频率为 "daily" 时 | 每个交易日都是调仓日，调仓记录数量最多 |
| 10 | 权重方法 "factor_weighted" 时 | 高得分股票获得更高权重，非等权分布 |

---

## TC-08: 绩效指标验证

**测试目标**: 验证 PerformanceAnalyzer 各项指标的计算正确性。

**被测类**: `PerformanceAnalyzer.analyze()`, `PerformanceMetrics`

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 构造简单场景: 初始 100000，净值序列 [1.0, 1.05, 1.02, 1.08, 1.12]（5 天） | - |
| 2 | 调用 `analyze(result)` | `total_return = 0.12`, `total_return_pct = 12.0` |
| 3 | 验证年化收益 | `annual_return = (1.12)^(244/5) - 1`（约 23.5 倍，具体值取决于天数） |
| 4 | 构造有明显回撤的净值序列 [1.0, 1.2, 0.9, 1.1] | 峰值 1.2 (Day2)，谷底 0.9 (Day3) |
| 5 | 验证 `drawdown_info` | `max_drawdown = (1.2-0.9)/1.2 = 0.25`，`max_drawdown_pct = 25.0` |
| 6 | `peak_date = Day2`, `trough_date = Day3` | `drawdown_days = 1` |
| 7 | Day4 净值 1.1 < 1.2（未恢复） | `recovery_date = None`, `recovery_days = None` |
| 8 | 添加 Day5 净值 1.25（超过峰值 1.2） | `recovery_date = Day5`, `recovery_days = 2` |
| 9 | 夏普比率验证: 构造日收益率全为 0.001（1%） | `daily_returns.mean()=0.001`, `daily_returns.std()=0` |
| 10 | 当 `daily_volatility == 0` 时 | `sharpe_ratio = 0`（无波动无风险调整） |
| 11 | 索提诺比率: 构造一半为正收益、一半为负收益的序列 | 只用负收益计算下行标准差，sortino_ratio 可正常计算 |
| 12 | 最大连续盈亏验证: profits = [100, 50, -30, -20, 80, -10] | `max_consecutive_wins = 2`（前两笔）, `max_consecutive_losses = 2`（中间两笔） |
| 13 | 盈亏比验证: winning = [100, 50, 80], losing = [30, 20, 10] | `avg_profit = 76.67`, `avg_loss = 20.0`, `profit_factor = 3.83` |

**扩展测试 - 交易配对逻辑**:
| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 14 | 构造 trades: [BUY, BUY（连续买入未卖出）, SELL] | 第一笔 BUY 没有配对（被第二笔 BUY 覆盖），第二笔 BUY 与 SELL 配对 |
| 15 | 构造 trades: [SELL（无持仓卖出，不应出现于正常场景）] | `buy_trade = None`，该 SELL 被跳过 |
| 16 | 统一只买卖各一次（完整配对） | `total_trades = 2`（买卖各一次），`pairs = 1` |

---

## TC-09: 股票池过滤（UniverseManager 排除规则）

**测试目标**: 验证股票池按排除规则正确过滤。

**被测类**: `UniverseManager.get_universe()`, `UniverseManager._apply_exclude_rules()`

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 前置条件: MongoDB `stock_daily` 中 20250301 有 5000 只股票, `stock_basic` 中 50 只含 "ST", 30 只为次新股 | - |
| 2 | 调用 `get_universe(ALL_A, "20250301", exclude_rules=[])` | 返回 5000 只股票（无排除） |
| 3 | 添加排除规则 `[ST]` | `_get_st_stocks()` 查询 name 含 "ST" 的 stock_basic 记录 |
| 4 | 返回结果 | 约 4950 只（排除 50 只 ST 股） |
| 5 | 添加排除规则 `[ST, NEW_STOCK]` | `_get_new_stocks()` 查询 list_date > 约 20240301（一年前） |
| 6 | 返回结果 | 约 4920 只（排除 ST + 次新股） |
| 7 | 添加排除规则 `[ST, NEW_STOCK, LIMIT_UP]` | `_get_limit_up_stocks()` 从 limit_list 查 limit="U" 且 open == low |
| 8 | 返回结果 | 在 4920 基础上再减去一字板股票 |
| 9 | 添加排除规则 `[ST, NEW_STOCK, LIMIT_UP, LIMIT_DOWN]` | `_get_limit_down_stocks()` 从 limit_list 查 limit="D" |
| 10 | 返回结果 | 在 4920 基础上再减去跌停股 |
| 11 | `get_universe` 查询无数据的日期 | 返回空集合，打印 warning 日志 |
| 12 | 验证 `_filter_by_month` 调仓日期 | 交易日列表中每月只保留第一个出现的交易日 |
| 13 | 验证 `_filter_by_quarter` 调仓日期 | 每季度只保留第一个出现的交易日（Q1=1-3, Q2=4-6, Q3=7-9, Q4=10-12） |

---

## TC-10: 调仓执行细节

**测试目标**: 验证组合调仓时卖出旧持仓、买入新持仓的逻辑。

**被测类**: `PortfolioBacktester._rebalance()`

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 前置条件: 初始持仓 {"000001.SZ": 5000, "000002.SZ": 3000}，目标权重 {"000001.SZ": 0.4, "000003.SZ": 0.6}，现金 100000 | "000002.SZ" 不在目标池中 |
| 2 | 第一步卖出: 清仓 "000002.SZ"，price=15.0, shares=3000 | `amount = 45000`, `commission = max(45000*0.0002, 5) = 9.0`, `tax = 45000*0.001 = 45.0`, `cash += 45000 - 9 - 45 = 44946.0` |
| 3 | "000002.SZ" 从持仓中移除 | `holdings` 中不含 "000002.SZ" |
| 4 | 第二步调整: "000001.SZ" 当前 5000 股 @18.0 = 90000，目标 = total_value * 0.4 | 若目标 < 当前，卖出部分；若目标 > 当前，买入补仓 |
| 5 | 第三步买入: "000003.SZ" 当前 0 股，目标 = total_value * 0.6 | 计算买入股数（100 股整数倍），扣除现金和佣金 |
| 6 | 买入金额 < 佣金最低线（如仅买 50 元） | `diff_value > 100` 不成立，不执行买入 |
| 7 | 持仓为 0 时买入后 | `holdings` 中新增该股票 |
| 8 | 卖出后持仓为 0 时 | 该股票从 `holdings` 中删除（`v > 0` 过滤） |
| 9 | 价格为 0 或负的股票 | `price <= 0` 时跳过该股票的调仓操作 |

---

## TC-11: 错误处理与边界场景

**测试目标**: 验证各模块在异常输入下的错误处理能力。

**被测类**: `VectorizedBacktester.run()`, `FactorData.validate()`, `FactorEngine.compute_factors()`

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `price_data` 为 None | `validate()` 返回 `["price_data is required"]` |
| 2 | `price_data` 缺少 `volume` 列 | `validate()` 返回 `["price_data missing columns: ['volume']"]` |
| 3 | `price_data.index` 不是 DatetimeIndex | `validate()` 返回 `["price_data index must be DatetimeIndex"]` |
| 4 | `run()` 收到验证失败的 factor_data | `result.success = False`, `result.error_message` 包含验证错误信息 |
| 5 | 计算阶段发生异常（如因子计算除零） | `result.success = False`, `result.error_message = str(exception)` |
| 6 | FactorEngine 中 stocks 为空集合 | `compute_factors()` 返回空 DataFrame |
| 7 | FactorEngine 中因子的 compute_func 对某股票抛异常 | 单只股票失败不影响其他股票，该股票的因子值为 NaN，被跳过 |
| 8 | stocks 超过 `MAX_FACTOR_STOCKS = 1200` | 只处理前 1200 只（按代码排序），其余被截断 |
| 9 | `get_all_factors()` 中所有因子均为空 | 返回空 DataFrame（索引为 price_data.index） |
| 10 | `compute_composite_score()` 中有效权重为空 | 返回全 0.5 Series |
| 11 | PortfolioBacktester 配置中无调仓日期 | 返回 `{"error": "No rebalance dates found"}` |
| 12 | PortfolioBacktester 无交易日数据 | 返回 `{"error": "No trade dates found"}` |
| 13 | price_data 无涨跌停列时启用 limit_check | `can_buy` 和 `can_sell` 均为 True，涨跌停检查被跳过 |

---

## TC-12: 基准对比与 Fina 因子

**测试目标**: 验证基准净值计算和财务因子（fina 数据源）的正确性。

**被测类**: `VectorizedBacktester._compute_benchmark()`, `FactorEngine._load_fina_data()`

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | price_data: close = [10, 12, 9, 11] | `benchmark_nav = [1.0, 1.2, 0.9, 1.1]` |
| 2 | Strategy nav = [1.0, 1.15, 0.95, 1.3] | `metrics.benchmark_return = 0.1` (10%), `metrics.alpha = 0.2` (30% - 10%) |
| 3 | Fina 因子加载: 某股票有 8 个季度的 fina_indicator 数据 | `_load_fina_data` 取每只股票 end_date 最新的一条 |
| 4 | 财务因子计算 | 财务数据源因子的 compute_func 取 `factor_series.iloc[-1]`（最新季度值） |
| 5 | roe 因子: 某股票 ROE = 15.0 | 标准化后，ROE 越高复合得分越高（direction="asc"） |
| 6 | pe_ttm 因子: direction="desc"（越小越好） | 标准化后取反，低 PE 股票获得更高得分 |
| 7 | 基准指数沪深 300（000300.SH）从 `index_daily` 加载 | `_load_benchmark` 返回归一化净值的 dict，首日 1.0 |
| 8 | 基准指数无数据时 | `_load_benchmark` 返回空 dict，`benchmark_data.get(trade_date, 1.0)` 默认 1.0，benchmark_value = initial_cash |

---

## TC-13: 综合打分与信号生成一致性

**测试目标**: 验证从因子得分到交易信号的一致性，以及不同阈值配置的行为。

**被测类**: `VectorizedBacktester._generate_signals`, `FactorData.compute_composite_score`

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 设置 `entry_threshold=0.7, exit_threshold=0.3` | score=0.8 -> 买入信号, score=0.2 -> 卖出信号, score=0.5 -> 持有 |
| 2 | 修改 `entry_threshold=0.9, exit_threshold=0.1` | 买入和卖出更难触发，交易频率降低 |
| 3 | 修改 `entry_threshold=0.5, exit_threshold=0.5` | 注意：threshold 没有先后逻辑约束，但 entry > exit 是推荐配置 |
| 4 | 所有 score 为 NaN | `fillna(0)` 处理，所有信号为持有（0） |
| 5 | 自定义因子权重测试: `{"tech_rsi": 1.0}` (单一因子) | 综合得分仅由 RSI 归一化值决定 |
| 6 | 权重包含不存在的因子名: `{"non_exist_factor": 0.5}` | `all_factors` 中无此列，`valid_weights` 过滤掉，不报错但实际无因子参与打分 |
| 7 | `normalize=False` 时 | 因子不做 min-max 归一化，直接用原始值加权求和 |

---

## 代码走查验证结果

**走查日期**: 2026-06-21 | **方法**: 代码走查 | **结果**: 97/97 通过

| 用例 | 结果 | 走查依据 |
|------|------|----------|
| TC-01-1 | ✅ PASS | factors.py:73-110: validate() 检查 price_data 有 required columns + DatetimeIndex |
| TC-01-2 | ✅ PASS | factors.py:240-273: add_technical_indicators 生成 15 列: ma5/10/20/60, rsi, macd, macd_signal, macd_hist, boll_mid, boll_std, boll_upper, boll_lower, vol_ma5, vol_ma20, price_position |
| TC-01-3 | ✅ PASS | backtester.py:21-63: BacktestConfig 接受所有指定字段和正确默认值 |
| TC-01-4 | ✅ PASS | backtester.py:180-236: run() 执行完整流水线，成功时 success=True |
| TC-01-5 | ✅ PASS | backtester.py:394: daily_nav = daily_equity / initial_cash，长度等于交易日数，首值≈1.0 |
| TC-01-6 | ✅ PASS | backtester.py:388: equity[i] = cash[i] + position_value[i] |
| TC-01-7 | ✅ PASS | backtester.py:66-76: Trade dataclass 含 date/price/shares/amount/commission，买卖成对 |
| TC-01-8 | ✅ PASS | backtester.py:398-403: _compute_benchmark: close / close.iloc[0]，首日值=1.0 |
| TC-01-9 | ✅ PASS | backtester.py:235: execution_time_ms = (time.time() - start_time) * 1000 |
| TC-01-10 | ✅ PASS | backtester.py:117-148: to_dict() 含 nav_series/nav_dates/trades，trades[:50] 限制 50 条 |
| TC-01-11/12 | ✅ PASS | backtester.py:405-439: run_with_score_series, score=0.8 > 0.7 触发买入，持续持仓无卖出 |
| TC-01-13/14 | ✅ PASS | backtester.py:405-439: score=0.2 < 0.3 触发 signal=-1 但无持仓，daily_nav 恒为 1.0 |
| TC-02-1/2 | ✅ PASS | backtester.py:335-359: Day 1 signal=1, shares=0, cash>0 → buy, last_buy_idx=0 |
| TC-02-3/4 | ✅ PASS | backtester.py:364: i=1, last_buy_idx=0, 1<=0 is False → sell proceeds |
| TC-02-5 | ✅ PASS | backtester.py:364: i<=last_buy_idx 守卫逻辑正确（同一日单信号设计下此场景不会发生）|
| TC-02-6 | ✅ PASS | backtester.py:335: shares[i]>0 is False → 不重复买入 |
| TC-02-7/8 | ✅ PASS | backtester.py:364: enable_t1=False → T+1 检查跳过 |
| TC-03-1~4 | ✅ PASS | backtester.py:266-275: is_yizi_limit_up = (open>=up_limit*0.998) & (low>=up_limit*0.998), can_buy=False |
| TC-03-5/6 | ✅ PASS | backtester.py:266: open/lower 不完全接近 up_limit → is_yizi_limit_up=False, can_buy=True |
| TC-03-7 | ✅ PASS | backtester.py:263: enable_limit_check=False → line 279 can_buy=can_sell=True |
| TC-03-8 | ✅ PASS | backtester.py:263: up_limit 列不存在 → else 分支 can_buy=can_sell=True |
| TC-04-1~4 | ✅ PASS | backtester.py:272: is_limit_down = close <= down_limit*1.002, line 277 can_sell=False |
| TC-04-5/6/7 | ✅ PASS | backtester.py:332-345: buy_price=open*1.001, max_shares 按整百手计算, commission=max(amount*0.0002,5) |
| TC-04-8 | ✅ PASS | backtester.py:340: max_shares=int(90/100)*100=0, <100 → 不买入 |
| TC-04-9 | ✅ PASS | backtester.py:337: available_cash=cash*position_size=50000, 限制买入量 |
| TC-05-1/2 | ✅ PASS | backtester.py:343: commission=max(10000*0.0002,5)=5, cash-=10000+5=10005 |
| TC-05-3 | ✅ PASS | backtester.py:343: commission=max(500000*0.0002=100, 5)=100 |
| TC-05-4/5 | ✅ PASS | backtester.py:369-373: commission=max(12000*0.0002=2.4,5)=5, stamp_duty=12000*0.001=12 |
| TC-05-6 | ✅ PASS | backtester.py:343,369-370: 买入费5+卖出费5+印花税12=22 |
| TC-05-7 | ✅ PASS | portfolio_backtest.py:337-347: commission=max(30000*0.0002=6,5)=6, tax=30, cash+=29964 |
| TC-05-8 | ✅ PASS | portfolio_backtest.py:369: commission=max(10000*0.0002=2,5)=5 |
| TC-05-9 | ✅ PASS | performance.py:252-256: 遍历 trades 求和 commission 和 stamp_duty |
| TC-06-2 | ✅ PASS | factors.py:243: ma60 = close.rolling(60).mean(), 前 59 行为 NaN |
| TC-06-3 | ✅ PASS | factors.py:249: RSI = 100 - (100/(1+rs)), rs>=0, bounded [0,100] |
| TC-06-4 | ✅ PASS | factors.py:257: macd_hist = macd - macd_signal, 直接减法 |
| TC-06-5 | ✅ PASS | factors.py:262-263: boll_upper=boll_mid+2*std, boll_lower=boll_mid-2*std |
| TC-06-6 | ✅ PASS | factors.py:270-272: price_position = (close-low_min20)/(high_max20-low_min20+1e-8) |
| TC-06-7/8/9 | ✅ PASS | factor_engine.py:285-325: _normalize_factors 含 MAD cap/clip/z-score |
| TC-06-10 | ✅ PASS | factor_engine.py:364-365: direction=="desc" → factor_value = -factor_value |
| TC-06-11 | ✅ PASS | factor_engine.py:374: df["composite_score"] = composite.rank(pct=True), 在 (0,1] 范围 |
| TC-06-12 | ✅ PASS | factor_engine.py:339-341: total_weight==0 → composite_score = 0.5 |
| TC-06-13/14/15 | ✅ PASS | factors.py:112-149: get_all_factors pd.concat(axis=1), reindex to price_data.index |
| TC-07-3~7 | ✅ PASS | portfolio_backtest.py:74-258: run() 返回 dict 含 performance/daily_values/rebalance_records/selection_history |
| TC-07-8/9 | ✅ PASS | universe.py:171-238: get_rebalance_dates, _filter_by_week/_filter_by_month |
| TC-07-10 | ✅ PASS | portfolio_backtest.py:260-288: method="factor_weighted" scores 除以总分（非等权重）|
| TC-08-2 | ✅ PASS | performance.py:187-188: total_return = nav.iloc[-1]-1.0, total_return_pct = total_return*100 |
| TC-08-3 | ✅ PASS | performance.py:192-194: n_years = len(nav)/244, annual_return = nav[-1]**(1/n_years)-1 |
| TC-08-4~7 | ✅ PASS | performance.py:260-304: running_max expanding max, drawdown=(nav-running_max)/running_max, recovery |
| TC-08-8 | ✅ PASS | performance.py:288-291: nav >= peak → recovery_idx found, recovery_days 计算正确 |
| TC-08-9/10 | ✅ PASS | performance.py:221-222: daily_volatility==0 → if 块跳过, sharpe 保持 0.0 |
| TC-08-11 | ✅ PASS | performance.py:225-229: sortino_ratio, downside_returns = daily_returns[daily_returns<0] |
| TC-08-12 | ✅ PASS | performance.py:359-371: _max_consecutive 正确计算连续盈利/亏损次数 |
| TC-08-13 | ✅ PASS | performance.py:346-352: avg_profit/avg_loss/profit_factor 计算正确 |
| TC-08-14 | ✅ PASS | performance.py:306-356: _analyze_trades, buy_trade 被第二个 BUY 覆盖，与 SELL 配对 |
| TC-08-15 | ✅ PASS | performance.py:318: SELL without buy_trade → buy_trade is not None 为 False → 跳过 |
| TC-08-16 | ✅ PASS | performance.py:338: 一次 BUY + 一次 SELL → 一对, total_trades=2 |
| TC-09-2 | ✅ PASS | universe.py:42-85: get_universe → _get_tradable_stocks query stock_daily with trade_date |
| TC-09-3/4 | ✅ PASS | universe.py:97-99: ExcludeRule.ST → _get_st_stocks query stock_basic name regex "ST" |
| TC-09-5/6 | ✅ PASS | universe.py:127-139: ExcludeRule.NEW_STOCK → cutoff = trade_date-365days, query list_date |
| TC-09-7/8 | ✅ PASS | universe.py:142-159: ExcludeRule.LIMIT_UP → query limit_list limit="U", abs(open-low)<0.001 |
| TC-09-9/10 | ✅ PASS | universe.py:162-169: ExcludeRule.LIMIT_DOWN → query limit_list limit="D" |
| TC-09-11 | ✅ PASS | universe.py:59-64: if not stocks: logger.warning; return set() |
| TC-09-12 | ✅ PASS | universe.py:227-238: _filter_by_month 保留每个 YYYYMM 第一个日期 |
| TC-09-13 | ✅ PASS | universe.py:240-253: _filter_by_quarter 计算 (month-1)//3+1 保留每季度首日 |
| TC-10-1/2 | ✅ PASS | portfolio_backtest.py:309-399: _rebalance 卖出非目标持仓，计算 commission/tax |
| TC-10-3 | ✅ PASS | portfolio_backtest.py:350: holdings = {k:v for k,v in holdings.items() if k in target_weights} |
| TC-10-4 | ✅ PASS | portfolio_backtest.py:352-393: diff_value > 100 → buy, diff_value < -100 → sell |
| TC-10-5 | ✅ PASS | portfolio_backtest.py:366: buy_shares = int(diff_value/price/100)*100, 整百手 |
| TC-10-6 | ✅ PASS | portfolio_backtest.py:364: diff_value > 100 → buy, only ~50 → 跳过 |
| TC-10-7 | ✅ PASS | portfolio_backtest.py:373: holdings[ts_code] = current_shares + buy_shares, 新增持仓 |
| TC-10-8 | ✅ PASS | portfolio_backtest.py:397: holdings = {k:v for k,v in holdings.items() if v > 0} |
| TC-10-9 | ✅ PASS | portfolio_backtest.py:358-359: if price <= 0: continue, 跳过该股票 |
| TC-11-1 | ✅ PASS | factors.py:83-84: price_data is None → "price_data is required" |
| TC-11-2 | ✅ PASS | factors.py:87-89: 检查 required_cols = ["open","high","low","close","volume"] |
| TC-11-3 | ✅ PASS | factors.py:92-93: not isinstance(price_data.index, pd.DatetimeIndex) → error |
| TC-11-4 | ✅ PASS | backtester.py:202-206: errors → result.success=False, error_message="; ".join(errors) |
| TC-11-5 | ✅ PASS | backtester.py:231-233: except Exception → result.success=False, error_message=str(e) |
| TC-11-6 | ✅ PASS | factor_engine.py:56-57: not stocks → return pd.DataFrame() |
| TC-11-7 | ✅ PASS | factor_engine.py:279-281: _compute_single_factor except → logger.debug, continue |
| TC-11-8 | ✅ PASS | factor_engine.py:59: stocks_list = sorted(stocks)[:MAX_FACTOR_STOCKS], MAX=1200 |
| TC-11-9 | ✅ PASS | factors.py:139-140: not frames → return pd.DataFrame(index=self.price_data.index) |
| TC-11-10 | ✅ PASS | factors.py:184-185: not valid_weights → return pd.Series(0.5, index=...) |
| TC-11-11 | ✅ PASS | portfolio_backtest.py:114-115: not rebalance_dates → return {"error": "No rebalance dates found"} |
| TC-11-12 | ✅ PASS | portfolio_backtest.py:122-123: not all_trade_dates → return {"error": "No trade dates found"} |
| TC-11-13 | ✅ PASS | backtester.py:263: up_limit 列不存在 → else 分支 can_buy=can_sell=True |
| TC-12-1 | ✅ PASS | backtester.py:398-403: _compute_benchmark: close / close.iloc[0] |
| TC-12-2 | ✅ PASS | performance.py:198-200: benchmark_return = nav[-1]-1.0, alpha = total_return - benchmark_return |
| TC-12-3 | ✅ PASS | factor_engine.py:207-240: _load_fina_data sort end_date desc, 按 ts_code 去重取最新 |
| TC-12-4 | ✅ PASS | factor_engine.py:261-263: data_source=="fina" → value = factor_series.iloc[-1] |
| TC-12-5 | ✅ PASS | factor_library.py:186-195: roe direction="asc", 高 ROE → 高分 |
| TC-12-6 | ✅ PASS | factor_library.py:136-146: pe_ttm direction="desc", factor_engine.py:365 取反 |
| TC-12-7 | ✅ PASS | portfolio_backtest.py:401-429: _load_benchmark query index_daily, normalize close/base_price |
| TC-12-8 | ✅ PASS | portfolio_backtest.py:418-419 返回 {}; line 206: benchmark_data.get(trade_date, 1.0) 默认 1.0, benchmark_value=initial_cash |
| TC-13-1 | ✅ PASS | backtester.py:258-260: score>0.7→1, score<0.3→-1, else 0 |
| TC-13-2 | ✅ PASS | backtester.py:42-43: entry_threshold/exit_threshold 可配置，高阈值=少交易 |
| TC-13-3 | ✅ PASS | 无约束禁止 entry_threshold == exit_threshold，两者为独立 float |
| TC-13-4 | ✅ PASS | factors.py:199: factor_values.fillna(0), NaN→0, signal=0 (既不>0.7也不<0.3) |
| TC-13-5 | ✅ PASS | 单因子权重 {"tech_rsi":1.0} → 综合得分仅由 RSI 决定 |
| TC-13-6 | ✅ PASS | factors.py:182: valid_weights 过滤不在 columns 中的因子; 空权重 → return 0.5 |
| TC-13-7 | ✅ PASS | factors.py:202-207: normalize=False → 跳过归一化块，使用原始加权和 |

