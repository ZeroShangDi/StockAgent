from pathlib import Path
import sys
import unittest


DATASYNC_ROOT = Path(__file__).resolve().parents[1]
if str(DATASYNC_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASYNC_ROOT))

from nodes.data_sync import node as data_sync_node
from nodes.data_sync.node import DataSyncNode


class _FakeJob:
    def __init__(self, name: str) -> None:
        self.name = name

    async def recover_trade_date(self, trade_date: str) -> dict:
        return {"success": True, "trade_date": trade_date, "count": 1}


class CoreGapRecoveryTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_integrity_builder = data_sync_node.build_core_integrity_overview
        self.node = DataSyncNode(node_id="data-sync-recovery-test", rpc_port=0)
        self.node._jobs = [_FakeJob(name) for name in self.node.CORE_READY_DATASETS]
        self.ops_events: list[dict] = []

        async def record_ops_event(**kwargs) -> None:
            self.ops_events.append(kwargs)

        self.node._record_ops_event = record_ops_event

    async def asyncTearDown(self) -> None:
        data_sync_node.build_core_integrity_overview = self.original_integrity_builder

    async def test_latest_recovery_reruns_from_first_missing_dataset(self) -> None:
        data_sync_node.build_core_integrity_overview = self._integrity_builder(
            self._entry(missing_from="daily_basic", ready=False),
            self._entry(ready=True),
        )
        calls: list[dict] = []

        async def run_job_with_lock(job, **kwargs):
            calls.append({"job_name": job.name, **kwargs})
            return {"success": True, "count": 1, "target_trade_date": "20260528"}

        self.node._run_job_with_lock = run_job_with_lock

        result = await self.node._recover_latest_core_gaps(trigger="unit_test")

        expected_order = self.node.CORE_READY_DATASETS[
            self.node.CORE_READY_DATASETS.index("daily_basic"):
        ]
        self.assertTrue(result["success"])
        self.assertTrue(result["recovered"])
        self.assertEqual(result["rerun_order"], expected_order)
        self.assertEqual([call["job_name"] for call in calls], expected_order)
        self.assertTrue(all(call["pipeline_name"] == "core_gap_recovery" for call in calls))
        self.assertEqual(result["completed_jobs"], expected_order)
        self.assertIsNone(result["failure_point"])
        self.assertEqual(self.ops_events[0]["details"]["completed_jobs"], expected_order)

    async def test_latest_recovery_stops_and_reports_failure_point(self) -> None:
        data_sync_node.build_core_integrity_overview = self._integrity_builder(
            self._entry(missing_from="daily_basic", ready=False),
            self._entry(missing_from="moneyflow_industry", ready=False),
        )
        calls: list[str] = []

        async def run_job_with_lock(job, **kwargs):
            calls.append(job.name)
            if job.name == "moneyflow_industry":
                return {"success": False, "error": "upstream timeout", "reason": "timeout"}
            return {"success": True, "count": 1, "target_trade_date": "20260528"}

        self.node._run_job_with_lock = run_job_with_lock

        result = await self.node._recover_latest_core_gaps(trigger="unit_test")

        self.assertEqual(calls, ["daily_basic", "moneyflow_industry"])
        self.assertEqual(result["completed_jobs"], ["daily_basic"])
        self.assertEqual(
            result["failure_point"],
            {
                "job_name": "moneyflow_industry",
                "error": "upstream timeout",
                "reason": "timeout",
                "skipped": False,
            },
        )
        self.assertEqual(self.ops_events[0]["details"]["failure_point"]["job_name"], "moneyflow_industry")

    async def test_latest_recovery_skips_before_sync_window(self) -> None:
        data_sync_node.build_core_integrity_overview = self._integrity_builder(
            self._entry(missing_from="stock_daily", awaiting_sync_window=True, ready=False),
        )
        calls: list[str] = []

        async def run_job_with_lock(job, **kwargs):
            calls.append(job.name)
            return {"success": True}

        self.node._run_job_with_lock = run_job_with_lock

        result = await self.node._recover_latest_core_gaps(trigger="unit_test")

        self.assertTrue(result["success"])
        self.assertFalse(result["recovered"])
        self.assertEqual(result["reason"], "awaiting_sync_window")
        self.assertEqual(calls, [])
        self.assertEqual(self.ops_events, [])

    async def test_recent_recovery_records_recovered_skipped_and_failed_dates(self) -> None:
        data_sync_node.build_core_integrity_overview = self._integrity_builder(
            self._overview(
                self._entry(trade_date="20260526", missing_from="daily_basic", ready=False),
                self._entry(trade_date="20260527", missing_from="index_daily", ready=False),
                self._entry(trade_date="20260528", missing_from="stock_daily", awaiting_sync_window=True, ready=False),
                latest_trade_date="20260528",
            ),
            self._overview(
                self._entry(trade_date="20260526", ready=True),
                self._entry(trade_date="20260527", missing_from="index_daily", ready=False),
                self._entry(trade_date="20260528", missing_from="stock_daily", awaiting_sync_window=True, ready=False),
                latest_trade_date="20260528",
            ),
        )
        targeted_calls: list[tuple[str, str]] = []

        async def recover_job_trade_date(dataset, trade_date, **kwargs):
            targeted_calls.append((trade_date, dataset))
            if trade_date == "20260527" and dataset == "index_daily":
                return {
                    "success": False,
                    "result": {
                        "success": False,
                        "reason": "timeout",
                        "error": "upstream timeout",
                    },
                }
            return {"success": True, "result": {"success": True, "count": 1}}

        self.node._recover_job_trade_date = recover_job_trade_date

        result = await self.node._recover_recent_core_gaps(trigger="unit_test", days=3)

        self.assertTrue(result["success"])
        self.assertEqual(result["recovered_trade_dates"], ["20260526"])
        self.assertEqual(result["skipped_trade_dates"], [{"trade_date": "20260528", "reason": "awaiting_sync_window"}])
        self.assertEqual(result["failed_trade_dates"][0]["trade_date"], "20260527")
        self.assertEqual(result["failed_trade_dates"][0]["failure_point"]["dataset"], "index_daily")
        expected_20260526_order = [
            ("20260526", dataset)
            for dataset in self.node.CORE_READY_DATASETS[
                self.node.CORE_READY_DATASETS.index("daily_basic"):
            ]
        ]
        self.assertEqual(targeted_calls, [("20260527", "index_daily"), *expected_20260526_order])
        self.assertEqual(self.ops_events[0]["severity"], "warning")
        self.assertEqual(self.ops_events[0]["details"]["recovered_trade_dates"], ["20260526"])
        self.assertEqual(self.ops_events[0]["details"]["failed_trade_dates"][0]["trade_date"], "20260527")

    def _entry(
        self,
        *,
        trade_date: str = "20260528",
        missing_from: str | None = None,
        ready: bool = False,
        awaiting_sync_window: bool = False,
    ) -> dict:
        missing_index = (
            self.node.CORE_READY_DATASETS.index(missing_from)
            if missing_from in self.node.CORE_READY_DATASETS
            else len(self.node.CORE_READY_DATASETS)
        )
        datasets = []
        for index, dataset in enumerate(self.node.CORE_READY_DATASETS):
            ok = ready or index < missing_index
            datasets.append(
                {
                    "dataset": dataset,
                    "ok": ok,
                    "state": "ready" if ok else ("waiting_window" if awaiting_sync_window else "missing"),
                }
            )
        return {
            "trade_date": trade_date,
            "ready": ready,
            "awaiting_sync_window": awaiting_sync_window,
            "datasets": datasets,
        }

    @staticmethod
    def _overview(*entries: dict, latest_trade_date: str | None = None) -> dict:
        resolved_latest = latest_trade_date or (entries[-1]["trade_date"] if entries else "")
        return {
            "success": True,
            "latest_trade_date": resolved_latest,
            "overview": list(entries),
        }

    def _integrity_builder(self, *items: dict):
        calls = {"count": 0}

        async def build_core_integrity_overview(days: int = 1) -> dict:
            index = min(calls["count"], len(items) - 1)
            calls["count"] += 1
            item = items[index]
            if "overview" in item:
                return item
            return self._overview(item, latest_trade_date=item["trade_date"])

        return build_core_integrity_overview


if __name__ == "__main__":
    unittest.main()
