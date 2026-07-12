# MCP Server 测试用例

## 1. GetStockBasicTool -- 精确查询 / 模糊搜索 / 全量获取

### TC-MCP-001: ts_code 精确查询 -- 命中
- **被测组件:** `GetStockBasicTool`
- **前置条件:** MongoDB `stock_basic` 集合中已存在 `ts_code="000001.SZ"` 的数据
- **步骤:**

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 构造 `GetStockBasicInput(ts_code="000001.SZ")` | 输入校验通过 |
| 2 | `await tool.execute(input_data)` | 返回 `GetStockBasicOutput(success=True, data=[{ts_code:"000001.SZ", name:"平安银行", ...}])` |
| 3 | 检查 `execution_time_ms` | 已自动设置，值 > 0 |

### TC-MCP-002: ts_code 精确查询 -- 未命中
- **被测组件:** `GetStockBasicTool`
- **前置条件:** MongoDB 中不存在 `ts_code="999999.SZ"`
- **步骤:**

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 构造 `GetStockBasicInput(ts_code="999999.SZ")` | 输入校验通过 |
| 2 | `await tool.execute(input_data)` | 返回 `GetStockBasicOutput(success=True, data=[])` |

### TC-MCP-003: name 模糊搜索
- **被测组件:** `GetStockBasicTool`
- **前置条件:** MongoDB 中已存在名称含"平安"的股票
- **步骤:**

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 构造 `GetStockBasicInput(name="平安")` | 输入校验通过 |
| 2 | `await tool.execute(input_data)` | 返回 `data` 列表，length <= 10，每条 name 含"平安" |
| 3 | 校验返回数量 | 不超过 10（limit=10） |

### TC-MCP-004: 无参数 -- 全量获取
- **被测组件:** `GetStockBasicTool`
- **前置条件:** `data_source_manager.get_stock_basic()` 可用
- **步骤:**

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 构造 `GetStockBasicInput()`（不传任何参数） | 输入校验通过 |
| 2 | `await tool.execute(input_data)` | 调用 `data_source_manager.get_stock_basic()`，返回全量列表 |

### TC-MCP-005: 通过 `BaseTool.__call__` 调用 -- 自动计时和错误包装
- **被测组件:** `BaseTool.__call__`（基类框架）
- **前置条件:** 工具正常可用
- **步骤:**

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `result = await tool(GetStockBasicInput(ts_code="000001.SZ"))` | 通过 `__call__` 执行 |
| 2 | 检查 `result.success` | `True` |
| 3 | 检查 `result.execution_time_ms` | > 0，计时正确 |
| 4 | 检查 `result.error_message` | `None` |

### TC-MCP-006: 异常场景 -- 工具执行中抛出异常
- **被测组件:** `BaseTool.__call__` 异常处理
- **前置条件:** 模拟 `execute` 抛出 `ValueError("数据库连接失败")`
- **步骤:**

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | Mock `execute` 抛出异常 | --- |
| 2 | `result = await tool(input_data)` | 返回 `output_model` 实例（不是抛出异常） |
| 3 | 检查 `result.success` | `False` |
| 4 | 检查 `result.error_message` | `"数据库连接失败"` |
| 5 | 检查 `result.execution_time_ms` | > 0 |

---

## 2. GetStockDailyTool -- MongoDB 优先 + Tushare 降级

### TC-MCP-007: MongoDB 有数据 -- 直接返回
- **被测组件:** `GetStockDailyTool`
- **前置条件:** `stock_daily` 集合中 `ts_code="000001.SZ"` 有最近 30 条记录
- **步骤:**

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `await tool.execute(GetStockDailyInput(ts_code="000001.SZ"))` | 从 MongoDB 直接返回 data |
| 2 | 检查 `data` 长度 | <= 30（默认 limit） |
| 3 | 检查排序 | 按 `trade_date` 降序 |
| 4 | 确认未调用 `data_source_manager.get_daily()` | MongoDB 命中即跳过 |

