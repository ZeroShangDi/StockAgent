"""
市场统计预聚合缓存任务

将市场分析页中的重查询统计结果提前计算并写入 Redis/Mongo 缓存，
避免请求时反复扫描多张大表。
"""

from __future__ import annotations

from typing import Dict, Any

from core.base import BaseTask
from core.settings import settings
from core.managers import data_source_manager
from nodes.web.api.market import (
    _build_statistics_leader_cycle_payload,
    _build_statistics_limit_snapshot_payload,
    _build_statistics_sentiment_payload,
)
from src.analysis.market_statistics_cache import set_cached_market_statistics


class MarketStatisticsCacheTask(BaseTask):
    name = "market_statistics_cache"
    description = "预聚合市场统计缓存"
    default_schedule = "20 18 * * 1-5"
    PERIODS = ("1w", "1m", "3m", "1y")
    run_at_startup = False

    @property
    def schedule(self) -> str:
        return getattr(settings.data_sync, "market_statistics_cache_schedule", None) or self.default_schedule

    def _configured_periods(self) -> tuple[str, ...]:
        configured = getattr(settings.data_sync, "market_statistics_cache_periods", "1w,1m,3m")
        periods = [
            item.strip()
            for item in str(configured or "").split(",")
            if item.strip() in self.PERIODS
        ]
        return tuple(dict.fromkeys(periods)) or ("1w", "1m", "3m")

    async def execute(self) -> Dict[str, Any]:
        latest_trade_date, _ = await data_source_manager.get_latest_trade_date()
        if not latest_trade_date:
            return {"count": 0, "skipped": True, "message": "No latest trade date"}

        built = 0

        limit_snapshot_payload = await _build_statistics_limit_snapshot_payload(latest_trade_date)
        await set_cached_market_statistics(
            "limit_snapshot",
            latest_trade_date,
            limit_snapshot_payload,
            trade_date=latest_trade_date,
        )
        built += 1

        periods = self._configured_periods()
        for period in periods:
            leader_cycle_payload = await _build_statistics_leader_cycle_payload(period)
            await set_cached_market_statistics(
                "leader_cycle",
                f"{period}:{latest_trade_date}",
                leader_cycle_payload,
                trade_date=latest_trade_date,
            )
            built += 1

            sentiment_payload = await _build_statistics_sentiment_payload(period)
            await set_cached_market_statistics(
                "sentiment",
                f"{period}:{latest_trade_date}",
                sentiment_payload,
                trade_date=latest_trade_date,
            )
            built += 1

        return {
            "count": built,
            "trade_date": latest_trade_date,
            "periods": list(periods),
            "message": f"Precomputed market statistics cache for {latest_trade_date}",
        }
