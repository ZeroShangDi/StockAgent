from pathlib import Path
import asyncio
import sys
import unittest


DATASYNC_ROOT = Path(__file__).resolve().parents[1]
if str(DATASYNC_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASYNC_ROOT))

from nodes.data_sync.collectors.stock.daily import StockDailyCollector
from nodes.data_sync.node import DataSyncNode


class CapabilityManifestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.node = DataSyncNode(node_id="data-sync-capability-test", rpc_port=0)
        self.settings = self.node.settings.data_sync
        self.original_profile = self.settings.profile
        self.original_enabled_jobs = self.settings.enabled_jobs
        self.original_disabled_jobs = self.settings.disabled_jobs

    def tearDown(self) -> None:
        self.settings.profile = self.original_profile
        self.settings.enabled_jobs = self.original_enabled_jobs
        self.settings.disabled_jobs = self.original_disabled_jobs

    def test_job_manifest_contains_static_capabilities_only(self) -> None:
        manifest = StockDailyCollector().capability_manifest(resource_class="core")

        self.assertEqual(manifest["name"], "stock_daily")
        self.assertEqual(manifest["dataset_name"], "stock_daily")
        self.assertEqual(manifest["resource_class"], "core")
        self.assertEqual(manifest["target_collections"], ["stock_daily"])
        self.assertIn("trade_calendar", manifest["dependencies"])
        self.assertTrue(manifest["supports_recover_trade_date"])
        self.assertTrue(manifest["supports_backfill"])
        self.assertEqual(manifest["recoverability"]["mode"], "full")
        self.assertEqual(manifest["recoverability"]["severity_on_missing"], "warning")
        self.assertNotIn("last_run", manifest)
        self.assertNotIn("last_result", manifest)

    def test_conservative_manifest_exports_core_capabilities(self) -> None:
        self.settings.profile = "conservative"
        self.settings.enabled_jobs = None
        self.settings.disabled_jobs = None

        manifest = self.node.get_capability_manifest()
        capability_by_name = {
            item["name"]: item
            for item in manifest["capabilities"]
        }

        self.assertTrue(manifest["success"])
        self.assertEqual(set(capability_by_name), self.node.CORE_JOB_NAMES)
        self.assertIn("market_weather", capability_by_name)
        self.assertNotIn("market_weather", manifest["core_ready_datasets"])
        self.assertNotIn("hot_news", capability_by_name)
        self.assertEqual(capability_by_name["market_statistics_cache"]["target_collections"], ["market_statistics_cache"])
        self.assertEqual(capability_by_name["market_weather"]["dependencies"], ["coze_market_indicator_workflow"])

    def test_registered_manifest_uses_registered_jobs(self) -> None:
        self.settings.profile = "full"
        self.settings.enabled_jobs = None
        self.settings.disabled_jobs = None

        self.node._register_jobs()
        manifest = self.node.get_capability_manifest(registered_only=True)
        capability_by_name = {
            item["name"]: item
            for item in manifest["capabilities"]
        }

        self.assertIn("hot_news", capability_by_name)
        self.assertIn("fina_indicator", capability_by_name)
        self.assertEqual(capability_by_name["hot_news"]["resource_class"], "background")
        self.assertEqual(capability_by_name["hot_news"]["recoverability"]["mode"], "none")
        self.assertEqual(capability_by_name["hot_news"]["recoverability"]["severity_on_missing"], "warning")
        self.assertEqual(capability_by_name["fina_indicator"]["resource_class"], "heavy")
        self.assertGreater(manifest["count"], len(self.node.CORE_JOB_NAMES))

    def test_failure_event_severity_uses_recoverability(self) -> None:
        self.settings.profile = "full"
        self.settings.enabled_jobs = None
        self.settings.disabled_jobs = None
        self.node._register_jobs()

        hot_news = self.node._get_job("hot_news")
        stock_daily = self.node._get_job("stock_daily")

        self.assertIsNotNone(hot_news)
        self.assertIsNotNone(stock_daily)
        self.assertEqual(self.node._get_failure_ops_event_severity(hot_news, "background"), "warning")
        self.assertEqual(self.node._get_failure_ops_event_severity(stock_daily, "core"), "warning")

    def test_rpc_handler_returns_capability_manifest(self) -> None:
        self.settings.profile = "conservative"
        self.settings.enabled_jobs = None
        self.settings.disabled_jobs = None

        result = asyncio.run(
            self.node._handle_get_data_capabilities({"registered_only": False})
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["core_ready_marker"], self.node.CORE_READY_MARKER)
        self.assertEqual(result["count"], len(self.node.CORE_JOB_NAMES))


if __name__ == "__main__":
    unittest.main()
