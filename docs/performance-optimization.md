# StockAgent 内存与性能优化方案

## 问题定位

Docker 部署到云服务器后，内存在运行期间持续增长，最终 OOM 导致服务器崩溃。重启后 CPU 不到 10%、内存约 30%，但短时间内再次崩溃。

---

## 根因分析（按严重程度排序）

### 🔴 Critical 1：无限制的 MongoDB 全表扫描

**文件**: `AgentServer/nodes/web/api/market.py`

三个函数直接对 `stock_daily` 集合执行无 `limit` 的全量扫描：

| 函数 | 行号 | 查询数据量估算 |
|------|------|---------------|
| `_scan_stock_period_metrics` | L191 | 5000股 × N个交易日 × ~200B/条 |
| `_build_nextday_win_rate` | L296 | 同上 |
| `_build_streak_rankings` | L344 | 同上 |

**影响**：以 1 年周期（250 个交易日）为例，5000 × 250 = **125 万条文档**加载到 Python 进程内存中，每条文档约 200B，单次请求消耗 **~250MB+**。多个用户并发请求时，内存会被瞬间撑爆。

与之相关的还有：

| 文件 | 行号 | 问题 |
|------|------|------|
| `data_sync/collectors/stock/ths_sector.py` | L144-146 | `.to_list(None)` 无限制加载所有板块数据 |

**MySQL/PostgreSQL 使用游标流式读取是安全的，但 MongoDB 的 `async for doc in cursor` 在 Motor 驱动中会在客户端缓冲大量文档**。

---

### 🔴 Critical 2：Docker 容器无内存限制

`docker-compose.yml` 和 `docker-compose.full.yml` 中所有服务均未设置 `mem_limit` 或 `deploy.resources.limits.memory`。

**影响**：单个容器可以占用全部系统内存，导致整个服务器 OOM。MongoDB、Milvus 等数据库也会无限制占用内存。

---

### 🟠 Major 3：Listener 全市场监控内存问题

**文件**: `AgentServer/nodes/listener/node.py`

当策略包含 `is_all_market()` 时（L419-430），每 60 秒：
1. 拉取 ~5000 只股票的实时行情（L281-288）
2. 构建 `MarketSnapshot` 对象存储全部行情数据（L294-295）
3. `_current_snapshot` + `_previous_snapshot` 各保留一份完整副本

**影响**：单次快照约 5000 × ~500B = 2.5MB，加上两份快照 = 5MB，持续运行内存稳定但高。问题在于全量拉取 5000 只股票的 API 调用开销，以及每次 60s 的轮询间隔下数据源 API 的压力。

**文件**: `AgentServer/nodes/listener/strategies/intraday_price_move.py`

`IntradayPriceMoveStrategy` 维护 `_price_history: Dict[str, Deque[HistoryPoint]]`（L34），在全市场模式下缓存所有 5000 只股票的价格历史，每个 deque 最多保留 `interval_minutes × 3` 分钟的数据点（60s 轮询 = 每只股票 15-30 个点）。

**影响**：5000 × 25 × 16B ≈ 2MB，可控但在极端配置下可能膨胀。

---

### 🟠 Major 4：LLM 内存缓存过大

**文件**: `AgentServer/src/llm/cache.py`

`MemoryCache` 默认 `max_size=1000`，缓存内容包含：
- Chat 响应：LLM 分析报告可达 4K-16K token（16KB-64KB 文本）
- Embedding 向量：1024 维 float 列表（~8KB/条）

**影响**：最坏情况 ~1000 × 64KB = **64MB+**。且 eviction 仅在 `set()` 时触发，高并发下可能远超上限。`MemoryCache` 是模块级全局单例（L417），进程生命周期内不会释放。

---

### 🟡 Medium 5：httpx 连接池无限制

以下位置创建 `httpx.AsyncClient` 时未指定连接池上限：

| 文件 | 行号 |
|------|------|
| `core/managers/notification_manager.py` | L49 |
| `nodes/data_sync/collectors/hot_news.py` | L53 |
| `nodes/data_sync/collectors/news/hot_news.py` | L53 |

此外，`LLMManager` 创建的 `openai.AsyncOpenAI` 内部也使用 httpx，默认连接池上限为 100。

---

### 🟡 Medium 6：MongoDB 的 find_many 缺少投影

多处 `find_many` 调用未使用 `projection` 限定字段，返回完整文档，浪费内存和网络带宽：

