# MCP Server 功能说明

## 概述

MCP Server 节点 (`AgentServer/nodes/mcp/`) 是 Model Context Protocol 服务实现，作为数据中间层为 Inference Agent（LangChain/LangGraph 推理图）提供 LLM 可访问的数据工具。它通过 Redis 消息队列消费工具调用请求，封装了对 MongoDB、Tushare 数据源、Milvus 向量数据库等的访问逻辑，并对外提供标准化的 Function Calling Schema。

该服务作为独立节点运行（`NODE_TYPE=mcp`），在 Inference 图的 refinement（精炼）循环中被调用，帮助 LLM 获取实时数据、历史行情、财务指标、新闻舆情和相似研报检索能力。

## 文件结构

```
AgentServer/nodes/mcp/
├── node.py                  # MCPNode: Redis 队列消费者，工具注册与路由
└── tools/
    ├── __init__.py          # 工具集导出
    ├── stock_basic.py       # GetStockBasicTool: 股票基础信息查询
    ├── stock_daily.py       # GetStockDailyTool: 股票日线行情（MongoDB + 降级）
    ├── financial.py         # GetFinancialIndicatorTool: 财务指标查询
    ├── news.py              # GetNewsSentimentTool: 新闻舆情（正则匹配）
    └── search.py            # SearchSimilarReportsTool: Milvus 向量检索 + LLM Embedding
```

---

## 1. 节点主循环 (`node.py`)

### 1.1 `MCPNode` 类

继承自 `BaseNode`，节点类型为 `NodeType.MCP`。

**初始化:**
- 创建工具注册表 `_tools: Dict[str, BaseTool]`
- 支持自定义 `port`（默认 9000）

**启动流程 (`start`):**
```
1. 初始化 redis_manager（消息队列）
2. 初始化 mongo_manager（数据查询）
3. 初始化 data_source_manager（股票数据源）
4. 初始化 milvus_manager（向量检索）
5. 注册全部 5 个工具 (_register_tools)
```

**主循环 (`run`):**
```
while self._running:
    1. 从 Redis 队列阻塞获取请求 (dequeue_task, timeout=5s)
    2. 解析 JSON，若含 tool_name 字段则为工具调用请求
    3. 设置 trace_id 用于链路追踪
    4. 反序列化为 ToolRequest，调用 _handle_tool_request
    5. 通过 Redis publish_result 发布 ToolResponse
    6. 清理 trace_id
    7. 异常时 sleep 1s 后继续
```

### 1.2 方法说明

| 方法 | 说明 |
|------|------|
| `_register_tools()` | 遍历工具类列表，实例化并注册到 `_tools` 字典 |
| `_handle_tool_request(request)` | 根据 `tool_name` 路由到对应工具，构建输入、执行、返回响应 |
| `call_tool(tool_name, **kwargs)` | 本地直接调用工具（非 Redis），用于同步场景 |
| `get_tool_schemas()` | 获取所有工具的 Function Calling Schema 列表 |

---

## 2. 工具框架 (`core/base.py`)

### 2.1 `BaseTool[InputT, OutputT]` 抽象基类

所有 MCP 工具必须继承此类。

| 属性/方法 | 说明 |
|-----------|------|
| `name: str` | 工具唯一名称，同时也是 Redis 路由键 |
| `description: str` | 工具描述，用于 LLM Function Calling |
| `input_model: Type[InputT]` | Pydantic 输入模型（定义参数 Schema） |
| `output_model: Type[OutputT]` | Pydantic 输出模型（继承 ToolResult） |
| `execute(input_data) -> OutputT` | 抽象方法，子类实现具体逻辑 |
| `__call__(input_data) -> OutputT` | 调用入口：计时 + 异常捕获 + 自动设置 `execution_time_ms` |
| `get_schema() -> dict` | 返回 `{name, description, parameters}` 用于 LLM Function Calling |

### 2.2 `ToolResult` 基类

```python
class ToolResult(BaseModel):
    success: bool = True
    error_message: Optional[str] = None
    execution_time_ms: float = 0
```

所有工具输出模型继承 `ToolResult`，在此基础上扩展 `data` 字段。

### 2.3 错误处理机制

`BaseTool.__call__` 方法自动捕获 `execute` 中的异常，返回 `output_model(success=False, error_message=str(e), execution_time_ms=...)`。这意味着调用方总能获得一个结构完整的响应，不会因工具内部异常而中断整个推理链路。

---

## 3. 五大工具详解

### 3.1 GetStockBasicTool -- 股票基础信息

**工具名:** `get_stock_basic`

**输入:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `ts_code` | string | 否 | 股票代码，如 `000001.SZ` |
| `name` | string | 否 | 股票名称，支持模糊搜索 |

**执行逻辑:**
1. 若提供 `ts_code`，从 MongoDB `stock_basic` 集合精确查询
2. 若提供 `name`，使用 MongoDB `$regex` 模糊匹配（limit=10）
3. 若两者均未提供，从 Tushare 数据源获取全量数据

**输出:** `GetStockBasicOutput` 包含 `data: List[Dict[str, Any]]`，每条记录含 `ts_code`、`name`、`industry`、`list_date` 等字段。

### 3.2 GetStockDailyTool -- 股票日线行情

**工具名:** `get_stock_daily`

**输入:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `ts_code` | string | 是 | 股票代码 |
| `start_date` | string | 否 | 开始日期，格式 `YYYYMMDD` |
| `end_date` | string | 否 | 结束日期，格式 `YYYYMMDD` |
| `limit` | int | 否 | 返回条数，默认 30 |

