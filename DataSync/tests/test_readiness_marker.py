from datetime import datetime
from pathlib import Path
import sys
import unittest


DATASYNC_ROOT = Path(__file__).resolve().parents[1]
if str(DATASYNC_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASYNC_ROOT))

from nodes.data_sync import node as data_sync_node
from nodes.data_sync.node import DataSyncNode


class _FakeMongoManager:
    def __init__(self) -> None:
        self.marker: dict | None = None

    async def get_last_sync_date(self, sync_type: str) -> str | None:
        return None

    async def upsert_readiness_marker(self, **kwargs) -> None:
        self.marker = kwargs


class ReadinessMarkerContractTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_mongo_manager = data_sync_node.mongo_manager
        self.original_integrity_builder = data_sync_node.build_core_integrity_overview
        self.fake_mongo = _FakeMongoManager()
        data_sync_node.mongo_manager = self.fake_mongo
        self.node = DataSyncNode(node_id="data-sync-marker-test", rpc_port=0)

    async def asyncTearDown(self) -> None:
        data_sync_node.mongo_manager = self.original_mongo_manager
        data_sync_node.build_core_integrity_overview = self.original_integrity_builder

    async def test_ready_marker_contract_for_ready_status(self) -> None:
        data_sync_node.build_core_integrity_overview = self._integrity_builder(
            {
                "trade_date": "20260527",
                "ready": True,
                "expected_ready": True,
                "awaiting_sync_window": False,
                "missing_datasets": [],
                "warning_datasets": [],
                "datasets": [
                    {"dataset": "stock_daily", "sync_date": "20260527", "ok": True, "state": "ready"},
                    {"dataset": "index_daily", "sync_date": "20260527", "ok": True, "state": "ready"},
                ],
            }
        )

        await self.node._refresh_core_ready_marker(
            "20260527",
            source="unit_test",
        )

        marker = self.fake_mongo.marker
        self.assertEqual(marker["status"], "ready")
        self.assertIsInstance(marker["ready_at"], datetime)
        self.assertEqual(marker["ready_datasets"], ["stock_daily", "index_daily"])
        self.assertEqual(marker["pending_datasets"], [])
        self.assertEqual(marker["warnings"], [])
        self.assertIsInstance(marker["last_checked_at"], datetime)
        self.assertEqual(marker["details"]["ready_datasets"], ["stock_daily", "index_daily"])

    async def test_marker_contract_for_waiting_window_status(self) -> None:
        data_sync_node.build_core_integrity_overview = self._integrity_builder(
            {
                "trade_date": "20260528",
                "ready": False,
                "expected_ready": False,
                "awaiting_sync_window": True,
                "missing_datasets": ["stock_daily"],
                "warning_datasets": [],
                "datasets": [
                    {
                        "dataset": "stock_daily",
                        "sync_date": None,
                        "ok": False,
                        "state": "waiting_window",
                        "reason": "awaiting configured core sync window",
                    },
                ],
            }
        )

        await self.node._refresh_core_ready_marker(
            "20260528",
            source="unit_test",
        )

        marker = self.fake_mongo.marker
        self.assertEqual(marker["status"], "waiting_window")
        self.assertIsNone(marker["ready_at"])
        self.assertEqual(marker["pending_datasets"], ["stock_daily"])
        self.assertEqual(marker["details"]["missing_datasets"], ["stock_daily"])
        self.assertTrue(marker["details"]["awaiting_sync_window"])

    async def test_marker_contract_for_degraded_status_with_warnings(self) -> None:
        data_sync_node.build_core_integrity_overview = self._integrity_builder(
            {
                "trade_date": "20260527",
                "ready": False,
                "expected_ready": True,
                "awaiting_sync_window": False,
                "missing_datasets": [],
                "warning_datasets": ["stock_daily"],
                "datasets": [
                    {"dataset": "index_daily", "sync_date": "20260527", "ok": True, "state": "ready"},
                    {
                        "dataset": "stock_daily",
                        "sync_date": "20260527",
                        "ok": False,
                        "state": "warning",
                        "reason": "coverage=20.00%, threshold=85%",
                        "count": 20,
                        "expected_count": 100,
                    },
                ],
            }
        )

        await self.node._refresh_core_ready_marker(
            "20260527",
            source="unit_test",
        )

        marker = self.fake_mongo.marker
        self.assertEqual(marker["status"], "degraded")
        self.assertIsNone(marker["ready_at"])
        self.assertEqual(marker["ready_datasets"], ["index_daily"])
        self.assertEqual(marker["pending_datasets"], ["stock_daily"])
        self.assertEqual(marker["warnings"][0]["dataset"], "stock_daily")
        self.assertEqual(marker["details"]["warning_datasets"], ["stock_daily"])

    async def test_marker_contract_for_failed_status_after_sla_failure_time(self) -> None:
        data_sync_node.build_core_integrity_overview = self._integrity_builder(
            {
                "trade_date": "20260528",
                "ready": False,
                "expected_ready": True,
                "awaiting_sync_window": False,
                "syncing_window": False,
                "sla_phase": "failed",
                "missing_datasets": [],
                "warning_datasets": [],
                "failed_datasets": ["stock_daily"],
                "datasets": [
                    {
                        "dataset": "stock_daily",
                        "sync_date": None,
                        "ok": False,
                        "state": "failed",
                        "reason": "core dataset still missing after configured failure alert time",
                    },
                ],
            }
        )

        await self.node._refresh_core_ready_marker(
            "20260528",
            source="unit_test",
        )

        marker = self.fake_mongo.marker
        self.assertEqual(marker["status"], "failed")
        self.assertIsNone(marker["ready_at"])
        self.assertEqual(marker["pending_datasets"], ["stock_daily"])
        self.assertEqual(marker["details"]["sla_phase"], "failed")
        self.assertEqual(marker["details"]["failed_datasets"], ["stock_daily"])

    @staticmethod
    def _integrity_builder(entry: dict):
        async def build_core_integrity_overview(days: int = 10) -> dict:
            return {
                "success": True,
                "overview": [entry],
            }

        return build_core_integrity_overview


if __name__ == "__main__":
    unittest.main()
