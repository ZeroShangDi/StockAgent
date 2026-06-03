# DataSync 重构任务清单

本文档把当前项目状态、4C8G 服务器约束、通用 ETL 采集器硬能力建议，以及本项目真实数据优先级合并成一份可执行任务清单。

目标不是一次性追求“工业级全能 ETL 平台”，而是在不拖垮服务器的前提下，把 DataSync 做成一个安全、稳定、可靠、完整、全自动、可观测、可维护、可扩展、成本可控的数据采集器。

## 1. 服务器与业务约束

### 1.1 标准运行环境

- 服务器规格：`4C8G`
- 简化 Docker 栈需要同时运行：
  - Web
  - Listener
  - DataSync
  - MongoDB
  - Redis
  - 前端静态服务或相关容器
- DataSync 不能假设自己独占 CPU、内存、Mongo 连接池或网络带宽。

### 1.2 数据优先级

P0 数据必须优先保证：

- 股票指数日 K
- 股票日 K
- 每日基础指标
- 监听任务依赖的分时/快照数据
- 市场晴雨表
- 股票统计
- 行情分析
- 板块分析
- 不可后补或后补成本高的数据

P1 数据可以稳定后补：

- 复盘扩展数据
- 板块成分历史刷新
- 财务数据
- 新闻与热点
- 长周期历史缺口

P2 数据可以降频、暂停或手动触发：

- 大规模历史全量回补
- 高频新闻扩展
- LLM 深度处理
- 大范围事件聚类
- 非核心页面预热缓存

### 1.3 总体原则

- 核心链路优先，非核心链路不能影响核心链路。
- 当天数据优先，历史补缺只能在闲时运行。
- 可以后补的数据宁可延迟，也不能压垮服务器。
- 所有任务必须有超时、限流、批量上限、失败记录和可恢复路径。
- 任何采集器都不能捏造数据，源端异常必须显式失败或降级。
- Web 判断数据可用必须依赖 ready marker 或完整性检查，不再靠猜测 `sync_records`。

## 2. 当前状态判断

当前已有基础：

- `DataSync/` 已有独立入口、独立配置、独立运行目录和独立容器化雏形。
- 已有 `DataSyncNode`，支持定时任务、RPC、核心流水线、缺口恢复、ready marker。
- 已有 `job_execution_records`、`readiness_markers`、运维摘要和数据源调用统计雏形。
- AgentServer 内部 DataSync 已做过多轮性能加固，包含并发收敛、查询上限、批量写保护、Docker 保守配置。
- 已有核心数据能力文档：[DATASYNC_ARCHITECTURE_AND_CAPABILITIES.md](/Users/shangjunhao/Project/StockAgent/docs/DATASYNC_ARCHITECTURE_AND_CAPABILITIES.md)

当前主要风险：

- `DataSync/` 独立目录仍有大量未收口工作区改动，需要整理、验证、提交。
- 旧 `AgentServer/nodes/data_sync` 与新 `DataSync/` 的边界还没有最终确认。
- `sync_date` 语义混用，影响可用性判断和补缺判断。
- 高频 `hot_news`、周/月重任务、历史回补仍可能和核心链路抢资源。
- 部署配置、Docker 资源限制、环境变量默认值需要统一。
- 缺少一个严格的“采集器基座契约”，导致各采集器处理重试、清洗、写入、记录的方式不一致。

## 3. 任务拆解规则

每个任务应满足：

- 能被 AI 独立执行。
- 文件范围尽量明确。
- 目标单一，不和其他任务混在一起。
- 有明确验收标准。
- 可以形成一个独立提交。
- 不要求一次性理解整个项目。

任务优先级：

- `P0`：不做就可能继续崩服务器或丢核心数据。
- `P1`：完成后可形成可部署替代版。
- `P2`：完成后可形成长期维护版。
- `P3`：增强能力，可后置。

## 4. P0 任务：先防止服务器再被打爆

### DS-P0-01：冻结独立 DataSync 工作区边界

优先级：`P0`

目标：

明确当前 `DataSync/` 独立重构目录里哪些是有效改动、哪些是临时生成物，避免后续任务误提交、误删或重复实现。

建议文件范围：

- `DataSync/`
- `docs/DATASYNC_ARCHITECTURE_AND_CAPABILITIES.md`
- `docs/datasync-task-timeline.md`

执行要点：

- 列出 `DataSync/` 当前所有未提交文件。
- 标记代码文件、配置文件、文档文件、运行产物、临时文件。
- 确认 `.env`、日志、缓存、数据库本地文件不应提交。
- 生成一个短文档说明当前重构线的文件边界。

验收标准：

- 有明确的文件分类清单。
- `.env`、日志、缓存、运行数据不会被纳入后续提交。
- 后续 AI 可以知道哪些文件能改，哪些文件必须避开。

禁止事项：

- 不改业务逻辑。
- 不删除用户未确认的工作区文件。

### DS-P0-02：统一 Docker 与环境变量保守默认值

优先级：`P0`

目标：

保证服务器 `.env.docker` 即使不手动补齐新变量，也能使用安全默认值启动，避免缺配置导致高并发、高频率或启动风暴。

建议文件范围：

- `DataSync/.env.example`
- `DataSync/.env.docker.example`
- `DataSync/docker-compose.yml`
- `docker-compose.yml`
- `docker-compose.full.yml`
- `docker-compose.lite.yml`
- `AgentServer/core/settings.py`
- `DataSync/core/settings.py`

执行要点：

- 给所有新增性能保护变量提供代码级默认值。
- Docker 示例中显式写出核心限流参数。
- 默认关闭启动时全任务同步。
- 默认关闭重型历史回补。
- 默认限制 DataSync 并发、Mongo 批量大小、新闻来源并发。
- 默认把高频非核心任务降频或标记为可关闭。

验收标准：

- 服务器旧 `.env.docker` 缺少新增变量时仍使用安全值。
- `docker compose config` 能通过。
- 文档说明哪些变量是保守默认，哪些变量可按机器提高。

禁止事项：

- 不要求服务器开放新端口。
- 不默认启用远程 Mongo 直连。

### DS-P0-03：建立 DataSync 全局资源预算配置

优先级：`P0`

目标：

在 4C8G 环境下给 DataSync 一个明确资源预算，所有采集器和任务都从统一配置读取并发、批量、超时、运行时长上限。

建议文件范围：

- `DataSync/core/settings.py`
- `DataSync/core/base/`
- `DataSync/nodes/data_sync/node.py`
- `AgentServer/core/settings.py`

执行要点：

- 增加全局配置：
  - 最大同时运行 job 数。
  - 单 job 最大运行秒数。
  - 外部请求最大并发。
  - Mongo 写入最大并发。
  - 默认批量写入大小。
  - 单次任务最大处理记录数。
  - 核心任务和非核心任务不同预算。
- 默认配置按 4C8G 保守值。
- 采集器不能绕过统一预算随意开并发。

验收标准：

- 所有核心采集器能读取统一资源配置。
- 默认值下不会出现多个重任务同时跑。
- 配置项有文档说明。

禁止事项：

- 不做复杂自适应调度。
- 不引入新的大型依赖。

### DS-P0-04：增加任务级硬超时与超时失败记录

优先级：`P0`

目标：

任何 DataSync 任务不能无限运行；超时后必须失败、释放锁、记录错误，并允许下一轮恢复。

建议文件范围：

- `DataSync/nodes/data_sync/node.py`
- `DataSync/core/base/scheduled_job.py`
- `AgentServer/nodes/data_sync/node.py`

执行要点：

- 在任务运行包装层增加 `asyncio.wait_for`。
- 核心任务和非核心任务使用不同 timeout。
- 超时后写入 `job_execution_records`。
- 超时后写入 ops event。
- 超时后释放 Redis 锁或任务锁。

验收标准：

- 构造一个 sleep 超时任务可以被正确标记 failed。
- 超时不会导致 active lock 残留。
- `ops-summary` 能看到超时失败。

禁止事项：

- 不在采集器内部到处复制 timeout 逻辑。

### DS-P0-05：拆分核心任务和非核心任务调度池

