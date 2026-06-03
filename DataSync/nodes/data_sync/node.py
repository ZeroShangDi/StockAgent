"""
数据同步节点实现

使用分布式锁防止多个节点重复抓取同一天的行情数据。
使用 BulkWrite 批量写入提高同步效率。
"""

import asyncio
import logging
from datetime import UTC, date, datetime, time
from typing import Optional, List, Type

from common.logger import log_event
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from core.base import BaseNode, ScheduledJob
from core.protocols import NodeType
from core.managers.redis_manager import redis_manager
from core.managers.mongo_manager import mongo_manager
from core.managers.data_source_manager import data_source_manager
from core.managers.llm_manager import llm_manager

# 数据采集器 (Collectors)
from .collectors import (
    StockBasicCollector,
    StockDailyCollector,
    DailyBasicCollector,
    IndexBasicCollector,
    IndexDailyCollector,
    MoneyflowIndustryCollector,
    MoneyflowConceptCollector,
    LimitListCollector,
    StockRelationsCollector,
    StockNewsCollector,
    FinaIndicatorCollector,
    HotNewsCollector,
    # 复盘相关
    ThsSectorCollector,
    ReviewDataCollector,
)

# 处理任务 (Tasks)
from .tasks import (
    DailyStatsTask,
    MarketStatisticsCacheTask,
    MarketWeatherTask,
)
from .services.core_integrity import build_core_integrity_overview
from .services.ops_summary import (
    build_ops_summary,
    get_core_job_runtime_summary,
    get_recent_failed_job_executions,
    get_recent_ops_events,
)
from .services.backfill_queue import BackfillQueueService


