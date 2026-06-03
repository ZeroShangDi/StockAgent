"""历史补缺任务队列服务。

队列只负责可靠地小批量领取和更新状态；具体数据恢复仍复用各任务的
`recover_trade_date` 能力，避免在队列层捏造或绕开采集器校验逻辑。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from core.managers.data_source_manager import data_source_manager
from core.managers.mongo_manager import mongo_manager
from core.settings import settings


class BackfillQueueService:
    """DataSync 历史补缺队列服务。"""

    def __init__(self, mongo=None) -> None:
        self.mongo = mongo or mongo_manager

    async def enqueue(
        self,
        *,
        dataset: str,
        target_trade_date: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        priority: int = 100,
        created_by: str = "manual",
        payload: Optional[dict] = None,
    ) -> dict:
        """创建一个补缺任务；同一 dataset/date/window 会去重。"""
        return await self.mongo.create_backfill_job(
            dataset=dataset,
            target_trade_date=target_trade_date,
            start_date=start_date,
            end_date=end_date,
            priority=priority,
            created_by=created_by,
            payload=payload or {},
        )

    async def list_jobs(
        self,
        *,
        status: Optional[str] = None,
        dataset: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """列出补缺任务。"""
        return await self.mongo.list_backfill_jobs(status=status, dataset=dataset, limit=limit)

    async def run_once(
        self,
        node: Any,
        *,
        limit: int,
        max_attempts: int,
        max_jobs_per_night: Optional[int] = None,
        max_external_requests_per_night: Optional[int] = None,
        consecutive_failure_limit: Optional[int] = None,
        budget_date: Optional[str] = None,
    ) -> dict:
        """领取并执行一小批补缺任务。"""
        results = []
        success_count = 0
        failed_count = 0
        claimed_count = 0
        stopped_reason: Optional[str] = None
        safe_limit = max(1, min(int(limit or 1), 20))
        safe_max_attempts = max(1, int(max_attempts or 3))
        safe_max_jobs = max(
            0,
            int(
                settings.data_sync.backfill_max_jobs_per_night
                if max_jobs_per_night is None
                else max_jobs_per_night
            ),
        )
        safe_max_requests = max(
            0,
            int(
                settings.data_sync.backfill_max_external_requests_per_night
                if max_external_requests_per_night is None
                else max_external_requests_per_night
            ),
        )
        safe_failure_limit = max(
            1,
            int(
                settings.data_sync.backfill_consecutive_failure_limit
                if consecutive_failure_limit is None
                else consecutive_failure_limit
            ),
        )
        budget_key = budget_date or datetime.now().strftime("%Y%m%d")
        budget_state = await self.mongo.get_backfill_budget_state(budget_key)

        while claimed_count < safe_limit:
            stopped_reason = self._get_budget_stop_reason(
                budget_state,
                max_jobs=safe_max_jobs,
                max_external_requests=safe_max_requests,
                consecutive_failure_limit=safe_failure_limit,
            )
            if stopped_reason:
                break

            claimed = await self.mongo.claim_backfill_jobs(
                limit=1,
                node_id=getattr(node, "node_id", "datasync"),
                max_attempts=safe_max_attempts,
            )
            if not claimed:
                break

            job = claimed[0]
            claimed_count += 1
            job_id = job.get("job_id")
            dataset = job.get("dataset")
            trade_date = job.get("target_trade_date")
            requests_before = self._current_external_request_count()
            if not job_id or not dataset or not trade_date:
                failed_count += 1
                result = {"job": job, "success": False, "error": "invalid_backfill_job_payload"}
                if job_id:
                    await self.mongo.mark_backfill_job_failed(
                        job_id,
                        error="invalid_backfill_job_payload",
                        result=result,
                        max_attempts=safe_max_attempts,
                    )
                budget_state = await self.mongo.record_backfill_budget_usage(
                    budget_key,
                    job_success=False,
                    external_requests=max(0, self._current_external_request_count() - requests_before),
                    result=result,
                )
                results.append({"job_id": job_id, "success": False, "error": "invalid_backfill_job_payload"})
                continue

            result = await node._recover_job_trade_date(
                dataset,
                trade_date,
                trigger="backfill_queue",
                pipeline_name="backfill_queue",
                force_backfill_window=True,
            )
            request_delta = max(0, self._current_external_request_count() - requests_before)
            item = {
                "job_id": job_id,
                "dataset": dataset,
                "target_trade_date": trade_date,
                "success": bool(result.get("success")),
                "external_requests": request_delta,
                "result": result,
            }
            results.append(item)
            if result.get("success"):
                success_count += 1
                await self.mongo.mark_backfill_job_done(job_id, result=result)
                budget_state = await self.mongo.record_backfill_budget_usage(
                    budget_key,
                    job_success=True,
                    external_requests=request_delta,
                    result=item,
                )
            else:
                failed_count += 1
                error = (
                    result.get("error")
                    or result.get("result", {}).get("error")
                    or result.get("result", {}).get("reason")
                    or "backfill_job_failed"
                )
                await self.mongo.mark_backfill_job_failed(
                    job_id,
                    error=str(error),
                    result=result,
                    max_attempts=safe_max_attempts,
                )
                budget_state = await self.mongo.record_backfill_budget_usage(
                    budget_key,
                    job_success=False,
                    external_requests=request_delta,
                    result=item,
                )

        return {
            "success": True,
            "claimed": claimed_count,
            "success_count": success_count,
            "failed_count": failed_count,
            "stopped_reason": stopped_reason,
            "budget_date": budget_key,
            "budget": {
                "state": budget_state,
                "max_jobs_per_night": safe_max_jobs,
                "max_external_requests_per_night": safe_max_requests,
                "consecutive_failure_limit": safe_failure_limit,
            },
            "results": results,
        }

    @staticmethod
    def _current_external_request_count() -> int:
        try:
            summary = data_source_manager.get_call_stats_summary()
        except Exception:
            return 0
        return sum(int(item.get("attempt_count") or 0) for item in summary.get("entries", []))

    @staticmethod
    def _get_budget_stop_reason(
        budget_state: dict,
        *,
        max_jobs: int,
        max_external_requests: int,
        consecutive_failure_limit: int,
    ) -> Optional[str]:
        if max_jobs <= 0:
            return "backfill_job_budget_disabled"
        if int(budget_state.get("jobs_consumed") or 0) >= max_jobs:
            return "backfill_job_budget_exhausted"
        if max_external_requests <= 0:
            return "backfill_request_budget_disabled"
        if int(budget_state.get("external_requests") or 0) >= max_external_requests:
            return "backfill_request_budget_exhausted"
        if int(budget_state.get("consecutive_failures") or 0) >= consecutive_failure_limit:
            return "backfill_consecutive_failures_exhausted"
        return None
