# 推理引擎 功能说明

## 概述

推理引擎（Inference Engine）是 StockAgent 的 AI 分析核心，负责执行股票/大盘/自定义查询三类分析任务。基于 LangGraph 状态机架构，实现多维度并行分析、Supervisor 冲突调和、置信度检查与动态纠偏、跨轮次增量分析的完整推理闭环。

**代码位置：**

| 文件 | 类名 | 说明 |
|---|---|---|
| `nodes/inference/node.py` | `InferenceNode` | 节点入口，Redis 任务消费、并发控制、进度发布 |
| `nodes/inference/graph/stock_analysis.py` | `StockAnalysisGraph` | LangGraph 工作流，8 节点分析链路 (V3.2) |

**版本：** V3.2（跨轮次记忆 + 增量分析）

---

## 一、架构总览

```
InferenceNode (node.py)
  │
  ├── redis_manager   (任务队列消费 BRPOP)
  ├── mongo_manager   (任务持久化、数据读取)
  ├── llm_manager     (LLM 推理)
  ├── milvus_manager  (向量检索)
  │
  └── StockAnalysisGraph (stock_analysis.py)
        │
        ├── analyze_stock()     → 个股分析 (8 节点 LangGraph)
        ├── analyze_market()    → 大盘分析 (V2.3)
        └── custom_query()      → 自定义查询 (V2.0 意图驱动 RAG)
```

### 图拓扑 (V3.2)

```
data_collect
     ↓
┌────┼────┐
↓    ↓    ↓
fund tech  sent  (并行) ← 首轮分析
└────┼────┘
     ↓
supervisor ← 评估 + 保存 RoundSummary
     ↓
check_result
     ↓
[条件边缘] ─────────────────────────────────┐
     ↓                                     ↓
confidence >= 60                   confidence < 60
     ↓                                     ↓
   output                         query_refinement
                                         ↓
                                    mcp_search
                                         ↓
                                ┌────┼────┐
                                ↓    ↓    ↓
                              fund tech  sent (增量分析)
                                └────┼────┘
                                         ↓
                                   supervisor (重评 + 对比上轮)
```

---

## 二、核心组件

### 2.1 InferenceNode 节点

**文件：** `nodes/inference/node.py`

**职责：**
- 从 Redis 任务队列消费分析任务（BRPOP 阻塞读取）
- 通过 `asyncio.Semaphore` 控制并发任务数（默认 2，可通过 `MAX_CONCURRENT_TASKS` 环境变量配置）
- 按任务类型路由：`stock_analysis` / `market_overview` / `custom_query`
- 发布任务进度（Redis Pub/Sub，0-100%）
- 任务执行结果写回 MongoDB 并发布完成通知

**初始化顺序（按依赖）：**
```
redis → mongo → llm → milvus → RPC server → StockAnalysisGraph
```

**关键参数：**

| 参数 | 默认值 | 说明 |
|---|---|---|
| `max_concurrent_tasks` | `5` (构造函数) / `2` (环境变量) | 最大并发分析任务数 |
| `rpc_port` | `50052` | RPC 服务端口 |

**任务生命周期：**
1. `BRPOP` 获取任务 JSON
2. 跳过 `tool_name` 任务（留给 MCP 节点处理）
3. 创建 `asyncio.create_task` 异步处理
4. 更新 MongoDB `tasks` 集合状态：`RUNNING` / `COMPLETED` / `FAILED`
5. 发布进度 (`TaskProgress`) 和结果 (`AgentResponse`) 到 Redis Pub/Sub

**进度回调机制：**
- 50% 以下：数据采集 + 首轮分析
- 50-70%：Supervisor + 置信度检查
- 70-90%：精炼循环（Query Refinement → MCP Search → 增量分析）
- 90-100%：输出生成

---

### 2.2 StockAnalysisGraph (V3.2)

**文件：** `nodes/inference/graph/stock_analysis.py`（2356 行）

**核心常量：**