### TC-MCP-008: MongoDB 无数据 -- Tushare 降级
- **被测组件:** `GetStockDailyTool`
- **前置条件:** MongoDB `stock_daily` 中无 `ts_code="000001.SZ"` 的数据
- **步骤:**

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `await tool.execute(GetStockDailyInput(ts_code="000001.SZ"))` | MongoDB 返回空列表 |
| 2 | 自动降级到 `data_source_manager.get_daily()` | 调用 Tushare/BaoStock/AkShare 链 |
| 3 | 检查 `data` | 若有数据，返回 Tushare 结果；若全部数据源失败，返回空列表 |

### TC-MCP-009: 日期范围过滤
- **被测组件:** `GetStockDailyTool`
- **前置条件:** MongoDB 有数据
- **步骤:**

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `GetStockDailyInput(ts_code="000001.SZ", start_date="20240601", end_date="20240607")` | 输入校验通过 |
| 2 | `await tool.execute(input_data)` | 查询条件含 `trade_date >= "20240601" AND <= "20240607"` |
| 3 | 检查 `data` | 所有记录 `trade_date` 在范围内 |

### TC-MCP-010: 自定义 limit
- **被测组件:** `GetStockDailyTool`
- **前置条件:** MongoDB 有足够数据
- **步骤:**

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `GetStockDailyInput(ts_code="000001.SZ", limit=5)` | limit=5 |
| 2 | `await tool.execute(input_data)` | `len(data) <= 5` |

---

## 3. GetFinancialIndicatorTool -- 数据源直连

### TC-MCP-011: 正常查询财务指标
- **被测组件:** `GetFinancialIndicatorTool`
- **前置条件:** `data_source_manager` 可用
- **步骤:**

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `GetFinancialIndicatorInput(ts_code="000001.SZ")` | 输入校验通过 |
| 2 | `await tool.execute(input_data)` | 调用 `data_source_manager.get_financial_indicator()` |
| 3 | 检查 `data` | 含 `eps`、`roe`、`grossprofit_margin` 等字段 |

### TC-MCP-012: 指定报告期查询
- **被测组件:** `GetFinancialIndicatorTool`
- **前置条件:** 数据源有 2024Q1 数据
- **步骤:**

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `GetFinancialIndicatorInput(ts_code="000001.SZ", period="20240331")` | 输入校验通过 |
| 2 | `await tool.execute(input_data)` | 返回对应报告期的财务数据 |

---

## 4. GetNewsSentimentTool -- 关键词正则匹配

### TC-MCP-013: keyword 正则搜索
- **被测组件:** `GetNewsSentimentTool`
- **前置条件:** MongoDB `news` 集合中有标题含"降息"的新闻
- **步骤:**

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `GetNewsSentimentInput(keyword="降息", limit=10)` | 输入校验通过 |
| 2 | `await tool.execute(input_data)` | MongoDB 查询 `$or: [{title: {$regex: "降息"}}, {content: {$regex: "降息"}}]` |
| 3 | 检查 `data` | 每条记录的 title 或 content 含"降息" |
| 4 | 检查排序 | 按 `datetime` 降序 |

### TC-MCP-014: keyword 无匹配
- **被测组件:** `GetNewsSentimentTool`
- **前置条件:** MongoDB `news` 中无匹配关键词的文档
- **步骤:**

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `GetNewsSentimentInput(keyword="不存在的关键词xyz123")` | 输入校验通过 |
| 2 | `await tool.execute(input_data)` | 返回 `data=[]` |

### TC-MCP-015: 无 keyword 全部返回
- **被测组件:** `GetNewsSentimentTool`
- **前置条件:** `news` 集合有数据
- **步骤:**

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `GetNewsSentimentInput(limit=5)`（不传 keyword） | 输入校验通过 |
| 2 | `await tool.execute(input_data)` | 返回最近 5 条新闻，不限关键词 |

---

## 5. SearchSimilarReportsTool -- Milvus 向量检索 + LLM Embedding

### TC-MCP-016: 正常语义搜索
- **被测组件:** `SearchSimilarReportsTool`
- **前置条件:** Milvus 已连接，有研报向量数据；LLM Embedding 可用
- **步骤:**

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `SearchSimilarReportsInput(query="新能源汽车行业前景", top_k=5)` | 输入校验通过 |
| 2 | `await tool.execute(input_data)` | 1) 调用 `llm_manager.embedding()` 生成向量；2) 调用 `milvus_manager.search_reports()` 检索 |
| 3 | 检查 `data` | 返回 top_k 条相似研报，含相似度得分 |

