from pathlib import Path
import sys
import unittest


DATASYNC_ROOT = Path(__file__).resolve().parents[1]
if str(DATASYNC_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASYNC_ROOT))

from main import _build_probe_result, _derive_ready_probe_result


class DataSyncProbeCommandTest(unittest.TestCase):
    def test_health_probe_result_requires_all_checks(self) -> None:
        result = _build_probe_result(
            probe="health",
            checks={"config": True, "redis": True, "mongo": False},
            details={"mongo_error": "timeout"},
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["probe"], "health")
        self.assertEqual(result["details"]["mongo_error"], "timeout")

    def test_ready_probe_accepts_ready_marker_without_recent_failures(self) -> None:
        result = _derive_ready_probe_result(
            {"status": "ready", "trade_date": "20260528"},
            [],
        )

        self.assertTrue(result["success"])
        self.assertTrue(result["checks"]["core_ready_marker"])
        self.assertTrue(result["checks"]["recent_core_failures"])
        self.assertEqual(result["details"]["marker_trade_date"], "20260528")

    def test_ready_probe_fails_when_marker_missing(self) -> None:
        result = _derive_ready_probe_result(None, [])

        self.assertFalse(result["success"])
        self.assertFalse(result["checks"]["core_ready_marker"])
        self.assertEqual(result["details"]["marker_status"], "missing")

    def test_ready_probe_fails_when_recent_core_failures_exist(self) -> None:
        result = _derive_ready_probe_result(
            {"status": "ready", "trade_date": "20260528"},
            [{"job_name": "stock_daily", "status": "failed"}],
        )

        self.assertFalse(result["success"])
        self.assertFalse(result["checks"]["recent_core_failures"])
        self.assertEqual(result["details"]["recent_failure_count"], 1)


if __name__ == "__main__":
    unittest.main()
