from pathlib import Path
import os
import sys
import unittest


DATASYNC_ROOT = Path(__file__).resolve().parents[1]
if str(DATASYNC_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASYNC_ROOT))

from core.settings import CozeSettings, DataSyncSettings, MongoSettings, RedisSettings


class DataSyncConservativeDefaultsTest(unittest.TestCase):
    def test_datasync_defaults_are_server_conservative_without_env_file(self) -> None:
        settings = DataSyncSettings(_env_file=None)

        self.assertEqual(settings.profile, "conservative")
        self.assertFalse(settings.run_initial_sync)
        self.assertEqual(settings.max_running_jobs, 1)
        self.assertEqual(settings.max_parallel_collect_concurrency, 2)
        self.assertEqual(settings.job_timeout_seconds, 1200)
        self.assertEqual(settings.lock_timeout_seconds, 1200)
        self.assertEqual(settings.scheduler_misfire_grace_seconds, 300)
        self.assertTrue(settings.prevent_initial_history_sync)
        self.assertEqual(settings.initial_backfill_days, 5)
        self.assertEqual(settings.backfill_window_start, "00:00")
        self.assertEqual(settings.backfill_window_end, "08:00")
        self.assertEqual(settings.backfill_queue_schedule, "*/30 * * * *")
        self.assertEqual(settings.backfill_jobs_per_round, 2)
        self.assertEqual(settings.backfill_max_attempts, 3)
        self.assertEqual(settings.backfill_max_jobs_per_night, 24)
        self.assertEqual(settings.backfill_max_external_requests_per_night, 300)
        self.assertEqual(settings.backfill_consecutive_failure_limit, 3)
        self.assertIsNone(settings.core_gap_recovery_schedule)
        self.assertEqual(settings.recent_core_gap_recovery_days, 3)
        self.assertTrue(settings.run_core_gap_recovery_on_startup)
        self.assertEqual(settings.core_ready_check_after_local_time, "15:30")
        self.assertEqual(settings.core_ready_expected_after_local_time, "16:10")
        self.assertEqual(settings.core_ready_fail_after_local_time, "17:00")
        self.assertEqual(settings.core_ready_after_local_time, "16:10")
        self.assertIsNone(settings.source_chain_overrides)
        self.assertEqual(settings.dead_letter_max_records_per_batch, 20)
        self.assertEqual(settings.bulk_upsert_batch_size, 1000)
        self.assertEqual(settings.bulk_upsert_min_batch_size, 100)
        self.assertEqual(settings.bulk_upsert_max_batch_size, 1000)
        self.assertEqual(settings.bulk_upsert_slow_batch_ms, 1500)
        self.assertEqual(settings.bulk_upsert_stable_batches_to_grow, 3)
        self.assertIn("tushare=200/m", settings.source_rate_limits)
        self.assertIn("akshare=60/m", settings.source_rate_limits)
        self.assertIn("baostock=60/m", settings.source_rate_limits)
        self.assertIn("coze=30/m", settings.source_rate_limits)
        self.assertEqual(settings.source_rate_limit_cooldown_seconds, 60)

    def test_connection_pool_defaults_are_small_enough_for_4c8g(self) -> None:
        self.assertEqual(RedisSettings(_env_file=None).max_connections, 30)
        mongo_settings = MongoSettings(_env_file=None)
        self.assertEqual(mongo_settings.max_pool_size, 20)
        self.assertTrue(mongo_settings.ensure_indexes)
        self.assertEqual(mongo_settings.index_startup_scope, "core")
        self.assertEqual(mongo_settings.index_create_timeout_seconds, 10)

    def test_coze_http_defaults_are_bounded(self) -> None:
        settings = CozeSettings(_env_file=None)

        self.assertEqual(settings.timeout, 30.0)
        self.assertEqual(settings.max_retries, 2)
        self.assertEqual(settings.retry_backoff_seconds, 0.5)
        self.assertEqual(settings.retry_backoff_max_seconds, 5.0)

    def test_non_core_task_defaults_are_rate_limited(self) -> None:
        settings = DataSyncSettings(_env_file=None)

        self.assertFalse(settings.hot_news_enabled)
        self.assertEqual(settings.hot_news_source_allowlist, "cls,xueqiu,wallstreetcn")
        self.assertEqual(settings.hot_news_max_sources_per_round, 3)
        self.assertEqual(settings.hot_news_max_items_per_source, 20)
        self.assertEqual(settings.review_data_max_rows_per_collection, 10000)
        self.assertEqual(settings.market_statistics_cache_periods, "1w,1m,3m")
        self.assertEqual(settings.hot_news_max_concurrency, 3)
        self.assertEqual(settings.hot_news_http_timeout_seconds, 10.0)
        self.assertEqual(settings.hot_news_total_timeout_seconds, 30.0)
        self.assertEqual(settings.multi_source_news_max_concurrency, 2)
        self.assertEqual(settings.multi_source_news_limit_per_source, 50)
        self.assertEqual(settings.event_clustering_batch_size, 30)
        self.assertEqual(settings.event_clustering_max_concurrent, 3)

    def test_backfill_window_accepts_datasync_env_alias(self) -> None:
        original_start = os.environ.get("DATASYNC_BACKFILL_WINDOW_START")
        original_end = os.environ.get("DATASYNC_BACKFILL_WINDOW_END")
        try:
            os.environ["DATASYNC_BACKFILL_WINDOW_START"] = "01:30"
            os.environ["DATASYNC_BACKFILL_WINDOW_END"] = "07:45"
            settings = DataSyncSettings(_env_file=None)
            self.assertEqual(settings.backfill_window_start, "01:30")
            self.assertEqual(settings.backfill_window_end, "07:45")
        finally:
            if original_start is None:
                os.environ.pop("DATASYNC_BACKFILL_WINDOW_START", None)
            else:
                os.environ["DATASYNC_BACKFILL_WINDOW_START"] = original_start
            if original_end is None:
                os.environ.pop("DATASYNC_BACKFILL_WINDOW_END", None)
            else:
                os.environ["DATASYNC_BACKFILL_WINDOW_END"] = original_end


if __name__ == "__main__":
    unittest.main()
