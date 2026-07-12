# 回测引擎 功能说明

## 概述

回测引擎模块提供完整的 A 股量化策略回测能力，包括单股票向量化回测、全市场因子选股组合回测以及绩效评估分析。核心特性包括：A 股 T+1 交易规则、涨跌停限制、佣金与印花税精确计算、18 种内置因子以及多层标准化打分。

---

## 1. VectorizedBacktester（向量化回测引擎）

- **文件路径**: `nodes/backtest_engine/backtester.py`
- **类名**: `VectorizedBacktester`
- **用途**: 对单只股票执行向量化回测，使用 Pandas/NumPy 全流程向量化计算。
- **配置类**: `BacktestConfig`
  - **资金配置**: `initial_cash`（默认 100000）, `position_size`（仓位比例，默认 1.0，满仓）, `max_position_pct`（最大仓位比例，默认 1.0）
  - **信号阈值**: `entry_threshold`（买入阈值 0.7，综合得分 > 此值买入）, `exit_threshold`（卖出阈值 0.3，综合得分 < 此值卖出）
  - **费用配置**: `commission_rate`（万2 佣金，默认 0.0002）, `stamp_duty_rate`（千1 印花税仅卖出，默认 0.001）, `min_commission`（最低 5 元，默认 5.0）
  - **滑点**: `slippage`（0.1%，默认 0.001）
  - **A 股规则开关**: `enable_t1`（T+1 限制，默认 True）, `enable_limit_check`（涨跌停检查，默认 True）
  - **因子权重**: `factor_weights`（Dict[str, float]，如 `{"tech_rsi": 0.5, "tech_macd_signal": 0.5}`）
- **执行流程 （`run` 方法）**:
  1. 验证数据完整性 （`factor_data.validate()`）
  2. 计算综合因子得分 （`compute_composite_score`），归一化到 [0, 1]
  3. 生成交易信号 （`_generate_signals`）：score > entry_threshold 产生买入信号（1），score < exit_threshold 产生卖出信号（-1），其他为持有（0）
  4. 模拟交易 （`_simulate_trading`）：逐日遍历，处理买入/卖出逻辑
  5. 计算基准收益（首日买入持有）
- **信号生成规则**:
  - 基础信号：raw_signal = 1（买入）, -1（卖出）, 0（持有）
  - 一字涨停检查：`open >= up_limit * 0.998 AND low >= up_limit * 0.998` 判定为一字板，禁止买入（can_buy = False）
  - 跌停检查：`close <= down_limit * 1.002` 判定为跌停，禁止卖出（can_sell = False）
  - 普通涨停（盘中打开过）可以排队买入，不受限制
- **交易模拟规则**:
  - 买入价 = `open_price * (1 + slippage)`，卖出价 = `open_price * (1 - slippage)`
  - 以 100 股为整数倍计算可买股数 （`int(available_cash / buy_price / 100) * 100`）
  - 买入需满足：信号 = 1、无持仓、资金足够（含佣金）
  - T+1 规则：`last_buy_idx` 追踪最近一次买入日，`i <= last_buy_idx` 时禁止卖出
  - 卖出后更新现金：`cash += amount - commission - stamp_duty`
- **辅助方法**:
  - `run_with_score_series()`: 直接使用外部评分序列运行回测，无需构建完整 `FactorData`
- **返回结果**: `BacktestResult` 数据类
  - `daily_nav`（每日净值，归一化到 1.0）, `daily_equity`（每日总资产）, `daily_cash`（每日现金）, `daily_position_value`（每日持仓市值）
  - `trades`（交易记录列表，每笔包含 date/price/shares/amount/commission/stamp_duty）
  - `signal_series`（原始信号）, `position_series`（持仓股数序列）
  - `benchmark_nav`（基准净值，买入持有策略）
  - `success` / `error_message` / `execution_time_ms`
  - `to_dict()` 方法支持序列化输出

---

## 2. FactorData（因子数据系统）

