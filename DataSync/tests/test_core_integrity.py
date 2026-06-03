from datetime import datetime
from pathlib import Path
import sys
import unittest


DATASYNC_ROOT = Path(__file__).resolve().parents[1]
if str(DATASYNC_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASYNC_ROOT))

from nodes.data_sync.services import core_integrity


class _FakeDataSourceManager:
    def __init__(self, latest_trade_date: str) -> None:
        self.latest_trade_date = latest_trade_date

    async def get_latest_trade_date(self) -> tuple[str, None]:
        return self.latest_trade_date, None

    async def get_trade_calendar(self, start_date: str, end_date: str) -> tuple[list[str], None]:
        return [self.latest_trade_date], None


class _FakeMongoManager:
    def __init__(
        self,
        *,
        listed_stock_count: int = 100,
        counts: dict[str, int] | None = None,
        executions: dict[tuple[str, str], dict] | None = None,
    ) -> None:
        self.listed_stock_count = listed_stock_count
        self.counts = counts or {}
        self.executions = executions or {}

    async def count(self, collection: str, filter: dict) -> int:
        if collection == "stock_basic":
            return self.listed_stock_count
        trade_date = str(filter.get("trade_date") or "")
        return self.counts.get(f"{collection}:{trade_date}", 0)

    async def get_last_sync_date(self, sync_type: str) -> str | None:
        return None

    async def find_one(
        self,
        collection: str,
        filter: dict,
        projection: dict | None = None,
        sort: list | None = None,
    ) -> dict | None:
        if collection != "job_execution_records":
            return None
        key = (str(filter.get("job_name")), str(filter.get("target_trade_date")))
        return self.executions.get(key)


class CoreIntegrityTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_mongo_manager = core_integrity.mongo_manager
        self.original_data_source_manager = core_integrity.data_source_manager
        self.original_market_now = core_integrity.market_now
        self.original_market_today_str = core_integrity.market_today_str
        self.original_check_after = core_integrity.settings.data_sync.core_ready_check_after_local_time
        self.original_expected_after = core_integrity.settings.data_sync.core_ready_expected_after_local_time
        self.original_fail_after = core_integrity.settings.data_sync.core_ready_fail_after_local_time
        self.original_ready_after = core_integrity.settings.data_sync.core_ready_after_local_time

    async def asyncTearDown(self) -> None:
        core_integrity.mongo_manager = self.original_mongo_manager
        core_integrity.data_source_manager = self.original_data_source_manager
        core_integrity.market_now = self.original_market_now
        core_integrity.market_today_str = self.original_market_today_str
        core_integrity.settings.data_sync.core_ready_check_after_local_time = self.original_check_after
        core_integrity.settings.data_sync.core_ready_expected_after_local_time = self.original_expected_after
        core_integrity.settings.data_sync.core_ready_fail_after_local_time = self.original_fail_after
        core_integrity.settings.data_sync.core_ready_after_local_time = self.original_ready_after

    async def test_limit_list_can_be_ready_with_successful_zero_row_execution(self) -> None:
        trade_date = "20260527"
        counts = {
            f"stock_daily:{trade_date}": 90,
            f"daily_basic:{trade_date}": 90,
            f"index_daily:{trade_date}": 3,
            f"moneyflow_industry:{trade_date}": 1,
            f"moneyflow_concept:{trade_date}": 1,
            f"daily_stats:{trade_date}": 1,
            f"market_statistics_cache:{trade_date}": 9,
        }
        executions = {
            ("limit_list", trade_date): {
                "status": "success",
                "started_at": datetime(2026, 5, 27, 16, 10),
                "count": 0,
                "resource_class": "core",
            }
        }
        core_integrity.mongo_manager = _FakeMongoManager(counts=counts, executions=executions)
        core_integrity.data_source_manager = _FakeDataSourceManager(trade_date)
        core_integrity.market_today_str = lambda: "20260528"

        result = await core_integrity.build_core_integrity_overview(days=1)

        self.assertTrue(result["latest_ready"])
        entry = result["overview"][0]
        limit_status = next(item for item in entry["datasets"] if item["dataset"] == "limit_list")
        self.assertTrue(limit_status["ok"])
        self.assertEqual(limit_status["execution"]["status"], "success")

    async def test_low_stock_coverage_is_warning_and_blocks_ready(self) -> None:
        trade_date = "20260527"
        counts = {
            f"stock_daily:{trade_date}": 20,
            f"daily_basic:{trade_date}": 90,
            f"index_daily:{trade_date}": 3,
            f"moneyflow_industry:{trade_date}": 1,
            f"moneyflow_concept:{trade_date}": 1,
            f"limit_list:{trade_date}": 1,
            f"daily_stats:{trade_date}": 1,
            f"market_statistics_cache:{trade_date}": 9,
        }
        core_integrity.mongo_manager = _FakeMongoManager(counts=counts)
        core_integrity.data_source_manager = _FakeDataSourceManager(trade_date)
        core_integrity.market_today_str = lambda: "20260528"

        result = await core_integrity.build_core_integrity_overview(days=1)

        self.assertFalse(result["latest_ready"])
        entry = result["overview"][0]
        self.assertIn("stock_daily", entry["warning_datasets"])
        stock_status = next(item for item in entry["datasets"] if item["dataset"] == "stock_daily")
        self.assertEqual(stock_status["state"], "warning")
        self.assertEqual(stock_status["recoverability"]["mode"], "full")
        self.assertEqual(
            result["core_dataset_recoverability"]["stock_daily"]["severity_on_missing"],
            "warning",
        )

    async def test_latest_trade_date_before_sync_window_is_waiting_not_blocking(self) -> None:
        trade_date = "20260528"
        core_integrity.mongo_manager = _FakeMongoManager(counts={})
        core_integrity.data_source_manager = _FakeDataSourceManager(trade_date)
        core_integrity.market_today_str = lambda: trade_date
        core_integrity.market_now = lambda: datetime(2026, 5, 28, 10, 0)
        self._set_sla_times()

        result = await core_integrity.build_core_integrity_overview(days=1)

        self.assertFalse(result["latest_ready"])
        self.assertTrue(result["latest_effectively_ready"])
        self.assertEqual(result["latest_trade_date_sla_phase"], "waiting_window")
        self.assertEqual(result["blocking_incomplete_trade_dates"], [])
        entry = result["overview"][0]
        self.assertTrue(entry["awaiting_sync_window"])
        self.assertFalse(entry["recovery_allowed"])
        self.assertTrue(all(item["state"] == "waiting_window" for item in entry["datasets"]))

    async def test_latest_trade_date_inside_syncing_window_is_pending_not_blocking(self) -> None:
        trade_date = "20260528"
        core_integrity.mongo_manager = _FakeMongoManager(counts={})
        core_integrity.data_source_manager = _FakeDataSourceManager(trade_date)
        core_integrity.market_today_str = lambda: trade_date
        core_integrity.market_now = lambda: datetime(2026, 5, 28, 15, 45)
        self._set_sla_times()

        result = await core_integrity.build_core_integrity_overview(days=1)

        self.assertFalse(result["latest_ready"])
        self.assertTrue(result["latest_effectively_ready"])
        self.assertEqual(result["latest_trade_date_sla_phase"], "syncing_window")
        self.assertEqual(result["blocking_incomplete_trade_dates"], [])
        entry = result["overview"][0]
        self.assertFalse(entry["awaiting_sync_window"])
        self.assertTrue(entry["syncing_window"])
        self.assertTrue(entry["recovery_allowed"])
        self.assertTrue(all(item["state"] == "syncing_window" for item in entry["datasets"]))

    async def test_latest_trade_date_after_expected_time_is_blocking_missing(self) -> None:
        trade_date = "20260528"
        core_integrity.mongo_manager = _FakeMongoManager(counts={})
        core_integrity.data_source_manager = _FakeDataSourceManager(trade_date)
        core_integrity.market_today_str = lambda: trade_date
        core_integrity.market_now = lambda: datetime(2026, 5, 28, 16, 30)
        self._set_sla_times()

        result = await core_integrity.build_core_integrity_overview(days=1)

        self.assertFalse(result["latest_ready"])
        self.assertFalse(result["latest_effectively_ready"])
        self.assertEqual(result["latest_trade_date_sla_phase"], "overdue")
        self.assertEqual(result["blocking_incomplete_trade_dates"], [trade_date])
        entry = result["overview"][0]
        self.assertIn("stock_daily", entry["missing_datasets"])
        self.assertTrue(any(item["state"] == "missing" for item in entry["datasets"]))

    async def test_latest_trade_date_after_fail_time_marks_missing_as_failed(self) -> None:
        trade_date = "20260528"
        core_integrity.mongo_manager = _FakeMongoManager(counts={})
        core_integrity.data_source_manager = _FakeDataSourceManager(trade_date)
        core_integrity.market_today_str = lambda: trade_date
        core_integrity.market_now = lambda: datetime(2026, 5, 28, 17, 5)
        self._set_sla_times()

        result = await core_integrity.build_core_integrity_overview(days=1)

        self.assertEqual(result["latest_trade_date_sla_phase"], "failed")
        entry = result["overview"][0]
        self.assertIn("stock_daily", entry["failed_datasets"])
        self.assertTrue(all(item["state"] == "failed" for item in entry["datasets"]))

    @staticmethod
    def _set_sla_times() -> None:
        core_integrity.settings.data_sync.core_ready_check_after_local_time = "15:30"
        core_integrity.settings.data_sync.core_ready_expected_after_local_time = "16:10"
        core_integrity.settings.data_sync.core_ready_fail_after_local_time = "17:00"
        core_integrity.settings.data_sync.core_ready_after_local_time = "16:10"


if __name__ == "__main__":
    unittest.main()
