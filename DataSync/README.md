# DataSync

独立的 `DataSync` 服务目录。当前版本已经具备独立代码、独立配置、独立运行目录和独立容器入口，不再需要通过 `PYTHONPATH` 反向依赖别的服务目录。

## 本地校验

使用任意满足 [requirements.txt](/Users/shangjunhao/Project/StockAgent/DataSync/requirements.txt) 的 Python 环境：

```bash
cp DataSync/.env.example DataSync/.env
```

然后执行：

```bash
python DataSync/main.py --check
```

这会完成：

- 环境文件加载
- 独立运行目录初始化
- 任务注册检查

如果要额外检查它是否仍然保持“真正独立”，可以执行：

```bash
python DataSync/main.py --audit-self-contained
```

这会验证：

- 当前没有使用仓库根共享环境文件回退
- `DataSync/` 下所有 Python 模块都能在独立环境内导入
- 代码里没有重新引入 `AgentServer`、`nodes.web`、`nodes.listener`、`nodes.inference` 这些跨服务依赖
- 运行时加载到的本地 `common/core/nodes/src/config` 模块都实际来自 `DataSync/` 自己，而不是仓库其他位置的同名包

`DataSync` 会优先只读取自身目录下的 `DataSync/.env` 或 `DataSync/.env.docker`。如果本地没有这些文件，当前版本仍会临时回退到仓库共享环境文件作为兼容兜底，并在启动时打印警告。建议把 `DATASYNC_ALLOW_SHARED_ENV_FALLBACK=0` 保持开启，这样它就不会再偷偷借用仓库根配置。

`core/settings.py` 的默认 dotenv 路径现在也固定指向 `DataSync/.env`，不会再因为你从别的工作目录启动，或者修改 `DATASYNC_RUNTIME_DIR`，就把 `BaseSettings` 的默认读取位置带偏。

如果要做一次更接近真实启动链路的验证：

```bash
python DataSync/main.py --check-startup
```

它会初始化 `Redis`、`MongoDB`、数据源管理器、`LLM`、调度器和 RPC 服务，然后立刻退出。

如果要直接查看最近交易日的核心链路完整性：

```bash
python DataSync/main.py --check-core-integrity --integrity-days 2
```

这个检查现在会区分几种情况：

- `waiting_window`：还没到默认 `15:30` 的核心同步观察窗口，不触发恢复和故障判断
- `syncing_window`：默认 `15:30-16:10`，可以恢复缺口，但不会把未齐数据当成故障
- `overdue`：默认 `16:10-17:00`，核心链路应该已经 ready，缺失会进入阻断缺口
- `failed`：默认 `17:00` 后仍缺失，会标记为明确失败态，便于告警和排障

对应配置为 `SYNC_CORE_READY_CHECK_AFTER_LOCAL_TIME`、`SYNC_CORE_READY_EXPECTED_AFTER_LOCAL_TIME`、`SYNC_CORE_READY_FAIL_AFTER_LOCAL_TIME`。旧的 `SYNC_CORE_READY_AFTER_LOCAL_TIME` 仅保留兼容，默认等同于期望 ready 时间。

如果你希望这个命令在“最近窗口里只要还有任何旧交易日没 ready”时直接返回非 0 退出码，可以加：

```bash
python DataSync/main.py --check-core-integrity --integrity-days 3 --require-recent-window-ready
```

如果要手动触发一次“最新交易日核心缺口恢复”：

```bash
python DataSync/main.py --recover-latest-core-gaps
```

这个命令会检查最新交易日缺少哪些核心数据，并按核心链路顺序尽量补齐，再打印恢复结果和最新完整性概览。

如果要检查并尽量补齐最近几天窗口里的核心缺口：

```bash
python DataSync/main.py --recover-recent-core-gaps --integrity-days 3
```

如果希望用一条命令安全地补最近窗口，比如最近 4 个交易日：

```bash
python DataSync/main.py --safe-recover-core-window --integrity-days 4
```

这个命令会依次执行：

- 检查最近窗口完整性
- 先跑一轮最近窗口自动恢复
- 如果还有缺口，只对残缺的任务/交易日做定向补数
- 最后再做一次严格完整性检查，并用退出码告诉你窗口是否已经补齐

为了优先保证核心同步主链路稳定，下面这些能力的默认数据源顺序都已经调整为传统源优先：

- `index_daily`: `tushare -> baostock -> akshare`
- `latest_trade_date`: `tushare -> baostock -> akshare -> coze`
- `trade_calendar`: `tushare -> baostock -> akshare -> coze`
- 全市场 `daily_basic(trade_date=...)`: `tushare -> baostock -> akshare -> coze`

也就是说，正常情况下会优先走更稳定的 `Tushare`，只有它不可用或返回空结果时才回退到免费源；`Coze` 继续更适合单股、实时和增强型请求。

为了避免某一个源长时间卡住整条核心同步链路，这些核心能力现在还额外带了一层“单源保守超时 + 自动回退”：

