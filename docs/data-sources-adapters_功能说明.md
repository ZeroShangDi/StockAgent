# 数据源适配层功能说明

## 概述

数据源适配层 (`src/data_sources/`) 为 DataSync 提供统一的多源数据获取能力。所有适配器继承自 `AsyncDataSourceAdapter` 抽象基类，返回数据遵循标准 TypedDict 结构。数据获取遵循 `Tushare -> AKShare -> BaoStock -> Coze` 的优先级回退链。

## 架构设计

### 基类: `AsyncDataSourceAdapter` (`src/data_sources/base.py`)

定义统一的异步接口，所有具体适配器必须实现。核心设计要点：

**标准数据结构 (TypedDict):**

| 数据类型 | TypedDict | 关键字段 |
|---------|-----------|---------|
| 股票基础信息 | `StockBasicRecord` | ts_code, symbol, name, industry, market, list_date |
| 日线行情 | `DailyRecord` | ts_code, trade_date, open, close, vol, amount |
| 每日指标 | `DailyBasicRecord` | ts_code, trade_date, pe, pb, total_mv(亿元), circ_mv(亿元) |
| 实时行情 | `RealtimeQuoteRecord` | ts_code, close, pct_chg, vol, amount |
| 资金流向 | `MoneyflowRecord` | ts_code, trade_date, net_amount, buy_elg/lg/md/sm_amount |
| 涨跌停 | `LimitListRecord` | ts_code, trade_date, limit(U/D), limit_times, first_time |
| 指数基础 | `IndexBasicRecord` | ts_code, name, index_type, base_date, base_point |
| 指数日线 | `IndexDailyRecord` | ts_code, trade_date, open, close, pct_chg, vol, amount |
| K线数据 | `KlineRecord` | time, open, high, low, close, volume, amount |
| 新闻 | `NewsRecord` | ts_code, title, content, datetime, url, source, type |

**令牌桶限流:** `TokenBucket` 类实现令牌桶算法，用于 Tushare API 频率控制。配置参数 `rate`（每秒生成令牌数）和 `capacity`（最大容量）。

**通用工具方法:**
- `_safe_float(value)` - 安全转换为 float，处理 NaN/None
- `_safe_int(value, default=0)` - 安全转换为 int
- `_normalize_ts_code(code)` - 将各种代码格式标准化为 `000001.SZ` 格式
  - `60xxxx` / `68xxxx` / `90xxxx` -> `.SH`
  - `00xxxx` / `30xxxx` / `20xxxx` -> `.SZ`
  - `8xxxxx` / `4xxxxx` / `92xxxx` -> `.BJ`
- `_extract_code(ts_code)` - 从 `600000.SH` 提取 `600000`

**数据源能力描述:** `DataSourceCapability` 数据类描述每个适配器支持的数据维度（11个布尔字段）。

**抽象方法列表（按职责分组）:**

| 职责 | 方法 | 返回类型 |
|------|------|---------|
| 生命周期 | `initialize()`, `shutdown()`, `is_available()` | None/None/bool |
| 股票基础 | `get_stock_basic()` | List[StockBasicRecord] |
| 日线数据 | `get_daily()`, `get_daily_basic()` | List[DailyRecord], List[DailyBasicRecord] |
| 实时行情 | `get_realtime_quotes()`, `get_realtime_index_quotes()` | Dict[str, RealtimeQuoteRecord] |
| 财务数据 | `get_financial_indicator()`, `get_income_statement()`, `get_balance_sheet()`, `get_cashflow_statement()`, `get_financial_data()` | List[dict] |
| 资金流向 | `get_moneyflow_industry()`, `get_moneyflow_concept()`, `get_moneyflow_hsgt()` | List[MoneyflowRecord] |
| 涨跌停 | `get_limit_list()`, `get_stk_limit()` | List[LimitListRecord] |
| 指数 | `get_index_basic()`, `get_index_daily()` | List[IndexBasicRecord], List[IndexDailyRecord] |
| 交易日历 | `get_trade_calendar()`, `get_latest_trade_date()`, `is_trading_time()` | List[str], Optional[str], bool |
| K线 | `get_kline()` | List[KlineRecord] |
| 新闻 | `get_news()`, `get_stock_news()` | List[NewsRecord] |

---

## 适配器详解

### 1. Tushare 适配器 (`src/data_sources/tushare_adapter.py`)

**类名:** `TushareAdapter`

**特点:** 数据最全面，需要付费 Token，有 API 调用频率限制。

**优先级:** `20`（最低优先级，作为最后回退——权限/积分不稳定时避免阻塞）。