优先级：`P0`

目标：

确保 `stock_daily -> index_daily -> daily_basic -> moneyflow -> limit_list -> daily_stats -> market_statistics_cache` 不被新闻、财务、历史回补、板块周任务抢资源。

建议文件范围：

- `DataSync/nodes/data_sync/node.py`
- `DataSync/core/settings.py`
- `DataSync/nodes/data_sync/collectors/`
- `DataSync/nodes/data_sync/tasks/`

执行要点：

- 给任务定义 `priority` 或 `resource_class`。
- 核心任务使用 `core`。
- 复盘、新闻、财务、板块映射使用 `background` 或 `heavy`。
- 同一时间只允许一个 `heavy` 任务运行。
- 核心流水线运行时暂停或跳过非核心任务。

验收标准：

- 核心流水线运行时不会启动 `hot_news`、`fina_indicator`、`ths_sector` 等重任务。
- 非核心任务被跳过时有明确 skipped 记录。
- 不影响手动触发核心恢复。

禁止事项：

- 不直接删除非核心任务。

### DS-P0-06：限制高频热点新闻任务

优先级：`P0`

目标：

把 `hot_news` 从持续请求压力最高的任务降为低风险任务，避免每 5 分钟多来源抓取拖垮网络和 CPU。

建议文件范围：

- `DataSync/nodes/data_sync/collectors/news/hot_news.py`
- `DataSync/core/settings.py`
- `DataSync/.env.example`
- `DataSync/.env.docker.example`

执行要点：

- 增加 `HOT_NEWS_ENABLED`。
- 默认可设为关闭或低频。
- 增加来源白名单。
- 增加每源最大条数。
- 增加每轮最大来源数。
- 增加 HTTP 总超时。
- 核心同步窗口期间自动跳过。

验收标准：

- 4C8G 默认配置下热点新闻不会成为持续高压任务。
- 手动启用后仍可工作。
- 跳过原因会写入执行记录。

禁止事项：

- 不影响核心行情数据。

## 5. P1 任务：核心数据稳定更新闭环

### DS-P1-01：统一任务运行记录模型

优先级：`P1`

目标：

把“任务跑没跑”和“目标交易日数据齐没齐”分开记录，解决 `sync_date` 语义混乱。

建议文件范围：

- `DataSync/core/managers/mongo_manager.py`
- `DataSync/nodes/data_sync/node.py`
- `DataSync/nodes/data_sync/services/core_integrity.py`
- `AgentServer/core/managers/mongo_manager.py`

执行要点：

- 明确 `job_execution_records` 字段：
  - `job_name`
  - `run_date`
  - `target_trade_date`
  - `data_cutoff_time`
  - `trigger`
  - `status`
  - `count`
  - `duration_ms`
  - `source`
  - `error`
  - `resource_class`
- 保留 `sync_records` 兼容旧逻辑。
- 新完整性检查优先读取目标交易日覆盖，而不是只看 `sync_records`。

验收标准：

- 每个核心任务执行后都有目标交易日。
- 运行日期和目标交易日不再混用。
- 文档说明旧字段兼容策略。

禁止事项：

- 不一次性迁移历史数据。

### DS-P1-02：完善核心数据完整性检查

优先级：`P1`

目标：

建立可信的核心数据完整性判断，明确某个交易日到底缺什么，不靠人工查表。

建议文件范围：

- `DataSync/nodes/data_sync/services/core_integrity.py`
- `DataSync/nodes/data_sync/node.py`
- `DataSync/main.py`

执行要点：

- 检查核心集合真实数据覆盖：
  - `stock_daily`
  - `index_daily`
  - `daily_basic`
  - `moneyflow_industry`
  - `moneyflow_concept`
  - `limit_list`
  - `daily_stats`
  - `market_statistics_cache`
- 每个数据集定义最低可接受记录数或判断函数。
- 支持最近 N 个交易日窗口。
- 区分：
  - 未到同步窗口。
  - 正在同步。
  - 真实缺失。
  - 数据量异常偏低。

验收标准：

- `--check-core-integrity --integrity-days 4` 能明确列出每个交易日缺失项。
- 对交易日当天未到同步窗口不会误报。
- 对数据量明显异常偏低会标记 warning。

禁止事项：

- 不伪造 ready。

### DS-P1-03：完善 ready marker 写入契约

优先级：`P1`

目标：

让 Web、系统页、运维脚本都能通过统一 ready marker 判断核心市场数据是否可用。

建议文件范围：

- `DataSync/nodes/data_sync/node.py`
- `DataSync/core/managers/mongo_manager.py`
- `AgentServer/nodes/web/api/system_sync.py`
- `AgentServer/nodes/web/api/market.py`

执行要点：

- ready marker 必须包含：
  - `trade_date`
  - `status`
  - `ready_at`
  - `pending_datasets`
  - `ready_datasets`
  - `warnings`
  - `last_checked_at`
- Web 查询接口优先返回 ready marker。
- marker 状态至少包含：
  - `missing`
  - `waiting_window`
  - `building`
  - `ready`
  - `degraded`
  - `failed`

验收标准：

- 数据齐全时 marker 为 ready。
- 缺核心数据时 marker 明确 pending。
- Web 能展示当前核心数据日期与可用状态。

禁止事项：

- 不让页面继续依赖多个散乱接口自行判断。

### DS-P1-04：核心收盘后流水线失败恢复

优先级：`P1`

目标：

当天核心链路中途失败后，系统能从第一个缺失环节继续补，而不是全部重跑或人工逐条命令补。

建议文件范围：

- `DataSync/nodes/data_sync/node.py`
- `DataSync/nodes/data_sync/services/core_integrity.py`
- `DataSync/main.py`

执行要点：

- 根据完整性检查找到第一个缺失核心环节。
- 从该环节开始顺序恢复。
- 每步执行前检查锁。
- 每步失败立即停止，并记录失败点。
- 支持 CLI 和 RPC 两种入口。

验收标准：

- `--recover-latest-core-gaps` 可以补当天缺口。
- 失败后再次执行不会重复写坏已有数据。
- 恢复结果包含 rerun_order 和每步结果。

禁止事项：

- 不强制全链路重跑。

### DS-P1-05：最近窗口自动补缺

优先级：`P1`

目标：

服务重启、系统手动停止、容器崩溃后，能自动检查最近 1-5 个交易日并补齐核心缺口。

建议文件范围：

- `DataSync/nodes/data_sync/node.py`
- `DataSync/main.py`
- `DataSync/core/settings.py`

执行要点：

- 启动后延迟执行一次补缺。
- 常驻每隔固定时间扫描最近窗口。
- 默认窗口为 3 个交易日。
- 最大窗口不超过 10 个交易日。
- 自动补缺只处理核心数据。
- 非核心历史数据不在启动时补。

验收标准：

- 重启后能自动识别最近缺口。
- 自动补缺不会和正在运行的核心任务并发冲突。
- 补缺过程有执行记录和 ops event。

禁止事项：

- 不在启动时做长历史全量回补。

### DS-P1-06：当天核心数据 SLA 时间窗

优先级：`P1`

目标：

明确当天核心数据应该在什么时间尝试同步、什么时间判断失败、什么时间重试，避免过早误判或过晚才发现缺失。

建议文件范围：

- `DataSync/core/settings.py`
- `DataSync/nodes/data_sync/services/core_integrity.py`
- `DataSync/nodes/data_sync/node.py`
- `docs/datasync-task-timeline.md`

执行要点：

- 配置核心 ready 最早检查时间。
- 配置核心 ready 最晚期望时间。
- 配置核心失败告警时间。
- 工作日、非交易日、节假日要区分。
- 当前建议：
  - 15:30 开始 `stock_daily`
  - 15:50-16:10 期望核心可用
  - 16:35 cron 兜底
  - 17:00 后仍缺失则标记 failed/degraded

验收标准：

- `check-core-integrity` 能解释“未到窗口”和“过窗缺失”。
- 文档中有明确 SLA 时间窗。
- ops summary 能看到 latest_effectively_ready。

禁止事项：

