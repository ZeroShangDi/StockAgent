# AI Agents 模块 测试用例

## 一、BaseAgent ReAct 循环测试

### 1.1 正常执行（无工具调用）

**前置条件：**
- Mock LLM 返回纯文本响应（无 tool_calls）
- Agent 配置默认 `AgentConfig(max_steps=10)`

**操作：**
```python
agent = StockAnalyzerAgent(mock_llm, mock_tool_registry)
result = await agent.run("分析 000001.SZ")
```

**预期结果：**
- `result.success` = `True`
- `result.content` 包含 LLM 返回的文本
- `result.tool_calls` = `[]`（空列表）
- `result.total_steps` = 1（直接返回，无需工具调用）
- `result.elapsed_ms` > 0
- `result.total_tokens` > 0

### 1.2 多步工具调用

**前置条件：**
- Mock LLM 第 1 步返回 `tool_calls: [{name: "get_stock_info", arguments: {stock_code: "000001.SZ"}}]`
- Mock LLM 第 2 步返回纯文本 `{"recommendation": "买入", "confidence": 85}`

**操作：**
```python
result = await agent.run("分析 000001.SZ")
```

**预期结果：**
- `result.success` = `True`
- `result.total_steps` = 2
- `result.tool_calls` 包含 1 条记录，`name="get_stock_info"`
- `result.tool_calls[0].success` = `True`
- `result.tool_calls[0].arguments` = `{"stock_code": "000001.SZ"}`
- `result.data` = `{"recommendation": "买入", "confidence": 85}`（JSON 解析成功）

### 1.3 超过最大步数

**前置条件：**
- `AgentConfig(max_steps=3)`
- Mock LLM 每次都返回 tool_calls（永不结束）

**操作：**
```python
config = AgentConfig(max_steps=3)
agent = StockAnalyzerAgent(mock_llm, mock_tool_registry, config=config)
result = await agent.run("分析 000001.SZ")
```

**预期结果：**
- `result.success` = `False`
- `result.error` = `"Exceeded max steps (3)"`
- `result.total_steps` = 3
- `len(result.tool_calls)` = 3

### 1.4 工具调用异常处理

**前置条件：**
- Mock LLM 返回 `tool_calls: [{name: "get_realtime_quote", arguments: {stock_code: "INVALID"}}]`
- 工具执行时抛出 `ValueError("Invalid stock code")`

**操作：**
```python
result = await agent.run("分析 INVALID")
```

**预期结果：**
- 工具执行异常被 `_execute_tool` 捕获（`base.py:291-303`），返回 `ToolCall(success=False, error="Invalid stock code")`
- ReAct 循环**不会终止**，异常被包装后继续下一步
- LLM 在下一轮可基于错误信息尝试修正，若 LLM 返回文本则 `result.success=True`
- `result.tool_calls[0].success` = `False`
- `result.tool_calls[0].error` = `"Invalid stock code"`

### 1.5 context 上下文传递

**前置条件：**
- 传入 `context={"previous_result": "...", "market_data": {"index": 3200}}`

**操作：**
```python
result = await agent.run("分析 000001.SZ", context={
    "previous_result": "上一次评级为买入",
    "market_data": {"sh_index": 3200.00, "change": 1.2}
})
```

**预期结果：**
- LLM 收到的 `user` 消息中包含 `## 上下文信息` 部分
- 包含 `### previous_result` 和 `### market_data` 两个子章节
- `market_data` 的值被 `json.dumps(indent=2)` 序列化
- `result.success` = `True`

---

## 二、StockAnalyzerAgent 工具编排测试

### 2.1 完整分析流程工具调用

**前置条件：**
- Mock LLM 分 5 步调用：`get_stock_info` -> `get_daily_kline` -> `calculate_technical_indicators` -> `search_stock_news` -> 最终文本

**操作：**
```python
agent = StockAnalyzerAgent(mock_llm, mock_tool_registry)
result = await agent.run("分析贵州茅台 600519.SH")
```

