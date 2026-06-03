from pathlib import Path
import sys
import unittest
from unittest.mock import patch


DATASYNC_ROOT = Path(__file__).resolve().parents[1]
if str(DATASYNC_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASYNC_ROOT))

from core.managers.mongo_manager import BulkUpsertBatchError, MongoManager
from core.settings import settings


class _FakeBulkWriteResult:
    def __init__(self, matched: int, modified: int, upserted: int) -> None:
        self.matched_count = matched
        self.modified_count = modified
        self.upserted_count = upserted


class _FakeCollection:
    def __init__(self) -> None:
        self.bulk_write_calls = []

    async def bulk_write(self, operations, ordered: bool = False):
        self.bulk_write_calls.append({"operations": operations, "ordered": ordered})
        return _FakeBulkWriteResult(matched=1, modified=1, upserted=max(len(operations) - 1, 0))


class _FakeDB:
    def __init__(self) -> None:
        self.collections = {}

    def __getitem__(self, collection: str) -> _FakeCollection:
        if collection not in self.collections:
            self.collections[collection] = _FakeCollection()
        return self.collections[collection]


class _MongoManagerForDeadLetterTest(MongoManager):
    def __init__(self) -> None:
        super().__init__()
        self._initialized = True
        self._db = _FakeDB()
        self.bulk_insert_calls = []

    async def bulk_insert(self, collection: str, documents: list[dict], batch_size: int = 1000, ordered: bool = False) -> int:
        self.bulk_insert_calls.append(
            {
                "collection": collection,
                "documents": documents,
                "batch_size": batch_size,
                "ordered": ordered,
            }
        )
        return len(documents)


class _MongoManagerForCheckpointTest(MongoManager):
    def __init__(self) -> None:
        super().__init__()
        self._initialized = True
        self.rows = {}

    async def update_one(self, collection: str, filter: dict, update: dict, upsert: bool = False) -> int:
        self.assert_collection(collection)
        checkpoint_id = filter["checkpoint_id"]
        row = self.rows.setdefault(checkpoint_id, {})
        if "$setOnInsert" in update and not row:
            row.update(update["$setOnInsert"])
        if "$set" in update:
            row.update(update["$set"])
        else:
            row.update(update)
        return 1

    async def find_one(self, collection: str, filter: dict, projection=None, sort=None):
        self.assert_collection(collection)
        checkpoint_id = filter["checkpoint_id"]
        row = self.rows.get(checkpoint_id)
        return dict(row) if row else None

    async def find_many(self, collection: str, filter: dict, projection=None, sort=None, limit: int = 0, skip: int = 0):
        self.assert_collection(collection)
        rows = []
        for row in self.rows.values():
            if all(row.get(key) == value for key, value in filter.items()):
                rows.append(dict(row))
        rows.sort(key=lambda item: item.get("updated_at"), reverse=True)
        return rows[:limit or None]

    @staticmethod
    def assert_collection(collection: str) -> None:
        if collection != "datasync_checkpoints":
            raise AssertionError(f"unexpected collection: {collection}")


class MongoDeadLetterTest(unittest.IsolatedAsyncioTestCase):
    async def test_record_dead_letters_enforces_limit_and_fields(self) -> None:
        manager = _MongoManagerForDeadLetterTest()

        written = await manager.record_dead_letters(
            job_name="stock_daily",
            collection="stock_daily",
            source="tushare",
            target_trade_date="20260528",
            max_records=2,
            records=[
                {"reason": ["missing_required:close"], "raw_item": {"ts_code": "000001.SZ", "trade_date": "20260528"}},
                {"reason": "invalid_date:trade_date", "raw_item": {"ts_code": "000002.SZ", "trade_date": "bad"}},
                {"reason": "overflow", "raw_item": {"ts_code": "000003.SZ"}},
            ],
        )

        self.assertEqual(written, 2)
        call = manager.bulk_insert_calls[0]
        self.assertEqual(call["collection"], "datasync_dead_letters")
        self.assertEqual(call["batch_size"], 2)
        self.assertFalse(call["ordered"])
        self.assertEqual(len(call["documents"]), 2)
        first = call["documents"][0]
        self.assertEqual(first["job_name"], "stock_daily")
        self.assertEqual(first["collection"], "stock_daily")
        self.assertEqual(first["source"], "tushare")
        self.assertEqual(first["target_trade_date"], "20260528")
        self.assertEqual(first["error_type"], "validation_failed")
        self.assertIn("dead_letter_id", first)
        self.assertIn("created_at", first)


