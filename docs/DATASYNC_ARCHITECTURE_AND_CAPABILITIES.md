# DataSync 重构版技术架构与数据能力说明

本文档描述当前工作区中 `DataSync/` 重构版的数据同步服务设计、已具备的功能能力，以及它能对外提供的数据更新能力。它更接近“能力契约文档”，不是 Web 业务接口文档。

> 注意：当前 `DataSync/` 目录仍是独立重构线的工作区状态，和已经提交到 `AgentServer` 内部 DataSync 的稳定性改造不是同一个交付边界。本文描述的是当前代码具备的设计与能力，生产是否已启用需要以部署配置和镜像版本为准。

## 1. 当前技术架构

### 1.1 服务定位

重构版 `DataSync` 被设计成一个独立的数据同步服务，目标是从原来的 `AgentServer` 内部节点中收敛出来，成为可以单独部署、单独配置、单独诊断的数据服务。

核心定位：

- 负责外部数据源到本地 MongoDB / Redis 的同步。
- 负责核心交易日数据的完整性检查、缺口恢复和就绪标记。
- 负责数据源调用的超时、降级、回退和运行统计。
- 负责向 Web、运维脚本或其他服务提供轻量 RPC 运维能力。
- 不直接承载业务页面逻辑，也不直接定义选股、监听、交易等业务接口。

### 1.2 架构分层

```mermaid
flowchart TD
    CLI["main.py CLI / Docker Entrypoint"] --> Runtime["运行时准备<br/>env / runtime dir / logs / config"]
    Runtime --> Node["DataSyncNode"]
    Node --> Scheduler["APScheduler 定时调度"]
    Node --> RPC["gRPC RPC 服务"]
    Node --> Recovery["核心缺口恢复器"]
    Scheduler --> Jobs["Collectors / Tasks"]
    RPC --> Jobs
    Recovery --> Jobs
    Jobs --> DSM["DataSourceManager<br/>多数据源适配与回退"]
    Jobs --> Mongo["MongoManager<br/>主库写入 / 镜像库尽力同步"]
    Jobs --> Redis["RedisManager<br/>锁 / 热点新闻缓存"]
    Jobs --> LLM["LLMManager<br/>统计分析依赖"]
    DSM --> Sources["Tushare / Baostock / AKShare / Coze"]
    Mongo --> BizCollections["业务数据集合"]
    Mongo --> OpsCollections["sync_records / job_execution_records / readiness_markers / ops_events"]
```

### 1.3 主要模块职责

| 模块 | 职责 |
| --- | --- |
| `DataSync/main.py` | 独立入口，负责加载环境、准备运行目录、执行 CLI 检查/恢复/运维命令，或启动常驻服务。 |
| `DataSync/nodes/data_sync/node.py` | 数据同步节点核心，负责注册任务、定时调度、分布式锁、RPC 方法、核心流水线、缺口恢复、就绪标记。 |
| `collectors/` | 原始数据采集器，负责从外部数据源拉取股票、指数、资金流、复盘、新闻、财务等数据。 |
| `tasks/` | 本地处理任务，负责对已同步数据进行统计、预聚合、缓存化处理。 |
| `services/core_integrity.py` | 核心链路完整性检查，判断最近交易日核心数据是否齐全。 |
| `services/ops_summary.py` | 运维摘要，整合就绪状态、失败任务、运行耗时、数据源退化、运维事件。 |
| `core/managers/data_source_manager.py` | 多数据源统一入口，负责源优先级、超时控制、失败回退、调用统计。 |
| `core/managers/mongo_manager.py` | MongoDB 访问、索引、同步记录、执行记录、就绪标记、主库/镜像库写入状态。 |
| `core/managers/redis_manager.py` | Redis 连接、分布式锁、热点新闻缓存等。 |

### 1.4 常驻运行流程

1. 加载 `DataSync/.env` 或 `DataSync/.env.docker`。
2. 初始化运行目录、日志目录、数据目录和本地 Milvus 路径。
3. 初始化 Redis、MongoDB、数据源管理器、LLM 管理器。
4. 启动 gRPC RPC 服务。
5. 注册所有采集器和处理任务。
6. 注册 APScheduler 定时任务。
7. 注册内部核心缺口恢复任务 `core_gap_recovery`。
8. 如配置允许，启动后延迟执行一次最近窗口缺口恢复。
9. 常驻运行，等待定时任务、RPC 手动触发或恢复任务触发。

