# DataSync 迁移边界与灰度计划

本文用于判断什么时候可以用独立 `DataSync/` 服务替换旧 `AgentServer/nodes/data_sync` 节点。结论先行：当前独立 DataSync 已经具备更强的核心行情、股票晴雨表、补缺、探针和运维能力，但正式下线旧链路前仍需要生产灰度验证，并确认生产调度只运行一条 DataSync 链路。

## 1. 当前结论

- 可以优先灰度独立 DataSync：核心行情链路、ready marker、最近窗口补缺、单任务定向补缺、夜间补缺队列和 ops-summary 已经优于旧链路。
- `market_weather` 已迁移到独立 DataSync：保守档会注册，支持定时同步和单交易日定向恢复，但不纳入 `market_core_ready` 硬门槛，避免 Coze 工作流波动拖垮核心行情 ready。
- 不建议两套 DataSync 同时长期运行：两边都写同一批 Mongo 集合，会增加上游请求、Mongo 写入和锁竞争；灰度期必须通过白名单/黑名单明确只让一边负责某类任务。
- 下线旧链路前，应先跑一轮“最近 3-5 个交易日核心数据完整性 + 股票晴雨表数据存在性 + 页面可用性”检查。

## 2. 任务注册对照

| 任务 | 旧 AgentServer DataSync | 独立 DataSync | 替换状态 | 说明 |
| --- | --- | --- | --- | --- |
| `stock_basic` | 有，保守档启用 | 有，核心启用 | 可替换 | 股票基础信息。 |
| `stock_daily` | 有，保守档启用 | 有，核心启用，支持定向恢复 | 可替换 | 新链路支持 checkpoint、缺口恢复和 ready marker。 |
| `daily_basic` | 有，但旧保守档未列入 conservative_names | 有，核心启用，支持定向恢复 | 可替换且新链路更完整 | 根目录环境示例已有调度，独立链路将其纳入核心数据。 |
| `index_basic` | 有，保守档启用 | 有，核心启用 | 可替换 | 指数基础信息。 |
| `index_daily` | 有，保守档启用 | 有，核心启用，支持定向恢复 | 可替换 | 指数日 K 是核心数据。 |
| `moneyflow_industry` | 有，保守档启用 | 有，核心启用，支持定向恢复 | 可替换 | 行业资金流。 |
| `moneyflow_concept` | 有，保守档启用 | 有，核心启用，支持定向恢复 | 可替换 | 概念资金流。 |
| `limit_list` | 有，保守档启用 | 有，核心启用，支持定向恢复 | 可替换 | 涨跌停数据。 |
| `stock_relations` | 有，但旧保守档未列入 conservative_names | 有，核心启用 | 可替换 | 个股关联数据；新链路纳入核心。 |
| `daily_stats` | 有，保守档启用 | 有，核心启用，支持定向恢复 | 可替换 | 股票统计。 |
| `market_statistics_cache` | 有，保守档启用 | 有，核心启用，支持定向恢复 | 可替换 | 行情分析/市场统计缓存。 |
| `market_weather` | 有，旧保守档启用 | 有，核心启用，支持定向恢复 | 可替换，需生产灰度 | 股票晴雨表依赖 Coze 工作流，不纳入 `market_core_ready` 硬门槛。 |
| `review_data` | 有，旧保守档启用 | 有，但独立保守档默认不启用 | 需策略确认 | 可作为 background 后台任务，不建议与核心行情抢资源。 |
| `stock_news` | 有，非保守核心 | 有，background | 可后置 | 非核心，可按需白名单启用。 |
| `hot_news` | 有，默认 5 分钟 | 有，background，默认 30 分钟且可关闭 | 可替换且新链路更安全 | 新链路默认 `SYNC_HOT_NEWS_ENABLED=false`。 |
| `fina_indicator` | 有，heavy | 有，heavy | 可后置 | 财报/因子数据可夜间补，不应影响当日核心。 |
| `ths_sector` | 有，heavy | 有，heavy | 可后置 | 板块数据重任务，建议夜间或手动。 |
| `event_clustering` | 有，旧链路可注册 | 文件存在但独立节点暂未注册 | 暂不替换 | LLM 重任务，后续单独设计资源隔离。 |
| `news_lifecycle` | 有，旧链路可注册 | 文件存在但独立节点暂未注册 | 暂不替换 | 新闻生命周期清理可后置。 |
| `morning_report` / `noon_report` | 旧链路可注册 | 文件存在但独立节点暂未注册 | 暂不替换 | 报告生成不属于核心采集器，可拆到报告服务。 |

## 3. 能力差异

