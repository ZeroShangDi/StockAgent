# AI Agents 模块 功能说明

## 概述

AI Agents 模块是 StockAgent 的智能分析核心，基于 ReAct 循环（Thought -> Action -> Observation）实现多 Agent 协作分析。模块包含 Agent 层（BaseAgent + 7 个具体 Agent）、分析服务层（Coze 工作流、市场晴雨表、缓存服务）、工作流引擎层（LangGraph 编排）、以及两个核心管理器（AnalysisManager V2.1、PromptManager V3.0）。

**代码位置：**

| 路径 | 内容 | 说明 |
|---|---|---|
| `AgentServer/src/agents/` | Agent 实现 | BaseAgent + StockAnalyzer + ReportWriter + 6 个复盘 Agent |
| `AgentServer/src/analysis/` | 分析服务 | Coze 工作流、市场晴雨表、统计缓存、股票联动 |
| `AgentServer/src/tools/` | 工具层 | 工具注册中心、工具定义 |
| `AgentServer/src/workflows/` | 工作流 | LangGraph 编排定义 |
| `AgentServer/core/managers/analysis_manager.py` | 分析管理器 | 双评分情绪周期系统 V2.1 |
| `AgentServer/core/managers/prompt_manager.py` | 提示词管理器 | Jinja2 模板引擎 V3.0 |
| `AgentServer/core/prompts/` | 提示词模板 | 8 个 YAML 模板文件 |

---

## 一、Agent 层

### 1.1 BaseAgent (`src/agents/base.py`)

所有 Agent 的基类，实现 ReAct 循环核心逻辑。

**配置与数据结构：**

| 类 | 字段 | 说明 |
|---|---|---|
| `AgentConfig` | `max_steps` (10) | 最大执行步数 |
| | `max_tokens` (4096) | 单次 LLM 响应最大 token |
| | `temperature` (0.3) | LLM 温度参数 |
| | `timeout` (120.0) | 超时时间（秒） |
| | `verbose` (False) | 详细日志开关 |
| `ToolCall` | `id`, `name`, `arguments` | 工具调用标识 |
| | `result`, `success`, `error` | 执行结果 |
| | `elapsed_ms` | 耗时 |
| `AgentResult` | `success`, `content`, `data` | 执行结果 |
| | `tool_calls` (List[ToolCall]) | 工具调用记录 |
| | `total_steps`, `total_tokens`, `elapsed_ms` | 统计信息 |

**ReAct 循环流程：**

```
Step 1: 构建初始消息 (system_prompt + user_message)
Step 2: 获取可用工具的 OpenAI Function Calling 格式
Step 3: ReAct 循环 (最多 max_steps 步):
    a. 调用 LLM (chat_with_tools)
    b. 如果 LLM 返回 tool_calls → 执行工具，将结果追加到消息历史
    c. 如果 LLM 返回纯文本 → 解析结果，返回 AgentResult
Step 4: 超过 max_steps → 返回失败结果
```

**自定义 Agent 方式：**

```python
class MyAgent(BaseAgent):
    name = "my_agent"
    description = "My custom agent"
    prompt_template_name = "agent_my_agent"  # 引用 YAML 模板

    @property
    def available_tools(self) -> List[str]:
        return ["tool1", "tool2"]
```

**关键方法：**