- **文件路径**: `nodes/backtest_engine/factors.py`
- **类名**: `FactorData`
- **用途**: 标准化因子数据容器，统一管理多类型因子输入。
- **基础属性**: `ts_code`（股票代码）, `start_date`/`end_date`（YYYYMMDD 格式）, `stock_name`, `industry`
- **必需数据**: `price_data`（DataFrame，必须含 open/high/low/close/volume 列，可选 up_limit/down_limit，索引为 DatetimeIndex）
- **可选因子数据**（每类均为 DataFrame，索引为日期）:
  - `technical_factors`（技术因子，自动添加前缀 `tech_`）
  - `sentiment_factors`（情绪因子，自动添加前缀 `sent_`）
  - `fundamental_factors`（基本面因子，自动添加前缀 `fund_`）
  - `custom_factors`（自定义因子字典，自动添加前缀 `custom_{name}_`）
- **数据验证 （`validate`）**:
  - 检查 `price_data` 是否为空
  - 检查必需列（open, high, low, close, volume）是否存在
  - 检查 price_data 索引是否为 DatetimeIndex
  - 检查各因子数据的日期是否都是 price_data 日期的子集（对齐检查）
- **因子合并 （`get_all_factors`）**: 将所有因子 DataFrame 按前缀合并后对齐到 price_data 的日期索引
- **综合评分 （`compute_composite_score`）**:
  - 输入：因子权重字典（key 为带前缀的因子名，value 为权重）
  - 对每个因子单独做 min-max 归一化到 [0, 1]
  - 按权重加权求和后，再做一次 min-max 归一化
  - 无因子数据时返回全 0.5（中性得分）
- **技术指标自动计算 （`add_technical_indicators`）**:
  - MA5, MA10, MA20, MA60（简单移动平均）
  - RSI（14 日相对强弱指标）
  - MACD（12, 26, 9），含 MACD 线、信号线、柱状线
  - 布林带（20 日均线，2 倍标准差），含上轨/中轨/下轨
  - 成交量均线：vol_ma5, vol_ma20
  - 价格位置（0-1）：当前收盘价在 20 日高低点区间中的相对位置
- **扩展接口**: `CustomFactorInterface`（ABC 抽象类），支持 LLM 动态因子、外部数据源因子等自定义扩展

---

## 3. PerformanceAnalyzer（绩效分析器）

- **文件路径**: `nodes/backtest_engine/performance.py`
- **类名**: `PerformanceAnalyzer`
- **用途**: 对回测结果进行全面绩效评估，输出标准风险收益指标。
- **配置**: `risk_free_rate`（年化无风险利率，默认 3%）, `TRADING_DAYS_PER_YEAR = 244`
- **核心方法**:
  - `analyze(result)` 输入 `BacktestResult`，返回 `PerformanceMetrics`
  - `generate_report(result, metrics)` 生成完整报告字典，包含净值曲线、回撤序列、交易清单等前端渲染数据
- **收益指标**:
  - `total_return` / `total_return_pct`（总收益率）
  - `annual_return` / `annual_return_pct`（年化收益率，按 244 天/年计算）
  - `benchmark_return`（基准收益率）, `alpha`（超额收益 = 策略收益 - 基准收益）
- **风险指标**:
  - `volatility`（年化波动率，`daily_returns.std() * sqrt(244)`）, `daily_volatility`（日波动率）
  - `max_drawdown` / `max_drawdown_pct`（最大回撤比例/百分比）
  - `drawdown_info`（`DrawdownInfo` 数据类：peak_date/trough_date/recovery_date/drawdown_days/recovery_days）
- **风险调整收益**:
  - `sharpe_ratio`（夏普比率）：`(超额日均收益均值 / 超额日均收益标准差) * sqrt(244)`
  - `sortino_ratio`（索提诺比率）：仅考虑下行波动（负收益日），`(日均收益 - 日无风险利率) / 下行标准差 * sqrt(244)`
  - `calmar_ratio`（卡玛比率）：`年化收益率 / 最大回撤`
- **交易统计**:
  - 买卖配对（按顺序匹配 buy->sell），计算每对盈亏（含费用）
  - `win_rate`（胜率）, `profit_factor`（盈亏比 = avg_profit / avg_loss）
  - `max_consecutive_wins` / `max_consecutive_losses`（最大连续盈/亏次数）
  - `total_commission`, `total_stamp_duty`, `total_costs`