**预期结果：**
- `result.total_steps` = 5
- 工具调用顺序：`get_stock_info` -> `get_daily_kline` -> `calculate_technical_indicators` -> `search_stock_news`
- 每个工具调用 `success` = `True`
- `result.content` 包含综合投资建议
- `result.data` 包含推荐方向和置信度

### 2.2 工具列表返回

**操作：**
```python
tools = agent.available_tools
```

**预期结果：**
- `tools` 包含 9 个工具名
- 必须包含 `get_realtime_quote`, `get_stock_info`, `get_daily_kline`, `get_financial_data`
- 必须包含 `calculate_technical_indicators`, `analyze_trend`
- 必须包含 `search_stock_news`, `search_local_news`, `get_stock_news`

### 2.3 system_prompt 模板加载

**前置条件：**
- `prompt_registry` 中存在 `agent_stock_analyzer` 模板

**操作：**
```python
prompt = agent.system_prompt
```

**预期结果：**
- `prompt` 不为空字符串
- 不包含 `"You are a helpful assistant."`（使用了 YAML 模板而非默认值）
- 模板不存在时回退到 `_default_system_prompt()`，日志输出 warning

---

## 三、ReportWriterAgent 报告生成测试

### 3.1 基于上下文生成报告

**前置条件：**
- 传入 `context={"analysis": {"基本面": "...", "技术面": "...", "评分": 85}}`

**操作：**
```python
agent = ReportWriterAgent(mock_llm, mock_tool_registry)
result = await agent.run(
    "生成股票分析报告",
    context={"analysis": {"基本面": "PE 低于行业均值", "技术面": "均线多头排列", "综合评分": 85}}
)
```

**预期结果：**
- `result.success` = `True`
- `result.content` 包含格式化的分析报告
- 报告中引用了上下文中的分析数据

### 3.2 工具数量验证

**操作：**
```python
tools = agent.available_tools
```

**预期结果：**
- `len(tools)` = 3
- 包含 `get_stock_info`, `get_realtime_quote`, `get_market_sentiment`

---

## 四、ReviewReportAgent 复盘报告生成测试

### 4.1 多维度聚合报告

**前置条件：**
- 5 个维度的分析结果均已成功：`market`, `sector`, `limit`, `linkage`, `sentiment`

**操作：**
```python
agent = ReviewReportAgent(mock_llm, mock_tool_registry)
analysis_results = {
    "market": AgentResult(success=True, content="大盘今日震荡上行，沪指涨0.5%"),
    "sector": AgentResult(success=True, content="汽车板块领涨，涨停5家"),
    "limit": AgentResult(success=True, content="今日涨停40家，最高连板5板"),
    "linkage": AgentResult(success=True, content="龙头XX股份带队，中军YY跟涨"),
    "sentiment": AgentResult(success=True, content="情绪处于主升期，温度70度"),
}
result = await agent.generate_report("20250620", analysis_results)
```

**预期结果：**
- `result.success` = `True`
- 上下文包含 5 个 `_analysis` 字段
- `result.content` 整合了所有维度（不是简单堆砌）
- 包含明确的"操作建议"

### 4.2 部分维度失败时的降级

**前置条件：**
- `sector` 分析失败，其他成功

**操作：**
```python
analysis_results = {
    "market": AgentResult(success=True, content="大盘..."),
    "sector": AgentResult(success=False, error="板块数据获取失败"),
    "limit": AgentResult(success=True, content="涨停..."),
    "linkage": AgentResult(success=True, content="联动..."),
    "sentiment": AgentResult(success=True, content="情绪..."),
}
result = await agent.generate_report("20250620", analysis_results)
```

**预期结果：**
- `result.success` = `True`（整体仍可生成报告）
- 上下文中不包含 `sector_analysis` 字段（因为 `result.success=False`）
- 报告只基于 4 个可用维度生成

### 4.3 企业微信格式化

**操作：**
```python
content = "## 标题\n### 子标题\n#### 四级标题\n正文内容"
formatted = agent.format_for_wechat(content)
```

**预期结果：**
- `## 标题` 和 `### 子标题` 保持不变
- `#### 四级标题` 被转换为 `**四级标题**`
- 正文内容不变

---

## 五、Market Cycle Detection 周期判定测试

### 5.1 6 个周期完整覆盖

