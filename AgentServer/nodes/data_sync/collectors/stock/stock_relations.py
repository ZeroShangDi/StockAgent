"""
股票关联关系采集器

基于本地已同步的数据构建股票与行业、板块、概念、涨停来源行业之间的
关联边，作为后续题材分析和复盘增强的统一关系层。
"""

from typing import Dict, Any

from core.base import BaseCollector
from core.settings import settings
from core.managers import stock_relation_manager


class StockRelationsCollector(BaseCollector):
    """股票关联关系采集器。"""

    name = "stock_relations"
    description = "构建股票与行业/板块/概念/涨停来源之间的关联关系"
    default_schedule = "20 16 * * 1-5"

    @property
    def schedule(self) -> str:
        return getattr(settings.data_sync, "stock_relations_schedule", None) or self.default_schedule

    async def collect(self) -> Dict[str, Any]:
        if not stock_relation_manager.is_initialized:
            await stock_relation_manager.initialize()

        result = await stock_relation_manager.sync_relations()
        total_count = int(result.get("static_docs", 0) or 0) + int(result.get("dynamic_docs", 0) or 0)

        return {
            "count": total_count,
            "trade_date": result.get("trade_date"),
            "stats": result,
            "message": f"Synced {total_count} stock relation edges",
        }