- 不把非交易日当缺失。

## 6. P1 任务：采集器基座能力

### DS-P1-07：建立统一 HTTP 客户端基座

优先级：`P1`

当前进度：已完成首个可运行闭环。`UnifiedHttpClient` 已覆盖 GET/POST、超时、重试退避、`Retry-After`、429/503/5xx 分类和非法 JSON 分类；当前先接入 Coze 工作流源，并把结构化错误写入 DataSourceManager 调用统计。第三方库封装源暂不强行改写。

目标：

为外部接口请求提供统一超时、重试、退避、限流、Header、错误分类能力，避免各采集器各写一套。

建议文件范围：

- `DataSync/src/data_sources/`
- `DataSync/core/managers/data_source_manager.py`
- `AgentServer/src/data_sources/`

执行要点：

- 封装统一请求方法。
- 支持 GET/POST。
- 支持请求超时。
- 支持指数退避。
- 支持 429 / 503 / 5xx 分类。
- 支持 `Retry-After`。
- 支持结构化错误返回。
- 记录 source、method、duration、status。

验收标准：

- 核心数据源调用经过统一统计。
- 超时、429、5xx 能被分类。
- 不同数据源可配置不同超时和重试次数。

禁止事项：

- 不强行重写所有第三方库，只包住当前可控调用入口。

### DS-P1-08：统一数据源回退策略

优先级：`P1`

当前进度：已完成首个可运行闭环。DataSourceManager 已按能力和调用形态定义 source chain，支持 `SYNC_SOURCE_CHAIN_OVERRIDES` 覆盖；调用统计会记录实际链路、已尝试来源和 fallback from/to；当所有可尝试来源均报错时会抛出链路错误，避免把源端故障伪装成空数据。

目标：

核心数据源失败时按明确优先级回退，且回退行为可观测、可配置、不可静默伪造。

建议文件范围：

- `DataSync/core/managers/data_source_manager.py`
- `DataSync/core/settings.py`
- `DataSync/src/data_sources/`

执行要点：

- 每个核心能力定义 source chain。
- 回退时记录：
  - failed source
  - fallback source
  - error type
  - duration
- 空结果和失败分开处理。
- 如果所有源失败，返回失败，不构造假数据。

验收标准：

- `data-source-call-stats` 能看到回退次数。
- 核心任务执行记录能说明实际使用的数据源。
- 所有源失败时任务失败且可恢复。

禁止事项：

- 不把空列表当成功，除非该接口业务上允许空。

### DS-P1-09：统一采集器数据校验与清洗入口

优先级：`P1`

当前进度：已完成首个可运行闭环。BaseCollector 的 `_write_buffer` 入口已接入核心集合轻量校验，覆盖 `stock_daily`、`daily_basic`、`index_daily`、`limit_list`、`moneyflow_industry`、`moneyflow_concept`；会校验必填字段、标准化日期、转换数值字段，并记录被丢弃坏记录样本。后续 DS-P1-10 再把坏记录样本落到死信集合。

目标：

核心采集器写库前必须经过基础校验，避免字段缺失、类型异常、日期异常污染数据库。

建议文件范围：

- `DataSync/core/base/collector.py`
- `DataSync/nodes/data_sync/collectors/stock/`
- `DataSync/nodes/data_sync/tasks/`

执行要点：

- 为每类核心数据定义最小 schema。
- 校验必填字段。
- 标准化日期。
- 数值字段做安全转换。
- 单条失败隔离，不影响整批。
- 记录 bad record 样本。

验收标准：

- 核心数据写入前有校验。
- 异常记录不会导致整任务崩溃。
- 错误样本可追踪。

禁止事项：

- 不做复杂 DDL 自适应。
- 不对缺失关键价格字段进行猜测填充。

### DS-P1-10：建立死信/脏数据记录集合

优先级：`P1`

当前进度：已完成首个可运行闭环。MongoManager 已新增 `datasync_dead_letters` 索引和 `record_dead_letters` 方法；BaseCollector 校验失败样本会 best-effort 写入死信集合，单批默认最多 20 条；ops summary 会返回 `recent_dead_letters` 并在核心采集器出现近期死信时生成告警。

目标：

无法解析或无法入库的数据要有归档位置，便于后续排查，而不是只在日志里闪过。

建议文件范围：

- `DataSync/core/managers/mongo_manager.py`
- `DataSync/core/base/collector.py`
- `DataSync/nodes/data_sync/collectors/`

执行要点：

- 新增集合 `datasync_dead_letters`。
- 字段包含：
  - `job_name`
  - `source`
  - `target_trade_date`
  - `reason`
  - `raw_item`
  - `created_at`
  - `error_type`
- 控制单次最大记录量，避免 DLQ 自己打爆库。

验收标准：

- 单条坏数据能进入 DLQ。
- DLQ 有上限保护。
- ops summary 能统计近期 DLQ 数量。

禁止事项：

- 不把大量原始响应全文无限写入。

### DS-P1-11：统一幂等批量写入工具

优先级：`P1`

当前进度：已完成首个可运行闭环。MongoManager 新增 `bulk_upsert_batched`，旧 `bulk_upsert` 保持兼容并委托新入口；新入口强制 `key_fields`、按 `SYNC_BULK_UPSERT_BATCH_SIZE` 控制批次、返回 `matched/modified/upserted/inserted/failed/batch_errors`，批次失败会抛出 `BulkUpsertBatchError`。BaseCollector 的 `_write_buffer` 已切到新入口，并把 `write_results` 挂回任务结果，供 job execution details 记录。

目标：

所有核心采集器使用统一 upsert/bulk 写入方式，保证重复拉取不会重复记录，同时控制批量大小。

建议文件范围：

- `DataSync/core/managers/mongo_manager.py`
- `DataSync/core/base/collector.py`
- `DataSync/nodes/data_sync/collectors/stock/`

执行要点：

- 提供 `bulk_upsert_batched`。
- 必须传业务主键。
- 批大小来自统一配置。
- 写入结果返回 inserted、modified、matched、failed。
- 写入失败时记录批次错误，不吞异常。

验收标准：

- 核心集合重复同步不会产生重复记录。
- 批量写入不会一次性塞入超大列表。
- 写入结果进入 job_execution_records details。

禁止事项：

- 不把 delete+insert 作为默认模式，除非该数据集明确适合全量覆盖。

### DS-P1-12：任务 checkpoint 与断点续拉契约

优先级：`P1`

状态：`已完成基础契约`

目标：

支持任务中断后从安全位置恢复，尤其是历史补缺和多股票扫描类任务。

建议文件范围：

- `DataSync/core/managers/mongo_manager.py`
- `DataSync/core/base/scheduled_job.py`
- `DataSync/core/base/collector.py`
- `DataSync/nodes/data_sync/collectors/stock/daily.py`

执行要点：

- 新增集合 `datasync_checkpoints`。
- checkpoint 维度：
  - `job_name`
  - `target_trade_date`
  - `window`
  - `cursor`
  - `last_success_key`
  - `updated_at`
- 核心当天全市场任务优先按交易日 checkpoint。
- 历史任务按股票代码/日期窗口 checkpoint。
- 完成后标记 checkpoint done。

验收标准：

- 中断后重启不会从头全量重扫。
- checkpoint 可通过 CLI 查看。
- checkpoint 不影响幂等写入。

落地说明：

- 已新增 `datasync_checkpoints` 集合索引和 `MongoManager` 读写方法。
- 已新增 `BaseCollector` checkpoint helper，后续采集器可逐个接入。
- `stock_daily` 已接入按交易日增量续跑和按股票代码/日期窗口历史续跑。
- 已新增 `DataSync/main.py --recent-checkpoints` 运维查看入口。
- 已补充 checkpoint 管理与 `stock_daily` 续跑单元测试。

禁止事项：

- 不依赖本地文件作为唯一状态。

## 7. P1 任务：闲时历史补缺

### DS-P1-13：定义闲时任务窗口

优先级：`P1`

状态：`已完成基础闸门`

目标：

把历史补缺和重型任务限制在晚上 00:00 到早上 08:00，避免白天影响 Web、监听和当天核心数据。

