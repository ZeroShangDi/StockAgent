from pathlib import Path
import importlib
import logging
import sys
import unittest


DATASYNC_ROOT = Path(__file__).resolve().parents[1]
if str(DATASYNC_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASYNC_ROOT))

from core.base.collector import BaseCollector
from core.settings import settings


class _ValidationCollector(BaseCollector):
    name = "validation_test"
    description = "validation test"
    default_schedule = "* * * * *"

    async def collect(self):
        return {"count": 0}


class CollectorValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.collector = _ValidationCollector()

    def test_stock_daily_validation_drops_missing_required_and_converts_types(self) -> None:
        records = [
            {
                "ts_code": "000001.SZ",
                "trade_date": "2026-05-28",
                "open": "10.1",
                "high": "10.8",
                "low": "9.9",
                "close": "10.5",
                "vol": "1000",
            },
            {
                "ts_code": "000002.SZ",
                "trade_date": "20260528",
                "open": "10.1",
                "high": "10.8",
                "low": "9.9",
            },
        ]

        valid = self.collector._validate_records_for_collection(records, "stock_daily")

        self.assertEqual(len(valid), 1)
        self.assertEqual(valid[0]["trade_date"], "20260528")
        self.assertEqual(valid[0]["open"], 10.1)
        self.assertEqual(valid[0]["vol"], 1000.0)

    def test_daily_basic_validation_keeps_valid_null_optional_metrics(self) -> None:
        records = [
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260528",
                "pe": None,
                "pb": "1.23",
                "total_mv": "bad-number",
            }
        ]

        valid = self.collector._validate_records_for_collection(records, "daily_basic")

        self.assertEqual(len(valid), 1)
        self.assertIsNone(valid[0]["pe"])
        self.assertEqual(valid[0]["pb"], 1.23)
        self.assertNotIn("total_mv", valid[0])

    def test_limit_list_validation_converts_ints_and_requires_limit_type(self) -> None:
        records = [
            {
                "ts_code": "000001.SZ",
                "trade_date": "20260528",
                "limit": "U",
                "open_times": "2.0",
                "limit_times": "3",
            },
            {
                "ts_code": "000002.SZ",
                "trade_date": "20260528",
            },
        ]

        valid = self.collector._validate_records_for_collection(records, "limit_list")

        self.assertEqual(len(valid), 1)
        self.assertEqual(valid[0]["open_times"], 2)
        self.assertEqual(valid[0]["limit_times"], 3)

    def test_unknown_collection_is_not_modified(self) -> None:
        records = [{"raw": object()}]

        valid = self.collector._validate_records_for_collection(records, "unknown_collection")

        self.assertIs(valid, records)

    def test_bad_record_log_samples_respect_observability_limit(self) -> None:
        records = [
            {
                "ts_code": f"{idx:06d}.SZ",
                "trade_date": "20260528",
                "open": "10.1",
                "high": "10.8",
                "low": "9.9",
            }
            for idx in range(3)
        ]
        captured = []

        class CaptureHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record)

        original_limit = settings.observability.log_sample_limit
        original_handlers = list(self.collector.logger.handlers)
        original_propagate = self.collector.logger.propagate
        original_level = self.collector.logger.level
        self.collector.logger.handlers = []
        self.collector.logger.propagate = False
        self.collector.logger.addHandler(CaptureHandler())
        self.collector.logger.setLevel(logging.WARNING)
        settings.observability.log_sample_limit = 1
        try:
            valid, dead_letters = self.collector._validate_records_with_dead_letters(
                records,
                "stock_daily",
            )
        finally:
            settings.observability.log_sample_limit = original_limit
            self.collector.logger.handlers = original_handlers
            self.collector.logger.propagate = original_propagate
            self.collector.logger.setLevel(original_level)

        self.assertEqual(valid, [])
        self.assertEqual(len(dead_letters), 3)
        self.assertEqual(len(captured), 1)
        extra = captured[0].extra_data
        self.assertEqual(extra["event"], "datasync_validation_dropped_records")
        self.assertEqual(extra["bad_count"], 3)
        self.assertEqual(extra["sample_limit"], 1)
        self.assertEqual(len(extra["samples"]), 1)


class CollectorDeadLetterTest(unittest.IsolatedAsyncioTestCase):
    async def test_dead_letter_samples_are_recorded_best_effort(self) -> None:
        collector = _ValidationCollector()
        valid, dead_letters = collector._validate_records_with_dead_letters(
            [
                {
                    "ts_code": "000002.SZ",
                    "trade_date": "20260528",
                    "open": "10.1",
                    "high": "10.8",
                    "low": "9.9",
                }
            ],
            "stock_daily",
        )

        class FakeMongoManager:
            def __init__(self) -> None:
                self.calls = []

            async def record_dead_letters(self, **kwargs):
                self.calls.append(kwargs)
                return len(kwargs["records"])

        mongo_module = importlib.import_module("core.managers.mongo_manager")
        original = mongo_module.mongo_manager
        fake = FakeMongoManager()
        mongo_module.mongo_manager = fake
        try:
            await collector._record_dead_letters("stock_daily", dead_letters)
        finally:
            mongo_module.mongo_manager = original

        self.assertEqual(valid, [])
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.calls[0]["job_name"], "validation_test")
        self.assertEqual(fake.calls[0]["collection"], "stock_daily")
        self.assertEqual(fake.calls[0]["records"][0]["error_type"], "validation_failed")

    async def test_write_results_are_attached_to_do_work_result(self) -> None:
        class WriteResultCollector(_ValidationCollector):
            async def collect(self):
                count = await self._write_buffer(
                    [
                        {
                            "ts_code": "000001.SZ",
                            "trade_date": "20260528",
                            "open": 10,
                            "high": 11,
                            "low": 9,
                            "close": 10.5,
                        }
                    ],
                    "stock_daily",
                    ["ts_code", "trade_date"],
                )
                return {"count": count}

        class FakeMongoManager:
            async def record_dead_letters(self, **kwargs):
                return 0

            async def bulk_upsert_batched(self, **kwargs):
                return {
                    "matched": 0,
                    "modified": 0,
                    "upserted": 1,
                    "inserted": 1,
                    "failed": 0,
                    "total": len(kwargs["documents"]),
                    "batch_count": 1,
                    "batch_size": kwargs["batch_size"],
                    "batch_size_history": [kwargs["batch_size"]],
                    "adaptive_batching": {"enabled": True, "min_batch_size": 100},
                    "batch_errors": [],
                }

        mongo_module = importlib.import_module("core.managers.mongo_manager")
        original = mongo_module.mongo_manager
        mongo_module.mongo_manager = FakeMongoManager()
        try:
            result = await WriteResultCollector()._do_work()
        finally:
            mongo_module.mongo_manager = original

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["write_results"][0]["collection"], "stock_daily")
        self.assertEqual(result["write_results"][0]["inserted"], 1)
        self.assertEqual(result["write_results"][0]["batch_size_history"], [1000])
        self.assertTrue(result["write_results"][0]["adaptive_batching"]["enabled"])


if __name__ == "__main__":
    unittest.main()