| 常量 | 值 | 说明 |
|---|---|---|
| `CONFIDENCE_THRESHOLD` | `60` | 置信度阈值（可通过配置覆盖） |
| `MAX_RETRY_COUNT` | `2` | 最大重试次数 |

#### 节点 1: data_collect_node（数据采集）

**职责：** 获取分析所需的基础数据
- 从 `stock_basic` 获取 PE、PB、总市值、行业、换手率
- 从 `stock_daily` 获取最近 60 条日线数据
- 从 `fina_indicator` 获取最近 8 个季度财务数据
- 自动标准化股票代码（纯数字 → `XXXXXX.SH`/`.SZ`/`.BJ`）

**输出字段：** `ts_code`, `stock`, `stock_name`, `daily_data`, `fina_data`, `reasoning_chain`

#### 节点 2: fundamental_node（基本面分析）

**职责：** LLM 分析财务数据
- 核心指标：EPS、ROE、ROA、毛利率、净利率、资产负债率、流动比率
- 成长性指标：营收同比、净利润同比
- 区间涨跌幅（30 天）
- 支持增量分析模式（Round 2+）：结合上轮结论 + SupplementaryData

**提示词配置：** `core/prompts/stock_analysis/fundamental.yaml`

#### 节点 3: technical_node（技术面分析）

**职责：** LLM 分析价格趋势
- 计算 MA5、MA20、量比（vol_ratio）
- 趋势判断：上升/下降/横盘
- 近 5 日 K 线摘要（收盘价、涨跌幅、成交量）
- 20 日区间极值（period_high / period_low）
- 支持增量分析模式

**提示词配置：** `core/prompts/stock_analysis/technical.yaml`

#### 节点 4: sentiment_node（舆情分析）

**职责：** LLM 分析新闻舆情 + 市场信号
- 从 MongoDB `news` 集合检索相关新闻（按股票名/代码模糊匹配，limit=5）
- 市场情绪指标：涨跌停状态（涨停/大涨/上涨/下跌/大跌/跌停）、量能状态（放量/正常/缩量）
- 支持增量分析模式

**提示词配置：** `core/prompts/stock_analysis/sentiment.yaml`

#### 节点 5: supervisor_node（Supervisor 协调）

**职责：** 综合研判，8 大子任务：
1. 结构化精简三方意见（各 ≤50 字核心结论）
2. 识别逻辑冲突（量价背离、资金背离等 5 类）
3. 冲突调和
4. 置信度评估（数据完整性 / 意见一致性 / 综合置信度）
5. 信号生成（STRONG_BUY / BUY / HOLD / SELL / STRONG_SELL）
6. 各维度评分（基本面 / 技术面 / 舆情）
7. 风险提示
8. 保存 RoundSummary 用于跨轮次记忆

**JSON 解析容错：** 使用 `_parse_json_response()` 正则提取 `{...}` 块，解析失败时不抛异常，使用默认值。

**信号映射：**

| LLM 输出 | SignalType |
|---|---|
| 强烈买入 | `STRONG_BUY` |
| 买入 | `BUY` |
| 持有 | `HOLD` |
| 卖出 | `SELL` |
| 强烈卖出 | `STRONG_SELL` |

**提示词配置：** `core/prompts/stock_analysis/supervisor.yaml`

#### 节点 6: check_result_node（置信度检查）

**职责：** 判断是否需要触发数据补充流程
- 读取配置中的 `confidence_threshold`（默认 60）
- 判断逻辑：`overall_confidence < threshold AND retry_count < MAX_RETRY_COUNT`
- 设置 `needs_refinement` 标志

#### 节点 7: query_refinement_node（查询精炼）

**职责：** 当置信度不足时，生成 MCP 工具调用指令
- 输入：置信度评分、冲突列表、结构化摘要
- LLM 生成针对性的工具调用列表（指定 tool、query、target_conflict、expected_evidence）
- 异常兜底：LLM 调用失败时返回默认查询（获取量能变化 + 搜索资金流向新闻）

