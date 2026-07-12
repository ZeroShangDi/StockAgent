# 核心管理-数据源与LLM 测试用例

## 一、DataSourceManager 测试用例

### 1.1 数据源正常回退（Tushare 成功时跳过 AKShare）

**前置条件：**
- Tushare token 已配置，`is_available()` 返回 `True`
- AKShare 可用
- `get_stock_basic` 的回退链为 `akshare → baostock → coze → tushare`
- Tushare `get_stock_basic()` 返回 5000 条有效数据

**操作：** 调用 `await data_source_manager.get_stock_basic()`

**预期结果：**
- 按回退链顺序，第一个源是 `akshare`
- 如果 `akshare` 成功返回非空数据 → 返回 akshare 的数据，标记 `source="akshare"`
- `tushare` 不会被调用（已提前返回）
- `attempted_sources` 只包含 `["akshare"]`

### 1.2 数据源异常回退（Tushare 超时 → AKShare）

**前置条件：**
- `get_limit_list` 的回退链为 `tushare → akshare`
- Tushare `get_limit_list()` 超时（模拟 `asyncio.TimeoutError`）
- AKShare `get_limit_list()` 返回有效数据

**操作：** 调用 `await data_source_manager.get_limit_list(trade_date="20250620")`

**预期结果：**
1. Tushare 调用发起，等待 20 秒后超时
2. 记录 Tushare 的 timeout 统计
3. 自动 fallback 到 AKShare
4. AKShare 返回有效数据
5. 最终返回 `(data, "akshare")`
6. `attempted_sources` = `["tushare", "akshare"]`
7. 不抛异常

### 1.3 全源不可用时的错误处理

**前置条件：**
- 所有数据源都不可用（如所有 adapter 的 `get_daily()` 都抛异常或超时）
- 且所有 outcome status 都不是 `"empty"`

**操作：** 调用 `await data_source_manager.get_daily(trade_date="20250620")`

**预期结果：**
- 抛出 `DataSourceChainError`
- 异常的 `method_name` = `"get_daily"`
- 异常的 `source_chain` 包含所有尝试的源名称
- 异常的 `outcomes` 包含每个源的详细失败信息（status, duration_ms, error_type, error）
- 可以通过 `get_call_stats_summary()` 查看所有失败记录

### 1.4 所有源返回空数据（非异常）

**前置条件：**
- 所有数据源可用，但都返回 `None` 或空列表（如查询不存在的数据）

**操作：** 调用 `await data_source_manager.get_daily(ts_code="INVALID")`

**预期结果：**
- 返回 `(None, None)`
- 不抛出 `DataSourceChainError`（因为所有 outcome 包含 "empty"）
- 各源的状态记录为 `"empty"` 而非 `"failed"`

### 1.5 速率限制触发与恢复

**前置条件：**
- 配置 `DATASYNC_SOURCE_RATE_LIMITS="tushare=200/m"`
- 不设置额外的 source cooldown
- 模拟 Tushare 返回 `DataSourceHttpError(error_type="rate_limited", retry_after_seconds=30)`

**操作：** 连续快速调用 `get_daily` 直到触发

**预期结果：**

**第一次触发 rate_limited 时：**
- Tushare 被标记为 cooling down（`cooldown_until = now + 30s`）
- 后续调用自动跳过 Tushare，直接尝试下一个源
- `_record_call_outcome` 记录 `status="rate_limited"`
- 日志输出 `"Tushare.get_daily skipped: source cooling down for 30.0s"`

**冷却期间（30秒内）：**
- Tushare 被跳过，不发起 HTTP 请求
- 不影响其他数据源（AKShare、BaoStock 正常调用）

**冷却结束后（30秒后）：**
- Tushare 自动恢复可用
- 下次调用正常尝试 Tushare

**TokenBucket 限流行为：**
- 200/m = 3.33 tokens/s
- 调用 `_wait_for_source_budget("tushare")` 在令牌不足时自动等待

### 1.6 回退链覆盖（自定义优先级）

**前置条件：**
- 设置环境变量：
  ```
  DATASYNC_SOURCE_CHAIN_OVERRIDES="get_limit_list=akshare"
  ```

**操作：** 调用 `await data_source_manager.get_limit_list(trade_date="20250620")`

**预期结果：**
- `_get_configured_source_chain` 返回 `(chain_key, ["akshare"], True)`（标记为 override）
- 回退链只包含 akshare
- 如果 akshare 失败 → 不尝试 tushare → 抛出 `DataSourceChainError`
- 如果是 normal chain（`override_chain=False`），skip 的源后会自动追加剩余源

### 1.7 单股 vs 全市场的回退链自动选择