| 方法 | 说明 |
|---|---|
| `run(task, context)` | 执行 Agent 主任务，返回 `AgentResult` |
| `_call_llm(messages, tools)` | 调用 LLM 获取响应（含 tool_calls） |
| `_execute_tool(tool_call)` | 执行单个工具调用，返回 `ToolCall` |
| `_build_user_message(task, context)` | 构建用户消息（自动格式化上下文） |
| `_parse_response(content)` | 解析 LLM 响应中的 JSON 结构（支持 ```json 块和直接 JSON） |
| `_serialize_result(result)` | 序列化工具结果为字符串 |
| `system_prompt` (property) | 从 PromptRegistry 加载模板或使用默认 |

### 1.2 StockAnalyzerAgent (`src/agents/stock_analyzer_agent.py`)

股票综合分析 Agent，配备 8 个工具。

| 属性 | 值 |
|---|---|
| `name` | `stock_analyzer` |
| `prompt_template_name` | `agent_stock_analyzer` |

**可用工具（8个）：**

| 分类 | 工具名 | 功能 |
|---|---|---|
| 数据工具 | `get_realtime_quote` | 获取实时行情 |
| | `get_stock_info` | 获取股票基本信息 |
| | `get_daily_kline` | 获取历史K线 |
| | `get_financial_data` | 获取财务数据 |
| 分析工具 | `calculate_technical_indicators` | 计算技术指标 |
| | `analyze_trend` | 趋势分析 |
| 搜索工具 | `search_stock_news` | 搜索相关新闻 |
| | `search_local_news` | 搜索本地新闻 |
| | `get_stock_news` | 获取股票新闻 |

**分析流程：**
1. 获取股票基本信息和实时行情
2. 获取历史K线，计算技术指标
3. 搜索相关新闻和公告
4. 综合分析，给出投资建议

### 1.3 ReportWriterAgent (`src/agents/report_writer_agent.py`)

报告撰写 Agent，根据分析结果生成结构化报告。

| 属性 | 值 |
|---|---|
| `name` | `report_writer` |
| `prompt_template_name` | `agent_report_writer` |

**可用工具（3个）：**

| 工具名 | 功能 |
|---|---|
| `get_stock_info` | 获取股票基本信息 |
| `get_realtime_quote` | 获取实时行情 |
| `get_market_sentiment` | 获取市场情绪数据 |

### 1.4 复盘 Agent 集合 (`src/agents/review/`)

共 6 个复盘专用 Agent：

| Agent | 类名 | 工具数 | 分析内容 |
|---|---|---|---|
| 大盘复盘 | `MarketReviewAgent` | 4 | 三大指数涨跌、北向资金、涨跌家数比、大盘强弱 |
| 板块复盘 | `SectorReviewAgent` | 5 | 领涨/领跌板块、板块轮动、资金流向 |
| 涨停复盘 | `LimitUpReviewAgent` | 5 | 涨停家数、连板天梯、炸板率、空间股 |
| 个股联动 | `StockLinkageAgent` | 7 | 龙头/中军/补涨识别、板块内梯队 |
| 情绪周期 | `SentimentCycleAgent` | 5 | 情绪阶段判断、周期位置、风险机会提示 |
| 报告生成 | `ReviewReportAgent` | 6 | 汇总各维度分析，生成完整复盘报告 |

**ReviewReportAgent 附加方法：**

| 方法 | 说明 |
|---|---|
| `generate_report(trade_date, analysis_results)` | 聚合各维度结果生成报告 |
| `format_for_wechat(content)` | 格式化为企业微信兼容 Markdown |

---

## 二、分析服务层 (`src/analysis/`)

### 2.1 CozeWorkflowClient (`src/analysis/coze_workflow_client.py`)

轻量级 Coze Workflow HTTP 客户端，用于调用与股票插件无关的独立 Coze 工作流。

**初始化参数：**

| 参数 | 来源 | 说明 |
|---|---|---|
| `api_token` | `settings.coze.api_token` | Coze API 令牌 |
| `api_base` | `settings.coze.api_base` | API 基础 URL |
| `timeout` | `settings.coze.timeout` | HTTP 超时 |

**关键方法：**

| 方法 | 说明 |
|---|---|
| `run(workflow_id, parameters)` | 调用 Coze 工作流，返回完整响应 JSON |
| `decode_json_like(value)` | 递归解析嵌套 JSON 字符串（字符串 `"{\\"...\\"}"` -> dict） |

**错误处理：**
- API Token 未配置 → `RuntimeError("COZE_API_TOKEN 未配置")`
- workflow_id 为空 → `RuntimeError("workflow_id 未配置")`
- Coze 返回 code > 0 → `RuntimeError("Coze workflow 调用失败: code=X, msg=Y")`

### 2.2 MarketWeatherService (`src/analysis/market_weather.py`)

市场晴雨表服务，调用 Coze 市场指标工作流并解析结果。

**核心因子（6个）：**

| 因子 | 字段名 | 取值范围 |
|---|---|---|
| 市场温度指数 | `市场温度指数` | 0-100 |
| 涨停溢价延续因子 | `涨停溢价延续因子` | 0-1 |
| 趋势惯性累积因子 | `趋势惯性累积因子` | 0-1 |
| 量价共振强度因子 | `量价共振强度因子` | 0-1 |
| 市场广度扩散因子 | `市场广度扩散因子` | 0-1 |
| 多空动能极化因子 | `多空动能极化因子` | 0-1 |

**交易信号（4种操作）：**

| 仓位分 | 操作 | 说明 |
|---|---|---|
| <= 30 | 持币 | 市场偏冷，等待转暖 |
| 31-45 | 观望 | 方向不明，观望为主 |
| 46-65 | 持筹 | 温度适中，可适度参与 |
| > 65 | 积极 | 市场活跃，可积极操作 |

**策略建议（4种）：**
- **低吸**：温度<35 且溢价因子<0.5 且动能<0.4，或温度<40 且量能>0.7 且动能<0.5
- **追高**：溢价因子>0.7 且趋势>0.6 且温度>60，或温度>65 且广度>0.7 且动能>0.6
- **波段**：趋势>0.45 且量能>0.45
- **防守**：其他情况

**关键方法：**

| 方法 | 说明 |
|---|---|
| `fetch_one(trade_date)` | 获取单日市场晴雨表 |
| `store_record(record)` | 持久化到 MongoDB |
| `sync_recent(days)` | 同步最近 N 天数据 |
| `sync_range(start, end, ...)` | 按日期范围批量同步（支持断点停止） |
| `list_history(days)` | 查询历史记录 |
| `get_coverage_summary()` | 获取数据覆盖概况 |

### 2.3 MarketStatisticsCacheService (`src/analysis/market_statistics_cache.py`)

市场统计预聚合缓存服务，双写 Redis + MongoDB。

**缓存层级：**
1. **Redis 热缓存**（优先读取）：TTL 默认 6 小时
2. **MongoDB 持久化**（回退读取）：服务重启后快速恢复

**缓存 Key 格式：** `market_statistics:{cache_type}:{cache_key}`

**关键函数：**

| 函数 | 说明 |
|---|---|
| `get_cached_market_statistics(cache_type, cache_key)` | 读取缓存（Redis 优先） |
| `set_cached_market_statistics(cache_type, cache_key, payload, ...)` | 写入缓存（双写） |

### 2.4 其他分析服务

| 服务 | 文件 | 功能 |
|---|---|---|
| StockChartContext | `stock_chart_context.py` | 为 LLM 提供 K 线图表上下文 |
| StockLinkageService | `stock_linkage.py` | 个股联动分析 |
| OneLineStockPicker | `stock_picker.py` | 调用 Coze 选股工作流 |
| TradeReviewService | `trade_review.py` | 交易复盘分析 |

---

## 三、AnalysisManager V2.1 (`core/managers/analysis_manager.py`)

双评分动态情绪周期系统，对超短线市场进行量化周期判定。

### 3.1 评分体系

```
最终评分 = 5日EMA平滑(3日EMA平滑(核心动态分) + 趋势分)
```

**评分结构：**

| 层级 | 情绪评分 | 强度评分 | 说明 |
|---|---|---|---|
| 核心动态分 (70分) | 5因子（高度25+晋级率25+连板10+封板5+跌停惩罚15） | 4因子（上涨占比20+涨幅中位数20+成交额15+涨跌5%比15） | 相对基准 + 绝对阈值双重约束 |
| 3日EMA平滑 | 0.6*今日 + 0.3*昨日 + 0.1*前日 | 同左 | 消除单日脉冲 |
| 趋势分 (30分) | 与昨日的比例变化 | 同左 | 分档：>=+15%明显走强(30) / >=+10%温和(10) / >=-10%横盘(5) / <-10%走弱(0) |
| 5日EMA强平滑 | 0.30*t0 + 0.25*t-1 + 0.20*t-2 + 0.15*t-3 + 0.10*t-4 | 同左 | 消除锯齿 |

### 3.2 核心分因子权重

**情绪核心分 (70分)：**

| 因子 | 满分 | 计算方式 | 约束 |
|---|---|---|---|
| 连板高度 | 25 | `min(绝对分, 相对分)` | <=2板 → 核心分封顶40 |
| 晋级率 | 25 | `min(绝对分, 相对分)` | <=30% → 扣10分 |
| 连板家数(2板+) | 10 | `min(绝对分, 相对分)` | - |
| 封板率 | 5 | 相对分 | - |
| 跌停惩罚 | 15(反向) | 相对分(反向) | 跌停越多分越低 |

**强度核心分 (70分)：**

| 因子 | 满分 | 计算方式 | 约束 |
|---|---|---|---|
| 上涨家数占比 | 20 | `min(绝对分, 相对分)` | <=30% → 核心分封顶40 |
| 涨幅中位数 | 20 | `min(绝对分, 相对分)` | <=-0.5% → 扣10分 |
| 成交额 | 15 | 相对分 | - |
| 涨5%/跌5%家数比 | 15 | `min(绝对分, 相对分)` | - |

### 3.3 周期判定（6个周期 + 未知）

基于双趋势方向（3日趋势 up/down/flat）组合判定：

| 情绪趋势 | 强度趋势 | 周期 | 仓位建议 |
|---|---|---|---|
| up | up | 主升期 (main_upward) | 重仓 (7~10成) |
| up | down | 分歧期 (divergence) | 半仓 (3~5成) |
| down | up | 分歧期 (divergence) | 半仓 (3~5成) |
| down | down | 退潮期 (decline) | 空仓 (0~1成) |
| flat | flat | 混沌期 (chaos) | 观望 (1~3成) |
| 双低(<20) + 非走强 | - | 冰点期 (ice_point) | 空仓 (0成) |
| 双低(<40) + 有止跌 | - | 修复期 (recovery) | 轻仓 (2~3成) |

### 3.4 分歧判定

强弱差 >= 15 分 **且** 情绪/强度趋势方向相反（且都不是 flat）时才显示分歧。

### 3.5 关键方法

| 方法 | 说明 |
|---|---|
| `load_ma10_baseline(trade_date, mongo_manager)` | 加载 10 日 EMA 动态基准值 |
| `calculate_sentiment_core_v2(stats, baseline)` | 计算情绪核心动态分 |
| `calculate_strength_core_v2(stats, baseline)` | 计算强度核心动态分 |
| `calculate_trend_score(today, prev)` | 计算趋势分 |
| `apply_3day_ema(today, day1, day2)` | 3 日 EMA 平滑 |
| `apply_5day_ema(scores)` | 5 日 EMA 强平滑 |
| `identify_3day_trend(today, day1, day2)` | 判定 3 日趋势方向 |
| `identify_cycle_by_trends(sent_trend, stren_trend, ...)` | 基于双趋势组合判定周期 |
| `analyze_and_store(stats, prev_stats, mongo_manager)` | 完整分析流程，结果写入 MongoDB |
| `get_position_advice(cycle)` | 获取仓位建议 |

---

## 四、PromptManager V3.0 (`core/managers/prompt_manager.py`)

基于 Jinja2 的提示词模板渲染引擎，支持 YAML 模板预加载和编译。

### 4.1 核心特性

- **StrictUndefined 模式**：模板中缺失变量会抛出 `jinja2.UndefinedError`，便于调试
- **预加载**：`initialize()` 时递归扫描 `core/prompts/` 目录，加载所有 YAML 到内存
- **预编译**：所有模板在初始化时编译为 Jinja2 Template 对象，运行时直接渲染
- **热重载**：`reload()` 方法支持不重启服务更新提示词

### 4.2 模板组织结构

```
core/prompts/
└── stock_analysis/
    ├── fundamental.yaml    # 基本面分析（支持增量分析模式）
    ├── technical.yaml      # 技术面分析
    ├── sentiment.yaml      # 舆情分析
    ├── market.yaml         # 市场分析
    ├── supervisor.yaml     # 首席策略官（逻辑对冲+置信度评估）
    ├── query.yaml          # 查询分析
    ├── refinement.yaml     # 精炼分析
    └── mcp_search.yaml     # MCP 搜索