**执行逻辑（MongoDB 优先 + Tushare 降级）:**
1. 构建 MongoDB 查询过滤器（`ts_code` + 可选日期范围）
2. 从 MongoDB `stock_daily` 集合查询，按 `trade_date` 降序
3. 若 MongoDB 无数据，降级到 `data_source_manager.get_daily()` —— 依次尝试 Tushare/BaoStock/AkShare 数据源链
4. 返回查询结果

**输出:** `GetStockDailyOutput` 包含 `data: List[Dict[str, Any]]`，含 `open`、`high`、`low`、`close`、`vol`、`pct_chg` 等。

### 3.3 GetFinancialIndicatorTool -- 财务指标

**工具名:** `get_financial_indicator`

**输入:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `ts_code` | string | 是 | 股票代码 |
| `period` | string | 否 | 报告期，格式 `YYYYMMDD` |

**执行逻辑:** 直接调用 `data_source_manager.get_financial_indicator(ts_code, period)`，通过 Tushare/BaoStock/AkShare 数据源链获取财务指标数据。

**输出:** `GetFinancialIndicatorOutput` 包含 `data: List[Dict[str, Any]]`，含 `eps`、`roe`、`grossprofit_margin`、`netprofit_margin` 等字段。

### 3.4 GetNewsSentimentTool -- 新闻舆情

**工具名:** `get_news_sentiment`

**输入:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `ts_code` | string | 否 | 股票代码 |
| `keyword` | string | 否 | 关键词（使用正则匹配） |
| `limit` | int | 否 | 返回条数，默认 10 |

**执行逻辑:**
1. 若提供 `keyword`，构建 `$or` 查询：`{"title": {"$regex": keyword}}` 或 `{"content": {"$regex": keyword}}`
2. 从 MongoDB `news` 集合查询，按 `datetime` 降序

**输出:** `GetNewsSentimentOutput` 包含 `data: List[Dict[str, Any]]`，含 `title`、`content`、`datetime`、`sentiment` 等。

### 3.5 SearchSimilarReportsTool -- 相似研报检索 (RAG)

**工具名:** `search_similar_reports`

**输入:**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | 是 | 查询内容 |
| `ts_code` | string | 否 | 股票代码过滤 |
| `top_k` | int | 否 | 返回数量，默认 5 |

**执行逻辑:**
1. 调用 `llm_manager.embedding([query])` 生成查询向量
2. 调用 `milvus_manager.search_reports(query_vector, top_k, ts_code)` 进行向量相似度检索
3. 若 Milvus 未启用或连接失败，返回错误

**输出:** `SearchSimilarReportsOutput` 包含 `data: List[Dict[str, Any]]`，含相似度得分、研报内容片段、来源等。

---

## 4. Redis 消息协议

### 4.1 请求格式 (`ToolRequest`)

从 Redis 队列接收的 JSON 结构：

```json
{
  "tool_name": "get_stock_daily",
  "message_id": "msg_abc123",
  "trace_id": "trace_xyz789",
  "arguments": {
    "ts_code": "000001.SZ",
    "start_date": "20240601",
    "end_date": "20240607"
  }
}
```

### 4.2 响应格式 (`ToolResponse`)

通过 Redis `publish_result` 发布的 JSON 结构：

```json
{
  "request_id": "msg_abc123",
  "success": true,
  "result": {
    "success": true,
    "execution_time_ms": 45.2,
    "data": [...]
  },
  "error": null,
  "execution_time_ms": 45.2
}
```

### 4.3 错误路由

| 场景 | 处理方式 |
|------|----------|
| 工具不存在 | `ToolResponse(success=False, error="Tool not found: xxx")` |
| 输入解析失败 | `BaseTool.__call__` 捕获 Pydantic 校验异常 |
| 工具执行异常 | `BaseTool.__call__` 捕获，设置 `success=False` + `error_message` |
| Redis 队列异常 | `MCPNode.run()` 主循环捕获，sleep 1s 后继续 |

---

## 5. 配置依赖

| 配置项 | 说明 | 来源 |
|--------|------|------|
| `NODE_TYPE=mcp` | 指定启动 MCP 节点 | 环境变量 |
| `MCP_PORT` | MCP 节点端口，默认 9000 | 环境变量 |
| `MONGO_*` | MongoDB 连接 | 全局配置 |
| `REDIS_*` | Redis 消息队列 | 全局配置 |
| `TUSHARE_TOKEN` | Tushare 数据源令牌 | 全局配置 |
| `LLM_PROVIDER` / `LLM_API_KEY` | LLM Embedding 服务 | 全局配置 |
| `MILVUS_*` | Milvus 向量数据库连接 | 全局配置 |

---

## 6. 数据流

```
Inference Graph (LangChain/LangGraph)
  │
  │  LLM 决策需要数据 → Function Calling
  │  通过 gRPC 或直接 Redis 入队
  ▼
Redis Queue (mcp_tool_requests)
  │
  │  MCPNode.run() 消费
  ▼
MCPNode._handle_tool_request()
  │
  ├─ tool_name = "get_stock_basic"      → GetStockBasicTool      → MongoDB stock_basic
  ├─ tool_name = "get_stock_daily"      → GetStockDailyTool      → MongoDB stock_daily / Tushare
  ├─ tool_name = "get_financial_indicator" → GetFinancialIndicatorTool → data_source_manager
  ├─ tool_name = "get_news_sentiment"   → GetNewsSentimentTool   → MongoDB news (regex)
  └─ tool_name = "search_similar_reports" → SearchSimilarReportsTool → Milvus + LLM Embedding
  │
  ▼
Redis Publish (mcp_tool_responses)
  │
  ▼
Inference Graph 消费结果，继续推理循环
```