**场景 1：全市场**
```python
await data_source_manager.get_daily(trade_date="20250620")  # 无 ts_code
```
- 链键：`get_daily.full_market`
- 回退链：`tushare → baostock → akshare → coze`

**场景 2：单股**
```python
await data_source_manager.get_daily(ts_code="000001.SZ")
```
- 链键：`get_daily.single`
- 回退链：`coze → akshare → baostock → tushare`

### 1.8 Adapter 初始化失败不阻断整体

**前置条件：**
- Tushare token 已配置但网络不可达（`is_available()` 返回 `False`）
- AKShare 和 BaoStock 正常

**操作：** 调用 `await data_source_manager.initialize()`

**预期结果：**
- Tushare adapter 初始化后被 `shutdown()` 清理，不加入 `_adapters`
- AKShare 和 BaoStock 正常初始化
- `_adapters` 列表包含 akshare 和 baostock，不含 tushare
- 日志输出 `"Adapter tushare not available"`
- 整体初始化成功（`_initialized = True`）

### 1.9 调用统计准确性

**操作：** 执行多次不同方法的调用后，调用 `data_source_manager.get_call_stats_summary()`

**预期结果：**
- `entries` 包含所有 `{method_name}:{adapter_name}` 组合的统计
- `success_count` + `failure_count` + `timeout_count` + `empty_result_count` + ... = `attempt_count`
- `core_entries` 仅包含 `CORE_SYNC_METHODS` 中的方法
- `degraded_entries` 包含所有有过降级行为的条目
- `started_at` 记录统计开始时间（可通过 `reset_call_stats()` 重置）

---

## 二、LLMManager 测试用例

### 2.1 多 Provider 切换

#### 2.1.1 DeepSeek 初始化

**前置条件：** `LLM_PROVIDER=deepseek`, `LLM_API_KEY` 已配置

**操作：** 调用 `await llm_manager.initialize()`

**预期结果：**
- `_client.base_url` 为 `"https://api.deepseek.com/v1"`（或自定义的 `LLM_API_BASE`）
- `_client.api_key` 为配置的 API Key
- `_initialized = True`

#### 2.1.2 OpenAI 初始化

**前置条件：** `LLM_PROVIDER=openai`

**预期结果：**
- `_client.base_url` 为 OpenAI 官方地址或自定义 `LLM_API_BASE`

#### 2.1.3 Ollama 初始化

**前置条件：** `LLM_PROVIDER=ollama`

**预期结果：**
- `_client.base_url` 为 `"http://localhost:11434/v1"`
- `_client.api_key` 为 `"ollama"`（不需要真实 key）

#### 2.1.4 不支持的 Provider

**前置条件：** `LLM_PROVIDER=unknown_provider`

**操作：** 调用 `await llm_manager.initialize()`

**预期结果：** 抛出 `ValueError("Unsupported LLM provider: unknown_provider")`

### 2.2 LLM 并发请求控制

**前置条件：**
- `max_concurrent_requests = 2`（配置为较小值以测试）
- 启动 5 个并发请求

**操作：**
```python
tasks = [llm_manager.chat([{"role": "user", "content": "hi"}]) for _ in range(5)]
results = await asyncio.gather(*tasks)
```

**预期结果：**
- 所有请求最终成功完成（5 个都返回非空字符串）
- 同一时刻最多有 2 个请求在处理（由 `asyncio.Semaphore(2)` 控制）
- 超过并发限制的请求排队等待
- 不会因并发超限而报错

### 2.3 Chat 调用与 Token 统计

**前置条件：** LLM 服务正常

**操作：**
```python
# 清空统计或记录初始值
initial_usage = llm_manager.get_token_usage()

response = await llm_manager.chat([
    {"role": "system", "content": "你是市场分析师"},
    {"role": "user", "content": "分析A股走势"},
])

final_usage = llm_manager.get_token_usage()
```

**预期结果：**
- `response` 为非空字符串
- `final_usage["total_tokens"] > initial_usage["total_tokens"]`
- `final_usage["prompt_tokens"] > 0`（system + user 消息的 token 数）
- `final_usage["completion_tokens"] > 0`（响应的 token 数）

### 2.4 流式 Chat

**操作：**
```python
chunks = []
async for chunk in llm_manager.chat_stream([
    {"role": "user", "content": "hello"}
]):
    chunks.append(chunk)
full_text = "".join(chunks)
```

**预期结果：**
- `chunks` 非空列表
- `full_text` 与同步 `chat()` 调用返回内容一致（内容层面）

### 2.5 Embedding 调用

