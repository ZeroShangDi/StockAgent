# DataSync 任务时间轴与请求量清单

本文档用于回答 3 个问题：

1. 当前 `DataSync` 到底在什么时间更新什么数据。
2. 各任务大致会产生多少外部请求。
3. 在不超频的前提下，Web 最早什么时候能拿到“可用数据”。

本文档基于 2026-05-24 的当前代码与本地库快照整理。

## 当前已经补上的稳定性护栏

- `stock_daily` 成功后会立即触发一条“收盘后快速流水线”：
  `index_daily -> daily_basic -> moneyflow_industry -> moneyflow_concept -> limit_list -> stock_relations -> daily_stats -> market_statistics_cache`
- 每次 job 执行现在都会落入 `job_execution_records`，用于追踪：
  - 任务名
  - 开始/结束时间
  - 成功、失败、跳过
  - 目标交易日
  - 触发来源（scheduler / startup / manual / pipeline）
- 核心链路现在会写 `readiness_markers`，用于判断“当天核心市场数据是否已经准备好”。
- `DataSync` 现在额外暴露了几个轻量 RPC 能力：
  - `run_sync_job`
  - `get_core_readiness`
  - `get_recent_job_executions`
  - `get_core_integrity_overview`
  - `recover_latest_core_gaps`
  - `get_sync_targets_status`
- `DataSyncNode` 现在会额外注册一个内部恢复任务 `core_gap_recovery`：
  - 默认每 `20` 分钟检查一次最新交易日核心链路缺口
  - 启动后会延迟触发一次恢复检查
  - 目标是让“重启后自动补缺”和“定时巡检补缺”变成默认能力，而不是只靠人工 RPC
  - 默认检查最近 `3` 个交易日，最大不超过 `10` 个交易日
  - 自动补缺只恢复核心数据，非核心历史数据不会在启动时抢资源
- `MongoManager` 现在已经有了多目标数据库同步的最小骨架：
  - 主库继续是默认唯一真源
  - 可选配置一个 `MONGO_MIRROR_*` 第二目标库
  - 写入会以“主库优先、镜像尽力而为”的方式同步到第二目标
  - 镜像失败只会记 warning，不会阻断主同步链路
- `DataSync/main.py --check-startup` 现在会直接打印主库与镜像库的目标状态，
  包括是否启用、是否连接成功、当前目标库名，方便托管环境排查。
- `DataSync/main.py --check-sync-targets` 现在可以单独查看主库/镜像库状态，
  并包含镜像写入成功次数、失败次数和最后一次写入错误，方便判断远程库是否在“连得上但写不稳”。
- `moneyflow_industry`、`moneyflow_concept`、`limit_list`、`market_statistics_cache` 现在也会检查最新交易日覆盖情况，
  不再只看 `sync_records` 标记，避免“同步标记已前进，但当日数据其实没落全”的误判。
- 独立 `DataSyncNode` 现在接入了全局运行预算：
  - 默认同一节点只允许 `1` 个 job 运行。
  - 单 job 默认 `1200` 秒硬超时，超时会记录失败并释放锁。
  - 分布式锁 TTL 默认从 `SYNC_LOCK_TIMEOUT_SECONDS` 读取，不再写死 `10` 分钟。
  - 定向交易日恢复也复用同一套并发与超时保护。
- 独立 `DataSyncNode` 现在按资源类别注册任务：
  - `core`：核心市场链路，`conservative` 档默认只注册这一类。
  - `background`：新闻、复盘等可后补任务，需要 `SYNC_PROFILE=full` 或 `SYNC_ENABLED_JOBS` 显式启用。
  - `heavy`：财务、板块映射等重任务，启用后也会单独串行，避免多个重任务叠加。
  - 核心链路运行中，定时触发的非核心任务会记录为 `skipped`，不会抢核心同步资源。
- `hot_news` 现在进一步降压：
  - 默认 `SYNC_HOT_NEWS_ENABLED=false`，即使注册任务也会显式 `skipped`。
  - 默认只允许 `cls,xueqiu,wallstreetcn` 三个来源。
  - 默认每轮最多 `3` 个来源、每源最多 `20` 条。
  - 单来源 HTTP 默认 `10` 秒超时，整轮默认 `30` 秒超时。