**能力覆盖:** 全部 11 项能力均为 `True`。

**初始化流程:**
1. 读取 `TUSHARE_TOKEN`（优先级：构造参数 > `settings.tushare.token`）
2. 设置环境变量 `TUSHARE_TOKEN` 和 `TS_TOKEN`（避免 tushare 写入 `~/tk.csv`）
3. 创建 `ts.pro_api(token)` 客户端
4. 创建 `TokenBucket`：默认 rate_limit=200/分钟

**支持的 API 接口:**
| 方法 | Tushare API | 说明 |
|------|------------|------|
| `get_stock_basic` | `stock_basic` | A股列表，含行业/地区/上市日期 |
| `get_daily` | `daily` | 日线行情，支持前复权/后复权 |
| `get_daily_basic` | `daily_basic` | PE/PB/换手率/市值，**市值万->亿元转换** |
| `get_realtime_quotes` | `realtime_quote` (tushare包) | 实时行情，批次大小50，超时2秒 |
| `get_realtime_index_quotes` | `realtime_quote` (tushare包) | 三大指数(000001.SH/399001.SZ/399006.SZ) |
| `get_financial_indicator` | `fina_indicator` | 45个财务指标字段 |
| `get_income_statement` | `income` | 利润表 |
| `get_balance_sheet` | `balancesheet` | 资产负债表 |
| `get_cashflow_statement` | `cashflow` | 现金流量表 |
| `get_financial_data` | 以上4者并发 | 完整财务数据，`asyncio.gather` 并发 |
| `get_moneyflow_industry` | `moneyflow_ind_dc` (content_type="行业") | 行业资金流向，含分档数据 |
| `get_moneyflow_concept` | `moneyflow_ind_dc` (content_type="概念") | 概念板块资金流向 |
| `get_moneyflow_hsgt` | `moneyflow_hsgt` | 沪深港通资金流向 |
| `get_limit_list` | `limit_list_d` | 涨跌停列表，含16个字段 |
| `get_limit_step` | `limit_step` | 连板天梯（复盘用） |
| `get_limit_cpt_list` | `limit_cpt_list` | 最强板块统计（复盘用） |
| `get_top_inst` | `top_inst` | 龙虎榜机构买卖明细（复盘用） |
| `get_hm_list` | `hm_list` | 游资营业部名录（复盘用） |
| `get_ths_hot` | `ths_hot` | 同花顺热股排行（复盘用） |
| `get_ths_index` | `ths_index` | 同花顺概念/行业指数列表（复盘用） |
| `get_ths_member` | `ths_member` | 同花顺板块成分股（复盘用） |
| `get_ths_daily` | `ths_daily` | 同花顺板块日线（复盘用） |
| `get_index_basic` | `index_basic` | 指数基础信息 |
| `get_index_daily` | `index_daily` | 指数日线 |
| `get_trade_calendar` | `trade_cal` | 交易日历 |
| `get_latest_trade_date` | `trade_cal` | 最近交易日（18点前用昨天） |
| `get_news` | `news` | 新闻公告 |
| `get_kline` | `pro_bar` | K线数据，支持多周期多复权 |

**数据转换要点:**
- `get_daily_basic`: Tushare 原始市值单位是**万元**，代码中除以 10000 转换为**亿元**
- `get_realtime_quotes`: 涨跌幅若缺失，自动根据 `(close - pre_close) / pre_close * 100` 计算
- 所有方法在 Token 不可用或异常时返回空列表/字典，不抛异常

**限流机制:**
- 通过 `TokenBucket` 控制，配置 `rate_limit`（默认200次/分钟）
- 每次 API 调用前 `wait_and_acquire(1)` 获取令牌
- 实时行情批次间额外 `await asyncio.sleep(0.1)`

**错误处理:**
- `moneyflow_ind_dc` 权限不足时：记录 warning 日志，返回空列表，不中断流程
- `get_realtime_quotes` 使用 `asyncio.wait_for` 超时控制（默认2秒）

---

### 2. AKShare 适配器 (`src/data_sources/akshare_adapter.py`)

**类名:** `AKShareAdapter`

**特点:** 完全免费，实时行情较好（东方财富/新浪），新闻采集能力强，财务数据支持有限。

**优先级:** `70`（免费源中优先级最高）。

**能力覆盖:** `financial_data=False`（不支持完整财务），其余 10 项为 `True`。

**初始化:** 仅 `import akshare` 验证安装。

