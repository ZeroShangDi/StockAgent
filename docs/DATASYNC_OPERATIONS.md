# DataSync 生产补数操作手册

本文用于生产环境安全处理“最近 1-5 个交易日核心数据缺失”的场景。目标是优先补齐核心市场数据，同时避免历史补缺、重型任务或外部接口重试压垮 4C8G 服务器。

## 适用范围

本手册适用于这些核心数据缺口：

- `stock_daily`：股票日 K。
- `index_daily`：核心指数日 K。
- `daily_basic`：每日指标。
- `moneyflow_industry`：行业资金流。
- `moneyflow_concept`：概念资金流。
- `limit_list`：涨跌停数据。
- `daily_stats`：每日统计。
- `market_statistics_cache`：市场统计缓存。

不适用范围：

- 大规模多年历史全量补库。
- 财务、新闻、板块历史等非核心重型任务。
- 直接连接或开放 MongoDB 端口做人工修数据。

## 命令前缀

Docker 简化部署推荐使用项目根目录命令：

```bash
docker compose exec data-sync python DataSync/main.py
```

独立 DataSync Compose 部署使用：

```bash
docker compose -f DataSync/docker-compose.yml exec data-sync python main.py
```

本地运行使用：

```bash
AgentServer/venv/bin/python DataSync/main.py
```

下文用 `<DS>` 代表上述任一命令前缀。

## 先诊断

1. 先看进程依赖是否健康。

```bash
<DS> --health
```

用途：只检查配置、Redis、Mongo，不读取大集合。
风险：低，可白天执行。

2. 再看核心数据是否就绪。

```bash
<DS> --ready
```

用途：只读取最新 `market_core_ready` marker 和近期核心失败任务。
风险：低，可白天执行。

3. 查看完整运维总览。

```bash
<DS> --ops-summary --integrity-days 4 --job-log-limit 10
```

用途：确认缺哪些交易日、哪些核心数据集、是否有补缺队列熔断。
风险：中低，会做核心完整性检查，但不会主动补数。

## 安全补最近 1-5 天

推荐优先使用安全窗口恢复命令，例如最近 4 个交易日：

```bash
<DS> --safe-recover-core-window --integrity-days 4
```

用途：先检查、再恢复最近核心缺口、必要时逐个任务定向恢复、最后再检查。
风险：中。只处理核心数据，但可能触发外部接口请求；建议收盘后或低峰执行。

如果只补最新交易日：

```bash
<DS> --recover-latest-core-gaps
```

如果补最近 3 个交易日：

```bash
<DS> --recover-recent-core-gaps --integrity-days 3
```

注意事项：

- `--integrity-days` 建议在 `1-5` 之间，不要在生产上直接拉很大窗口。
- 如果源端限流或失败，命令会显式失败或记录告警，不会捏造数据。
- 白天交易时间不要跑大窗口补缺，避免和 Web、监听、当天核心同步抢资源。

## 单任务单交易日定向补

当已经确认某个数据集某天缺失时，可定向恢复。例如补 `index_daily` 的 `20260526`：

```bash
<DS> --recover-job-trade-date --job-name index_daily --trade-date 20260526
```

用途：只调用该任务的 `recover_trade_date`，适合明确缺口。
风险：中低。仍会访问外部数据源，但范围最小。

常见示例：

```bash
<DS> --recover-job-trade-date --job-name stock_daily --trade-date 20260526
<DS> --recover-job-trade-date --job-name daily_basic --trade-date 20260526
<DS> --recover-job-trade-date --job-name moneyflow_industry --trade-date 20260526
<DS> --recover-job-trade-date --job-name moneyflow_concept --trade-date 20260526
<DS> --recover-job-trade-date --job-name limit_list --trade-date 20260526
```

## 夜间补缺队列

如果缺口不紧急，建议加入夜间补缺队列：

```bash
<DS> --enqueue-backfill-job --job-name stock_daily --trade-date 20260526
<DS> --enqueue-backfill-job --job-name daily_basic --trade-date 20260526
```

查看队列：

```bash
<DS> --recent-backfill-jobs --backfill-status pending
<DS> --recent-backfill-jobs --backfill-status failed
```

手动消费一轮队列：

```bash
<DS> --run-backfill-queue-once
```

用途：按队列预算小批量补缺。
风险：中。默认只在 `00:00-08:00` 闲时窗口自动消费。

只有确认服务器资源允许时，才可窗口外强制消费：

```bash
<DS> --run-backfill-queue-once --force
```

## 确认补齐

补数后先看总探针：

```bash
<DS> --ops-summary --integrity-days 4 --job-log-limit 10
```

严格确认最近窗口已 ready：

```bash
<DS> --ops-summary --integrity-days 4 --require-recent-window-ready
```

同时确认没有近期失败和未解决告警：

```bash
<DS> --ops-summary --integrity-days 4 --require-recent-window-ready --require-no-recent-failures --require-no-warning-events
```

成功标准：

- `operational_status` 为 `healthy` 或可接受的 `degraded`。
- `probe_checks.recent_window_ready=true`。
- `probe_checks.no_unresolved_recent_failures=true`。
- `core_integrity.blocking_incomplete_trade_dates=[]`。

## 失败后排查

1. 看最近失败任务。

```bash
<DS> --recent-failed-jobs --job-log-limit 20
```

2. 看最近运维事件。

```bash
<DS> --recent-ops-events --event-lookback-hours 24
```

3. 看数据源退化。

```bash
<DS> --ops-summary --require-no-core-data-source-degradation
```

4. 看补缺队列预算和熔断。

```bash
<DS> --ops-summary --job-log-limit 10
```

重点字段：

- `backfill_queue_status.status_counts`
- `backfill_queue_status.latest_budget`
- `backfill_queue_status.consecutive_failure_exhausted`
- `alerts`

## 白天禁止或慎用

白天交易时段不要执行：

- 大窗口 `--safe-recover-core-window --integrity-days 5`。
- 多个 `stock_daily` 或 `daily_basic` 定向补缺连续运行。
- `--run-backfill-queue-once --force`。
- 非核心重型历史回补任务。

白天可执行：

- `--health`
- `--ready`
- `--ops-summary`
- 单个非常明确且范围很小的 `--recover-job-trade-date`

## 禁止事项

- 不要开放 MongoDB 端口给本地直接连接补数。
- 不要手动修改生产 Mongo 集合来伪造 ready 状态。
- 不要把 `SYNC_BACKFILL_WINDOW_START/END` 改成全天开放。
- 不要把 `SYNC_BACKFILL_MAX_JOBS_PER_NIGHT` 和 `SYNC_BACKFILL_MAX_EXTERNAL_REQUESTS_PER_NIGHT` 调得过大。
- 不要在源端连续超时或限流时反复手动重跑；应先等待或切换到夜间队列。
