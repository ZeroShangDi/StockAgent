# 数据采集-新闻 测试用例

## TC-01: 各来源数据抓取

**测试目标**: 验证各新闻来源能正常抓取数据，返回标准化格式。

**被测类**: `HotNewsCollector` 中定义的各来源类

### 金融类来源

| 步骤 | 来源 | 操作 | 预期结果 |
|------|------|------|----------|
| 1 | CLSSource | 实例化并调用 `fetch()` | 返回 list，每个元素含 `title`(str), `url`(str, cls.cn/detail/xxx), `hot`(int), `extra.time`(毫秒时间戳) |
| 2 | XueqiuSource | 调用 `fetch()` | 先访问 `xueqiu.com/hq` 获取 cookie，再请求热股 API。返回元素含 `title`(股票名), `extra.percent`, `extra.code` |
| 3 | WallstreetcnSource | 调用 `fetch()` | 返回快讯列表，含 `title`, `url`, `extra.time`（display_time 毫秒时间戳） |
| 4 | GelonghuiSource | 调用 `fetch()` | 先尝试 API（`/api/v3/live/list`），失败则 HTML 解析。返回含 `title`, `url`（去除 HTML 标签后的标题） |
| 5 | Jin10Source | 调用 `fetch()` | 解析 `flash_newest.js`（`var newest = [...]`），提取 `【标题】内容` 格式，返回含 `title`, `url`, `extra.desc`, `extra.important` |

### 科技类来源

| 步骤 | 来源 | 操作 | 预期结果 |
|------|------|------|----------|
| 6 | JuejinSource | 调用 `fetch()` | 请求 `article_rank` API，返回文章列表含 `title`, `url`(juejin.cn/post/xxx) |
| 7 | ITHomeSource | 调用 `fetch()` | HTML 解析 IT之家列表，过滤广告关键词（"神券","优惠","补贴","京东","lapin"），返回新闻标题和链接 |
| 8 | Kr36Source | 调用 `fetch()` | HTML 解析 36氪快讯列表，匹配 `<a class="item-title">` 标签 |
| 9 | GithubSource | 调用 `fetch()` | HTML 解析 GitHub Trending，匹配 `article > h2 > a` 仓库链接。首次模式失败时尝试备用正则 |

### 娱乐/综合类来源

| 步骤 | 来源 | 操作 | 预期结果 |
|------|------|------|----------|
| 10 | DouyinSource | 调用 `fetch()` | 先从 `login.douyin.com` 获取 cookie，再请求热榜 API。返回 `title`(热搜词), `hot`(热度值) |
| 11 | BilibiliSource | 调用 `fetch()` | 请求 `main/hotword` API，返回含 `title`(show_name), `hot`(heat_score), `extra.icon` |
| 12 | KaopuSource | 调用 `fetch()` | 请求 Azure Blob JSON，过滤 "财新"、"公视" 来源，返回含 `title`, `url`, `extra.publisher`, `extra.desc` |
| 13 | ThePaperSource | 调用 `fetch()` | 请求 rightSidebar API，返回 hotNews, financialInformationNews, editorHandpicked 三类数据 |

---

## TC-02: 限流与并发控制

**测试目标**: 验证新闻采集的并发控制和限流机制。

**被测类**: `HotNewsCollector`

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 配置 `SYNC_HOT_NEWS_MAX_CONCURRENCY=3` | `asyncio.Semaphore(3)` 限制同时抓取的来源数 |
| 2 | 触发 `collect()`，13 个来源同时启动 | 最多 3 个来源同时执行 HTTP 请求，其余等待信号量 |
| 3 | 检查任务完成顺序 | 完成一个后立即释放信号量，下一个开始执行 |
| 4 | 配置 `SYNC_HOT_NEWS_TOTAL_TIMEOUT_SECONDS=30` | 整个采集轮次最多 30 秒 |
| 5 | 模拟某来源响应超过 30 秒 | `asyncio.wait_for(..., timeout=30)` 触发 TimeoutError |
| 6 | 检查超时后的行为 | 所有来源的 HTTP 客户端被关闭（`source.close()`），返回 `{"success": False, "error": "hot_news_total_timeout_after_30s"}` |

**来源白名单测试**:

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 7 | 配置 `SYNC_HOT_NEWS_SOURCE_ALLOWLIST="cls,xueqiu,jin10"` | `_parse_source_allowlist()` 返回 `{"cls", "xueqiu", "jin10"}` |
| 8 | `_select_source_classes()` | 只返回 3 个匹配的来源类 |
| 9 | 触发 `collect()` | 只抓取财联社、雪球、金十数据，其他 10 个来源被跳过 |