```

### 4.3 YAML 模板格式

```yaml
name: "template_name"
version: "3.2.0"
description: "模板说明"

system_prompt: |
  系统提示词（支持 {{ variable }} 和 {% if %} 等 Jinja2 语法）

template: |
  用户提示词模板，支持 {{ variable }} 替换
  {% if condition %}
  条件渲染内容
  {% endif %}
  {% for item in list %}
  - {{ item }}
  {% endfor %}
```

### 4.4 关键方法

| 方法 | 说明 |
|---|---|
| `initialize()` | 扫描 prompts/ 目录，加载 YAML，预编译模板 |
| `get_prompt(name, **kwargs)` | 获取渲染后的提示词 |
| `get_system_prompt(name, **kwargs)` | 获取渲染后的系统提示词 |
| `get_config(name)` | 获取完整提示词配置 |
| `list_prompts()` | 列出所有已加载的提示词名称 |
| `has_prompt(name)` | 检查提示词是否存在 |
| `reload()` | 热重载所有提示词 |
| `shutdown()` | 清理内存 |

### 4.5 错误处理

| 场景 | 行为 |
|---|---|
| 模板不存在 | `KeyError("Prompt not found: X")` |
| 模板变量缺失 | `jinja2.UndefinedError` |
| YAML 文件格式错误 | `initialize()` 中 error 日志，跳过该文件 |
| 未初始化就调用 | `_ensure_initialized()` 报错 |

---

## 五、ToolRegistry (`src/tools/registry.py`)

工具注册中心，管理所有可用工具的注册、查询和执行。

### 5.1 核心数据结构

| 类 | 字段 | 说明 |
|---|---|---|
| `ToolParameter` | `name`, `type`, `description` | 参数定义 |
| | `required` (True) | 是否必需 |
| | `enum`, `default` | 枚举值和默认值 |
| `ToolDefinition` | `name`, `description`, `parameters` | 工具定义 |
| | `handler` (Callable) | 执行函数 |
| | `category` | 分类（data/search/analysis/action） |
| | `tags` | 标签列表 |

### 5.2 格式转换

| 方法 | 说明 |
|---|---|
| `to_openai_tools(names)` | 转换为 OpenAI Function Calling 格式 |
| `to_anthropic_tools(names)` | 转换为 Anthropic Tool 格式 |

### 5.3 `@tool` 装饰器

自动从函数签名推断参数定义（类型、是否必需、docstring 描述）：

```python
@tool(name="get_quote", description="获取实时行情", category="data")
async def get_realtime_quote(stock_code: str, market: str = "CN") -> dict:
    """
    获取股票实时行情

    Args:
        stock_code: 股票代码
        market: 市场代码 (CN/HK/US)
    """
    ...
```

**类型映射：** `str -> string`, `int -> integer`, `float -> number`, `bool -> boolean`, `list -> array`, `dict -> object`

### 5.4 关键方法

| 方法 | 说明 |
|---|---|
| `register(tool)` | 注册工具 |
| `unregister(name)` | 注销工具 |
| `get(name)` | 查询工具定义 |
| `execute(name, **kwargs)` | 执行工具（自动识别同步/异步） |
| `list_by_category(category)` | 按分类列出 |
| `list_by_tag(tag)` | 按标签列出 |
| `get_stats()` | 获取注册统计 |
