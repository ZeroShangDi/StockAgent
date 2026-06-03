from pathlib import Path
import sys
import unittest


DATASYNC_ROOT = Path(__file__).resolve().parents[1]
if str(DATASYNC_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASYNC_ROOT))

from core.managers.mongo_manager import MongoManager
from nodes.data_sync.services.backfill_queue import BackfillQueueService


class _MongoManagerForBackfillQueueTest(MongoManager):
    def __init__(self) -> None:
        super().__init__()
        self._initialized = True
        self.rows_by_job_id = {}
        self.rows_by_dedupe = {}
        self.rows_by_budget_date = {}

    async def update_one(self, collection: str, filter: dict, update: dict, upsert: bool = False) -> int:
        self._assert_collection(collection)
        row = self._find_row(filter)
        if row is None:
            if not upsert:
                return 0
            row = {}

        if not self._matches(row, filter) and row:
            return 0

        was_empty = not row
        if "$setOnInsert" in update and was_empty:
            row.update(update["$setOnInsert"])
        if "$set" in update:
            row.update(update["$set"])
        elif not any(key.startswith("$") for key in update):
            row.update(update)
        if "$inc" in update:
            for key, value in update["$inc"].items():
                row[key] = int(row.get(key) or 0) + int(value)

        self._store(row)
        return 1

    async def find_one(self, collection: str, filter: dict, projection=None, sort=None):
        self._assert_collection(collection)
        row = self._find_row(filter)
        return dict(row) if row and self._matches(row, filter) else None

    async def find_many(self, collection: str, filter: dict, projection=None, sort=None, limit: int = 0, skip: int = 0):
        self._assert_collection(collection)
        source = self.rows_by_budget_date if collection == "datasync_backfill_budgets" else self.rows_by_job_id
        rows = [dict(row) for row in source.values() if self._matches(row, filter)]
        rows.sort(key=lambda item: (item.get("priority", 100), item.get("created_at")))
        return rows[:limit or None]

    def _find_row(self, filter: dict):
        if "job_id" in filter:
            return self.rows_by_job_id.get(filter["job_id"])
        if "dedupe_key" in filter:
            return self.rows_by_dedupe.get(filter["dedupe_key"])
        if "budget_date" in filter:
            return self.rows_by_budget_date.get(filter["budget_date"])
        return None

    def _store(self, row: dict) -> None:
        if "budget_date" in row:
            self.rows_by_budget_date[row["budget_date"]] = row
            return
        self.rows_by_job_id[row["job_id"]] = row
        self.rows_by_dedupe[row["dedupe_key"]] = row

    @staticmethod
    def _matches(row: dict, filter: dict) -> bool:
        for key, expected in filter.items():
            actual = row.get(key)
            if isinstance(expected, dict):
                if "$lt" in expected and not (actual < expected["$lt"]):
                    return False
            elif actual != expected:
                return False
        return True

    @staticmethod
    def _assert_collection(collection: str) -> None:
        if collection not in {"datasync_backfill_jobs", "datasync_backfill_budgets"}:
            raise AssertionError(f"unexpected collection: {collection}")


class _FakeNode:
    node_id = "node-test"

    def __init__(self, success: bool = True) -> None:
        self.success = success
        self.calls = []

    async def _recover_job_trade_date(self, dataset: str, trade_date: str, **kwargs):
        self.calls.append({"dataset": dataset, "trade_date": trade_date, **kwargs})
        if self.success:
            return {"success": True, "count": 1, "trade_date": trade_date}
        return {"success": False, "error": "upstream failed", "trade_date": trade_date}


class MongoBackfillQueueTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_claim_done_and_failed_status_flow(self) -> None:
        manager = _MongoManagerForBackfillQueueTest()

        first = await manager.create_backfill_job(
            dataset="stock_daily",
            target_trade_date="20260528",
            priority=10,
            created_by="unit",
        )
        duplicate = await manager.create_backfill_job(
            dataset="stock_daily",
            target_trade_date="20260528",
            priority=99,
            created_by="unit",
        )
        self.assertEqual(first["job_id"], duplicate["job_id"])
        self.assertEqual(duplicate["priority"], 10)

        claimed = await manager.claim_backfill_jobs(limit=1, node_id="node-a", max_attempts=2)
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0]["status"], "running")
        self.assertEqual(claimed[0]["attempts"], 1)
        self.assertEqual(claimed[0]["locked_by"], "node-a")

        await manager.mark_backfill_job_failed(
            first["job_id"],
            error="temporary",
            result={"success": False},
            max_attempts=2,
        )
        retry_row = await manager.find_one("datasync_backfill_jobs", {"job_id": first["job_id"]})
        self.assertEqual(retry_row["status"], "pending")

        await manager.claim_backfill_jobs(limit=1, node_id="node-a", max_attempts=2)
        await manager.mark_backfill_job_failed(
            first["job_id"],
            error="final",
            result={"success": False},
            max_attempts=2,
        )
        failed = await manager.find_one("datasync_backfill_jobs", {"job_id": first["job_id"]})
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["last_error"], "final")


class BackfillQueueServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_run_once_marks_successful_job_done(self) -> None:
        manager = _MongoManagerForBackfillQueueTest()
        service = BackfillQueueService(manager)
        job = await service.enqueue(dataset="stock_daily", target_trade_date="20260528")

        result = await service.run_once(_FakeNode(success=True), limit=2, max_attempts=3)

        self.assertEqual(result["claimed"], 1)
        self.assertEqual(result["success_count"], 1)
        row = await manager.find_one("datasync_backfill_jobs", {"job_id": job["job_id"]})
        self.assertEqual(row["status"], "done")

    async def test_run_once_requeues_until_max_attempts_then_failed(self) -> None:
        manager = _MongoManagerForBackfillQueueTest()
        service = BackfillQueueService(manager)
        job = await service.enqueue(dataset="stock_daily", target_trade_date="20260528")

        first = await service.run_once(_FakeNode(success=False), limit=1, max_attempts=2)
        self.assertEqual(first["failed_count"], 1)
        row = await manager.find_one("datasync_backfill_jobs", {"job_id": job["job_id"]})
        self.assertEqual(row["status"], "pending")

        second = await service.run_once(_FakeNode(success=False), limit=1, max_attempts=2)
        self.assertEqual(second["failed_count"], 1)
        failed = await manager.find_one("datasync_backfill_jobs", {"job_id": job["job_id"]})
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["attempts"], 2)

    async def test_run_once_stops_when_job_budget_is_exhausted(self) -> None:
        manager = _MongoManagerForBackfillQueueTest()
        service = BackfillQueueService(manager)
        await service.enqueue(dataset="stock_daily", target_trade_date="20260528", priority=1)
        await service.enqueue(dataset="daily_basic", target_trade_date="20260528", priority=2)

        result = await service.run_once(
            _FakeNode(success=True),
            limit=2,
            max_attempts=3,
            max_jobs_per_night=1,
            max_external_requests_per_night=100,
            budget_date="20260529",
        )

        self.assertEqual(result["claimed"], 1)
        self.assertEqual(result["stopped_reason"], "backfill_job_budget_exhausted")
        budget = await manager.get_backfill_budget_state("20260529")
        self.assertEqual(budget["jobs_consumed"], 1)

    async def test_run_once_stops_after_consecutive_failure_limit(self) -> None:
        manager = _MongoManagerForBackfillQueueTest()
        service = BackfillQueueService(manager)
        await service.enqueue(dataset="stock_daily", target_trade_date="20260528", priority=1)
        await service.enqueue(dataset="daily_basic", target_trade_date="20260528", priority=2)

        result = await service.run_once(
            _FakeNode(success=False),
            limit=2,
            max_attempts=3,
            max_jobs_per_night=10,
            max_external_requests_per_night=100,
            consecutive_failure_limit=1,
            budget_date="20260529",
        )

        self.assertEqual(result["claimed"], 1)
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["stopped_reason"], "backfill_consecutive_failures_exhausted")
        budget = await manager.get_backfill_budget_state("20260529")
        self.assertEqual(budget["consecutive_failures"], 1)


if __name__ == "__main__":
    unittest.main()
