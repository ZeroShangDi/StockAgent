"""
市场晴雨表同步任务。

只同步最近交易日，避免在 DataSync 常驻进程中触发历史批量回补。
"""

from typing import Dict, Any

from core.base import BaseTask
from core.settings import settings
from core.managers import data_source_manager, mongo_manager
from src.analysis.market_weather import market_weather_service


class MarketWeatherTask(BaseTask):
    name = "market_weather"
    description = "同步最新市场晴雨表"
    default_schedule = "40 18 * * 1-5"
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
            return {"count": 0, "skipped": True, "message": f"Market weather {latest_trade_date} already synced"}

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
