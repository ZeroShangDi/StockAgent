# 数据采集-新闻 功能说明

## 概述

新闻采集模块包含三大采集器：热点新闻采集（HotNewsCollector）、涨跌停股票新闻采集（StockNewsCollector）和多源聚合采集（MultiSourceCollector，占位）。模块覆盖 10+ 个新闻来源，支持异步并发抓取、统一格式存储、Redis 缓存、MongoDB 持久化和 Milvus 向量化。

---

## 1. HotNewsCollector（热点新闻采集）

- **文件路径**: `nodes/data_sync/collectors/news/hot_news.py`
- **类名**: `HotNewsCollector`
- **用途**: 定时并发抓取多个来源的热点新闻/热搜/快讯，统一存入 Redis（TTL 2 小时），供前端展示使用。
- **存储**: Redis（通过 `redis_manager.set_hot_news(source_id, documents)`），每条数据的 TTL 默认为 2 小时。
- **调度**: 默认 cron `*/30 * * * *`（每 30 分钟），可通过 `SYNC_HOT_NEWS_SCHEDULE` 环境变量覆盖。
- **恢复模式**: `recoverability.mode = "none"` —— 热点榜单和快讯具有强时效性，错过采集窗口后无法可靠还原。
- **总超时**: 通过 `SYNC_HOT_NEWS_TOTAL_TIMEOUT_SECONDS` 控制整个采集轮次的总超时时间。

### 新闻源清单（13 个来源类）

| 来源类 | 来源 ID | 显示名称 | 分类 | API / URL |
|--------|---------|----------|------|-----------|
| `CLSSource` | cls | 财联社 | finance | `https://www.cls.cn/nodeapi/updateTelegraphList` |
| `XueqiuSource` | xueqiu | 雪球 | finance | `https://stock.xueqiu.com/v5/stock/hot_stock/list.json` |
| `WallstreetcnSource` | wallstreetcn | 华尔街见闻 | finance | `https://api-one.wallstcn.com/apiv1/content/lives` |
| `GelonghuiSource` | gelonghui | 格隆汇 | finance | `https://www.gelonghui.com/api/v3/live/list` + 备用 HTML 解析 |
| `Jin10Source` | jin10 | 金十数据 | finance | `https://www.jin10.com/flash_newest.js` |
| `JuejinSource` | juejin | 稀土掘金 | tech | `https://api.juejin.cn/content_api/v1/content/article_rank` |
| `ITHomeSource` | ithome | IT之家 | tech | `https://www.ithome.com/list/`（HTML 解析） |
| `Kr36Source` | 36kr | 36氪 | tech | `https://www.36kr.com/newsflashes`（HTML 解析） |
| `GithubSource` | github | Github | tech | `https://github.com/trending`（HTML 解析 + 备用正则） |
| `DouyinSource` | douyin | 抖音 | entertainment | `https://www.douyin.com/aweme/v1/web/hot/search/list/` |
| `BilibiliSource` | bilibili | 哔哩哔哩 | entertainment | `https://s.search.bilibili.com/main/hotword` |
| `KaopuSource` | kaopu | 靠谱新闻 | world | `https://kaopustorage.blob.core.windows.net/news-prod/news_list_hans_0.json` |
| `ThePaperSource` | thepaper | 澎湃新闻 | china | `https://cache.thepaper.cn/contentapi/wwwIndex/rightSidebar` |

### 来源选择与过滤

- **来源白名单**: 通过 `SYNC_HOT_NEWS_SOURCE_ALLOWLIST` 环境变量（逗号分隔）指定要启用的来源，如 `"cls,xueqiu,jin10"`。不设置则启用全部。
- **来源数量限制**: 通过 `SYNC_HOT_NEWS_MAX_SOURCES_PER_ROUND` 限制每轮采集的来源数（默认值由 `_select_source_classes` 中 `max_sources` 控制）。
- **每条来源的最大条目数**: 通过 `SYNC_HOT_NEWS_MAX_ITEMS_PER_SOURCE` 限制。
- **总开关**: `SYNC_HOT_NEWS_ENABLED=false` 可完全禁用热点新闻采集。

### 采集策略