- `job_execution_records` 现在开始拆分运行语义：
  - `run_date` 表示任务实际运行日期。
  - `target_trade_date` 表示该次任务面向的交易日，核心任务缺失时会尽量补为最新交易日。
  - `data_cutoff_time` 暂时跟随目标交易日或任务返回值，后续可扩展到更精确的数据截止点。
  - `resource_class` 表示 `core/background/heavy`，用于运维和调度判断。
  - `source` 表示任务返回的数据源，旧 `sync_records` 继续保留作为兼容标记。
- 核心完整性检查现在输出更明确的状态：
  - `ready`：真实集合覆盖达到最低要求。
  - `missing`：真实集合没有覆盖，且没有可接受的成功执行记录。
  - `warning`：有数据但数量明显偏低，例如股票覆盖率低于阈值。
  - `waiting_window`：当天还没到配置的核心同步时间窗，不作为阻断缺口。
  - 对 `limit_list` 这类可能零记录的数据，允许成功执行记录作为“当天已确认”的辅助证据。
- ready marker 现在有稳定顶层契约：
  - `ready_datasets`、`pending_datasets`、`warnings`、`last_checked_at` 会直接写在 marker 顶层。
  - `details` 继续保留旧结构和完整性检查细节，兼容已有读取方式。
  - 状态会在 `missing / waiting_window / building / ready / degraded / failed` 这个集合内收敛。
- Web 侧现在也有只读可用性入口：
  - `GET /api/v1/system/data-readiness/market-core`
  - `GET /api/v1/market/core-readiness`
  - 两个接口都优先读取 `readiness_markers(marker_type=market_core_ready)`，返回统一字段和 `usable` 布尔值。
- 最新交易日核心缺口恢复现在进一步收敛：
  - 通过完整性检查找到首个缺失数据集，只从该数据集开始按核心链路顺序恢复。
  - 每个步骤仍走任务锁、节点并发预算和任务硬超时。
  - 任一步失败会立即停止，并在结果中返回 `failure_point`、`completed_jobs`、`rerun_order` 和每步 `results`。
  - 如果最新交易日还在 `waiting_window`，恢复入口会直接跳过，避免源端未出数时反复空跑。
- 最近窗口恢复结果现在会汇总：
  - `recovered_trade_dates`：本轮确实执行恢复的交易日。
  - `skipped_trade_dates`：例如仍处于 `waiting_window` 而主动跳过的交易日。
  - `failed_trade_dates`：恢复失败的交易日和失败点。
  - `unsupported`：当前仍缺少定向恢复能力的数据集。
- 当天核心数据 SLA 时间窗现在拆成四段：
  - `waiting_window`：默认 `15:30` 前，不恢复、不告警。
  - `syncing_window`：默认 `15:30-16:10`，允许恢复，但不把未齐数据算故障。
  - `overdue`：默认 `16:10-17:00`，核心链路应当 ready，缺失进入阻断缺口。
  - `failed`：默认 `17:00` 后仍缺失，缺失数据集标记为 failed，供 ready marker 和 ops summary 使用。
- 可控 HTTP 数据源现在开始接入统一请求基座：
  - 当前先覆盖 Coze 工作流源，后续再逐步迁移其他直接 HTTP 源。
  - 429 会按 `Retry-After` 等待，503/5xx/网络错误/超时会进入有限重试。
  - 重试失败后抛出结构化错误，DataSourceManager 会记录 `rate_limited`、`server_error`、`network_error`、`http_error` 等分类，方便判断是源端限频还是本地异常。
- 数据源回退链路现在显式化：
  - 全市场日 K 默认 `tushare -> baostock -> akshare -> coze`，单股日 K 默认 `coze -> akshare -> baostock -> tushare`。
  - `SYNC_SOURCE_CHAIN_OVERRIDES` 可以覆盖具体能力链路，例如 `get_daily.full_market=tushare,baostock,akshare`。
  - 调用统计会记录 `last_source_chain`、`last_attempted_sources`、`last_fallback_from`、`last_fallback_to`。
  - 全部来源报错会抛出链路错误；只有来源返回空集合时才按空数据处理。
- 核心集合入库前现在有轻量校验：
  - 覆盖 `stock_daily`、`daily_basic`、`index_daily`、`limit_list`、`moneyflow_industry`、`moneyflow_concept`。
  - 校验必填字段、标准化 `trade_date`、安全转换 float/int 字段。
  - 无效记录会在写库前隔离，并在日志里记录最多 5 条样本；后续 DS-P1-10 会把这些样本接到死信集合。
