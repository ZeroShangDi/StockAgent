"""独立 DataSync 的午报生成占位任务。"""

from __future__ import annotations

from typing import Any, Dict

from core.base import BaseGenerator


class NoonReportGenerator(BaseGenerator):
    name = "noon_report"
    description = "生成午报（待独立迁入）"
    default_schedule = "50 13 * * 1-5"
    run_at_startup = False

    async def generate(self) -> Dict[str, Any]:
        return {
            "count": 0,
            "skipped": True,
            "message": "noon_report is not yet extracted into standalone DataSync",
        }
