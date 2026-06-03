from pathlib import Path
import asyncio
from datetime import datetime, timedelta
import sys
import unittest


DATASYNC_ROOT = Path(__file__).resolve().parents[1]
if str(DATASYNC_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASYNC_ROOT))

from core.base import ScheduledJob
from nodes.data_sync import node as data_sync_node
from nodes.data_sync.node import DataSyncNode


class _FakeLock:
    def __init__(self) -> None:
        self.released = False

    async def release(self) -> None:
        self.released = True


class _FakeRedisManager:
    def __init__(self) -> None:
        self.lock_timeouts: list[int] = []
        self.locks: list[_FakeLock] = []

    async def try_lock(self, key: str, timeout: int) -> _FakeLock:
        self.lock_timeouts.append(timeout)
        lock = _FakeLock()
        self.locks.append(lock)
        return lock


class _SlowJob(ScheduledJob):
    name = "slow_job"
    description = "慢任务"
    default_schedule = "0 0 * * *"

    def __init__(self, delay_seconds: float = 2.0) -> None:
        super().__init__()
        self.delay_seconds = delay_seconds

    async def _do_work(self) -> dict:
        await asyncio.sleep(self.delay_seconds)
        return {"count": 1}


class _ObservedJob(ScheduledJob):
    name = "observed_job"
    description = "并发观察任务"
    default_schedule = "0 0 * * *"

    active_count = 0
    max_active_count = 0

    async def _do_work(self) -> dict:
        type(self).active_count += 1
        type(self).max_active_count = max(type(self).max_active_count, type(self).active_count)
        try:
            await asyncio.sleep(0.05)
            return {"count": 1}
        finally:
            type(self).active_count -= 1


class _HeavyJob(_ObservedJob):
    name = "fina_indicator"
    description = "重型任务"


class DataSyncRuntimeGuardsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_redis_manager = data_sync_node.redis_manager
        self.fake_redis_manager = _FakeRedisManager()
        data_sync_node.redis_manager = self.fake_redis_manager

        self.node = DataSyncNode(node_id="data-sync-test", rpc_port=0)
        self.records: list[dict] = []

        async def record_job_execution(**kwargs) -> None:
            self.records.append(kwargs)

        self.node._record_job_execution = record_job_execution

        self.original_job_timeout = self.node.settings.data_sync.job_timeout_seconds
        self.original_lock_timeout = self.node.settings.data_sync.lock_timeout_seconds
        self.original_backfill_window_start = self.node.settings.data_sync.backfill_window_start
        self.original_backfill_window_end = self.node.settings.data_sync.backfill_window_end
        self.node.settings.data_sync.job_timeout_seconds = 1
        self.node.settings.data_sync.lock_timeout_seconds = 7

    async def asyncTearDown(self) -> None:
        data_sync_node.redis_manager = self.original_redis_manager
        self.node.settings.data_sync.job_timeout_seconds = self.original_job_timeout
        self.node.settings.data_sync.lock_timeout_seconds = self.original_lock_timeout
        self.node.settings.data_sync.backfill_window_start = self.original_backfill_window_start
        self.node.settings.data_sync.backfill_window_end = self.original_backfill_window_end

    async def test_job_timeout_is_recorded_as_failure_and_lock_is_released(self) -> None:
        result = await self.node._run_job_with_lock(
            _SlowJob(delay_seconds=2.0),
            trigger="unit_test",
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "timeout")
        self.assertEqual(result["error"], "job_timeout_after_1s")
        self.assertEqual(self.fake_redis_manager.lock_timeouts, [7])
        self.assertTrue(self.fake_redis_manager.locks[0].released)
        self.assertEqual(len(self.records), 1)
        self.assertEqual(self.records[0]["result"]["reason"], "timeout")

    async def test_node_semaphore_limits_concurrent_jobs(self) -> None:
        _ObservedJob.active_count = 0
        _ObservedJob.max_active_count = 0
        self.node._job_semaphore = asyncio.Semaphore(1)

        await asyncio.gather(
            self.node._run_job_with_lock(_ObservedJob(), trigger="unit_test"),
            self.node._run_job_with_lock(_ObservedJob(), trigger="unit_test"),
        )

        self.assertEqual(_ObservedJob.max_active_count, 1)
        self.assertEqual(len(self.records), 2)

    async def test_scheduler_skips_non_core_job_while_core_resource_is_busy(self) -> None:
        self.node._active_core_jobs = 1

        result = await self.node._run_job_with_lock(
            _ObservedJob(),
            trigger="scheduler",
        )

        self.assertFalse(result["success"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "core_resource_busy")
        self.assertEqual(result["resource_class"], "background")
        self.assertEqual(len(self.records), 1)
        self.assertEqual(self.records[0]["result"]["reason"], "core_resource_busy")

    async def test_heavy_job_is_skipped_outside_backfill_window(self) -> None:
        now = datetime.now()
        self.node.settings.data_sync.backfill_window_start = (now + timedelta(hours=1)).strftime("%H:%M")
        self.node.settings.data_sync.backfill_window_end = (now + timedelta(hours=2)).strftime("%H:%M")

        result = await self.node._run_job_with_lock(
            _HeavyJob(),
            trigger="scheduler",
        )

        self.assertFalse(result["success"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "backfill_window_closed")
        self.assertEqual(result["resource_class"], "heavy")
        self.assertEqual(len(self.records), 1)
        self.assertEqual(self.records[0]["result"]["reason"], "backfill_window_closed")
        self.assertEqual(self.fake_redis_manager.lock_timeouts, [])

    async def test_force_backfill_window_allows_manual_heavy_job(self) -> None:
        now = datetime.now()
        self.node.settings.data_sync.backfill_window_start = (now + timedelta(hours=1)).strftime("%H:%M")
        self.node.settings.data_sync.backfill_window_end = (now + timedelta(hours=2)).strftime("%H:%M")

        result = await self.node._run_job_with_lock(
            _HeavyJob(),
            trigger="manual",
            force_backfill_window=True,
        )

        self.assertTrue(result["success"])
        self.assertEqual(self.fake_redis_manager.lock_timeouts, [7])
        self.assertEqual(len(self.records), 1)

    def test_cross_midnight_backfill_window(self) -> None:
        self.node.settings.data_sync.backfill_window_start = "23:00"
        self.node.settings.data_sync.backfill_window_end = "08:00"

        self.assertTrue(self.node._get_backfill_window_state(datetime(2026, 5, 29, 1, 0))["open"])
        self.assertTrue(self.node._get_backfill_window_state(datetime(2026, 5, 29, 23, 30))["open"])
        self.assertFalse(self.node._get_backfill_window_state(datetime(2026, 5, 29, 12, 0))["open"])


if __name__ == "__main__":
    unittest.main()