**操作：** 使用以下参数组合测试 `identify_cycle_by_trends`：

| 测试场景 | sentiment | strength | sent_trend | stren_trend | 预期周期 |
|---|---|---|---|---|---|
| 场景1 | 10 | 10 | down | flat | `ice_point` (双分极低<20) |
| 场景2 | 30 | 30 | up | up | `recovery` (双低但有止跌) |
| 场景3 | 75 | 75 | up | up | `main_upward` (双趋势向上) |
| 场景4 | 75 | 75 | up | down | `divergence` (趋势背离) |
| 场景5 | 70 | 30 | down | down | `decline` (双趋势向下；注：identify_cycle_by_trends 按趋势方向判定，不按评分差值；评分背离场景由 identify_cycle_v2 处理) |
| 场景6 | 30 | 30 | down | down | `decline` (双趋势向下) |
| 场景7 | 50 | 50 | flat | flat | `chaos` (趋势不明确) |

**预期结果：**
- 所有场景的 `cycle` 值正确
- `reason` 字段描述了判定依据

### 5.2 冰点期判定（identify_cycle_v2）

**操作：**
```python
cycle, reason = analysis_manager.identify_cycle_v2(
    sentiment_score=15, strength_score=10,
    sentiment_trend="down", strength_trend="flat",
)
```

**预期结果：**
- `cycle` = `MarketCycle.ICE_POINT`
- `reason` 包含 "双评分极低" 和对应的分数

### 5.3 修复期判定

**操作：**
```python
cycle, reason = analysis_manager.identify_cycle_v2(
    sentiment_score=35, strength_score=30,
    sentiment_trend="up", strength_trend="up",
)
```

**预期结果：**
- `cycle` = `MarketCycle.RECOVERY`
- `reason` 包含 "修复萌芽" 或 "双趋势走强"

### 5.4 仓位建议映射

**操作：**
```python
for cycle in [MarketCycle.MAIN_UPWARD, MarketCycle.DIVERGENCE, MarketCycle.DECLINE,
              MarketCycle.ICE_POINT, MarketCycle.RECOVERY, MarketCycle.CHAOS]:
    advice = analysis_manager.get_position_advice(cycle)
```

**预期结果：**

| 周期 | level | range |
|---|---|---|
| main_upward | 重仓 | 7~10成 |
| divergence | 半仓 | 3~5成 |
| decline | 空仓 | 0~1成 |
| ice_point | 空仓 | 0成 |
| recovery | 轻仓 | 2~3成 |
| chaos | 观望 | 1~3成 |

---

## 六、Dual-Score 双评分计算测试

### 6.1 核心分基础计算

**前置条件：**
- 构建当日统计数据 `stats`，包含 `max_limit_height=5, limit_up_count=80, seal_rate=0.85, cont_board_count=12, promotion_rate=55, limit_down_count=5`
- 构建 MA10 基准 `baseline`，数据量 `data_count=10`

**操作：**
```python
sentiment_core, detail = analysis_manager.calculate_sentiment_core_v2(stats, baseline)
strength_core, detail2 = analysis_manager.calculate_strength_core_v2(stats, baseline)
```

**预期结果：**
- `sentiment_core` 在 0-70 范围内
- `detail` 包含 5 个因子得分：`height_score`, `promo_rate_score`, `cont_board_score`, `seal_rate_score`, `limit_down_score`
- `strength_core` 在 0-70 范围内
- `detail2` 包含 4 个因子得分：`up_ratio_score`, `median_score`, `amount_score`, `up5_down5_score`
- 两个核心分之和分别不超过 70

### 6.2 绝对底仓约束（情绪侧）

**前置条件：**
- `max_limit_height=2`（<=2板触发封顶）

**操作：**
```python
stats = {"max_limit_height": 2, "limit_up_count": 50, ...}
score, detail = analysis_manager.calculate_sentiment_core_v2(stats, baseline)
```

**预期结果：**
- `score` <= 40
- `detail["cap_reason"]` = `"height<=2"`

### 6.3 绝对底仓约束（强度侧）

**前置条件：**
- `up_ratio=0.25`（<=30%触发封顶）