- **持仓统计**: `total_days`, `days_in_market`, `market_exposure`（持仓天数占比）, `avg_holding_days`
- **最大回撤计算 （`_calculate_max_drawdown`）**:
  1. 计算历史最高点序列 `running_max = nav.expanding().max()`
  2. 回撤序列 = `(nav - running_max) / running_max`
  3. 找出最大回撤点 `max_dd_idx = drawdown.idxmin()`，峰值点 `peak_idx = nav[:max_dd_idx].idxmax()`
  4. 检查恢复日期：谷底之后首次重回峰值水平的日期
- **交易分析 （`_analyze_trades`）**:
  - 配对算法：按交易顺序匹配买入和卖出，形成盈亏对
  - 盈亏计算：`profit = (卖出价 - 买入价) * 股数 - 双方佣金 - 印花税`

---

## 4. FactorLibrary（因子库）

- **文件路径**: `nodes/backtest_engine/factor_selection/factor_library.py`
- **类名**: `FactorLibrary`（类级别注册表模式）, `FactorDefinition`（因子定义数据类）
- **用途**: 管理 18 个内置选股因子，支持扩展自定义因子。
- **因子定义属性**: `name`（唯一标识）, `display_name`（显示名称）, `category`（分类枚举）, `description`, `direction`（"asc" 越大越好 / "desc" 越小越好）, `data_source`（数据来源：daily/daily_basic/fina）, `required_fields`, `compute_func`（计算 lambda）, `lookback_days`
- **注册方法**: `FactorLibrary.register(factor_def)` 类方法注册因子
- **18 个内置因子**（按分类）:

| 分类 | 因子名 | 方向 | 说明 | 数据源 |
|------|--------|------|------|--------|
| 动量 | momentum_5d | asc | 5 日收益率 | daily |
| 动量 | momentum_20d | asc | 20 日收益率 | daily |
| 动量 | momentum_60d | asc | 60 日收益率 | daily |
| 价值 | pe_ttm | desc | 滚动市盈率，越低越好 | daily_basic |
| 价值 | pb | desc | 市净率，越低越好 | daily_basic |
| 价值 | ps_ttm | desc | 滚动市销率，越低越好 | daily_basic |
| 价值 | dv_ttm | asc | 滚动股息率，越高越好 | daily_basic |
| 质量 | roe | asc | 净资产收益率 | fina |
| 质量 | roa | asc | 总资产收益率 | fina |
| 质量 | gross_margin | asc | 毛利率 | fina |
| 成长 | revenue_growth | asc | 营收同比增长率 | fina |
| 成长 | profit_growth | asc | 净利润同比增长率 | fina |
| 波动 | volatility_20d | desc | 20 日波动率，低波动优先 | daily |
| 波动 | volatility_60d | desc | 60 日波动率，低波动优先 | daily |
| 流动性 | turnover_20d | asc | 20 日平均换手率 | daily_basic |
| 流动性 | amount_20d | asc | 20 日平均成交额（亿元） | daily |
| 流动性 | total_mv | asc | 总市值（亿元） | daily_basic |
| 技术 | ma_deviation_20 | desc | 股价与 20 日均线偏离度 | daily |
| 技术 | rsi_14 | asc | 14 日 RSI | daily |
| 技术 | price_position | desc | 价格在 60 日高低点区间位置 | daily |

- **辅助函数**:
  - `_safe_divide(a, b)`: 安全除法，除零返回 NaN
  - `_compute_rsi(close, period=14)`: 通用 RSI 计算函数

---

## 5. FactorEngine（因子计算引擎）

- **文件路径**: `nodes/backtest_engine/factor_selection/factor_engine.py`
- **类名**: `FactorEngine`
- **用途**: 批量计算全市场股票的因子值，支持多数据源整合、因子标准化、综合打分和选股。
- **容量限制**:
  - `MAX_FACTOR_STOCKS = 1200`（单次最大计算股票数）
  - `MAX_FACTOR_LOOKBACK_DAYS = 120`（最大回溯天数）
  - `MAX_FACTOR_QUERY_ROWS = 300000`（单次查询最大行数）
- **核心方法 `compute_factors(stocks, trade_date, factor_configs, lookback_days)`**:
  1. 收集所需因子定义，从 `FactorLibrary` 查询
  2. 按数据源分组加载数据（daily, daily_basic, fina），从 MongoDB 批量拉取
  3. 逐股票计算因子值：（日线数据按指定 trade_date 取值，财务数据取最新值）
  4. 组装为 DataFrame（columns = ts_code + 各因子列）
  5. 标准化（`_normalize_factors`）+ 综合打分（`_compute_composite_score`）