**前置条件：** 配置了独立的 `embedding_provider`（如 `openai`）

**操作：**
```python
embeddings = await llm_manager.embedding(
    texts=["股票A涨停", "股票B跌停"],
    model="text-embedding-3-small",
)
```

**预期结果：**
- `len(embeddings)` = 2
- 每个 `embeddings[i]` 为 `List[float]`
- Embedding 维度取决于模型（如 1536）
- 使用独立的 `_embedding_client` 而非主 `_client`

### 2.6 未初始化时调用

**前置条件：** `llm_manager` 未调用 `initialize()`

**操作：** 调用 `await llm_manager.chat([{"role": "user", "content": "hi"}])`

**预期结果：**
- `_ensure_initialized()` 抛出异常
- 错误信息提示 LLM manager 未初始化

### 2.7 健康检查

**操作：**
```python
healthy = await llm_manager.health_check()
```

**预期结果：**
- 初始化后 LLM 服务正常：返回 `True`
- 未初始化：返回 `False`
- LLM API 不可达：返回 `False`（不抛异常）

---

## 三、AnalysisManager 测试用例

### 3.1 情绪/强度双评分计算验证

**前置条件：**
- 构造测试 `stats` 数据（模拟正常市场）：

```python
stats = {
    "trade_date": "20250620",
    "max_limit_height": 6,
    "limit_up_count": 80,
    "limit_down_count": 5,
    "seal_rate": 85.0,
    "cont_board_count": 25,
    "promotion_rate": 55.0,
    "total_amount": 1.2 * 10**12,  # 1.2万亿（千元单位）
    "up_ratio": 55.0,
    "pct_chg_median": 0.35,
    "up_5pct_count": 120,
    "down_5pct_count": 30,
    "index_pct_chg": 0.5,
}
```

- MA10 基准为正常范围（各因子均值接近上述值）

**操作：**
```python
sentiment_core, sent_detail = analysis_manager.calculate_sentiment_core_v2(stats, baseline)
strength_core, stren_detail = analysis_manager.calculate_strength_core_v2(stats, baseline)
```

**预期结果：**
- `sentiment_core`: 40~70 之间的浮点数（连板高度 6 板 + 晋级率 55% 应得较高分）
- `strength_core`: 40~70 之间的浮点数
- `sent_detail` 包含 5 个因子得分（`height_score`, `promo_rate_score`, `cont_board_score`, `seal_rate_score`, `limit_down_score`）
- `stren_detail` 包含 4 个因子得分（`up_ratio_score`, `median_score`, `amount_score`, `up5_down5_score`）
- 连板高度 ≥ 5 时 `height_score` 达到 25 满分
- 上涨家数 55%（>30%）不触发底仓约束

### 3.2 连板高度 ≤ 2 时的底仓约束

**前置条件：**
```python
stats["max_limit_height"] = 2
stats["promotion_rate"] = 20.0
```

**操作：** 计算情绪核心分

**预期结果：**
- `core_score` ≤ 40（触发 `cap_reason = "height<=2"`）
- `height_score` = 0（绝对阈值：≤2 板 = 0 分）
- 即使其他因子得分高，总分也被封顶在 40

### 3.3 上涨家数 ≤ 30% 时的底仓约束

**前置条件：**
```python
stats["up_ratio"] = 25.0  # < 30%
```

**操作：** 计算强度核心分

**预期结果：**
- `core_score` ≤ 40（触发 `cap_reason = "up_ratio<=30%"`）
- `up_ratio_score` = 0（绝对阈值：< 30% = 0 分）

### 3.4 趋势分计算

**前置条件：**
- 今日核心分 = 60
- 前日核心分 = 50

**操作：**
```python
trend_score, trend_direction = analysis_manager.calculate_trend_score(60, 50)
```

**预期结果：**
- `trend_ratio = (60 - 50) / 50 = 0.20 = 20%`
- 20% ≥ 15%（`strong_up` 阈值） → `trend_score = 30`
- `trend_direction = "up"`

**更多边界条件：**

| 今日 | 前日 | 趋势比例 | 预期得分 | 预期方向 |
|---|---|---|---|---|
| 60 | 55 | +9.1% | 10（mild_up） | "up" |
| 60 | 58 | +3.4% | 5（flat） | "flat" |
| 50 | 60 | -16.7% | 0（strong_down） | "down" |
| 60 | None | N/A | 15 | "flat" |

### 3.5 3 日 EMA 平滑

**操作：**
```python
smoothed = analysis_manager.apply_3day_ema(
    today=65.0,  # 当日核心分
    day1=58.0,   # 昨日核心分
    day2=52.0,   # 前日核心分
)
```