- `index_daily`
- `latest_trade_date`
- `trade_calendar`
- 全市场 `daily(trade_date=...)`
- 全市场 `daily_basic(trade_date=...)`
- `moneyflow_industry`
- `moneyflow_concept`
- `limit_list`

另外，`index_daily` 现在默认按 3 个核心指数串行抓取，而不是并发抓取。因为这里只有 3 个指数，串行带来的耗时增加很小，但能明显降低单源抖动、锁竞争和异常长尾把整条恢复链路拖住的概率。

如果要直接调用某个任务的 `recover_trade_date` 能力做定向修复：

```bash
python DataSync/main.py --recover-job-trade-date --job-name index_daily --trade-date 20260526
```

这个命令会：

- 对最新交易日继续走完整的核心恢复链路
- 对更早但仍在最近窗口内的交易日，只对已经具备 `recover_trade_date` 能力的核心任务做定向补缺
- 明确列出当前还不支持历史定向恢复的核心环节

默认常驻恢复任务现在也会按最近窗口巡检，而不只是盯最新交易日。窗口大小由 `RECENT_CORE_GAP_RECOVERY_DAYS` 控制，默认是 `3`。

如果要单独查看当前主库/镜像库同步目标状态：

```bash
python DataSync/main.py --check-sync-targets
```

这个命令会输出：

- 主库是否健康
- 镜像库是否启用、是否连接成功
- 镜像写入成功/失败计数
- 最近一次镜像写入成功时间
- 最近一次镜像写入错误
- 镜像写入是否正处于降级状态，以及最近一次恢复时间

如果要直接查看最近失败的任务执行记录：

```bash
python DataSync/main.py --recent-failed-jobs --failure-lookback-hours 24
```

如果只关心核心链路失败：

```bash
python DataSync/main.py --recent-failed-jobs --core-jobs-only
```

如果要查看最近的运维事件，比如自动补缺、核心任务失败、恢复完成：

```bash
python DataSync/main.py --recent-ops-events --event-severities info,warning
```

如果只想看最近 6 小时内的运维事件：

```bash
python DataSync/main.py --recent-ops-events --event-severities warning,critical --event-lookback-hours 6
```

如果想看核心同步任务最近 24 小时的成功率和耗时摘要：

```bash
python DataSync/main.py --core-job-runtime-summary --runtime-lookback-hours 24
```

这里的 `success_rate` 现在只按真正执行过的 `success/failed` 计算，`skipped` 不会再把成功率拉低；耗时统计也只看真正执行过的记录，不会再被 `Already synced` / `lock_held` 这类跳过样本稀释。摘要里还会单独给出 `latest_executed_*` 字段，方便区分“最近一次只是跳过”还是“最近一次真正执行成功/失败”。

另外，运行摘要现在还会显式给出 `outlier_jobs`，用于标记最近窗口里“明显异常长”的核心任务。当前默认阈值是：

- `latest_executed_duration_ms >= 10 分钟`
- `p95_duration_ms >= 5 分钟`

这样像 `index_daily` 这类虽然最终成功、但执行时间异常长的任务，就不会再只埋在明细里了。

像 `index_daily` 这类核心链路任务，现在还会把更细的任务内明细写进执行记录：

- 每个指数的 `ts_code`
- 实际命中的 `source`
- 拉回记录数
- 写入记录数
- 单指数耗时 `duration_ms`

这样后面如果再出现长尾，就能直接判断到底是哪个指数、哪个源在拖慢，而不是只看到一个整任务总耗时。

如果要单独查看当前 `DataSync` 进程内的数据源调用统计：

```bash
python DataSync/main.py --data-source-call-stats
```

这里会按 `method + source` 维度输出：

- 调用次数
- 成功 / 超时 / 失败 / 空结果次数
- 回退次数
- 最近状态
- 最近错误
- 最近耗时
- 最近成功 / 超时 / 失败时间

这层统计更适合排查“是不是某个免费源最近总在超时”或者“某个核心方法是不是一直在回退到次级源”。

如果想把这层统计窗口清零，重新观察“从现在开始还会不会继续抖”，可以执行：

```bash
python DataSync/main.py --reset-data-source-call-stats
```

这会重置当前 `DataSync` 进程内的数据源统计窗口，并返回新的 `started_at`。

如果要看一份更适合运维排查的综合摘要：

```bash
python DataSync/main.py --ops-summary --integrity-days 2 --job-log-limit 10
```

如果要把它直接当成监控探针，并要求最近窗口也必须全绿：

```bash
python DataSync/main.py --ops-summary --integrity-days 3 --job-log-limit 10 --require-recent-window-ready
```

如果还希望“最近窗口必须全绿，而且最近不能出现失败任务”，可以再加：

```bash
python DataSync/main.py --ops-summary --integrity-days 3 --job-log-limit 10 --require-recent-window-ready --require-no-recent-failures
```

