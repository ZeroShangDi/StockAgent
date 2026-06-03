"""
数据源管理器

统一管理多个数据源适配器，提供自动降级和优先级调度。

使用方式:
    from core.managers import data_source_manager

    # 初始化 (在应用启动时调用)
    await data_source_manager.initialize()

    # 获取数据 (自动选择可用的数据源)
    stocks, source = await data_source_manager.get_stock_basic()
    daily, source = await data_source_manager.get_daily(ts_code="000001.SZ")

    # 关闭
    await data_source_manager.shutdown()
"""

from typing import Optional, List, Dict, Any, Tuple, Type
import asyncio
import inspect
import logging
import time
from datetime import UTC, datetime, timedelta

from core.base import BaseManager
from core.settings import settings
from src.data_sources import (
    AsyncDataSourceAdapter,
    TokenBucket,
    TushareAdapter,
    AKShareAdapter,
    BaoStockAdapter,
    CozeWorkflowAdapter,
)
from src.data_sources.http_client import DataSourceHttpError


logger = logging.getLogger(__name__)


class DataSourceChainError(RuntimeError):
    """所有可尝试数据源均失败时抛出，避免把源端故障伪装成空数据。"""

    def __init__(self, method_name: str, source_chain: List[str], outcomes: List[Dict[str, Any]]):
        super().__init__(f"All data sources failed for {method_name}: {source_chain}")
        self.method_name = method_name
        self.source_chain = source_chain
        self.outcomes = outcomes