### TC-MCP-017: 带 ts_code 过滤
- **被测组件:** `SearchSimilarReportsTool`
- **前置条件:** Milvus 可用
- **步骤:**

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `SearchSimilarReportsInput(query="财报分析", ts_code="000001.SZ", top_k=3)` | 输入校验通过 |
| 2 | `await tool.execute(input_data)` | `milvus_manager.search_reports()` 收到 `ts_code="000001.SZ"` 过滤参数 |
| 3 | 检查 `data` | 返回的研报均关联 `000001.SZ` |

### TC-MCP-018: Milvus 未启用 -- 错误处理
- **被测组件:** `SearchSimilarReportsTool`
- **前置条件:** Milvus 未连接或 `search_reports` 抛出异常
- **步骤:**

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `SearchSimilarReportsInput(query="测试查询")` | 输入校验通过 |
| 2 | `await tool(input_data)`（通过 `__call__`） | 返回 `SearchSimilarReportsOutput(success=False, error_message="...")` |
| 3 | 确认未抛出未捕获异常 | 返回结构化错误，不中断调用方 |

---

## 6. MCPNode -- Redis 队列消费与工具路由

### TC-MCP-019: 工具路由 -- 已知 tool_name
- **被测组件:** `MCPNode._handle_tool_request`
- **前置条件:** 节点已启动，工具已注册
- **步骤:**

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 构造 `ToolRequest(tool_name="get_stock_basic", message_id="msg_001", arguments={"ts_code": "000001.SZ"})` | --- |
| 2 | `response = await node._handle_tool_request(request)` | 返回 `ToolResponse(request_id="msg_001", success=True, ...)` |
| 3 | 检查 `response.result` | 包含 `data` 字段 |

### TC-MCP-020: 工具路由 -- 未知 tool_name
- **被测组件:** `MCPNode._handle_tool_request`
- **前置条件:** 节点已启动
- **步骤:**

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 构造 `ToolRequest(tool_name="non_existent_tool", message_id="msg_001", arguments={})` | --- |
| 2 | `response = await node._handle_tool_request(request)` | `response.success=False` |
| 3 | 检查 `response.error` | `"Tool not found: non_existent_tool"` |

### TC-MCP-021: Redis 队列消费完整流程
- **被测组件:** `MCPNode.run()` 主循环
- **前置条件:** 节点已启动，Redis 可用
- **步骤:**

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 向 Redis 队列推送一条合法的工具请求 JSON | `redis_manager.enqueue_task(json.dumps({tool_name: "get_stock_basic", message_id: "msg_002", ...}))` |
| 2 | 等待节点消费 | `dequeue_task(timeout=5)` 获取到消息 |
| 3 | 节点执行工具并 `publish_result` | Redis 结果通道收到 `ToolResponse` JSON |
| 4 | 检查响应中的 `request_id` | `"msg_002"` |

### TC-MCP-022: 工具输入参数非法 -- Pydantic 校验失败
- **被测组件:** 工具输入校验 + `MCPNode._handle_tool_request`
- **前置条件:** 节点已启动
- **步骤:**

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 构造 `ToolRequest(tool_name="get_stock_daily", message_id="msg_003", arguments={})`（缺少必填的 ts_code） | --- |
| 2 | `response = await node._handle_tool_request(request)` | `response.success=False` |
| 3 | 检查 `response.error` | 含 Pydantic 校验错误信息（缺少 ts_code） |

### TC-MCP-023: `get_tool_schemas()` -- LLM Function Calling Schema
- **被测组件:** `MCPNode.get_tool_schemas()`
- **前置条件:** 节点已启动，5 个工具均已注册
- **步骤:**

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | `schemas = node.get_tool_schemas()` | 返回长度为 5 的列表 |
| 2 | 检查每个 schema 结构 | 含 `name`、`description`、`parameters` |
| 3 | 检查 `parameters` | 含 `type: "object"`、`properties`、`required` 等标准 JSON Schema 字段 |
| 4 | 校验所有 name | `["get_stock_basic", "get_stock_daily", "get_financial_indicator", "get_news_sentiment", "search_similar_reports"]` |