建议文件范围：

- `DataSync/core/settings.py`
- `DataSync/nodes/data_sync/node.py`
- `DataSync/main.py`

执行要点：

- 配置 `DATASYNC_BACKFILL_WINDOW_START=00:00`。
- 配置 `DATASYNC_BACKFILL_WINDOW_END=08:00`。
- 非窗口内 backfill 自动 skipped。
- 手动命令可带 `--force`，但默认不允许。

验收标准：

- 白天不会自动跑历史补缺。
- 闲时窗口内可自动补最近历史缺口。
- skipped 有清晰原因。

落地说明：

- 已新增 `SYNC_BACKFILL_WINDOW_START/END`，并兼容 `DATASYNC_BACKFILL_WINDOW_START/END`。
- Docker 编排已透传默认 `00:00-08:00`，旧服务器 `.env.docker` 缺省时仍使用保守默认值。
- `DataSyncNode` 已在运行入口拦截 `heavy` 任务和显式 `backfill/history` 触发，窗口外返回 `backfill_window_closed` 并记录执行明细。
- CLI 定向恢复新增 `--force`，用于人工确认后绕过闲时窗口；当天核心缺口恢复不受该闸门限制。
- 已补充窗口判断、heavy 任务 skip 和 force 绕过测试。

禁止事项：

- 不阻止当天核心缺口恢复。

### DS-P1-14：建立历史补缺任务队列

优先级：`P1`

状态：`已完成基础队列`

目标：

历史缺口不再靠人工命令临时跑，而是进入一个可控队列，按闲时窗口小批量执行。

建议文件范围：

- `DataSync/core/managers/mongo_manager.py`
- `DataSync/nodes/data_sync/services/backfill_queue.py`
- `DataSync/nodes/data_sync/node.py`
- `DataSync/main.py`

执行要点：

- 新增集合 `datasync_backfill_jobs`。
- 字段包含：
  - `job_id`
  - `dataset`
  - `target_trade_date`
  - `start_date`
  - `end_date`
  - `status`
  - `priority`
  - `attempts`
  - `last_error`
  - `created_by`
- 每轮只取少量任务。
- 支持暂停、失败、完成。

验收标准：

- 可以创建一个最近 4 天补缺任务。
- 闲时 worker 能消费任务。
- 失败不会无限快速重试。

落地说明：

- 已新增 `datasync_backfill_jobs` 集合索引。
- 已新增补缺任务创建、列表、领取、完成、失败、暂停、恢复方法。
- 已新增 `BackfillQueueService`，队列消费时复用任务自身 `recover_trade_date`，不绕过采集器校验。
- 已新增内部 `backfill_queue_worker`，默认每 30 分钟在闲时窗口内最多消费 2 个任务。
- 已新增 CLI：
  - `--enqueue-backfill-job --job-name <dataset> --trade-date <YYYYMMDD>`
  - `--recent-backfill-jobs`
  - `--run-backfill-queue-once`
- 失败任务会按 `SYNC_BACKFILL_MAX_ATTEMPTS` 限制重试次数，耗尽后进入 `failed`。
- 已补充队列状态流转、服务消费和保守默认测试。

禁止事项：

- 不做复杂 UI。

### DS-P1-15：核心历史定向恢复能力补齐

优先级：`P1`

目标：

保证核心数据集都具备 `recover_trade_date(trade_date)` 能力，便于最近几天缺口自动补齐。

建议文件范围：

- `DataSync/nodes/data_sync/collectors/stock/daily.py`
- `DataSync/nodes/data_sync/collectors/stock/index_daily.py`
- `DataSync/nodes/data_sync/collectors/stock/daily_basic.py`
- `DataSync/nodes/data_sync/collectors/stock/moneyflow_industry.py`
- `DataSync/nodes/data_sync/collectors/stock/moneyflow_concept.py`
- `DataSync/nodes/data_sync/collectors/stock/limit_list.py`
- `DataSync/nodes/data_sync/tasks/daily_stats.py`
- `DataSync/nodes/data_sync/tasks/market_statistics_cache.py`

执行要点：

- 每个核心任务提供同名恢复方法。
- 恢复方法只处理指定交易日。
- 恢复前检查该交易日是否交易日。
- 恢复后返回 count、trade_date、source、warnings。

验收标准：

- `recover_job_trade_date` 对所有核心数据集可用。
- 最近 4 天缺口可以自动逐项修复。
- 不支持的任务列表为空或有明确说明。

当前进度：

- 8 个核心数据集均已接入统一 `recover_trade_date` 契约。
- 恢复前统一调用交易日历校验，非法日期和非交易日会显式跳过，交易日历源异常会显式失败并进入可重试路径。
- 恢复结果统一返回 `success`、`count`、`trade_date`、`source`、`sources`、`warnings`、`failed_items` 等字段。
- `daily_basic`、`moneyflow_industry`、`moneyflow_concept`、`limit_list` 的定向恢复会保留实际数据源信息，方便排查源端回退。
- 已补充 `test_recovery_contract.py`，覆盖交易日校验、来源汇总、告警生成和核心恢复方法契约。

禁止事项：

- 不让某个恢复方法偷偷跑长区间。

### DS-P1-16：历史补缺节流与每日预算

优先级：`P1`

目标：

历史补缺不能无限跑，必须有每日请求预算、每晚任务数预算和失败熔断。

建议文件范围：

- `DataSync/core/settings.py`
- `DataSync/nodes/data_sync/services/backfill_queue.py`
- `DataSync/core/managers/data_source_manager.py`

执行要点：

- 配置每晚最大 backfill job 数。
- 配置每晚最大外部请求数。
- 配置连续失败上限。
- 达到预算后停止消费。
- 预算状态写入 ops summary。

验收标准：

- 历史补缺达到预算会停止。
- 停止原因可观测。
- 第二天可继续。

当前进度：

- 已新增每晚最大补缺任务数、每晚最大外部请求数、连续失败熔断配置。
- 补缺队列消费改为逐个领取任务，运行前检查预算，运行后记录当日预算用量，避免一次性领取过多任务后无法中途刹车。
- 预算状态写入 `datasync_backfill_budgets`，包含 `jobs_consumed`、`external_requests`、`success_count`、`failure_count`、`consecutive_failures`。
- 达到预算或连续失败上限时返回 `stopped_reason`，并写入 `backfill_queue_budget_stopped` 运维事件。
- `ops summary` 会展示最近 3 天补缺预算状态，便于确认当晚为什么停止以及第二天是否恢复。
- 已补充队列预算与保守默认测试，覆盖任务预算耗尽和连续失败熔断。

禁止事项：

- 不因为历史补缺预算耗尽影响当天核心同步。

## 8. P2 任务：部署、健康检查与运维体验

### DS-P2-01：增加健康检查与就绪检查命令

优先级：`P2`

目标：

容器编排和人工运维能区分“进程活着”和“核心数据服务可用”。

建议文件范围：

- `DataSync/main.py`
- `DataSync/nodes/data_sync/node.py`
- `DataSync/Dockerfile`
- `DataSync/docker-compose.yml`

执行要点：

- 增加 `--health`。
- 增加 `--ready`。
- `health` 检查进程依赖：配置、Mongo、Redis。
- `ready` 检查核心数据 ready marker 和最近失败状态。
- Docker healthcheck 使用轻量命令。

验收标准：

- `docker compose ps` 能看到健康状态。
- Mongo 不可用时 health 失败。
- 核心数据缺失时 ready 失败但 health 可成功。

当前进度：

- 已新增 `python DataSync/main.py --health`，只校验配置加载、Redis ping、Mongo ping 和主/镜像库状态，不读取核心大集合。
- 已新增 `python DataSync/main.py --ready`，只读取最新 `market_core_ready` marker 和近期核心失败任务，不初始化外部数据源。
- `ready` 将 `ready/degraded` 视为可用状态；marker 缺失或近期核心任务失败时返回非 0。
- 独立 DataSync Docker Compose 已将 `data-sync` healthcheck 切换为 `python main.py --health`。
- 已补充 `test_probe_commands.py`，覆盖 health/ready 探针结果判断。

