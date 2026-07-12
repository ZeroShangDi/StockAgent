# 核心管理-数据源与LLM 功能说明

## 概述

数据源管理器、LLM 管理器、分析管理器构成了 DataSync 的上游数据通路，分别负责多源数据获取路由、大模型调用、市场情绪周期分析。

**代码位置：**

| 文件 | 类名 | 全局单例 | 说明 |
|---|---|---|---|
| `core/managers/data_source_manager.py` | `DataSourceManager` | `data_source_manager` | 多源统一路由，回退链调度 |
| `core/managers/llm_manager.py` | `LLMManager` | `llm_manager` | 大模型路由，多 provider 支持 |
| `core/managers/analysis_manager.py` | `AnalysisManager` | `analysis_manager` | 双评分情绪/强度分析，市场周期判断 |

---

## 一、DataSourceManager

### 1.1 Adapter 注册与初始化

```python
await data_source_manager.initialize()
```

**注册顺序（按配置可用性）：**

| 顺序 | Adapter 类 | 条件 | priority |
|---|---|---|---|
| 1 | `TushareAdapter` | `TUSHARE_TOKEN` 已配置 | 最高（通过 settings.tushare.is_configured 检查） |
| 2 | `CozeWorkflowAdapter` | Coze 已配置（api_token, workflow_id 等） | 中 |
| 3 | `AKShareAdapter` | 始终添加（免费） | 低 |
| 4 | `BaoStockAdapter` | 始终添加（免费） | 低 |

**初始化逻辑：**
1. 检查 `settings.tushare.is_configured` 判断 Tushare token 是否配置
2. 检查 `settings.coze.is_configured` 判断 Coze 工作流是否配置
3. AKShare 和 BaoStock 作为免费数据源始终尝试添加
4. 每个 adapter 调用 `initialize()` + `is_available()` 确认可用
5. 不可用的 adapter 会被 `shutdown()` 清理
6. 最终按 `priority` 降序排列

**所有方法返回统一格式：** `(data, source_name)` 元组，`source_name` 表示实际提供数据的 adapter 名称

### 1.2 回退链机制（`_get_with_fallback`）

这是 DataSourceManager 的核心方法，所有公开 API 方法都通过它实现多源降级。

```python
async def _get_with_fallback(
    method_name: str,
    preferred_source: Optional[str] = None,
    **kwargs,
) -> Tuple[Any, Optional[str]]:
```

**执行流程：**

```
1. 获取配置的回退链（source chain）
   - 通过 _get_source_chain_key 确定链键
   - 先检查环境变量 SOURCE_CHAIN_OVERRIDES 是否有覆盖
   - 否则使用 DEFAULT_SOURCE_CHAINS 默认配置
    |
2. 对链上的每个 adapter（按优先级排列）：
   a. 检查 adapter.is_available()
   b. 检查 source cooling down（速率限制冷却期）
   c. 调用 _wait_for_source_budget（TokenBucket 速率控制）
   d. 调用 adapter.{method_name}(**accepted_kwargs)
      - 方法级别的超时控制（_get_method_timeout）
      - 参数过滤：只传 adapter 方法接受的参数
   e. 结果检查：
      - None → 跳过，尝试下一个源
      - list/dict 非空 → 成功，记录 stats 并返回
   f. 异常处理：
      - asyncio.TimeoutError → skip，记录 timeout stats
      - DataSourceHttpError → 按 error_type 分类处理
        - rate_limited → 触发 source cooldown
      - 其他异常 → skip，记录 failure stats
    |
3. 所有源都失败：
   - 如果所有 outcome 都不为 "empty" → 抛出 DataSourceChainError
   - 否则 → 返回 (None, None)
```

### 1.3 默认回退链配置

`DEFAULT_SOURCE_CHAINS` 根据不同方法+调用形态分配不同的优先级链：