---

## 代码走查验证结果

**走查日期**: 2026-06-21 | **方法**: 代码走查 | **结果**: 23/23 通过

| 用例 | 结果 | 走查依据 |
|------|------|----------|
| TC-MCP-001 | ✅ PASS | stock_basic.py:32-52: execute() ts_code → find_one with ts_code.upper() (line 36-40), output_model=GetStockBasicOutput (line 30) |
| TC-MCP-002 | ✅ PASS | stock_basic.py:36-40: find_one returns None → data=[] (line 40), success=True (ToolResult default) |
| TC-MCP-003 | ✅ PASS | stock_basic.py:41-47: name → find_many with $regex, limit=10 |
| TC-MCP-004 | ✅ PASS | stock_basic.py:48-50: 无ts_code且无name → data_source_manager.get_stock_basic() 全量获取 |
| TC-MCP-005 | ✅ PASS | tool.py:67-81: __call__ wraps execute, sets execution_time_ms (line 73), catches exceptions→output_model(success=False) (line 77-80) |
| TC-MCP-006 | ✅ PASS | tool.py:75-81: execute 抛异常 → catch, output_model(success=False, error_message=str(e), execution_time_ms) |
| TC-MCP-007 | ✅ PASS | stock_daily.py:34-59: MongoDB find_many with sort trade_date desc, limit=30, not empty→returns directly |
| TC-MCP-008 | ✅ PASS | stock_daily.py:52-57: data empty → data_source_manager.get_daily() fallback chain |
| TC-MCP-009 | ✅ PASS | stock_daily.py:37-42: start_date → filter_query["trade_date"]["$gte"], end_date → ["$lte"] |
| TC-MCP-010 | ✅ PASS | stock_daily.py:17-18: limit default=30, passed to find_many limit (line 48) |
| TC-MCP-011 | ✅ PASS | financial.py:32-39: execute calls data_source_manager.get_financial_indicator(ts_code, period) |
| TC-MCP-012 | ✅ PASS | financial.py:15-16: period Optional[str]=None, passed through to get_financial_indicator (line 36) |
| TC-MCP-013 | ✅ PASS | news.py:33-50: keyword → $or title/content $regex, sort datetime desc, limit |
| TC-MCP-014 | ✅ PASS | news.py:37-41: keyword unmatched → find_many returns [], GetNewsSentimentOutput(data=[]) |
| TC-MCP-015 | ✅ PASS | news.py:36-48: no keyword → filter_query={}, returns recent <limit> news |
| TC-MCP-016 | ✅ PASS | search.py:33-46: llm_manager.embedding to vector, milvus_manager.search_reports with query_vector/top_k/ts_code |
| TC-MCP-017 | ✅ PASS | search.py:16-17: ts_code Optional[str]=None, passed to search_reports (line 43) |
| TC-MCP-018 | ✅ PASS | tool.py:75-81: execute 抛异常 → catch → output_model(success=False, error_message=str(e)), call 不抛出未捕获异常 |
| TC-MCP-019 | ✅ PASS | node.py:118-151: _handle_tool_request finds tool by name (line 122-127), builds input (line 133), calls tool (line 136), returns ToolResponse with result (line 138-144) |
| TC-MCP-020 | ✅ PASS | node.py:122-127: tool_name not in _tools → ToolResponse(success=False, error=f"Tool not found: {tool_name}") |
| TC-MCP-021 | ✅ PASS | node.py:73-101: run() dequeues from Redis (line 76), tool_name check (line 82), _handle_tool_request (line 89), publish_result (line 92-95) |
| TC-MCP-022 | ✅ PASS | node.py:131-133: input_data = tool.input_model(**request.arguments), Pydantic 校验失败 → ValidationError 传播至 except (line 146-151) → ToolResponse(success=False, error=str(e)) |
| TC-MCP-023 | ✅ PASS | node.py:164-166: get_tool_schemas() returns [tool.get_schema() for tool in self._tools.values()]; 5 tools registered (line 105-111); get_schema (tool.py:83-89) returns name/description/parameters (model_json_schema) |