禁止事项：

- healthcheck 不做重型查询。

### DS-P2-02：完善 ops-summary 作为总探针

优先级：`P2`

目标：

提供一个命令能回答：服务是否健康、数据是否齐、最近是否失败、是否出现数据源退化、是否有慢任务。

建议文件范围：

- `DataSync/nodes/data_sync/services/ops_summary.py`
- `DataSync/main.py`

执行要点：

- 输出核心 ready 状态。
- 输出最近失败任务。
- 输出 unresolved warning/critical ops events。
- 输出数据源退化。
- 输出核心任务耗时异常。
- 输出 backfill 队列状态。
- 支持严格模式退出码。

验收标准：

- `--ops-summary --require-recent-window-ready` 能作为监控命令。
- 输出 JSON 结构稳定。
- 文档给出服务器常用命令。

当前进度：

- `ops-summary` 已新增顶层 `operational_status`，取值为 `healthy/degraded/critical`。
- `ops-summary` 已新增稳定的 `probe_checks`，包含主库健康、最新核心数据就绪、最近窗口就绪、未解决失败、未解决告警、核心数据源退化、核心慢任务、补缺队列可运行等布尔检查。
- 已新增 `backfill_queue_status`，输出队列状态计数、最近少量任务样本、最近预算、预算上限和熔断状态。
- CLI 严格模式已优先复用 `probe_checks`，`--ops-summary --require-recent-window-ready` 可作为监控命令。
- 已补充 `test_ops_summary.py`，覆盖总探针健康/退化/严重状态判断和 backfill 队列检查。

服务器常用命令：

- `docker compose -f DataSync/docker-compose.yml exec data-sync python main.py --ops-summary`
- `docker compose -f DataSync/docker-compose.yml exec data-sync python main.py --ops-summary --require-recent-window-ready`
- `docker compose -f DataSync/docker-compose.yml exec data-sync python main.py --ops-summary --require-no-recent-failures --require-no-warning-events`
- `docker compose -f DataSync/docker-compose.yml exec data-sync python main.py --ops-summary --require-no-core-data-source-degradation --require-no-core-runtime-outliers`

禁止事项：

- 不输出过大的明细列表。

### DS-P2-03：生成生产补数操作手册

优先级：`P2`

目标：

让“最近四天数据缺失怎么补”这种场景有安全标准命令，不再临时猜命令。

建议文件范围：

- `docs/DATASYNC_OPERATIONS.md`

执行要点：

- 写清 Docker 部署下命令。
- 写清本地运行下命令。
- 写清最近 1-5 天核心补缺。
- 写清单任务单交易日补缺。
- 写清如何确认补齐。
- 写清哪些命令不能白天跑。

验收标准：

- 用户能按文档安全补最近四天数据。
- 每条命令说明用途和风险。
- 包含失败后下一步排查。

禁止事项：

- 不推荐直接开放 Mongo 端口。

当前进度：

- 已新增 `docs/DATASYNC_OPERATIONS.md` 作为生产补数操作手册。
- 手册覆盖 Docker Compose、独立 DataSync Compose、本地三种命令前缀。
- 手册覆盖最近 1-5 个交易日核心数据安全补缺、单任务单交易日定向补缺、夜间补缺队列、完成确认、失败排查和白天禁用命令。
- 明确禁止通过开放 MongoDB 端口、手动改库伪造 ready、白天跑大窗口或无限制放大补缺预算来处理生产缺数。

### DS-P2-04：统一 Docker 部署收口

优先级：`P2`

目标：

让服务器简化 Docker 栈可以稳定运行 DataSync，不依赖本地开发配置。

建议文件范围：

- `DataSync/Dockerfile`
- `DataSync/docker-compose.yml`
- `docker-compose.lite.yml`
- `docker-compose.full.yml`
- `.env.docker.example`
- `DataSync/.env.docker.example`

执行要点：

- 确认启动命令。
- 确认 env 文件加载顺序。
- 确认容器健康检查。
- 确认日志目录。
- 确认 Mongo/Redis 主机名。
- 确认资源限制。

验收标准：

- `docker compose config` 通过。
- 简化部署栈有 DataSync 保守配置。
- 缺少可选变量时仍能启动。
- Docker 示例默认不把 Mongo/Redis 暴露到公网。
- DataSync、Mongo、Redis 都有保守资源边界。

禁止事项：

- 不把本地 `.env` 提交。

当前进度：

- 已将根目录简化 Compose、full Compose、独立 DataSync Compose 的 Mongo/Redis 端口映射默认绑定到 `127.0.0.1`。
- 已拆分 `MONGO_PUBLISHED_PORT` / `REDIS_PUBLISHED_PORT` 与容器内连接使用的 `MONGO_PORT` / `REDIS_PORT`，避免改宿主机端口后应用误连容器内错误端口。
- 已为独立 DataSync Compose 补充 `data-sync`、`mongodb`、`redis` 的保守资源边界，并为 full Compose 的 `data-sync` 补齐 CPU 上限。
- 已将根目录 `.env.docker.example` 补齐补缺窗口、补缺预算、ready 时间窗、死信、批量 upsert 和热点新闻保护项。

### DS-P2-05：旧 AgentServer DataSync 替换边界评估

优先级：`P2`

目标：

明确什么时候可以用独立 `DataSync/` 替换 `AgentServer/nodes/data_sync`，哪些功能需要保留兼容。

建议文件范围：

- `AgentServer/nodes/data_sync/`
- `DataSync/`
- `docs/DATASYNC_MIGRATION_PLAN.md`

执行要点：

- 列出旧 DataSync 注册任务。
- 列出新 DataSync 注册任务。
- 对比数据集合、调度时间、恢复能力、配置变量。
- 标记可替换、需迁移、暂不替换。
- 给出灰度部署方案。

验收标准：

- 有迁移对照表。
- 旧链路下线前缺口明确。
- 不会误删仍被 Web/Listener 依赖的能力。

禁止事项：

- 不直接删除旧代码。

当前进度：

- 已新增 `docs/DATASYNC_MIGRATION_PLAN.md`。
- 已完成旧 `AgentServer/nodes/data_sync` 与独立 `DataSync/nodes/data_sync` 的任务注册、能力和集合边界对照。
- 当前结论是独立 DataSync 可以灰度接管核心行情链路，`market_weather` 股票晴雨表任务已迁移到独立 DataSync；正式下线旧链路前仍需生产灰度验证。
- 已给出影子验证、核心链路切换、股票晴雨表验证、旧链路下线四阶段灰度方案。

## 9. P2 任务：可维护与扩展

### DS-P2-06：定义采集器能力声明协议

优先级：`P2`

目标：

每个采集器自描述自己的数据集、依赖、调度、恢复能力、资源等级、数据质量规则，便于后续生成能力目录和运维页面。

建议文件范围：

- `DataSync/core/base/scheduled_job.py`
- `DataSync/core/base/collector.py`
- `DataSync/nodes/data_sync/collectors/`
- `DataSync/nodes/data_sync/tasks/`

执行要点：

- 增加属性：
  - `dataset_name`
  - `resource_class`
  - `target_collections`
  - `dependencies`
  - `supports_recover_trade_date`
  - `supports_backfill`
  - `quality_checks`
  - `default_schedule`
- 任务注册时读取这些声明。

验收标准：

- 能生成所有任务的能力清单。
- 核心任务声明完整。
- 文档可由代码生成或校验。

禁止事项：

- 不要求所有旧任务一次性完美补齐，先核心。

当前进度：

- 已在 `ScheduledJob` 增加统一 `capability_manifest()` 静态能力声明出口。
- 已为保守档核心任务补齐数据集、目标集合、依赖、资源等级、恢复能力和质量规则声明。
- `DataSyncNode.get_capability_manifest()` 可按当前 profile 生成任务能力清单，并通过 RPC `get_data_capabilities` 暴露。
- 已补 `DataSync/tests/test_capability_manifest.py`，覆盖任务级声明、保守档核心能力清单、full 档注册能力和 RPC 出口。