- `_load_subscriptions` (listener/node.py L211)：加载策略订阅全文档
- `_get_valid_stocks_from_db` (listener/node.py L1036)：已使用 projection
- `_load_subscriptions` 相关调用

---

### 🟢 Low 7：日志文件累积

虽然使用了 `RotatingFileHandler`，但容器内 `/app/logs` 目录通过 volume 挂载持久化。长期运行下，如果日志级别设为 DEBUG，可能产生大量日志文件。

---

### 🟢 Low 8：Python GC 未调优

未针对长时间运行的容器化 Python 服务进行 GC 调优：
- Python 默认使用引用计数 + 分代 GC
- 分代 GC 在内存压力大时才触发
- 大量短生命周期对象（如 dict、list）可能导致内存碎片

---

## 优化方案

### 方案 1：MongoDB 查询优化（Critical）

**目标**：将全量加载改为数据库端聚合或添加硬限制

**1.1 `_scan_stock_period_metrics` 改造**

改用 MongoDB 聚合管道，在数据库端完成 first/last/min 计算：

```python
async def _scan_stock_period_metrics(start_date: str, end_date: str) -> List[Dict[str, Any]]:
    pipeline = [
        {"$match": {"trade_date": {"$gte": start_date, "$lte": end_date}}},
        {"$sort": {"ts_code": 1, "trade_date": 1}},
        {"$group": {
            "_id": "$ts_code",
            "first_close": {"$first": "$close"},
            "last_close": {"$last": "$close"},
            "min_low": {"$min": "$low"},
            "min_low_date": {"$min": {"$cond": [
                {"$eq": ["$low", "$min_low"]}, "$trade_date", None
            ]}},
        }},
    ]
    # 聚合管道返回聚合后的结果，数量 = 股票数量
    results = await mongo_manager.aggregate("stock_daily", pipeline)
    ...
```

注意：`$first`/`$last` 需要在 `$group` 之前有 `$sort`，且在 `$group` 内部需要额外的 `$push`/`$reduce` 或 `$first`/`$last` accumulator。MongoDB 的 `$first` 会返回 group 中第一个文档的字段值。

**1.2 `_build_nextday_win_rate` 改造**

同样使用聚合管道：

```python
pipeline = [
    {"$match": {"trade_date": {"$gte": start_date, "$lte": end_date}}},
    {"$sort": {"ts_code": 1, "trade_date": 1}},
    {"$group": {
        "_id": "$ts_code",
        "trade_days": {"$sum": 1},
        "up_days": {"$sum": {"$cond": [{"$gt": ["$pct_chg", 0]}, 1, 0]}},
        "returns": {"$push": "$pct_chg"},
    }},
]
```

**1.3 `_build_streak_rankings` 改造**

连胜/连跌计算需要顺序处理，聚合管道较难表达。可以：
- 方案 A：添加 `limit(N)` 分批处理，限制每批处理的股票数
- 方案 B：仅对近期热门股票计算连涨/连跌，减少计算范围
- 方案 C：保持游标遍历但添加批次提交 + 显式 `cursor.close()`

**1.4 `ths_sector.py` 添加限制**

`to_list(None)` → `to_list(500)` 添加合理上限。

---

### 方案 2：Docker 内存限制（Critical）

**目标**：防止单个容器耗尽系统内存

为 `docker-compose.yml` 各服务添加：

```yaml
services:
  web:
    deploy:
      resources:
        limits:
          memory: 512M
        reservations:
          memory: 256M

  data-sync:
    deploy:
      resources:
        limits:
          memory: 512M
        reservations:
          memory: 256M

  listener:
    deploy:
      resources:
        limits:
          memory: 384M
        reservations:
          memory: 192M

  inference:
    deploy:
      resources:
        limits:
          memory: 512M
        reservations:
          memory: 256M

  mongodb:
    deploy:
      resources:
        limits:
          memory: 1G
        reservations:
          memory: 512M

  redis:
    deploy:
      resources:
        limits:
          memory: 256M
        reservations:
          memory: 128M
```

---

### 方案 3：Listener 全市场监控优化（Major）

**目标**：保持全市场监听能力，但降低内存和 API 开销

**3.1 分批拉取 + 流式处理**