- 死信/脏数据记录现在进入 `datasync_dead_letters`：
  - 单批默认最多写入 20 条，由 `SYNC_DEAD_LETTER_MAX_RECORDS_PER_BATCH` 控制。
  - 记录包含任务名、目标集合、来源、目标交易日、错误原因、错误类型和压缩后的原始样本。
  - ops summary 会返回近期死信样本，并在核心采集器产生近期死信时追加 warning 告警。
- 幂等批量写入现在有统一入口：
  - `bulk_upsert_batched` 强制业务主键，避免重复同步产生重复记录。
  - 批次大小默认 `1000`，由 `SYNC_BULK_UPSERT_BATCH_SIZE` 控制。
  - 结果包含 `matched`、`modified`、`inserted/upserted`、`failed`、`batch_errors`。
  - 采集器 `_write_buffer` 会把写入结果追加到任务返回值的 `write_results`，最终进入 job execution details。
- 任务 checkpoint 与断点续拉现在有基础契约：
  - 新增 `datasync_checkpoints`，按 `job_name + target_trade_date + window` 记录游标。
  - `stock_daily` 增量按交易日记录 `last_success_key`，中断后跳过已完成交易日。
  - `stock_daily` 历史扫描按股票代码和日期窗口记录 `last_success_key`，中断后从下一个股票批次继续。
  - `DataSync/main.py --recent-checkpoints` 可查看最近 checkpoint，支持 `--job-name` 和 `--checkpoint-status` 过滤。
- 闲时补缺窗口现在有统一闸门：
  - 默认 `SYNC_BACKFILL_WINDOW_START=00:00`、`SYNC_BACKFILL_WINDOW_END=08:00`。
  - `heavy` 任务和显式 `backfill/history` 触发在窗口外会记录 `backfill_window_closed` 并跳过。
  - CLI 定向恢复可用 `--force` 在人工确认后绕过窗口。
  - 当天核心缺口恢复不受该闸门限制，仍按核心 SLA 时间窗处理。
- 历史补缺队列现在有基础能力：
  - 新增 `datasync_backfill_jobs`，记录 `dataset`、`target_trade_date`、日期窗口、状态、优先级、尝试次数和错误。
  - `BackfillQueueService` 每轮只领取少量 `pending` 任务，并复用对应任务的 `recover_trade_date`。
  - 默认每 `30` 分钟检查一次队列，每轮最多消费 `2` 个任务，最多尝试 `3` 次。
  - `--enqueue-backfill-job`、`--recent-backfill-jobs`、`--run-backfill-queue-once` 可用于人工入队、查看和验证。
- 核心历史定向恢复现在统一走恢复契约：
  - 8 个核心数据集恢复前都会校验目标日期是否交易日，非交易日只显式跳过，不制造空数据。
  - 交易日历源异常会返回失败结果，交给队列重试，不静默写入或伪装成功。
  - 恢复结果统一携带 `source`、`sources`、`warnings` 和 `failed_items`，方便从队列、执行记录和运维事件追踪问题来源。
- 历史补缺现在有每日预算和失败熔断：
  - 默认每晚最多消费 `24` 个补缺任务，最多产生 `300` 次外部数据源请求。
  - 连续失败达到 `3` 次后停止当晚队列消费，避免源端异常时反复打接口。
  - 预算状态写入 `datasync_backfill_budgets`，`ops summary` 可看到最近预算用量和停止原因。
- 轻量探针现在拆成健康与就绪两层：
  - `--health` 只检查配置、Redis 和 Mongo，用于 Docker 高频探活。
  - `--ready` 只检查核心 ready marker 和近期核心失败，用于判断核心数据服务是否可用。
  - 独立 DataSync Compose 的 `data-sync` healthcheck 已使用 `python main.py --health`，不会触发重型查询。
- `ops-summary` 现在可以作为总探针：
  - 顶层输出 `operational_status` 和 `probe_checks`，脚本不需要解析深层明细。
  - 输出 `backfill_queue_status`，能看到队列状态计数、最近任务样本和夜间预算状态。
  - 严格模式可组合 `--require-recent-window-ready`、`--require-no-recent-failures`、`--require-no-warning-events`、`--require-no-core-data-source-degradation`、`--require-no-core-runtime-outliers`。
- 生产补数现在有独立操作手册：
  - `docs/DATASYNC_OPERATIONS.md` 写清最近 1-5 个交易日核心补缺、单任务单交易日补缺、夜间补缺队列、完成确认和失败排查。
  - 手册明确不建议开放 MongoDB 端口或手动改库，白天只使用轻量探针和小窗口核心补缺。