### DS-P2-07：生成机器可读数据能力目录

优先级：`P2`

目标：

提供类似接口文档的 `datasync_capabilities.yaml/json`，描述所有数据更新能力。

建议文件范围：

- `DataSync/config/datasync_capabilities.yaml`
- `DataSync/main.py`
- `docs/DATASYNC_ARCHITECTURE_AND_CAPABILITIES.md`

执行要点：

- 输出能力名。
- 输出目标集合。
- 输出调度。
- 输出依赖。
- 输出是否核心。
- 输出是否可恢复。
- 输出资源等级。
- 输出数据源优先级。

验收标准：

- 有机器可读文件。
- 文档中的数据能力和配置文件一致。
- 后续 Web 可以读取它展示能力状态。

禁止事项：

- 不把运行状态写进静态能力目录。

当前进度：

- 已新增 [datasync_capabilities.yaml](/Users/shangjunhao/Project/StockAgent/DataSync/config/datasync_capabilities.yaml)，记录当前 conservative 档 12 个核心能力。
- 已新增 `DataSync/src/datasync_capabilities.py`，支持构建和写入 YAML/JSON 能力目录。
- `DataSync/main.py` 已支持 `--data-capabilities` 和 `--write-data-capabilities`。
- 能力目录包含能力名、目标集合、默认/生效调度、依赖、是否核心、是否可恢复、资源等级、质量规则和默认数据源链路。
- 已补 `DataSync/tests/test_datasync_capabilities_catalog.py`，覆盖目录构建、YAML/JSON 写入和已生成配置文件一致性。

### DS-P2-08：索引与集合初始化收敛

优先级：`P2`

目标：

避免服务启动时集中创建大量索引造成 Mongo 压力，同时保证核心查询所需索引存在。

建议文件范围：

- `DataSync/core/managers/mongo_manager.py`
- `AgentServer/core/managers/mongo_manager.py`
- `DataSync/main.py`

执行要点：

- 核心索引单独清单。
- 启动时只检查核心索引。
- 非核心索引延迟创建或手动命令创建。
- 单集合索引创建有超时。
- 已存在索引不重复创建。

验收标准：

- 启动不因索引检查长时间阻塞。
- 核心查询具备必要索引。
- 有 CLI 可手动检查/创建索引。

禁止事项：

- 不在交易时段自动跑全量索引重建。

当前进度：

- DataSync `MongoManager` 已支持 `MONGO_INDEX_STARTUP_SCOPE=core/all/none`，默认 `core`，启动只检查核心集合索引。
- DataSync 索引创建增加单集合超时和已存在索引跳过，避免每次启动重复 createIndexes。
- DataSync `--health` / `--ready` 探针已跳过索引检查，避免 Docker 高频探活反复触发索引维护。
- DataSync CLI 已新增 `--ensure-indexes`、`--index-scope`、`--index-collections`，可在闲时手动补齐全量或指定集合索引。
- AgentServer `MongoManager` 已支持启动索引范围配置，默认同样使用 core 范围，避免 Web 重启时集中检查所有业务集合。
- 已补 `DataSync/tests/test_mongo_index_scope.py`，覆盖默认配置、core 范围跳过非核心集合、已存在索引不重复创建。

### DS-P2-09：日志结构化与采样

优先级：`P2`

目标：

日志能用于排查问题，但不会因为高频任务或大批量错误刷爆磁盘。

建议文件范围：

- `DataSync/common/logger/`
- `DataSync/core/base/`
- `DataSync/nodes/data_sync/`

执行要点：

- 核心任务开始/结束日志结构化。
- 错误日志包含 job、trade_date、source、attempt。
- 大量单条错误采样输出。
- 详细错误进入 DLQ 或 job details。
- 日志轮转配置明确。

验收标准：

- 失败时能通过日志定位任务和源。
- 单批大量坏数据不会刷屏。
- Docker 日志量可控。

禁止事项：

- 不把完整外部响应无限打日志。

当前进度：已完成首版结构化与采样收敛。`DataSyncNode` 的任务开始、成功、失败、跳过和超时都会输出稳定事件名，并带上 `job`、`trigger`、`resource_class`、`target_trade_date`、`source`、`attempt`、`duration_ms` 等排障字段；采集器校验丢弃记录时只按 `OBS_LOG_SAMPLE_LIMIT` 输出压缩样本，详细坏数据仍进入 `datasync_dead_letters` 或 job details；日志字段通过 `sanitize_log_value` 截断，避免完整外部响应刷爆 Docker 日志。文件轮转仍由 `OBS_LOG_MAX_SIZE_MB` 与 `OBS_LOG_BACKUP_COUNT` 控制。

## 10. P3 任务：增强能力

### DS-P3-01：动态批次大小调整

优先级：`P3`

目标：

根据 Mongo 写入耗时、失败率、内存压力调整批大小。

建议文件范围：

- `DataSync/core/managers/mongo_manager.py`
- `DataSync/core/base/collector.py`

验收标准：

- 写入变慢时自动缩小批次。
- 写入稳定时不无限扩大。

当前进度：已完成首版动态批次闭环。`bulk_upsert_batched` 会从 `SYNC_BULK_UPSERT_BATCH_SIZE` 起步，并受 `SYNC_BULK_UPSERT_MAX_BATCH_SIZE` 硬上限约束；单批写入耗时超过 `SYNC_BULK_UPSERT_SLOW_BATCH_MS` 时自动缩小到不低于 `SYNC_BULK_UPSERT_MIN_BATCH_SIZE`，连续稳定批次达到 `SYNC_BULK_UPSERT_STABLE_BATCHES_TO_GROW` 后只恢复到本次请求上限，不会无限扩大。返回值新增 `batch_size_history` 与 `adaptive_batching`，采集器会把它们带入 `write_results`，方便从任务详情确认是否发生过降载。

### DS-P3-02：更细的外部限流令牌桶

优先级：`P3`

目标：

不同数据源、不同接口有独立限流预算。

建议文件范围：

- `DataSync/core/managers/data_source_manager.py`
- `DataSync/src/data_sources/`

验收标准：

- Tushare、AKShare、Baostock、Coze 可分别限流。
- 429 后能按源进入冷却。

当前进度：已完成首版源级限流和冷却。`DataSourceManager` 会按 `SYNC_SOURCE_RATE_LIMITS` 为 `tushare/akshare/baostock/coze` 分别创建令牌桶，调用适配器前先获取源级预算；可控 HTTP 源返回 429 时，会按 `Retry-After` 或 `SYNC_SOURCE_RATE_LIMIT_COOLDOWN_SECONDS` 进入源级冷却，冷却期间跳过该源并继续回退到其他可用源。`get_call_stats_summary()` 顶层会返回 `source_rate_limits`，同时单源统计记录 `source_cooling_down`、剩余冷却时间和最近冷却截止时间。

### DS-P3-03：Web 数据能力状态页

优先级：`P3`

目标：

在系统页面展示 DataSync 当前数据能力状态、核心 ready、最近失败、补缺队列。

建议文件范围：

- `AgentServer/nodes/web/api/system_sync.py`
- `frontend/src/views/system/`
- `frontend/src/api/modules/`

验收标准：

- 能看到核心数据日期。
- 能看到缺失数据集。
- 能看到最近失败任务。
- 能手动触发安全补缺。

当前进度：已完成首版 Web 数据能力状态面板。AgentServer 新增 `GET /api/v1/system/datasync/status`，轻量汇总核心 ready marker、机器可读能力目录、最近 7 天失败任务和补缺队列少量摘要；系统“能力状态”页已展示核心交易日、ready/缺失数量、缺失数据集、最近失败、补缺队列，并复用现有安全补最近 3 个交易日核心数据入口。已补充 mock 单测覆盖面板汇总契约。

### DS-P3-04：不可后补数据白名单

优先级：`P3`

目标：

明确哪些数据错过后无法可靠补，给它们更高优先级和更强告警。

建议文件范围：

- `DataSync/config/datasync_capabilities.yaml`
- `DataSync/nodes/data_sync/services/core_integrity.py`