### 1.5 核心收盘后流水线

`stock_daily` 成功后，会立即触发一条串行核心流水线：

```text
stock_daily
  -> index_daily
  -> daily_basic
  -> moneyflow_industry
  -> moneyflow_concept
  -> limit_list
  -> stock_relations
  -> daily_stats
  -> market_statistics_cache
```

设计意图：

- 让核心市场页面尽快可用，而不是只等固定 cron 时间。
- 任一环节失败后暂停后续链路，避免错误扩散。
- 保留原 cron 作为兜底重试入口。
- 每个任务都记录执行日志，便于追踪失败位置。

### 1.6 运行保障机制

| 机制 | 当前能力 |
| --- | --- |
| 分布式锁 | 每个任务运行前使用 Redis 锁，避免多个节点重复同步同一天数据。 |
| 执行记录 | 每次任务执行写入 `job_execution_records`，记录触发来源、目标交易日、耗时、状态、错误。 |
| 同步记录 | 数据集同步完成后写入 `sync_records`，保留旧系统兼容口径。 |
| 就绪标记 | 核心链路写入 `readiness_markers`，表达某个交易日核心市场数据是否 ready。 |
| 运维事件 | 核心任务失败、恢复完成、恢复失败等写入运维事件。 |
| 数据源回退 | 核心能力优先使用传统稳定源，单源超时后自动回退。 |
| 数据源统计 | 记录当前进程内每个方法/数据源的成功、失败、超时、空结果、回退情况。 |
| 近期缺口恢复 | 默认每 20 分钟检查最近交易日核心缺口，并尝试恢复。 |
| 主库/镜像库 | 主库是唯一强依赖，镜像库可选，镜像失败不阻断主链路。 |

## 2. 当前能实现的功能

这里列的是“系统功能能力”，不是业务接口。

### 2.1 数据同步功能

| 功能 | 说明 |
| --- | --- |
| 定时同步 | 按 cron 定时执行股票、指数、资金流、复盘、财务、新闻等数据任务。 |
| 手动同步 | 通过 CLI 或 RPC 触发指定任务运行。 |
| 收盘后快速推进 | `stock_daily` 成功后自动推进核心市场链路。 |
| 首次历史补齐 | 部分任务支持首次运行时补一段历史数据，例如 `review_data`。 |
| 最近窗口补缺 | 对最近若干交易日检查核心数据缺口并尝试恢复。 |
| 单任务定向修复 | 对支持 `recover_trade_date` 的任务，按指定交易日进行修复。 |
| 同步跳过 | 已同步数据会按任务口径跳过，降低重复抓取和重复写入。 |

### 2.2 数据完整性与可用性功能

| 功能 | 说明 |
| --- | --- |
| 最新交易日识别 | 通过数据源获取最新交易日，用于判定目标同步日期。 |
| 核心链路完整性检查 | 检查最近 N 个交易日核心数据集是否覆盖完整。 |
| 核心 ready marker | 在核心数据齐全后写入 `market_core_ready` 标记，供 Web 或运维判断可用状态。 |
| 等待窗口识别 | 未到收盘后同步窗口时，不把盘中缺失误判成故障。 |
| 最近窗口严格检查 | 可要求最近 N 个交易日全部 ready，否则命令返回非 0。 |

### 2.3 运维诊断功能

| 功能 | 说明 |
| --- | --- |
| 启动检查 | 检查环境、配置、管理器、调度器、RPC、数据源是否可初始化。 |
| 独立性审计 | 检查 `DataSync/` 是否错误依赖 `AgentServer` 或其他服务目录。 |
| 最近失败任务查询 | 查看最近失败的任务，可限制只看核心任务。 |
| 最近运维事件查询 | 查看自动恢复、核心失败、告警等运维事件。 |
| 核心任务耗时摘要 | 查看近期核心任务成功率、最新耗时、p95 和异常长尾任务。 |
| 数据源调用统计 | 查看不同数据源的成功、失败、超时、回退、空结果情况。 |
| 数据源统计重置 | 重置当前进程内统计窗口，便于观察后续源端状态。 |
| 综合运维摘要 | 一次性输出完整性、主/镜像库、失败任务、事件、运行耗时、数据源退化。 |

### 2.4 资源保护功能