- Docker 部署默认安全边界已收口：
  - MongoDB / Redis 宿主机端口默认只绑定 `127.0.0.1`。
  - 宿主机映射端口拆分为 `MONGO_PUBLISHED_PORT` / `REDIS_PUBLISHED_PORT`，避免影响容器内服务连接端口。
  - 独立 DataSync Compose 已给 DataSync、MongoDB、Redis 补资源上限。
- 旧 AgentServer DataSync 替换边界已有迁移计划：
  - `docs/DATASYNC_MIGRATION_PLAN.md` 对照了旧链路与独立链路的任务、集合、能力和灰度步骤。
  - `market_weather` 股票晴雨表已迁移到独立 DataSync，正式下线旧链路前仍需生产灰度验证。
  - 股票晴雨表依赖 Coze 工作流，不纳入 `market_core_ready` 硬门槛。
- DataSync 任务已有静态能力声明协议：
  - 核心任务声明了数据集、目标集合、依赖、资源等级、恢复能力和质量规则。
  - `DataSyncNode.get_capability_manifest()` 与 RPC `get_data_capabilities` 可导出当前 profile 下的能力清单，下一步可以生成机器可读目录文件。
- 机器可读能力目录已生成：
  - `DataSync/config/datasync_capabilities.yaml` 记录 conservative 档 12 个核心能力。
  - `python DataSync/main.py --data-capabilities` 可打印目录，`--write-data-capabilities` 可重新生成 YAML/JSON。
  - 目录包含默认数据源链路，后续 Web 能以它作为数据能力状态页的静态基线。
- Mongo 索引初始化已收敛：
  - 启动默认只检查核心集合索引，`MONGO_INDEX_STARTUP_SCOPE=all` 才会恢复全量索引检查。
  - `--health` / `--ready` 探针不再触发索引检查。
  - `python DataSync/main.py --ensure-indexes --index-scope all` 可在闲时手动补齐全量索引。
- 日志结构化与采样已收敛：
  - 任务开始、成功、失败、跳过和超时会输出 `datasync_job_*` 事件，包含任务名、触发方式、资源类别、交易日、来源、耗时和错误原因。
  - 入库校验丢弃坏数据时，Docker 日志只保留 `OBS_LOG_SAMPLE_LIMIT` 条压缩样本；详细坏数据继续进入 `datasync_dead_letters`。
  - 结构化日志字段会按 `OBS_LOG_MAX_VALUE_CHARS` 截断，避免完整外部响应或大 payload 刷爆日志。
- Mongo 幂等写入批次现在支持动态调整：
  - 默认从 `SYNC_BULK_UPSERT_BATCH_SIZE=1000` 起步，硬上限仍是 `SYNC_BULK_UPSERT_MAX_BATCH_SIZE=1000`。
  - 单批写入慢于 `SYNC_BULK_UPSERT_SLOW_BATCH_MS=1500` 会缩小批次，最低默认 `100`。
  - 连续稳定批次只会小步恢复到本次请求上限，任务详情会记录 `batch_size_history`，方便判断是否发生过降载。
- 数据源调用现在有源级限流预算：
  - 默认 `SYNC_SOURCE_RATE_LIMITS=tushare=200/m,akshare=60/m,baostock=60/m,coze=30/m`。
  - 429 或明确限频错误会让对应数据源进入冷却，冷却期间跳过该源并继续尝试后续 fallback。
- Web 能力状态页已接入 DataSync 状态面板：
  - `GET /api/v1/system/datasync/status` 汇总核心 ready、能力目录、最近失败和补缺队列。
  - 系统“能力状态”页能看到核心交易日、缺失数据集、最近失败任务和补缺队列摘要。
  - 安全补缺继续复用现有“补最近 3 个交易日核心数据”入口。
- 数据恢复语义已进入能力目录：
  - `recoverability.mode` 区分 `full / best_effort / none`。
  - 核心完整性检查会在数据集状态中带出可恢复性，便于页面和告警判断缺口严重程度。
  - `hot_news` 等强时效任务失败时会按 `severity_on_missing` 进入 warning/critical 运维事件，不再只停留在普通执行记录。
- Web 状态页已展示可恢复性：
  - 状态接口输出 `recoverability_summary`。
  - 缺失数据集和最近失败任务会标注 `可补 / 尽力补 / 不可还原`。
  - 页面能看到不可完整后补能力数量，便于优先排查强时效数据。