验收标准：

- 能力目录中标记 `recoverability`。
- 不可后补数据失败时 ops event 为 warning/critical。

当前进度：已完成首版可恢复性声明。所有 `ScheduledJob.capability_manifest()` 会输出稳定 `recoverability` 对象，包含 `mode(full/best_effort/none)`、是否支持交易日恢复、是否支持 backfill、是否可重跑、缺失告警级别和原因；核心完整性检查会在顶层和单个数据集状态中输出 `recoverability`。`hot_news` 明确标记为 `mode=none`、`severity_on_missing=warning`，`stock_news` 标记为 `best_effort/warning`；任务失败执行记录会写入 recoverability，不可后补或强时效任务失败时会写入 warning/critical 级 ops event。

### DS-P3-05：Web 可恢复性展示

优先级：`P3`

目标：

在系统能力状态页展示数据能力的可恢复性，避免只看到“缺失”却不知道是“可补”“尽力补”还是“不可还原”。

建议文件范围：

- `AgentServer/nodes/web/api/system_sync.py`
- `frontend/src/views/system/SystemStatusView.vue`
- `frontend/src/api/types.ts`

验收标准：

- DataSync 状态接口输出 `recoverability_summary`。
- 缺失数据集能显示可恢复性模式。
- 最近失败任务能显示对应能力的可恢复性。

当前进度：已完成首版。`GET /api/v1/system/datasync/status` 会返回 `recoverability_summary`，包含能力模式计数、不可完整后补能力和缺失数据集恢复模式；系统“能力状态”页展示不可完整后补/尽力补数量，并在缺失数据集、最近失败任务中标注 `可补/尽力补/不可还原`。

### DS-P3-06：Web 补缺入队闭环

优先级：`P3`

目标：

把系统能力状态页看到的缺失数据集安全加入 DataSync 夜间补缺队列，形成“发现缺口 -> 入队 -> 查看队列”的轻量闭环；Web 不直接消费队列，避免手动操作绕过 4C8G 资源预算。

建议文件范围：

- `AgentServer/nodes/web/api/system.py`
- `AgentServer/nodes/web/api/system_sync.py`
- `frontend/src/views/system/SystemStatusView.vue`
- `frontend/src/api/modules/system.ts`
- `frontend/src/api/types.ts`

验收标准：

- Web API 支持按 `dataset + trade_date` 创建 `datasync_backfill_jobs`。
- 仅允许能力目录中可补或尽力补的数据集入队，不可还原数据拒绝入队。
- 同一数据集和交易日重复入队返回既有任务，不制造重复任务。
- 系统能力状态页能在缺失数据集旁触发入队，并刷新补缺队列摘要。

当前进度：已完成首版。新增 `POST /api/v1/system/datasync/backfill-jobs`，按能力目录校验可恢复性后通过 Mongo upsert 写入 `datasync_backfill_jobs`；系统“能力状态”页在缺失数据集旁展示“加入补缺队列”按钮，只对 `full/best_effort` 数据开放，入队后刷新队列状态。队列状态统计已对齐 DataSync 实际状态 `pending/running/failed/paused/done`。

### DS-P3-07：Web 补缺队列人工操作与审计

优先级：`P3`

目标：

让系统能力状态页能够安全管理补缺队列中的异常任务，支持暂停待执行任务、恢复暂停任务、重试失败任务，并把人工操作写入运维事件；不允许 Web 强制中断正在运行的任务。

建议文件范围：

- `AgentServer/nodes/web/api/system.py`
- `AgentServer/nodes/web/api/system_sync.py`
- `frontend/src/views/system/SystemStatusView.vue`
- `frontend/src/api/modules/system.ts`
- `frontend/src/api/types.ts`

验收标准：

- `pending/failed` 补缺任务可以暂停为 `paused`。
- `paused` 补缺任务可以恢复为 `pending`。
- `failed` 补缺任务可以重试为 `pending`，并重置 attempts 和错误字段。
- `running/done` 任务不允许由 Web 直接改状态。
- 每次人工操作写入 `ops_events`，保留操作者、任务、交易日、前后状态和动作。

当前进度：已完成首版。新增 `PATCH /api/v1/system/datasync/backfill-jobs/{job_id}/action`，支持 `pause/resume/retry` 三个动作并写入 `backfill_queue_manual_action` 运维事件；系统“能力状态”页的补缺队列列表会按任务状态显示“暂停/恢复/重试”按钮，操作后自动刷新队列摘要。

### DS-P3-08：Web 运维事件展示

优先级：`P3`

目标：

把 DataSync 近期运维事件接入系统能力状态页，让补缺队列人工操作、不可后补告警、核心恢复事件可以在页面上追踪，减少只能查日志或上服务器查 Mongo 的情况。

建议文件范围：

- `AgentServer/nodes/web/api/system_sync.py`
- `frontend/src/views/system/SystemStatusView.vue`
- `frontend/src/api/types.ts`

验收标准：

- `GET /api/v1/system/datasync/status` 返回最近少量 `ops_events`。
- 查询必须有时间窗口和数量上限，不能让状态页造成无界读取。
- 页面展示事件类型、级别、来源、时间、消息和关键 details。
- 补缺队列人工操作可以在运维事件中看到动作、前后状态和操作者。

当前进度：已完成首版。状态接口读取最近 72 小时最多 5 条 `datasync/web` 运维事件并输出 `recent_ops_events`；系统“能力状态”页新增“运维事件”卡片，展示事件级别、来源、时间、消息和补缺队列相关 details。

### DS-P3-09：Docker Compose 安全默认值回归测试

优先级：`P3`

目标：

把 DataSync 部署层的 4C8G 保守默认值纳入自动化测试，避免后续修改 `docker-compose.yml`、`docker-compose.full.yml` 或独立 `DataSync/docker-compose.yml` 时，悄悄放开初始同步、任务并发、热点新闻或资源限制。

建议文件范围：

- `DataSync/tests/test_docker_compose_safety.py`
- `docker-compose.yml`
- `docker-compose.full.yml`
- `DataSync/docker-compose.yml`

验收标准：

- 根 compose 与 full compose 的 `data-sync` 服务必须保持 `SYNC_PROFILE=conservative`、禁止初始同步、任务并发为 1、采集并发为 2、禁止首次历史全量回补。
- 根 compose 与 full compose 的 `data-sync` 服务必须保留 0.75 CPU、512M 内存的保守资源限制。
- 根 compose 与 full compose 的 `data-sync` 服务必须默认关闭热点新闻，并限制补缺队列每轮任务数、每晚任务数和外部请求预算。
- 独立 `DataSync/docker-compose.yml` 必须关闭共享环境文件回退，并保留 `python main.py --health` 健康检查。
- 不把独立 DataSync 的 `--health` 直接混入根 compose 的旧 `AgentServer main.py --node-type data_sync` 启动链路，避免入口不一致导致容器误失败。

当前进度：已完成。新增 `DataSync/tests/test_docker_compose_safety.py`，覆盖根 compose、full compose 和独立 DataSync compose 的关键安全默认值；DataSync 全量测试已纳入该测试并通过。

### DS-P3-10：UTC 时间戳时区感知化

优先级：`P3`

目标：

统一替换独立 DataSync 中的 `datetime.utcnow()`，改为 Python 推荐的 `datetime.now(UTC)`，消除 Python 3.13 下的弃用警告，并避免未来 Python 版本升级时把时间戳写入、运行记录、ready marker、checkpoint、补缺队列和运维摘要暴露在兼容性风险里。

建议文件范围：

- `DataSync/core/`
- `DataSync/nodes/data_sync/`
- `DataSync/src/`
- `DataSync/main.py`

验收标准：

- `DataSync/` 下不再存在 `datetime.utcnow()`。
- DataSync 所有 Python 文件可编译通过。
- DataSync 全量单元测试通过。
- `DataSync/main.py --check` 通过。
- 不改变原有“UTC 时间”业务语义，只从 naive UTC datetime 调整为 timezone-aware UTC datetime。

