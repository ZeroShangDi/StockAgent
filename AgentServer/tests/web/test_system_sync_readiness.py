import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from nodes.web.api import system_sync


class FakeMongoManager:
    def __init__(self, marker, failures=None, backfill_jobs=None, ops_events=None, counts=None):
        self.marker = marker
        self.failures = failures or []
        self.backfill_jobs = backfill_jobs or []
        self.ops_events = ops_events or []
        self.counts = counts or {}
        self.calls = []

    async def find_one(self, collection, query, projection=None, sort=None):
        self.calls.append({"collection": collection, "query": query, "projection": projection, "sort": sort})
        if collection == "datasync_backfill_jobs":
            for job in self.backfill_jobs:
                if all(job.get(key) == value for key, value in query.items()):
                    return job
            return None
        return self.marker

    async def update_one(self, collection, filter, update, upsert=False):
        self.calls.append({"collection": collection, "filter": filter, "update": update, "upsert": upsert})
        if collection != "datasync_backfill_jobs":
            return 0

        row = None
        for job in self.backfill_jobs:
            if all(job.get(key) == value for key, value in filter.items()):
                row = job
                break
        if row is None:
            if not upsert:
                return 0
            row = {}
            self.backfill_jobs.append(row)
            if "$setOnInsert" in update:
                row.update(update["$setOnInsert"])
        if "$set" in update:
            row.update(update["$set"])
        return 1

    async def insert_one(self, collection, document):
        self.calls.append({"collection": collection, "document": document, "operation": "insert_one"})
        if collection == "ops_events":
            self.ops_events.append(document)
            return document.get("event_id", "event")
        return "inserted"

    async def find_many(self, collection, query, projection=None, sort=None, limit=0, skip=0):
        self.calls.append(
            {
                "collection": collection,
                "query": query,
                "projection": projection,
                "sort": sort,
                "limit": limit,
                "skip": skip,
            }
        )
        if collection == "job_execution_records":
            return self.failures[:limit]
        if collection == "datasync_backfill_jobs":
            return self.backfill_jobs[:limit]
        if collection == "ops_events":
            return self.ops_events[:limit]
        return []

    async def count(self, collection, query):
        self.calls.append({"collection": collection, "query": query, "operation": "count"})
        return self.counts.get(query.get("status"), 0)


