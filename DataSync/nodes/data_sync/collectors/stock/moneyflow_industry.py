"""
行业资金流向采集器

使用日期同步策略，支持并行采集和失败重试。
数据来源: 同花顺行业资金流向 (moneyflow_ind_ths)
"""

from typing import Dict, Any, List
import asyncio

from core.base import BaseCollector
from core.settings import settings
from core.managers.data_source_manager import data_source_manager
from core.managers.mongo_manager import mongo_manager
from nodes.data_sync.services.recovery_contract import (
    build_recovery_warnings,
    extract_sources_from_parallel_result,
    primary_source,
    skipped_recovery_result,
    validate_recovery_trade_date,
)


class MoneyflowIndustryCollector(BaseCollector):
    """
    行业资金流向采集器

    采集同花顺行业资金流向数据。支持并行采集和失败自动重试。

    调度时间:
    - 可通过 SYNC_MONEYFLOW_INDUSTRY_SCHEDULE 环境变量配置
    - 默认: 每个交易日 16:00 (收盘后)
    """

    name = "moneyflow_industry"
    description = "采集行业资金流向数据"
    default_schedule = "0 16 * * 1-5"
    dataset_name = "moneyflow_industry"
    resource_class = "core"
    target_collections = ("moneyflow_industry",)
    dependencies = ("trade_calendar",)
    source_chain_keys = ("get_latest_trade_date", "get_moneyflow_industry")
    supports_backfill = True
    quality_checks = (
        "required_fields:ts_code,trade_date",
        "dedupe_key:ts_code,trade_date",
    )

    INITIAL_SYNC_DAYS = 30
    WRITE_BATCH_SIZE = 1000
    MAX_CONCURRENT = 5
    API_INTERVAL = 0.2

    @property
    def schedule(self) -> str:
        return settings.data_sync.moneyflow_industry_schedule or self.default_schedule

    async def collect(self) -> Dict[str, Any]:
        """执行采集"""
        latest_trade_date, _ = await data_source_manager.get_latest_trade_date()

        already_synced = await mongo_manager.is_synced(self.name, latest_trade_date)
        coverage_ok = await self._has_trade_date_coverage(latest_trade_date)

        if already_synced and coverage_ok:
            self.logger.info(f"Moneyflow industry {latest_trade_date} already synced, skipping")
            return {"count": 0, "message": f"Already synced {latest_trade_date}", "skipped": True}

        if already_synced and not coverage_ok:
            self.logger.warning(
                f"Sync marker {self.name} already points to {latest_trade_date}, "
                "but moneyflow_industry coverage is incomplete; forcing latest-date resync"
            )
            sync_info = (latest_trade_date, latest_trade_date)
        else:
            sync_info = await self._determine_sync_range_simple(latest_trade_date)

        if sync_info is None:
            return {"count": 0, "message": f"Already synced {latest_trade_date}", "skipped": True}

        start_date, end_date = sync_info
        trade_dates = await self._get_trade_dates(start_date, end_date)

        if not trade_dates:
            return {"count": 0, "message": "No trade dates in range"}

        self.logger.info(f"Syncing moneyflow industry: {start_date} -> {end_date} ({len(trade_dates)} dates)")

        total_count = 0

        async def collect_single_date(trade_date: str) -> int:
            nonlocal total_count
            records, _ = await data_source_manager.get_moneyflow_industry(trade_date=trade_date)
            if records:
                count = await self._write_buffer(
                    buffer=records,
                    collection="moneyflow_industry",
                    key_fields=["ts_code", "trade_date"],
                )
                total_count += count
                await asyncio.sleep(self.API_INTERVAL)
                return count
            await asyncio.sleep(self.API_INTERVAL)
            return 0

        result = await self._parallel_collect(
            items=trade_dates,
            collect_func=collect_single_date,
            max_concurrent=self.MAX_CONCURRENT,
            retry_failures=True,
        )

        await mongo_manager.record_sync(
            sync_type=self.name,
            sync_date=end_date,
            count=total_count,
        )

        return {
            "count": total_count,
            "start_date": start_date,
            "end_date": end_date,
            "success_dates": result["success"],
            "failed_dates": result["failed"],
            "message": f"Synced {total_count} records ({result['success']}/{result['total']} dates)",
        }

    async def recover_trade_date(self, trade_date: str) -> Dict[str, Any]:
        """定向补指定交易日的行业资金流。"""
        guard = await validate_recovery_trade_date(trade_date)
        if not guard["ok"]:
            return skipped_recovery_result(self.name, guard)

        trade_date = guard["trade_date"]
        total_count, result = await self._collect_trade_dates([trade_date])
        sources = extract_sources_from_parallel_result(result, default=guard.get("source") or "unknown")
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
            "success_dates": result["success"],
            "failed_dates": result["failed"],
            "failed_items": result.get("failed_items", []),
            "message": f"Recovered moneyflow_industry for {trade_date}",
        }

    async def _collect_trade_dates(self, trade_dates: List[str]) -> tuple[int, Dict[str, Any]]:
        total_count = 0

        async def collect_single_date(trade_date: str) -> Dict[str, Any]:
            nonlocal total_count
            records, source = await data_source_manager.get_moneyflow_industry(trade_date=trade_date)
            if records:
                count = await self._write_buffer(
                    buffer=records,
                    collection="moneyflow_industry",
                    key_fields=["ts_code", "trade_date"],
                )
                total_count += count
                await asyncio.sleep(self.API_INTERVAL)
                return {"count": count, "source": source, "record_count": len(records)}
            await asyncio.sleep(self.API_INTERVAL)
            return {"count": 0, "source": source, "record_count": 0}

        result = await self._parallel_collect(
            items=trade_dates,
            collect_func=collect_single_date,
            max_concurrent=self.MAX_CONCURRENT,
            retry_failures=True,
        )
        return total_count, result

    async def _has_trade_date_coverage(self, trade_date: str) -> bool:
        rows = await mongo_manager.find_many(
            "moneyflow_industry",
            {"trade_date": trade_date},
            projection={"ts_code": 1},
            limit=1,
        )
        return bool(rows)