| 能力 | 旧 AgentServer DataSync | 独立 DataSync |
| --- | --- | --- |
| 任务运行档位 | `conservative/full/custom` | `conservative/full/custom`，并按 `core/background/heavy` 分类。 |
| 并发保护 | 节点级 `SYNC_MAX_RUNNING_JOBS` | 节点级预算、heavy 串行、核心 pipeline 活跃计数。 |
| 启动保护 | 可关闭初始同步 | 默认不跑全任务，支持启动后最近窗口核心恢复。 |
| 核心 ready | 无统一 ready marker | 写入 `market_core_ready`，区分 ready/missing/warning/waiting/failed。 |
| 最近缺口恢复 | 基本靠手动任务 | 自动 `core_gap_recovery`，支持最近窗口和最新交易日恢复。 |
| 单任务定向恢复 | 无统一契约 | `recover_job_trade_date` 统一入口，校验交易日和来源结果。 |
| 夜间补缺队列 | 无 | `datasync_backfill_jobs`，支持去重、预算、失败熔断。 |
| 死信/脏数据 | 无统一集合 | `datasync_dead_letters`。 |
| 幂等批量写入 | 分散实现 | `bulk_upsert_batched` 统一批次、主键和错误返回。 |
| 运维探针 | 主要靠日志/RPC | `--health`、`--ready`、`--ops-summary`。 |
| RPC 能力 | `refresh_hot_news` | 增加运行任务、ready、失败记录、ops events、数据源统计、补缺恢复等。 |
| Docker 边界 | 依赖根目录 AgentServer 镜像 | 独立 Dockerfile、独立 Compose、独立 env、独立运行目录。 |

## 4. 数据集合边界

### 可由独立 DataSync 接管的核心集合

- `stock_basic`
- `stock_daily`
- `daily_basic`
- `index_basic`
- `index_daily`
- `moneyflow_industry`
- `moneyflow_concept`
- `limit_list`
- `stock_relations`
- `daily_stats`
- `market_statistics_cache`
- `readiness_markers`
- `data_sync_logs`
- `datasync_ops_events`
- `datasync_checkpoints`
- `datasync_backfill_jobs`
- `datasync_backfill_budgets`
- `datasync_dead_letters`

### 下线旧链路前必须验证的集合

- 股票晴雨表集合：`market_weather_daily` 已由独立 `MarketWeatherTask` 写入，需要在生产灰度时确认最近交易日存在记录。

### 可后置或按需启用的集合

- `review_data` 相关每日复盘子集合。
- `news`、热点新闻、多源新闻相关集合。
- `fina_income`、`fina_balance`、`fina_cashflow`、`fina_indicator`。
- `ths_sectors`、`stock_sector_map`、`sector_stocks`。

## 5. 替换前检查项

1. 确认独立 DataSync 的 `market_weather` 在生产环境能正常调用 Coze 市场指标工作流。
2. 确认 `market_weather_daily` 最近交易日有数据，且市场页展示正常。
3. 确认系统页/市场页读取 `readiness_markers` 和股票晴雨表数据时不会依赖旧 `data_sync_logs` 的旧语义。
4. 明确生产只运行一套 DataSync：要么旧 AgentServer DataSync 关掉，要么旧链路 `SYNC_ENABLED_JOBS` 只保留独立链路未覆盖的任务。

## 6. 灰度部署方案

### 阶段一：影子验证

- 保持旧 AgentServer DataSync 负责生产写入。
- 独立 DataSync 本地或测试库运行 `--check`、`--health`、`--ready`、`--ops-summary`。
- 对照最近 3-5 个交易日核心集合记录数，不开启 full 档。

### 阶段二：核心链路切换

- 独立 DataSync 使用 `SYNC_PROFILE=conservative` 接管核心行情。
- 每天盘后执行 `--ops-summary --require-recent-window-ready`，连续 3 个交易日无缺口后进入下一阶段。

### 阶段三：股票晴雨表验证

- 独立 DataSync 启用并验证 `market_weather`。
- 使用 `recover_job_trade_date` 对最近交易日做一次定向恢复演练。
- 旧 AgentServer DataSync 停止 `data_sync` 节点。
- 保留 Web/Listener/Inference，避免影响用户侧功能。

### 阶段四：旧链路下线

- 将根目录 Compose 的 `data-sync` 服务改为独立 DataSync 或删除旧 data_sync 启动路径。
- 保留旧集合历史数据，不做破坏性迁移。
- 文档中标注旧 `AgentServer/nodes/data_sync` 只读保留或待删除。

## 7. 验收命令

```bash
AgentServer/venv/bin/python DataSync/main.py --check
AgentServer/venv/bin/python DataSync/main.py --health
AgentServer/venv/bin/python DataSync/main.py --ready
AgentServer/venv/bin/python DataSync/main.py --ops-summary --integrity-days 4 --job-log-limit 10
AgentServer/venv/bin/python DataSync/main.py --ops-summary --integrity-days 4 --require-recent-window-ready
```

生产 Docker 环境使用 `docs/DATASYNC_OPERATIONS.md` 中的 `<DS>` 前缀替换本地命令。

## 8. 不做的事

- 不直接删除旧 `AgentServer/nodes/data_sync`。
- 不让两套 DataSync 同时 full 档运行。
- 不为替换旧链路开放 MongoDB 公网端口。
- 不用手动改库伪造 ready 或补数成功状态。