| 链键 | 优先级链 | 适用场景 |
|---|---|---|
| `get_stock_basic` | akshare → baostock → coze → tushare | 股票基础信息（akshare 免费可靠） |
| `get_daily.single` | coze → akshare → baostock → tushare | 单股日线（Coze 优先） |
| `get_daily.full_market` | tushare → baostock → akshare → coze | 全市场日线（Tushare 优先） |
| `get_daily_basic.single` | coze → akshare → baostock → tushare | 单股指标 |
| `get_daily_basic.full_market` | tushare → baostock → akshare → coze | 全市场指标 |
| `get_index_daily` | tushare → baostock → akshare | 指数日线 |
| `get_latest_trade_date` | tushare → baostock → akshare → coze | 最新交易日 |
| `get_trade_calendar` | tushare → baostock → akshare → coze | 交易日历 |
| `get_limit_list` | tushare → akshare | 涨跌停列表 |
| `get_moneyflow_industry` | tushare → akshare | 行业资金流向 |
| `get_moneyflow_concept` | tushare → akshare | 概念资金流向 |
| `get_realtime_quotes` | coze → tushare → akshare → baostock | 实时行情 |
| `get_realtime_index_quotes` | coze → akshare → tushare | 实时指数 |
| `get_financial_indicator` | coze → akshare → baostock → tushare | 财务指标 |
| `get_financial_data` | coze → akshare → baostock → tushare | 财务数据 |
| `get_kline` | coze → akshare → baostock → tushare | K线数据 |

**单股 vs 全市场的区分：**
- `ts_code` 存在且不含逗号 → `single` 链（Coze 优先）
- `trade_date` 存在且无 `ts_code` → `full_market` 链（Tushare 优先）

### 1.4 速率限制

#### TokenBucket 限流

通过环境变量 `DATASYNC_SOURCE_RATE_LIMITS` 配置，格式：
```
tushare=200/m,coze=30/m
```

每个数据源独立维护一个 `TokenBucket` 实例：
- `rate`：令牌生成速率（如 `200/m` → `200/60 = 3.33 tokens/s`）
- `capacity`：令牌桶容量（`max(1, amount)`）

每次调用前通过 `_wait_for_source_budget(adapter_name)` 等待获取令牌。

#### Source Cooldown（冷却）

当某个数据源返回 `rate_limited` 错误时，触发冷却机制：
- 冷却时长：默认 `settings.data_sync.source_rate_limit_cooldown_seconds`（默认 60 秒）或从响应的 `retry_after_seconds` 取值
- 冷却期间：该源被跳过，记录为 `rate_limited` 状态
- 冷却结束后：自动恢复可用

### 1.5 方法级超时配置

每个核心同步方法对不同的 adapter 有不同的超时时间：

| 方法 | Tushare | BaoStock | AKShare |
|---|---|---|---|
| `get_daily`（全市场） | 45s | 25s | 30s |
| `get_daily_basic`（全市场） | 35s | 20s | 25s |
| `get_index_daily` | 20s | 12s | 15s |
| `get_latest_trade_date` | 15s | 10s | 10s |
| `get_trade_calendar` | 15s | 10s | 10s |
| `get_moneyflow_industry` / `_concept` | 25s | - | 25s |
| `get_limit_list` | 20s | - | 20s |

非核心方法和单股请求不设超时（`_get_method_timeout` 返回 `None`）。

### 1.6 回退链覆盖

通过环境变量 `DATASYNC_SOURCE_CHAIN_OVERRIDES` 可自定义回退链：

```
export DATASYNC_SOURCE_CHAIN_OVERRIDES="get_daily.full_market=baostock,akshare;get_limit_list=akshare"
```

格式：`chain_key=source1,source2,...`，多个链用 `;` 分隔。

### 1.7 调用统计

每次 `_get_with_fallback` 调用都会记录详细统计，通过 `get_call_stats_summary()` 查询：

```python
summary = data_source_manager.get_call_stats_summary()
```

统计字段（per method+adapter）：`attempt_count`, `success_count`, `timeout_count`, `rate_limited_count`, `server_error_count`, `network_error_count`, `failure_count`, `empty_result_count`, `fallback_count`, `last_duration_ms` 等。

### 1.8 公开 API 方法概览

