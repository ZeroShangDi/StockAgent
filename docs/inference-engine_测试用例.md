# 推理引擎 测试用例

## TC-INF-01: 个股分析完整流程（首轮通过）

**测试目标：** 验证股票分析从数据采集到输出的完整首轮流程，置信度达标直接输出结果。

**被测组件：** `InferenceNode._process_task()` → `StockAnalysisGraph.analyze_stock()` → 全节点链路

**前置条件：**
- MongoDB 中存在有效的 `stock_basic`（含 PE/PB/industry/total_mv）、`stock_daily`（>=60 条）、`fina_indicator`（>=8 条）数据
- Redis 任务队列可用
- LLM 服务正常
- MongoDB `tasks` 集合存在

| 步骤 | 操作 | 预期结果 |
|---|---|---|
| 1 | 向 Redis 队列推送 `stock_analysis` 任务（`ts_code="600519.SH"`） | 任务成功入队 |
| 2 | `InferenceNode.run()` 通过 BRPOP 消费任务 | 任务被正确解析为 `AgentTask` |
| 3 | 调用 `analyze_stock()` | 进入 LangGraph 工作流 |
| 4 | `data_collect_node` 执行 | 返回 `stock`（含 name/industry/pe/pb）、`daily_data`（60 条）、`fina_data`（8 条），推理链记录 step_id=1 |
| 5 | `fundamental_node`、`technical_node`、`sentiment_node` 并行执行 | 三个节点同时完成，分别返回 `fundamental_res`、`technical_res`、`sentiment_res`（非空字符串），首轮保存 `initial_*_res` |
| 6 | `supervisor_node` 执行 | 返回 `structured_summary`（三面各 <=50 字）、`analysis_conflicts`（可能为空或 0-N 条）、`confidence_score.overall`（0-100）、`signal`（如 `buy`/`hold`/`sell`）、`decision_reason`、`scores`、`risks`，`reasoning_steps` 新增一条 RoundSummary |
| 7 | `check_result_node` 执行，置信度 >= 60 | `needs_refinement=False`，不触发精炼循环 |
| 8 | `build_output` 构建最终报告 | 包含 20+ 字段：`trace_id`、`signal`、`confidence`、`summary`、`scores`、`fundamental_analysis`、`technical_analysis`、`sentiment_analysis`、`structured_summary`、`analysis_conflicts`、`confidence_score`、`risks`、`reasoning_chain`（完整 4 步）、`retry_count=0`、`round_history`（1 轮） |
| 9 | 进度回调发布 | 依次收到 0% → 10% → 30% → 55% → 65% → 95% → 100% 进度消息 |
| 10 | MongoDB `tasks` 集合更新 | 状态为 `completed`，`execution_time_ms` > 0，`result` 字段包含完整输出 |
| 11 | Redis Pub/Sub 发布结果 | `AgentResponse` 包含 `status=COMPLETED` 和完整 `result` |

---

## TC-INF-02: 置信度检查与迭代精炼

**测试目标：** 验证当综合置信度低于阈值时，触发精炼循环（Query Refinement → MCP Search → 增量分析 → 重新评估）的完整流程。

**被测组件：** `check_result_node` → `query_refinement_node` → `mcp_search_node` → 增量 `fundamental_node`/`technical_node`/`sentiment_node` → `supervisor_node` (Round 2)

**前置条件：**
- 同 TC-INF-01
- 模拟或使用一只数据不完整的股票（如 `fina_indicator` 仅有 1-2 条记录），使 LLM 给出较低置信度

