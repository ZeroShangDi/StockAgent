import asyncio
from pathlib import Path
import sys
import unittest

import httpx


DATASYNC_ROOT = Path(__file__).resolve().parents[1]
if str(DATASYNC_ROOT) not in sys.path:
    sys.path.insert(0, str(DATASYNC_ROOT))

from core.managers.data_source_manager import DataSourceChainError, DataSourceManager
from src.data_sources.http_client import DataSourceHttpError, HttpRequestMeta, UnifiedHttpClient


class UnifiedHttpClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_retry_after_429_then_success(self) -> None:
        attempts = 0
        sleeps = []

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(429, headers={"Retry-After": "0.01"}, json={"error": "limited"})
            return httpx.Response(200, json={"ok": True})

        async def sleeper(delay: float) -> None:
            sleeps.append(delay)

        client = UnifiedHttpClient(
            source="test",
            retries=1,
            backoff_seconds=0,
            transport=httpx.MockTransport(handler),
            sleeper=sleeper,
        )
        try:
            payload = await client.request_json("GET", "https://example.test/data")
        finally:
            await client.aclose()

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(attempts, 2)
        self.assertEqual(sleeps, [0.01])

    async def test_service_unavailable_is_structured_error(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"error": "busy"})

        client = UnifiedHttpClient(
            source="test",
            retries=0,
            transport=httpx.MockTransport(handler),
            sleeper=asyncio.sleep,
        )
        try:
            with self.assertRaises(DataSourceHttpError) as ctx:
                await client.request_json("POST", "https://example.test/data", json={})
        finally:
            await client.aclose()

        self.assertEqual(ctx.exception.error_type, "service_unavailable")
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(ctx.exception.attempts, 1)

    async def test_timeout_is_structured_error(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("read timed out", request=request)

        client = UnifiedHttpClient(
            source="test",
            retries=0,
            transport=httpx.MockTransport(handler),
        )
        try:
            with self.assertRaises(DataSourceHttpError) as ctx:
                await client.request("GET", "https://example.test/data")
        finally:
            await client.aclose()

        self.assertEqual(ctx.exception.error_type, "timeout")
        self.assertIsNone(ctx.exception.status_code)

    async def test_invalid_json_is_structured_error(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="not-json")

        client = UnifiedHttpClient(
            source="test",
            retries=0,
            transport=httpx.MockTransport(handler),
        )
        try:
            with self.assertRaises(DataSourceHttpError) as ctx:
                await client.request_json("GET", "https://example.test/data")
        finally:
            await client.aclose()

        self.assertEqual(ctx.exception.error_type, "invalid_json")
        self.assertEqual(ctx.exception.status_code, 200)


class DataSourceManagerHttpStatsTest(unittest.IsolatedAsyncioTestCase):
    async def test_data_source_http_error_is_counted_by_error_type(self) -> None:
        class FakeAdapter:
            name = "coze"
            priority = 100

            async def is_available(self) -> bool:
                return True

            async def get_stock_basic(self, ts_code: str = "", list_status: str = "L"):
                meta = HttpRequestMeta(
                    source=self.name,
                    method="POST",
                    url="https://example.test/workflow",
                    duration_ms=12.0,
                    attempts=1,
                    status_code=429,
                    error_type="rate_limited",
                )
                raise DataSourceHttpError("limited", meta)

        manager = DataSourceManager()
        adapter = FakeAdapter()
        manager._adapters = [adapter]
        manager._adapter_map = {adapter.name: adapter}
        manager.reset_call_stats()

        with self.assertRaises(DataSourceChainError):
            await manager.get_stock_basic(ts_code="000001.SZ", preferred_source="coze")
        summary = manager.get_call_stats_summary()
        entry = summary["entries"][0]

        self.assertEqual(entry["rate_limited_count"], 1)
        self.assertEqual(entry["last_status"], "rate_limited")
        self.assertEqual(entry["last_error_type"], "rate_limited")
        self.assertEqual(entry["last_status_code"], 429)

    async def test_rate_limited_source_enters_cooldown_and_falls_back(self) -> None:
        class RateLimitedAdapter:
            name = "coze"
            priority = 100

            async def is_available(self) -> bool:
                return True

            async def get_stock_basic(self, ts_code: str = "", list_status: str = "L"):
                meta = HttpRequestMeta(
                    source=self.name,
                    method="POST",
                    url="https://example.test/workflow",
                    duration_ms=12.0,
                    attempts=1,
                    status_code=429,
                    error_type="rate_limited",
                    retry_after_seconds=30.0,
                )
                raise DataSourceHttpError("limited", meta)

        class FallbackAdapter:
            name = "baostock"
            priority = 50

            async def is_available(self) -> bool:
                return True

            async def get_stock_basic(self, ts_code: str = "", list_status: str = "L"):
                return [{"ts_code": ts_code or "000001.SZ"}]

        manager = DataSourceManager()
        coze = RateLimitedAdapter()
        baostock = FallbackAdapter()
        manager._adapters = [coze, baostock]
        manager._adapter_map = {adapter.name: adapter for adapter in manager._adapters}
        manager.reset_call_stats()

        first_records, first_source = await manager.get_stock_basic(
            ts_code="000001.SZ",
            preferred_source="coze",
        )
        second_records, second_source = await manager.get_stock_basic(
            ts_code="000001.SZ",
            preferred_source="coze",
        )
        summary = manager.get_call_stats_summary()
        coze_entry = next(item for item in summary["entries"] if item["adapter_name"] == "coze")
        status = manager.get_source_rate_limit_status()

        self.assertEqual(first_source, "baostock")
        self.assertEqual(second_source, "baostock")
        self.assertEqual(first_records, [{"ts_code": "000001.SZ"}])
        self.assertEqual(second_records, [{"ts_code": "000001.SZ"}])
        self.assertEqual(coze_entry["rate_limited_count"], 2)
        self.assertEqual(coze_entry["last_error_type"], "source_cooling_down")
        self.assertGreater(coze_entry["last_cooldown_remaining_seconds"], 0)
        self.assertIn("coze", status["cooldowns"])


if __name__ == "__main__":
    unittest.main()
