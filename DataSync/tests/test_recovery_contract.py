from pathlib import Path
import sys
import unittest


DATASYNC_ROOT = Path(__file__).resolve().parents[1]
if str(DATASYNC_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASYNC_ROOT))

from core.managers.data_source_manager import data_source_manager
from nodes.data_sync.services import recovery_contract
from nodes.data_sync.services.recovery_contract import (
    build_recovery_warnings,
    compact_sources,
    extract_sources_from_parallel_result,
    primary_source,
    skipped_recovery_result,
    validate_recovery_trade_date,
)
from nodes.data_sync.collectors.stock.daily import StockDailyCollector
from nodes.data_sync.collectors.stock.daily_basic import DailyBasicCollector
from nodes.data_sync.collectors.stock.index_daily import IndexDailyCollector
from nodes.data_sync.collectors.stock.limit_list import LimitListCollector
from nodes.data_sync.collectors.stock.moneyflow_concept import MoneyflowConceptCollector
from nodes.data_sync.collectors.stock.moneyflow_industry import MoneyflowIndustryCollector
from nodes.data_sync.tasks.daily_stats import DailyStatsTask
from nodes.data_sync.tasks.market_statistics_cache import MarketStatisticsCacheTask
from nodes.data_sync.tasks.market_weather import MarketWeatherTask


class RecoveryContractHelperTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_get_trade_calendar = data_source_manager.get_trade_calendar

    async def asyncTearDown(self) -> None:
        data_source_manager.get_trade_calendar = self.original_get_trade_calendar

    async def test_invalid_trade_date_is_a_successful_skip(self) -> None:
        guard = await validate_recovery_trade_date("2026-05-28")

        self.assertFalse(guard["ok"])
        self.assertTrue(guard["success"])
        self.assertTrue(guard["skipped"])
        self.assertEqual(guard["reason"], "invalid_trade_date")

        result = skipped_recovery_result("stock_daily", guard)
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["reason"], "invalid_trade_date")

    async def test_non_trade_date_is_a_successful_skip(self) -> None:
        async def fake_calendar(start_date: str, end_date: str):
            return [], "calendar-source"

        data_source_manager.get_trade_calendar = fake_calendar

        guard = await validate_recovery_trade_date("20260530")

        self.assertFalse(guard["ok"])
        self.assertTrue(guard["success"])
        self.assertEqual(guard["source"], "calendar-source")
        self.assertEqual(guard["reason"], "non_trade_date")

    async def test_calendar_failure_is_retryable_failure(self) -> None:
        async def fake_calendar(start_date: str, end_date: str):
            raise RuntimeError("calendar timeout")

        data_source_manager.get_trade_calendar = fake_calendar

        guard = await validate_recovery_trade_date("20260528")
        result = skipped_recovery_result("index_daily", guard)

        self.assertFalse(guard["success"])
        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "trade_calendar_error")
        self.assertIn("calendar timeout", result["error"])

    async def test_valid_trade_date_keeps_calendar_source(self) -> None:
        async def fake_calendar(start_date: str, end_date: str):
            return ["20260528"], "tushare"

        data_source_manager.get_trade_calendar = fake_calendar

        guard = await validate_recovery_trade_date("20260528")

        self.assertTrue(guard["ok"])
        self.assertEqual(guard["trade_date"], "20260528")
        self.assertEqual(guard["source"], "tushare")

    async def test_imported_singleton_is_same_object(self) -> None:
        self.assertIs(recovery_contract.data_source_manager, data_source_manager)


class RecoveryContractResultTest(unittest.TestCase):
    def test_sources_are_compacted_and_primary_source_is_explicit(self) -> None:
        sources = compact_sources(["tushare", "", None, ["akshare", "tushare"]])

        self.assertEqual(sources, ["tushare", "akshare"])
        self.assertEqual(primary_source(sources), "multiple")
        self.assertEqual(primary_source(["tushare"]), "tushare")

    def test_extract_sources_from_parallel_result(self) -> None:
        result = {
            "results": [
                {"success": True, "result": {"source": "tushare"}},
                {"success": True, "result": {"sources": ["akshare", "tushare"]}},
                {"success": False, "error": "timeout"},
            ]
        }

        self.assertEqual(
            extract_sources_from_parallel_result(result, default="unknown"),
            ["tushare", "akshare"],
        )

    def test_warnings_include_failed_items(self) -> None:
        warnings = build_recovery_warnings(
            {"warnings": ["calendar verified"]},
            failed_count=1,
            failed_items=[{"item_id": "399001.SZ", "error": "timeout"}],
        )

        self.assertEqual(warnings[0], "calendar verified")
        self.assertIn("1 recovery item(s) failed", warnings)
        self.assertIn("399001.SZ: timeout", warnings)


class CoreRecoveryContractCoverageTest(unittest.TestCase):
    def test_core_recovery_methods_use_trade_date_guard(self) -> None:
        import inspect

        core_classes = [
            StockDailyCollector,
            IndexDailyCollector,
            DailyBasicCollector,
            MoneyflowIndustryCollector,
            MoneyflowConceptCollector,
            LimitListCollector,
            DailyStatsTask,
            MarketStatisticsCacheTask,
            MarketWeatherTask,
        ]

        for cls in core_classes:
            with self.subTest(cls=cls.__name__):
                source = inspect.getsource(cls.recover_trade_date)
                self.assertIn("validate_recovery_trade_date", source)
                self.assertIn("skipped_recovery_result", source)


if __name__ == "__main__":
    unittest.main()