| 步骤 | 操作 | 预期结果 |
|---|---|---|
| 1 | 触发股票分析，Supervisor Round 1 输出 `confidence_score.overall=45`（< 60） | 置信度低于阈值 |
| 2 | `check_result_node` 执行 | `needs_refinement=True`，`reasoning_chain` 新增 step |
| 3 | 条件路由 `route_after_check` | 返回 `"refinement"`，进入精炼分支 |
| 4 | `query_refinement_node` 执行 | 生成 `refinement_queries`（1-3 条），每条包含 `tool`、`query`、`target_conflict`、`expected_evidence`；`retry_count` 从 0 递增到 1 |
| 5 | LLM 生成 query_refinement 失败 | 使用默认查询兜底：`get_stock_daily`（成交量变化）+ `get_news_sentiment`（资金流向新闻） |
| 6 | `mcp_search_node` 执行 | `mcp_tool_calls` 列表含每个工具的执行记录（`tool`/`query`/`result`/`success`）；`mcp_evidence` 列表含补充证据；`supplementary_data` 列表（`SupplementaryData` 包含 `source`/`target_conflict`/`content`） |
| 7 | 增量 `fundamental_node` 执行（Round 2） | 接收 `is_refinement=True`、`previous_conclusion`（首轮 `initial_fundamental_res`）、`previous_issues`、`supplementary_data`（匹配 fundamental 的工具），输出包含修正说明 |
| 8 | 增量 `technical_node` 执行（Round 2） | 同上模式，接收匹配 technical 的 supplementary_data |
| 9 | 增量 `sentiment_node` 执行（Round 2） | 同上模式 |
| 10 | `supervisor_node` 执行（Round 2） | 接收 `reasoning_steps`（含 Round 1 摘要）、`previous_issues`、`mcp_evidence`，输出包含"上轮问题解决情况"（`resolved`/`unresolved`） |
| 11 | `build_output` 最终报告 | `retry_count=1`、`round_history` 含 2 轮记录、`mcp_tool_calls` 非空、`supplementary_data` 非空 |

---

## TC-INF-03: 精炼循环最大重试限制

**测试目标：** 验证当精炼后置信度仍然不足时，最多重试 2 次即终止。

**被测组件：** `check_result_node` + 条件路由

**前置条件：** 配置 `MAX_RETRY_COUNT=2`

| 步骤 | 操作 | 预期结果 |
|---|---|---|
| 1 | 触发分析，Round 1 置信度=35 | `needs_refinement=True`，执行精炼循环 |
| 2 | Round 2 精炼完成后，Supervisor 再次输出置信度=50（仍 < 60） | `retry_count=1` |
| 3 | `check_result_node` 再次执行 | `retry_count=1`，`1 < MAX_RETRY_COUNT(2)` → `needs_refinement=True` |
| 4 | 执行第二次精炼循环 | Round 3 分析，`retry_count=2` |
| 5 | Round 3 精炼完成后，Supervisor 输出置信度=55（仍 < 60） | `retry_count=2` |
| 6 | `check_result_node` 第三次执行 | `retry_count=2`，`2 >= MAX_RETRY_COUNT(2)` → `needs_refinement=False`，不再进入精炼 |
| 7 | 直接进入 `build_output` | 输出以最后一次结果为准，`retry_count=2`，`round_history` 含 3 轮记录 |

---

## TC-INF-04: Supervisor 协调与信号生成

**测试目标：** 验证 Supervisor 正确解析 LLM JSON 输出，生成投资信号、置信度评分和冲突列表。

**被测组件：** `supervisor_node`（`_parse_json_response`、信号映射、结构化摘要构建）

**前置条件：** 已向 Supervisor 传入完整的三方分析文本（fundamental_res / technical_res / sentiment_res）

| 步骤 | 操作 | 预期结果 |
|---|---|---|
| 1 | LLM 返回标准 Supervisor JSON（含"投资信号"= "强烈买入"） | `signal` 映射为 `SignalType.STRONG_BUY.value` |
| 2 | LLM 输出含 `置信度评估.综合置信度=75` | `confidence_score.overall=75`，`confidence=0.75` |
| 3 | LLM 输出含 2 个逻辑冲突（如"量价背离"、"消息驱动"） | `analysis_conflicts` 列表含 2 条，每条含 `conflict_type`/`description`/`resolution` |
| 4 | LLM 输出含"结构化摘要.技术面"核心结论 | `structured_summary.technical_core` 被正确提取 |
| 5 | LLM 输出含"风险提示"列表 | `risks` 列表非空 |
| 6 | LLM 输出含"各维度评分"（基本面:70, 技术面:65, 舆情:55） | `scores` 为 `{"fundamental": 70, "technical": 65, "sentiment": 55}` |
| 7 | LLM 响应不含合法 JSON（仅纯文本） | `_parse_json_response` 返回 `{}`，信号默认为 HOLD，置信度为默认值，不抛异常 |
| 8 | LLM 输出 JSON 包裹在 markdown 代码块中（```json ... ```） | 正则正确提取并解析 |
| 9 | 增量轮次（Round 2）LLM 输出含"上轮问题解决情况" | `resolved` / `unresolved` 列表被正确记录 |

