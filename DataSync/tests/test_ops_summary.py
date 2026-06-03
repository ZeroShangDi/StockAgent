from pathlib import Path
import sys
import unittest


DATASYNC_ROOT = Path(__file__).resolve().parents[1]
if str(DATASYNC_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASYNC_ROOT))

from nodes.data_sync.services.ops_summary import (
    build_probe_checks,
    derive_operational_status,
)


class OpsSummaryProbeTest(unittest.TestCase):
    def test_probe_checks_are_stable_for_healthy_summary(self) -> None:
        checks = build_probe_checks(
            summary_success=True,
            sync_targets={"primary": {"healthy": True}},
            core_integrity={"latest_effectively_ready": True, "recent_window_ready": True},
            unresolved_recent_failures={"count": 0},
            unresolved_recent_ops_events={"unresolved_warning_count": 0},
            data_source_runtime_stats={"core_degraded_entry_count": 0},
            core_job_runtime_summary={"outlier_job_count": 0},
            backfill_queue_status={"operational": True},
        )

        self.assertTrue(all(checks.values()))
        self.assertEqual(derive_operational_status(checks, []), "healthy")

    def test_operational_status_is_degraded_for_warning_alerts(self) -> None:
        checks = build_probe_checks(
            summary_success=True,
            sync_targets={"primary": {"healthy": True}},
            core_integrity={"latest_effectively_ready": True, "recent_window_ready": True},
            unresolved_recent_failures={"count": 0},
            unresolved_recent_ops_events={"unresolved_warning_count": 0},
            data_source_runtime_stats={"core_degraded_entry_count": 0},
            core_job_runtime_summary={"outlier_job_count": 0},
            backfill_queue_status={"operational": True},
        )

        status = derive_operational_status(
            checks,
            [{"severity": "warning", "code": "backfill_queue_failed_jobs"}],
        )

        self.assertEqual(status, "degraded")

    def test_operational_status_is_critical_for_primary_or_core_failure(self) -> None:
        primary_down = build_probe_checks(
            summary_success=True,
            sync_targets={"primary": {"healthy": False}},
            core_integrity={"latest_effectively_ready": True, "recent_window_ready": True},
            unresolved_recent_failures={"count": 0},
            unresolved_recent_ops_events={"unresolved_warning_count": 0},
            data_source_runtime_stats={"core_degraded_entry_count": 0},
            core_job_runtime_summary={"outlier_job_count": 0},
            backfill_queue_status={"operational": True},
        )
        core_not_ready = build_probe_checks(
            summary_success=True,
            sync_targets={"primary": {"healthy": True}},
            core_integrity={"latest_effectively_ready": False, "recent_window_ready": False},
            unresolved_recent_failures={"count": 0},
            unresolved_recent_ops_events={"unresolved_warning_count": 0},
            data_source_runtime_stats={"core_degraded_entry_count": 0},
            core_job_runtime_summary={"outlier_job_count": 0},
            backfill_queue_status={"operational": True},
        )

        self.assertEqual(derive_operational_status(primary_down, []), "critical")
        self.assertEqual(derive_operational_status(core_not_ready, []), "critical")

    def test_probe_checks_include_backfill_queue_operational_state(self) -> None:
        checks = build_probe_checks(
            summary_success=True,
            sync_targets={"primary": {"healthy": True}},
            core_integrity={"latest_effectively_ready": True, "recent_window_ready": True},
            unresolved_recent_failures={"count": 0},
            unresolved_recent_ops_events={"unresolved_warning_count": 0},
            data_source_runtime_stats={"core_degraded_entry_count": 0},
            core_job_runtime_summary={"outlier_job_count": 0},
            backfill_queue_status={"operational": False},
        )

        self.assertFalse(checks["backfill_queue_operational"])
        self.assertEqual(derive_operational_status(checks, []), "degraded")


if __name__ == "__main__":
    unittest.main()