class MongoBulkUpsertBatchedTest(unittest.IsolatedAsyncioTestCase):
    async def test_bulk_upsert_batched_requires_key_fields(self) -> None:
        manager = _MongoManagerForDeadLetterTest()

        with self.assertRaises(ValueError):
            await manager.bulk_upsert_batched("stock_daily", [{"ts_code": "000001.SZ"}], [])

    async def test_bulk_upsert_batched_batches_and_returns_structured_result(self) -> None:
        manager = _MongoManagerForDeadLetterTest()

        result = await manager.bulk_upsert_batched(
            "stock_daily",
            [
                {"ts_code": "000001.SZ", "trade_date": "20260528", "close": 10},
                {"ts_code": "000002.SZ", "trade_date": "20260528", "close": 11},
                {"ts_code": "000003.SZ", "trade_date": "20260528", "close": 12},
            ],
            ["ts_code", "trade_date"],
            batch_size=2,
        )

        collection = manager._db["stock_daily"]
        self.assertEqual(len(collection.bulk_write_calls), 2)
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["batch_count"], 2)
        self.assertEqual(result["batch_size"], 2)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["upserted"], 1)
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(result["batch_size_history"], [2, 1])
        self.assertTrue(result["adaptive_batching"]["enabled"])

    async def test_bulk_upsert_batched_shrinks_after_slow_batch(self) -> None:
        manager = _MongoManagerForDeadLetterTest()
        original_min = settings.data_sync.bulk_upsert_min_batch_size
        original_max = settings.data_sync.bulk_upsert_max_batch_size
        original_slow_ms = settings.data_sync.bulk_upsert_slow_batch_ms
        original_grow = settings.data_sync.bulk_upsert_stable_batches_to_grow
        settings.data_sync.bulk_upsert_min_batch_size = 2
        settings.data_sync.bulk_upsert_max_batch_size = 4
        settings.data_sync.bulk_upsert_slow_batch_ms = 100
        settings.data_sync.bulk_upsert_stable_batches_to_grow = 99
        perf_values = iter([0.0, 0.2, 0.2, 0.21])
        try:
            with patch("core.managers.mongo_manager.time.perf_counter", lambda: next(perf_values)):
                result = await manager.bulk_upsert_batched(
                    "stock_daily",
                    [
                        {"ts_code": f"{idx:06d}.SZ", "trade_date": "20260528", "close": idx}
                        for idx in range(6)
                    ],
                    ["ts_code", "trade_date"],
                    batch_size=4,
                )
        finally:
            settings.data_sync.bulk_upsert_min_batch_size = original_min
            settings.data_sync.bulk_upsert_max_batch_size = original_max
            settings.data_sync.bulk_upsert_slow_batch_ms = original_slow_ms
            settings.data_sync.bulk_upsert_stable_batches_to_grow = original_grow

        collection = manager._db["stock_daily"]
        self.assertEqual([len(call["operations"]) for call in collection.bulk_write_calls], [4, 2])
        self.assertEqual(result["batch_size_history"], [4, 2])
        self.assertEqual(result["adaptive_batching"]["min_batch_size"], 2)
        self.assertEqual(result["adaptive_batching"]["slow_batch_ms"], 100)

    async def test_bulk_upsert_batched_raises_structured_error_for_missing_business_key(self) -> None:
        manager = _MongoManagerForDeadLetterTest()

        with self.assertRaises(BulkUpsertBatchError) as ctx:
            await manager.bulk_upsert_batched(
                "stock_daily",
                [{"ts_code": "000001.SZ", "close": 10}],
                ["ts_code", "trade_date"],
                batch_size=10,
            )

        self.assertEqual(ctx.exception.result["failed"], 1)
        self.assertEqual(ctx.exception.result["batch_errors"][0]["error_type"], "ValueError")


class MongoCheckpointTest(unittest.IsolatedAsyncioTestCase):
    async def test_checkpoint_upsert_get_mark_done_and_list(self) -> None:
        manager = _MongoManagerForCheckpointTest()

        checkpoint_id = await manager.upsert_checkpoint(
            "stock_daily",
            "20260528",
            "history_by_stock:20260501:20260528",
            cursor="000001.SZ",
            last_success_key="000001.SZ",
            details={"processed_batches": 1},
        )
        self.assertEqual(checkpoint_id, "stock_daily:20260528:history_by_stock:20260501:20260528")

        row = await manager.get_checkpoint(
            "stock_daily",
            "20260528",
            "history_by_stock:20260501:20260528",
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "running")
        self.assertEqual(row["last_success_key"], "000001.SZ")

        await manager.mark_checkpoint_done(
            "stock_daily",
            "20260528",
            "history_by_stock:20260501:20260528",
            details={"processed_batches": 2},
        )
        done = await manager.get_checkpoint(
            "stock_daily",
            "20260528",
            "history_by_stock:20260501:20260528",
        )
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["details"]["processed_batches"], 2)

        rows = await manager.list_checkpoints(job_name="stock_daily", status="done", limit=5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["checkpoint_id"], checkpoint_id)


if __name__ == "__main__":
    unittest.main()