---

## TC-INF-05: 大盘分析完整流程 (V2.3)

**测试目标：** 验证大盘分析的数据采集、预处理、LLM 分析和对冲校验的完整流程。

**被测组件：** `StockAnalysisGraph.analyze_market()` + `_hedge_check_market_result()`

**前置条件：**
- MongoDB 中存在 `daily_stats`（>=10 条）、`market_analysis`（>=10 条）、`sector_ranking`、`index_daily`（`000001.SH`）数据
- LLM 服务正常

| 步骤 | 操作 | 预期结果 |
|---|---|---|
| 1 | 调用 `analyze_market()` | 开始 V2.3 大盘分析 |
| 2 | 数据采集：读取 `daily_stats`（10 条）、`market_analysis`（10 条）、`sector_ranking`（TOP10）、上证指数 K 线（10 条） | 四条数据均成功获取，日志输出条数 |
| 3 | 逻辑预处理：计算 5 日均量、情绪趋势、背离检查 | `volume_change_pct`/`volume_status` 有值，`sentiment_trend` 含变化量，`divergence` 为"无"或具体背离描述（看涨/诱多） |
| 4 | 上证指数分析：计算连阳天数 | `consecutive_up_days` >= 0，`sh_index_snapshot` 含 10 条 K 线 |
| 5 | 构建 LLM prompt（含 10 日趋势快照 + 板块 TOP10） | `trend_snapshot` 含 10 条记录（情绪/强度/涨停/跌停/最高板/成交额），`sector_snapshot` 含 10 条板块（涨幅/净流入/排名趋势） |
| 6 | LLM 返回 JSON（cycle / signal / risk_score / position_advice / tomorrow_outlook 等） | 所有字段被正确解析，`cycle` 映射为英文值（`ice_point`/`climax` 等），`signal` 映射为标准信号值 |
| 7 | LLM 返回 `risk_score=85` 且 `signal=buy` | `_hedge_check_market_result` 触发风险对冲：`signal` 强制改为 `hold`，`summary` 追加防守修正说明 |
| 8 | LLM 返回 cycle="退潮冰点期" 且 `position_advice` 含 "建议仓位 60%" | 触发仓位对冲警告，`hedge_warnings` 列表非空 |
| 9 | LLM JSON 格式错误 | 回退使用 LLM 原始响应作为 `summary`，不中断流程 |
| 10 | `daily_stats` / `market_analysis` 中部分字段为 None | 空值填充逻辑使用有效均值替换，不传 None 给 LLM |

---

## TC-INF-06: 自定义查询 RAG 流程 (V2.0)

**测试目标：** 验证意图驱动的多路检索 + RAG 回答生成流程。

**被测组件：** `StockAnalysisGraph.custom_query()` → `_parse_query_intent()` → `_search_milvus()` → `_get_market_stats()` → `_get_stock_snapshots()`

**前置条件：**
- Milvus 服务可用（或不可用时测试降级）
- MongoDB 存在 `daily_stats`、`market_analysis`、`stock_basic`、`stock_daily` 数据
- LLM 服务正常

| 步骤 | 操作 | 预期结果 |
|---|---|---|
| 1 | 查询 "今天大盘怎么样" | `_parse_query_intent` 返回 `intent_type="market"`, `need_market_stats=True` |
| 2 | 查询 "分析一下 600519" | `_parse_query_intent` 返回 `intent_type="stock"`, `ts_codes=["600519.SH"]`, `need_stock_snapshot=True` |
| 3 | 查询 "最近有什么新闻" | `_parse_query_intent` 返回 `intent_type="news"` 或 `"general"` |
| 4 | LLM 意图解析失败 | 回退 `_simple_intent_parse`，基于关键词规则匹配；"大盘" → `market`，"600519" → `stock` 含代码 |
| 5 | 大盘类查询：并行检索 Milvus + `_get_market_stats` | `market_stats` 返回含日期/情绪/周期/涨跌家数/涨停数的结构化文本 |
| 6 | 个股类查询：并行检索 `_get_stock_snapshots`（最多 3 只） | `stock_snapshot` 返回每只股票最近 3 日的收盘/涨跌幅/换手率 |
| 7 | Milvus 检索正常 | `reports` 列表含最多 5 条研报（截取前 400 字符），`news` 列表含最多 5 条新闻片段 |
| 8 | Milvus 服务不可用 | `_search_milvus` 捕获异常，返回 `{type: "milvus", reports: [], news: []}`，不阻断整体流程 |
| 9 | Jinja2 上下文模板渲染 | 当任意数据源非空时生成 `rendered_context`，作为第二个 system message |
| 10 | LLM 生成回答 | 返回 `summary`（完整回答文本）、`intent`（意图解析结果）、`context_sources`（各数据源统计） |