如果还希望“最近窗口必须全绿，而且最近事件窗口里不能出现 warning / critical 运维事件”，可以再加：

```bash
python DataSync/main.py --ops-summary --integrity-days 3 --job-log-limit 10 --event-lookback-hours 6 --require-recent-window-ready --require-no-warning-events
```

这里的 `--require-no-warning-events` 现在看的是“最近窗口内尚未被后续恢复或 ready marker 覆盖的 warning/critical 运维事件”，不会再被已经补绿后的旧 warning 误卡住。

如果还希望“最近窗口必须全绿，而且当前 `DataSync` 进程里最近没有出现数据源退化（超时 / 失败 / 回退）”，可以再加：

```bash
python DataSync/main.py --ops-summary --integrity-days 3 --job-log-limit 10 --require-recent-window-ready --require-no-data-source-degradation
```

这里的 `--require-no-data-source-degradation` 看的是当前 `DataSync` 进程内的 `data_source_runtime_stats.degraded_entry_count`。它适合挂在长跑中的常驻 `DataSync` 健康探针上，用来表达“这条进程最近虽然可能最终补成功了，但底层源端其实已经开始抖了”。

如果你只想盯“核心同步方法”的数据源健康，而不让新闻之类的边缘采集源影响主探针，可以改用：

```bash
python DataSync/main.py --ops-summary --integrity-days 3 --job-log-limit 10 --require-recent-window-ready --require-no-core-data-source-degradation
```

这里看的是 `data_source_runtime_stats.core_degraded_entry_count`，默认只统计这批核心方法：

- `get_latest_trade_date`
- `get_trade_calendar`
- `get_daily`
- `get_daily_basic`
- `get_index_daily`
- `get_moneyflow_industry`
- `get_moneyflow_concept`
- `get_limit_list`

如果你还希望把“核心任务虽然成功了，但最近耗时已经明显异常长”也挡在健康探针上，可以再加：

```bash
python DataSync/main.py --ops-summary --integrity-days 3 --job-log-limit 10 --require-recent-window-ready --require-no-core-runtime-outliers
```

这里看的是 `core_job_runtime_summary.outlier_job_count`。当前默认 outlier 阈值是：

- 最近一次真正执行成功耗时 `>= 10 分钟`
- 或 `p95_duration_ms >= 5 分钟`

这个摘要会同时包含：

- 最新核心链路完整性概览
- 主库 / 镜像库状态
- 当前 DataSync 进程内的数据源运行态统计（超时 / 回退 / 空结果 / 最近错误）
- 最近任务执行记录
- 最近真正执行过的任务记录（不含 `skipped`）
- 最近真正执行过的核心任务记录（不含 `skipped`）
- 最近失败任务记录
- 最近运维事件
- 核心任务近期运行耗时与成功率摘要
- 当前告警信号

本地直接跑 `--check-startup` 时，如果加载到 Docker 风格环境变量（例如 `REDIS_HOST=redis`），启动器会自动把这些容器内主机名转换为本地 `localhost`，避免本机自检被容器地址绊住。

现在这层归一也已经下沉到了 `RedisManager`、`MongoManager`、`MilvusManager` 自身初始化里。所以即使不是通过 `DataSync/main.py` 入口，而是直接跑临时 Python 脚本，只要是在本机环境下，它们也会把 `redis` / `mongodb` / `milvus` 这类容器内主机名自动收回到 `localhost`。

如果需要直接启动：

```bash
python DataSync/main.py
```

也支持从 `DataSync/` 目录内部启动：

```bash
cd DataSync
python main.py
```

## 容器方式

```bash
cd DataSync
cp .env.docker.example .env.docker
docker compose --env-file .env.docker up --build
```

容器会：

- 使用 `DataSync/Dockerfile`
- 启动独立的 `data-sync + mongo + redis`
- 将日志和数据固定落在 `DataSync` 自己的运行目录
- 仅依赖 `DataSync/` 自己的代码和部署文件
- 默认禁止共享仓库根环境文件回退
- 本地 `.env`、`.env.docker`、`logs/`、`data/` 不会被打进镜像构建上下文

## 当前实现边界

当前版本已经可以独立运行，但仍然保留了部分从历史服务中迁出的同源代码：

- `common/`
- `core/`
- `src/config`
- `src/data_sources`
- `nodes/data_sync`

这让 `DataSync` 先具备独立部署能力，同时保留后续继续精简、重组目录边界的空间。

## 运行目录约定

默认情况下，独立 `DataSync` 会把运行时文件固定到自身目录下：

- 日志：`DataSync/logs/`
- 本地数据：`DataSync/data/`
- Milvus Lite：`DataSync/data/milvus_lite.db`

如果需要自定义，可以通过下面的环境变量覆盖：

- `DATASYNC_RUNTIME_DIR`
- `DATASYNC_DATA_DIR`
- `OBS_LOG_DIR`
- `MILVUS_URI`