- Web 补缺入队闭环已接入：
  - `POST /api/v1/system/datasync/backfill-jobs` 可把支持补缺的数据集加入夜间补缺队列。
  - 系统“能力状态”页在缺失数据集旁提供入队按钮，入队后刷新队列摘要。
  - 入队前会按能力目录校验可恢复性，不可还原或未知数据集不会创建队列任务。
- Web 补缺队列人工操作已接入：
  - `PATCH /api/v1/system/datasync/backfill-jobs/{job_id}/action` 支持 `pause/resume/retry`。
  - 页面只暴露安全状态转换，不允许直接中断 `running` 任务。
  - 人工操作会写入 `ops_events`，保留用户、任务、交易日、动作和前后状态。
- Web 运维事件展示已接入：
  - `GET /api/v1/system/datasync/status` 输出最近 72 小时最多 5 条 `recent_ops_events`。
  - 系统“能力状态”页新增“运维事件”卡片，展示事件级别、来源、时间、消息和关键 details。
  - 补缺队列人工操作、不可后补告警、核心恢复事件可以在页面中被追踪。

这些能力的目标不是增加业务复杂度，而是让 `DataSync` 更容易被托管、排障和远程触发。

## 当前库规模快照

- 上市股票数：`5836`
- `stock_daily` 最近交易日 `20260522` 记录数：`5504`
- `daily_basic` 最近交易日 `20260522` 记录数：`5504`
- `limit_list` 最近交易日 `20260522` 记录数：`120`
- `ths_sectors` 当前板块数：`409`

这些数字会直接影响历史补数、财报同步、热点新闻扩展等任务的请求量。

## 为什么同步日期看起来不一致

当前项目里存在两种不同的 `sync_date` 语义：

- `stock_daily`、`daily_basic`、`limit_list`、`moneyflow_*`、`daily_stats`、`review_data` 这类“交易日数据”记录的是目标交易日，例如当前看到的是 `20260522`。
- `stock_basic`、`index_basic`、`ths_sector`、`fina_indicator` 这类“静态/周期型数据”记录的是任务实际运行日期，例如当前看到的是 `20260524`。

所以 `20260524` 和 `20260522` 同时出现，并不一定表示任务漏跑，很多时候只是“运行日期”和“目标交易日”混在了一张同步表里。

## 当前默认任务时间轴

除了下面这套 cron 兜底时间外，当前代码还新增了一条“收盘后快速流水线”：

`stock_daily` 成功后，会立即尝试串行推进：

`index_daily -> daily_basic -> moneyflow_industry -> moneyflow_concept -> limit_list -> stock_relations -> daily_stats -> market_statistics_cache`

这条流水线的目标是让 Web 尽快拿到当天核心市场数据，而不是继续傻等固定的 `16:30/16:35` 档位。原来的 cron 仍然保留，作为兜底与重试入口。

### 盘前与静态数据

| 时间 | 任务 | 数据 | 依赖 | 典型外部请求量 |
| --- | --- | --- | --- | --- |
| `09:00` | `stock_basic` | 股票基础信息 + 最新估值字段合并 | `daily_basic(latest_trade_date)` | 约 `3` 次 |
| `09:00` | `index_basic` | 指数基础信息 | 无 | 约 `4` 次 |
| `每月1号 09:00` | `fina_indicator` | 三大报表 + 财务指标 | `stock_basic` | 很重，见下文 |

### 收盘后核心行情链路

| 时间 | 任务 | 数据 | 依赖 | 典型外部请求量 |
| --- | --- | --- | --- | --- |
| `15:30` | `stock_daily` | 全市场日线 | `latest_trade_date` | 正常增量约 `2` 次；首次历史约 `5836` 次 |
| `15:35` | `index_daily` | 3 个核心指数日线 | `latest_trade_date` | 约 `4` 次 |
| `16:00` | `daily_basic` | 全市场每日指标 | `latest_trade_date` | 正常增量约 `2` 次 |
| `16:00` | `moneyflow_industry` | 行业资金流 | `trade_calendar` | 正常增量约 `3` 次 |
| `16:05` | `moneyflow_concept` | 概念资金流 | `trade_calendar` | 正常增量约 `3` 次 |
| `16:10` | `limit_list` | 涨跌停列表 | `trade_calendar` | 正常增量约 `3` 次 |
| `16:20` | `stock_relations` | 个股-板块-题材关系 | 本地库 | 外部请求近似 `0` |
| `16:30` | `daily_stats` | 市场统计、连板、情绪分析 | `stock_daily` `index_daily` `moneyflow_*` `limit_list` | 正常约 `3` 次，主要压力在本地聚合 |
| `16:35` | `market_statistics_cache` | 市场统计预聚合缓存 | `daily_stats` | 外部请求近似 `0`，主要是本地聚合 |