---

## TC-INF-07: 并发任务执行与信号量控制

**测试目标：** 验证并发任务数限制和队列消费的正确性。

**被测组件：** `InferenceNode.run()` + `InferenceNode._process_task()` + `asyncio.Semaphore`

**前置条件：** `MAX_CONCURRENT_TASKS=2`，Redis 队列中有多个待处理任务

| 步骤 | 操作 | 预期结果 |
|---|---|---|
| 1 | 向 Redis 队列推送 5 个 `stock_analysis` 任务 | 5 条任务全部入队 |
| 2 | `InferenceNode.run()` 启动消费循环 | 最多同时有 2 个任务处于 `_process_task` 中（`_current_tasks <= 2`） |
| 3 | 第 3 个任务到达时前 2 个任务仍在处理 | 主循环检测 `_current_tasks >= _max_tasks`，`sleep(0.5)` 后重试 |
| 4 | 前 2 个任务逐一完成 | `_semaphore` 释放后，新任务被拾取，始终不超过 2 个并发 |
| 5 | 所有 5 个任务处理完毕 | Redis 队列为空，MongoDB 中 5 条记录均为 `completed` 或 `failed` |
| 6 | 任务中包含 `tool_name` 字段 | 该任务被跳过（留给 MCP 节点处理），不消耗并发槽位 |
| 7 | 主循环中发生异常（如 Redis 断连） | 日志记录错误，`sleep(1)` 后继续循环，不退出 |

---

## TC-INF-08: 错误处理与故障恢复

**测试目标：** 验证各类异常场景下的容错能力和状态恢复。

**被测组件：** `InferenceNode._process_task()`、各节点的异常处理逻辑

**前置条件：** 基础服务可用（MongoDB / Redis / LLM 至少其一可用）

| 步骤 | 操作 | 预期结果 |
|---|---|---|
| 1 | 股票代码 `ts_code` 不存在于 `stock_basic` | `data_collect_node` 返回 `stock=None`，`stock_name=ts_code`，`daily_data=[]`，不抛异常 |
| 2 | `daily_data` 为空（无行情数据） | `technical_node` 返回 `"无足够的行情数据进行技术分析。"`，不抛异常；`sentiment_node` 仅依赖市场信号（涨跌幅/量能） |
| 3 | `fina_data` 为空（无财务数据） | `fundamental_node` 传入 `has_fina_data=False`、`eps="N/A"` 等占位值，LLM 正常分析 |
| 4 | LLM 调用超时或返回异常 | 节点级异常向上传播至 `_process_task`，catch 后更新 MongoDB 状态为 `FAILED`，记录 `error_message`，发布 `FAILED` 的 `AgentResponse` |
| 5 | MongoDB 写入失败（如网络中断） | `_process_task` 异常处理记录失败状态，Redis 发布失败结果，`_current_tasks` 正确减 1 |
| 6 | Redis Pub/Sub 发布失败 | 不影响主流程，任务状态已写入 MongoDB |
| 7 | `query_refinement_node` LLM 调用失败 | 使用默认查询兜底（`get_stock_daily` + `get_news_sentiment`），`reasoning` 记录"默认补充量价和资金数据" |
| 8 | MCP 工具 `get_stock_daily` 执行中 MongoDB 查询异常 | 记录 `MCPToolCall(success=False)`，`content_summary="调用失败: {error}"`，不生成 `SupplementaryData`，继续执行其他工具 |
| 9 | MCP 工具 `search_similar_reports` 执行时 Milvus 不可用 | 返回 `"研报检索服务不可用"`，`success=True`（优雅降级，非失败） |
| 10 | `custom_query` 所有检索路均失败 | `reports=[]`, `news=[]`, `market_stats=""`, `stock_snapshot=""`，`rendered_context` 为空，LLM 仅基于用户原始 query 回答 |
| 11 | 大盘分析 JSON 解析失败 (`JSONDecodeError`) | 保留 LLM 原始响应作为 `summary`，使用默认字段值（`signal=hold`, `cycle=current_cycle`, `risk_score=50`），记录 warning 日志 |
| 12 | Node 停止信号 (Ctrl+C)，有任务正在执行 | `InferenceNode.stop()` 等待 `_current_tasks` 降为 0，每秒检查一次 |