**提示词配置：** `core/prompts/stock_analysis/refinement.yaml`

#### 节点 8: mcp_search_node（MCP 工具调用）

**职责：** 执行 MCP 工具，生成 SupplementaryData

**支持的工具：**

| 工具名 | 实现 | 说明 |
|---|---|---|
| `get_stock_daily` | MongoDB `stock_daily` 查询 | 计算近 10 日成交量变化序列 |
| `get_financial_indicator` | 简化实现 | 返回占位数据 |
| `get_news_sentiment` | MongoDB `news` 模糊搜索 | 按股票名 + 代码检索 |
| `search_similar_reports` | Milvus 向量检索 | 依赖 Milvus 可用，失败时优雅降级 |

**容错机制：**
- 单个工具调用失败不中断整体流程，记录 `success=False`
- Milvus 不可用时 `search_similar_reports` 返回 "研报检索服务不可用"
- 每个成功调用生成 `SupplementaryData` 供增量分析使用

#### 条件路由：route_after_check

```python
def route_after_check(state) -> Literal["refinement", "output"]:
    if state.needs_refinement:
        return "refinement"
    return "output"
```

#### 输出构建：build_output

**输出字段（共 20+ 个）：**

| 字段 | 说明 |
|---|---|
| `trace_id` | 分布式追踪 ID |
| `signal` | 投资信号 (`hold`/`buy`/`sell`/`strong_buy`/`strong_sell`) |
| `confidence` | 置信度 (0.0-1.0) |
| `summary` | 综合摘要 |
| `scores` | 各维度评分 `{fundamental, technical, sentiment}` |
| `fundamental_analysis` | 基本面完整分析文本 |
| `technical_analysis` | 技术面完整分析文本 |
| `sentiment_analysis` | 舆情完整分析文本 |
| `structured_summary` | 结构化精简摘要 |
| `analysis_conflicts` | 逻辑冲突列表 |
| `conflict_summary` | 冲突对冲说明 |
| `confidence_score` | 置信度详情 `{data_completeness, opinion_consistency, overall}` |
| `final_decision` | 最终决策文本 |
| `decision_reason` | 决策理由 |
| `risks` | 风险提示列表 |
| `mcp_tool_calls` | MCP 工具调用记录 |
| `mcp_evidence` | MCP 补充证据 |
| `reasoning_chain` | 决策链（各步骤摘要） |
| `refinement_queries` | 精炼查询列表 |
| `retry_count` | 重试次数 |
| `round_history` | 跨轮次决策历史 |

---

### 2.3 大盘分析 (analyze_market V2.3)

**入口：** `StockAnalysisGraph.analyze_market()`

**数据采集（4 路并行）：**

| 数据源 | MongoDB 集合 | 说明 |
|---|---|---|
| `daily_stats` (10 条) | `daily_stats` | 涨跌家数、涨停跌停数、最高连板高度、成交额 |
| `market_analysis` (10 条) | `market_analysis` | 情绪评分、市场评分、周期定位 |
| `sector_ranking` (10 条) | `sector_ranking` | 行业板块排名 TOP10，含 3 日前排名对比 |
| 上证 K 线 (10 条) | `index_daily` | `000001.SH` 指数日线 |

**逻辑预处理：**
1. **空值填充：** 对缺失的评分/成交额字段，使用 10 日有效均值填充
2. **量能变化：** 今日成交额 vs 5 日均量，映射为语义标签（大幅放量/温和放量/小幅放量/持平/小幅缩量/温和缩量/显著缩量）
3. **评分趋势：** 今日情绪分 vs 昨日情绪分（上升/下降/微幅变动）
4. **背离检查：**
   - 看涨背离：10 日内情绪评分底部抬升 + 连板高度突破
   - 诱多背离：市场评分持续下滑 + 涨跌家数表面繁荣
5. **上证指数：** 连阳天数、10 日 K 线快照

**LLM 输出解析字段：**