### 日终复盘与高频热点

| 时间 | 任务 | 数据 | 依赖 | 典型外部请求量 |
| --- | --- | --- | --- | --- |
| `18:30` | `stock_news` | 涨跌停个股新闻 | `limit_list` | 当前代码实际 `skip`，未生效 |
| `19:30` | `review_data` | 龙虎榜、热股、北向、连板天梯等复盘数据 | `latest_trade_date` | 正常日约 `7` 次；首次回补约 `6 x 近60个交易日` |
| `每周六 02:00` | `ths_sector` | 同花顺板块与成分股映射 | 无 | 约 `411` 次/周 |
| `每5分钟` | `hot_news` | 13 个来源热点新闻 | Redis | 至少 `13` 次/轮，约 `3744+` 次/天 |

## `fina_indicator` 的请求量说明

`fina_indicator` 现在应优先走 `Tushare`。

原因很简单：

- 这个任务的目标是“三大报表 + 财务指标”。
- 当前 `Coze` 的 `get_financial_data()` 只提供 `fina_indicator`，不是真正完整的财务四件套。
- 如果这里不优先 `Tushare`，任务语义和落库结果会不一致。

按当前 `5836` 只上市股票估算：

- 月度增量模式：约 `5836` 股
- 如果 `Tushare` 端一次 `get_financial_data()` 内部并发拉 4 个接口，则总外部 API 调用量接近 `23344` 次/月
- 如果任务退化回退到其他源，应视为“降级兜底”，不应作为主路径

## 哪些任务最影响 Web 可用时间

如果只看“Web 页面什么时候能拿到核心市场数据”，最关键的是这条链：

`stock_daily` -> `index_daily` -> `daily_basic` -> `moneyflow_*` -> `limit_list` -> `daily_stats` -> `market_statistics_cache`

在当前实现下，核心页面数据会优先走“快速流水线”，cron 只是兜底。

所以在没有失败重试、没有源端异常、且单任务耗时保持在正常分钟级的前提下，目标窗口应调整为：

- 核心行情/统计类页面的目标可用时间：`15:50 - 16:05`
- 如果快速流水线未触发或中途失败，cron 兜底时间仍然是 `16:35` 左右
- 复盘页全量数据的目标可用时间：`19:30 - 19:50`

这里保留了 `daily_stats` 和 `market_statistics_cache` 的 `16:30/16:35` cron，目的是让“更早可用”和“定时兜底”同时存在。

## 当前最重的外部请求任务

按“持续压力”排序，大致是：

1. `hot_news`
2. `fina_indicator`
3. `ths_sector`
4. `stock_daily` 首次历史回补
5. `review_data` 首次历史回补

其中最容易把服务长期拖慢的不是日线，而是：

- 高频 `hot_news`
- 历史回补型任务
- 周度板块成分股映射

## 当前最重的本地数据库任务

按本地聚合/扫描压力看，重点关注：

1. `daily_stats`
2. `market_statistics_cache`
3. `review_data`
4. `stock_relations`

这些任务不一定打很多外部 API，但很容易吃 CPU、Mongo I/O 和内存。

## 当前明显问题

### 1. `stock_news` 虽然在调度里，但实际上是关闭的

当前 [stock_news.py](/Users/shangjunhao/Project/StockAgent/DataSync/nodes/data_sync/collectors/news/stock_news.py:49) 在 `collect()` 开头直接返回了：

```python
return {"count": 0, "message": "skip"}
```

所以它现在不提供真实数据价值。

### 2. `hot_news` 是当前请求量最高的任务

它每 `5` 分钟跑一次，并发抓取 `13` 个来源。
如果后面要优先保核心交易数据，`hot_news` 应单独看待，不能和日线同步放在同一优先级。

### 3. 同步表里的 `sync_date` 语义不统一

这会让“今天到底哪些数据真的齐了”变得不好判断。后续建议把：

- `run_date`
- `target_trade_date`
- `data_cutoff_time`

拆开记录，而不是继续只靠一个 `sync_date` 字段混用。

## 推荐的可用性判断口径

后续 Web 或运维面板不要只看“任务跑没跑”，而要看两层：

1. `latest_trade_date`
2. 关键集合对该交易日是否覆盖完成

对 Web 而言，至少应该监控这些集合是否已经覆盖到同一个交易日：