---

## TC-INF-09: MCP 工具容错与数据补充

**测试目标：** 验证 MCP 搜索节点的四种工具执行逻辑和 SupplementaryData 生成的正确性。

**被测组件：** `mcp_search_node`（四种工具分支）

**前置条件：** MongoDB 存在 `stock_daily`、`news` 数据，Milvus 状态任意

| 步骤 | 操作 | 预期结果 |
|---|---|---|
| 1 | `refinement_queries` 包含 `{"tool": "get_stock_daily", "query": "获取最近10日成交量变化"}` | 从 MongoDB 查询最近 10 条 `stock_daily`，计算相邻日成交量变化百分比，生成 `content_summary` 如 "近10日成交量变化: +5.2%, -3.1%, ..."，`mcp_evidence` 新增"日线数据"证据 |
| 2 | `refinement_queries` 包含 `{"tool": "get_news_sentiment", "query": "搜索相关新闻"}` | 从 MongoDB `news` 模糊匹配股票名和代码（limit=5），有结果时生成标题列表摘要，`mcp_evidence` 新增"新闻舆情"证据 |
| 3 | `refinement_queries` 包含 `{"tool": "get_financial_indicator", "query": "获取最新财务数据"}` | 返回 `"暂无最新财务数据"`（简化实现） |
| 4 | `refinement_queries` 包含 `{"tool": "search_similar_reports", "query": "搜索相似研报"}` | Milvus 可用时：embedding → `search_reports(top_k=3)`，`mcp_evidence` 新增"研报检索"证据；Milvus 不可用时：返回 `"研报检索服务不可用"` |
| 5 | `refinement_queries` 中某条 item 为字符串格式（非 dict） | 自动转换为 `{"tool": "get_news_sentiment", "query": str_item}` |
| 6 | 所有工具调用完成 | `mcp_tool_calls` 列表长度等于 `refinement_queries` 长度；`supplementary_data` 仅在 `success=True` 且有内容时生成；`mcp_evidence` 累积所有证据条目 |

---

## TC-INF-10: 数据采集节点代码标准化

**测试目标：** 验证 `data_collect_node` 正确标准化不同格式的股票代码，并区分数据为空的情况。

**被测组件：** `data_collect_node` + `_normalize_ts_code()`

**前置条件：** MongoDB 有任意股票数据

| 步骤 | 操作 | 预期结果 |
|---|---|---|
| 1 | `ts_code="002131"` | 标准化为 `"002131.SZ"` |
| 2 | `ts_code="600519"` | 标准化为 `"600519.SH"` |
| 3 | `ts_code="430047"` | 标准化为 `"430047.BJ"` |
| 4 | `ts_code="002131.SZ"` | 保持 `"002131.SZ"`（已完整格式，转大写） |
| 5 | `ts_code="002131.sz"` | 标准化为 `"002131.SZ"`（转大写） |
| 6 | 传入空的 `ts_code` | 返回原值不变，不抛异常 |
| 7 | 数据库中该代码不存在 | `stock=None`, `stock_name=ts_code`, `daily_data=[]`, `fina_data=[]`，推理链步骤正常记录 |
| 8 | 数据库中仅有 15 条 `stock_daily` | `daily_data` 返回 15 条（实际条数，不超过 limit=60） |
| 9 | 数据库中仅有 3 条 `fina_indicator` | `fina_data` 返回 3 条（实际条数，不超过 limit=8） |

---

## 代码走查验证结果

**走查日期**: 2026-06-21 | **方法**: 代码走查 | **结果**: 10/10 通过