- **因子标准化 （Z-Score + MAD 去极值）**:
  1. MAD 去极值：`upper = median + 3 * 1.4826 * mad`，`lower = median - 3 * 1.4826 * mad`，clip 到区间内
  2. Z-Score 标准化：`(value - mean) / std`
- **综合打分**:
  - 按权重加权求和，`direction="desc"` 的因子取反
  - 得分转换为百分位排名（`rank(pct=True)`），结果在 [0, 1] 区间
- **选股方法 `select_top_stocks(factor_df, top_n)`**: 按 composite_score 降序选 Top N，过滤 NaN
- **数据加载**:
  - `_load_daily_data`: 从 `stock_daily` 集合按股票批量查询日线数据
  - `_load_daily_basic_data`: 从 `daily_basic` 集合加载估值指标（PE/PB/PS/换手率/市值等）
  - `_load_fina_data`: 从 `fina_indicator` 集合加载最新财务数据（ROE/ROA/利润率等）

---

## 6. UniverseManager（股票池管理器）

- **文件路径**: `nodes/backtest_engine/factor_selection/universe.py`
- **类名**: `UniverseManager`
- **用途**: 管理回测的股票池范围，应用排除规则，生成调仓日期列表。
- **股票池类型**: `UniverseType.ALL_A`（全 A 股，当前唯一类型）
- **排除规则 （`ExcludeRule`）**:
  - `ST`：排除名称含 "ST" 的股票（从 `stock_basic` 查询）
  - `NEW_STOCK`：排除上市不满约 250 个交易日的次新股（从 `stock_basic` 按 `list_date` 过滤）
  - `LIMIT_UP`：排除涨停股（从 `limit_list` 查 `limit="U"` 且 open == low 的一字板）
  - `LIMIT_DOWN`：排除跌停股（从 `limit_list` 查 `limit="D"`）
- **核心方法 `get_universe(universe_type, trade_date, exclude_rules)`**:
  1. `_get_tradable_stocks(trade_date)`：从 `stock_daily` 查询当日有数据的所有股票，上限 `MAX_UNIVERSE_STOCKS = 6000`
  2. `_apply_exclude_rules`：逐个应用排除规则，返回排除集并从基础池中移除
- **调仓日期生成 （`get_rebalance_dates`）**:
  - 从 `data_source_manager.get_trade_calendar` 获取交易日历
  - 按频率筛选：
    - `daily`：全部交易日
    - `weekly`：每周第一个交易日（按 ISO 周）
    - `monthly`：每月第一个交易日（按 YYYYMM 前缀）
    - `quarterly`：每季度第一个交易日（按 Q1-Q4 分组）
- **辅助方法**: `get_all_trade_dates(start_date, end_date)` 获取区间内所有交易日

---

## 7. PortfolioBacktester（组合回测引擎）

- **文件路径**: `nodes/backtest_engine/factor_selection/portfolio_backtest.py`
- **类名**: `PortfolioBacktester`
- **用途**: 对全市场股票执行多因子选股组合回测，支持定期调仓、多种权重方法、A 股交易成本计算。
- **交易成本配置**: `BUY_COMMISSION`（万2）, `SELL_COMMISSION`（万2）, `STAMP_TAX`（千1 仅卖出）, `MIN_COMMISSION`（最低 5 元）
- **执行流程 （`run(config)`）**:
  1. 解析排除规则和调仓日期列表
  2. 获取所有交易日列表
  3. 加载基准指数数据（默认沪深 300，归一化到首日 1.0）
  4. 逐日遍历所有交易日：
     - 若当日是调仓日：获取股票池 -> 计算因子 -> 选 Top N -> 计算目标权重 -> 执行调仓
     - 计算当日组合市值（持仓股数 * 收盘价 + 现金）
     - 记录每日资产和基准净值
  5. 计算最终绩效指标
- **调仓执行 （`_rebalance`）**:
  1. 卖出不在目标池的股票（收取佣金 + 印花税）
  2. 调整持仓到目标权重：
     - 差值 > 100 元时买入（100 股整数倍），需满足 `cash >= buy_amount + commission`
     - 差值 < -100 元时卖出（100 股整数倍），卖出后的现金回到账户
  3. 清理零股持仓
