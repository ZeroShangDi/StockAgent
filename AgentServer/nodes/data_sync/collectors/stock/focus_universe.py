"""
重点股票同步范围辅助工具。

用于在 Coze 单股能力为主时，从本地业务数据中提取最值得优先落库的股票集合。
"""

from typing import List

from core.managers import mongo_manager
from core.settings import settings


async def get_focus_stock_codes(max_count: int | None = None) -> List[str]:
    """
    获取重点股票列表。

    来源：
    - users.watchlist
    - strategy_subscriptions.watch_list（仅激活策略）
    """
    limit = max_count or settings.data_sync.focus_stocks_max_count
    seen = set()
    codes: List[str] = []

    users = await mongo_manager.find_many(
        "users",
        {},
        projection={"watchlist": 1},
        limit=5000,
    )
    for user in users:
        for ts_code in user.get("watchlist", []) or []:
            normalized = str(ts_code).upper()
            if normalized and normalized not in seen:
                seen.add(normalized)
                codes.append(normalized)
                if len(codes) >= limit:
                    return codes

    subscriptions = await mongo_manager.find_many(
        "strategy_subscriptions",
        {"is_active": True},
        projection={"watch_list": 1},
        limit=2000,
    )
    for subscription in subscriptions:
        for ts_code in subscription.get("watch_list", []) or []:
            normalized = str(ts_code).upper()
            if normalized and normalized not in seen:
                seen.add(normalized)
                codes.append(normalized)
                if len(codes) >= limit:
                    return codes

    return codes
