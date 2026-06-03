from pathlib import Path
import sys
import unittest

from pymongo import ASCENDING, IndexModel


DATASYNC_ROOT = Path(__file__).resolve().parents[1]
if str(DATASYNC_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASYNC_ROOT))

from core.managers.mongo_manager import MongoManager
from core.settings import MongoSettings


class _AsyncIndexCursor:
    def __init__(self, items):
        self._items = list(items)
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._index]
        self._index += 1
        return item


class _FakeCollection:
    def __init__(self, existing_indexes=None):
        self.existing_indexes = existing_indexes or []
        self.create_calls = []
        self.drop_calls = []

    def list_indexes(self):
        return _AsyncIndexCursor(self.existing_indexes)

    async def create_indexes(self, indexes):
        self.create_calls.append(indexes)
        return [index.document.get("name") or "created" for index in indexes]

    async def drop_index(self, name):
        self.drop_calls.append(name)


class _FakeDb:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        if name not in self.collections:
            self.collections[name] = _FakeCollection()
        return self.collections[name]


class MongoIndexScopeTest(unittest.IsolatedAsyncioTestCase):
    def test_mongo_index_defaults_are_startup_safe(self) -> None:
        settings = MongoSettings(_env_file=None)

        self.assertTrue(settings.ensure_indexes)
        self.assertEqual(settings.index_startup_scope, "core")
        self.assertEqual(settings.index_create_timeout_seconds, 10)

    async def test_core_scope_skips_non_core_collections(self) -> None:
        manager = MongoManager()
        fake_db = _FakeDb()
        manager._db = fake_db
        manager._active_index_scope = "core"

        await manager._safe_create_indexes(
            "news",
            [IndexModel([("created_at", ASCENDING)])],
        )
        await manager._safe_create_indexes(
            "stock_daily",
            [IndexModel([("trade_date", ASCENDING)])],
        )

        self.assertEqual(fake_db["news"].create_calls, [])
        self.assertEqual(len(fake_db["stock_daily"].create_calls), 1)

    async def test_existing_index_name_is_not_recreated(self) -> None:
        manager = MongoManager()
        fake_db = _FakeDb()
        fake_db.collections["stock_daily"] = _FakeCollection(
            existing_indexes=[{"name": "trade_date_1"}]
        )
        manager._db = fake_db
        manager._active_index_scope = "all"

        await manager._safe_create_indexes(
            "stock_daily",
            [IndexModel([("trade_date", ASCENDING)])],
        )

        self.assertEqual(fake_db["stock_daily"].create_calls, [])


if __name__ == "__main__":
    unittest.main()