| 字段 | 说明 |
|---|---|
| `cycle` | 周期定位（退潮冰点期/分歧修复期/高潮亢奋期/混沌震荡期） |
| `cycle_reason` | 周期定位理由 |
| `signal` | 投资信号（buy/sell/hold） |
| `risk_score` | 风险等级（0-100） |
| `risk_reason` | 风险评估理由 |
| `position_advice` | 仓位建议（含百分比） |
| `strategy` | 实战策略建议 |
| `focus_sectors` | 重点关注板块 |
| `index_analysis` | 上证指数走势分析 (V2.5) |
| `tomorrow_outlook` | 明日预判 (V2.4)：方向/置信度/关键观察/风险点 |

**对冲校验（`_hedge_check_market_result`）：**

| 规则 | 触发条件 | 处理 |
|---|---|---|
| 风险与信号对冲 | `risk_score > 80` 且 `signal == buy` | 强制改为 `hold`，附加防守修正说明 |
| 仓位与周期对冲 | cycle 为"退潮冰点期"且仓位建议 > 40% | 记录 `hedge_warnings` 警告 |

---

### 2.4 自定义查询 (custom_query V2.0)

**入口：** `StockAnalysisGraph.custom_query()`

**流程（4 步）：**

```
意图拆解 → 多路并行检索 → Jinja2 上下文模板 → LLM 回答
```

**第 1 步：意图拆解（`_parse_query_intent`）**
- LLM 解析用户查询意图 → `intent_type`: `stock` / `market` / `news` / `general`
- 提取 `search_queries`（语义短句）、`ts_codes`（股票代码）
- 判断是否需要 `need_market_stats` / `need_stock_snapshot`
- 异常兜底：`_simple_intent_parse` 基于关键词规则（大盘/股票代码/时间）

**第 2 步：多路并行检索（`asyncio.gather`）**

| 检索路 | 方法 | 数据源 |
|---|---|---|
| 文本路 | `_search_milvus` | Milvus 向量检索（研报 + 新闻），支持股票代码过滤 |
| 统计路 | `_get_market_stats` | MongoDB `daily_stats` + `market_analysis` |
| 个股路 | `_get_stock_snapshots` | MongoDB `stock_basic` + `stock_daily`（最近 3 日） |

**第 3 步：Jinja2 上下文模板**
- 从 `prompt_manager.get_config("stock_analysis/query")` 获取模板
- 研报和新闻各最多 5 条
- 作为第二个 system message 注入 LLM

**第 4 步：LLM 回答**

**容错机制：**
- Milvus 检索失败返回空结果，不阻断流程
- 意图解析失败自动回退规则模式
- 所有检索异常以 `return_exceptions=True` 处理

---

## 三、状态管理

### StockAnalysisState（Pydantic 模型）

**文件：** `core/protocols.py`

```python
class StockAnalysisState(BaseModel):
    # 追踪信息
    trace_id: str
    # 输入参数
    ts_code: str
    task_id: str
    # 数据采集
    stock: Optional[Dict]
    stock_name: Optional[str]
    daily_data: List[Dict]
    fina_data: List[Dict]
    # 补充数据 (V3.2)
    supplementary_data: List[SupplementaryData]
    # 三方分析
    fundamental_res: Optional[str]
    technical_res: Optional[str]
    sentiment_res: Optional[str]
    # 首轮分析备份
    initial_fundamental_res: Optional[str]
    initial_technical_res: Optional[str]
    initial_sentiment_res: Optional[str]
    # 结构化精简
    structured_summary: Optional[StructuredSummary]
    # Supervisor 输出
    analysis_conflicts: List[AnalysisConflict]
    confidence_score: Optional[ConfidenceScore]
    final_decision: Optional[str]
    signal: Optional[str]
    confidence: Optional[float]
    summary: Optional[str]
    scores: Optional[Dict]
    risks: List[str]
    decision_reason: Optional[str]
    # MCP 搜索结果
    mcp_tool_calls: List[MCPToolCall]
    mcp_evidence: List[Dict]
    refinement_queries: List
    # 决策链追踪
    reasoning_chain: List[ReasoningStep]
    reasoning_steps: List[RoundSummary]  # V3.2 跨轮次记忆
    # 控制流
    retry_count: int
    needs_refinement: bool
```

