"""独立 DataSync 的新闻生命周期占位任务。"""

from __future__ import annotations

from typing import Any, Dict

from core.base import BaseTask
from core.settings import settings


class NewsLifecycleTask(BaseTask):
    name = "news_lifecycle"
    description = "新闻生命周期管理（待独立迁入）"
    default_schedule = "0 3 * * *"
    run_at_startup = False

    @property
    def schedule(self) -> str:
        return getattr(settings.data_sync, "news_lifecycle_schedule", None) or self.default_schedule

    async def execute(self) -> Dict[str, Any]:
        return {
            "count": 0,
            "skipped": True,
            "message": "news_lifecycle is not yet extracted into standalone DataSync",
        }