| 方法 | 说明 | 返回类型 |
|---|---|---|
| `get_stock_basic()` | 股票基础信息 | `Tuple[List[dict], str]` |
| `get_daily()` | 日线行情 | `Tuple[List[dict], str]` |
| `get_daily_basic()` | 每日指标（PE/PB等） | `Tuple[List[dict], str]` |
| `get_index_daily()` | 指数日线 | `Tuple[List[dict], str]` |
| `get_index_basic()` | 指数基础信息 | `Tuple[List[dict], str]` |
| `get_moneyflow_industry()` | 行业资金流向 | `Tuple[List[dict], str]` |
| `get_moneyflow_concept()` | 概念板块资金流向 | `Tuple[List[dict], str]` |
| `get_moneyflow_hsgt()` | 沪深港通资金流向 | `Tuple[List[dict], str]` |
| `get_limit_list()` | 涨跌停列表 | `Tuple[List[dict], str]` |
| `get_stk_limit()` | 涨跌停价格 | `Tuple[List[dict], str]` |
| `get_trade_calendar()` | 交易日历 | `Tuple[List[str], str]` |
| `get_latest_trade_date()` | 最新交易日 | `Tuple[Optional[str], str]` |
| `get_realtime_quotes()` | 实时行情 | `Tuple[Dict, str]` |
| `get_realtime_index_quotes()` | 指数实时行情 | `Tuple[Dict, str]` |
| `get_financial_indicator()` | 财务指标 | `Tuple[List[dict], str]` |
| `get_financial_data()` | 完整财务数据 | `Tuple[Dict, str]` |
| `get_kline()` | K线数据 | `Tuple[List[dict], str]` |
| `get_news()` | 新闻数据 | `Tuple[List[dict], str]` |
| `get_stock_news()` | 个股新闻 | `Tuple[List[dict], str]` |
| `get_ths_index()` | 同花顺板块列表 | `Tuple[List[dict], str]` |
| `get_ths_member()` | 同花顺板块成分股 | `Tuple[List[dict], str]` |
| `get_ths_daily()` | 同花顺板块日线 | `Tuple[List[dict], str]` |
| `get_limit_step()` | 连板天梯 | `Tuple[List[dict], str]` |
| `get_limit_cpt_list()` | 最强板块统计 | `Tuple[List[dict], str]` |
| `get_top_inst()` | 龙虎榜机构明细 | `Tuple[List[dict], str]` |
| `is_trading_time()` | 是否交易时间 | `bool` |

---

## 二、LLMManager

### 2.1 Provider 支持

| Provider | 配置值 | 默认 API Base | 说明 |
|---|---|---|---|
| OpenAI | `openai` | OpenAI 官方 | GPT 系列 |
| DashScope | `dashscope` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 通义千问 |
| DeepSeek | `deepseek` | `https://api.deepseek.com/v1` | DeepSeek 系列 |
| 智谱 AI | `zhipu` | `https://open.bigmodel.cn/api/paas/v4` | GLM 系列 |
| Ollama | `ollama` | `http://localhost:11434/v1` | 本地部署 |

所有 provider 均通过 OpenAI 兼容 SDK（`openai.AsyncOpenAI`）调用，仅 `api_key` 和 `base_url` 不同。

**配置项（`settings.llm`）：**

| 配置项 | 环境变量 | 说明 |
|---|---|---|
| `provider` | `LLM_PROVIDER` | Provider 名称 |
| `model_name` | `LLM_MODEL_NAME` | 模型名称 |
| `api_key` | `LLM_API_KEY` | API Key |
| `api_base` | `LLM_API_BASE` | API Base URL（可覆盖默认值） |
| `temperature` | - | 温度参数 |
| `max_tokens` | - | 最大 token 数 |
| `max_concurrent_requests` | - | 最大并发请求数 |
| `embedding_provider` | - | 独立 Embedding provider |
| `embedding_model` | - | Embedding 模型名 |
| `embedding_api_key` | - | Embedding API Key |
| `embedding_api_base` | - | Embedding API Base |

### 2.2 Chat 接口

#### 同步 Chat

```python
response = await llm_manager.chat(
    messages=[{"role": "user", "content": "分析今天的行情"}],
    model="deepseek-chat",      # 可选，默认使用配置
    temperature=0.3,             # 可选
    max_tokens=2000,             # 可选
)
# 返回: str
```

#### 流式 Chat

```python
async for chunk in llm_manager.chat_stream(
    messages=[{"role": "user", "content": "分析今天的行情"}],
):
    print(chunk, end="")
```

**并发控制：** 两个方法都受 `asyncio.Semaphore(max_concurrent_requests)` 限制，防止同时向 LLM API 发送过多请求。

### 2.3 Embedding 接口

```python
embeddings = await llm_manager.embedding(
    texts=["股票A今天涨停", "股票B今天跌停"],
    model="text-embedding-3-small",  # 可选
)
# 返回: List[List[float]]，每个文本对应一个向量
```

- 使用独立的 `_embedding_client`（如果配置了 `embedding_provider`）
- 否则使用主 `_client`（注意：DeepSeek 不支持 Embedding API）

### 2.4 Token 统计

```python
usage = llm_manager.get_token_usage()
# → {"prompt_tokens": 12345, "completion_tokens": 5678, "total_tokens": 18023}
```