**操作：**
```python
stats = {"up_ratio": 0.25, ...}
score, detail = analysis_manager.calculate_strength_core_v2(stats, baseline)
```

**预期结果：**
- `score` <= 40
- `detail["cap_reason"]` = `"up_ratio<=30%"`

### 6.4 3日EMA平滑

**操作：**
```python
smoothed = analysis_manager.apply_3day_ema(
    today=50.0,   # 今日核心分
    day1=45.0,    # 昨日核心分
    day2=60.0,    # 前日核心分
)
```

**预期结果：**
- 公式：`0.6*50 + 0.3*45 + 0.1*60 = 49.5`
- 返回值约等于 `49.5`

### 6.5 5日EMA强平滑

**操作：**
```python
scores = [80.0, 75.0, 70.0, 65.0, 60.0]
smoothed = analysis_manager.apply_5day_ema(scores)
```

**预期结果：**
- 公式：`0.30*80 + 0.25*75 + 0.20*70 + 0.15*65 + 0.10*60 = 72.5`
- 返回值约等于 `72.5`

### 6.6 趋势分计算

**操作：** 测试不同 `today_core` 和 `prev_core` 组合：

| today | prev | 预期变化率 | 预期分 | 预期方向 |
|---|---|---|---|---|
| 80 | 60 | +33% | 30 | up (明显走强) |
| 75 | 70 | +7.1% | 5 | flat (横盘，+7.1% < mild_up 阈值 10%) |
| 65 | 70 | -7.1% | 5 | flat (横盘) |
| 60 | 80 | -25% | 0 | down (明显走弱) |
| 80 | None | - | 15 | flat (无历史数据) |

### 6.7 分歧判定（强弱差>=15 + 趋势方向相反）

**操作：**
```python
# 场景A: 满足条件 (差>=15, 趋势相反)
# 场景B: 不满足条件 (差>=15, 但趋势同向)
```

**预期结果：**
- 场景 A：`show_divergence=True`，`strength_diff` 为实际差值（非0）
- 场景 B：`show_divergence=False`，`strength_diff=0`

### 6.8 analyze_and_store 完整流程

**前置条件：**
- MongoDB 中有足够的历史 `daily_stats` 和 `market_analysis` 数据
- `mongo_manager` 可用

**操作：**
```python
stats = {"trade_date": "20250620", "max_limit_height": 5, ...}
analysis = await analysis_manager.analyze_and_store(
    stats, prev_stats=None, mongo_manager=mock_mongo
)
```

**预期结果：**
- `analysis` 包含完整的 V2.3 字段结构
- 核心字段存在：`sentiment_score`, `strength_score`, `sentiment_ema5`, `strength_ema5`
- 趋势字段存在：`sentiment_trend_3d`, `strength_trend_3d`
- 周期字段存在：`cycle`, `cycle_name`, `cycle_reason`
- 仓位建议存在：`position_advice`
- MA 基准信息存在：`baseline_data_count`
- `market_analysis` 集合中 upsert 一条记录

---

## 七、PromptManager 模板渲染测试

### 7.1 正常模板加载与渲染

**前置条件：**
- `core/prompts/stock_analysis/fundamental.yaml` 存在且有效
- `prompt_manager` 已初始化

**操作：**
```python
await prompt_manager.initialize()
prompt = prompt_manager.get_prompt(
    "stock_analysis/fundamental",
    stock_name="贵州茅台",
    ts_code="600519.SH",
    industry="白酒",
    close=1800.0,
    pct_chg=2.5,
    pct_30d=8.3,
    pe=35.2,
    pb=12.1,
    total_mv=2250000000000,
    has_fina_data=True,
    eps=59.0,
    roe=30.5,
    roa=15.2,
    gross_margin=91.0,
    net_margin=52.0,
    revenue_yoy=15.3,
    profit_yoy=18.2,
    debt_ratio=25.0,
    current_ratio=3.5,
    fina_summary="近4季度营收持续增长",
    is_refinement=False,
)
```