| 用例 | 结果 | 走查依据 |
|------|------|----------|
| TC-INF-01 | ✅ PASS (附注) | stock_analysis.py:157-251: data_collect_node 返回 stock/daily_data/fina_data/reasoning_chain(step_id=1); 1370-1374: 三节点 asyncio.gather 并发; 682-891: supervisor_node 构建 structured_summary/confidence_score/signal; 894-932: check_result_node; 1205-1300: build_output 22 字段; 1361-1444: progress callbacks。附注: Step 8 说 reasoning_chain 有 "完整 4 步"，非精炼路径实际产生 3 步（data_collect/supervisor/check_result），fundamental/technical/sentiment 节点不添加 reasoning_chain |
| TC-INF-02 | ✅ PASS | stock_analysis.py:914: confidence<threshold → needs_refinement=True; 1196-1202: route_after_check → "refinement"; 935-1015: query_refinement_node 生成 refinement_queries; 1018-1193: mcp_search_node 执行工具; 388-391/524-527/650-653: 增量分析节点接收 is_refinement=True; 824-829: supervisor 读取上轮问题解决情况; build_output 含 retry_count/round_history/mcp_tool_calls |
| TC-INF-03 | ✅ PASS | stock_analysis.py:1396-1437: while state.needs_refinement 循环支持最多 MAX_RETRY_COUNT=2 次精炼迭代，每次迭代后重新 check_result |
| TC-INF-04 | ✅ PASS | stock_analysis.py:69-77: _parse_json_response 安全返回 {}; 838-846: signal_map 中文映射→SignalType 默认 HOLD; 792-797: structured_summary; 809-814: confidence_score 默认 50; 883-887: scores 各维度; 888: risks。附注: resolved/unresolved 在 supervisor 输出中仅记录日志(line 825-829)，不在返回 dict 中(line 874-891) |
| TC-INF-05 | ✅ PASS | stock_analysis.py:1456-1938: analyze_market 收集 4 数据集(daily_stats/market_analysis/sector_ranking/index_daily); 1610-1633: volume_change_pct/volume_status; 1677-1691: sentiment_trend; 1698-1727: divergence; 1856-1928: LLM JSON 解析含 cycle_map/signal_map; 1940-2000: _hedge_check (risk_score>80+signal=buy→强制持有; ice_point+position>40%→警告); 1925-1928: JSON 解析失败→raw response 保存为 summary |
| TC-INF-06 | ✅ PASS | stock_analysis.py:2002-2160: custom_query 调用 _parse_query_intent; 2162-2240: intent 解析含 LLM + regex fallback; 2069: asyncio.gather 并发检索(Milvus/market_stats/stock_snapshots); 2274-2276: Milvus 失败返回 {"type":"milvus","reports":[],"news":[]}; 2271: reports 截断 400 字符; 2107-2121: Jinja2 模板渲染 |
| TC-INF-07 | ✅ PASS | node.py:51: _max_tasks; 70: Semaphore(_max_tasks); 95-96: _current_tasks>=max → sleep 0.5s; 120: async with self._semaphore; 106: tool_name 检查跳过 MCP 任务; 114-116: 主循环异常→log+sleep 1s; 280: MAX_CONCURRENT_TASKS=2; 81-86: stop() 等待 _current_tasks→0 |
| TC-INF-08 | ✅ PASS | stock_analysis.py:171: stock=None→stock_name=ts_code; 434-436: daily_data空→early return; 348: has_fina_data=False + "N/A" values; node.py:179-201: LLM 异常→FAILED+error_message; 204: finally 块 decrement; MCP 异常→success=False(line 1151-1156); 1146-1149: Milvus 不可用→"研报检索服务不可用" success=True; 2081-2093: empty results; 1925-1928: JSONDecodeError catch; 81-86: stop() |
| TC-INF-09 | ✅ PASS | stock_analysis.py:1018-1193: get_stock_daily(1059-1087) 查询 stock_daily 计算量比; get_news_sentiment(1095-1125) 查询 news $regex; get_financial_indicator(1089-1093) 返回 "暂无最新财务数据"; search_similar_reports(1127-1149) Milvus 不可用→"研报检索服务不可用" success=True; 1044-1048: 非 dict 项默认 tool="get_news_sentiment"; 1158-1165: mcp_tool_calls 始终追加; 1168-1174: supplementary_data 仅 success+content_summary 时追加 |
| TC-INF-10 | ✅ PASS | stock_analysis.py:129-154: _normalize_ts_code: "002131"→"002131.SZ"; "600519"→"600519.SH"; "430047"→"430047.BJ"; "002131.SZ"→upper(); "002131.sz"→"002131.SZ"; 空字符串→返回原值。171: stock=None 时 stock_name=ts_code; 178: daily_data limit=60; 189: fina_data limit=8 |

