from pathlib import Path
import json
import sys
import unittest


DATASYNC_ROOT = Path(__file__).resolve().parents[1]
if str(DATASYNC_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASYNC_ROOT))

from nodes.data_sync.node import DataSyncNode
from nodes.data_sync.tasks import market_weather as market_weather_task_module
from nodes.data_sync.tasks.market_weather import MarketWeatherTask
from src.analysis.coze_workflow_client import CozeWorkflowClient
from src.analysis.market_weather import MarketWeatherService
from core.managers.data_source_manager import data_source_manager


class FakeCozeClient:
    decode_json_like = CozeWorkflowClient.decode_json_like

    async def run(self, workflow_id, parameters=None):
        indicator = {
            "数据截止日期": parameters.get("date", "2026-05-28"),
            "市场温度指数": "72",
            "涨停溢价延续因子": "0.8",
            "趋势惯性累积因子": "0.7",
            "量价共振强度因子": "0.6",
            "市场广度扩散因子": "0.75",
            "多空动能极化因子": "0.8",
        }
        return {
            "code": 0,
            "data": json.dumps(
                {"getMarketIndicator": json.dumps(indicator, ensure_ascii=False)},
                ensure_ascii=False,
            ),
        }


class MarketWeatherServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_one_builds_normalized_record_and_signal(self) -> None:
        service = MarketWeatherService(workflow_id="workflow-id", client=FakeCozeClient())

        record = await service.fetch_one("20260528")

        self.assertEqual(record["trade_date"], "20260528")
        self.assertEqual(record["display_trade_date"], "2026-05-28")
        self.assertEqual(record["source"], "coze")
        self.assertEqual(record["workflow_id"], "workflow-id")
        self.assertEqual(record["temperature_index"], 72.0)
        self.assertIn(record["signal"]["做不做"], {"持筹", "积极"})
        self.assertIn("说明", record["signal"])


class MarketWeatherTaskTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_get_trade_calendar = data_source_manager.get_trade_calendar
        self.original_sync_trade_dates = market_weather_task_module.market_weather_service.sync_trade_dates

    async def asyncTearDown(self) -> None:
        data_source_manager.get_trade_calendar = self.original_get_trade_calendar
        market_weather_task_module.market_weather_service.sync_trade_dates = self.original_sync_trade_dates

    async def test_recover_trade_date_uses_trade_date_guard(self) -> None:
        async def fake_calendar(start_date: str, end_date: str):
            return ["20260528"], "calendar-source"

        async def fake_sync_trade_dates(trade_dates, overwrite=False):
            return {"requested": 1, "success": 1, "skipped": 0, "failed": 0, "errors": []}

        data_source_manager.get_trade_calendar = fake_calendar
        market_weather_task_module.market_weather_service.sync_trade_dates = fake_sync_trade_dates

        result = await MarketWeatherTask().recover_trade_date("20260528")

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["trade_date"], "20260528")
        self.assertEqual(result["source"], "coze_market_indicator")
        self.assertEqual(result["warnings"], [])

    async def test_invalid_recover_trade_date_is_skipped(self) -> None:
        result = await MarketWeatherTask().recover_trade_date("2026-05-28")

        self.assertTrue(result["success"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "invalid_trade_date")

    def test_market_weather_registers_in_conservative_profile_without_ready_gate(self) -> None:
        node = DataSyncNode()

        self.assertTrue(node._should_register_job("market_weather"))
        self.assertIn("market_weather", node.CORE_JOB_NAMES)
        self.assertNotIn("market_weather", node.CORE_READY_DATASETS)


if __name__ == "__main__":
    unittest.main()
