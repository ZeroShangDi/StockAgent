"""统一外部 HTTP 请求基座。

目标是把可控的 REST/HTTP 调用统一收敛到这里：超时、重试、退避、
429/503/5xx 分类、Retry-After 处理和请求元信息记录。
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any, Awaitable, Callable, Dict, Optional

import httpx


logger = logging.getLogger(__name__)


@dataclass
class HttpRequestMeta:
    source: str
    method: str
    url: str
    duration_ms: float
    attempts: int
    status_code: Optional[int] = None
    error_type: Optional[str] = None
    retry_after_seconds: Optional[float] = None


class DataSourceHttpError(RuntimeError):
    """结构化 HTTP 错误，供 DataSourceManager 统计分类。"""

    def __init__(self, message: str, meta: HttpRequestMeta):
        super().__init__(message)
        self.meta = meta
        self.error_type = meta.error_type
        self.status_code = meta.status_code
        self.duration_ms = meta.duration_ms
        self.attempts = meta.attempts
        self.retry_after_seconds = meta.retry_after_seconds


class UnifiedHttpClient:
    """轻量异步 HTTP 客户端封装。"""

    RETRYABLE_ERROR_TYPES = {
        "timeout",
        "network_error",
        "rate_limited",
        "service_unavailable",
        "server_error",
    }

    def __init__(
        self,
        *,
        source: str,
        timeout: float = 30.0,
        retries: int = 2,
        backoff_seconds: float = 0.5,
        max_backoff_seconds: float = 5.0,
        headers: Optional[Dict[str, str]] = None,
        follow_redirects: bool = True,
        max_connections: int = 20,
        max_keepalive_connections: int = 10,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        sleeper: Optional[Callable[[float], Awaitable[None]]] = None,
    ) -> None:
        self.source = source
        self.timeout = max(float(timeout or 30.0), 0.1)
        self.retries = max(int(retries or 0), 0)
        self.backoff_seconds = max(float(backoff_seconds or 0.0), 0.0)
        self.max_backoff_seconds = max(float(max_backoff_seconds or self.backoff_seconds), self.backoff_seconds)
        self._sleeper = sleeper or asyncio.sleep
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout),
            headers=headers,
            follow_redirects=follow_redirects,
            limits=httpx.Limits(
                max_connections=max(1, int(max_connections)),
                max_keepalive_connections=max(1, int(max_keepalive_connections)),
            ),
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", url, **kwargs)

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        method = method.upper()
        attempts_allowed = self.retries + 1
        started_at = time.perf_counter()
        last_meta: Optional[HttpRequestMeta] = None
        last_error: Optional[BaseException] = None

        for attempt in range(1, attempts_allowed + 1):
            try:
                response = await self._client.request(method, url, **kwargs)
                duration_ms = (time.perf_counter() - started_at) * 1000
                error_type = self._classify_status(response.status_code)
                retry_after = self._parse_retry_after(response.headers.get("Retry-After"))
                meta = HttpRequestMeta(
                    source=self.source,
                    method=method,
                    url=url,
                    duration_ms=duration_ms,
                    attempts=attempt,
                    status_code=response.status_code,
                    error_type=error_type,
                    retry_after_seconds=retry_after,
                )
                if error_type is None:
                    response.extensions["datasync_http_meta"] = meta
                    return response

                last_meta = meta
                if not self._should_retry(error_type, attempt, attempts_allowed):
                    raise DataSourceHttpError(
                        f"{self.source} {method} {url} failed: status={response.status_code}, error_type={error_type}",
                        meta,
                    )
                await self._sleep_before_retry(attempt, retry_after)
            except httpx.TimeoutException as exc:
                last_error = exc
                last_meta = self._build_error_meta(started_at, attempt, method, url, "timeout")
                if not self._should_retry("timeout", attempt, attempts_allowed):
                    break
                await self._sleep_before_retry(attempt, None)
            except httpx.TransportError as exc:
                last_error = exc
                last_meta = self._build_error_meta(started_at, attempt, method, url, "network_error")
                if not self._should_retry("network_error", attempt, attempts_allowed):
                    break
                await self._sleep_before_retry(attempt, None)

        assert last_meta is not None
        message = f"{self.source} {method} {url} failed: error_type={last_meta.error_type}"
        if last_error:
            message = f"{message}, error={last_error}"
        raise DataSourceHttpError(message, last_meta)

    async def request_json(self, method: str, url: str, **kwargs: Any) -> Any:
        response = await self.request(method, url, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            meta = response.extensions.get("datasync_http_meta") or HttpRequestMeta(
                source=self.source,
                method=method.upper(),
                url=url,
                duration_ms=0.0,
                attempts=1,
                status_code=response.status_code,
                error_type="invalid_json",
            )
            meta.error_type = "invalid_json"
            raise DataSourceHttpError(f"{self.source} {method.upper()} {url} returned invalid JSON", meta) from exc

    def _build_error_meta(
        self,
        started_at: float,
        attempt: int,
        method: str,
        url: str,
        error_type: str,
    ) -> HttpRequestMeta:
        return HttpRequestMeta(
            source=self.source,
            method=method,
            url=url,
            duration_ms=(time.perf_counter() - started_at) * 1000,
            attempts=attempt,
            error_type=error_type,
        )

    @staticmethod
    def _classify_status(status_code: int) -> Optional[str]:
        if status_code < 400:
            return None
        if status_code == 429:
            return "rate_limited"
        if status_code == 503:
            return "service_unavailable"
        if status_code >= 500:
            return "server_error"
        return "http_error"

    @classmethod
    def _should_retry(cls, error_type: Optional[str], attempt: int, attempts_allowed: int) -> bool:
        return bool(error_type in cls.RETRYABLE_ERROR_TYPES and attempt < attempts_allowed)

    async def _sleep_before_retry(self, attempt: int, retry_after: Optional[float]) -> None:
        if retry_after is not None and retry_after >= 0:
            delay = retry_after
        else:
            jitter = random.uniform(0, min(self.backoff_seconds, 0.25)) if self.backoff_seconds > 0 else 0.0
            delay = min(self.backoff_seconds * (2 ** max(attempt - 1, 0)) + jitter, self.max_backoff_seconds)
        if delay > 0:
            await self._sleeper(delay)

    @staticmethod
    def _parse_retry_after(value: Optional[str]) -> Optional[float]:
        if not value:
            return None
        text = value.strip()
        try:
            return max(float(text), 0.0)
        except ValueError:
            pass
        try:
            retry_at = parsedate_to_datetime(text)
            return max(retry_at.timestamp() - time.time(), 0.0)
        except Exception:
            return None