**预期结果：**
```
smoothed = 0.6 * 65.0 + 0.3 * 58.0 + 0.1 * 52.0 = 39.0 + 17.4 + 5.2 = 61.6
(再除以 total_weights: (0.6+0.3+0.1) = 1.0，乘回总权重 1.0)
```

实际公式：
```
smoothed = (65*0.6 + 58*0.3 + 52*0.1) / (0.6+0.3+0.1) * (0.6+0.3+0.1)
         = 61.6 / 1.0 * 1.0 = 61.6
```

**缺少历史数据时：**
```
apply_3day_ema(today=65, day1=None, day2=None)
= (65*0.6) / 0.6 * 1.0 = 65.0  (仅用当日数据)
```

### 3.6 5 日 EMA 强平滑

**操作：**
```python
smoothed = analysis_manager.apply_5day_ema([
    65.0,  # 今日
    60.0,  # 昨日
    58.0,  # 前日
    55.0,  # 大前日
    50.0,  # 大大前日
])
```

**预期结果：**
```
= (65*0.30 + 60*0.25 + 58*0.20 + 55*0.15 + 50*0.10) / (0.30+0.25+0.20+0.15+0.10) * 1.0
= (19.5 + 15.0 + 11.6 + 8.25 + 5.0) / 1.0 * 1.0
= 59.35
```

### 3.7 周期判定边界条件

#### 3.7.1 主升期

**前置条件：**
```python
sentiment_trend = "up"
strength_trend = "up"
sentiment_score = 75.0
strength_score = 80.0
```

**操作：** `analysis_manager.identify_cycle_by_trends("up", "up", 75, 80)`

**预期结果：** `(MarketCycle.MAIN_UPWARD, "双趋势向上")`

#### 3.7.2 分歧期（趋势背离）

**前置条件：**
```python
sentiment_trend = "up"
strength_trend = "down"
```

**预期结果：** `(MarketCycle.DIVERGENCE, "趋势背离(情绪up/强度down)")`

#### 3.7.3 退潮期

**前置条件：** `("down", "down", 35, 35)`

**预期结果：** `(MarketCycle.DECLINE, "双趋势向下")`

#### 3.7.4 冰点期

**前置条件：** `("flat", "flat", 15, 15)` 或 `("down", "down", 15, 15)`

**预期结果：** `(MarketCycle.ICE_POINT, "双分极低(<20)")`

#### 3.7.5 修复期

**前置条件：** `("up", "flat", 35, 30)` — 双低但情绪有止跌

**预期结果：** `(MarketCycle.RECOVERY, "双低(<40)但有止跌")`

#### 3.7.6 混沌期

**前置条件：** `("flat", "flat", 50, 55)` — 趋势不明确

**预期结果：** `(MarketCycle.CHAOS, "趋势不明确")`

### 3.8 3 日趋势方向判定

| 今日 | 昨日 | 前日 | 预期 |
|---|---|---|---|
| 65 | 60 | 55 | "up"（连续递增） |
| 55 | 60 | 65 | "down"（连续递减） |
| 65 | 55 | 60 | "flat"（不是连续递增） |
| 65 | 60 | None | "flat"（数据不足） |
| 65 | None | None | "flat"（数据不足） |

### 3.9 MA10 基准缓存行为

**操作：**
1. 第一次调用 `load_ma10_baseline("20250620", mongo_manager)` → 从 MongoDB 加载
2. 第二次调用同一参数 → 直接从 LRU 缓存返回
3. 插入超过 256 条新缓存 → 最旧的条目被逐出

**验证方式：** 第二次调用不发起 MongoDB 查询（可通过 mock 验证 `find_many` 调用次数）。

### 3.10 analyze_and_store 端到端验证

**前置条件：**
- `daily_stats` 中存在足够多历史数据（≥10 天，用于 MA10 基准）
- `market_analysis` 中存在近 5 日分析记录

**操作：**
```python
result = await analysis_manager.analyze_and_store(
    stats=stats,
    prev_stats=prev_stats,
    mongo_manager=mongo_manager,
)
```

**预期结果：**
- `result["trade_date"]` = 传入的 `trade_date`
- `result["sentiment_score"]` 在 0-100 之间
- `result["strength_score"]` 在 0-100 之间
- `result["cycle"]` 为七种有效枚举值之一
- `result["sentiment_trend_3d"]` 为 "up" / "down" / "flat"
- `result["strength_trend_3d"]` 为 "up" / "down" / "flat"
- `result["position_advice"]` 包含 `level` 和 `range` 字段
- `result["baseline_data_count"]` > 0
- MongoDB `market_analysis` 集合中已写入对应记录（可通过 `find_one` 验证）
- 强弱差仅在 ≥15 且趋势方向相反且均非 flat 时有效（`strength_diff` > 0）