当前进度：已完成。已将 DataSync 范围内的 `datetime.utcnow()` 全部替换为 `datetime.now(UTC)` 并补齐 `UTC` 导入；DataSync 全量编译和 `100` 个单元测试通过，`--check` 通过。Pydantic V2 class-based `Config` 警告已在 `DS-P3-11` 处理，当前严格警告模式也可通过。

### DS-P3-11：Pydantic V2 协议模型迁移

优先级：`P3`

目标：

把独立 DataSync 中仍使用 Pydantic V1 风格 `class Config` 的协议模型迁移为 Pydantic V2 推荐的 `ConfigDict`，避免未来 Pydantic V3 升级时模型导入失败；同时修复迁移过程中容易出现的时间默认值冻结风险。

建议文件范围：

- `DataSync/core/protocols.py`
- `DataSync/src/collector/types.py`
- `DataSync/tests/test_pydantic_v2_protocols.py`

验收标准：

- DataSync 范围内不再存在 Pydantic 模型 `class Config`。
- `StockAnalysisState`、`NewsItem` 等原先允许额外字段的模型继续允许额外字段。
- datetime `default_factory` 必须在每次实例化时执行，不能在模块导入时冻结。
- DataSync 全量编译通过。
- DataSync 全量单元测试通过。
- `PYTHONWARNINGS=error::DeprecationWarning` 下 DataSync 全量测试通过。

当前进度：已完成。`StockAnalysisState` 和 `NewsItem` 已改用 `ConfigDict(extra="allow")`，协议模型时间字段已改为 `lambda: datetime.now(UTC)`；新增 `DataSync/tests/test_pydantic_v2_protocols.py` 覆盖额外字段兼容和时间默认值逐实例刷新；严格警告模式下 DataSync 全量 `102` 个测试通过。

### DS-P3-12：统一提交范围审查

优先级：`P3`

目标：

在 DataSync 重构进入统一提交前，对当前工作区改动做一次范围审查，明确哪些文件属于 DataSync 重构交付，哪些文件默认排除或需要单独确认，避免最终提交混入生成文件、个人工具配置或其他模块遗留改动。

建议文件范围：

- `docs/DATASYNC_UNIFIED_COMMIT_SCOPE_REVIEW.md`
- `docs/DATASYNC_REFACTOR_TASK_BREAKDOWN.md`
- `docs/datasync-task-timeline.md`
- `docs/CHANGELOG.md`

验收标准：

- 明确列出建议纳入统一提交的独立 DataSync、AgentServer 配套、前端系统状态页、Docker 配置和文档范围。
- 明确列出建议排除或单独确认的文件。
- 明确不应提交的运行生成物。
- 给出统一提交前建议验证命令。
- 本任务只做范围审查和文档收口，不提交代码。

当前进度：已完成。新增 `docs/DATASYNC_UNIFIED_COMMIT_SCOPE_REVIEW.md`，建议统一提交纳入 DataSync 主体、AgentServer 配套接口、系统状态页、Docker 保守配置和 DataSync 文档；默认排除 `frontend/src/components.d.ts` 和 `CLAUDE.md`，并记录运行生成物继续保持忽略。统一提交前建议执行 DataSync 全量测试、Web 系统同步测试、`main.py --check`、`--audit-self-contained`、前端构建和 `git diff --check`。

## 11. 推荐执行顺序

第一轮，先保证不会炸：

1. `DS-P0-01`
2. `DS-P0-02`
3. `DS-P0-03`
4. `DS-P0-04`
5. `DS-P0-05`
6. `DS-P0-06`

第二轮，打通核心数据闭环：

1. `DS-P1-01`
2. `DS-P1-02`
3. `DS-P1-03`
4. `DS-P1-04`
5. `DS-P1-05`
6. `DS-P1-06`

第三轮，补齐采集器基座：

1. `DS-P1-07`
2. `DS-P1-08`
3. `DS-P1-09`
4. `DS-P1-10`
5. `DS-P1-11`
6. `DS-P1-12`

第四轮，处理历史补缺：

1. `DS-P1-13`
2. `DS-P1-14`
3. `DS-P1-15`
4. `DS-P1-16`

第五轮，部署与运维收口：

1. `DS-P2-01`
2. `DS-P2-02`
3. `DS-P2-03`
4. `DS-P2-04`
5. `DS-P2-05`

第六轮，维护性增强：

1. `DS-P2-06`
2. `DS-P2-07`
3. `DS-P2-08`
4. `DS-P2-09`

第七轮，最终收口：

1. `DS-P3-09`
2. `DS-P3-10`
3. `DS-P3-11`
4. `DS-P3-12`

## 12. 15 分钟 heartbeat 执行建议

如果按 15 分钟间隔连续推进，建议每次只领取一个任务，最多一个小任务加一个验证任务。

每次 heartbeat 输出必须包含：

- 本轮领取的任务编号。
- 改动文件。
- 验证命令。
- 是否提交。
- 下一轮建议任务编号。
- 未解决风险。

推荐节奏：

- 第 1 天：完成 P0 和部分 P1 核心闭环。
- 第 2 天：完成 P1 核心闭环和采集器基座主要能力。
- 第 3 天：完成闲时补缺、运维命令、Docker 收口。

如果中途发现生产风险，应立即暂停后续功能任务，优先补 P0 保护。

## 13. 完成标准

### 13.1 最小可部署版

必须满足：

- 4C8G 默认配置下 DataSync 不会启动全量重任务。
- 核心任务有并发、超时、批量和锁保护。
- 当天核心数据能按 ready marker 判断。
- 最近 1-5 个交易日核心缺口可检查、可恢复。
- Docker 配置与 `.env.docker` 默认值安全。
- 有安全补数命令文档。

### 13.2 可替代旧 DataSync 版

必须满足：

- 新旧任务能力对照完成。
- 核心数据源能力全部迁移。
- 核心任务定向恢复完整。
- ops summary 可作为生产探针。
- 服务器部署验证通过。
- 旧链路下线范围明确。

### 13.3 长期维护版

必须满足：

- 采集器能力声明完整。
- 数据能力目录机器可读。
- 脏数据、checkpoint、backfill 队列具备稳定实现。
- Web 或系统页可查看数据能力状态。
- 高频、重型、历史任务与核心任务彻底隔离。

## 14. 测试策略

DataSync 重构不是只把代码写出来，而是要达到真正可用。因此后续实现时按下面规则补测试。

### 14.1 每个任务的最低验证

每个任务完成后至少需要执行：

- 语法或编译检查。
- 相关单元测试或最小脚本验证。
- 配置类改动必须执行配置加载检查。
- Docker 类改动必须执行 `docker compose config` 或等价检查。
- 数据恢复类改动必须提供 dry-run、mock 或小范围验证方式。

如果当前环境无法运行某项验证，必须在最终报告里说明原因和替代检查。

### 14.2 大模块完成时必须补测试

下面这些独立模块完成后必须配套测试用例：

- 资源预算与任务硬超时。
- 核心完整性检查。
- ready marker 写入与读取。
- 最近窗口自动补缺。
- 数据源回退与调用统计。
- 数据校验与 DLQ。
- 幂等批量写入。
- checkpoint 与断点续拉。
- backfill 队列与闲时窗口。
- health / ready / ops-summary 运维命令。

测试可以先走单元测试和 mock，不要求一开始就接真实外部接口。

### 14.3 测试优先还是后补

执行策略：

- 对基础设施模块，优先先写或同步补单元测试，例如资源预算、超时、完整性检查、幂等写入。
- 对强依赖真实数据源的采集任务，可以先完成最小实现，再补 mock 测试和小范围真实验证。
- 对 Docker、运维命令和生产补数流程，优先补命令级验证和操作文档，再逐步补自动化测试。

原则是：可以分阶段补测试，但不能在大模块完成后长期没有测试保护。

### 14.4 heartbeat 任务的测试要求

每次 15 分钟 heartbeat 推进时，应在报告中明确：

- 本轮是否新增或修改测试。
- 本轮执行了哪些验证命令。
- 哪些验证因为环境限制未执行。
- 当前模块是否仍缺测试。
- 下一轮是否需要优先补测试。