**支持的接口:**
| 方法 | AKShare 函数 | 说明 |
|------|-------------|------|
| `get_stock_basic` | `stock_info_a_code_name` | 股票列表（仅代码和名称，无行业/地区） |
| `get_daily` | `stock_zh_a_hist` | 日线行情，支持前复权/后复权 |
| `get_daily_basic` | `stock_individual_info_em` | 单股估值（逐股查询，不支持批量） |
| `get_realtime_quotes` | `stock_zh_a_spot_em` (默认) / `stock_zh_a_spot` (新浪) | 全市场实时行情 |
| `get_realtime_index_quotes` | `stock_zh_index_spot_em` | 仅返回三大指数 |
| `get_moneyflow_industry` | `stock_sector_fund_flow_rank` | 行业资金流向 |
| `get_limit_list` | `stock_zt_pool_em` + `stock_zt_pool_dtgc_em` | 涨跌停分两个接口获取 |
| `get_stock_news` | `stock_news_em` | 个股新闻（东方财富） |
| `get_kline` | `stock_zh_a_hist` / `stock_zh_a_minute` | K线数据，日/周/月 + 分钟级 |
| `get_trade_calendar` | `tool_trade_date_hist_sina` | 新浪交易日历 |

**数据标准化要点:**
- 列名兼容中英文：`代码`/`code`、`名称`/`name` 均支持
- 实时行情自动提取纯数字代码（处理带前缀/后缀的代码格式）
- AKShare 市值单位可能为万元，通过 `total_mv_raw > 1000` 启发式判断是否需转换为亿元
- 涨跌停分别调用涨停池和跌停池两个接口，合并返回
- 资金流向用行业名称作为 `ts_code`（稳定且唯一）

**限制:**
- `daily_basic` 批量查询不支持（逐股查询太慢），仅支持单只股票
- 不提供完整财务数据
- 不支持沪深港通资金流向

**错误处理:** 每个方法异常时记录 error 日志，返回空列表/字典。

---

### 3. BaoStock 适配器 (`src/data_sources/baostock_adapter.py`)

**类名:** `BaoStockAdapter`

**特点:** 完全免费，历史数据较全，不支持实时行情，需要登录/登出。

**优先级:** `60`（免费回退源）。

**能力覆盖:** `realtime_quotes=False`, `financial_data=False`, `money_flow=False`, `limit_data=False`, `news=False`，其余 6 项为 `True`。

**初始化/生命周期:**
- `initialize()`: `import baostock` 验证安装
- `_login()`: 调用 `bs.login()`，返回 `LoginResult` 对象
- `_logout()`: 调用 `bs.logout()`
- 每次数据查询前自动调用 `_login()` 确保已登录

**代码转换 `_convert_code()`:**
- `000001.SZ` -> `sz.000001`
- `600000.SH` -> `sh.600000`
- 北交所代码（8/4/92开头）不支持，返回空字符串

**支持的接口:**
| 方法 | BaoStock API | 说明 |
|------|-------------|------|
| `get_stock_basic` | `query_stock_basic` + `query_stock_industry` | 股票列表含行业（过滤type=1） |
| `get_daily` | `query_history_k_data_plus` | 日线行情，date/close/volume/amount/pctChg |
| `get_daily_basic` | `query_history_k_data_plus` (估值字段) | PE_TTM/PB/PS_TTM，仅支持单股指定日期 |
| `get_kline` | `query_history_k_data_plus` | K线，支持日/周/月/5/15/30/60分钟 |
| `get_trade_calendar` | `query_trade_dates` | 交易日历，过滤 is_trading_day=1 |
| `get_index_daily` | `query_history_k_data_plus` | 指数日线 |

**数据获取模式:** BaoStock 使用游标模式，需循环 `rs.next()` 读取所有行。

**复权标记映射:**
- `qfq` -> adjflag `"2"`（前复权）
- `hfq` -> adjflag `"1"`（后复权）
- 不复权 -> adjflag `"3"`

**日期格式:** BaoStock 需要 `YYYY-MM-DD` 格式，适配器在调用前自动转换。

**行业名称清洗:** 去掉编码前缀（如 `A01`），通过 `re.sub(r'^[A-Z]\d+', '', name)` 处理。

**限制:**
- 不支持实时行情（`get_realtime_quotes` 返回 `{}`）
- 不支持北交所代码
- `daily_basic` 批量查询太慢，仅支持单股指定日期
- 不支持资金流向/涨跌停/新闻

---

### 4. Coze 工作流适配器 (`src/data_sources/coze_workflow_adapter.py`)

**类名:** `CozeWorkflowAdapter`

