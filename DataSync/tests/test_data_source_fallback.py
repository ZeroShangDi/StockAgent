from pathlib import Path
import sys
import unittest


DATASYNC_ROOT = Path(__file__).resolve().parents[1]
if str(DATASYNC_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASYNC_ROOT))

from core.managers.data_source_manager import DataSourceChainError, DataSourceManager
from core.settings import settings


class _FakeAdapter:
    priority = 100

    def __init__(self, name: str, *, result=None, error: Exception | None = None):
        self.name = name
        self._result = result
        self._error = error

    async def is_available(self) -> bool:
        return True

    async def get_daily(self, trade_date: str | None = None, ts_code: str | None = None):
        if self._error:
            raise self._error
        return self._result


class DataSourceFallbackPolicyTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._settings = settings.data_sync
        self._original_overrides = self._settings.source_chain_overrides

    def tearDown(self) -> None:
        self._settings.source_chain_overrides = self._original_overrides

    def _manager(self, adapters: list[_FakeAdapter]) -> DataSourceManager:
        manager = DataSourceManager()
        manager._adapters = adapters
        manager._adapter_map = {adapter.name: adapter for adapter in adapters}
        manager.reset_call_stats()
        return manager

    async def test_full_market_daily_falls_back_and_records_chain(self) -> None:
        tushare = _FakeAdapter("tushare", error=RuntimeError("upstream down"))
        baostock = _FakeAdapter("baostock", result=[{"ts_code": "000001.SZ", "trade_date": "20260528"}])
        akshare = _FakeAdapter("akshare", result=[{"unused": True}])
        manager = self._manager([tushare, baostock, akshare])

        records, source = await manager.get_daily(trade_date="20260528")
        summary = manager.get_call_stats_summary()
        success_entry = next(
            item for item in summary["entries"]
            if item["adapter_name"] == "baostock"
        )

        self.assertEqual(source, "baostock")
        self.assertEqual(len(records), 1)
        self.assertEqual(success_entry["fallback_count"], 1)
        self.assertEqual(success_entry["last_fallback_from"], "tushare")
        self.assertEqual(success_entry["last_fallback_to"], "baostock")
        self.assertEqual(success_entry["last_source_chain_key"], "get_daily.full_market")
        self.assertEqual(success_entry["last_source_chain"][:3], ["tushare", "baostock", "akshare"])
        self.assertEqual(success_entry["last_attempted_sources"], ["tushare", "baostock"])

    async def test_source_chain_override_is_respected(self) -> None:
        self._settings.source_chain_overrides = "get_daily.full_market=akshare,baostock"
        tushare = _FakeAdapter("tushare", result=[{"source": "tushare"}])
        akshare = _FakeAdapter("akshare", result=[{"source": "akshare"}])
        baostock = _FakeAdapter("baostock", result=[{"source": "baostock"}])
        manager = self._manager([tushare, akshare, baostock])

        records, source = await manager.get_daily(trade_date="20260528")
        summary = manager.get_call_stats_summary()
        entry = summary["entries"][0]

        self.assertEqual(source, "akshare")
        self.assertEqual(records, [{"source": "akshare"}])
        self.assertEqual(entry["last_source_chain"], ["akshare", "baostock"])
        self.assertEqual(entry["last_attempted_sources"], ["akshare"])

    async def test_all_failed_sources_raise_chain_error(self) -> None:
        manager = self._manager([
            _FakeAdapter("tushare", error=RuntimeError("first failed")),
            _FakeAdapter("baostock", error=RuntimeError("second failed")),
        ])

        with self.assertRaises(DataSourceChainError) as ctx:
            await manager.get_daily(trade_date="20260528")

        self.assertEqual(ctx.exception.method_name, "get_daily")
        self.assertEqual(ctx.exception.source_chain, ["tushare", "baostock"])
        self.assertEqual([item["status"] for item in ctx.exception.outcomes], ["failed", "failed"])

    async def test_empty_results_remain_empty_not_chain_failure(self) -> None:
        manager = self._manager([
            _FakeAdapter("tushare", result=[]),
            _FakeAdapter("baostock", result=[]),
        ])

        records, source = await manager.get_daily(trade_date="20260528")

        self.assertIsNone(records)
        self.assertIsNone(source)


if __name__ == "__main__":
    unittest.main()