每次 Chat 调用完成后自动累加。

---

## 三、AnalysisManager

### 3.1 设计概述（V2.3 双评分动态情绪周期系统）

AnalysisManager 实现了双评分（情绪评分 + 强度评分）动态周期判定系统，版本 V2.3。

**评分结构：**
```
情绪评分 = EMA5平滑( 3日EMA平滑(情绪核心分(70)) + 趋势分(30) )
强度评分 = EMA5平滑( 3日EMA平滑(强度核心分(70)) + 趋势分(30) )
```

**参数说明：**
- **核心分（70分）**：基于当日数据 vs. MA10 基准计算
- **趋势分（30分）**：基于今日核心分 vs. 前日核心分的变化比例
- **3日 EMA 平滑**：消除单日脉冲（权重：今日 0.6 + 昨日 0.3 + 前日 0.1）
- **5日 EMA 平滑**：消除锯齿（权重：今日 0.30 + 昨日 0.25 + 前日 0.20 + 大前日 0.15 + 大大前日 0.10）

### 3.2 情绪评分核心分（70分）—— calculate_sentiment_core_v2

**设计思路：** 聚焦超短情绪，权重向连板高度、晋级率倾斜。

| 因子 | 满分 | 计算方式 | 绝对阈值约束 |
|---|---|---|---|
| 连板高度 | 25 | `min(绝对值分, 相对值分)` | ≤2板=0分, ≥5板=满分 |
| 晋级率 | 25 | `min(绝对值分, 相对值分)` | ≤30%=0分, ≥60%=满分 |
| 连板家数(2板+) | 10 | `min(绝对值分, 相对值分)` | ≤3家=0分, ≥10家=满分 |
| 封板率 | 5 | 仅相对值分 | - |
| 跌停惩罚 | 15 | 反向计分（越多分越低） | - |

**底仓约束：**
- 连板高度 ≤ 2 → 核心分封顶 40 分
- 晋级率 ≤ 30% → 额外扣 10 分

### 3.3 强度评分核心分（70分）—— calculate_strength_core_v2

**设计思路：** 聚焦市场亏钱效应，权重向涨跌比倾斜。

| 因子 | 满分 | 计算方式 | 绝对阈值约束 |
|---|---|---|---|
| 上涨家数占比 | 20 | `min(绝对值分, 相对值分)` | <30%=0分, >60%=满分 |
| 涨幅中位数 | 20 | `min(绝对值分, 相对值分)` | ≤-0.5%=0分, ≥1%=满分 |
| 成交额相对强度 | 15 | 仅相对值分 | - |
| 涨5%/跌5%比 | 15 | `min(绝对值分, 相对值分)` | <0.5=0分, >2=满分 |

**底仓约束：**
- 上涨家数 ≤ 30% → 核心分封顶 40 分
- 涨跌幅中位数 ≤ -0.5% → 额外扣 10 分

### 3.4 趋势分（30分）—— calculate_trend_score

```
趋势比例 = (今日平滑核心分 - 前日平滑核心分) / 前日平滑核心分
```

| 条件 | 得分 | 趋势方向 |
|---|---|---|
| ≥ +15% | 30 | "up"（明显走强） |
| ≥ +10% | 10 | "up"（温和走强） |
| ≥ -10% | 5 | "flat"（横盘震荡） |
| < -10% | 0 | "down"（明显走弱） |

### 3.5 周期判定 —— identify_cycle_by_trends

基于双趋势组合判定周期：

| 情绪趋势 | 强度趋势 | 周期 | 说明 |
|---|---|---|---|
| up | up | `main_upward` | 主升期，双趋势向上 |
| up | down | `divergence` | 分歧期，趋势背离 |
| down | up | `divergence` | 分歧期，趋势背离 |
| down | down | `decline` | 退潮期，双趋势向下 |
| flat | flat | `chaos` | 混沌期，无明确方向 |
| 双低(<20) | 双低(<20) | `ice_point` | 冰点期，极度悲观 |
| 双低(<40) | 双低(<40) + 有止跌 | `recovery` | 修复期，情绪回暖 |

### 3.6 完整分析流程 —— analyze_and_store

```python
analysis = await analysis_manager.analyze_and_store(
    stats=stats_result,      # _compute_daily_stats 的产出
    prev_stats=prev_stats,   # 前一日 daily_stats 记录
    mongo_manager=mongo_manager,
)
```

