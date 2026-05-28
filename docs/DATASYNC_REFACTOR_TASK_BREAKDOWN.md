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

禁止事项：

- 不依赖本地文件作为唯一状态。

## 7. P1 任务：闲时历史补缺

### DS-P1-13：定义闲时任务窗口

优先级：`P1`

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

禁止事项：

- 不阻止当天核心缺口恢复。

### DS-P1-14：建立历史补缺任务队列

优先级：`P1`

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

禁止事项：

- 不把本地 `.env` 提交。

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
