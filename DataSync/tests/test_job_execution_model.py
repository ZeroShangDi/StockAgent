from datetime import datetime
from pathlib import Path
import sys
import unittest


DATASYNC_ROOT = Path(__file__).resolve().parents[1]
if str(DATASYNC_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASYNC_ROOT))

from core.base import ScheduledJob
from nodes.data_sync import node as data_sync_node
from nodes.data_sync.node import DataSyncNode


class _CoreJob(ScheduledJob):
    name = "stock_daily"
    description = "核心日线任务"
    default_schedule = "0 0 * * *"

    async def _do_work(self) -> dict:
        return {"count": 0}


class _BackgroundJob(ScheduledJob):
    name = "hot_news"
    description = "热点新闻任务"
    default_schedule = "0 0 * * *"

    async def _do_work(self) -> dict:
        return {"count": 0}


class _FakeMongoManager:
    def __init__(self) -> None:
        self.records: list[dict] = []

    async def record_job_execution(self, **kwargs) -> str:
        self.records.append(kwargs)
        return "execution-id"


class _FakeDataSourceManager:
    async def get_latest_trade_date(self) -> tuple[str, None]:
        return "20260527", None


class JobExecutionModelTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.original_mongo_manager = data_sync_node.mongo_manager
        self.original_data_source_manager = data_sync_node.data_source_manager
        self.fake_mongo = _FakeMongoManager()
        data_sync_node.mongo_manager = self.fake_mongo
        data_sync_node.data_source_manager = _FakeDataSourceManager()
        self.node = DataSyncNode(node_id="data-sync-model-test", rpc_port=0)

    async def asyncTearDown(self) -> None:
        data_sync_node.mongo_manager = self.original_mongo_manager
        data_sync_node.data_source_manager = self.original_data_source_manager

    async def test_core_job_record_has_run_date_target_trade_date_and_resource_class(self) -> None:
        started_at = datetime(2026, 5, 28, 15, 30, 0)
        finished_at = datetime(2026, 5, 28, 15, 31, 0)

        await self.node._record_job_execution(
            job=_CoreJob(),
            result={"success": True, "count": 10, "source": "tushare"},
            started_at=started_at,
            finished_at=finished_at,
            trigger="unit_test",
            pipeline_name=None,
        )

        record = self.fake_mongo.records[0]
        self.assertEqual(record["run_date"], "20260528")
        self.assertEqual(record["target_trade_date"], "20260527")
        self.assertEqual(record["data_cutoff_time"], "20260527")
        self.assertEqual(record["resource_class"], "core")
        self.assertEqual(record["source"], "tushare")
        self.assertEqual(record["details"]["target_trade_date"], "20260527")
        self.assertEqual(record["details"]["run_date"], "20260528")
        self.assertEqual(record["details"]["resource_class"], "core")

    async def test_background_job_does_not_guess_target_trade_date(self) -> None:
        started_at = datetime(2026, 5, 28, 15, 30, 0)
        finished_at = datetime(2026, 5, 28, 15, 31, 0)

        await self.node._record_job_execution(
            job=_BackgroundJob(),
            result={"success": False, "skipped": True, "reason": "hot_news_disabled"},
            started_at=started_at,
            finished_at=finished_at,
            trigger="unit_test",
            pipeline_name=None,
        )

        record = self.fake_mongo.records[0]
        self.assertEqual(record["run_date"], "20260528")
        self.assertIsNone(record["target_trade_date"])
        self.assertIsNone(record["data_cutoff_time"])
        self.assertEqual(record["resource_class"], "background")
        self.assertEqual(record["details"]["reason"], "hot_news_disabled")


if __name__ == "__main__":
    unittest.main()