**辅助方法：**
- `is_refinement_round()` — 判断当前是否为补充分析轮次（`retry_count > 0`）
- `get_previous_issues()` — 获取上一轮未解决的问题列表
- `save_round_summary()` — 保存当前轮次决策摘要

### 关键子模型

| 模型 | 字段 |
|---|---|
| `StructuredSummary` | `fundamental_core`, `technical_core`, `sentiment_core` |
| `AnalysisConflict` | `conflict_type`, `description`, `resolution` |
| `ConfidenceScore` | `data_completeness`, `opinion_consistency`, `overall` |
| `MCPToolCall` | `tool`, `query`, `target_conflict`, `expected_evidence`, `result`, `success` |
| `ReasoningStep` | `step_id`, `node_name`, `action`, `reasoning`, `result_summary`, `timestamp` |
| `RoundSummary` | `round_id`, `fundamental_conclusion`, `technical_conclusion`, `sentiment_conclusion`, `conflicts_found`, `confidence_score`, `decision`, `unresolved_issues` |
| `SupplementaryData` | `source`, `target_conflict`, `content`, `raw_data` |

---

## 四、数据流

### 个股分析完整数据流

```
1. Redis BRPOP 获取任务
2. MongoDB 更新任务状态 → RUNNING
3. data_collect: stock_basic + stock_daily(60条) + fina_indicator(8季度)
4. 并行: fundamental_node + technical_node + sentiment_node (LLM)
5. supervisor_node: 冲突检测 + 置信度 + 信号 + RoundSummary
6. check_result_node: 置信度 >= 60?
   ├── YES → 8. build_output
   └── NO  → 7. 精炼循环
       7a. query_refinement_node: LLM 生成 MCP 指令
       7b. mcp_search_node: 执行工具 → SupplementaryData
       7c. 并行增量分析 (Round 2)
       7d. supervisor_node 重新评估
       7e. → 8. build_output
8. build_output: 构建 20+ 字段的完整报告
9. MongoDB 更新任务状态 → COMPLETED
10. Redis Pub/Sub 发布结果
```

### 进度回调映射

| 进度 | 阶段 |
|---|---|
| 0% | 开始分析 |
| 10% | 获取股票数据 |
| 30% | 多维度分析中 (Round 1) |
| 55% | Supervisor 综合研判 (Round 1) |
| 65% | 置信度检查 |
| 70% | 置信度不足，生成补充查询 |
| 75% | 执行 MCP 工具调用 |
| 80% | 增量分析中 (Round 2) |
| 90% | Supervisor 重新评估 (Round 2) |
| 95% | 生成报告 |
| 100% | 分析完成 |

---

## 五、配置依赖

### 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `MAX_CONCURRENT_TASKS` | 最大并发分析任务数 | `2` |
| `LLM_PROVIDER` | LLM 提供商 (openai/deepseek/dashscope/zhipu/ollama) | - |
| `LLM_API_KEY` | LLM API 密钥 | - |
| `MONGO_HOST` / `MONGO_PORT` / `MONGO_DATABASE` | MongoDB 连接 | - |
| `REDIS_HOST` / `REDIS_PORT` | Redis 连接 | - |
| `MILVUS_HOST` / `MILVUS_PORT` | Milvus 连接（可选） | - |
| `JWT_SECRET` | JWT 签名密钥 | - |

### Prompt 配置