### 3.11 数据不足时的降级

**前置条件：**
- `daily_stats` 中无任何历史数据（全新部署）

**操作：** 调用 `analyze_and_store`

**预期结果：**
- `baseline_data_count` = 0
- 核心分计算中的相对分值给 50%（`_calc_relative_score` 返回 `max_score * 0.5`）
- 最终评分仍在 0-100 合理范围内
- `cycle` 可能为 `"unknown"`
- 不抛异常，正常写入 `market_analysis`

---

## 代码走查验证结果

**走查日期**: 2026-06-21 | **方法**: 代码走查 | **结果**: 21/21 通过

| 用例 | 结果 | 走查依据 |
|------|------|----------|
| 1.1 | ✅ PASS | `_get_with_fallback` (data_source_manager.py:597-836): 按适配器链顺序尝试，第一个返回非空数据即返回，不尝试后续源 |
| 1.2 | ✅ PASS | TimeoutError 处理 (line 734-744): `status="timeout"` → 继续下一个源。`attempted_sources` 追踪所有尝试的源 |
| 1.3 | ✅ PASS | 所有源都失败且非 empty → `DataSourceChainError` (line 834)，含 method_name/outcomes/source_chain |
| 1.4 | ✅ PASS | 所有源返回 empty → 返回 `(None, None)` (line 836)，不抛异常。outcome status 为 "empty" |
| 1.5 | ✅ PASS | `_cool_down_source` (line 544): 设置 cooldown_until。`_get_source_cooldown_remaining` (line 554): 检查冷却期。冷却结束后自动恢复。TokenBucket 在 `_wait_for_source_budget` 中 |
| 1.6 | ✅ PASS | `_get_configured_source_chain` (line 462-515): 解析 `DATASYNC_SOURCE_CHAIN_OVERRIDES`，返回 override_chain=True。非 override 时自动追加剩余源 |
| 1.7 | ✅ PASS | `get_daily` (line 161-245): 根据是否传入 ts_code 选择 `get_daily.single` 或 `get_daily.full_market` 链键。single 链 coze 优先，full_market 链 tushare 优先 |
| 1.8 | ✅ PASS | `initialize()` (line 348-372): adapter 初始化失败 → `shutdown()` + WARNING 日志，不阻断整体。`_adapters` 仅包含成功初始化的适配器 |
| 1.9 | ✅ PASS | `get_call_stats_summary()` (line 837-927): entries/core_entries/degraded_entries 统计，`reset_call_stats()` 重置 |
| 2.1 | ✅ PASS | LLMManager 支持 deepseek/openai/ollama/zhipu/dashscope 等 provider |
| 2.2 | ✅ PASS | `asyncio.Semaphore(max_concurrent_requests)` 控制并发请求数 |
| 2.3 | ✅ PASS | `chat()` 方法支持 system/user 消息，`get_token_usage()` 返回 prompt/completion/total tokens |
| 2.4 | ✅ PASS | `chat_stream()` 方法支持异步生成器流式输出 |
| 2.5 | ✅ PASS | `embedding()` 方法使用独立 `_embedding_client`，支持批量文本嵌入 |
| 2.6 | ✅ PASS | `_ensure_initialized()` 在未初始化时抛出异常 |
| 2.7 | ✅ PASS | `health_check()` 初始化后 ping 检测，未初始化返回 False |
| 3.1-3.9 | ✅ PASS | `calculate_sentiment_core_v2` (analysis_manager.py:357-451): 5 因子加权 + 绝对阈值约束 + 底仓封顶。`calculate_strength_core_v2` (line 474-571): 4 因子 + 绝对阈值。`calculate_trend_score` (line 573-605): ±10%/±15% 分档。`apply_3day_ema` (line 607-633): 0.6/0.3/0.1 权重。`apply_5day_ema` (line 635-666): 0.30/0.25/0.20/0.15/0.10 权重。`identify_cycle_by_trends` (line 691-735): 双趋势组合 7 周期判定 |
| 3.10 | ✅ PASS | `analyze_and_store` (line 1234-1432): 加载 MA10 基准 → 核心分 → 3日EMA → 趋势分 → 5日EMA → 双趋势 → 周期 → 仓位。upsert=True 写入 market_analysis (line 1425-1430) |
| 3.11 | ✅ PASS | 无历史数据时 baseline_data_count=0，`_calc_relative_score` avg=None → `max_score*0.5` (line 346)。cycle 可能为 unknown。不抛异常 |