| 功能 | 说明 |
| --- | --- |
| 核心任务源超时 | 对核心数据源调用增加保守超时，避免单源卡死整条链路。 |
| 串行指数同步 | `index_daily` 只抓 3 个核心指数，采用串行方式降低波动。 |
| 高频任务隔离意识 | `hot_news` 被识别为高频高请求量任务，后续应继续与核心链路隔离。 |
| 镜像库降级 | 镜像写失败只记 warning，不影响主库同步。 |
| 启动后延迟恢复 | 启动时恢复任务延迟执行，降低启动瞬间资源峰值。 |

## 3. 数据更新服务能力目录

这一节按“数据能力”描述，每一行都可以理解成一个内部数据更新服务。

### 3.1 核心市场数据能力

| 能力名 | 类型 | 默认触发 | 目标数据 | 主要写入位置 | 可恢复 | 用途 |
| --- | --- | --- | --- | --- | --- | --- |
| `stock_basic` | 采集 | 工作日 09:00 | 股票基础信息、上市状态、估值字段合并 | `stock_basic` | 否 | 股票列表、名称、状态、基础属性。 |
| `index_basic` | 采集 | 工作日 09:00 | 指数基础信息 | `index_basic` | 否 | 指数元数据。 |
| `stock_daily` | 采集 | 工作日 15:30 | 全市场股票日 K | `stock_daily` | 是 | 核心行情、选股、统计、回测基础数据。 |
| `index_daily` | 采集 | 工作日 15:35 | 上证、深证、创业板等核心指数日 K | `index_daily` | 是 | 指数行情、市场环境、择时判断。 |
| `daily_basic` | 采集 | 工作日 16:00 | 全市场每日指标 | `daily_basic` | 是 | 估值、换手、量比、市值等指标。 |
| `moneyflow_industry` | 采集 | 工作日 16:00 | 行业资金流 | `moneyflow_industry` | 是 | 行业资金强弱、市场结构分析。 |
| `moneyflow_concept` | 采集 | 工作日 16:05 | 概念资金流 | `moneyflow_concept` | 是 | 概念题材资金强弱。 |
| `limit_list` | 采集 | 工作日 16:10 | 涨跌停列表 | `limit_list` | 是 | 涨停、跌停、连板、市场情绪分析。 |
| `stock_relations` | 处理 | 工作日 16:20 | 个股和板块/题材关系 | `stock_relations` 相关集合 | 否 | 股票与行业、概念、题材关联。 |
| `daily_stats` | 处理 | 工作日 16:30 | 市场统计、情绪、连板等聚合 | `daily_stats` 等统计集合 | 是 | 市场晴雨表、涨跌统计、行情分析基础。 |
| `market_statistics_cache` | 处理 | 工作日 16:35 | 市场统计预聚合缓存 | 市场统计缓存集合 | 是 | Web 市场统计页面快速读取。 |

核心 ready 判断当前关注这些数据集：

```text
stock_daily
index_daily
daily_basic
moneyflow_industry
moneyflow_concept
limit_list
daily_stats
market_statistics_cache
```

这些数据集在同一目标交易日都完整后，`readiness_markers` 会写入 `marker_type=market_core_ready` 的 ready 状态。

### 3.2 复盘与辅助数据能力

| 能力名 | 类型 | 默认触发 | 目标数据 | 主要写入位置 | 可恢复 | 用途 |
| --- | --- | --- | --- | --- | --- | --- |
| `review_data` | 采集 | 工作日 19:30 | 连板天梯、板块涨停、板块日线、龙虎榜、热股、北向资金 | `review_limit_step`、`review_sector_limit`、`review_sector_daily`、`review_dragon`、`review_hot`、`review_northbound` | 部分历史采集 | 日终复盘、题材分析、强弱榜单。 |
| `ths_sector` | 采集 | 每周六 02:00 | 同花顺板块、成分股、个股映射 | `ths_sectors`、`stock_sector_map`、`sector_stocks` | 否 | 板块分析、概念映射、个股归属。 |
| `fina_indicator` | 采集 | 每月 1 日 09:00 | 利润表、资产负债表、现金流、财务指标 | `fina_income`、`fina_balance`、`fina_cashflow`、`fina_indicator` | 否 | 基本面分析、财务因子。 |

### 3.3 新闻与热点能力