1. 检查 `SYNC_HOT_NEWS_ENABLED` 开关，禁用时直接跳过。
2. 确保 Redis 已初始化。
3. 根据白名单和数量限制选择要使用的来源类（`_select_source_classes`）。
4. 通过 `asyncio.Semaphore` 控制并发度（`SYNC_HOT_NEWS_MAX_CONCURRENCY`），避免新闻任务挤占核心同步资源。
5. 对每个来源调用 `fetch_with_limit` -> `_fetch_source`:
   - 调用来源的 `fetch()` 方法获取新闻列表。
   - 截取 `max_items` 条。
   - 调用 `_save_items` 写入 Redis。
6. 全部来源抓取有总超时限制（`asyncio.wait_for` + total_timeout），防止单个慢源拖垮整轮。
7. 统计成功/失败来源数，返回结果。

### 新闻数据格式

每条热点新闻在 Redis 中存储为 JSON 文档：
```json
{
  "source": "cls",
  "source_name": "财联社",
  "color": "red",
  "column": "finance",
  "title": "新闻标题",
  "url": "https://...",
  "hot": 25,
  "rank": 5,
  "extra": {"time": 1718928000000},
  "updated_at": "2026-06-20T12:00:00+00:00"
}
```

### 手动刷新接口

- `fetch_single_source(source_id)`: 手动抓取单个来源并立即写入 Redis。
- `refresh(source_id=None)`: API 入口，可指定来源或刷新全部。
- `get_available_sources()`: 获取所有可用来源的元信息列表（id/name/color/column）。

---

## 2. StockNewsCollector（涨跌停股票新闻采集）

- **文件路径**: `nodes/data_sync/collectors/news/stock_news.py`
- **类名**: `StockNewsCollector`
- **用途**: 从 `limit_list` 表获取当日涨跌停股票列表，为每只股票采集最新新闻，保存到 MongoDB 的 `news` 集合，并向量化存入 Milvus 以支持 RAG 检索。
- **数据源**: 通过 `data_source_manager.get_stock_news(symbol, limit)` 调用来获取个股新闻。
- **目标集合**: `news`（MongoDB），去重键 `_key`（由 `ts_code + datetime + title前50字` 组成）
- **向量存储**: Milvus（通过 `milvus_manager.insert_news_batch` 批量插入，每批 10 条）
- **调度**: 默认 cron `30 18 * * 1-5`（每个交易日 18:30，大盘统计完成后），可通过 `SYNC_NEWS_SCHEDULE` 环境变量覆盖。
- **恢复模式**: `recoverability.mode = "best_effort"` —— 可以重新拉取最新新闻，但会丢失当日事件热度和部分实时上下文。
- **注意**: 当前 `collect()` 方法第 65 行有 `return {"count": 0, "message": "skip"}` 早期返回，实际采集逻辑被注释/跳过，处于待激活状态。

### 采集策略（设计意图）

1. 检查今日是否已同步，避免重复采集。
2. 确保数据源已初始化。
3. 从 `limit_list` 表获取当日涨跌停股票列表（`_get_limit_stocks`）：
   - 优先查询当日 `trade_date` 的涨跌停记录。
   - 若无当日数据，回退到最新日期的数据。
   - 提取股票代码并去重（涨停 U 和跌停 D 都采集）。
4. 批量采集新闻（`_get_stock_news_batch`）：
   - 每只股票最多采集 10 条新闻。
   - 每次请求间隔 `asyncio.sleep(0.3)`，避免请求过快。
   - 收集所有新闻到 `news_list`，统计成功/失败数。
5. 保存到 MongoDB（`_save_news`）：
   - 为每条新闻生成唯一键 `_key`。
   - 使用 `mongo_manager.bulk_upsert` 以 `_key` 去重写入 `news` 集合。
6. 向量化存入 Milvus（`_vectorize_news`）：
   - 检查 Milvus 是否可用（`is_disabled()`）。
   - 批量 embedding + 插入，每批 10 条。
7. 记录同步标记。

### 手动调用接口

- `collect_for_stocks(stocks)`: 为指定股票列表采集新闻（不依赖 `limit_list`）。

---

## 3. MultiSourceCollector（多源聚合采集，占位）