class MarketCoreReadinessTest(unittest.IsolatedAsyncioTestCase):
    def test_serialize_market_core_readiness_keeps_required_contract(self):
        marker = {
            "_id": object(),
            "marker_type": "market_core_ready",
            "trade_date": "20260528",
            "status": "ready",
            "ready_at": datetime(2026, 5, 28, 15, 8, tzinfo=UTC),
            "ready_datasets": ["stock_daily"],
            "pending_datasets": [],
            "warnings": [{"dataset": "daily_basic", "state": "warning"}],
            "last_checked_at": datetime(2026, 5, 28, 15, 9, tzinfo=UTC),
            "source": "datasync",
            "node_id": "data_sync",
            "details": {"nested_at": datetime(2026, 5, 28, 15, 10, tzinfo=UTC), "_id": object()},
        }

        payload = system_sync._serialize_market_core_readiness(marker)

        self.assertEqual(payload["trade_date"], "20260528")
        self.assertEqual(payload["status"], "ready")
        self.assertTrue(payload["usable"])
        self.assertTrue(payload["ready_at"].startswith("2026-05-28T15:08:00"))
        self.assertNotIn("_id", payload["details"])
        self.assertTrue(payload["details"]["nested_at"].startswith("2026-05-28T15:10:00"))

    def test_serialize_market_core_readiness_handles_missing_marker(self):
        payload = system_sync._serialize_market_core_readiness(None, trade_date="20260528")

        self.assertEqual(payload["marker_type"], "market_core_ready")
        self.assertEqual(payload["trade_date"], "20260528")
        self.assertEqual(payload["status"], "missing")
        self.assertFalse(payload["usable"])
        self.assertEqual(payload["pending_datasets"], [])

    def test_serialize_market_core_readiness_unknown_status_fails_closed(self):
        payload = system_sync._serialize_market_core_readiness(
            {"trade_date": "20260528", "status": "unexpected"}
        )

        self.assertEqual(payload["status"], "failed")
        self.assertFalse(payload["usable"])

    async def test_get_market_core_readiness_marker_queries_latest(self):
        fake_mongo = FakeMongoManager(
            {
                "marker_type": "market_core_ready",
                "trade_date": "20260528",
                "status": "degraded",
                "ready_datasets": ["stock_daily"],
                "pending_datasets": [],
                "warnings": [{"dataset": "daily_basic"}],
            }
        )

        with patch.object(system_sync, "mongo_manager", fake_mongo):
            payload = await system_sync.get_market_core_readiness_marker()

        self.assertEqual(payload["trade_date"], "20260528")
        self.assertEqual(payload["status"], "degraded")
        self.assertTrue(payload["usable"])
        self.assertEqual(
            fake_mongo.calls,
            [
                {
                    "collection": "readiness_markers",
                    "query": {"marker_type": "market_core_ready"},
                    "projection": None,
                    "sort": [("trade_date", -1), ("updated_at", -1)],
                }
            ],
        )

    async def test_get_market_core_readiness_marker_queries_trade_date(self):
        fake_mongo = FakeMongoManager(None)

        with patch.object(system_sync, "mongo_manager", fake_mongo):
            payload = await system_sync.get_market_core_readiness_marker("20260527")

        self.assertEqual(payload["trade_date"], "20260527")
        self.assertEqual(payload["status"], "missing")
        self.assertEqual(
            fake_mongo.calls[0]["query"],
            {
                "marker_type": "market_core_ready",
                "trade_date": "20260527",
            },
        )

    async def test_get_datasync_status_panel_summarizes_core_failures_and_backfill_queue(self):
        fake_mongo = FakeMongoManager(
            {
                "marker_type": "market_core_ready",
                "trade_date": "20260528",
                "status": "degraded",
                "ready_datasets": ["stock_daily", "index_daily"],
                "pending_datasets": ["daily_basic"],
                "warnings": [{"dataset": "daily_basic", "reason": "缺失"}],
            },
            failures=[
                {
                    "job_name": "daily_basic",
                    "status": "failed",
                    "target_trade_date": "20260528",
                    "started_at": datetime(2026, 5, 28, 16, 0, tzinfo=UTC),
                    "result": {"error": "upstream_timeout"},
                }
            ],
            backfill_jobs=[
                {
                    "job_id": "bf-1",
                    "dataset": "daily_basic",
                    "target_trade_date": "20260528",
                    "status": "pending",
                    "created_at": datetime(2026, 5, 28, 17, 0, tzinfo=UTC),
                }
            ],
            ops_events=[
                {
                    "event_id": "ops-1",
                    "event_type": "backfill_queue_manual_action",
                    "severity": "info",
                    "message": "manual retry",
                    "source": "web",
                    "node_id": "web",
                    "details": {
                        "job_id": "bf-1",
                        "dataset": "daily_basic",
                        "target_trade_date": "20260528",
                        "action": "retry",
                        "previous_status": "failed",
                        "next_status": "pending",
                        "user_id": "user_01",
                    },
                    "created_at": datetime(2026, 5, 28, 18, 0, tzinfo=UTC),
                }
            ],
            counts={"pending": 1, "failed": 2},
        )
        fake_catalog = {
            "success": True,
            "count": 3,
            "core_ready_datasets": ["stock_daily", "index_daily", "daily_basic"],
            "core_recoverable_datasets": ["daily_basic"],
            "capabilities": [
                {
                    "name": "daily_basic",
                    "dataset_name": "daily_basic",
                    "recoverability": {
                        "mode": "full",
                        "severity_on_missing": "warning",
                    },
                },
                {
                    "name": "hot_news",
                    "dataset_name": "hot_news",
                    "recoverability": {
                        "mode": "none",
                        "severity_on_missing": "warning",
                        "reason": "实时热点不可还原",
                    },
                },
            ],
        }

        with (
            patch.object(system_sync, "mongo_manager", fake_mongo),
            patch.object(system_sync, "_load_datasync_capability_catalog", return_value=fake_catalog),
        ):
            payload = await system_sync.get_datasync_status_panel()

        self.assertEqual(payload["core_status"]["trade_date"], "20260528")
        self.assertEqual(payload["core_status"]["missing_datasets"], ["daily_basic"])
        self.assertEqual(payload["recent_failures"][0]["error"], "upstream_timeout")
        self.assertEqual(payload["recent_failures"][0]["recoverability"]["mode"], "full")
        self.assertEqual(payload["recoverability_summary"]["mode_counts"]["full"], 1)
        self.assertEqual(payload["recoverability_summary"]["mode_counts"]["none"], 1)
        self.assertEqual(
            payload["recoverability_summary"]["missing_datasets"][0]["mode"],
            "full",
        )
        self.assertEqual(payload["backfill_queue"]["pending_total"], 1)
        self.assertEqual(payload["backfill_queue"]["failed_total"], 2)
        self.assertEqual(payload["backfill_queue"]["recent_jobs"][0]["job_id"], "bf-1")
        self.assertEqual(payload["recent_ops_events"][0]["event_type"], "backfill_queue_manual_action")
        self.assertEqual(payload["recent_ops_events"][0]["details"]["action"], "retry")

    async def test_create_datasync_backfill_job_enqueues_supported_dataset(self):
        fake_mongo = FakeMongoManager(None)
        fake_catalog = {
            "success": True,
            "capabilities": [
                {
                    "name": "daily_basic",
                    "dataset_name": "daily_basic",
                    "supports_recover_trade_date": True,
                    "supports_backfill": True,
                    "recoverability": {"mode": "full", "severity_on_missing": "warning"},
                }
            ],
        }

        with (
            patch.object(system_sync, "mongo_manager", fake_mongo),
            patch.object(system_sync, "_load_datasync_capability_catalog", return_value=fake_catalog),
        ):
            payload = await system_sync.create_datasync_backfill_job(
                user_id="user_01",
                dataset="daily_basic",
                trade_date="20260528",
            )

        self.assertFalse(payload["already_exists"])
        self.assertEqual(payload["dataset"], "daily_basic")
        self.assertEqual(payload["target_trade_date"], "20260528")
        self.assertEqual(payload["status"], "pending")
        self.assertEqual(payload["recoverability"]["mode"], "full")

    async def test_create_datasync_backfill_job_reuses_existing_job(self):
        fake_mongo = FakeMongoManager(
            None,
            backfill_jobs=[
                {
                    "job_id": "existing",
                    "dedupe_key": "daily_basic:20260528::",
                    "dataset": "daily_basic",
                    "target_trade_date": "20260528",
                    "status": "pending",
                    "priority": 100,
                }
            ],
        )
        fake_catalog = {
            "success": True,
            "capabilities": [
                {
                    "name": "daily_basic",
                    "dataset_name": "daily_basic",
                    "supports_recover_trade_date": True,
                    "recoverability": {"mode": "full"},
                }
            ],
        }

        with (
            patch.object(system_sync, "mongo_manager", fake_mongo),
            patch.object(system_sync, "_load_datasync_capability_catalog", return_value=fake_catalog),
        ):
            payload = await system_sync.create_datasync_backfill_job(
                user_id="user_01",
                dataset="daily_basic",
                trade_date="20260528",
            )

        self.assertTrue(payload["already_exists"])
        self.assertEqual(payload["job_id"], "existing")
        self.assertEqual(len(fake_mongo.backfill_jobs), 1)

    async def test_create_datasync_backfill_job_rejects_unrecoverable_dataset(self):
        fake_mongo = FakeMongoManager(None)
        fake_catalog = {
            "success": True,
            "capabilities": [
                {
                    "name": "hot_news",
                    "dataset_name": "hot_news",
                    "supports_recover_trade_date": False,
                    "supports_backfill": False,
                    "recoverability": {"mode": "none"},
                }
            ],
        }

        with (
            patch.object(system_sync, "mongo_manager", fake_mongo),
            patch.object(system_sync, "_load_datasync_capability_catalog", return_value=fake_catalog),
        ):
            with self.assertRaises(ValueError):
                await system_sync.create_datasync_backfill_job(
                    user_id="user_01",
                    dataset="hot_news",
                    trade_date="20260528",
                )

    async def test_update_datasync_backfill_job_action_pauses_and_resumes_pending_job(self):
        fake_mongo = FakeMongoManager(
            None,
            backfill_jobs=[
                {
                    "job_id": "bf-pending",
                    "dataset": "daily_basic",
                    "target_trade_date": "20260528",
                    "status": "pending",
                    "attempts": 0,
                }
            ],
        )

        with patch.object(system_sync, "mongo_manager", fake_mongo):
            paused = await system_sync.update_datasync_backfill_job_action(
                user_id="user_01",
                job_id="bf-pending",
                action="pause",
            )
            resumed = await system_sync.update_datasync_backfill_job_action(
                user_id="user_01",
                job_id="bf-pending",
                action="resume",
            )

        self.assertEqual(paused["status"], "paused")
        self.assertEqual(resumed["status"], "pending")
        self.assertEqual(len(fake_mongo.ops_events), 2)
        self.assertEqual(fake_mongo.ops_events[0]["event_type"], "backfill_queue_manual_action")
        self.assertIn("created_at", fake_mongo.ops_events[0])

    async def test_update_datasync_backfill_job_action_retries_failed_job(self):
        fake_mongo = FakeMongoManager(
            None,
            backfill_jobs=[
                {
                    "job_id": "bf-failed",
                    "dataset": "stock_daily",
                    "target_trade_date": "20260528",
                    "status": "failed",
                    "attempts": 3,
                    "last_error": "upstream failed",
                }
            ],
        )

        with patch.object(system_sync, "mongo_manager", fake_mongo):
            payload = await system_sync.update_datasync_backfill_job_action(
                user_id="user_01",
                job_id="bf-failed",
                action="retry",
            )

        self.assertEqual(payload["status"], "pending")
        self.assertEqual(fake_mongo.backfill_jobs[0]["attempts"], 0)
        self.assertIsNone(fake_mongo.backfill_jobs[0]["last_error"])
        self.assertEqual(fake_mongo.ops_events[0]["details"]["action"], "retry")

    async def test_update_datasync_backfill_job_action_rejects_running_pause(self):
        fake_mongo = FakeMongoManager(
            None,
            backfill_jobs=[
                {
                    "job_id": "bf-running",
                    "dataset": "stock_daily",
                    "target_trade_date": "20260528",
                    "status": "running",
                    "attempts": 1,
                }
            ],
        )

        with patch.object(system_sync, "mongo_manager", fake_mongo):
            with self.assertRaises(ValueError):
                await system_sync.update_datasync_backfill_job_action(
                    user_id="user_01",
                    job_id="bf-running",
                    action="pause",
                )

        self.assertEqual(fake_mongo.backfill_jobs[0]["status"], "running")
        self.assertEqual(fake_mongo.ops_events, [])


if __name__ == "__main__":
    unittest.main()