| 能力名 | 类型 | 默认触发 | 目标数据 | 主要写入位置 | 当前状态 | 用途 |
| --- | --- | --- | --- | --- | --- | --- |
| `hot_news` | 采集 | 每 5 分钟 | 多来源热点新闻榜单 | Redis 热点新闻缓存 | 已注册，常驻高频 | 首页热点、舆情观察。 |
| `stock_news` | 采集 | 工作日 18:30 | 涨跌停个股相关新闻 | `news`、Milvus 向量库 | 已注册但当前 `collect()` 直接 `skip` | 预留给个股新闻/RAG。 |
| `event_clustering` | 处理 | 预留 | 新闻事件聚类 | 预留 | 当前未注册 | 后续新闻深度去重与事件化。 |
| `news_lifecycle` | 处理 | 预留 | 新闻生命周期清理 | 预留 | 当前未注册 | 后续控制新闻数据体量。 |

### 3.4 数据源优先级

当前核心能力倾向于传统稳定源优先：

| 能力 | 优先级 |
| --- | --- |
| `index_daily` | `tushare -> baostock -> akshare` |
| `latest_trade_date` | `tushare -> baostock -> akshare -> coze` |
| `trade_calendar` | `tushare -> baostock -> akshare -> coze` |
| 全市场 `daily` | `tushare -> baostock -> akshare -> coze` |
| 全市场 `daily_basic` | `tushare -> baostock -> akshare -> coze` |
| 财务数据 | 优先 `tushare` |

设计原则：

- 核心交易数据优先稳定性，不优先追求免费源或 AI 源。
- Coze 更适合单股、实时、增强型或非核心链路能力。
- 任一源超时或返回空数据时，可以进入回退链路。

## 4. 运维与调用契约

这一节不是 HTTP API，而是当前 DataSync 对外提供的“操作能力”。

### 4.1 CLI 能力

| 命令 | 功能 | 典型用途 |
| --- | --- | --- |
| `python DataSync/main.py --check` | 检查配置、导入和任务注册 | 本地改动后快速确认服务能启动。 |
| `python DataSync/main.py --audit-self-contained` | 检查独立性 | 防止重构版重新依赖 `AgentServer`。 |
| `python DataSync/main.py --check-startup` | 初始化管理器、调度器、RPC 后退出 | 部署前确认 Redis、Mongo、数据源、RPC 能工作。 |
| `python DataSync/main.py --check-core-integrity --integrity-days 3` | 检查最近 3 个交易日核心完整性 | 判断最近数据是否缺失。 |
| `python DataSync/main.py --recover-latest-core-gaps` | 恢复最新交易日核心缺口 | 当天数据不全时优先使用。 |
| `python DataSync/main.py --recover-recent-core-gaps --integrity-days 3` | 恢复最近窗口核心缺口 | 补最近几天缺口。 |
| `python DataSync/main.py --safe-recover-core-window --integrity-days 4` | 检查、恢复、定向修复、再检查 | 安全补齐最近 N 个交易日。 |
| `python DataSync/main.py --recover-job-trade-date --job-name index_daily --trade-date 20260526` | 指定任务和交易日定向修复 | 已知某个任务某天缺失时使用。 |
| `python DataSync/main.py --check-sync-targets` | 查看主库/镜像库状态 | 排查 Mongo 连接和镜像写入状态。 |
| `python DataSync/main.py --recent-failed-jobs` | 查看最近失败任务 | 排查同步失败。 |
| `python DataSync/main.py --recent-ops-events` | 查看最近运维事件 | 排查恢复、告警、核心失败。 |
| `python DataSync/main.py --core-job-runtime-summary` | 查看核心任务运行摘要 | 排查慢任务和长尾。 |
| `python DataSync/main.py --data-source-call-stats` | 查看数据源调用统计 | 排查某个源是否超时或退化。 |
| `python DataSync/main.py --reset-data-source-call-stats` | 重置数据源调用统计 | 重新观察后续数据源状态。 |
| `python DataSync/main.py --ops-summary` | 输出综合运维摘要 | 最适合做人工排障或监控探针。 |

### 4.2 RPC 能力