**流程（共 11 步）：**

1. 加载 MA10 基准（`load_ma10_baseline`）— 从 daily_stats 历史数据计算各因子均值
2. 加载近 3 日核心分（`load_recent_core_scores`）— 从 market_analysis 读取
3. 加载近 5 日最终评分（`load_recent_final_scores`）— 用于 5 日 EMA
4. 计算当日核心分（情绪 + 强度）
5. 3 日 EMA 平滑核心分
6. 计算趋势分
7. 原始评分 = 平滑核心分 + 趋势分
8. 5 日 EMA 强平滑 → 最终评分
9. 计算 3 日趋势方向（`identify_3day_trend`）→ up/down/flat
10. 双趋势组合判定周期
11. 写入 `market_analysis` 集合（`upsert=True`）

### 3.7 MA10 基准计算

`load_ma10_baseline(trade_date, mongo_manager)` 从 `daily_stats` 集合加载最近 10 个交易日数据，计算各因子均值：

| 基准字段 | 来源字段 | 用途 |
|---|---|---|
| `avg_max_height` | `max_limit_height` | 情绪-连板高度相对分 |
| `avg_limit_up` | `limit_up_count` | 情绪-跌停惩罚 |
| `avg_seal_rate` | `seal_rate` | 情绪-封板率相对分 |
| `avg_cont_board` | `cont_board_count` | 情绪-连板家数相对分 |
| `avg_promo_rate` | `promotion_rate` | 情绪-晋级率相对分 |
| `avg_limit_down` | `limit_down_count` | 情绪-跌停惩罚基准 |
| `avg_amount` | `total_amount` | 强度-成交额相对分 |
| `avg_up_ratio` | `up_ratio` | 强度-涨跌比相对分 |
| `avg_pct_median` | `pct_chg_median` | 强度-涨幅中位数相对分 |
| `avg_index_chg` | `index_pct_chg` | （未在当前强度计算中使用） |

**缓存：** 使用 `OrderedDict` 做 LRU 缓存，最大 256 条，避免重复查询。

### 3.8 仓位建议

| 周期 | 仓位级别 | 仓位范围 | 操作建议 |
|---|---|---|---|
| `main_upward` | 重仓 | 7~10成 | 顺势做多，追强不追弱 |
| `divergence` | 半仓 | 3~5成 | 只做核心龙头，警惕补跌 |
| `decline` | 空仓 | 0~1成 | 等待企稳，不抄底 |
| `ice_point` | 空仓 | 0成 | 极小仓试错首板，等待修复 |
| `recovery` | 轻仓 | 2~3成 | 试错先锋龙，逐步加仓 |
| `chaos` | 观望 | 1~3成 | 轮动行情，快进快出 |
| `unknown` | 观望 | 0~2成 | 数据不足，谨慎操作 |

### 3.9 兼容旧接口

| 旧方法 | 新方法 | 说明 |
|---|---|---|
| `calculate_scores(stats)` | `calculate_scores_with_baseline(stats, baseline)` | 旧方法使用固定默认基准（1万亿成交额、80家涨停） |
| `identify_cycle(stats, prev_stats)` | `identify_cycle_by_trends(...)` 或 `identify_cycle_v2(...)` | 旧方法基于简化规则，新方法基于双趋势组合 |
| `load_ma30_baseline()` | `load_ma10_baseline()` | MA30 降级为 MA10（代码注释"兼容旧接口"） |

---

## 四、异常与边界条件汇总

### DataSourceManager
- **全源不可用**：抛出 `DataSourceChainError`，携带 `method_name` 和各源失败详情
- **所有源返回空**：返回 `(None, None)`，不抛异常
- **速率限制触发**：触发 source cooldown，跳过该源直到冷却结束
- **无 Tushare token**：跳过 TushareAdapter，仅使用免费数据源

### LLMManager
- **不支持 Chat 的 Embedding provider**：通过独立 `embedding_client` 隔离
- **并发超限**：`asyncio.Semaphore` 自动排队等待
- **Provider 不支持**：初始化时抛出 `ValueError("Unsupported LLM provider: xxx")`

### AnalysisManager
- **MA10 数据不足**：`data_count < 10` 时仍正常计算，各因子使用已有数据均值
- **历史数据完全缺失**：`_calc_relative_score` 返回 `max_score * 0.5`（给 50% 分）
- **前日核心分不存在**：趋势分固定给 15 分，趋势方向为 "flat"