| 配置路径 | 用途 |
|---|---|
| `core/prompts/stock_analysis/fundamental.yaml` | 基本面分析提示词 |
| `core/prompts/stock_analysis/technical.yaml` | 技术面分析提示词 |
| `core/prompts/stock_analysis/sentiment.yaml` | 舆情分析提示词 |
| `core/prompts/stock_analysis/supervisor.yaml` | Supervisor 协调提示词 |
| `core/prompts/stock_analysis/refinement.yaml` | 查询精炼提示词 |
| `core/prompts/stock_analysis/market.yaml` | 大盘分析提示词 |
| `core/prompts/stock_analysis/query.yaml` | 自定义查询提示词 |

### supervisor.yaml 关键配置

```yaml
confidence_threshold: 60    # 置信度阈值（可覆盖默认值 60）
max_retry_count: 2          # 最大重试次数
```

### 依赖的管理器

| 管理器 | 用途 |
|---|---|
| `redis_manager` | 任务队列消费、进度/结果发布 |
| `mongo_manager` | 数据读取（stock_basic/stock_daily/news 等）、任务持久化 |
| `llm_manager` | LLM 推理（chat + embedding） |
| `milvus_manager` | 向量检索（研报/新闻，可选） |
| `prompt_manager` | 提示词模板管理 |

---

## 六、增量分析机制 (V3.2)

### 首轮 vs 补充分析

| 特性 | 首轮分析 (Round 1) | 补充分析 (Round 2) |
|---|---|---|
| 数据来源 | `daily_data` / `fina_data` | 初始数据 + `supplementary_data` |
| Prompt 模式 | 标准分析 | 增量分析（显式说明修正） |
| 上下文 | 无 | 上轮结论 + 上轮问题 |
| `is_refinement` | `False` | `True` |
| `initial_*_res` | 保存当前分析结果 | 保持不变（首轮备份） |

### SupplementaryData 匹配规则

| 分析节点 | 匹配的 MCP 数据源 |
|---|---|
| `fundamental` | `get_financial_indicator`, `search_similar_reports` |
| `technical` | `get_stock_daily` |
| `sentiment` | `get_news_sentiment`, `search_similar_reports` |

### Supervisor 跨轮次对比

在 Round 2 时 Supervisor 会额外判断：
1. 历史决策摘要（`reasoning_steps`）对比
2. 上轮未解决问题是否被解决
3. 输出"上轮问题解决情况"（`resolved` / `unresolved` / `summary`）

---

## 七、错误处理策略

| 场景 | 处理方式 |
|---|---|
| MongoDB 数据为空 | 节点返回空数据占位文本，不中断流程 |
| LLM JSON 输出格式错误 | `_parse_json_response` 正则提取兜底，返回空 dict |
| Supervisor JSON 解析失败 | 使用默认值（HOLD 信号，50 分置信度） |
| query_refinement LLM 调用失败 | 使用默认查询列表（量能 + 资金流向） |
| MCP 单个工具调用失败 | 记录 `success=False`，继续执行其他工具 |
| Milvus 不可用 | `search_similar_reports` 返回"服务不可用"，不阻断 |
| custom_query Milvus 检索异常 | 返回空结果 `{reports: [], news: []}` |
| 任务执行异常 | MongoDB 记录 FAILED 状态 + 错误信息，Redis 发布失败结果 |
| 大盘分析 JSON 解析失败 | 保留 LLM 原始响应作为 summary |

---

## 八、日志规范

所有节点日志包含 `trace_id` 用于分布式追踪：

```
格式: [node_name] trace_id=<id> | message

示例:
[data_collect] trace_id=a1b2c3 | Fetching data for 600519.SH
[fundamental] trace_id=a1b2c3 | Analysis complete, length=1234, refinement=False
[supervisor] trace_id=a1b2c3 | Signal: 买入, Confidence: 72
[check_result] trace_id=a1b2c3 | Confidence=72, threshold=60, retry=0
[check_result] trace_id=a1b2c3 | Needs refinement: False
[output] trace_id=a1b2c3 | Final result: signal=buy, confidence=0.72
```

每个节点还输出 DEBUG 级别的完整数据打印（数据字段、LLM 输入参数、LLM 响应预览等），便于问题排查。
