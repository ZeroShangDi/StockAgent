"""项目运行态能力巡检。"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
import socket
import time

from core.managers import (
    data_source_manager,
    mongo_manager,
    redis_manager,
)
from core.settings import settings


StatusLevel = str
SectionName = str

SECTION_KEYS = ("services", "data_sources", "datasets", "features")
CACHE_TTL_SECONDS = 30.0
_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_LOCKS: Dict[str, asyncio.Lock] = {}

DATA_SOURCE_INTERFACE_META = [
    ("stock_basic", "股票列表", "股票基础信息、搜索候选、自选股添加入口"),
    ("daily_quotes", "日线行情", "个股历史日线、批量日线、K线基础来源"),
    ("daily_basic", "每日指标", "PE/PB、换手率、市值等估值指标"),
    ("realtime_quotes", "实时行情", "自选股实时价格、盘口快照"),
    ("financial_data", "财务数据", "财务指标、报表、基本面分析"),
    ("money_flow", "资金流向", "行业/概念/个股资金流向"),
    ("limit_data", "涨跌停", "涨跌停榜、涨跌停价格"),
    ("index_data", "指数数据", "指数实时行情与指数历史日线"),
    ("trade_calendar", "交易日历", "最近交易日、交易日范围判断"),
    ("news", "新闻公告", "个股新闻、公告、热点新闻来源"),
    ("kline", "K线数据", "日/周/月/分钟级 K 线"),
]

DATA_SOURCE_MATRIX_META = [
    ("stock_basic_full", "全市场股票列表", "全量股票基础信息与搜索候选主数据", "stock_basic"),
    ("stock_basic_single", "单股基础信息", "股票详情、监听配置等单股基础资料", "stock_basic"),
    ("daily_single", "单股日线", "单只股票历史 K 线与详情图表", "daily_quotes"),
    ("daily_market", "全市场日线", "按交易日整市场同步 stock_daily", "daily_quotes"),
    ("daily_basic_single", "单股每日指标", "PE/PB/换手率/市值等指标", "daily_basic"),
    ("realtime_quotes", "实时行情", "自选股报价、实时快照", "realtime_quotes"),
    ("financial_indicator", "财务指标", "财报关键指标与基本面数据", "financial_data"),
    ("index_daily", "指数历史日线", "上证/深证/创业板等指数日线", "index_data"),
    ("trade_calendar", "交易日历", "最近交易日、交易日范围判断", "trade_calendar"),
]

DATA_SOURCE_DESCRIPTIONS = {
    "tushare": "官方 Pro 数据源，覆盖面最全，但当前账号部分接口有权限或频率限制。",
    "akshare": "免费公开数据聚合源，覆盖较广，适合作为 Tushare 的免费回退。",
    "baostock": "免费量化数据源，指数与日线稳定，但实时和部分指标能力有限。",
    "coze": "通过 Coze 工作流封装的单股数据源，实时/单股日线/财务强，但不适合全市场批量主同步。",
}

COZE_PLUGIN_META = [
    {
        "key": "etf_current",
        "name": "ETF 实时行情",
        "description": "获取单个 ETF/基金的实时行情",
        "params": {"fund_code": "510300"},
        "used_in_project": False,
        "usage_description": "当前项目暂无直接调用入口",
    },
    {
        "key": "stock_current",
        "name": "股票实时行情",
        "description": "获取单个股票的实时最新行情数据",
        "params": {"stock_code": "000001"},
        "used_in_project": True,
        "usage_description": "Coze 实时行情主入口，自选股/监听/策略实时判断依赖它",
    },
    {
        "key": "stock_k",
        "name": "股票 K 线",
        "description": "获取单个股票的 K 线行情信息",
        "params_builder": "stock_k",
        "used_in_project": True,
        "usage_description": "单股日线、K 线、交易日历派生和部分 daily_basic 依赖它",
    },
    {
        "key": "stock_shares",
        "name": "股票股本信息",
        "description": "获取单个股票的股本信息",
        "params": {"stock_code": "000001"},
        "used_in_project": True,
        "usage_description": "daily_basic 的总股本/流通股本/市值计算依赖它",
    },
    {
        "key": "stock_latest_buy",
        "name": "最新分时成交",
        "description": "获取单个股票的成交分时",
        "params": {"stock_code": "000001"},
        "used_in_project": False,
        "usage_description": "当前项目暂无直接调用入口",
    },
    {
        "key": "stock_min_flow",
        "name": "股票分时资金流向",
        "description": "获取单个股票的分时资金流向",
        "params": {"stock_code": "000001"},
        "used_in_project": False,
        "usage_description": "当前项目暂无直接调用入口",
    },
    {
        "key": "etf_min",
        "name": "ETF 分时行情",
        "description": "获取单个 ETF 的分时行情",
        "params": {"fund_code": "510300"},
        "used_in_project": False,
        "usage_description": "当前项目暂无 ETF 模块接入",
    },
    {
        "key": "index_k",
        "name": "指数 K 线",
        "description": "获取单个指数的 K 线行情",
        "params_builder": "index_k",
        "used_in_project": True,
        "usage_description": "Coze 指数历史日线候选能力，但当前项目默认改走免费源",
    },
    {
        "key": "stock_east_hot",
        "name": "东方财富人气榜",
        "description": "获取东方财富人气榜 TOP100 股票",
        "params": {},
        "used_in_project": False,
        "usage_description": "当前项目暂无直接调用入口",
    },
    {
        "key": "etf_k",
        "name": "ETF K 线",
        "description": "获取单个 ETF/基金的日周月 K 线",
        "params": {"fund_code": "510300", "k_type": 1},
        "used_in_project": False,
        "usage_description": "当前项目暂无 ETF 模块接入",
    },
    {
        "key": "index_current_data",
        "name": "指数实时行情",
        "description": "获取主要指数实时行情",
        "params": {"index_code": "000001"},
        "used_in_project": True,
        "usage_description": "指数实时行情可作为市场概览候选来源",
    },
    {
        "key": "stock_min",
        "name": "股票分时行情",
        "description": "获取单个股票分时行情",
        "params": {"stock_code": "000001"},
        "used_in_project": False,
        "usage_description": "当前项目暂无直接调用入口",
    },
    {
        "key": "stock_fin_data",
        "name": "财务核心指标",
        "description": "获取单只股票财务核心指标",
        "params": {"stock_code": "000001"},
        "used_in_project": True,
        "usage_description": "财务指标与一句话选股/分析类能力的 Coze 财务入口",
    },
    {
        "key": "stock_dividend",
        "name": "历史分红信息",
        "description": "获取股票全部历史分红信息",
        "params": {"stock_code": "000001"},
        "used_in_project": False,
        "usage_description": "当前项目暂无直接调用入口",
    },
    {
        "key": "info_all_code",
        "name": "全市场股票代码列表",
        "description": "获取 A 股全部股票代码信息",
        "params": {},
        "used_in_project": True,
        "usage_description": "Coze 股票列表候选入口，但当前不作为主列表源",
    },
    {
        "key": "stock_ths_hot_concept",
        "name": "同花热门概念板块",
        "description": "获取热门概念板块",
        "params": {},
        "used_in_project": False,
        "usage_description": "当前项目暂无直接调用入口",
    },
    {
        "key": "stock_day_flow",
        "name": "股票日资金流向",
        "description": "获取股票日资金流入流向",
        "params_builder": "stock_day_flow",
        "used_in_project": False,
        "usage_description": "当前项目暂无直接调用入口，但后续资金流模块可能会接入",
    },
    {
        "key": "index_min",
        "name": "指数分时行情",
        "description": "获取指数分时行情",
        "params": {"index_code": "000001"},
        "used_in_project": False,
        "usage_description": "当前项目暂无直接调用入口",
    },
    {
        "key": "stock_five",
        "name": "股票五档行情",
        "description": "获取单个股票五档盘口",
        "params": {"stock_code": "000001"},
        "used_in_project": False,
        "usage_description": "当前项目暂无盘口模块接入",
    },
    {
        "key": "stock_ths_hot",
        "name": "同花顺热股榜",
        "description": "获取同花顺热股 TOP100",
        "params": {},
        "used_in_project": False,
        "usage_description": "当前项目暂无直接调用入口",
    },
]


async def _run_with_timeout(coro: Any, timeout: float, default: Any = None) -> Any:
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        return default


def _status_item(
    key: str,
    name: str,
    status: StatusLevel,
    reason: str = "",
    *,
    endpoint: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "status": status,
        "reason": reason,
        "endpoint": endpoint,
        "details": details or {},
    }


def _dataset_item(
    key: str,
    name: str,
    status: StatusLevel,
    count: int,
    reason: str = "",
    *,
    latest_value: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    item = _status_item(key, name, status, reason, details=details)
    item["count"] = count
    item["latest_value"] = latest_value
    return item


def _get_cache_lock(cache_key: str) -> asyncio.Lock:
    lock = _CACHE_LOCKS.get(cache_key)
    if lock is None:
        lock = asyncio.Lock()
        _CACHE_LOCKS[cache_key] = lock
    return lock


async def _get_cached(cache_key: str, builder: Any, *, force_refresh: bool = False) -> Dict[str, Any]:
    now = time.monotonic()
    cached = _CACHE.get(cache_key)
    if not force_refresh and cached and now - cached["ts"] < CACHE_TTL_SECONDS:
        return cached["value"]

    async with _get_cache_lock(cache_key):
        cached = _CACHE.get(cache_key)
        now = time.monotonic()
        if not force_refresh and cached and now - cached["ts"] < CACHE_TTL_SECONDS:
            return cached["value"]

        value = await builder()
        _CACHE[cache_key] = {
            "ts": time.monotonic(),
            "value": value,
        }
        return value


def _build_interface_items(
    adapter_name: str,
    capability: Any,
    *,
    adapter_available: bool,
    overrides: Optional[Dict[str, Dict[str, str]]] = None,
) -> List[Dict[str, Any]]:
    interfaces: List[Dict[str, Any]] = []
    override_map = overrides or {}

    for key, name, description in DATA_SOURCE_INTERFACE_META:
        supported = bool(getattr(capability, key, False))
        if not supported:
            status = "unavailable"
            reason = "该数据源未实现此接口"
        elif not adapter_available:
            status = "unavailable"
            reason = "适配器当前不可用，相关接口无法调用"
        else:
            status = "available"
            reason = "当前探测未发现阻塞问题"

        if key in override_map:
            status = override_map[key].get("status", status)
            reason = override_map[key].get("reason", reason)

        interfaces.append(
            {
                "key": key,
                "name": name,
                "status": status,
                "reason": reason,
                "description": description,
            }
        )
    return interfaces


def _with_data_source_details(
    item: Dict[str, Any],
    *,
    adapter: Any,
    interfaces: List[Dict[str, Any]],
    extra_details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    details = dict(item.get("details") or {})
    details.update(
        {
            "priority": getattr(adapter, "priority", None),
            "description": DATA_SOURCE_DESCRIPTIONS.get(adapter.name, ""),
            "interfaces": interfaces,
        }
    )
    if extra_details:
        details.update(extra_details)
    item["details"] = details
    return item


def _recent_probe_window() -> tuple[str, str]:
    end = date.today() - timedelta(days=4)
    while end.weekday() >= 5:
        end -= timedelta(days=1)
    start = end - timedelta(days=2)
    while start.weekday() >= 5:
        start -= timedelta(days=1)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def _recent_probe_window_hyphenated() -> tuple[str, str]:
    start, end = _recent_probe_window()
    return f"{start[:4]}-{start[4:6]}-{start[6:8]}", f"{end[:4]}-{end[4:6]}-{end[6:8]}"


def _format_percentage(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "0.0%"
    return f"{numerator / denominator * 100:.1f}%"


def _build_coze_probe_params(meta: Dict[str, Any]) -> Dict[str, Any]:
    builder = meta.get("params_builder")
    if not builder:
        return dict(meta.get("params") or {})

    if builder == "stock_k":
        start_date, end_date = _recent_probe_window_hyphenated()
        return {
            "stock_code": "000001",
            "k_type": 1,
            "adjust_type": 1,
            "start_date": start_date,
            "end_date": end_date,
        }

    if builder == "index_k":
        start_date, _ = _recent_probe_window_hyphenated()
        return {
            "index_code": "000001",
            "k_type": 1,
            "start_date": start_date,
        }

    if builder == "stock_day_flow":
        start_date, end_date = _recent_probe_window_hyphenated()
        return {
            "stock_code": "000001",
            "start_date": start_date,
            "end_date": end_date,
        }

    return dict(meta.get("params") or {})


def _extract_coze_payload_metrics(payload: Any) -> Dict[str, Any]:
    top_level_keys: List[str] = []
    array_counts: Dict[str, int] = {}
    primary_key = ""
    primary_count = 0
    sample: Optional[Dict[str, Any]] = None

    if isinstance(payload, dict):
        top_level_keys = list(payload.keys())
        for key, value in payload.items():
            if isinstance(value, list):
                array_counts[key] = len(value)
                if len(value) > primary_count:
                    primary_key = key
                    primary_count = len(value)
                    if value and isinstance(value[0], dict):
                        sample = value[0]
            elif isinstance(value, dict) and sample is None:
                sample = value
        if primary_count <= 0 and isinstance(payload.get("data"), dict):
            sample = payload.get("data")
    elif isinstance(payload, list):
        primary_key = "data"
        primary_count = len(payload)
        if payload and isinstance(payload[0], dict):
            sample = payload[0]

    has_data = primary_count > 0 or bool(sample)
    sample_keys = list(sample.keys())[:8] if isinstance(sample, dict) else []
    return {
        "has_data": has_data,
        "primary_key": primary_key,
        "primary_count": primary_count,
        "array_counts": array_counts,
        "top_level_keys": top_level_keys,
        "sample_keys": sample_keys,
    }


async def _ensure_optional_managers() -> Dict[str, Optional[str]]:
    notes: Dict[str, Optional[str]] = {
        "data_source": None,
    }

    if not data_source_manager.is_initialized:
        try:
            await asyncio.wait_for(data_source_manager.initialize(), timeout=10.0)
        except Exception as exc:  # pragma: no cover - runtime probe
            notes["data_source"] = str(exc)

    return notes


async def _probe_tcp_port(host: str, port: int, timeout: float = 1.0) -> bool:
    def _connect() -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    return await asyncio.to_thread(_connect)


async def _get_collection_snapshot(collection: str) -> Dict[str, Any]:
    count = await mongo_manager.count(collection, {})
    latest_value = None
    if count > 0:
        sort_fields = [("trade_date", -1), ("date", -1), ("created_at", -1)]
        for field, direction in sort_fields:
            doc = await mongo_manager.find_one(
                collection,
                {},
                sort=[(field, direction)],
                projection={field: 1, "_id": 0},
            )
            if doc and doc.get(field):
                value = doc.get(field)
                latest_value = value.isoformat() if hasattr(value, "isoformat") else str(value)
                break
    return {
        "count": count,
        "latest_value": latest_value,
    }


async def _get_trade_date_coverage(collection: str, trade_date: Optional[str]) -> int:
    if not trade_date:
        return 0
    return len(await mongo_manager.db[collection].distinct("ts_code", {"trade_date": trade_date}))


async def _probe_tushare_adapter(adapter: Any) -> Dict[str, Any]:
    start_date, end_date = _recent_probe_window()
    issues: List[str] = []
    details: Dict[str, Any] = {"priority": adapter.priority}
    interface_overrides: Dict[str, Dict[str, str]] = {}

    try:
        daily = await _run_with_timeout(
            adapter.get_daily(
                ts_code="000001.SZ",
                start_date=start_date,
                end_date=end_date,
            ),
            timeout=4.0,
        )
        details["daily_count"] = len(daily or [])
    except Exception as exc:
        item = _status_item(
            "tushare",
            "Tushare",
            "unavailable",
            f"日线探测失败：{exc}",
            details=details,
        )
        interfaces = _build_interface_items(
            adapter.name,
            adapter.capability,
            adapter_available=False,
        )
        return _with_data_source_details(item, adapter=adapter, interfaces=interfaces)

    daily_basic, index_daily, trade_calendar = await asyncio.gather(
        _run_with_timeout(
            adapter.get_daily_basic(
                ts_code="000001.SZ",
                start_date=end_date,
                end_date=end_date,
            ),
            timeout=4.0,
            default=[],
        ),
        _run_with_timeout(
            adapter.get_index_daily(
                ts_code="000001.SH",
                start_date=end_date,
                end_date=end_date,
            ),
            timeout=4.0,
            default=[],
        ),
        _run_with_timeout(
            adapter.get_trade_calendar(start_date=start_date, end_date=end_date),
            timeout=4.0,
            default=[],
        ),
    )

    if not daily_basic:
        reason = "当前 Token 没有 `daily_basic` 权限，估值与换手率等指标不可直接用"
        issues.append(reason)
        interface_overrides["daily_basic"] = {"status": "degraded", "reason": reason}
    if not index_daily:
        reason = "当前 Token 没有 `index_daily` 权限，指数历史日线需要其他源回退"
        issues.append(reason)
        interface_overrides["index_data"] = {"status": "degraded", "reason": reason}
    if not trade_calendar:
        reason = "`trade_cal` 无权限，最近交易日会回退到其他源或工作日兜底"
        issues.append(reason)
        interface_overrides["trade_calendar"] = {"status": "degraded", "reason": reason}

    status = "degraded" if issues else "available"
    reason = "；".join(issues) if issues else "日线可用，且核心探测通过"
    interfaces = _build_interface_items(
        adapter.name,
        adapter.capability,
        adapter_available=True,
        overrides=interface_overrides,
    )
    item = _status_item("tushare", "Tushare", status, reason, details=details)
    return _with_data_source_details(item, adapter=adapter, interfaces=interfaces)


async def _probe_coze_adapter(adapter: Any) -> Dict[str, Any]:
    start_date, end_date = _recent_probe_window()
    issues: List[str] = []
    details: Dict[str, Any] = {"priority": adapter.priority}
    interface_overrides: Dict[str, Dict[str, str]] = {}

    try:
        daily = await _run_with_timeout(
            adapter.get_daily(
                ts_code="000001.SZ",
                start_date=start_date,
                end_date=end_date,
            ),
            timeout=4.0,
        )
        details["daily_count"] = len(daily or [])
    except Exception as exc:
        item = _status_item(
            "coze",
            "Coze 工作流",
            "unavailable",
            f"日线探测失败：{exc}",
            details=details,
        )
        interfaces = _build_interface_items(
            adapter.name,
            adapter.capability,
            adapter_available=False,
        )
        return _with_data_source_details(item, adapter=adapter, interfaces=interfaces)

    stock_basic, index_daily = await asyncio.gather(
        _run_with_timeout(adapter.get_stock_basic(), timeout=4.0, default=[]),
        _run_with_timeout(
            adapter.get_index_daily(
                ts_code="000001.SH",
                start_date=end_date,
                end_date=end_date,
            ),
            timeout=4.0,
            default=[],
        ),
    )

    details["stock_basic_count"] = len(stock_basic or [])
    if len(stock_basic or []) < 3000:
        reason = f"`info_all_code` 当前仅返回 {len(stock_basic or [])} 条股票，不适合作为完整股票列表主源"
        issues.append(reason)
        interface_overrides["stock_basic"] = {"status": "degraded", "reason": reason}

    if not index_daily:
        reason = "`index_k` 当前返回空数据，Coze 暂不适合作为指数历史 K 线主源"
        issues.append(reason)
        interface_overrides["index_data"] = {"status": "degraded", "reason": reason}

    interface_overrides["money_flow"] = {"status": "unavailable", "reason": "当前工作流未封装稳定的资金流接口"}
    interface_overrides["limit_data"] = {"status": "unavailable", "reason": "当前工作流未封装涨跌停接口"}
    interface_overrides["news"] = {"status": "unavailable", "reason": "当前工作流未封装新闻/公告接口"}

    status = "degraded" if issues else "available"
    reason = "；".join(issues) if issues else "实时/日线/财务探测通过"
    interfaces = _build_interface_items(
        adapter.name,
        adapter.capability,
        adapter_available=True,
        overrides=interface_overrides,
    )
    item = _status_item("coze", "Coze 工作流", status, reason, details=details)
    return _with_data_source_details(item, adapter=adapter, interfaces=interfaces)


async def _build_coze_plugin_status_data() -> Dict[str, Any]:
    optional_notes = await _ensure_optional_managers()
    generated_at = datetime.now().isoformat()

    if optional_notes.get("data_source"):
        return {
            "generated_at": generated_at,
            "summary": {"available": 0, "degraded": 0, "unavailable": len(COZE_PLUGIN_META)},
            "plugins": [
                {
                    "key": meta["key"],
                    "name": meta["name"],
                    "status": "unavailable",
                    "reason": f"统一数据源初始化失败：{optional_notes['data_source']}",
                    "description": meta["description"],
                    "params": _build_coze_probe_params(meta),
                    "latency_ms": None,
                    "data_count": 0,
                    "top_level_keys": [],
                    "sample_keys": [],
                    "used_in_project": meta["used_in_project"],
                    "usage_description": meta["usage_description"],
                }
                for meta in COZE_PLUGIN_META
            ],
        }

    adapter = next((item for item in getattr(data_source_manager, "_adapters", []) if item.name == "coze"), None)
    if adapter is None or not await adapter.is_available():
        reason = "Coze 适配器未初始化或当前不可用"
        return {
            "generated_at": generated_at,
            "summary": {"available": 0, "degraded": 0, "unavailable": len(COZE_PLUGIN_META)},
            "plugins": [
                {
                    "key": meta["key"],
                    "name": meta["name"],
                    "status": "unavailable",
                    "reason": reason,
                    "description": meta["description"],
                    "params": _build_coze_probe_params(meta),
                    "latency_ms": None,
                    "data_count": 0,
                    "top_level_keys": [],
                    "sample_keys": [],
                    "used_in_project": meta["used_in_project"],
                    "usage_description": meta["usage_description"],
                }
                for meta in COZE_PLUGIN_META
            ],
        }

    semaphore = asyncio.Semaphore(6)

    async def _probe_plugin(meta: Dict[str, Any]) -> Dict[str, Any]:
        params = _build_coze_probe_params(meta)
        async with semaphore:
            started_at = time.perf_counter()
            try:
                payload = await _run_with_timeout(adapter._run_plugin(meta["key"], params), timeout=8.0)
                latency_ms = round((time.perf_counter() - started_at) * 1000, 1)
                if payload is None:
                    status = "degraded"
                    reason = "请求超时或未返回可解析结果"
                    metrics = {
                        "primary_count": 0,
                        "primary_key": "",
                        "top_level_keys": [],
                        "sample_keys": [],
                    }
                else:
                    metrics = _extract_coze_payload_metrics(payload)
                    if metrics["has_data"]:
                        status = "available"
                        reason = "请求成功且返回了可解析数据"
                    else:
                        status = "degraded"
                        reason = "请求成功，但当前返回空数据或无法识别的数据结构"

                return {
                    "key": meta["key"],
                    "name": meta["name"],
                    "status": status,
                    "reason": reason,
                    "description": meta["description"],
                    "params": params,
                    "latency_ms": latency_ms,
                    "data_count": metrics["primary_count"],
                    "data_key": metrics["primary_key"] or None,
                    "top_level_keys": metrics["top_level_keys"],
                    "sample_keys": metrics["sample_keys"],
                    "used_in_project": meta["used_in_project"],
                    "usage_description": meta["usage_description"],
                }
            except Exception as exc:
                latency_ms = round((time.perf_counter() - started_at) * 1000, 1)
                return {
                    "key": meta["key"],
                    "name": meta["name"],
                    "status": "unavailable",
                    "reason": str(exc),
                    "description": meta["description"],
                    "params": params,
                    "latency_ms": latency_ms,
                    "data_count": 0,
                    "data_key": None,
                    "top_level_keys": [],
                    "sample_keys": [],
                    "used_in_project": meta["used_in_project"],
                    "usage_description": meta["usage_description"],
                }

    plugins = await asyncio.gather(*[_probe_plugin(meta) for meta in COZE_PLUGIN_META])
    summary = {
        "available": sum(1 for item in plugins if item["status"] == "available"),
        "degraded": sum(1 for item in plugins if item["status"] == "degraded"),
        "unavailable": sum(1 for item in plugins if item["status"] == "unavailable"),
    }

    return {
        "generated_at": generated_at,
        "summary": summary,
        "plugins": plugins,
    }


async def _probe_generic_adapter(adapter: Any) -> Dict[str, Any]:
    try:
        healthy = await _run_with_timeout(adapter.health_check(), timeout=4.0, default=False)
    except Exception as exc:
        item = _status_item(
            adapter.name,
            adapter.name.upper(),
            "unavailable",
            f"健康检查失败：{exc}",
            details={"priority": adapter.priority},
        )
        interfaces = _build_interface_items(
            adapter.name,
            adapter.capability,
            adapter_available=False,
        )
        return _with_data_source_details(item, adapter=adapter, interfaces=interfaces)

    if not healthy:
        item = _status_item(
            adapter.name,
            adapter.name.upper(),
            "unavailable",
            "健康检查未通过",
            details={"priority": adapter.priority},
        )
        interfaces = _build_interface_items(
            adapter.name,
            adapter.capability,
            adapter_available=False,
        )
        return _with_data_source_details(item, adapter=adapter, interfaces=interfaces)

    overrides: Dict[str, Dict[str, str]] = {}
    if adapter.name == "akshare":
        overrides["daily_basic"] = {"status": "degraded", "reason": "支持单股 daily_basic，但全市场批量很慢"}
        overrides["financial_data"] = {"status": "unavailable", "reason": "未实现完整财务报表接口"}
    elif adapter.name == "baostock":
        overrides["daily_basic"] = {"status": "degraded", "reason": "仅能提供部分指标，完整估值能力有限"}

    interfaces = _build_interface_items(
        adapter.name,
        adapter.capability,
        adapter_available=True,
        overrides=overrides,
    )
    item = _status_item(
        adapter.name,
        adapter.name.upper(),
        "available",
        "基础探测通过",
        details={"priority": adapter.priority},
    )
    return _with_data_source_details(item, adapter=adapter, interfaces=interfaces)


async def _probe_data_sources(optional_notes: Dict[str, Optional[str]]) -> List[Dict[str, Any]]:
    if optional_notes.get("data_source"):
        return [
            _status_item(
                "data_source_manager",
                "统一数据源管理器",
                "unavailable",
                f"初始化失败：{optional_notes['data_source']}",
            )
        ]

    adapters = list(getattr(data_source_manager, "_adapters", []))
    tasks = []
    for adapter in adapters:
        if adapter.name == "tushare":
            tasks.append(_probe_tushare_adapter(adapter))
        elif adapter.name == "coze":
            tasks.append(_probe_coze_adapter(adapter))
        else:
            tasks.append(_probe_generic_adapter(adapter))
    items = await asyncio.gather(*tasks) if tasks else []

    if not items:
        items.append(_status_item("data_sources", "数据源适配器", "unavailable", "当前没有可用数据源适配器"))

    return items


async def _probe_manager_default_sources() -> Dict[str, Dict[str, Any]]:
    start_date, end_date = _recent_probe_window()
    results = await asyncio.gather(
        _run_with_timeout(data_source_manager.get_stock_basic(), timeout=4.0, default=([], None)),
        _run_with_timeout(data_source_manager.get_stock_basic(ts_code="000001.SZ"), timeout=4.0, default=([], None)),
        _run_with_timeout(
            data_source_manager.get_daily(ts_code="000001.SZ", start_date=start_date, end_date=end_date),
            timeout=4.0,
            default=([], None),
        ),
        _run_with_timeout(
            data_source_manager.get_daily(trade_date=end_date),
            timeout=6.0,
            default=([], None),
        ),
        _run_with_timeout(
            data_source_manager.get_daily_basic(ts_code="000001.SZ", start_date=end_date, end_date=end_date),
            timeout=4.0,
            default=([], None),
        ),
        _run_with_timeout(
            data_source_manager.get_realtime_quotes(ts_codes=["000001.SZ"]),
            timeout=4.0,
            default=({}, None),
        ),
        _run_with_timeout(
            data_source_manager.get_financial_indicator(ts_code="000001.SZ", limit=1),
            timeout=4.0,
            default=([], None),
        ),
        _run_with_timeout(
            data_source_manager.get_index_daily(ts_code="000001.SH", start_date=end_date, end_date=end_date),
            timeout=4.0,
            default=([], None),
        ),
        _run_with_timeout(
            data_source_manager.get_trade_calendar(start_date=start_date, end_date=end_date),
            timeout=4.0,
            default=([], None),
        ),
    )

    keys = [
        "stock_basic_full",
        "stock_basic_single",
        "daily_single",
        "daily_market",
        "daily_basic_single",
        "realtime_quotes",
        "financial_indicator",
        "index_daily",
        "trade_calendar",
    ]

    probed: Dict[str, Dict[str, Any]] = {}
    for key, result in zip(keys, results):
        data, source = result if isinstance(result, tuple) and len(result) == 2 else (None, None)
        if isinstance(data, dict):
            has_data = len(data) > 0
            count = len(data)
        elif isinstance(data, list):
            has_data = len(data) > 0
            count = len(data)
        else:
            has_data = data is not None
            count = 1 if data is not None else 0
        probed[key] = {
            "source": source,
            "has_data": has_data,
            "count": count,
        }
    return probed


def _build_data_source_matrix(items: List[Dict[str, Any]], usage: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    adapters = [
        {
            "key": item["key"],
            "name": item["name"],
            "priority": item.get("details", {}).get("priority"),
            "description": item.get("details", {}).get("description", ""),
        }
        for item in items
    ]
    interface_lookup: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for item in items:
        adapter_key = item["key"]
        interface_lookup[adapter_key] = {}
        for iface in item.get("details", {}).get("interfaces", []) or []:
            interface_lookup[adapter_key][iface["key"]] = iface

    rows = []
    for row_key, row_name, row_description, interface_key in DATA_SOURCE_MATRIX_META:
        current = usage.get(row_key, {})
        cells = []
        for adapter in adapters:
            iface = interface_lookup.get(adapter["key"], {}).get(interface_key, {})
            cells.append(
                {
                    "source_key": adapter["key"],
                    "source_name": adapter["name"],
                    "status": iface.get("status", "unavailable"),
                    "reason": iface.get("reason", "当前无接口状态"),
                }
            )
        rows.append(
            {
                "key": row_key,
                "name": row_name,
                "description": row_description,
                "current_source": current.get("source"),
                "current_source_has_data": current.get("has_data", False),
                "current_source_count": current.get("count", 0),
                "interface_key": interface_key,
                "cells": cells,
            }
        )
    return {
        "adapters": adapters,
        "rows": rows,
    }


async def _build_nodes_context() -> Dict[str, Any]:
    await redis_manager.initialize()
    all_nodes = await redis_manager.get_all_nodes()
    node_counts: Dict[str, int] = {}
    for node in all_nodes:
        node_type = node.get("node_type", "unknown")
        node_counts[node_type] = node_counts.get(node_type, 0) + 1
    realtime_market_data, hot_news_stats = await asyncio.gather(
        redis_manager.get_realtime_market_data(),
        redis_manager.get_hot_news_stats(),
    )
    return {
        "generated_at": datetime.now().isoformat(),
        "nodes": node_counts,
        "realtime_market_data": realtime_market_data,
        "hot_news_stats": hot_news_stats,
    }


async def _build_datasets_context() -> Dict[str, Any]:
    await mongo_manager.initialize()
    optional_notes = await _ensure_optional_managers()

    snapshot_keys = [
        "users",
        "stock_basic",
        "stock_daily",
        "index_daily",
        "daily_basic",
        "limit_list",
        "daily_stats",
        "market_analysis",
        "sector_ranking",
        "reports",
        "strategy_subscriptions",
        "backtest_tasks",
    ]
    snapshot_values = await asyncio.gather(*[_get_collection_snapshot(key) for key in snapshot_keys])
    snapshots = dict(zip(snapshot_keys, snapshot_values))

    listed_stock_count = await mongo_manager.count("stock_basic", {"list_status": "L"})
    if listed_stock_count <= 0:
        listed_stock_count = snapshots["stock_basic"]["count"]

    expected_latest_trade_date_raw = await _run_with_timeout(
        data_source_manager.get_latest_trade_date(),
        timeout=4.0,
        default=(None, None),
    )
    expected_latest_trade_date = (
        expected_latest_trade_date_raw[0]
        if isinstance(expected_latest_trade_date_raw, tuple)
        else expected_latest_trade_date_raw
    )

    stock_daily_coverage, daily_basic_coverage, index_daily_coverage = await asyncio.gather(
        _get_trade_date_coverage("stock_daily", snapshots["stock_daily"]["latest_value"]),
        _get_trade_date_coverage("daily_basic", snapshots["daily_basic"]["latest_value"]),
        _get_trade_date_coverage("index_daily", snapshots["index_daily"]["latest_value"]),
    )

    watchlist_stock_docs, strategy_watch_docs = await asyncio.gather(
        mongo_manager.find_many("users", {}, projection={"watchlist": 1}),
        mongo_manager.find_many("strategy_subscriptions", {"is_active": True}, projection={"watch_list": 1}),
    )
    watchlist_codes = {
        str(ts_code).upper()
        for doc in watchlist_stock_docs
        for ts_code in (doc.get("watchlist", []) or [])
        if ts_code
    }
    strategy_watch_codes = {
        str(ts_code).upper()
        for doc in strategy_watch_docs
        for ts_code in (doc.get("watch_list", []) or [])
        if ts_code
    }

    return {
        "optional_notes": optional_notes,
        "snapshots": snapshots,
        "listed_stock_count": listed_stock_count,
        "expected_latest_trade_date": expected_latest_trade_date,
        "stock_daily_coverage": stock_daily_coverage,
        "daily_basic_coverage": daily_basic_coverage,
        "index_daily_coverage": index_daily_coverage,
        "watchlist_stock_count": len(watchlist_codes),
        "strategy_watch_stock_count": len(strategy_watch_codes),
        "generated_at": datetime.now().isoformat(),
    }


async def _build_services_section_data() -> Dict[str, Any]:
    await redis_manager.initialize()
    await mongo_manager.initialize()

    redis_ok, mongo_ok, milvus_reachable = await asyncio.gather(
        redis_manager.health_check(),
        mongo_manager.health_check(),
        _probe_tcp_port(settings.milvus.host, settings.milvus.port, timeout=1.0),
    )

    services: List[Dict[str, Any]] = []
    services.append(_status_item("redis", "Redis", "available" if redis_ok else "unavailable", "" if redis_ok else "Redis 连接异常"))
    services.append(_status_item("mongo", "MongoDB", "available" if mongo_ok else "unavailable", "" if mongo_ok else "MongoDB 连接异常"))

    if not settings.llm.is_configured:
        services.append(_status_item("llm", "LLM 服务", "unavailable", "未配置 LLM_API_KEY，LLM 相关能力不可用"))
    else:
        services.append(_status_item("llm", "LLM 服务", "available", "已配置 API Key；状态页未执行真实对话探测以避免阻塞"))

    if not settings.notification.enabled:
        services.append(_status_item("notification", "通知服务", "degraded", "通知功能已关闭（NOTIFY_ENABLED=false）"))
    elif not settings.notification.is_configured:
        services.append(_status_item("notification", "通知服务", "degraded", "未配置企业微信 Webhook，监听告警只能做 dry-run 验证"))
    else:
        services.append(_status_item("notification", "通知服务", "available", "Webhook 已配置"))

    if milvus_reachable:
        services.append(_status_item("milvus", "Milvus", "available", f"{settings.milvus.host}:{settings.milvus.port} 端口可连接"))
    else:
        services.append(_status_item("milvus", "Milvus", "degraded", f"{settings.milvus.host}:{settings.milvus.port} 端口不可连接，若未启用 Lite 模式则向量检索不可用"))

    return {
        "generated_at": datetime.now().isoformat(),
        "items": services,
    }


async def _build_data_sources_section_data() -> Dict[str, Any]:
    optional_notes = await _ensure_optional_managers()
    items = await _probe_data_sources(optional_notes)
    usage = await _probe_manager_default_sources() if items else {}
    return {
        "generated_at": datetime.now().isoformat(),
        "items": items,
        "metadata": {
            "matrix": _build_data_source_matrix(items, usage) if items else {"adapters": [], "rows": []},
        },
    }


async def _build_datasets_section_data() -> Dict[str, Any]:
    context = await _build_datasets_context()
    snapshots = context["snapshots"]
    listed_stock_count = context["listed_stock_count"]
    expected_latest_trade_date = context["expected_latest_trade_date"]
    stock_daily_coverage = context["stock_daily_coverage"]
    daily_basic_coverage = context["daily_basic_coverage"]
    index_daily_coverage = context["index_daily_coverage"]
    watchlist_stock_count = context["watchlist_stock_count"]
    strategy_watch_stock_count = context["strategy_watch_stock_count"]

    stock_daily_coverage_pct = stock_daily_coverage / listed_stock_count if listed_stock_count > 0 else 0.0
    daily_basic_coverage_pct = daily_basic_coverage / listed_stock_count if listed_stock_count > 0 else 0.0
    stock_daily_is_current = bool(
        snapshots["stock_daily"]["latest_value"]
        and expected_latest_trade_date
        and snapshots["stock_daily"]["latest_value"] == expected_latest_trade_date
    )
    daily_basic_is_current = bool(
        snapshots["daily_basic"]["latest_value"]
        and expected_latest_trade_date
        and snapshots["daily_basic"]["latest_value"] == expected_latest_trade_date
    )

    stock_daily_dataset_status = (
        "unavailable"
        if snapshots["stock_daily"]["count"] <= 0
        else "available"
        if stock_daily_is_current and stock_daily_coverage_pct >= 0.9
        else "degraded"
    )
    daily_basic_dataset_status = (
        "unavailable"
        if snapshots["daily_basic"]["count"] <= 0
        else "available"
        if daily_basic_is_current and daily_basic_coverage_pct >= 0.9
        else "degraded"
    )
    index_daily_dataset_status = (
        "unavailable"
        if snapshots["index_daily"]["count"] <= 0
        else "available"
        if index_daily_coverage >= 3
        else "degraded"
    )

    datasets = [
        _dataset_item(
            "stock_basic",
            "股票基础信息",
            "available" if snapshots["stock_basic"]["count"] > 0 else "unavailable",
            snapshots["stock_basic"]["count"],
            "" if snapshots["stock_basic"]["count"] > 0 else "stock_basic 表为空，股票搜索无法返回结果",
            latest_value=snapshots["stock_basic"]["latest_value"],
            details={
                "已上市股票数": listed_stock_count,
                "自选股去重数": watchlist_stock_count,
                "监听股去重数": strategy_watch_stock_count,
            },
        ),
        _dataset_item(
            "stock_daily",
            "股票日线",
            stock_daily_dataset_status,
            snapshots["stock_daily"]["count"],
            (
                "stock_daily 表为空，股票详情 K 线和自选股行情不可用"
                if snapshots["stock_daily"]["count"] <= 0
                else ""
                if stock_daily_dataset_status == "available"
                else f"最新交易日仅覆盖 {stock_daily_coverage}/{listed_stock_count} 只股票，覆盖率 {_format_percentage(stock_daily_coverage, listed_stock_count)}"
            ),
            latest_value=snapshots["stock_daily"]["latest_value"],
            details={
                "目标股票数": listed_stock_count,
                "期望最新交易日": expected_latest_trade_date,
                "最新交易日覆盖股票数": stock_daily_coverage,
                "最新交易日覆盖率": _format_percentage(stock_daily_coverage, listed_stock_count),
            },
        ),
        _dataset_item(
            "index_daily",
            "指数日线",
            index_daily_dataset_status,
            snapshots["index_daily"]["count"],
            (
                "index_daily 表为空，市场概览中的指数历史数据不可用"
                if snapshots["index_daily"]["count"] <= 0
                else ""
                if index_daily_dataset_status == "available"
                else f"核心指数最新交易日仅覆盖 {index_daily_coverage}/3"
            ),
            latest_value=snapshots["index_daily"]["latest_value"],
            details={
                "核心指数目标数": 3,
                "最新交易日覆盖指数数": index_daily_coverage,
            },
        ),
        _dataset_item(
            "daily_basic",
            "每日指标",
            daily_basic_dataset_status,
            snapshots["daily_basic"]["count"],
            (
                "daily_basic 表为空，估值/换手率等衍生指标无法直接使用"
                if snapshots["daily_basic"]["count"] <= 0
                else ""
                if daily_basic_dataset_status == "available"
                else f"最新交易日仅覆盖 {daily_basic_coverage}/{listed_stock_count} 只股票，覆盖率 {_format_percentage(daily_basic_coverage, listed_stock_count)}"
            ),
            latest_value=snapshots["daily_basic"]["latest_value"],
            details={
                "目标股票数": listed_stock_count,
                "期望最新交易日": expected_latest_trade_date,
                "最新交易日覆盖股票数": daily_basic_coverage,
                "最新交易日覆盖率": _format_percentage(daily_basic_coverage, listed_stock_count),
            },
        ),
        _dataset_item(
            "daily_stats",
            "市场统计",
            "available" if snapshots["daily_stats"]["count"] > 0 else "unavailable",
            snapshots["daily_stats"]["count"],
            "" if snapshots["daily_stats"]["count"] > 0 else "daily_stats 表为空，市场情绪/涨跌分布相关接口不可用",
            latest_value=snapshots["daily_stats"]["latest_value"],
        ),
        _dataset_item(
            "market_analysis",
            "市场分析结果",
            "available" if snapshots["market_analysis"]["count"] > 0 else "unavailable",
            snapshots["market_analysis"]["count"],
            "" if snapshots["market_analysis"]["count"] > 0 else "market_analysis 表为空，市场周期与强度分析为空",
            latest_value=snapshots["market_analysis"]["latest_value"],
        ),
        _dataset_item(
            "sector_ranking",
            "板块排名",
            "available" if snapshots["sector_ranking"]["count"] > 0 else "unavailable",
            snapshots["sector_ranking"]["count"],
            "" if snapshots["sector_ranking"]["count"] > 0 else "sector_ranking 表为空，板块分析页面没有可展示数据",
            latest_value=snapshots["sector_ranking"]["latest_value"],
        ),
        _dataset_item(
            "reports",
            "复盘报告",
            "available" if snapshots["reports"]["count"] > 0 else "unavailable",
            snapshots["reports"]["count"],
            "" if snapshots["reports"]["count"] > 0 else "reports 表为空，报告回顾页暂无内容",
            latest_value=snapshots["reports"]["latest_value"],
        ),
        _dataset_item(
            "strategy_subscriptions",
            "策略订阅配置",
            "available" if snapshots["strategy_subscriptions"]["count"] > 0 else "unavailable",
            snapshots["strategy_subscriptions"]["count"],
            "" if snapshots["strategy_subscriptions"]["count"] > 0 else "strategy_subscriptions 表为空，监听配置尚未初始化",
            latest_value=snapshots["strategy_subscriptions"]["latest_value"],
        ),
    ]

    return {
        "generated_at": context["generated_at"],
        "items": datasets,
        "details": {
            "listed_stock_count": listed_stock_count,
            "expected_latest_trade_date": expected_latest_trade_date,
            "stock_daily_dataset_status": stock_daily_dataset_status,
            "daily_basic_dataset_status": daily_basic_dataset_status,
            "stock_daily_coverage": stock_daily_coverage,
            "daily_basic_coverage": daily_basic_coverage,
        },
    }


async def _build_features_section_data() -> Dict[str, Any]:
    await mongo_manager.initialize()
    await redis_manager.initialize()
    datasets_context, nodes_context = await asyncio.gather(
        _build_datasets_context(),
        _build_nodes_context(),
    )

    snapshots = datasets_context["snapshots"]
    listed_stock_count = datasets_context["listed_stock_count"]
    stock_daily_coverage = datasets_context["stock_daily_coverage"]
    expected_latest_trade_date = datasets_context["expected_latest_trade_date"]

    has_stock_basic = snapshots["stock_basic"]["count"] > 0
    has_stock_daily = snapshots["stock_daily"]["count"] > 0
    has_index_daily = snapshots["index_daily"]["count"] > 0
    has_daily_stats = snapshots["daily_stats"]["count"] > 0
    has_market_analysis = snapshots["market_analysis"]["count"] > 0
    has_sector_ranking = snapshots["sector_ranking"]["count"] > 0
    has_reports = snapshots["reports"]["count"] > 0
    has_subscriptions = snapshots["strategy_subscriptions"]["count"] > 0
    realtime_market_data = nodes_context["realtime_market_data"]
    hot_news_stats = nodes_context["hot_news_stats"]
    has_realtime_market = bool(realtime_market_data)
    has_hot_news = hot_news_stats.get("total", 0) > 0
    node_counts = nodes_context["nodes"]
    listener_nodes = node_counts.get("listener", 0)
    inference_nodes = node_counts.get("inference", 0)
    data_sync_nodes = node_counts.get("data_sync", 0)
    backtest_nodes = node_counts.get("backtest", 0)

    stock_daily_is_current = bool(
        snapshots["stock_daily"]["latest_value"]
        and expected_latest_trade_date
        and snapshots["stock_daily"]["latest_value"] == expected_latest_trade_date
    )
    stock_daily_dataset_status = (
        "unavailable"
        if snapshots["stock_daily"]["count"] <= 0
        else "available"
        if listed_stock_count > 0 and stock_daily_is_current and (stock_daily_coverage / listed_stock_count) >= 0.9
        else "degraded"
    )

    mongo_ok = await mongo_manager.health_check()
    milvus_reachable = await _probe_tcp_port(settings.milvus.host, settings.milvus.port, timeout=1.0)

    features = [
        _status_item(
            "auth_login",
            "登录与用户鉴权",
            "available" if mongo_ok else "unavailable",
            "" if mongo_ok else "MongoDB 不可用，登录/鉴权接口无法工作",
            endpoint="/api/v1/auth/*",
        ),
        _status_item(
            "stock_search",
            "添加自选股搜索",
            "available" if has_stock_basic else "unavailable",
            "" if has_stock_basic else "stock_basic 表为空，`/stocks/search` 只能返回空数组",
            endpoint="/api/v1/stocks/search",
        ),
        _status_item(
            "stock_basic",
            "个股基础信息",
            "available" if has_stock_basic else "unavailable",
            "" if has_stock_basic else "stock_basic 表为空，个股基础信息接口无法返回数据",
            endpoint="/api/v1/stocks/{ts_code}/basic",
        ),
        _status_item(
            "stock_daily",
            "个股历史 K 线",
            "unavailable" if not has_stock_daily else ("available" if stock_daily_dataset_status == "available" else "degraded"),
            (
                "stock_daily 表为空，股票详情图表与历史行情接口不可用"
                if not has_stock_daily else
                ""
                if stock_daily_dataset_status == "available" else
                f"历史行情接口可查到部分股票，但最新交易日仅覆盖 {stock_daily_coverage}/{listed_stock_count}，缺口较大"
            ),
            endpoint="/api/v1/stocks/{ts_code}/daily",
        ),
        _status_item(
            "stock_realtime",
            "自选股行情",
            "unavailable" if not has_stock_daily else ("available" if stock_daily_dataset_status == "available" else "degraded"),
            (
                "`/stocks/realtime` 当前实现读取 Mongo 最新日线，stock_daily 为空时 price/pct_chg 都会是空"
                if not has_stock_daily else
                ""
                if stock_daily_dataset_status == "available" else
                f"`/stocks/realtime` 依赖本地日线，当前最新交易日仅覆盖 {stock_daily_coverage}/{listed_stock_count} 只股票"
            ),
            endpoint="/api/v1/stocks/realtime",
        ),
        _status_item(
            "market_overview",
            "市场概览",
            "available" if has_realtime_market or (has_index_daily and has_daily_stats) else "unavailable",
            (
                "Redis 中已有实时市场快照"
                if has_realtime_market
                else "既没有 Redis 实时市场快照，也没有 index_daily + daily_stats 历史数据"
            ) if not (has_realtime_market or (has_index_daily and has_daily_stats)) else "",
            endpoint="/api/v1/market/overview",
            details={"listener_nodes": listener_nodes, "data_sync_nodes": data_sync_nodes},
        ),
        _status_item(
            "market_analysis",
            "市场情绪与历史分析",
            "available" if has_daily_stats and has_market_analysis else "unavailable",
            "" if has_daily_stats and has_market_analysis else "daily_stats 或 market_analysis 表为空，`/market/latest` `/market/history` `/market/stats-table` 无法返回完整分析",
            endpoint="/api/v1/market/latest, /api/v1/market/history, /api/v1/market/stats-table",
        ),
        _status_item(
            "sector_analysis",
            "板块分析",
            "available" if has_sector_ranking else "unavailable",
            "" if has_sector_ranking else "sector_ranking 表为空，主线雷达、板块时间线、板块评分都会没有数据",
            endpoint="/api/v1/market/sector-*, /api/v1/market/theme-*",
        ),
        _status_item(
            "hot_news",
            "热点追踪",
            "available" if has_hot_news else ("degraded" if data_sync_nodes > 0 else "unavailable"),
            (
                "" if has_hot_news else
                "Redis 里暂时没有热点新闻缓存，但 data_sync 节点在线，可手动刷新后重试"
                if data_sync_nodes > 0 else
                "Redis 里没有热点新闻缓存，且未检测到 data_sync 节点，热点追踪页无法展示内容"
            ),
            endpoint="/api/v1/market/hot_news*",
            details={"hot_news_total": hot_news_stats.get("total", 0)},
        ),
        _status_item(
            "reports",
            "报告回顾",
            "available" if has_reports else "unavailable",
            "" if has_reports else "reports 表为空，报告回顾页暂无内容",
            endpoint="/api/v1/reports*",
        ),
        _status_item(
            "tasks",
            "分析任务",
            "available" if inference_nodes > 0 else "unavailable",
            "" if inference_nodes > 0 else "未检测到 inference 节点注册，任务虽然能创建入队，但没有节点消费执行",
            endpoint="/api/v1/tasks, /api/v1/tasks/analyze/*",
            details={"inference_nodes": inference_nodes},
        ),
        _status_item(
            "listener_subscriptions",
            "市场监听配置",
            "available" if has_subscriptions else "unavailable",
            "" if has_subscriptions else "策略订阅记录不存在，监听配置尚未初始化",
            endpoint="/api/v1/strategy/subscriptions*",
        ),
        _status_item(
            "listener_runtime",
            "市场监听执行与告警",
            "available" if listener_nodes > 0 and settings.notification.is_configured else ("degraded" if listener_nodes > 0 else "unavailable"),
            (
                "" if listener_nodes > 0 and settings.notification.is_configured else
                "Listener 节点在线，但未配置企业微信 Webhook，目前只能做 dry-run 告警验证"
                if listener_nodes > 0 else
                "未检测到 listener 节点注册，订阅虽然可编辑，但不会发生真实轮询和告警发送"
            ),
            endpoint="ListenerNode + Notification",
            details={"listener_nodes": listener_nodes},
        ),
        _status_item(
            "backtest",
            "单股回测与因子选股",
            "available" if backtest_nodes > 0 else "unavailable",
            "" if backtest_nodes > 0 else "未检测到 backtest 节点注册，回测任务无法提交到执行节点",
            endpoint="/api/v1/backtest/*",
            details={"backtest_nodes": backtest_nodes},
        ),
        _status_item(
            "vector_search",
            "向量检索与知识库",
            "available" if milvus_reachable else "degraded",
            "" if milvus_reachable else "Milvus 远程端口不可连接，若项目未使用 Lite 模式则知识库检索会失败",
            endpoint="Milvus / RAG",
        ),
    ]

    return {
        "generated_at": datetime.now().isoformat(),
        "items": features,
    }


def _compose_summary(sections: List[List[Dict[str, Any]]]) -> Dict[str, int]:
    all_items = [item for section in sections for item in section]
    return {
        "available": sum(1 for item in all_items if item["status"] == "available"),
        "degraded": sum(1 for item in all_items if item["status"] == "degraded"),
        "unavailable": sum(1 for item in all_items if item["status"] == "unavailable"),
    }


async def build_capability_overview(force_refresh: bool = False) -> Dict[str, Any]:
    nodes_context = await _get_cached("system_status:nodes", _build_nodes_context, force_refresh=force_refresh)
    section_results = [
        _CACHE.get(f"system_status:section:{section}")
        for section in SECTION_KEYS
    ]
    loaded_sections = [
        entry["value"]["items"]
        for entry in section_results
        if entry and time.monotonic() - entry["ts"] < CACHE_TTL_SECONDS
    ]
    summary = _compose_summary(loaded_sections) if loaded_sections else {"available": 0, "degraded": 0, "unavailable": 0}
    return {
        "generated_at": nodes_context["generated_at"],
        "nodes": nodes_context["nodes"],
        "summary": summary,
    }


async def build_capability_section(section: SectionName, force_refresh: bool = False) -> Dict[str, Any]:
    if section not in SECTION_KEYS:
        raise ValueError(f"Unknown section: {section}")

    async def builder() -> Dict[str, Any]:
        if section == "services":
            return await _build_services_section_data()
        if section == "data_sources":
            return await _build_data_sources_section_data()
        if section == "datasets":
            return await _build_datasets_section_data()
        return await _build_features_section_data()

    result = await _get_cached(
        f"system_status:section:{section}",
        builder,
        force_refresh=force_refresh,
    )
    return {
        "section": section,
        "generated_at": result["generated_at"],
        "items": result["items"],
        "metadata": result.get("metadata", {}),
    }


async def build_coze_plugin_status(force_refresh: bool = False) -> Dict[str, Any]:
    return await _get_cached(
        "system_status:coze_plugins",
        _build_coze_plugin_status_data,
        force_refresh=force_refresh,
    )


async def build_capability_audit() -> Dict[str, Any]:
    """生成完整项目能力巡检结果。"""
    overview, services, data_sources, datasets, features = await asyncio.gather(
        build_capability_overview(force_refresh=False),
        build_capability_section("services", force_refresh=False),
        build_capability_section("data_sources", force_refresh=False),
        build_capability_section("datasets", force_refresh=False),
        build_capability_section("features", force_refresh=False),
    )
    summary = _compose_summary([
        services["items"],
        data_sources["items"],
        datasets["items"],
        features["items"],
    ])
    return {
        "generated_at": max(
            overview["generated_at"],
            services["generated_at"],
            data_sources["generated_at"],
            datasets["generated_at"],
            features["generated_at"],
        ),
        "summary": summary,
        "nodes": overview["nodes"],
        "services": services["items"],
        "data_sources": data_sources["items"],
        "datasets": datasets["items"],
        "features": features["items"],
    }