- **文件路径**: `nodes/data_sync/collectors/news/multi_source.py`
- **类名**: `MultiSourceCollector`
- **用途**: 多源新闻聚合的占位实现，当前直接跳过。
- **状态**: 未迁入 standalone DataSync，`collect()` 直接返回 `{"count": 0, "skipped": True, "message": "multi_source_news is not yet extracted into standalone DataSync"}`。
- **调度**: 默认 cron `*/5 * * * *`，`run_at_startup = False`。
- **说明**: 该功能依赖旧版 AgentServer 的新闻采集框架（`src/collector/sources/`），后续将按独立模块方式迁移。

---

## 4. 独立新闻源采集器（sources/ 目录）

位于 `nodes/data_sync/collectors/news/sources/`，是完整的新闻采集框架，与 HotNewsCollector 中内嵌的简化版来源类互为补充：

| 文件 | 类名 | 来源 | 数据获取方式 | 优先级 |
|------|------|------|-------------|--------|
| `cls.py` | `CLSSource` | 财联社 | telegraph API, roll_news API, heads API | P3_PRO_MEDIA |
| `eastmoney.py` | `EastMoneySource` | 东方财富 | 快讯 JSONP API, 财富号 HTML 解析 | - |
| `xueqiu.py` | `XueqiuSource` | 雪球 | 7x24 快讯 API, 热股 API (需 session cookie) | - |
| `wallstreetcn.py` | `WallstreetcnSource` | 华尔街见闻 | 快讯 API, 文章 API | - |
| `jin10.py` | `Jin10Source` | 金十数据 | flash_newest.js 解析 | - |
| `gov.py` | `GovSource` | 国务院 | 政策文库搜索 API + 详情页抓取 | P1_OFFICIAL |
| `miit.py` | `MIITSource` | 工信部 | jpaas-publish-server API + 详情页解析 | P2_REGULATOR |
| `juejin.py` | `JuejinSource` | 稀土掘金 | 推荐流 API（后端/前端/AI 分类） | - |
| `thepaper.py` | `ThePaperSource` | 澎湃新闻 | rightSidebar API + 详情网页抓取 | P4_GENERAL_MEDIA |

这些来源类继承自 `src.collector.sources.base.BaseSource`，具有以下通用能力：
- 自动管理 `httpx.AsyncClient`（cookie 保持、UA 伪装、重定向跟随）。
- JSON API 请求（`fetch_json`）和 HTML 页面请求（`fetch_page`）。
- 基于 `content_hash` 的去重（已抓取过的内容不会重复入库）。
- `since` 时间过滤（只保留指定时间之后的新闻）。
- 统一的 `NewsItem` 结构化输出。

---

## 通用机制

### 限流与并发控制

- **HotNewsCollector**: 通过 `asyncio.Semaphore` 限制并发度（`SYNC_HOT_NEWS_MAX_CONCURRENCY`），通过 `asyncio.wait_for` 设置总超时（`SYNC_HOT_NEWS_TOTAL_TIMEOUT_SECONDS`）。
- **StockNewsCollector**: 每只股票间隔 `asyncio.sleep(0.3)`，避免请求过快被封禁。
- **sources/ 中的来源类**: 各自管理 HTTP 请求频率，无中心化限流。

### 新闻去重

- **HotNewsCollector**: 无去重，每次采集全量覆盖 Redis 中的数据（TTL 2 小时自动过期）。
- **StockNewsCollector**: 在 MongoDB 层通过 `_key`（`ts_code + datetime + title前50字`）实现 upsert 去重。
- **sources/ 中的来源类**: 通过 `content_hash` 在当前批次内去重。

### Milvus 向量化

- StockNewsCollector 在保存新闻到 MongoDB 后，调用 `_vectorize_news` 进行向量化：
  - 检查 `milvus_manager.is_disabled()`，若禁用则跳过。
  - 若 Milvus 未初始化则尝试初始化。
  - 调用 `milvus_manager.insert_news_batch(news_list, batch_size=10)` 批量 embedding 并插入。
  - 记录成功/失败数。

### 错误处理

- 所有来源类在 fetch 失败时返回空列表（而非抛出异常）。
- `HotNewsCollector._fetch_source` 在单个来源失败时抛出异常，外层 `asyncio.gather` 以 `return_exceptions=True` 捕获。
- 单个来源失败不影响其他来源的采集。