- `stock_daily`
- `daily_basic`
- `index_daily`
- `moneyflow_industry`
- `moneyflow_concept`
- `limit_list`
- `daily_stats`
- `market_statistics_cache`

只要这些集合在同一交易日覆盖完成，核心市场页面就应判定为“可用”。

## 还应该继续做什么

如果目标是“生产环境稳定、当天更早可用、Web 不缺关键数据”，下一步最值得做的是：

1. 把 `sync_records` 扩成真正的任务运行表
   - 至少记录 `run_started_at`、`run_finished_at`、`target_trade_date`、`source`、`success`、`error`、`written_count`
   - 这样才能从“模拟预估”升级成“真实 SLA”
2. 增加“核心数据就绪位”
   - 在 `stock_daily`、`daily_basic`、`limit_list`、`daily_stats`、`market_statistics_cache` 全部覆盖同一交易日后，写一个 `ready_marker`
   - Web 侧直接看这个 marker，不再自己猜
3. 为月度/周度重任务单独分层
   - `fina_indicator`
   - `ths_sector`
   - `review_data` 历史回补
   这些不应阻塞当天核心行情可用
4. 把 `hot_news` 从核心链路资源面再切开
   - 它请求频率高，但不应影响日线和统计链路
5. 给关键任务补“缺失检测 + 定向补数”
   - 尤其是最近 `1~3` 个交易日
   - 优先保证近期完整，再向历史回补

## 机器建议

下面是基于当前任务模型、当前库规模和现有并发参数给出的建议。

### 最低可用

- `4 vCPU`
- `8 GB RAM`
- SSD
- MongoDB 与 Redis 最好独立，不要和 `DataSync` 挤在同一台小机器上

这个档位可以跑，但有风险：

- 月初 `fina_indicator` 会明显拖慢
- 周度 `ths_sector` 和历史回补容易把 CPU/内存顶高
- 如果 `DataSync + MongoDB + Redis` 全挤在一台 `8G` 机器上，稳定性一般

### 推荐生产

- `8 vCPU`
- `16 GB RAM`
- NVMe SSD
- `DataSync` 单独容器或单独进程
- MongoDB 独立机器或至少独立容器，并保证自己的缓存内存

这个档位更适合当前代码：

- 正常交易日核心链路比较稳
- 可以承受 `daily_stats`、`market_statistics_cache`、`review_data` 这种本地聚合压力
- 月初财务同步不会特别从容，但可控

### 更稳妥的档位

- `8~16 vCPU`
- `24~32 GB RAM`
- NVMe SSD
- MongoDB 单独实例
- Redis 单独实例

适合这些场景：

- 要跑较多历史回补
- 月初财报同步要和日常任务并存
- 未来要扩成多目标数据库写入
- 还要保留 LLM/向量化/通知等附加能力

## 当前参数下，压缩后的最早可用时间

### 当前已经做到的

现在代码里已经有“收盘后快速流水线”：

`stock_daily -> index_daily -> daily_basic -> moneyflow_industry -> moneyflow_concept -> limit_list -> stock_relations -> daily_stats -> market_statistics_cache`

它会在 `stock_daily` 成功后立刻推进，不再死等后面的 cron 档位。

### 我对当前代码的保守预估

在以下前提下：

- 数据源没有异常
- 没有触发大规模历史回补
- MongoDB 在本地写入没有明显抖动
- 机器达到推荐生产配置

那么：

- 核心行情链路最早可用：`15:50 - 16:05`
- 如果快速流水线没触发或中途失败，cron 兜底仍然在：`16:35` 左右
- 日终复盘类数据最早可用：`19:30 - 19:50`

### 如果继续压缩，还能压到哪里

在不明显增加错误率的前提下，我认为比较现实的目标是：

- 核心页面：`15:45 - 15:55`

再往前压就会碰到数据源本身的更新时间边界，主要是：

- `daily_basic`
- `moneyflow_industry`
- `moneyflow_concept`
- `limit_list`

这些数据不是你机器快就一定会更早出来，很多时候要等源端自己出齐。所以：

- `15:45` 左右是现实目标
- `15:35` 左右通常就开始进入“赌源端时效”的区间了

### 月初与周末特殊日

- 月初 `fina_indicator`：不要把它算进“当天核心数据何时可用”，它会把整日完成时间拉到 `2.5 - 4` 小时级别
- 周六 `ths_sector`：一般额外吃 `10 - 25` 分钟

所以“核心页面可用时间”和“所有任务全部跑完时间”必须分开看。

