from pathlib import Path
import importlib
import sys
import unittest


DATASYNC_ROOT = Path(__file__).resolve().parents[1]
if str(DATASYNC_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASYNC_ROOT))

daily_module = importlib.import_module("nodes.data_sync.collectors.stock.daily")
mongo_module = importlib.import_module("core.managers.mongo_manager")
StockDailyCollector = daily_module.StockDailyCollector


class _FakeDataSourceManager:
    def __init__(self) -> None:
        self.daily_calls = []

    async def get_daily(self, **kwargs):
        self.daily_calls.append(kwargs)
        trade_date = kwargs.get("trade_date") or kwargs.get("end_date") or "20260528"
        ts_code = kwargs.get("ts_code") or "000001.SZ"
        return (
            [
                {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10.5,
                }
            ],
            "fake",
        )


class _FakeMongoManager:
    def __init__(self, checkpoint=None) -> None:
        self.checkpoint = checkpoint
        self.checkpoint_updates = []
        self.db = {"sync_failures": _FakeFailureCollection()}

    async def get_checkpoint(self, **kwargs):
        return dict(self.checkpoint) if self.checkpoint else None

    async def upsert_checkpoint(self, **kwargs):
        self.checkpoint_updates.append(kwargs)
        self.checkpoint = dict(kwargs)
        return "checkpoint-id"

    async def record_dead_letters(self, **kwargs):
        return 0

    async def bulk_upsert_batched(self, **kwargs):
        return {
            "matched": 0,
            "modified": len(kwargs["documents"]),
            "upserted": 0,
            "inserted": 0,
            "failed": 0,
            "total": len(kwargs["documents"]),
            "batch_count": 1,
            "batch_size": kwargs["batch_size"],
            "batch_errors": [],
        }


class _FakeFailureCollection:
    async def delete_one(self, filter):
        return None


class StockDailyCheckpointTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_daily_source = daily_module.data_source_manager
        self.original_mongo = mongo_module.mongo_manager

    async def asyncTearDown(self) -> None:
        daily_module.data_source_manager = self.original_daily_source
        mongo_module.mongo_manager = self.original_mongo

    async def test_incremental_trade_date_resume_skips_completed_dates(self) -> None:
        fake_source = _FakeDataSourceManager()
        fake_mongo = _FakeMongoManager({"last_success_key": "20260527", "status": "running"})
        daily_module.data_source_manager = fake_source
        mongo_module.mongo_manager = fake_mongo

        total_count, result = await StockDailyCollector()._collect_incremental_by_trade_date(
            ["20260526", "20260527", "20260528"]
        )

        self.assertEqual(total_count, 1)
        self.assertEqual(result["skipped_by_checkpoint"], 2)
        self.assertEqual(result["success"], 3)
        self.assertEqual(fake_source.daily_calls, [{"trade_date": "20260528"}])
        self.assertEqual(fake_mongo.checkpoint["status"], "done")

    async def test_history_by_stock_resume_runs_after_last_success_key(self) -> None:
        fake_source = _FakeDataSourceManager()
        fake_mongo = _FakeMongoManager({"last_success_key": "000001.SZ", "status": "running"})
        daily_module.data_source_manager = fake_source
        mongo_module.mongo_manager = fake_mongo

        total_count, result = await StockDailyCollector()._collect_history_by_stock(
            ["000001.SZ", "000002.SZ", "000003.SZ"],
            "20260501",
            "20260528",
            fetch_batch_size=1,
        )

        self.assertEqual(total_count, 2)
        self.assertEqual(result["skipped_by_checkpoint"], 1)
        self.assertEqual(result["success"], 3)
        self.assertEqual(
            [call["ts_code"] for call in fake_source.daily_calls],
            ["000002.SZ", "000003.SZ"],
        )
        self.assertEqual(fake_mongo.checkpoint["status"], "done")


if __name__ == "__main__":
    unittest.main()
