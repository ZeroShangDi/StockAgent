"""
市场晴雨表同步任务。

只同步最近交易日，避免在 DataSync 常驻进程中触发历史批量回补。
"""

from __future__ import annotations

from typing import Any, Dict

from core.base import BaseTask
from core.managers.data_source_manager import data_source_manager
from core.managers.mongo_manager import mongo_manager
from core.settings import settings
from nodes.data_sync.services.recovery_contract import (
    build_recovery_warnings,
    skipped_recovery_result,
    validate_recovery_trade_date,
)
from src.analysis.market_weather import market_weather_service


class MarketWeatherTask(BaseTask):
    name = "market_weather"
    description = "同步最新市场晴雨表"
    default_schedule = "50 18 * * 1-5"
    dataset_name = "market_weather"
    resource_class = "core"
    target_collections = ("market_weather_daily",)
    dependencies = ("coze_market_indicator_workflow",)
    source_chain_keys = ("get_latest_trade_date", "coze_market_indicator_workflow")
    quality_checks = (
        "required_fields:trade_date,indicator,signal",
        "dedupe_key:trade_date",
    )
    run_at_startup = False

    @property
    def schedule(self) -> str:
        return getattr(settings.data_sync, "market_weather_schedule", None) or self.default_schedule

    async def execute(self) -> Dict[str, Any]:
        latest_trade_date, _ = await data_source_manager.get_latest_trade_date()
        if not latest_trade_date:
            return {"count": 0, "skipped": True, "message": "No latest trade date"}

        existing = await mongo_manager.find_one(
            market_weather_service.COLLECTION,
            {"trade_date": latest_trade_date},
            projection={"trade_date": 1},
        )
        if existing:
            return {
                "count": 0,
                "trade_date": latest_trade_date,
                "skipped": True,
                "message": f"Market weather {latest_trade_date} already synced",
            }

        result = await market_weather_service.sync_trade_dates([latest_trade_date], overwrite=False)
        if result.get("success", 0) > 0:
            await mongo_manager.record_sync(
                sync_type=self.name,
                sync_date=latest_trade_date,
                count=result["success"],
            )

        return {
            "count": result.get("success", 0),
            "trade_date": latest_trade_date,
            "result": result,
            "message": f"Synced market weather for {latest_trade_date}",
        }

    async def recover_trade_date(self, trade_date: str) -> Dict[str, Any]:
        """定向补指定交易日的市场晴雨表。"""
        guard = await validate_recovery_trade_date(trade_date)
        if not guard["ok"]:
            return skipped_recovery_result(self.name, guard)

        trade_date = guard["trade_date"]
        result = await market_weather_service.sync_trade_dates([trade_date], overwrite=True)
        success_count = int(result.get("success", 0) or 0)
        failed_count = int(result.get("failed", 0) or 0)
        return {
            "success": success_count > 0 and failed_count == 0,
            "count": success_count,
            "trade_date": trade_date,
            "source": "coze_market_indicator",
            "sources": ["coze_market_indicator"],
            "warnings": build_recovery_warnings(
                guard,
                failed_count=failed_count,
                failed_items=result.get("errors") or [],
            ),
            "failed_items": result.get("errors") or [],
            "result": result,
            "message": f"Recovered market_weather for {trade_date}",
        }