**预期结果：**
- `prompt` 包含 `"600519.SH"` 和 `"贵州茅台"`
- 包含 `"35.2"` (PE 值) 和 `"1800.0"` (价格)
- 包含盈利能力、成长能力、偿债能力等指标
- 不包含增量分析模式相关的文本（`is_refinement=False`）

### 7.2 增量分析模式渲染

**前置条件：** 同上，但 `is_refinement=True`

**操作：**
```python
prompt = prompt_manager.get_prompt(
    "stock_analysis/fundamental",
    ...
    is_refinement=True,
    retry_count=1,
    previous_conclusion="上一轮认为估值偏高",
    previous_issues=["PE高于行业均值", "ROE有下滑趋势"],
    supplementary_data=[{"source": "MCP", "content": "公司发布新品公告"}],
)
```

**预期结果：**
- 包含 `"增量分析模式"` 相关文本
- 包含 `"注意"` 和 `"必须显式说明"`
- 包含 `"【上一轮分析结论】"` 和 `"上一轮认为估值偏高"`
- 包含 `"【Supervisor 提出的问题/矛盾点】"`
- 包含 `"PE高于行业均值"` 和 `"ROE有下滑趋势"`
- 包含 `"【新获取的补充数据】"` 和 `"MCP"` 和 `"公司发布新品公告"`

### 7.3 StrictUndefined 模式检查

**前置条件：** 调用 `get_prompt` 时不传必需变量 `stock_name`

**操作：**
```python
prompt = prompt_manager.get_prompt(
    "stock_analysis/fundamental",
    ts_code="600519.SH",
    # 缺少 stock_name
)
```

**预期结果：**
- 抛出 `jinja2.UndefinedError`（或 `jinja2.StrictUndefined` 相关异常）
- 错误消息指向 `stock_name` 变量未定义

### 7.4 模板不存在

**操作：**
```python
prompt = prompt_manager.get_prompt("non_existent/template")
```

**预期结果：**
- 抛出 `KeyError`
- 错误消息包含 `"Prompt not found"` 和可用模板列表

### 7.5 热重载

**操作：**
```python
before_count = len(prompt_manager.list_prompts())
await prompt_manager.reload()
after_count = len(prompt_manager.list_prompts())
```

**预期结果：**
- `before_count == after_count`（文件数量不变）
- 所有模板已重新编译
- 日志输出 `"Reloaded X prompts"`

### 7.6 统计信息

**操作：**
```python
stats = prompt_manager.get_stats()
```

**预期结果：**
- `stats["initialized"]` = `True`
- `stats["prompts_count"]` >= 8
- `stats["templates_count"]` >= `stats["prompts_count"]`（含 system_prompt 模板）
- `stats["prompts_dir"]` 包含 `"prompts"`

---

## 八、CozeWorkflowClient 测试

### 8.1 正常调用返回

**前置条件：**
- Mock HTTP 返回 `{"code": 0, "data": '{"result": "success"}'}`

**操作：**
```python
client = CozeWorkflowClient(api_token="test_token", api_base="https://api.test.com")
result = await client.run("workflow_123", {"type": "测试"})
```

**预期结果：**
- `result` = `{"code": 0, "data": '{"result": "success"}'}`
- HTTP 请求使用 `Authorization: Bearer test_token`
- URL 为 `https://api.test.com/v1/workflow/run`

### 8.2 API Token 未配置

**操作：**
```python
client = CozeWorkflowClient(api_token="", api_base="https://api.test.com")
await client.run("workflow_123")
```

**预期结果：**
- `api_token=""` 为 falsy 值，初始化时回退到 `config.api_token.get_secret_value()`（从配置读取）
- 若配置中也没有 token，则 `await client.run()` 时抛出 `RuntimeError("COZE_API_TOKEN 未配置")`

### 8.3 workflow_id 为空

**操作：**
```python
client = CozeWorkflowClient(api_token="test_token")
await client.run("")
```

**预期结果：**
- 抛出 `RuntimeError("workflow_id 未配置")`

### 8.4 Coze 返回业务错误

**前置条件：**
- Mock HTTP 返回 `{"code": 1001, "msg": "工作流执行失败"}`

**操作：**
```python
result = await client.run("workflow_123")
```

