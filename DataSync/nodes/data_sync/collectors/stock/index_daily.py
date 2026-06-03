"""
指数日线数据采集器

只同步三个核心指数：
- 000001.SH 上证指数
- 399001.SZ 深证成指
- 399006.SZ 创业板指

支持增量同步和失败重试。
"""

from typing import Dict, Any, List
import time

from core.base import BaseCollector
from core.settings import settings
from core.managers.data_source_manager import data_source_manager
from core.managers.mongo_manager import mongo_manager
from nodes.data_sync.services.recovery_contract import (
    build_recovery_warnings,
    compact_sources,
    primary_source,
    skipped_recovery_result,
    validate_recovery_trade_date,
)


class IndexDailyCollector(BaseCollector):
    """
    指数日线数据采集器

    采集核心指数的日线行情数据。支持失败自动重试。

    调度时间:
    - 可通过 SYNC_INDEX_DAILY_SCHEDULE 环境变量配置
    - 默认: 每个交易日 15:35 (收盘后)
    """

    name = "index_daily"
    description = "采集指数日线数据"
    default_schedule = "35 15 * * 1-5"
    dataset_name = "index_daily"
    resource_class = "core"
    target_collections = ("index_daily",)
    dependencies = ("index_basic", "trade_calendar")
    source_chain_keys = ("get_latest_trade_date", "get_index_daily")
    supports_backfill = True
    quality_checks = ("required_fields:ts_code,trade_date,open,high,low,close", "dedupe_key:ts_code,trade_date")

    # 配置（覆盖基类默认值）
    HISTORY_START_DATE = "20030127"
    HISTORY_SYNC_DAYS_THRESHOLD = 30
    WRITE_BATCH_SIZE = 1000
    # 只有 3 个核心指数，串行抓取更稳，能降低源端抖动和锁竞争带来的长尾风险。
    MAX_CONCURRENT = 1

    # 核心指数列表
    CORE_INDICES = [
        "000001.SH",  # 上证指数
        "399001.SZ",  # 深证成指
        "399006.SZ",  # 创业板指
    ]

    @property
    def schedule(self) -> str:
        return settings.data_sync.index_daily_schedule or self.default_schedule

    @staticmethod
    def _summarize_index_results(result: Dict[str, Any]) -> List[Dict[str, Any]]:
        summaries: List[Dict[str, Any]] = []
        for item in result.get("results", []):
            if not item.get("success"):
                continue
            payload = item.get("result") or {}
            summaries.append(
                {
                    "ts_code": item.get("item_id"),
                    "source": payload.get("source"),
                    "record_count": payload.get("record_count"),
                    "write_count": payload.get("write_count"),
                    "duration_ms": payload.get("duration_ms"),
                }
            )
        return summaries

    async def collect(self) -> Dict[str, Any]:
        """执行采集"""
        latest_trade_date, _ = await data_source_manager.get_latest_trade_date()

        already_synced = await mongo_manager.is_synced(self.name, latest_trade_date)
        coverage_ok = await self._has_trade_date_coverage(latest_trade_date)

        if already_synced and coverage_ok:
            self.logger.info(f"Index daily {latest_trade_date} already synced, skipping")
            return {"count": 0, "message": f"Already synced {latest_trade_date}", "skipped": True}

        if already_synced and not coverage_ok:
            self.logger.warning(
                f"Sync marker {self.name} already points to {latest_trade_date}, "
                "but index_daily coverage is incomplete; forcing latest-date resync"
            )
            sync_info = (latest_trade_date, latest_trade_date, False)
        else:
            # 使用基类方法确定同步范围
            sync_info = await self._determine_sync_range(latest_trade_date)

        if sync_info is None:
            return {"count": 0, "message": f"Already synced {latest_trade_date}", "skipped": True}

        start_date, end_date, is_history_sync = sync_info
        sync_type_desc = "历史同步" if is_history_sync else "增量同步"

        self.logger.info(
            f"[{sync_type_desc}] Syncing index daily: {start_date} -> {end_date} "
            f"({len(self.CORE_INDICES)} indices)"
        )

        total_count = 0

        async def collect_single_index(ts_code: str) -> Dict[str, Any]:
            """采集单个指数的数据并立即写入"""
            nonlocal total_count
            started_at = time.perf_counter()
            records, source = await data_source_manager.get_index_daily(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
            )
            duration_ms = round((time.perf_counter() - started_at) * 1000, 3)
            if records:
                count = await self._write_buffer(
                    buffer=records,
                    collection="index_daily",
                    key_fields=["ts_code", "trade_date"],
                )
                total_count += count
                return {
                    "source": source,
                    "record_count": len(records),
                    "write_count": count,
                    "duration_ms": duration_ms,
                }
            return {
                "source": source,
                "record_count": 0,
                "write_count": 0,
                "duration_ms": duration_ms,
            }

        # 使用基类并行采集方法，每个指数采集后立即写入
        result = await self._parallel_collect(
            items=self.CORE_INDICES,
            collect_func=collect_single_index,
            max_concurrent=self.MAX_CONCURRENT,
            retry_failures=True,
        )

        if await self._has_trade_date_coverage(end_date):
            await mongo_manager.record_sync(
                sync_type=self.name,
                sync_date=end_date,
                count=total_count,
            )
        else:
            self.logger.warning(
                f"Skip recording sync marker for {self.name}: index_daily still lacks {end_date} coverage"
            )

        return {
            "count": total_count,
            "start_date": start_date,
            "end_date": end_date,
            "sync_type": sync_type_desc,
            "success": result["success"],
            "failed": result["failed"],
            "index_results": self._summarize_index_results(result),
            "failed_items": result.get("failed_items", []),
            "message": f"[{sync_type_desc}] Synced {total_count} records ({result['success']}/{result['total']} indices)",
        }

    async def _has_trade_date_coverage(self, trade_date: str) -> bool:
        rows = await mongo_manager.find_many(
            "index_daily",
            {"trade_date": trade_date, "ts_code": {"$in": self.CORE_INDICES}},
            projection={"ts_code": 1},
        )
        covered = {row.get("ts_code") for row in rows if row.get("ts_code")}
        return all(code in covered for code in self.CORE_INDICES)

    async def recover_trade_date(self, trade_date: str) -> Dict[str, Any]:
        """定向补指定交易日的指数日线数据，不回退 sync marker。"""
        guard = await validate_recovery_trade_date(trade_date)
        if not guard["ok"]:
            return skipped_recovery_result(self.name, guard)

        trade_date = guard["trade_date"]
        total_count = 0

        async def collect_single_index(ts_code: str) -> Dict[str, Any]:
            nonlocal total_count
            started_at = time.perf_counter()
            records, source = await data_source_manager.get_index_daily(
                ts_code=ts_code,
                start_date=trade_date,
                end_date=trade_date,
            )
            duration_ms = round((time.perf_counter() - started_at) * 1000, 3)
            if records:
                count = await self._write_buffer(
                    buffer=records,
                    collection="index_daily",
                    key_fields=["ts_code", "trade_date"],
                )
                total_count += count
                return {
                    "source": source,
                    "record_count": len(records),
                    "write_count": count,
                    "duration_ms": duration_ms,
                }
            return {
                "source": source,
                "record_count": 0,
                "write_count": 0,
                "duration_ms": duration_ms,
            }

        result = await self._parallel_collect(
            items=self.CORE_INDICES,
            collect_func=collect_single_index,
            max_concurrent=self.MAX_CONCURRENT,
            retry_failures=True,
        )
        index_results = self._summarize_index_results(result)
        sources = compact_sources(
            [guard.get("source"), [item.get("source") for item in index_results]],
            default="unknown",
        )
        return {
            "success": result["failed"] == 0,
            "count": total_count,
            "trade_date": trade_date,
            "source": primary_source(sources),
            "sources": sources,
            "warnings": build_recovery_warnings(
                guard,
                failed_count=result.get("failed", 0),
                failed_items=result.get("failed_items", []),
            ),
            "success_items": result["success"],
            "failed": result["failed"],
            "index_results": index_results,
            "failed_items": result.get("failed_items", []),
            "message": f"Recovered index_daily for {trade_date}",
        }
