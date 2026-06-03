"""
市场统计预聚合缓存任务

将市场分析页中的重查询统计结果提前计算并写入 Redis/Mongo 缓存，
避免请求时反复扫描多张大表。
"""

from __future__ import annotations

from typing import Dict, Any

from core.base import BaseTask
from core.settings import settings
from core.managers.data_source_manager import data_source_manager
from core.managers.mongo_manager import mongo_manager
from nodes.data_sync.services.recovery_contract import (
    build_recovery_warnings,
    skipped_recovery_result,
    validate_recovery_trade_date,
)
from nodes.data_sync.services.market_statistics import (
    _build_statistics_leader_cycle_payload,
    _build_statistics_limit_snapshot_payload,
    _build_statistics_sentiment_payload,
)
from src.analysis.market_statistics_cache import set_cached_market_statistics


class MarketStatisticsCacheTask(BaseTask):
    name = "market_statistics_cache"
    description = "预聚合市场统计缓存"
    default_schedule = "35 16 * * 1-5"
    dataset_name = "market_statistics_cache"
    resource_class = "core"
    target_collections = ("market_statistics_cache",)
    dependencies = ("daily_stats", "limit_list", "stock_daily")
    source_chain_keys = ("get_latest_trade_date",)
    quality_checks = (
        "expected_cache_entries:9",
        "derived_dataset",
    )
    PERIODS = ("1w", "1m", "3m", "1y")
    run_at_startup = False

    @property
    def schedule(self) -> str:
        return getattr(settings.data_sync, "market_statistics_cache_schedule", None) or self.default_schedule

    async def execute(self) -> Dict[str, Any]:
        latest_trade_date, _ = await data_source_manager.get_latest_trade_date()
        if not latest_trade_date:
            return {"count": 0, "skipped": True, "message": "No latest trade date"}

        already_synced = await mongo_manager.is_synced(self.name, latest_trade_date)
        coverage_ok = await self._has_trade_date_coverage(latest_trade_date)
        if already_synced and coverage_ok:
            return {"count": 0, "trade_date": latest_trade_date, "skipped": True, "message": f"Already cached {latest_trade_date}"}

        built = await self._build_for_trade_date(latest_trade_date)

        await mongo_manager.record_sync(
            sync_type=self.name,
            sync_date=latest_trade_date,
            count=built,
        )

        return {
            "count": built,
            "trade_date": latest_trade_date,
            "message": f"Precomputed market statistics cache for {latest_trade_date}",
        }

    async def recover_trade_date(self, trade_date: str) -> Dict[str, Any]:
        """定向补指定交易日的市场统计缓存，不回退 sync marker。"""
        guard = await validate_recovery_trade_date(trade_date)
        if not guard["ok"]:
            return skipped_recovery_result(self.name, guard)

        trade_date = guard["trade_date"]
        built = await self._build_for_trade_date(trade_date)
        return {
            "success": True,
            "count": built,
            "trade_date": trade_date,
            "source": "local_cache_build",
            "sources": ["local_cache_build"],
            "warnings": build_recovery_warnings(guard),
            "message": f"Recovered market statistics cache for {trade_date}",
        }

    async def _build_for_trade_date(self, trade_date: str) -> int:
        built = 0

        limit_snapshot_payload = await _build_statistics_limit_snapshot_payload(trade_date)
        await set_cached_market_statistics(
            "limit_snapshot",
            trade_date,
            limit_snapshot_payload,
            trade_date=trade_date,
        )
        built += 1

        for period in self.PERIODS:
            leader_cycle_payload = await _build_statistics_leader_cycle_payload(period, latest_trade_date=trade_date)
            await set_cached_market_statistics(
                "leader_cycle",
                f"{period}:{trade_date}",
                leader_cycle_payload,
                trade_date=trade_date,
            )
            built += 1

            sentiment_payload = await _build_statistics_sentiment_payload(period, latest_trade_date=trade_date)
            await set_cached_market_statistics(
                "sentiment",
                f"{period}:{trade_date}",
                sentiment_payload,
                trade_date=trade_date,
            )
            built += 1

        return built

    async def _has_trade_date_coverage(self, trade_date: str) -> bool:
        count = await mongo_manager.count("market_statistics_cache", {"trade_date": trade_date})
        return count >= 9
