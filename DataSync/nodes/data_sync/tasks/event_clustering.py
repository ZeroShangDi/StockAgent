"""独立 DataSync 的事件聚类占位任务。"""

from __future__ import annotations

from typing import Any, Dict

from core.base import BaseTask
from core.settings import settings


class EventClusteringTask(BaseTask):
    name = "event_clustering"
    description = "新闻事件聚类（待独立迁入）"
    default_schedule = "*/30 * * * *"
    run_at_startup = False

    @property
    def schedule(self) -> str:
        return getattr(settings.data_sync, "event_clustering_schedule", None) or self.default_schedule

    async def execute(self) -> Dict[str, Any]:
        return {
            "count": 0,
            "skipped": True,
            "message": "event_clustering is not yet extracted into standalone DataSync",
        }