| RPC 方法 | 参数 | 返回能力 |
| --- | --- | --- |
| `refresh_hot_news` | `source` 可选 | 刷新全部或指定来源热点新闻。 |
| `run_sync_job` | `job_name` | 手动运行指定同步任务。 |
| `get_core_readiness` | 无 | 返回最新核心 ready marker。 |
| `get_recent_job_executions` | `job_name` 可选，`limit` 可选 | 返回最近任务执行记录。 |
| `get_recent_failed_job_executions` | `limit`、`lookback_hours`、`core_jobs_only` | 返回最近失败任务。 |
| `get_recent_ops_events` | `limit`、`lookback_hours`、`severities` | 返回最近运维事件。 |
| `get_core_job_runtime_summary` | `lookback_hours` | 返回核心任务耗时和成功率摘要。 |
| `get_core_integrity_overview` | `days` | 返回最近 N 个交易日核心完整性概览。 |
| `recover_latest_core_gaps` | 无 | 尝试恢复最新交易日核心缺口。 |
| `recover_recent_core_gaps` | `days` | 尝试恢复最近 N 个交易日核心缺口。 |
| `recover_job_trade_date` | `job_name`、`trade_date` | 定向恢复指定任务和交易日。 |
| `get_sync_targets_status` | 无 | 返回主库/镜像库健康状态。 |
| `get_data_source_call_stats` | 无 | 返回当前进程内数据源调用统计。 |
| `reset_data_source_call_stats` | 无 | 重置当前进程内数据源统计窗口。 |
| `get_ops_summary` | `days`、`job_limit`、`lookback_hours` 等 | 返回综合运维摘要。 |

### 4.3 就绪状态契约

`get_core_readiness` 或 `readiness_markers` 中的 `market_core_ready` 可以作为 Web 判断核心市场数据是否可用的依据。

核心字段含义：

| 字段 | 含义 |
| --- | --- |
| `marker_type` | 当前固定为 `market_core_ready`。 |
| `trade_date` | 当前 marker 对应的交易日。 |
| `status` | `ready` 表示核心链路齐全，`building` 表示仍在构建或部分缺失，`missing` 表示没有 marker。 |
| `ready_at` | 状态变为 ready 的时间。 |
| `details.ready_datasets` | 已完成的数据集。 |
| `details.pending_datasets` | 仍缺失的数据集。 |
| `details.dataset_sync_dates` | 每个核心数据集当前覆盖到的同步日期。 |

推荐使用口径：

- 页面只要依赖核心市场数据，就优先看 `market_core_ready`。
- 运维排障时再进一步看 `get_core_integrity_overview`。
- 不建议 Web 页面继续自己猜 `sync_records`，因为 `sync_date` 在不同任务里存在运行日期和目标交易日混用的历史问题。

## 5. 当前限制与待补齐点

| 问题 | 说明 |
| --- | --- |
| 重构线尚未完全交付 | `DataSync/` 当前仍是工作区重构状态，需要确认是否提交、部署、替换旧链路。 |
| `sync_date` 历史语义混杂 | 部分任务表示目标交易日，部分任务表示运行日期，后续最好拆成 `run_date`、`target_trade_date`、`data_cutoff_time`。 |
| `stock_news` 当前跳过 | 代码已注册，但 `collect()` 直接返回 `skip`，不能当作真实个股新闻能力。 |
| 高频热点仍需隔离 | `hot_news` 每 5 分钟多源抓取，请求量高，后续最好独立限频、独立降级，不影响核心链路。 |
| 周/月重任务仍需更强隔离 | `fina_indicator`、`ths_sector`、历史复盘补数都可能很重，不应与当日核心行情抢资源。 |
| 真正业务接口不在本文档范围 | 本文描述数据服务能力，Web 业务接口仍应另写接口文档。 |
| 镜像库只是尽力同步 | 镜像写失败不会阻断主库，适合灾备/迁移辅助，不适合作强一致双写。 |
| 生产配置需单独确认 | `.env.docker`、docker compose、服务器资源限制是否已对齐，需要以部署环境为准。 |

## 6. 推荐下一步

1. 把本文档作为 DataSync 重构验收基线，后续新增数据能力都补进第 3 节。
2. 另建一份 `DATASYNC_OPERATIONS.md`，只写生产补数、排障、健康检查命令。
3. 另建一份机器可读的 `datasync_capabilities.yaml`，把能力名、数据集、集合、调度、恢复能力、依赖关系结构化，后续 Web 能直接展示“数据能力状态”。
4. 等 `DataSync/` 独立服务确认交付后，再把本文档中的“工作区状态”改成“生产部署状态”。