- **权重方法**:
  - `equal`：等权重（1/N）
  - `factor_weighted`：按 composite_score 比例分配权重
- **绩效计算 （`_compute_performance`）**:
  - `total_return`（总收益率百分比）, `benchmark_return`（基准收益率）, `excess_return`（超额收益）
  - `annual_return`（年化收益率，按 252 天/年）, `volatility`（年化波动率）
  - `max_drawdown`（最大回撤百分比）, `max_drawdown_days`（最大回撤天数）
  - `sharpe_ratio`（夏普比率，无风险利率 3%）, `win_rate`（正收益天数比例）
- **返回结果**: 包含 config/performance/daily_values/rebalance_records/selection_history/final_holdings/final_cash

---

## 8. BacktestNode（回测节点）

- **文件路径**: `nodes/backtest_engine/node.py`
- **类名**: `BacktestNode`
- **用途**: 作为独立计算节点运行，通过 gRPC 接收回测任务请求，支持水平扩展。
- **继承关系**: `BaseNode` 子类，`NodeType.BACKTEST`
- **RPC 端口**: 默认 50056
- **工作协程数**: 2（通过 `_worker_count` 配置）
- **任务类型**:
  - `single_stock`（单股回测，由 `run_backtest` RPC 触发）
  - `factor_selection`（因子选股回测，由 `run_factor_selection` RPC 触发）
- **RPC 方法**:
  - `run_backtest(params)`: 投递单股回测任务到队列，立即返回 task_id 和队列状态
  - `run_factor_selection(params)`: 投递因子选股回测任务到队列
  - `get_task_status(params)`: 查询任务状态（queued / running / completed / failed）
  - `cancel_task(params)`: 取消排队中的任务
- **单股回测执行 （`_execute_backtest`）**:
  1. 从 MongoDB `stock_daily` 查询行情数据
  2. 构建 `FactorData` + 自动计算技术指标
  3. 配置 `BacktestConfig`（默认权重：RSI/MACD/价格位置/成交量各 25%）
  4. 执行 `VectorizedBacktester.run()` + `PerformanceAnalyzer.analyze()`
  5. 结果存储到 MongoDB `backtest_tasks` 集合
- **因子选股回测执行 （`_execute_factor_selection`）**:
  1. 构建组合回测配置（股票池/调仓频率/Top N/权重方法/因子列表/排除规则/基准）
  2. 调用 `PortfolioBacktester.run()`
  3. 结果存储到 MongoDB
- **任务状态管理**: 所有任务状态（queued/running/completed/failed/cancelled）持久化到 `backtest_tasks` 集合，`_update_task_result` 使用 `convert_numpy_types` 处理 NumPy 类型序列化
- **数据查询 （`_fetch_price_data`）**:
  - 从 MongoDB `stock_daily` 按 `ts_code` + `trade_date` 范围查询，上限 3000 条
  - 转换 trade_date 为 DatetimeIndex，映射列名（vol -> volume）

---

## 通用机制

### A 股交易规则适配

1. **T+1 规则**: 买入当日不可卖出，通过 `last_buy_idx` 追踪最近一次买入日，`i <= last_buy_idx` 时禁止卖出信号。
2. **涨跌停检查**: 一字涨停板（open >= up_limit * 0.998 且 low >= up_limit * 0.998）禁止买入；跌停板（close <= down_limit * 1.002）禁止卖出。
3. **100 股整数倍**: 所有买卖股数均为 100 的整数倍（`int(shares / 100) * 100`），最小交易单位为 1 手 = 100 股。
4. **费用精确计算**:
   - 买入：佣金 = max(成交金额 * 万2, 5 元)，无印花税
   - 卖出：佣金 = max(成交金额 * 万2, 5 元)，印花税 = 成交金额 * 千1

### 因子数据对齐

所有因子数据通过 `FactorData.get_all_factors()` 按日期合并，自动添加前缀（tech_/sent_/fund_/custom_{name}_）避免列名冲突，最终对齐到行情数据的 DatetimeIndex。

### 绩效指标基准

- 年化交易日数：244 天/年（单股回测），252 天/年（组合回测）
- 无风险利率：3%（年化）
- 基准收益：单股用买入持有策略，组合用指定指数（默认沪深 300 000300.SH）