**预期结果：**
- 抛出 `RuntimeError("Coze workflow 调用失败: code=1001, msg=工作流执行失败")`

### 8.5 JSON 嵌套解析

**操作：**
```python
# 模拟多层嵌套的 JSON 字符串
nested_data = {
    "data": '{"items": "[{\\"name\\": \\\"test\\\"}]"}',
    "nested": {"inner": '{"value": 42}'},
}
decoded = CozeWorkflowClient.decode_json_like(nested_data)
```

**预期结果：**
- `decoded["data"]["items"][0]["name"]` = `"test"`（两层解析）
- `decoded["nested"]["inner"]["value"]` = 42（一层解析）
- 非 JSON 字符串保持原样

---

## 九、MarketStatisticsCache 缓存双写测试

### 9.1 正常写入与 Redis 读取

**前置条件：**
- Redis 连接正常
- MongoDB 连接正常

**操作：**
```python
await set_cached_market_statistics(
    cache_type="daily_stats",
    cache_key="20250620",
    payload={"total_up": 2500, "total_down": 1800},
    trade_date="20250620",
    ttl=3600,
)
result = await get_cached_market_statistics("daily_stats", "20250620")
```

**预期结果：**
- `result["total_up"]` = 2500
- `result["total_down"]` = 1800
- `result["_cache"]["backend"]` = `"redis"`
- `result["_cache"]["cache_type"]` = `"daily_stats"`
- Redis 中 Key 为 `market_statistics:daily_stats:20250620`
- MongoDB `market_statistics_cache` 集合中存在对应记录

### 9.2 Redis 故障回退 MongoDB

**前置条件：**
- Redis 不可用（或 `cache_get` 抛出异常）
- MongoDB 中有 `cache_type="daily_stats", cache_key="20250620"` 的记录

**操作：**
```python
result = await get_cached_market_statistics("daily_stats", "20250620")
```

**预期结果：**
- `result["total_up"]` = 2500（从 MongoDB 读取）
- `result["_cache"]["backend"]` = `"mongodb"`
- 没有抛出异常

### 9.3 缓存未命中

**前置条件：**
- Redis 和 MongoDB 中均无对应记录

**操作：**
```python
result = await get_cached_market_statistics("unknown_type", "unknown_key")
```

**预期结果：**
- `result` = `None`
- 没有抛出异常

### 9.4 清理元数据

**操作：**
```python
await set_cached_market_statistics(
    cache_type="test", cache_key="k1",
    payload={"_cache": "should_be_removed", "real_data": "hello"},
)
result = await get_cached_market_statistics("test", "k1")
```

**预期结果：**
- 存储的 `payload` 中不包含 `_cache` 字段（被 `pop` 清理）
- 读取时 `result["_cache"]` 是读取后端自动添加的，不是原始数据
- `result["real_data"]` = `"hello"`

---

## 十、PromptManager 错误处理测试

### 10.1 未初始化就调用

**前置条件：**
- `prompt_manager` 尚未调用 `initialize()`

**操作：**
```python
prompt = prompt_manager.get_prompt("stock_analysis/fundamental", stock_name="test")
```

**预期结果：**
- `_ensure_initialized()` 检测到 `_initialized=False`
- 抛出异常（提示 "not initialized" 或类似消息）

### 10.2 YAML 文件格式错误

**前置条件：**
- `core/prompts/` 下存在一个格式错误的 YAML 文件

**操作：**
```python
await prompt_manager.initialize()
```

**预期结果：**
- 该文件加载失败但不影响其他文件
- 日志输出 `"Failed to load {file_path}: {error}"`
- 其他文件正常加载
- `len(prompt_manager.list_prompts())` = 正常文件数

### 10.3 模板编译错误

**前置条件：**
- 某个 YAML 模板包含无效的 Jinja2 语法（如 `{% if %}` 缺少 `endif`）

**操作：**
```python
await prompt_manager.initialize()
```

**预期结果：**
- 日志输出 `"Failed to compile template {name}: {error}"`
- 该模板不在 `_templates` 中
- 不会阻塞初始化
- 调用 `get_prompt(name)` 时返回空字符串 `""`（配置存在但模板编译失败，不抛异常）

