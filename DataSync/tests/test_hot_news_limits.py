from pathlib import Path
import asyncio
import sys
import unittest


DATASYNC_ROOT = Path(__file__).resolve().parents[1]
if str(DATASYNC_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASYNC_ROOT))

from nodes.data_sync.collectors.news import hot_news
from nodes.data_sync.collectors.news.hot_news import HotNewsCollector


class _FakeRedisManager:
    is_initialized = True

    def __init__(self) -> None:
        self.saved: dict[str, list[dict]] = {}

    async def initialize(self) -> None:
        self.is_initialized = True

    async def set_hot_news(self, source: str, news_list: list[dict]) -> None:
        self.saved[source] = news_list


class _FakeSourceA:
    name = "cls"
    display_name = "财联社"
    color = "red"
    column = "finance"

    async def fetch(self) -> list[dict]:
        return [
            {"title": f"news-{idx}", "url": f"https://example.com/{idx}", "rank": idx}
            for idx in range(5)
        ]

    async def close(self) -> None:
        return None


class _FakeSourceB:
    name = "xueqiu"
    display_name = "雪球"
    color = "blue"
    column = "finance"

    async def fetch(self) -> list[dict]:
        return [{"title": "xueqiu-news", "url": "https://example.com/xueqiu"}]

    async def close(self) -> None:
        return None


class _SlowSource:
    name = "wallstreetcn"
    display_name = "华尔街见闻"
    color = "blue"
    column = "finance"

    async def fetch(self) -> list[dict]:
        await asyncio.sleep(1.2)
        return [{"title": "slow-news", "url": "https://example.com/slow"}]

    async def close(self) -> None:
        return None


class HotNewsLimitsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.collector = HotNewsCollector()
        self.settings = hot_news.settings.data_sync
        self.original_values = {
            "enabled": self.settings.hot_news_enabled,
            "source_allowlist": self.settings.hot_news_source_allowlist,
            "max_sources_per_round": self.settings.hot_news_max_sources_per_round,
            "max_items_per_source": self.settings.hot_news_max_items_per_source,
            "max_concurrency": self.settings.hot_news_max_concurrency,
            "total_timeout_seconds": self.settings.hot_news_total_timeout_seconds,
        }
        self.original_source_classes = HotNewsCollector.SOURCE_CLASSES
        self.original_redis_manager = hot_news.redis_manager
        self.fake_redis = _FakeRedisManager()
        hot_news.redis_manager = self.fake_redis

    async def asyncTearDown(self) -> None:
        self.settings.hot_news_enabled = self.original_values["enabled"]
        self.settings.hot_news_source_allowlist = self.original_values["source_allowlist"]
        self.settings.hot_news_max_sources_per_round = self.original_values["max_sources_per_round"]
        self.settings.hot_news_max_items_per_source = self.original_values["max_items_per_source"]
        self.settings.hot_news_max_concurrency = self.original_values["max_concurrency"]
        self.settings.hot_news_total_timeout_seconds = self.original_values["total_timeout_seconds"]
        HotNewsCollector.SOURCE_CLASSES = self.original_source_classes
        hot_news.redis_manager = self.original_redis_manager

    async def test_disabled_hot_news_returns_skipped_without_fetching(self) -> None:
        self.settings.hot_news_enabled = False
        HotNewsCollector.SOURCE_CLASSES = [_FakeSourceA]

        result = await self.collector.collect()

        self.assertFalse(result["success"])
        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "hot_news_disabled")
        self.assertEqual(self.fake_redis.saved, {})

    async def test_enabled_hot_news_limits_sources_and_items(self) -> None:
        self.settings.hot_news_enabled = True
        self.settings.hot_news_source_allowlist = "cls,xueqiu"
        self.settings.hot_news_max_sources_per_round = 1
        self.settings.hot_news_max_items_per_source = 2
        self.settings.hot_news_total_timeout_seconds = 5
        HotNewsCollector.SOURCE_CLASSES = [_FakeSourceA, _FakeSourceB]

        result = await self.collector.collect()

        self.assertEqual(result["count"], 2)
        self.assertEqual(result["source_count"], 1)
        self.assertEqual(list(self.fake_redis.saved), ["cls"])
        self.assertEqual(len(self.fake_redis.saved["cls"]), 2)

    async def test_total_timeout_fails_explicitly(self) -> None:
        self.settings.hot_news_enabled = True
        self.settings.hot_news_source_allowlist = "wallstreetcn"
        self.settings.hot_news_max_sources_per_round = 1
        self.settings.hot_news_total_timeout_seconds = 1
        HotNewsCollector.SOURCE_CLASSES = [_SlowSource]

        result = await self.collector.collect()

        self.assertFalse(result["success"])
        self.assertEqual(result["reason"], "hot_news_total_timeout")
        self.assertIn("hot_news_total_timeout_after_", result["error"])


if __name__ == "__main__":
    unittest.main()