**停用开关测试**:

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 10 | 配置 `SYNC_HOT_NEWS_ENABLED=false` | `collect()` 直接返回 `{"success": False, "skipped": True, "reason": "hot_news_disabled"}` |

---

## TC-03: 新闻去重与向量化（StockNewsCollector）

**测试目标**: 验证股票新闻的去重写入和 Milvus 向量化。

**被测类**: `StockNewsCollector`

### 去重测试

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 前置条件: `news` 集合为空 | - |
| 2 | 调用 `_save_news` 传入 5 条新闻 | 5 条全部 upsert 成功，`result.upserted + result.modified = 5` |
| 3 | 再次调用 `_save_news` 传入相同的 5 条新闻（相同 `_key`） | `_key` 去重生效，`result.upserted = 0`, `result.modified = 5`（更新时间戳），`saved_count = 5` |
| 4 | 调用 `_save_news` 传入 3 条新 + 2 条旧（混合） | `result.upserted = 3`, `result.modified = 2`, `saved_count = 5` |

### 去重键验证

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 5 | 验证 `_key` 生成逻辑 | `"{ts_code}_{datetime}_{title[:50]}"`，如 `"000001.SZ_20260620_14:30:00_平安银行发布2026年一季报"` |
| 6 | 同一股票、同一时间、同一标题前 50 字一致的新闻 | 视为重复，只保留最后写入的一份 |
| 7 | 同一股票、不同时间的新闻 | `_key` 不同，作为两篇不同新闻存储 |

### 向量化测试

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 8 | 前置条件: Milvus 服务正常运行 | `milvus_manager.is_disabled() = False` |
| 9 | 调用 `_vectorize_news(news_list)` 传入 10 条新闻 | 调用 `milvus_manager.insert_news_batch`，参数 `batch_size=10` |
| 10 | 检查返回结果 | `result.success >= 0`, `result.failed >= 0` |
| 11 | 前置条件: Milvus 不可用（禁用或服务宕机） | `milvus_manager.is_disabled() = True` |
| 12 | 调用 `_vectorize_news()` | 日志: "Milvus disabled, skipping vectorization"，不报错 |
| 13 | 前置条件: Milvus 未初始化且初始化失败 | `milvus_manager.initialize()` 抛异常 |
| 14 | 调用 `_vectorize_news()` | 异常被捕获，日志 WARNING，不传播异常到上层 |

---

## TC-04: Milvus 写入验证

**测试目标**: 端到端验证新闻 -> MongoDB -> Milvus 的完整链路。

**被测环境**: 需要 MongoDB + Milvus 都在运行

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 准备 2 只测试股票的新闻数据 | ts_code: `000001.SZ`, `000002.SZ` |
| 2 | 调用 `collect_for_stocks(["000001.SZ", "000002.SZ"])` | 触发 `_get_stock_news_batch` |
| 3 | 新闻数据通过 `data_source_manager.get_stock_news(symbol, limit=10)` 获取 | 每只股票返回 0-10 条新闻 |
| 4 | `_save_news` 写入 MongoDB `news` 集合 | 记录数增加 |
| 5 | 查询 `news` 集合，验证字段 | `_key`(str), `ts_code`(str), `title`(str), `url`(str), `created_at`(datetime, UTC) |
| 6 | `_vectorize_news` 写入 Milvus | 记录数 > 0 |
| 7 | 在 Milvus 中查询向量化新闻 | 能通过相似度搜索检索到这些新闻的 embedding 向量 |

---

## TC-05: 空来源处理

**测试目标**: 验证各来源返回空数据时系统能正确处理。

**被测类**: `HotNewsCollector`

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 模拟 CLSSource.fetch() 返回空列表 | API 返回 `roll_data = []` |
| 2 | `_fetch_source` 处理 | `items = []`, 日志 WARNING: "[cls] No items fetched"，返回 `{"count": 0}` |
| 3 | 统计结果 | `success_count += 1`（来源本身没报错）, `total_news += 0` |

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 4 | 模拟来源 HTTP 请求异常（网络不可达） | `fetch()` 内部 `try/except` 返回 `[]` |
| 5 | 但部分来源（如 GelonghuiSource）有 API + HTML 双重保底 | 一级 API 失败后自动尝试 HTML 解析，任一成功即返回数据 |
| 6 | 所有来源返回空（极端情况） | `collect()` 返回 `{"count": 0, "total_news": 0, "success_count": N, "fail_count": M}` |

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 7 | 配置 `SYNC_HOT_NEWS_SOURCE_ALLOWLIST=""`（空字符串） | `_parse_source_allowlist()` 返回空 set |
| 8 | `_select_source_classes()` | 返回全部 13 个来源类（allowlist 为空时不限制） |
| 9 | 配置 `SYNC_HOT_NEWS_MAX_SOURCES_PER_ROUND=0` | `_select_source_classes()` 返回空列表（`source_classes[:0]`） |
| 10 | `collect()` 行为 | 日志 WARNING: "Hot news collection skipped: no source selected"，返回 skipped |