class DataSourceManager(BaseManager):
    """
    数据源管理器

    职责:
    - 管理多个数据源适配器
    - 根据优先级自动选择数据源
    - 当主数据源不可用时自动降级
    - 对 Node 层提供统一的数据获取接口
    """
    CORE_SYNC_METHODS = {
        "get_latest_trade_date",
        "get_trade_calendar",
        "get_daily",
        "get_daily_basic",
        "get_index_daily",
        "get_moneyflow_industry",
        "get_moneyflow_concept",
        "get_limit_list",
    }
    DEFAULT_SOURCE_CHAINS: Dict[str, List[str]] = {
        "get_stock_basic": ["akshare", "baostock", "coze", "tushare"],
        "get_daily.single": ["coze", "akshare", "baostock", "tushare"],
        "get_daily.full_market": ["tushare", "baostock", "akshare", "coze"],
        "get_daily_basic.single": ["coze", "akshare", "baostock", "tushare"],
        "get_daily_basic.full_market": ["tushare", "baostock", "akshare", "coze"],
        "get_index_daily": ["tushare", "baostock", "akshare"],
        "get_latest_trade_date": ["tushare", "baostock", "akshare", "coze"],
        "get_trade_calendar": ["tushare", "baostock", "akshare", "coze"],
        "get_limit_list": ["tushare", "akshare"],
        "get_moneyflow_industry": ["tushare", "akshare"],
        "get_moneyflow_concept": ["tushare", "akshare"],
        "get_realtime_quotes": ["coze", "tushare", "akshare", "baostock"],
        "get_realtime_index_quotes": ["coze", "akshare", "tushare"],
        "get_financial_indicator": ["coze", "akshare", "baostock", "tushare"],
        "get_financial_data": ["coze", "akshare", "baostock", "tushare"],
        "get_kline": ["coze", "akshare", "baostock", "tushare"],
    }

    def __init__(self):
        super().__init__()
        self._adapters: List[AsyncDataSourceAdapter] = []
        self._adapter_map: Dict[str, AsyncDataSourceAdapter] = {}
        self._call_stats: Dict[str, Dict[str, Any]] = {}
        self._call_stats_started_at: Optional[datetime] = None
        self._source_rate_limiters: Dict[str, TokenBucket] = {}
        self._source_cooldowns: Dict[str, float] = {}

    async def initialize(self) -> None:
        """初始化所有数据源适配器"""
        if self._initialized:
            return

        self.logger.info("Initializing DataSourceManager...")

        # 检查 Tushare 是否配置
        tushare_configured = False
        try:
            tushare_configured = settings.tushare.is_configured
        except Exception:
            pass

        # 按优先级添加适配器
        adapter_classes: List[Tuple[Type[AsyncDataSourceAdapter], dict]] = []

        if tushare_configured:
            token = settings.tushare.token.get_secret_value()
            adapter_classes.append((TushareAdapter, {"token": token}))
            self.logger.info("Tushare token configured, adding TushareAdapter")
        else:
            self.logger.warning("Tushare token not configured, using free data sources only")

        # Coze 工作流数据源（可选）
        try:
            if settings.coze.is_configured:
                adapter_classes.append(
                    (
                        CozeWorkflowAdapter,
                        {
                            "api_token": settings.coze.api_token.get_secret_value(),
                            "workflow_id": settings.coze.workflow_id,
                            "api_base": settings.coze.api_base,
                            "space_id": settings.coze.space_id,
                            "app_id": settings.coze.app_id,
                            "bot_id": settings.coze.bot_id,
                            "timeout": settings.coze.timeout,
                        },
                    )
                )
                self.logger.info("Coze workflow configured, adding CozeWorkflowAdapter")
        except Exception as e:
            self.logger.warning(f"Failed to load Coze config: {e}")

        # 免费数据源始终添加
        adapter_classes.append((AKShareAdapter, {}))
        adapter_classes.append((BaoStockAdapter, {}))

        # 初始化所有适配器
        self.reset_call_stats()
        for adapter_cls, kwargs in adapter_classes:
            try:
                adapter = adapter_cls(**kwargs)
                await adapter.initialize()

                if await adapter.is_available():
                    self._adapters.append(adapter)
                    self._adapter_map[adapter.name] = adapter
                    self.logger.info(f"Adapter {adapter.name} initialized (priority: {adapter.priority})")
                else:
                    self.logger.warning(f"Adapter {adapter.name} not available")
                    await adapter.shutdown()
            except Exception as e:
                self.logger.error(f"Failed to initialize {adapter_cls.__name__}: {e}")

        # 按优先级排序 (高优先级在前)
        self._adapters.sort(key=lambda x: x.priority, reverse=True)

        self._initialized = True
        self.logger.info(f"DataSourceManager initialized with {len(self._adapters)} adapters: {[a.name for a in self._adapters]}")

    async def shutdown(self) -> None:
        """关闭所有适配器"""
        for adapter in self._adapters:
            try:
                await adapter.shutdown()
            except Exception as e:
                self.logger.error(f"Error shutting down {adapter.name}: {e}")

        self._adapters.clear()
        self._adapter_map.clear()
        self._initialized = False
        self.logger.info("DataSourceManager shutdown")

    async def health_check(self) -> bool:
        """健康检查"""
        if not self._initialized or not self._adapters:
            return False

        # 至少有一个适配器可用
        for adapter in self._adapters:
            if await adapter.is_available():
                return True
        return False

    def get_available_adapters(self) -> List[str]:
        """获取可用的适配器名称列表"""
        return [a.name for a in self._adapters]

    def get_adapter(self, name: str) -> Optional[AsyncDataSourceAdapter]:
        """根据名称获取特定适配器"""
        return self._adapter_map.get(name)

    def _stats_key(self, method_name: str, adapter_name: str) -> str:
        return f"{method_name}:{adapter_name}"

    def _get_stats_bucket(self, method_name: str, adapter_name: str) -> Dict[str, Any]:
        key = self._stats_key(method_name, adapter_name)
        bucket = self._call_stats.get(key)
        if bucket is None:
            bucket = {
                "method_name": method_name,
                "adapter_name": adapter_name,
                "attempt_count": 0,
                "success_count": 0,
                "timeout_count": 0,
                "rate_limited_count": 0,
                "server_error_count": 0,
                "network_error_count": 0,
                "http_error_count": 0,
                "failure_count": 0,
                "empty_result_count": 0,
                "fallback_count": 0,
                "last_status": None,
                "last_error": None,
                "last_error_type": None,
                "last_status_code": None,
                "last_source_chain_key": None,
                "last_source_chain": [],
                "last_attempted_sources": [],
                "last_fallback_from": None,
                "last_fallback_to": None,
                "last_attempt_at": None,
                "last_success_at": None,
                "last_timeout_at": None,
                "last_rate_limited_at": None,
                "last_cooldown_until": None,
                "last_cooldown_remaining_seconds": None,
                "last_server_error_at": None,
                "last_network_error_at": None,
                "last_failure_at": None,
                "last_empty_result_at": None,
                "last_duration_ms": None,
            }
            self._call_stats[key] = bucket
        return bucket

    def _record_call_outcome(
        self,
        *,
        method_name: str,
        adapter_name: str,
        status: str,
        duration_ms: float,
        attempted_sources: List[str],
        error: Optional[str] = None,
        error_type: Optional[str] = None,
        status_code: Optional[int] = None,
        source_chain_key: Optional[str] = None,
        source_chain: Optional[List[str]] = None,
        cooldown_until: Optional[datetime] = None,
        cooldown_remaining_seconds: Optional[float] = None,
    ) -> None:
        bucket = self._get_stats_bucket(method_name, adapter_name)
        now = datetime.now(UTC)
        bucket["attempt_count"] += 1
        bucket["last_status"] = status
        bucket["last_error"] = error
        bucket["last_error_type"] = error_type
        bucket["last_status_code"] = status_code
        bucket["last_source_chain_key"] = source_chain_key
        bucket["last_source_chain"] = list(source_chain or [])
        bucket["last_attempted_sources"] = list(attempted_sources)
        bucket["last_cooldown_until"] = cooldown_until
        bucket["last_cooldown_remaining_seconds"] = (
            round(cooldown_remaining_seconds, 3)
            if cooldown_remaining_seconds is not None
            else None
        )
        bucket["last_fallback_from"] = attempted_sources[-2] if len(attempted_sources) >= 2 else None
        bucket["last_fallback_to"] = adapter_name if len(attempted_sources) >= 2 else None
        bucket["last_attempt_at"] = now
        bucket["last_duration_ms"] = round(duration_ms, 3)
        bucket["fallback_count"] += max(0, len(attempted_sources) - 1)

        if status == "success":
            bucket["success_count"] += 1
            bucket["last_success_at"] = now
        elif status == "timeout":
            bucket["timeout_count"] += 1
            bucket["last_timeout_at"] = now
            bucket["last_failure_at"] = now
        elif status == "rate_limited":
            bucket["rate_limited_count"] += 1
            bucket["last_rate_limited_at"] = now
            bucket["last_failure_at"] = now
        elif status in {"server_error", "service_unavailable"}:
            bucket["server_error_count"] += 1
            bucket["last_server_error_at"] = now
            bucket["last_failure_at"] = now
        elif status == "network_error":
            bucket["network_error_count"] += 1
            bucket["last_network_error_at"] = now
            bucket["last_failure_at"] = now
        elif status == "http_error":
            bucket["http_error_count"] += 1
            bucket["last_failure_at"] = now
        elif status == "empty":
            bucket["empty_result_count"] += 1
            bucket["last_empty_result_at"] = now
        elif status == "failed":
            bucket["failure_count"] += 1
            bucket["last_failure_at"] = now

    def get_call_stats_summary(self) -> Dict[str, Any]:
        stats = list(self._call_stats.values())
        ranked = sorted(
            stats,
            key=lambda item: (
                -(int(item.get("timeout_count") or 0)),
                -(int(item.get("rate_limited_count") or 0)),
                -(int(item.get("server_error_count") or 0)),
                -(int(item.get("network_error_count") or 0)),
                -(int(item.get("failure_count") or 0)),
                -(int(item.get("fallback_count") or 0)),
                item.get("method_name") or "",
                item.get("adapter_name") or "",
            ),
        )
        timeout_entries = [
            item for item in ranked
            if int(item.get("timeout_count") or 0) > 0
        ]
        degraded_entries = [
            item for item in ranked
            if int(item.get("timeout_count") or 0) > 0
            or int(item.get("failure_count") or 0) > 0
            or int(item.get("fallback_count") or 0) > 0
            or int(item.get("rate_limited_count") or 0) > 0
            or int(item.get("server_error_count") or 0) > 0
            or int(item.get("network_error_count") or 0) > 0
            or int(item.get("http_error_count") or 0) > 0
        ]
        core_entries = [
            item for item in ranked
            if str(item.get("method_name") or "") in self.CORE_SYNC_METHODS
        ]
        core_timed_out_entries = [
            item for item in timeout_entries
            if str(item.get("method_name") or "") in self.CORE_SYNC_METHODS
        ]
        core_degraded_entries = [
            item for item in degraded_entries
            if str(item.get("method_name") or "") in self.CORE_SYNC_METHODS
        ]
        return {
            "success": True,
            "started_at": self._call_stats_started_at,
            "core_methods": sorted(self.CORE_SYNC_METHODS),
            "entry_count": len(ranked),
            "timeout_entry_count": len(timeout_entries),
            "degraded_entry_count": len(degraded_entries),
            "core_entry_count": len(core_entries),
            "core_timeout_entry_count": len(core_timed_out_entries),
            "core_degraded_entry_count": len(core_degraded_entries),
            "entries": ranked,
            "timed_out_entries": timeout_entries,
            "degraded_entries": degraded_entries,
            "core_entries": core_entries,
            "core_timed_out_entries": core_timed_out_entries,
            "core_degraded_entries": core_degraded_entries,
            "source_rate_limits": self.get_source_rate_limit_status(),
        }

    def reset_call_stats(self) -> Dict[str, Any]:
        self._call_stats.clear()
        self._call_stats_started_at = datetime.now(UTC)
        return {
            "success": True,
            "started_at": self._call_stats_started_at,
            "entry_count": 0,
        }

    def _get_method_timeout(
        self,
        method_name: str,
        adapter_name: str,
        kwargs: Dict[str, Any],
    ) -> Optional[float]:
        """
        为核心同步方法提供保守的单源超时，避免某一个源长时间卡住整条链路。

        注意：
        - 这里只给 DataSync 主链路上的关键方法加超时。
        - 超时意味着当前数据源本次调用失败，交由后续源继续尝试。
        """
        is_full_market_daily = method_name == "get_daily" and kwargs.get("trade_date") and not kwargs.get("ts_code")
        is_full_market_daily_basic = method_name == "get_daily_basic" and kwargs.get("trade_date") and not kwargs.get("ts_code")

        if method_name == "get_index_daily":
            if adapter_name == "tushare":
                return 20.0
            if adapter_name == "baostock":
                return 12.0
            if adapter_name == "akshare":
                return 15.0

        if method_name in {"get_latest_trade_date", "get_trade_calendar"}:
            return 15.0 if adapter_name == "tushare" else 10.0

        if is_full_market_daily_basic:
            if adapter_name == "tushare":
                return 35.0
            if adapter_name == "baostock":
                return 20.0
            if adapter_name == "akshare":
                return 25.0

        if is_full_market_daily:
            if adapter_name == "tushare":
                return 45.0
            if adapter_name == "baostock":
                return 25.0
            if adapter_name == "akshare":
                return 30.0

        if method_name in {"get_moneyflow_industry", "get_moneyflow_concept"}:
            return 25.0

        if method_name == "get_limit_list":
            return 20.0

        return None

    def _get_source_chain_key(
        self,
        method_name: str,
        kwargs: Dict[str, Any],
    ) -> str:
        ts_code = kwargs.get("ts_code")
        has_single_ts_code = bool(ts_code) and isinstance(ts_code, str) and "," not in ts_code
        is_full_market_daily = method_name == "get_daily" and kwargs.get("trade_date") and not kwargs.get("ts_code")
        is_full_market_daily_basic = method_name == "get_daily_basic" and kwargs.get("trade_date") and not kwargs.get("ts_code")

        if method_name == "get_daily":
            if is_full_market_daily:
                return "get_daily.full_market"
            if has_single_ts_code:
                return "get_daily.single"
        if method_name == "get_daily_basic":
            if is_full_market_daily_basic:
                return "get_daily_basic.full_market"
            if has_single_ts_code:
                return "get_daily_basic.single"
        return method_name

    def _parse_source_chain_overrides(self) -> Dict[str, List[str]]:
        raw_value = settings.data_sync.source_chain_overrides or ""
        overrides: Dict[str, List[str]] = {}
        for item in raw_value.split(";"):
            item = item.strip()
            if not item or "=" not in item:
                continue
            key, value = item.split("=", 1)
            key = key.strip().replace(":", ".")
            chain = [source.strip() for source in value.split(",") if source.strip()]
            if key and chain:
                overrides[key] = chain
        return overrides

    def _get_configured_source_chain(
        self,
        method_name: str,
        kwargs: Dict[str, Any],
    ) -> Tuple[str, List[str], bool]:
        chain_key = self._get_source_chain_key(method_name, kwargs)
        overrides = self._parse_source_chain_overrides()
        for key in (chain_key, method_name):
            if key in overrides:
                return chain_key, overrides[key], True
        return chain_key, self.DEFAULT_SOURCE_CHAINS.get(chain_key, []), False

    def _parse_source_rate_limits(self) -> Dict[str, Tuple[float, int]]:
        """Parse per-source limits like ``tushare=200/m,coze=30/m``."""
        raw_value = str(settings.data_sync.source_rate_limits or "").strip()
        limits: Dict[str, Tuple[float, int]] = {}
        for item in raw_value.split(","):
            item = item.strip()
            if not item or "=" not in item:
                continue
            source, raw_limit = item.split("=", 1)
            source = source.strip().lower()
            raw_limit = raw_limit.strip().lower()
            if not source or not raw_limit:
                continue
            try:
                if raw_limit.endswith("/m"):
                    amount = float(raw_limit[:-2])
                    rate = amount / 60.0
                elif raw_limit.endswith("/s"):
                    amount = float(raw_limit[:-2])
                    rate = amount
                else:
                    amount = float(raw_limit)
                    rate = amount / 60.0
            except ValueError:
                continue
            if amount <= 0 or rate <= 0:
                continue
            limits[source] = (rate, max(1, int(amount)))
        return limits

    def _get_source_rate_limiter(self, source_name: str) -> Optional[TokenBucket]:
        source_key = str(source_name or "").lower()
        if not source_key:
            return None
        if source_key in self._source_rate_limiters:
            return self._source_rate_limiters[source_key]
        limit = self._parse_source_rate_limits().get(source_key)
        if not limit:
            return None
        rate, capacity = limit
        limiter = TokenBucket(rate=rate, capacity=capacity)
        self._source_rate_limiters[source_key] = limiter
        return limiter

    async def _wait_for_source_budget(self, source_name: str) -> None:
        limiter = self._get_source_rate_limiter(source_name)
        if limiter is None:
            return
        await limiter.wait_and_acquire(1)

    def _get_source_cooldown_remaining(self, source_name: str) -> float:
        cooldown_until = self._source_cooldowns.get(str(source_name or "").lower())
        if not cooldown_until:
            return 0.0
        remaining = cooldown_until - time.monotonic()
        if remaining <= 0:
            self._source_cooldowns.pop(str(source_name or "").lower(), None)
            return 0.0
        return remaining

    def _cool_down_source(self, source_name: str, seconds: Optional[float]) -> float:
        source_key = str(source_name or "").lower()
        if not source_key:
            return 0.0
        try:
            cooldown_seconds = float(seconds) if seconds is not None else float(
                settings.data_sync.source_rate_limit_cooldown_seconds
            )
        except Exception:
            cooldown_seconds = 60.0
        cooldown_seconds = max(cooldown_seconds, 0.0)
        if cooldown_seconds <= 0:
            return 0.0
        self._source_cooldowns[source_key] = time.monotonic() + cooldown_seconds
        return cooldown_seconds

    def get_source_rate_limit_status(self) -> Dict[str, Any]:
        configured = self._parse_source_rate_limits()
        cooldowns: Dict[str, float] = {}
        for source in set(configured) | set(self._source_cooldowns):
            remaining = self._get_source_cooldown_remaining(source)
            if remaining > 0:
                cooldowns[source] = round(remaining, 3)
        return {
            "success": True,
            "configured_sources": sorted(configured),
            "limits": {
                source: {"rate_per_second": rate, "capacity": capacity}
                for source, (rate, capacity) in configured.items()
            },
            "cooldowns": cooldowns,
        }

    def _get_default_preferred_sources(
        self,
        method_name: str,
        kwargs: Dict[str, Any],
    ) -> List[str]:
        """
        根据能力和调用形态给出默认首选数据源顺序。

        设计原则：
        - Coze 优先承担单股/实时/财务类请求
        - 全市场按交易日同步仍优先走 Tushare/传统源
        - 指数历史日线不强行走 Coze（当前 index_k 不稳定）
        """
        _, chain, _ = self._get_configured_source_chain(method_name, kwargs)
        preferred = [source for source in chain if source in self._adapter_map]

        return preferred

    # ==================== 通用数据获取方法 ====================

    async def _get_with_fallback(
        self,
        method_name: str,
        preferred_source: Optional[str] = None,
        **kwargs,
    ) -> Tuple[Any, Optional[str]]:
        """
        通用的降级获取方法

        Args:
            method_name: 要调用的方法名
            preferred_source: 优先使用的数据源名称
            **kwargs: 传递给方法的参数

        Returns:
            (data, source_name) - 数据和数据源名称
        """
        adapters = list(self._adapters)
        attempted_sources: List[str] = []
        attempt_outcomes: List[Dict[str, Any]] = []

        preferred_sources: List[str] = []
        source_chain_key, configured_chain, override_chain = self._get_configured_source_chain(method_name, kwargs)
        source_chain = configured_chain
        if preferred_source:
            preferred_sources = [preferred_source]
        else:
            preferred_sources = [source for source in configured_chain if source in self._adapter_map]

        if preferred_sources:
            reordered: List[AsyncDataSourceAdapter] = []
            added = set()
            for source_name in preferred_sources:
                adapter = self._adapter_map.get(source_name)
                if adapter and source_name not in added:
                    reordered.append(adapter)
                    added.add(source_name)
            if preferred_source or not override_chain:
                reordered.extend(adapter for adapter in adapters if adapter.name not in added)
            adapters = reordered

        for adapter in adapters:
            if not await adapter.is_available():
                continue

            method = getattr(adapter, method_name, None)
            if method is None:
                continue

            cooldown_remaining = self._get_source_cooldown_remaining(adapter.name)
            if cooldown_remaining > 0:
                attempted_sources.append(adapter.name)
                cooldown_until = datetime.now(UTC) + timedelta(seconds=cooldown_remaining)
                attempt_outcomes.append({
                    "source": adapter.name,
                    "status": "rate_limited",
                    "duration_ms": 0.0,
                    "error_type": "source_cooling_down",
                    "cooldown_remaining_seconds": round(cooldown_remaining, 3),
                    "error": f"Source cooling down for {cooldown_remaining:.1f}s",
                })
                self._record_call_outcome(
                    method_name=method_name,
                    adapter_name=adapter.name,
                    status="rate_limited",
                    duration_ms=0.0,
                    attempted_sources=attempted_sources,
                    error=f"Source cooling down for {cooldown_remaining:.1f}s",
                    error_type="source_cooling_down",
                    source_chain_key=source_chain_key,
                    source_chain=source_chain,
                    cooldown_until=cooldown_until,
                    cooldown_remaining_seconds=cooldown_remaining,
                )
                self.logger.warning(
                    "%s.%s skipped: source cooling down for %.1fs",
                    adapter.name,
                    method_name,
                    cooldown_remaining,
                )
                continue

            try:
                attempted_sources.append(adapter.name)
                started_at = time.perf_counter()
                await self._wait_for_source_budget(adapter.name)
                signature = inspect.signature(method)
                accepted_kwargs = {
                    key: value for key, value in kwargs.items()
                    if key in signature.parameters
                }
                timeout = self._get_method_timeout(method_name, adapter.name, kwargs)
                if timeout is not None:
                    result = await asyncio.wait_for(method(**accepted_kwargs), timeout=timeout)
                else:
                    result = await method(**accepted_kwargs)
                duration_ms = (time.perf_counter() - started_at) * 1000

                # 检查结果是否有效
                if result is not None:
                    if isinstance(result, (list, dict)):
                        if len(result) > 0:
                            self._record_call_outcome(
                                method_name=method_name,
                                adapter_name=adapter.name,
                                status="success",
                                duration_ms=duration_ms,
                                attempted_sources=attempted_sources,
                                source_chain_key=source_chain_key,
                                source_chain=source_chain,
                            )
                            return result, adapter.name
                    else:
                        self._record_call_outcome(
                            method_name=method_name,
                            adapter_name=adapter.name,
                            status="success",
                            duration_ms=duration_ms,
                            attempted_sources=attempted_sources,
                            source_chain_key=source_chain_key,
                            source_chain=source_chain,
                        )
                        return result, adapter.name
                attempt_outcomes.append({
                    "source": adapter.name,
                    "status": "empty",
                    "duration_ms": round(duration_ms, 3),
                })
                self._record_call_outcome(
                    method_name=method_name,
                    adapter_name=adapter.name,
                    status="empty",
                    duration_ms=duration_ms,
                    attempted_sources=attempted_sources,
                    source_chain_key=source_chain_key,
                    source_chain=source_chain,
                )
            except asyncio.TimeoutError:
                duration_ms = (time.perf_counter() - started_at) * 1000
                timeout = self._get_method_timeout(method_name, adapter.name, kwargs)
                attempt_outcomes.append({
                    "source": adapter.name,
                    "status": "timeout",
                    "duration_ms": round(duration_ms, 3),
                    "error_type": "timeout",
                    "error": f"Timed out after {timeout}s",
                })
                self._record_call_outcome(
                    method_name=method_name,
                    adapter_name=adapter.name,
                    status="timeout",
                    duration_ms=duration_ms,
                    attempted_sources=attempted_sources,
                    error=f"Timed out after {timeout}s",
                    error_type="timeout",
                    source_chain_key=source_chain_key,
                    source_chain=source_chain,
                )
                self.logger.warning(
                    f"{adapter.name}.{method_name} timed out after "
                    f"{timeout}s"
                )
                continue
            except DataSourceHttpError as e:
                duration_ms = getattr(e, "duration_ms", None) or (time.perf_counter() - started_at) * 1000
                error_type = str(getattr(e, "error_type", "") or "http_error")
                status_code = getattr(e, "status_code", None)
                retry_after_seconds = getattr(e, "retry_after_seconds", None)
                status = error_type if error_type in {
                    "timeout",
                    "rate_limited",
                    "service_unavailable",
                    "server_error",
                    "network_error",
                    "http_error",
                } else "failed"
                attempt_outcomes.append({
                    "source": adapter.name,
                    "status": status,
                    "duration_ms": round(duration_ms, 3),
                    "error_type": error_type,
                    "status_code": status_code,
                    "error": str(e),
                })
                cooldown_until = None
                cooldown_remaining_seconds = None
                if status == "rate_limited":
                    cooldown_remaining_seconds = self._cool_down_source(
                        adapter.name,
                        retry_after_seconds,
                    )
                    if cooldown_remaining_seconds > 0:
                        cooldown_until = datetime.now(UTC) + timedelta(seconds=cooldown_remaining_seconds)
                        attempt_outcomes[-1]["cooldown_remaining_seconds"] = round(cooldown_remaining_seconds, 3)
                self._record_call_outcome(
                    method_name=method_name,
                    adapter_name=adapter.name,
                    status=status,
                    duration_ms=duration_ms,
                    attempted_sources=attempted_sources,
                    error=str(e),
                    error_type=error_type,
                    status_code=status_code,
                    source_chain_key=source_chain_key,
                    source_chain=source_chain,
                    cooldown_until=cooldown_until,
                    cooldown_remaining_seconds=cooldown_remaining_seconds,
                )
                self.logger.warning(
                    f"{adapter.name}.{method_name} failed: "
                    f"error_type={error_type}, status_code={status_code}, error={e}"
                )
                continue
            except Exception as e:
                duration_ms = (time.perf_counter() - started_at) * 1000
                attempt_outcomes.append({
                    "source": adapter.name,
                    "status": "failed",
                    "duration_ms": round(duration_ms, 3),
                    "error_type": type(e).__name__,
                    "error": str(e),
                })
                self._record_call_outcome(
                    method_name=method_name,
                    adapter_name=adapter.name,
                    status="failed",
                    duration_ms=duration_ms,
                    attempted_sources=attempted_sources,
                    error=str(e),
                    error_type=type(e).__name__,
                    source_chain_key=source_chain_key,
                    source_chain=source_chain,
                )
                self.logger.warning(f"{adapter.name}.{method_name} failed: {e}")
                continue

        if attempt_outcomes and all(item.get("status") != "empty" for item in attempt_outcomes):
            raise DataSourceChainError(method_name, attempted_sources, attempt_outcomes)

        return None, None

    # ==================== 股票基础信息 ====================

    async def get_stock_basic(
        self,
        ts_code: Optional[str] = None,
        list_status: str = "L",
        preferred_source: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """获取股票基础信息"""
        return await self._get_with_fallback(
            "get_stock_basic",
            preferred_source=preferred_source,
            ts_code=ts_code,
            list_status=list_status,
        )

    # ==================== 日线数据 ====================

    async def get_daily(
        self,
        ts_code: Optional[str] = None,
        trade_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        adj: str = "qfq",
        preferred_source: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """获取日线行情"""
        return await self._get_with_fallback(
            "get_daily",
            preferred_source=preferred_source,
            ts_code=ts_code,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            adj=adj,
        )

    async def get_daily_basic(
        self,
        ts_code: Optional[str] = None,
        trade_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        preferred_source: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """获取每日指标"""
        return await self._get_with_fallback(
            "get_daily_basic",
            preferred_source=preferred_source,
            ts_code=ts_code,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
        )

    # ==================== 实时行情 ====================

    async def get_realtime_quotes(
        self,
        ts_codes: Optional[List[str]] = None,
        batch_size: int = 50,
        timeout: float = 2.0,
        preferred_source: Optional[str] = None,
    ) -> Tuple[Dict[str, Dict[str, Any]], Optional[str]]:
        """获取实时行情"""
        return await self._get_with_fallback(
            "get_realtime_quotes",
            preferred_source=preferred_source,
            ts_codes=ts_codes,
            batch_size=batch_size,
            timeout=timeout,
        )

    async def get_realtime_index_quotes(
        self,
        preferred_source: Optional[str] = None,
    ) -> Tuple[Dict[str, Dict[str, Any]], Optional[str]]:
        """获取指数实时行情"""
        return await self._get_with_fallback(
            "get_realtime_index_quotes",
            preferred_source=preferred_source,
        )

    # ==================== 财务数据 ====================

    async def get_financial_indicator(
        self,
        ts_code: str,
        period: Optional[str] = None,
        limit: Optional[int] = None,
        preferred_source: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """获取财务指标"""
        return await self._get_with_fallback(
            "get_financial_indicator",
            preferred_source=preferred_source,
            ts_code=ts_code,
            period=period,
            limit=limit,
        )

    async def get_financial_data(
        self,
        ts_code: str,
        limit: int = 4,
        preferred_source: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """获取完整财务数据"""
        return await self._get_with_fallback(
            "get_financial_data",
            preferred_source=preferred_source,
            ts_code=ts_code,
            limit=limit,
        )

    async def get_income_statement(
        self,
        ts_code: str,
        period: Optional[str] = None,
        limit: Optional[int] = None,
        preferred_source: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """获取利润表"""
        return await self._get_with_fallback(
            "get_income_statement",
            preferred_source=preferred_source,
            ts_code=ts_code,
            period=period,
            limit=limit,
        )

    async def get_balance_sheet(
        self,
        ts_code: str,
        period: Optional[str] = None,
        limit: Optional[int] = None,
        preferred_source: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """获取资产负债表"""
        return await self._get_with_fallback(
            "get_balance_sheet",
            preferred_source=preferred_source,
            ts_code=ts_code,
            period=period,
            limit=limit,
        )

    async def get_cashflow_statement(
        self,
        ts_code: str,
        period: Optional[str] = None,
        limit: Optional[int] = None,
        preferred_source: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """获取现金流量表"""
        return await self._get_with_fallback(
            "get_cashflow_statement",
            preferred_source=preferred_source,
            ts_code=ts_code,
            period=period,
            limit=limit,
        )

    # ==================== 资金流向 ====================

    async def get_moneyflow_industry(
        self,
        trade_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        preferred_source: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """获取行业资金流向"""
        return await self._get_with_fallback(
            "get_moneyflow_industry",
            preferred_source=preferred_source,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
        )

    async def get_moneyflow_concept(
        self,
        trade_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        preferred_source: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """获取概念板块资金流向"""
        return await self._get_with_fallback(
            "get_moneyflow_concept",
            preferred_source=preferred_source,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
        )

    async def get_moneyflow_hsgt(
        self,
        trade_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        preferred_source: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """获取沪深港通资金流向"""
        return await self._get_with_fallback(
            "get_moneyflow_hsgt",
            preferred_source=preferred_source,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
        )

    # ==================== 涨跌停 ====================

    async def get_limit_list(
        self,
        trade_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        ts_code: Optional[str] = None,
        limit_type: Optional[str] = None,
        preferred_source: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """获取涨跌停统计"""
        return await self._get_with_fallback(
            "get_limit_list",
            preferred_source=preferred_source,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
            limit_type=limit_type,
        )

    async def get_stk_limit(
        self,
        trade_date: Optional[str] = None,
        preferred_source: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """获取涨跌停价格"""
        return await self._get_with_fallback(
            "get_stk_limit",
            preferred_source=preferred_source,
            trade_date=trade_date,
        )

    # ==================== 指数 ====================

    async def get_index_basic(
        self,
        market: str = "SSE",
        ts_code: Optional[str] = None,
        preferred_source: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """获取指数基础信息"""
        return await self._get_with_fallback(
            "get_index_basic",
            preferred_source=preferred_source,
            market=market,
            ts_code=ts_code,
        )

    async def get_index_daily(
        self,
        ts_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        preferred_source: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """获取指数日线"""
        return await self._get_with_fallback(
            "get_index_daily",
            preferred_source=preferred_source,
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )

    # ==================== 交易日历 ====================

    async def get_trade_calendar(
        self,
        start_date: str,
        end_date: str,
        preferred_source: Optional[str] = None,
    ) -> Tuple[List[str], Optional[str]]:
        """获取交易日列表"""
        return await self._get_with_fallback(
            "get_trade_calendar",
            preferred_source=preferred_source,
            start_date=start_date,
            end_date=end_date,
        )

    async def get_latest_trade_date(
        self,
        preferred_source: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        """获取最近交易日"""
        return await self._get_with_fallback(
            "get_latest_trade_date",
            preferred_source=preferred_source,
        )

    async def is_trading_time(self) -> bool:
        """检查当前是否为交易时间"""
        for adapter in self._adapters:
            if await adapter.is_available():
                return await adapter.is_trading_time()
        return False

    # ==================== 新闻 ====================

    async def get_news(
        self,
        ts_code: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 50,
        preferred_source: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """获取新闻"""
        return await self._get_with_fallback(
            "get_news",
            preferred_source=preferred_source,
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )

    async def get_stock_news(
        self,
        symbol: str,
        limit: int = 20,
        preferred_source: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """获取个股新闻"""
        return await self._get_with_fallback(
            "get_stock_news",
            preferred_source=preferred_source,
            symbol=symbol,
            limit=limit,
        )

    # ==================== K线 ====================

    async def get_kline(
        self,
        code: str,
        period: str = "day",
        limit: int = 120,
        adj: Optional[str] = None,
        preferred_source: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """获取K线数据"""
        return await self._get_with_fallback(
            "get_kline",
            preferred_source=preferred_source,
            code=code,
            period=period,
            limit=limit,
            adj=adj,
        )

    # ==================== 同花顺板块数据（复盘用） ====================

    async def get_ths_index(
        self,
        ts_code: Optional[str] = None,
        exchange: Optional[str] = None,
        type: Optional[str] = None,
        preferred_source: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """获取同花顺板块列表"""
        return await self._get_with_fallback(
            "get_ths_index",
            preferred_source=preferred_source,
            ts_code=ts_code,
            exchange=exchange,
            type=type,
        )

    async def get_ths_member(
        self,
        ts_code: str,
        preferred_source: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """获取同花顺板块成分股"""
        return await self._get_with_fallback(
            "get_ths_member",
            preferred_source=preferred_source,
            ts_code=ts_code,
        )

    async def get_ths_daily(
        self,
        ts_code: Optional[str] = None,
        trade_date: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        preferred_source: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """获取同花顺板块日线行情"""
        return await self._get_with_fallback(
            "get_ths_daily",
            preferred_source=preferred_source,
            ts_code=ts_code,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
        )

    # ==================== 连板数据（复盘用） ====================

    async def get_limit_step(
        self,
        trade_date: str,
        preferred_source: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """获取连板天梯"""
        return await self._get_with_fallback(
            "get_limit_step",
            preferred_source=preferred_source,
            trade_date=trade_date,
        )

    async def get_limit_cpt_list(
        self,
        trade_date: str,
        preferred_source: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """获取最强板块统计"""
        return await self._get_with_fallback(
            "get_limit_cpt_list",
            preferred_source=preferred_source,
            trade_date=trade_date,
        )

    # ==================== 龙虎榜数据（复盘用） ====================

    async def get_top_inst(
        self,
        trade_date: str,
        ts_code: Optional[str] = None,
        preferred_source: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """获取龙虎榜机构买卖明细"""
        return await self._get_with_fallback(
            "get_top_inst",
            preferred_source=preferred_source,
            trade_date=trade_date,
            ts_code=ts_code,
        )

    async def get_hm_list(
        self,
        preferred_source: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """获取游资营业部名录"""
        return await self._get_with_fallback(
            "get_hm_list",
            preferred_source=preferred_source,
        )

    # ==================== 热股数据（复盘用） ====================

    async def get_ths_hot(
        self,
        trade_date: Optional[str] = None,
        ts_code: Optional[str] = None,
        preferred_source: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """获取同花顺热股排行"""
        return await self._get_with_fallback(
            "get_ths_hot",
            preferred_source=preferred_source,
            trade_date=trade_date,
            ts_code=ts_code,
        )

# 全局单例
data_source_manager = DataSourceManager()