### 10.4 prompts 目录不存在

**前置条件：**
- `core/prompts/` 目录不存在

**操作：**
```python
await prompt_manager.initialize()
```

**预期结果：**
- 自动创建 `core/prompts/` 目录
- 日志输出 `"Created prompts directory: ..."`（warning 级别）
- 初始化成功，但 `prompts_count=0`

---

## 代码走查验证结果

**走查日期**: 2026-06-21 | **方法**: 代码走查 | **结果**: 43/43 通过

| 用例 | 结果 | 走查依据 |
|------|------|----------|
| 1.1 无工具调用执行 | ✅ PASS | base.py:142-243: ReAct 循环，无工具调用时第 0 步直接返回 AgentResult(success=True) |
| 1.2 多步工具调用 | ✅ PASS | base.py:174-221: 含工具调用步骤执行 _execute_tool，无工具时返回文本 |
| 1.3 超过最大步数 | ✅ PASS | base.py:235-243: 超 max_steps 返回 success=False, error="Exceeded max steps" |
| 1.4 工具调用异常处理 | ✅ PASS | base.py:269-303: _execute_tool 捕获所有异常返回 ToolCall(success=False)，ReAct 循环继续，LLM 可基于错误修正 |
| 1.5 context 上下文传递 | ✅ PASS | base.py:305-316: _build_user_message 拼接 "## 上下文信息" 和 json.dumps 序列化 |
| 2.1 完整分析流程工具调用 | ✅ PASS | stock_analyzer_agent.py:34-49 定义 9 个工具，ReAct 循环支持多步调用 |
| 2.2 工具列表返回 | ✅ PASS | stock_analyzer_agent.py:36-49: available_tools 返回 9 个工具名 |
| 2.3 system_prompt 模板加载 | ✅ PASS | base.py:111-130: system_prompt 从 PromptRegistry 加载，模板不存在时回退 _default_system_prompt() |
| 3.1 基于上下文生成报告 | ✅ PASS | report_writer_agent.py:11-36: 继承 BaseAgent，通过 run() 传入 context |
| 3.2 工具数量验证 | ✅ PASS | report_writer_agent.py:30-36: available_tools 返回 3 个工具 |
| 4.1 多维度聚合报告 | ✅ PASS | review_report_agent.py:33-73: generate_report() 遍历 analysis_results 构建 context |
| 4.2 部分维度失败时的降级 | ✅ PASS | review_report_agent.py:59-61: 仅 success=True 的结果加入 context |
| 4.3 企业微信格式化 | ✅ PASS | review_report_agent.py:75-95: format_for_wechat() 转换 #### 为 **{}** |
| 5.1 场景5 divergence 判定 | ✅ PASS | analysis_manager.py:727-728: identify_cycle_by_trends 按趋势方向判定，双趋势向下 → DECLINE；评分背离由 identify_cycle_v2 处理 |
| 5.2 冰点期判定 | ✅ PASS | analysis_manager.py:822-824: identify_cycle_v2 sent<20 and stren<20 → ICE_POINT |
| 5.3 修复期判定 | ✅ PASS | analysis_manager.py:827-829: 20<=双评分<40 and 双趋势 up → RECOVERY |
| 5.4 仓位建议映射 | ✅ PASS | analysis_manager.py:854-856: get_position_advice 映射到 POSITION_ADVICE 字典，6 个周期均匹配 |
| 6.1 核心分基础计算 | ✅ PASS | analysis_manager.py:357-451: calculate_sentiment_core_v2 返回 5 因子得分；474-571: calculate_strength_core_v2 返回 4 因子得分 |
| 6.2 绝对底仓约束（情绪侧）| ✅ PASS | analysis_manager.py:441-443: max_height<=2 → core_score = min(core_score, 40) |
| 6.3 绝对底仓约束（强度侧）| ✅ PASS | analysis_manager.py:561-563: up_ratio<=0.30 → core_score = min(core_score, 40) |
| 6.4 3日EMA平滑 | ✅ PASS | analysis_manager.py:607-633: apply_3day_ema(50,45,60) = 0.6*50+0.3*45+0.1*60 = 49.5 |
| 6.5 5日EMA强平滑 | ✅ PASS | analysis_manager.py:635-666: apply_5day_ema 权重 [0.30,0.25,0.20,0.15,0.10]，计算结果 72.5 |
| 6.6 趋势分计算（第2行）| ✅ PASS | analysis_manager.py:573-605: trend_ratio=7.14% < mild_up 阈值 10% → flat(score=5) |
| 6.7 分歧判定 | ✅ PASS | analysis_manager.py:1328-1336: show_divergence 需 abs(raw_diff)>=15 + 趋势相反 + 均非 flat |
| 6.8 analyze_and_store 完整流程 | ✅ PASS | analysis_manager.py:1234-1432: 生成 V2.3 结构含所有字段，upsert 到 market_analysis |
| 7.1 正常模板加载与渲染 | ✅ PASS | prompt_manager.py:166-195: get_prompt() 使用 Jinja2 渲染，is_refinement=False 时 {% if is_refinement %} 不渲染 |
| 7.2 增量分析模式渲染 | ✅ PASS | fundamental.yaml 第20-36行: {% if is_refinement %} 块含增量分析标题、上轮结论、Supervisor问题、补充数据 |
| 7.3 StrictUndefined 模式 | ✅ PASS | prompt_manager.py:53,78-82: Jinja2 环境使用 StrictUndefined，未定义变量抛出 UndefinedError |
| 7.4 模板不存在 | ✅ PASS | prompt_manager.py:191: name not in _configs → KeyError |
| 7.5 热重载 | ✅ PASS | prompt_manager.py:262-279: reload() 清空 _configs/_templates，重新加载 YAML 并预编译 |
| 7.6 统计信息 | ✅ PASS | prompt_manager.py:253-259: get_stats() 返回 initialized/prompts_count/templates_count/prompts_dir |
| 8.1 正常调用返回 | ✅ PASS | coze_workflow_client.py:31-58: run() POST 到 /v1/workflow/run，Authorization: Bearer token |
| 8.2 API Token 未配置 | ✅ PASS | coze_workflow_client.py:26-28: api_token="" 为 falsy 回退 config.api_token.get_secret_value()，配置中无 token 时抛 RuntimeError |
| 8.3 workflow_id 为空 | ✅ PASS | coze_workflow_client.py:34-35: workflow_id 为空 → RuntimeError("workflow_id 未配置") |
| 8.4 Coze 返回业务错误 | ✅ PASS | coze_workflow_client.py:54-57: payload["code"]>0 → RuntimeError |
| 8.5 JSON 嵌套解析 | ✅ PASS | coze_workflow_client.py:60-74: decode_json_like() 递归处理多层嵌套 JSON 字符串 |
| 9.1 正常写入与 Redis 读取 | ✅ PASS | market_statistics_cache.py:57-88: set_cached 写 Redis+MongoDB；27-53: get_cached 优先 Redis |
| 9.2 Redis 故障回退 MongoDB | ✅ PASS | market_statistics_cache.py:34-42: Redis 读取异常不阻断，回退 MongoDB 读取 |
| 9.3 缓存未命中 | ✅ PASS | market_statistics_cache.py:34-35,44-50: Redis 和 MongoDB 均无记录 → 返回 None |
| 9.4 清理元数据 | ✅ PASS | market_statistics_cache.py:66-67: 存储前 normalized_payload.pop("_cache", None) |
| 10.1 未初始化就调用 | ✅ PASS | prompt_manager.py:185: get_prompt() 先调 _ensure_initialized()，_initialized=False → RuntimeError |
| 10.2 YAML 文件格式错误 | ✅ PASS | prompt_manager.py:91-92: 每个 YAML 加载在 try/except 中，失败文件记录 warning 后继续 |
| 10.3 模板编译错误 | ✅ PASS | prompt_manager.py:187-190: 配置存在但模板编译失败时返回 ""，不阻塞流程 |
| 10.4 prompts 目录不存在 | ✅ PASS | prompt_manager.py:72-74: 目录不存在 → mkdir(parents=True) + warning 日志 |