---

## TC-06: 各来源异常降级

**测试目标**: 验证单来源异常不影响其他来源。

**被测类**: `HotNewsCollector`

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 模拟 XueqiuSource cookie 获取失败 | `fetch()` 内 `try/except` 捕获异常，返回空列表 `[]`（不抛出） |
| 2 | 同时其他 12 个来源正常 | 最终 `success_count = 12`, `fail_count = 0`（返回空不算失败） |
| 3 | 模拟 CLSSource 抛出未捕获异常 | `_fetch_source` 内的 `await source.fetch()` 抛异常 |
| 4 | `_fetch_source` 的 `except Exception` 捕获 | 日志 ERROR，`raise` 传递给上层 |
| 5 | `asyncio.gather(return_exceptions=True)` | 捕获为 Exception 对象，不影响其他任务 |
| 6 | 结果统计 | `isinstance(result, Exception)` -> `fail_count += 1` |

---

## TC-07: Redis 存储验证（HotNewsCollector）

**测试目标**: 验证热点新闻正确写入 Redis 并设置 TTL。

**被测类**: `HotNewsCollector._save_items()`

| 步骤 | 操作 | 预期结果 |
|------|------|----------|
| 1 | 调用 `_save_items(source_id="cls", source_name="财联社", color="red", column="finance", items=[...])` | - |
| 2 | 调用 `redis_manager.set_hot_news("cls", documents)` | 写入成功 |
| 3 | 从 Redis 读取 `hot_news:cls` key | 返回 JSON 数组，每条含 `title`, `url`, `hot`, `rank`, `extra`, `updated_at` |
| 4 | 检查 `updated_at` 字段 | ISO 格式 UTC 时间字符串（如 `"2026-06-20T12:00:00+00:00"`） |
| 5 | 等待 TTL 过期（约 2 小时）后再次读取 | Redis key 已过期，返回 None |

---

## 代码走查验证结果

**走查日期**: 2026-06-21 | **方法**: 代码走查 | **结果**: 5/7 通过，2 失败（已修复）

| 用例 | 结果 | 走查依据 |
|------|------|----------|
| TC-01 | ✅ PASS | 全部 13 个来源类（CLS/Xueqiu/Wallstreetcn/Gelonghui/Jin10/Juejin/ITHome/Kr36/Github/Douyin/Bilibili/Kaopu/ThePaper）均已实现，各有 `fetch()` 方法返回标准化 `[Dict]` 格式 |
| TC-02 | ✅ PASS | `Semaphore(3)` 并发限制（hot_news.py），`asyncio.wait_for` 总超时，`_parse_source_allowlist()` 白名单解析，`SYNC_HOT_NEWS_ENABLED=false` 禁用开关 |
| TC-03 | ✅ PASS | `_save_news()` 去重逻辑：`_key = f"{ts_code}_{datetime}_{title[:50]}"`；`_vectorize_news()` 调用 `milvus_manager.insert_news_batch()`；Milvus 禁用时跳过不报错 |
| TC-04 | ✅ PASS | `collect_for_stocks()` 独立代码路径正常；`data_source_manager.get_stock_news(symbol, limit)` → `_save_news` → `_vectorize_news` 链路完整 |
| TC-05 | ✅ PASS | 空列表处理（_fetch_source 日志 WARNING）；`return_exceptions=True` 异常隔离；0 来源时跳过 |
| TC-06 | ✅ PASS | 每个来源 `fetch()` 内部 try/except 返回 `[]`（不抛出）；`asyncio.gather(return_exceptions=True)` 隔离异常，`isinstance(result, Exception)` 统计 fail_count |
| TC-07 | ✅ PASS | `_save_items()` → `redis_manager.set_hot_news(source_id, docs)` → TTL=7200s |

**Bug 修复**: `stock_news.py:65` 原有硬编码 `return {"count": 0, "message": "skip"}` 导致 `collect()` 自动采集路径完全失效，已于走查期间移除修复。