```python
# 将全市场 5000 只股票分 5 批，每批 1000 只
BATCH_SIZE = 1000
BATCH_INTERVAL = 12  # 每批间隔 12 秒，5 批 = 60 秒完成一轮

async def _poll_cycle(self, trace_id: str):
    watch_codes = await self._get_all_watch_codes()

    for batch_idx in range(0, len(watch_codes), BATCH_SIZE):
        batch_codes = watch_codes[batch_idx:batch_idx + BATCH_SIZE]
        quotes, source = await data_source_manager.get_realtime_quotes(
            batch_codes,
            batch_size=50,
        )
        # 增量处理这一批
        await self._process_batch(batch_codes, quotes, source)
        if batch_idx + BATCH_SIZE < len(watch_codes):
            await asyncio.sleep(BATCH_INTERVAL)
```

**3.2 Snapshot 瘦身**

`MarketSnapshot` 仅保留策略评估需要的最小字段集：

```python
SNAPSHOT_FIELDS = {"price", "pct_chg", "name", "open", "high", "low", "volume"}
```

**3.3 分层监控策略**

```
Layer 1 (全市场):  仅涨跌幅 > 3%、封板、炸板的股票 → 后续全量监控
Layer 2 (关注池):  自选股 + 持仓股 → 始终全量监控
Layer 3 (异动池):  触发预警后 30 分钟内持续监控
```

这种分层策略下，60s 轮询中：
- 全市场 5000 只：仅拉取基础涨跌幅字段（极轻量）
- 筛选出 ~100 只异动股：拉取完整行情
- 自选/持仓 ~50 只：拉取完整行情

内存从 5MB 降至 ~1MB，API 调用量降低 80%。

---

### 方案 4：LLM 缓存优化（Major）

**目标**：限制缓存内存占用，避免无界增长

**4.1 降低默认 max_size**

```python
# cache.py
class MemoryCache(CacheBackend):
    def __init__(self, max_size: int = 200):  # 1000 → 200
        ...
```

**4.2 添加后台定期清理**

```python
async def start_cleanup_task(self, interval: int = 300):
    """每 5 分钟清理过期条目"""
    async def _cleanup():
        while True:
            await asyncio.sleep(interval)
            self._evict_expired()
    asyncio.create_task(_cleanup())
```

**4.3 推荐启用 Redis 缓存**

在生产环境中设置 `LLM_CACHE_USE_REDIS=true`，将 LLM 缓存从进程内存迁移到 Redis，避免多进程重复缓存。

---

### 方案 5：httpx 连接池限制（Medium）

**目标**：控制 HTTP 连接数

```python
# notification_manager.py
self._client = httpx.AsyncClient(
    timeout=httpx.Timeout(10.0),
    limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
)

# hot_news.py
self.client = httpx.AsyncClient(
    timeout=httpx.Timeout(20.0),
    limits=httpx.Limits(max_keepalive_connections=5, max_connections=20),
)
```

---

### 方案 6：Python GC 与内存监控（Low）

**目标**：及时回收内存，提前发现泄漏

**6.1 定期触发 GC**

在 `BaseNode.main()` 中添加：

```python
import gc

async def _gc_monitor(self):
    while self._running:
        await asyncio.sleep(300)  # 每 5 分钟
        gc.collect()
        # 记录内存使用
        import tracemalloc
        ...
```

**6.2 添加内存使用健康检查端点**

```python
@app.get("/health/memory")
async def memory_health():
    import psutil, os
    process = psutil.Process(os.getpid())
    mem_info = process.memory_info()
    return {
        "rss_mb": mem_info.rss / 1024 / 1024,
        "vms_mb": mem_info.vms / 1024 / 1024,
    }
```

---

### 方案 7：MongoDB 连接池优化（Low）

**目标**：减少空闲连接

当前 `max_pool_size=50`（MongoDB）和 `max_connections=100`（Redis），每个容器内可能保持大量空闲连接。

建议：
- MongoDB `max_pool_size`: 50 → 20（单进程不需要 50 个连接）
- Redis `max_connections`: 100 → 30
- 添加 `minPoolSize` 保持少量热连接

---

## 实施优先级

| 优先级 | 方案 | 预期收益 | 实施难度 |
|--------|------|---------|---------|
| P0 | 方案 1：MongoDB 查询优化 | 消除主要内存泄漏源 | 中 |
| P0 | 方案 2：Docker 内存限制 | 防止 OOM 影响其他服务 | 低 |
| P1 | 方案 3：Listener 分层监控 | 降低 80% 常态内存 | 中 |
| P1 | 方案 4：LLM 缓存优化 | 减少 50MB+ 内存占用 | 低 |
| P2 | 方案 5：httpx 连接池限制 | 防止连接泄漏 | 低 |
| P2 | 方案 6：GC 与内存监控 | 提前发现内存问题 | 低 |
