"""
市场晴雨表 API。
"""

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query

from src.analysis.market_weather import market_weather_service
from .auth import CurrentUser, get_current_user


router = APIRouter(prefix="/market/weather", tags=["Market Weather"])


@router.get("/latest")
async def get_market_weather_latest() -> Dict[str, Any]:
    """获取最新市场晴雨表记录。若本地没有，则自动拉取一次最新数据。"""
    return await market_weather_service.ensure_latest()


@router.get("/history")
async def get_market_weather_history(
    days: int = Query(default=30, ge=5, le=90, description="最近 N 个交易日"),
) -> Dict[str, List[Dict[str, Any]]]:
    history = await market_weather_service.list_history(days)
    return {"history": history}


@router.post("/sync")
async def sync_market_weather(
    days: int = Query(default=30, ge=1, le=90, description="补最近 N 个交易日"),
    overwrite: bool = Query(default=False, description="是否覆盖已存在记录"),
    current_user: CurrentUser = Depends(get_current_user),
) -> Dict[str, Any]:
    _ = current_user
    return await market_weather_service.sync_recent(days=days, overwrite=overwrite)