**特点:** 通过 Coze 工作流调用股票插件能力，单个工作流承载所有数据接口，优先级最高（作为优选源）。支持股票基础信息、日线行情、实时行情、财务数据、指数数据和 K线数据。

**优先级:** `90`（最高优先级，首选数据源）。

**能力覆盖:** `money_flow=False`, `limit_data=False`, `news=False`，其余 8 项为 `True`。

**初始化流程:**
1. 从 `settings.coze` 读取配置：`api_token`, `workflow_id`, `api_base`, `space_id`, `app_id`, `bot_id`, `timeout`
2. 创建 `UnifiedHttpClient`，配置重试参数（`max_retries=2`, `retry_backoff_seconds=0.5`）
3. 设置 Authorization Bearer 头

**工作流调用机制 `_run_plugin(plugin, params)`:**
- 统一 POST 到 `{api_base}/v1/workflow/run`
- body 包含：`workflow_id`, `parameters.plugin`, `parameters.params`
- 自动解析嵌套 JSON 字符串（`_decode_json_like`）
- 返回码 `code > 0` 时抛出 `RuntimeError`

**支持的插件 (plugin):**

| 插件名 | 用途 | 对应方法 |
|--------|------|---------|
| `info_all_code` | 全市场股票列表 | `get_stock_basic` |
| `stock_current` | 个股实时行情 | `get_realtime_quotes`, `get_stock_basic(fallback)`, `health_check` |
| `stock_k` | 个股k线（日/周/月/分钟） | `get_daily`, `get_daily_basic`, `get_kline` |
| `stock_shares` | 股本信息（总股本/流通A股） | `get_daily_basic` |
| `stock_fin_data` | 财务指标数据 | `get_financial_indicator` |
| `index_current_data` | 指数实时行情 | `get_realtime_index_quotes` |
| `index_k` | 指数K线 | `get_index_daily`, `get_kline(指数)` |

**日期窗口拆分 `_split_date_windows()`:**
- 单次请求最大跨度 `MAX_STOCK_K_RANGE_DAYS = 700` 天
- 超过跨度自动拆分为多个窗口请求
- 合并结果后按 trade_date 排序去重

**数据标准化辅助方法:**
- `_normalize_trade_date()` - 支持时间戳(秒/毫秒/13位)、YYYYMMDD、YYYY-MM-DD 多种格式
- `_format_coze_date()` - 将 YYYYMMDD 转为 YYYY-MM-DD（Coze 接口要求）

**实时行情并发控制:**
- 使用 `asyncio.Semaphore(batch_size)` 控制并发数（默认8）
- 所有请求通过 `asyncio.gather` 并发执行

**`get_daily_basic` 增强计算:**
- 计算总市值 `total_mv = close * total_shares / 1e8`（亿元）
- 计算流通市值 `circ_mv = close * list_a_shares / 1e8`
- 计算 PE = `close / basic_eps`
- 计算 PB = `close / net_asset_ps`

**健康检查:** 调用 `stock_current` 插件查询 `000001`，验证返回记录中 `stock_code == "000001"`。

**错误处理:** 插件级别异常抛出 `RuntimeError`（包含 `debug_url`）；适配器 level 的 `get_*` 方法在适配器不可用时返回空列表/字典。

---

## 优先级与回退链

| 优先级 | 适配器 | 默认值 | 说明 |
|--------|--------|--------|------|
| 90 | CozeWorkflowAdapter | coze | 首选源，数据最全最快 |
| 70 | AKShareAdapter | akshare | 免费实时数据 |
| 60 | BaoStockAdapter | baostock | 免费历史数据 |
| 20 | TushareAdapter | tushare | 付费源，权限不稳定时作为最后回退 |

`DataSourceManager` 管理适配器注册和回退调度，当高优先级适配器失败/超时时自动尝试下一优先级。

## 数据格式标准

### vol 和 amount 单位约定

| 字段 | Tushare | AKShare | BaoStock | Coze | 标准输出 |
|------|---------|---------|----------|------|---------|
| vol (日线) | 手 | 股(东方财富) | 股 | 股 | **随源不变**（适配器不转换成交量单位） |
| amount (日线) | 千元 | 元(东方财富) | 元 | 元 | **随源不变** |
| vol (实时) | 股 | 股 | - | 股 | 股 |
| amount (实时) | 元 | 元 | - | 元 | 元 |
| total_mv (市值) | 万元 -> 转亿元 | 万元(启发式转亿元) | 不提供 | 亿元(计算) | **统一亿元** |

关键注意：**Tushare 的日线 vol 单位为"手"、amount 为"千元"**，与其他源不一致。调用方在使用时需要知道数据来源以正确解释数值。
