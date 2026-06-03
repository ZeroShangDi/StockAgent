"""独立 DataSync 的多源新闻采集占位实现。

当前 standalone DataSync 先保证已启用作业完全自包含。
多源新闻聚合依赖旧版新闻采集框架，后续再按独立模块方式迁入。
"""

from __future__ import annotations

from typing import Any, Dict

from core.base import BaseCollector


class MultiSourceCollector(BaseCollector):
    """占位版多源新闻采集器。"""

    name = "multi_source_news"
    description = "多源新闻聚合采集（待独立迁入）"
    default_schedule = "*/5 * * * *"
    run_at_startup = False

    async def collect(self) -> Dict[str, Any]:
        return {
            "count": 0,
            "skipped": True,
            "message": "multi_source_news is not yet extracted into standalone DataSync",
        }


multi_source_collector = MultiSourceCollector()