## 2026-06-03：Compose 安全默认值巡检

本轮做了一次统一收口前的小巡检，重点检查部署配置是否可能绕过代码里的保守默认值。

### 已补护栏

- 新增 `DataSync/tests/test_docker_compose_safety.py`。
- 覆盖 `docker-compose.yml`、`docker-compose.full.yml`、`DataSync/docker-compose.yml` 三个部署入口。
- 校验根 compose / full compose 的 `data-sync` 默认仍为 `conservative`，不会启动初始同步，不会放开任务并发和采集并发。
- 校验根 compose / full compose 的 `data-sync` 保持 `0.75 CPU / 512M` 资源上限。
- 校验热点新闻默认关闭，补缺队列每轮任务数、每晚任务数和外部请求预算保持保守。
- 校验独立 DataSync Compose 禁止共享环境回退，并保留 `python main.py --health` 健康检查。

### 巡检结论

- `DataSync` 当前全量单元测试达到 `100` 个，通过。
- 根 compose 当前仍是旧 `AgentServer main.py --node-type data_sync` 入口，不应直接接独立 `DataSync/main.py --health` 探针。
- `datetime.utcnow()` 弃用警告已在后续 `DS-P3-10` 统一处理。

## 2026-06-03：UTC 时间戳时区感知化

本轮处理上一轮巡检留下的 Python 3.13 弃用警告风险，将独立 DataSync 范围内的 `datetime.utcnow()` 统一替换为 `datetime.now(UTC)`。

### 已完成

- `DataSync/` 下已无 `datetime.utcnow()`。
- 补齐涉及模块的 `UTC` 导入。
- 覆盖运行记录、ready marker、checkpoint、补缺队列、核心完整性、数据源统计、采集器写入时间和 CLI 摘要等时间戳位置。
- 保持原有“UTC 时间”语义，只从 naive UTC datetime 调整为 timezone-aware UTC datetime。

### 验证结果

- DataSync 全量 Python 编译通过。
- DataSync 全量单元测试 `100` 个通过。
- `python DataSync/main.py --check` 通过。
- Pydantic V2 class-based `Config` 警告已在后续 `DS-P3-11` 处理，严格警告模式已经可通过。

## 2026-06-03：Pydantic V2 协议模型迁移

本轮处理 `DS-P3-10` 严格警告验证中暴露出的 Pydantic V2 迁移风险。

### 已完成

- 将 `StockAnalysisState` 的 `class Config` 改为 `ConfigDict(extra="allow")`。
- 将 `NewsItem` 的 `class Config` 改为 `ConfigDict(extra="allow")`。
- 将协议模型里的时间默认值从直接执行式 `default_factory=datetime.now(UTC)` 修正为 `lambda: datetime.now(UTC)`，避免默认时间在模块导入时冻结。
- 新增 `DataSync/tests/test_pydantic_v2_protocols.py`，覆盖 extra 字段兼容和时间默认值逐实例刷新。

### 验证结果

- DataSync 全量 Python 编译通过。
- `DataSync/tests/test_pydantic_v2_protocols.py` 通过。
- `PYTHONWARNINGS=error::DeprecationWarning` 下 DataSync 全量单元测试 `102` 个通过。

## 2026-06-03：统一提交范围审查

本轮没有继续增加业务能力，而是对 DataSync 重构当前工作区做统一提交前的范围审查。

### 已完成

- 新增 `docs/DATASYNC_UNIFIED_COMMIT_SCOPE_REVIEW.md`。
- 将建议纳入统一提交的范围拆为独立 DataSync 主体、AgentServer 配套改动、前端系统状态页、Docker/环境变量和 DataSync 文档。
- 将 `frontend/src/components.d.ts` 标记为默认排除，除非后续确认它是本次 DataSync 状态页构建必须依赖的生成文件。
- 将 `CLAUDE.md` 标记为默认排除或单独提交，避免混入 DataSync 重构。
- 明确 `DataSync/.env`、`DataSync/.env.docker`、日志、`__pycache__` 和 `*.pyc` 等运行生成物不应提交。

### 统一提交前建议

- 先执行 DataSync 全量测试与严格弃用警告测试。
- 再执行 AgentServer Web 系统同步接口测试。
- 再执行 `DataSync/main.py --check` 与 `DataSync/main.py --audit-self-contained`。
- 再执行前端构建与 `git diff --check`。
- 最终 staging 时显式排除 `frontend/src/components.d.ts` 和 `CLAUDE.md`，除非人工确认单独处理。