class DataSyncNode(BaseNode):
    """
    数据同步节点

    职责:
    - 定时从 Tushare 同步股票基础数据、日线数据
    - 同步新闻舆情数据
    - 将数据存储到 MongoDB

    特性:
    - 分布式锁防止多节点重复抓取
    - BulkWrite 批量写入
    - 通过 gRPC RPC 接收远程调用
    """

    node_type = NodeType.DATA_SYNC
    DEFAULT_RPC_PORT = 50054  # DataSyncNode 默认 RPC 端口
    POST_CLOSE_CORE_PIPELINE = [
        "index_daily",
        "daily_basic",
        "moneyflow_industry",
        "moneyflow_concept",
        "limit_list",
        "stock_relations",
        "daily_stats",
        "market_statistics_cache",
    ]
    CORE_READY_MARKER = "market_core_ready"
    CORE_READY_DATASETS = [
        "stock_daily",
        "index_daily",
        "daily_basic",
        "moneyflow_industry",
        "moneyflow_concept",
        "limit_list",
        "daily_stats",
        "market_statistics_cache",
    ]
    CORE_GAP_RECOVERY_SCHEDULE = "*/20 * * * *"
    CORE_EVENT_JOB_NAMES = set(CORE_READY_DATASETS)
    RECENT_RECOVERABLE_DATASETS = {
        "stock_daily",
        "index_daily",
        "daily_basic",
        "moneyflow_industry",
        "moneyflow_concept",
        "limit_list",
        "daily_stats",
        "market_statistics_cache",
    }
    CORE_JOB_NAMES = {
        "stock_basic",
        "stock_daily",
        "daily_basic",
        "index_basic",
        "index_daily",
        "moneyflow_industry",
        "moneyflow_concept",
        "limit_list",
        "stock_relations",
        "daily_stats",
        "market_statistics_cache",
        "market_weather",
    }
    RESOURCE_CLASS_BY_JOB = {
        **{name: "core" for name in CORE_JOB_NAMES},
        "stock_news": "background",
        "hot_news": "background",
        "review_data": "background",
        "ths_sector": "heavy",
        "fina_indicator": "heavy",
    }
    STATIC_SOURCE_CHAINS = {
        "get_index_basic": ["tushare", "akshare", "baostock"],
        "coze_market_indicator_workflow": ["coze"],
    }
    BACKFILL_TRIGGER_KEYWORDS = ("backfill", "history")
    JOB_CLASSES: List[Type[ScheduledJob]] = [
        # 数据采集 (Collectors)
        StockBasicCollector,
        StockDailyCollector,
        DailyBasicCollector,
        IndexBasicCollector,
        IndexDailyCollector,
        MoneyflowIndustryCollector,
        MoneyflowConceptCollector,
        LimitListCollector,
        StockRelationsCollector,
        StockNewsCollector,
        FinaIndicatorCollector,
        HotNewsCollector,
        # 复盘数据采集
        ThsSectorCollector,
        ReviewDataCollector,
        # 处理任务 (Tasks)
        DailyStatsTask,
        MarketStatisticsCacheTask,
        MarketWeatherTask,
    ]

    def __init__(self, node_id: Optional[str] = None, rpc_port: int = 0):
        from core.settings import settings
        super().__init__(node_id, rpc_port or settings.rpc.data_sync_port)

        self._scheduler: Optional[AsyncIOScheduler] = None
        self._jobs: List[ScheduledJob] = []
        # 节点级运行预算：默认 1，避免多个采集任务同时抢 CPU/Mongo/上游接口。
        self._job_semaphore = asyncio.Semaphore(max(1, settings.data_sync.max_running_jobs))
        # 重任务单独串行，即使 full/custom 档提高总并发，也不允许多个 heavy 任务叠加。
        self._heavy_job_semaphore = asyncio.Semaphore(1)
        self._active_core_jobs = 0
        self._active_core_pipelines = 0

    async def start(self) -> None:
        """启动数据同步节点"""
        from core.settings import settings

        # 按依赖顺序初始化管理器
        self.logger.info("Initializing managers...")
        await redis_manager.initialize()      # 心跳注册 + 分布式锁
        await mongo_manager.initialize()      # 数据存储
        await data_source_manager.initialize()  # 统一数据源管理
        await llm_manager.initialize()        # LLM / 统计分析

        # 启动 RPC 服务器
        await self._start_rpc_server()

        # 注册定时任务
        self._register_jobs()

        # 创建调度器。保守默认：错过的任务合并执行，单任务不并发重入。
        self._scheduler = AsyncIOScheduler(
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": max(1, settings.data_sync.scheduler_misfire_grace_seconds),
            }
        )

        # 注册采集任务
        for job in self._jobs:
            self._schedule_job(job)

        self._schedule_core_gap_recovery(
            settings.data_sync.core_gap_recovery_schedule,
            settings.data_sync.recent_core_gap_recovery_days,
        )
        self._schedule_backfill_queue_worker(settings.data_sync.backfill_queue_schedule)

        # 启动调度器
        self._scheduler.start()

        if settings.data_sync.run_core_gap_recovery_on_startup:
            asyncio.create_task(
                self._run_startup_core_gap_recovery(
                    settings.data_sync.recent_core_gap_recovery_days,
                )
            )

        self.logger.info(f"Data sync node started with {len(self._jobs)} jobs")

    async def stop(self) -> None:
        """停止节点"""
        if self._scheduler:
            self._scheduler.shutdown()

    async def run(self) -> None:
        """节点主循环"""
        # 首次启动默认不跑全任务，避免服务器重启时触发同步风暴。
        if self.settings.data_sync.run_initial_sync:
            self.logger.info("Running initial sync...")
            await self._run_all_jobs()

        # 保持运行
        while self._running:
            await asyncio.sleep(60)

    def _register_jobs(self) -> None:
        """注册所有定时任务"""
        for cls in self.JOB_CLASSES:
            job = cls()
            resource_class = self._get_job_resource_class(job.name)
            setattr(job, "resource_class", resource_class)
            if not self._should_register_job(job.name):
                self.logger.info(
                    "Skipped job registration: %s (profile=%s, resource_class=%s)",
                    job.name,
                    self.settings.data_sync.profile,
                    resource_class,
                )
                continue

            self._jobs.append(job)
            self.logger.info(
                "Registered job: %s (resource_class=%s)",
                job.name,
                resource_class,
            )

    @staticmethod
    def _parse_job_name_list(value: Optional[str]) -> set[str]:
        if not value:
            return set()
        return {item.strip() for item in value.split(",") if item.strip()}

    def _get_job_resource_class(self, job_name: str) -> str:
        return self.RESOURCE_CLASS_BY_JOB.get(job_name, "background")

    def _should_register_job(self, job_name: str) -> bool:
        settings = self.settings.data_sync
        enabled_jobs = self._parse_job_name_list(settings.enabled_jobs)
        disabled_jobs = self._parse_job_name_list(settings.disabled_jobs)

        if enabled_jobs:
            return job_name in enabled_jobs and job_name not in disabled_jobs
        if job_name in disabled_jobs:
            return False
        if settings.profile == "full":
            return True
        if settings.profile == "custom":
            return False
        return job_name in self.CORE_JOB_NAMES

    def _schedule_job(self, job: ScheduledJob) -> None:
        """调度任务"""
        async def run_job():
            await self._run_job_with_lock(job, trigger="scheduler")

        # 解析 cron 表达式
        trigger = CronTrigger.from_crontab(job.schedule)

        self._scheduler.add_job(
            run_job,
            trigger=trigger,
            id=job.name,
            name=f"Job: {job.name}",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=max(1, self.settings.data_sync.scheduler_misfire_grace_seconds),
        )

    def _schedule_core_gap_recovery(self, custom_schedule: Optional[str], recent_days: int) -> None:
        """调度核心链路缺口恢复检查。"""
        schedule = custom_schedule or self.CORE_GAP_RECOVERY_SCHEDULE
        trigger = CronTrigger.from_crontab(schedule)
        window_days = max(1, min(int(recent_days or 1), 10))

        async def run_recovery():
            if window_days > 1:
                result = await self._recover_recent_core_gaps(trigger="auto_recovery", days=window_days)
                if result.get("success") and result.get("recovered"):
                    self.logger.info(
                        "Recent core gap recovery completed for %s trade days",
                        window_days,
                    )
            else:
                result = await self._recover_latest_core_gaps(trigger="auto_recovery")
            if window_days == 1 and result.get("success") and result.get("recovered"):
                self.logger.info(
                    "Core gap recovery reran datasets for %s: %s",
                    result.get("trade_date"),
                    ",".join(result.get("rerun_order", [])),
                )
                await self._record_ops_event(
                    event_type="core_gap_recovery_reran",
                    severity="info",
                    message=f"Core gap recovery reran datasets for {result.get('trade_date')}",
                    source="auto_recovery",
                    details={
                        "trade_date": result.get("trade_date"),
                        "rerun_order": result.get("rerun_order", []),
                    },
                )

        self._scheduler.add_job(
            run_recovery,
            trigger=trigger,
            id="core_gap_recovery",
            name="Job: core_gap_recovery",
            replace_existing=True,
        )
        self.logger.info(
            "Registered internal recovery job: core_gap_recovery (%s, recent_days=%s)",
            schedule,
            window_days,
        )

    def _schedule_backfill_queue_worker(self, custom_schedule: Optional[str]) -> None:
        """调度历史补缺队列 worker。"""
        schedule = custom_schedule or "*/30 * * * *"
        if not schedule:
            return
        trigger = CronTrigger.from_crontab(schedule)

        async def run_backfill_queue():
            await self._run_backfill_queue_worker(trigger="auto_backfill_queue")

        self._scheduler.add_job(
            run_backfill_queue,
            trigger=trigger,
            id="backfill_queue_worker",
            name="Job: backfill_queue_worker",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        self.logger.info("Registered internal backfill queue worker: %s", schedule)

    async def _run_backfill_queue_worker(
        self,
        *,
        trigger: str,
        force_window: bool = False,
    ) -> dict:
        """在闲时窗口内小批量消费历史补缺队列。"""
        window_state = self._get_backfill_window_state()
        if not force_window and not window_state["open"]:
            result = {
                "success": True,
                "skipped": True,
                "reason": "backfill_window_closed",
                "backfill_window": window_state,
            }
            self.logger.info(
                "Backfill queue skipped outside window %s-%s",
                window_state["start"],
                window_state["end"],
            )
            return result

        if self._is_core_resource_busy():
            result = {
                "success": True,
                "skipped": True,
                "reason": "core_resource_busy",
                "backfill_window": window_state,
            }
            self.logger.info("Backfill queue skipped while core resource is busy")
            return result

        settings = self.settings.data_sync
        service = BackfillQueueService(mongo_manager)
        result = await service.run_once(
            self,
            limit=max(1, min(int(settings.backfill_jobs_per_round or 1), 20)),
            max_attempts=max(1, int(settings.backfill_max_attempts or 3)),
            max_jobs_per_night=max(0, int(settings.backfill_max_jobs_per_night or 0)),
            max_external_requests_per_night=max(
                0,
                int(settings.backfill_max_external_requests_per_night or 0),
            ),
            consecutive_failure_limit=max(1, int(settings.backfill_consecutive_failure_limit or 1)),
        )
        result["trigger"] = trigger
        result["backfill_window"] = window_state

        if result.get("claimed"):
            await self._record_ops_event(
                event_type="backfill_queue_consumed",
                severity="warning" if result.get("failed_count") else "info",
                message=(
                    f"Backfill queue consumed {result.get('claimed')} jobs, "
                    f"failed={result.get('failed_count')}"
                ),
                source=trigger,
                details={
                    "claimed": result.get("claimed"),
                    "success_count": result.get("success_count"),
                    "failed_count": result.get("failed_count"),
                },
            )
        if result.get("stopped_reason"):
            await self._record_ops_event(
                event_type="backfill_queue_budget_stopped",
                severity="warning",
                message=f"Backfill queue stopped: {result.get('stopped_reason')}",
                source=trigger,
                details={
                    "reason": result.get("stopped_reason"),
                    "budget_date": result.get("budget_date"),
                    "budget": result.get("budget"),
                },
            )
        return result

    async def _run_startup_core_gap_recovery(self, recent_days: int) -> None:
        """启动后延迟触发一次核心链路缺口恢复。"""
        await asyncio.sleep(5)
        try:
            window_days = max(1, min(int(recent_days or 1), 10))
            if window_days > 1:
                result = await self._recover_recent_core_gaps(trigger="startup_recovery", days=window_days)
                if result.get("success") and result.get("results"):
                    self.logger.info(
                        "Startup recent core gap recovery scanned %s trade days",
                        window_days,
                    )
            else:
                result = await self._recover_latest_core_gaps(trigger="startup_recovery")
                if result.get("success") and result.get("recovered"):
                    self.logger.info(
                        "Startup core gap recovery reran datasets for %s: %s",
                        result.get("trade_date"),
                        ",".join(result.get("rerun_order", [])),
                    )
                    await self._record_ops_event(
                        event_type="core_gap_recovery_reran",
                        severity="info",
                        message=f"Startup core gap recovery reran datasets for {result.get('trade_date')}",
                        source="startup_recovery",
                        details={
                            "trade_date": result.get("trade_date"),
                            "rerun_order": result.get("rerun_order", []),
                        },
                    )
        except Exception as exc:
            self.logger.warning(f"Startup core gap recovery failed: {exc}")
            await self._record_ops_event(
                event_type="core_gap_recovery_failed",
                severity="warning",
                message="Startup core gap recovery failed",
                source="startup_recovery",
                details={"error": str(exc)},
            )

    async def _run_job_with_lock(
        self,
        job: ScheduledJob,
        *,
        allow_follow_ups: bool = True,
        trigger: str = "scheduler",
        pipeline_name: Optional[str] = None,
        force_backfill_window: bool = False,
    ) -> dict:
        """
        使用分布式锁运行任务

        防止多个节点重复执行同一任务。
        """
        resource_class = self._get_job_resource_class(job.name)
        if self._requires_backfill_window(job, trigger) and not force_backfill_window:
            window_state = self._get_backfill_window_state()
            if not window_state["open"]:
                started_at = datetime.now(UTC)
                result = {
                    "success": False,
                    "skipped": True,
                    "reason": "backfill_window_closed",
                    "error": (
                        f"Job {job.name} skipped outside backfill window "
                        f"{window_state['start']}-{window_state['end']}"
                    ),
                    "resource_class": resource_class,
                    "backfill_window": window_state,
                }
                await self._record_job_execution(
                    job=job,
                    result=result,
                    started_at=started_at,
                    finished_at=datetime.now(UTC),
                    trigger=trigger,
                    pipeline_name=pipeline_name,
                )
                log_event(
                    self.logger,
                    logging.INFO,
                    "datasync_job_skipped",
                    job=job.name,
                    trigger=trigger,
                    resource_class=resource_class,
                    reason="backfill_window_closed",
                    backfill_window=window_state,
                )
                return result

        if trigger == "scheduler" and resource_class != "core" and self._is_core_resource_busy():
            started_at = datetime.now(UTC)
            result = {
                "success": False,
                "skipped": True,
                "reason": "core_resource_busy",
                "error": "Non-core job skipped while core pipeline is active",
                "resource_class": resource_class,
            }
            await self._record_job_execution(
                job=job,
                result=result,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                trigger=trigger,
                pipeline_name=pipeline_name,
            )
            log_event(
                self.logger,
                logging.INFO,
                "datasync_job_skipped",
                job=job.name,
                trigger=trigger,
                resource_class=resource_class,
                reason="core_resource_busy",
            )
            return result

        async with self._job_semaphore:
            heavy_acquired = False
            if resource_class == "heavy":
                await self._heavy_job_semaphore.acquire()
                heavy_acquired = True

            today = date.today().strftime("%Y%m%d")
            lock_key = f"sync:{job.name}:{today}"
            lock_timeout = max(1, int(self.settings.data_sync.lock_timeout_seconds))

            # 尝试获取锁
            lock = None
            core_marked_active = False
            try:
                lock = await redis_manager.try_lock(lock_key, timeout=lock_timeout)

                if lock is None:
                    log_event(
                        self.logger,
                        logging.INFO,
                        "datasync_job_skipped",
                        job=job.name,
                        trigger=trigger,
                        resource_class=resource_class,
                        reason="lock_held",
                        lock_key=lock_key,
                    )
                    return {"success": False, "skipped": True, "reason": "lock_held"}

                started_at = datetime.now(UTC)
                if resource_class == "core":
                    self._active_core_jobs += 1
                    core_marked_active = True

                log_event(
                    self.logger,
                    logging.INFO,
                    "datasync_job_started",
                    job=job.name,
                    trigger=trigger,
                    resource_class=resource_class,
                    pipeline_name=pipeline_name,
                    lock_key=lock_key,
                    timeout_seconds=self.settings.data_sync.job_timeout_seconds,
                )
                result = await self._run_job_with_timeout(job, started_at=started_at)
                finished_at = datetime.now(UTC)
                target_trade_date = await self._resolve_target_trade_date(job, result)
                if target_trade_date:
                    result.setdefault("target_trade_date", target_trade_date)

                if result.get("success"):
                    log_event(
                        self.logger,
                        logging.INFO,
                        "datasync_job_completed",
                        job=job.name,
                        trigger=trigger,
                        resource_class=resource_class,
                        pipeline_name=pipeline_name,
                        target_trade_date=target_trade_date,
                        source=self._extract_data_source(result),
                        count=result.get("count", 0),
                        duration_ms=result.get("duration_ms", 0.0),
                    )
                else:
                    log_event(
                        self.logger,
                        logging.ERROR,
                        "datasync_job_failed",
                        job=job.name,
                        trigger=trigger,
                        resource_class=resource_class,
                        pipeline_name=pipeline_name,
                        target_trade_date=target_trade_date,
                        source=self._extract_data_source(result),
                        attempt=result.get("attempt"),
                        reason=result.get("reason"),
                        error=result.get("error"),
                        duration_ms=result.get("duration_ms", 0.0),
                    )

                await self._record_job_execution(
                    job=job,
                    result=result,
                    started_at=started_at,
                    finished_at=finished_at,
                    trigger=trigger,
                    pipeline_name=pipeline_name,
                )

                if job.name == "stock_daily" and result.get("success") and target_trade_date:
                    await self._refresh_core_ready_marker(
                        target_trade_date,
                        source=f"{trigger}:{job.name}",
                        force_status="building",
                        pipeline_name=pipeline_name,
                    )

                if allow_follow_ups and result.get("success"):
                    await self._maybe_run_follow_up_pipeline(job.name)

                if result.get("success") and target_trade_date and job.name in self.CORE_READY_DATASETS:
                    await self._refresh_core_ready_marker(
                        target_trade_date,
                        source=f"{trigger}:{job.name}",
                        pipeline_name=pipeline_name,
                    )

                return result

            finally:
                if core_marked_active:
                    self._active_core_jobs = max(0, self._active_core_jobs - 1)
                if lock is not None:
                    # 释放锁
                    await lock.release()
                    self.logger.debug(f"Lock released: {lock_key}")
                if heavy_acquired:
                    self._heavy_job_semaphore.release()

    def _is_core_resource_busy(self) -> bool:
        return self._active_core_jobs > 0 or self._active_core_pipelines > 0

    @staticmethod
    def _parse_local_hhmm(value: str, fallback: str) -> time:
        text = str(value or fallback).strip()
        try:
            hour_text, minute_text = text.split(":", 1)
            hour = int(hour_text)
            minute = int(minute_text)
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return time(hour=hour, minute=minute)
        except Exception:
            pass
        hour_text, minute_text = fallback.split(":", 1)
        return time(hour=int(hour_text), minute=int(minute_text))

    def _get_backfill_window_state(self, now: Optional[datetime] = None) -> dict:
        """返回本地时间是否处于历史补缺窗口内。"""
        settings = self.settings.data_sync
        start_text = str(settings.backfill_window_start or "00:00")
        end_text = str(settings.backfill_window_end or "08:00")
        start = self._parse_local_hhmm(start_text, "00:00")
        end = self._parse_local_hhmm(end_text, "08:00")
        current = (now or datetime.now()).time()

        if start == end:
            is_open = False
        elif start < end:
            is_open = start <= current < end
        else:
            is_open = current >= start or current < end

        return {
            "open": is_open,
            "start": start.strftime("%H:%M"),
            "end": end.strftime("%H:%M"),
            "current": current.strftime("%H:%M"),
        }

    def _requires_backfill_window(self, job: ScheduledJob, trigger: str) -> bool:
        """判断任务是否必须在闲时窗口内运行。

        先保护 heavy 和显式 backfill/history 触发；核心缺口恢复不走这里，
        避免影响当天市场数据补齐。
        """
        resource_class = self._get_job_resource_class(job.name)
        if resource_class == "heavy":
            return True
        trigger_text = str(trigger or "").lower()
        if any(keyword in trigger_text for keyword in self.BACKFILL_TRIGGER_KEYWORDS):
            return True
        return bool(getattr(job, "requires_backfill_window", False))

    async def _run_job_with_timeout(self, job: ScheduledJob, *, started_at: datetime) -> dict:
        """以节点级硬超时运行任务，避免外部接口或数据库调用无限卡住。"""
        timeout_seconds = max(1, int(self.settings.data_sync.job_timeout_seconds))
        try:
            return await asyncio.wait_for(job.run(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            finished_at = datetime.now(UTC)
            duration_ms = max((finished_at - started_at).total_seconds() * 1000, 0.0)
            result = {
                "success": False,
                "error": f"job_timeout_after_{timeout_seconds}s",
                "reason": "timeout",
                "duration_ms": duration_ms,
            }
            job._last_run = finished_at
            job._last_result = result
            log_event(
                self.logger,
                logging.ERROR,
                "datasync_job_timeout",
                job=job.name,
                resource_class=self._get_job_resource_class(job.name),
                timeout_seconds=timeout_seconds,
                duration_ms=duration_ms,
            )
            return result

    async def _run_all_jobs(self) -> None:
        """运行所有任务（跳过 run_at_startup=False 的任务）"""
        for job in self._jobs:
            # 跳过不在启动时运行的任务
            if not getattr(job, 'run_at_startup', True):
                self.logger.info(f"Job {job.name} skipped (run_at_startup=False)")
                continue

            try:
                await self._run_job_with_lock(job, trigger="startup")
            except Exception as e:
                self.logger.exception(f"Job {job.name} error: {e}")

    async def run_job(self, job_name: str, *, force_backfill_window: bool = False) -> dict:
        """手动运行指定任务"""
        for job in self._jobs:
            if job.name == job_name:
                return await self._run_job_with_lock(
                    job,
                    trigger="manual",
                    force_backfill_window=force_backfill_window,
                )

        return {"success": False, "error": f"Job not found: {job_name}"}

    def get_job_status(self) -> List[dict]:
        """获取所有任务状态"""
        return [
            {
                **j.status,
                "resource_class": self._get_job_resource_class(j.name),
            }
            for j in self._jobs
        ]

    def get_capability_manifest(self, *, registered_only: bool = False) -> dict:
        """导出 DataSync 静态数据能力清单。

        该清单只描述任务能力，不读取 Mongo，也不包含最近运行结果，方便文档、
        运维页面和 Web API 复用同一份声明。
        """
        if self._jobs:
            jobs = list(self._jobs)
        else:
            jobs = [cls() for cls in self.JOB_CLASSES]

        source_chains = {
            **getattr(data_source_manager, "DEFAULT_SOURCE_CHAINS", {}),
            **self.STATIC_SOURCE_CHAINS,
        }
        capabilities = []
        for job in jobs:
            if registered_only and not self._jobs:
                continue
            if not self._jobs and not self._should_register_job(job.name):
                continue
            capabilities.append(
                job.capability_manifest(
                    resource_class=self._get_job_resource_class(job.name),
                    source_chains=source_chains,
                )
            )

        return {
            "success": True,
            "profile": self.settings.data_sync.profile,
            "count": len(capabilities),
            "core_ready_marker": self.CORE_READY_MARKER,
            "core_ready_datasets": list(self.CORE_READY_DATASETS),
            "core_recoverable_datasets": sorted(self.RECENT_RECOVERABLE_DATASETS),
            "source_chain_catalog": source_chains,
            "capabilities": capabilities,
        }

    async def _maybe_run_follow_up_pipeline(self, job_name: str) -> None:
        """在关键上游任务成功后，尽快串行推进核心收盘后链路。"""
        if job_name != "stock_daily":
            return

        today = date.today().strftime("%Y%m%d")
        pipeline_lock = await redis_manager.try_lock(
            f"pipeline:post_close_core:{today}",
            timeout=3600,
        )
        if pipeline_lock is None:
            self.logger.info("Post-close core pipeline skipped: already running on another node")
            return

        try:
            self._active_core_pipelines += 1
            self.logger.info(
                "Starting post-close core pipeline: %s",
                " -> ".join(self.POST_CLOSE_CORE_PIPELINE),
            )
            for downstream_job_name in self.POST_CLOSE_CORE_PIPELINE:
                downstream_job = self._get_job(downstream_job_name)
                if downstream_job is None:
                    self.logger.warning(f"Post-close pipeline missing job: {downstream_job_name}")
                    continue

                result = await self._run_job_with_lock(
                    downstream_job,
                    allow_follow_ups=False,
                    trigger="pipeline",
                    pipeline_name="post_close_core",
                )

                if not result.get("success"):
                    self.logger.warning(
                        "Post-close core pipeline paused at %s: %s",
                        downstream_job_name,
                        result.get("error") or result.get("reason") or "unknown_failure",
                    )
                    break

            self.logger.info("Post-close core pipeline completed")
        finally:
            self._active_core_pipelines = max(0, self._active_core_pipelines - 1)
            await pipeline_lock.release()

    def _extract_target_trade_date(self, result: dict) -> Optional[str]:
        for key in ("target_trade_date", "trade_date", "end_date", "sync_date"):
            value = result.get(key)
            if value:
                return str(value)
        return None

    async def _resolve_target_trade_date(self, job: ScheduledJob, result: dict) -> Optional[str]:
        target_trade_date = self._extract_target_trade_date(result)
        if target_trade_date:
            return target_trade_date
        if self._get_job_resource_class(job.name) != "core":
            return None
        try:
            latest_trade_date, _ = await data_source_manager.get_latest_trade_date()
            return str(latest_trade_date) if latest_trade_date else None
        except Exception as exc:
            self.logger.warning(
                "Failed to resolve target_trade_date for core job %s: %s",
                job.name,
                exc,
            )
            return None

    def _extract_data_source(self, result: dict) -> Optional[str]:
        for key in ("source", "data_source", "provider"):
            value = result.get(key)
            if value:
                return str(value)
        return None

    async def _record_job_execution(
        self,
        *,
        job: ScheduledJob,
        result: dict,
        started_at: datetime,
        finished_at: datetime,
        trigger: str,
        pipeline_name: Optional[str],
    ) -> None:
        status = "success"
        if result.get("skipped"):
            status = "skipped"
        elif not result.get("success"):
            status = "failed"

        details = {
            "message": result.get("message"),
            "success": result.get("success"),
            "skipped": result.get("skipped", False),
        }
        for key in (
            "start_date",
            "end_date",
            "trade_date",
            "sync_type",
            "reason",
            "success_batches",
            "failed_batches",
            "success_dates",
            "failed_dates",
            "backfilled",
            "index_results",
            "failed_items",
        ):
            if key in result:
                details[key] = result.get(key)

        try:
            duration_ms = result.get("duration_ms")
            if duration_ms is None:
                duration_ms = max((finished_at - started_at).total_seconds() * 1000, 0.0)
            target_trade_date = await self._resolve_target_trade_date(job, result)
            data_cutoff_time = result.get("data_cutoff_time") or target_trade_date
            resource_class = self._get_job_resource_class(job.name)
            if target_trade_date:
                details["target_trade_date"] = target_trade_date
            details["run_date"] = started_at.strftime("%Y%m%d")
            details["resource_class"] = resource_class
            details["recoverability"] = job.capability_manifest(
                resource_class=resource_class,
            ).get("recoverability")
            await mongo_manager.record_job_execution(
                job_name=job.name,
                node_id=self.node_id,
                started_at=started_at,
                finished_at=finished_at,
                status=status,
                trigger=trigger,
                run_date=started_at.strftime("%Y%m%d"),
                target_trade_date=target_trade_date,
                data_cutoff_time=str(data_cutoff_time) if data_cutoff_time else None,
                count=result.get("count"),
                duration_ms=duration_ms,
                error=result.get("error"),
                resource_class=resource_class,
                source=self._extract_data_source(result),
                details=details,
                pipeline_name=pipeline_name,
            )
            failure_event_severity = self._get_failure_ops_event_severity(job, resource_class)
            if status == "failed" and failure_event_severity:
                await self._record_ops_event(
                    event_type=(
                        "core_job_failed"
                        if job.name in self.CORE_EVENT_JOB_NAMES
                        else "unrecoverable_or_time_sensitive_job_failed"
                    ),
                    severity=failure_event_severity,
                    message=f"DataSync job failed: {job.name}",
                    source=trigger,
                    details={
                        "job_name": job.name,
                        "target_trade_date": target_trade_date,
                        "error": result.get("error"),
                        "pipeline_name": pipeline_name,
                        "recoverability": job.capability_manifest(
                            resource_class=resource_class,
                        ).get("recoverability"),
                    },
                )
        except Exception as exc:
            self.logger.warning(f"Failed to record job execution for {job.name}: {exc}")

    def _get_failure_ops_event_severity(self, job: ScheduledJob, resource_class: str) -> Optional[str]:
        """根据任务可恢复性判断失败是否需要进入运维事件。"""
        try:
            recoverability = job.capability_manifest(resource_class=resource_class).get("recoverability") or {}
        except Exception:
            recoverability = {}

        severity = str(recoverability.get("severity_on_missing") or "").strip().lower()
        if severity in {"warning", "critical"}:
            return severity
        if job.name in self.CORE_EVENT_JOB_NAMES:
            return "warning"
        return None

    async def _record_ops_event(
        self,
        *,
        event_type: str,
        severity: str,
        message: str,
        source: str,
        details: Optional[dict] = None,
    ) -> None:
        try:
            await mongo_manager.record_ops_event(
                event_type=event_type,
                severity=severity,
                message=message,
                source=source,
                node_id=self.node_id,
                details=details or {},
            )
        except Exception as exc:
            self.logger.warning(f"Failed to record ops event {event_type}: {exc}")

    async def _refresh_core_ready_marker(
        self,
        trade_date: str,
        *,
        source: str,
        force_status: Optional[str] = None,
        pipeline_name: Optional[str] = None,
    ) -> None:
        dataset_sync_dates: dict[str, Optional[str]] = {}
        ready_datasets: list[str] = []
        pending_datasets: list[str] = []
        warnings: list[dict] = []
        integrity_entry: Optional[dict] = None
        checked_at = datetime.now(UTC)

        integrity = await build_core_integrity_overview(days=10)
        if integrity.get("success"):
            for entry in integrity.get("overview", []):
                if str(entry.get("trade_date")) == str(trade_date):
                    integrity_entry = entry
                    break

        if integrity_entry:
            for item in integrity_entry.get("datasets", []):
                dataset = str(item.get("dataset") or "")
                if not dataset:
                    continue
                dataset_sync_dates[dataset] = item.get("sync_date")
                if item.get("ok"):
                    ready_datasets.append(dataset)
                else:
                    pending_datasets.append(dataset)
                    if item.get("state") == "warning":
                        warnings.append(
                            {
                                "dataset": dataset,
                                "reason": item.get("reason"),
                                "count": item.get("count"),
                                "expected_count": item.get("expected_count"),
                            }
                        )
            status = force_status or self._derive_core_marker_status(integrity_entry, ready_datasets, pending_datasets)
        else:
            for dataset in self.CORE_READY_DATASETS:
                sync_date = await mongo_manager.get_last_sync_date(dataset)
                dataset_sync_dates[dataset] = sync_date
                if sync_date == trade_date:
                    ready_datasets.append(dataset)
                else:
                    pending_datasets.append(dataset)
            status = force_status or ("ready" if not pending_datasets else "building")

        details = {
            "dataset_sync_dates": dataset_sync_dates,
            "ready_datasets": ready_datasets,
            "pending_datasets": pending_datasets,
            "warnings": warnings,
            "last_checked_at": checked_at.isoformat(),
            "pipeline_name": pipeline_name,
            "source": source,
        }
        if integrity_entry:
            details["integrity_ready"] = bool(integrity_entry.get("ready"))
            details["integrity_expected_ready"] = bool(integrity_entry.get("expected_ready"))
            details["awaiting_sync_window"] = bool(integrity_entry.get("awaiting_sync_window"))
            details["syncing_window"] = bool(integrity_entry.get("syncing_window"))
            details["sla_phase"] = integrity_entry.get("sla_phase")
            details["missing_datasets"] = integrity_entry.get("missing_datasets", [])
            details["warning_datasets"] = integrity_entry.get("warning_datasets", [])
            details["failed_datasets"] = integrity_entry.get("failed_datasets", [])

        await mongo_manager.upsert_readiness_marker(
            marker_type=self.CORE_READY_MARKER,
            trade_date=trade_date,
            status=status,
            details=details,
            source=source,
            node_id=self.node_id,
            ready_at=datetime.now(UTC) if status == "ready" else None,
            ready_datasets=ready_datasets,
            pending_datasets=pending_datasets,
            warnings=warnings,
            last_checked_at=checked_at,
        )

    def _derive_core_marker_status(
        self,
        integrity_entry: dict,
        ready_datasets: list[str],
        pending_datasets: list[str],
    ) -> str:
        if integrity_entry.get("ready"):
            return "ready"
        if integrity_entry.get("awaiting_sync_window"):
            return "waiting_window"
        if integrity_entry.get("failed_datasets"):
            return "failed"

        missing_datasets = list(integrity_entry.get("missing_datasets") or [])
        warning_datasets = list(integrity_entry.get("warning_datasets") or [])
        if missing_datasets:
            return "building" if ready_datasets else "missing"
        if warning_datasets:
            return "degraded"
        return "building" if pending_datasets else "ready"

    async def _recover_job_trade_date(
        self,
        job_name: str,
        trade_date: str,
        *,
        trigger: str,
        pipeline_name: str = "targeted_trade_date_recovery",
        force_backfill_window: bool = False,
    ) -> dict:
        """执行单个任务的定向交易日恢复，并补齐执行记录与就绪标记。"""
        job = self._get_job(job_name)
        if not job:
            return {"success": False, "error": f"Unknown job: {job_name}"}

        recover_fn = getattr(job, "recover_trade_date", None)
        if not callable(recover_fn):
            return {"success": False, "error": f"Job {job_name} does not support recover_trade_date"}

        if self._requires_backfill_window(job, trigger) and not force_backfill_window:
            window_state = self._get_backfill_window_state()
            if not window_state["open"]:
                started_at = datetime.now(UTC)
                result = {
                    "success": False,
                    "skipped": True,
                    "reason": "backfill_window_closed",
                    "error": (
                        f"Targeted recovery for {job_name} skipped outside backfill window "
                        f"{window_state['start']}-{window_state['end']}"
                    ),
                    "trade_date": trade_date,
                    "backfill_window": window_state,
                }
                await self._record_job_execution(
                    job=job,
                    result=result,
                    started_at=started_at,
                    finished_at=datetime.now(UTC),
                    trigger=trigger,
                    pipeline_name=pipeline_name,
                )
                return {
                    "success": False,
                    "job_name": job_name,
                    "trade_date": trade_date,
                    "result": result,
                }

        async with self._job_semaphore:
            lock_key = f"sync:{job_name}:{trade_date}"
            lock = await redis_manager.try_lock(
                lock_key,
                timeout=max(1, int(self.settings.data_sync.lock_timeout_seconds)),
            )
            started_at = datetime.now(UTC)
            if lock is None:
                result = {
                    "success": False,
                    "skipped": True,
                    "reason": "lock_held",
                    "error": f"Targeted recovery lock already held: {lock_key}",
                    "trade_date": trade_date,
                }
                await self._record_job_execution(
                    job=job,
                    result=result,
                    started_at=started_at,
                    finished_at=datetime.now(UTC),
                    trigger=trigger,
                    pipeline_name=pipeline_name,
                )
                return {
                    "success": False,
                    "job_name": job_name,
                    "trade_date": trade_date,
                    "result": result,
                }

            started_at = datetime.now(UTC)
            try:
                try:
                    result = await asyncio.wait_for(
                        recover_fn(trade_date),
                        timeout=max(1, int(self.settings.data_sync.job_timeout_seconds)),
                    )
                    if "success" not in result:
                        result = {"success": True, **result}
                except asyncio.TimeoutError:
                    result = {
                        "success": False,
                        "error": f"job_timeout_after_{max(1, int(self.settings.data_sync.job_timeout_seconds))}s",
                        "reason": "timeout",
                        "trade_date": trade_date,
                    }
                except Exception as exc:
                    result = {
                        "success": False,
                        "error": str(exc),
                        "trade_date": trade_date,
                    }
                finished_at = datetime.now(UTC)

                await self._record_job_execution(
                    job=job,
                    result=result,
                    started_at=started_at,
                    finished_at=finished_at,
                    trigger=trigger,
                    pipeline_name=pipeline_name,
                )

                if result.get("success") and job_name in self.CORE_READY_DATASETS:
                    await self._refresh_core_ready_marker(
                        trade_date,
                        source=f"{trigger}:{job_name}",
                        pipeline_name=pipeline_name,
                    )

                return {
                    "success": bool(result.get("success")),
                    "job_name": job_name,
                    "trade_date": trade_date,
                    "result": result,
                }
            finally:
                await lock.release()

    # ==================== RPC 方法 ====================

    def _register_rpc_methods(self) -> None:
        """注册 RPC 方法"""
        super()._register_rpc_methods()

        # 注册热点新闻刷新方法
        self.register_rpc_method("refresh_hot_news", self._handle_refresh_hot_news)
        self.logger.info("Registered RPC method: refresh_hot_news")
        self.register_rpc_method("run_sync_job", self._handle_run_sync_job)
        self.logger.info("Registered RPC method: run_sync_job")
        self.register_rpc_method("get_core_readiness", self._handle_get_core_readiness)
        self.logger.info("Registered RPC method: get_core_readiness")
        self.register_rpc_method("get_recent_job_executions", self._handle_get_recent_job_executions)
        self.logger.info("Registered RPC method: get_recent_job_executions")
        self.register_rpc_method("get_recent_failed_job_executions", self._handle_get_recent_failed_job_executions)
        self.logger.info("Registered RPC method: get_recent_failed_job_executions")
        self.register_rpc_method("get_recent_ops_events", self._handle_get_recent_ops_events)
        self.logger.info("Registered RPC method: get_recent_ops_events")
        self.register_rpc_method("get_core_job_runtime_summary", self._handle_get_core_job_runtime_summary)
        self.logger.info("Registered RPC method: get_core_job_runtime_summary")
        self.register_rpc_method("get_core_integrity_overview", self._handle_get_core_integrity_overview)
        self.logger.info("Registered RPC method: get_core_integrity_overview")
        self.register_rpc_method("recover_latest_core_gaps", self._handle_recover_latest_core_gaps)
        self.logger.info("Registered RPC method: recover_latest_core_gaps")
        self.register_rpc_method("recover_recent_core_gaps", self._handle_recover_recent_core_gaps)
        self.logger.info("Registered RPC method: recover_recent_core_gaps")
        self.register_rpc_method("recover_job_trade_date", self._handle_recover_job_trade_date)
        self.logger.info("Registered RPC method: recover_job_trade_date")
        self.register_rpc_method("get_sync_targets_status", self._handle_get_sync_targets_status)
        self.logger.info("Registered RPC method: get_sync_targets_status")
        self.register_rpc_method("get_data_source_call_stats", self._handle_get_data_source_call_stats)
        self.logger.info("Registered RPC method: get_data_source_call_stats")
        self.register_rpc_method("reset_data_source_call_stats", self._handle_reset_data_source_call_stats)
        self.logger.info("Registered RPC method: reset_data_source_call_stats")
        self.register_rpc_method("get_ops_summary", self._handle_get_ops_summary)
        self.logger.info("Registered RPC method: get_ops_summary")
        self.register_rpc_method("get_data_capabilities", self._handle_get_data_capabilities)
        self.logger.info("Registered RPC method: get_data_capabilities")

    async def _handle_refresh_hot_news(self, params: dict) -> dict:
        """
        处理热点新闻刷新 RPC 请求

        Args:
            params: {"source": "cls"} 或 {} 刷新全部

        Returns:
            刷新结果
        """
        source_id = params.get("source")
        trace_id = params.get("_trace_id", "-")

        self.logger.info(f"[{trace_id}] RPC refresh_hot_news: source={source_id or 'ALL'}")

        # 从已注册的任务中获取热点新闻采集器
        hot_news_collector = self._get_job("hot_news")
        if not hot_news_collector:
            return {"success": False, "error": "HotNewsCollector not found"}

        try:
            result = await hot_news_collector.refresh(source_id)
            self.logger.info(f"[{trace_id}] refresh_hot_news done: {result}")
            return result
        except Exception as e:
            self.logger.exception(f"[{trace_id}] refresh_hot_news failed: {e}")
            return {
                "success_count": 0,
                "fail_count": 1,
                "total_news": 0,
                "error": str(e),
            }

    async def _handle_run_sync_job(self, params: dict) -> dict:
        """RPC 手动触发指定同步任务。"""
        job_name = str(params.get("job_name") or "").strip()
        if not job_name:
            return {"success": False, "error": "Missing job_name"}
        return await self.run_job(
            job_name,
            force_backfill_window=bool(params.get("force") or params.get("force_backfill_window")),
        )

    async def _handle_get_core_readiness(self, params: dict) -> dict:
        """RPC 获取最新核心链路就绪状态。"""
        marker = await mongo_manager.find_one(
            "readiness_markers",
            {"marker_type": self.CORE_READY_MARKER},
            sort=[("trade_date", -1)],
        )
        if not marker:
            return {
                "success": True,
                "marker_type": self.CORE_READY_MARKER,
                "status": "missing",
                "marker": None,
            }
        return {
            "success": True,
            "marker_type": self.CORE_READY_MARKER,
            "status": marker.get("status", "unknown"),
            "marker": self._serialize_document(marker),
        }

    async def _handle_get_recent_job_executions(self, params: dict) -> dict:
        """RPC 获取最近任务执行记录。"""
        limit = max(1, min(int(params.get("limit") or 20), 100))
        job_name = str(params.get("job_name") or "").strip()
        query = {"job_name": job_name} if job_name else {}
        records = await mongo_manager.find_many(
            "job_execution_records",
            query,
            sort=[("started_at", -1)],
            limit=limit,
        )
        return {
            "success": True,
            "count": len(records),
            "records": [self._serialize_document(record) for record in records],
        }

    async def _handle_get_recent_failed_job_executions(self, params: dict) -> dict:
        """RPC 获取最近失败任务记录。"""
        limit = max(1, min(int(params.get("limit") or 20), 100))
        lookback_hours = max(1, min(int(params.get("lookback_hours") or 24), 24 * 30))
        core_jobs_only = bool(params.get("core_jobs_only", False))
        return await get_recent_failed_job_executions(
            limit=limit,
            lookback_hours=lookback_hours,
            core_jobs_only=core_jobs_only,
        )

    async def _handle_get_recent_ops_events(self, params: dict) -> dict:
        """RPC 获取最近运维事件。"""
        limit = max(1, min(int(params.get("limit") or 20), 100))
        lookback_hours = max(1, min(int(params.get("lookback_hours") or 24), 24 * 30))
        raw_severities = params.get("severities") or []
        if isinstance(raw_severities, str):
            severities = [part.strip() for part in raw_severities.split(",") if part.strip()]
        else:
            severities = list(raw_severities) if isinstance(raw_severities, list) else []
        return await get_recent_ops_events(
            limit=limit,
            severities=severities,
            lookback_hours=lookback_hours,
        )

    async def _handle_get_core_job_runtime_summary(self, params: dict) -> dict:
        """RPC 获取核心任务近期运行耗时摘要。"""
        lookback_hours = max(1, min(int(params.get("lookback_hours") or 24), 24 * 30))
        return await get_core_job_runtime_summary(
            lookback_hours=lookback_hours,
        )

    async def _handle_get_core_integrity_overview(self, params: dict) -> dict:
        """RPC 获取最近核心链路完整性概览。"""
        days = max(1, min(int(params.get("days") or 3), 10))
        return await build_core_integrity_overview(days=days)

    async def _handle_recover_latest_core_gaps(self, params: dict) -> dict:
        """RPC 检查并重跑最新交易日缺失的核心链路任务。"""
        return await self._recover_latest_core_gaps(trigger="rpc_recovery")

    async def _handle_recover_recent_core_gaps(self, params: dict) -> dict:
        """RPC 检查并尽量补齐最近若干交易日的核心链路缺口。"""
        days = max(1, min(int(params.get("days") or 3), 10))
        return await self._recover_recent_core_gaps(trigger="rpc_recent_recovery", days=days)

    async def _handle_recover_job_trade_date(self, params: dict) -> dict:
        """RPC 直接调用某个任务的 recover_trade_date 能力。"""
        job_name = str(params.get("job_name") or "").strip()
        trade_date = str(params.get("trade_date") or "").strip()
        if not job_name or not trade_date:
            return {"success": False, "error": "Missing job_name or trade_date"}
        return await self._recover_job_trade_date(
            job_name,
            trade_date,
            trigger="rpc_targeted_recovery",
        )

    async def _handle_get_sync_targets_status(self, params: dict) -> dict:
        """RPC 获取主库与镜像库状态。"""
        return {
            "success": True,
            "targets": await mongo_manager.get_target_status(),
        }

    async def _handle_get_data_source_call_stats(self, params: dict) -> dict:
        """RPC 获取当前 DataSync 进程内的数据源调用统计。"""
        return data_source_manager.get_call_stats_summary()

    async def _handle_reset_data_source_call_stats(self, params: dict) -> dict:
        """RPC 重置当前 DataSync 进程内的数据源调用统计窗口。"""
        return data_source_manager.reset_call_stats()

    async def _handle_get_ops_summary(self, params: dict) -> dict:
        """RPC 获取一份运维总览。"""
        integrity_days = max(1, min(int(params.get("days") or 3), 10))
        recent_job_limit = max(1, min(int(params.get("job_limit") or 10), 50))
        failure_lookback_hours = max(1, min(int(params.get("failure_lookback_hours") or 24), 24 * 30))
        event_lookback_hours = max(1, min(int(params.get("event_lookback_hours") or 24), 24 * 30))
        runtime_lookback_hours = max(1, min(int(params.get("runtime_lookback_hours") or 24), 24 * 30))
        return await build_ops_summary(
            integrity_days=integrity_days,
            recent_job_limit=recent_job_limit,
            recent_failure_lookback_hours=failure_lookback_hours,
            recent_event_lookback_hours=event_lookback_hours,
            core_runtime_lookback_hours=runtime_lookback_hours,
        )

    async def _handle_get_data_capabilities(self, params: dict) -> dict:
        """RPC 获取 DataSync 数据能力声明。"""
        return self.get_capability_manifest(
            registered_only=bool(params.get("registered_only", False)),
        )

    async def _recover_latest_core_gaps(self, trigger: str) -> dict:
        """检查并重跑最新交易日缺失的核心链路任务。"""
        overview = await build_core_integrity_overview(days=1)
        if not overview.get("success"):
            return overview

        latest_entry = (overview.get("overview") or [None])[-1]
        if not latest_entry:
            return {"success": False, "error": "No integrity overview available"}
        if latest_entry.get("ready"):
            return {
                "success": True,
                "trade_date": latest_entry.get("trade_date"),
                "recovered": False,
                "message": "Latest core chain already ready",
                "overview": latest_entry,
            }
        if latest_entry.get("awaiting_sync_window"):
            return {
                "success": True,
                "trade_date": latest_entry.get("trade_date"),
                "recovered": False,
                "reason": "awaiting_sync_window",
                "message": "Latest core chain is still before the configured sync window",
                "overview": latest_entry,
            }

        missing_datasets = [
            item["dataset"]
            for item in latest_entry.get("datasets", [])
            if not item.get("ok")
        ]
        first_missing_index = min(
            (self.CORE_READY_DATASETS.index(name) for name in missing_datasets if name in self.CORE_READY_DATASETS),
            default=len(self.CORE_READY_DATASETS),
        )
        rerun_order = self.CORE_READY_DATASETS[first_missing_index:] if missing_datasets else []

        results = []
        failure_point = None
        for job_name in rerun_order:
            job = self._get_job(job_name)
            result = await self._run_job_with_lock(
                job,
                trigger=trigger,
                pipeline_name="core_gap_recovery",
            ) if job else {"success": False, "error": f"Job not found: {job_name}"}
            results.append({"job_name": job_name, "result": result})
            if not result.get("success"):
                failure_point = {
                    "job_name": job_name,
                    "error": result.get("error"),
                    "reason": result.get("reason"),
                    "skipped": bool(result.get("skipped")),
                }
                break

        refreshed = await build_core_integrity_overview(days=1)
        latest_overview = refreshed.get("overview", [latest_entry])[-1] if refreshed.get("overview") else latest_entry
        completed_jobs = [
            item["job_name"]
            for item in results
            if item.get("result", {}).get("success")
        ]
        if results:
            await self._record_ops_event(
                event_type="core_gap_recovery_completed",
                severity="info" if latest_overview.get("ready") else "warning",
                message=(
                    f"Core gap recovery completed for {latest_entry.get('trade_date')}"
                    if latest_overview.get("ready")
                    else f"Core gap recovery finished but latest core chain is still incomplete for {latest_entry.get('trade_date')}"
                ),
                source=trigger,
                details={
                    "trade_date": latest_entry.get("trade_date"),
                    "missing_datasets": missing_datasets,
                    "rerun_order": rerun_order,
                    "completed_jobs": completed_jobs,
                    "failure_point": failure_point,
                    "latest_ready": latest_overview.get("ready"),
                },
            )
        return {
            "success": True,
            "trade_date": latest_entry.get("trade_date"),
            "recovered": bool(results),
            "missing_datasets": missing_datasets,
            "rerun_order": rerun_order,
            "results": results,
            "completed_jobs": completed_jobs,
            "failure_point": failure_point,
            "overview": latest_overview,
        }

    async def _recover_recent_core_gaps(self, trigger: str, days: int) -> dict:
        """尽量补齐最近若干交易日中可定向恢复的核心缺口。"""
        window_days = max(1, min(int(days or 3), 10))
        overview = await build_core_integrity_overview(days=window_days)
        if not overview.get("success"):
            return overview

        entries = list(overview.get("overview") or [])
        if not entries:
            return {"success": False, "error": "No integrity overview available", "days": window_days}

        latest_trade_date = overview.get("latest_trade_date")
        results = []
        unsupported = []
        recovered_trade_dates = []
        skipped_trade_dates = []
        failed_trade_dates = []

        for entry in reversed(entries):
            trade_date = entry.get("trade_date")
            if not trade_date or entry.get("ready"):
                continue
            if entry.get("awaiting_sync_window"):
                skipped_trade_dates.append({
                    "trade_date": trade_date,
                    "reason": "awaiting_sync_window",
                })
                results.append({
                    "trade_date": trade_date,
                    "mode": "skipped",
                    "reason": "awaiting_sync_window",
                    "message": "Trade date is still before the configured core sync window",
                })
                continue

            if trade_date == latest_trade_date:
                latest_result = await self._recover_latest_core_gaps(trigger=trigger)
                if latest_result.get("recovered"):
                    recovered_trade_dates.append(trade_date)
                if latest_result.get("reason") == "awaiting_sync_window":
                    skipped_trade_dates.append({"trade_date": trade_date, "reason": "awaiting_sync_window"})
                if latest_result.get("failure_point"):
                    failed_trade_dates.append({
                        "trade_date": trade_date,
                        "failure_point": latest_result.get("failure_point"),
                    })
                results.append({
                    "trade_date": trade_date,
                    "mode": "latest_pipeline",
                    "result": latest_result,
                })
                continue

            missing_datasets = [
                item["dataset"]
                for item in entry.get("datasets", [])
                if not item.get("ok")
            ]
            recovery_order = [
                dataset
                for dataset in self.CORE_READY_DATASETS
                if dataset in missing_datasets
            ]
            trade_date_results = []
            failure_point = None

            for dataset in recovery_order:
                if dataset not in self.RECENT_RECOVERABLE_DATASETS:
                    unsupported.append({"trade_date": trade_date, "dataset": dataset})
                    failure_point = {
                        "dataset": dataset,
                        "reason": "unsupported",
                        "message": f"{dataset} does not support historical targeted recovery yet",
                    }
                    trade_date_results.append({
                        "dataset": dataset,
                        "success": False,
                        "unsupported": True,
                        "message": f"{dataset} does not support historical targeted recovery yet",
                    })
                    break

                job = self._get_job(dataset)
                recover_fn = getattr(job, "recover_trade_date", None) if job else None
                if job is None or not callable(recover_fn):
                    unsupported.append({"trade_date": trade_date, "dataset": dataset})
                    failure_point = {
                        "dataset": dataset,
                        "reason": "recover_trade_date_missing",
                        "message": f"{dataset} lacks recover_trade_date handler",
                    }
                    trade_date_results.append({
                        "dataset": dataset,
                        "success": False,
                        "unsupported": True,
                        "message": f"{dataset} lacks recover_trade_date handler",
                    })
                    break

                recovery_result = await self._recover_job_trade_date(
                    dataset,
                    trade_date,
                    trigger=trigger,
                    pipeline_name="recent_core_gap_recovery",
                )
                trade_date_results.append({
                    "dataset": dataset,
                    "success": bool(recovery_result.get("success")),
                    "result": recovery_result.get("result", {}),
                })
                if not recovery_result.get("success"):
                    failure_point = {
                        "dataset": dataset,
                        "reason": recovery_result.get("result", {}).get("reason"),
                        "error": recovery_result.get("result", {}).get("error") or recovery_result.get("error"),
                    }
                    break

            if failure_point:
                failed_trade_dates.append({
                    "trade_date": trade_date,
                    "failure_point": failure_point,
                })
            elif trade_date_results:
                recovered_trade_dates.append(trade_date)

            results.append({
                "trade_date": trade_date,
                "mode": "targeted_recovery",
                "missing_datasets": missing_datasets,
                "recovery_order": recovery_order,
                "results": trade_date_results,
                "failure_point": failure_point,
            })

        refreshed = await build_core_integrity_overview(days=window_days)
        has_failures = bool(unsupported or failed_trade_dates)
        await self._record_ops_event(
            event_type="recent_core_gap_recovery_completed",
            severity="warning" if has_failures else "info",
            message=(
                f"Recent core gap recovery scanned {window_days} trade days"
                if not has_failures
                else f"Recent core gap recovery scanned {window_days} trade days with unresolved historical gaps"
            ),
            source=trigger,
            details={
                "days": window_days,
                "unsupported": unsupported,
                "result_count": len(results),
                "recovered_trade_dates": recovered_trade_dates,
                "skipped_trade_dates": skipped_trade_dates,
                "failed_trade_dates": failed_trade_dates,
            },
        )
        return {
            "success": True,
            "days": window_days,
            "latest_trade_date": latest_trade_date,
            "recovered": bool(results),
            "results": results,
            "unsupported": unsupported,
            "recovered_trade_dates": recovered_trade_dates,
            "skipped_trade_dates": skipped_trade_dates,
            "failed_trade_dates": failed_trade_dates,
            "overview": refreshed,
        }

    def _serialize_document(self, value):
        """将 Mongo 文档中的时间字段转成 JSON 友好的字符串。"""
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, list):
            return [self._serialize_document(item) for item in value]
        if isinstance(value, dict):
            return {
                str(key): self._serialize_document(item)
                for key, item in value.items()
                if key != "_id"
            }
        return value

    def _get_job(self, name: str) -> Optional[ScheduledJob]:
        """根据名称获取任务"""
        for job in self._jobs:
            if job.name == name:
                return job
        return None


def main():
    """入口函数"""
    node = DataSyncNode()
    asyncio.run(node.main())


if __name__ == "__main__":
    main()
