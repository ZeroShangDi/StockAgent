from pathlib import Path
import sys
import unittest


DATASYNC_ROOT = Path(__file__).resolve().parents[1]
if str(DATASYNC_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASYNC_ROOT))

from nodes.data_sync.node import DataSyncNode


class DataSyncJobResourceClassTest(unittest.TestCase):
    def setUp(self) -> None:
        self.node = DataSyncNode(node_id="data-sync-resource-test", rpc_port=0)
        self.settings = self.node.settings.data_sync
        self.original_profile = self.settings.profile
        self.original_enabled_jobs = self.settings.enabled_jobs
        self.original_disabled_jobs = self.settings.disabled_jobs

    def tearDown(self) -> None:
        self.settings.profile = self.original_profile
        self.settings.enabled_jobs = self.original_enabled_jobs
        self.settings.disabled_jobs = self.original_disabled_jobs

    def test_conservative_profile_registers_only_core_jobs(self) -> None:
        self.settings.profile = "conservative"
        self.settings.enabled_jobs = None
        self.settings.disabled_jobs = None

        self.node._register_jobs()
        job_names = {job.name for job in self.node._jobs}

        self.assertIn("stock_daily", job_names)
        self.assertIn("market_statistics_cache", job_names)
        self.assertNotIn("hot_news", job_names)
        self.assertNotIn("fina_indicator", job_names)
        self.assertNotIn("ths_sector", job_names)
        self.assertNotIn("review_data", job_names)
        self.assertTrue(job_names.issubset(self.node.CORE_JOB_NAMES))

    def test_full_profile_keeps_non_core_jobs_classified(self) -> None:
        self.settings.profile = "full"
        self.settings.enabled_jobs = None
        self.settings.disabled_jobs = None

        self.node._register_jobs()
        resource_classes = {
            job.name: getattr(job, "resource_class", None)
            for job in self.node._jobs
        }

        self.assertEqual(resource_classes["stock_daily"], "core")
        self.assertEqual(resource_classes["hot_news"], "background")
        self.assertEqual(resource_classes["review_data"], "background")
        self.assertEqual(resource_classes["fina_indicator"], "heavy")
        self.assertEqual(resource_classes["ths_sector"], "heavy")

    def test_enabled_jobs_override_profile_and_disabled_jobs_still_apply(self) -> None:
        self.settings.profile = "conservative"
        self.settings.enabled_jobs = "hot_news,stock_daily"
        self.settings.disabled_jobs = "stock_daily"

        self.node._register_jobs()
        job_names = {job.name for job in self.node._jobs}

        self.assertEqual(job_names, {"hot_news"})
        self.assertEqual(getattr(self.node._jobs[0], "resource_class", None), "background")


if __name__ == "__main__":
    unittest.main()
