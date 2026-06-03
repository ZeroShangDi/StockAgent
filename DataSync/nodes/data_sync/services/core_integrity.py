"""
核心链路完整性检查服务

面向 DataSync 的核心收盘后链路，提供：
- 最近 N 个交易日的完整性概览
- 最新交易日是否达到“核心可用”判断
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any, Dict, List

from common.utils import market_now, market_today_str
from core.managers.data_source_manager import data_source_manager
from core.managers.mongo_manager import mongo_manager
from core.settings import settings


CORE_DATASETS = [
    "stock_daily",
    "index_daily",
    "daily_basic",
    "moneyflow_industry",
    "moneyflow_concept",
    "limit_list",
    "daily_stats",
    "market_statistics_cache",
]
CORE_INDEX_CODES = ["000001.SH", "399001.SZ", "399006.SZ"]
MARKET_STATISTICS_EXPECTED_COUNT = 9
STOCK_DATASET_COVERAGE_THRESHOLD = 0.85
DEFAULT_RECOVERABILITY = {
    "mode": "full",
    "can_recover_trade_date": True,
    "can_backfill": True,
    "can_rerun": True,
    "severity_on_missing": "warning",
    "reason": "核心日级数据支持按交易日定向恢复或进入夜间补缺队列。",
}
CORE_DATASET_RECOVERABILITY = {
    dataset: dict(DEFAULT_RECOVERABILITY)
    for dataset in CORE_DATASETS
}


async def build_core_integrity_overview(days: int = 3) -> Dict[str, Any]:
    """构建最近若干交易日的核心链路完整性概览。"""
    window_days = max(1, min(int(days or 3), 10))
    latest_trade_date, _ = await data_source_manager.get_latest_trade_date()
    if not latest_trade_date:
        return {
            "success": False,
            "error": "Unable to resolve latest trade date",
            "days": window_days,
            "trade_dates": [],
            "overview": [],
        }

    trade_dates = await _get_recent_trade_dates(latest_trade_date, window_days)
    listed_stock_count = await mongo_manager.count("stock_basic", {"list_status": "L"})
    latest_expectation = _build_latest_trade_date_expectation(latest_trade_date)

    overview: List[Dict[str, Any]] = []
    for trade_date in trade_dates:
        dataset_items = await _build_dataset_statuses(trade_date, listed_stock_count)
        ready = all(item["ok"] for item in dataset_items)
        is_latest_trade_date = trade_date == latest_trade_date
        expected_ready = bool(not is_latest_trade_date or latest_expectation.get("expected_ready"))
        awaiting_sync_window = bool(is_latest_trade_date and latest_expectation.get("awaiting_sync_window"))
        syncing_window = bool(is_latest_trade_date and latest_expectation.get("syncing_window"))
        failed_after_reached = bool(is_latest_trade_date and latest_expectation.get("failed_after_reached"))

        if is_latest_trade_date and not ready and not expected_ready:
            for item in dataset_items:
                if not item["ok"] and item.get("state") in {"missing", "warning"}:
                    if awaiting_sync_window:
                        item["state"] = "waiting_window"
                        item["reason"] = "before configured core sync check window"
                    elif syncing_window:
                        item["state"] = "syncing_window"
                        item["reason"] = "within configured core sync SLA window"
        elif failed_after_reached and not ready:
            for item in dataset_items:
                if not item["ok"] and item.get("state") == "missing":
                    item["state"] = "failed"
                    item["reason"] = "core dataset still missing after configured failure alert time"
        overview.append(
            {
                "trade_date": trade_date,
                "ready": ready,
                "expected_ready": expected_ready,
                "awaiting_sync_window": awaiting_sync_window,
                "syncing_window": syncing_window,
                "recovery_allowed": bool(is_latest_trade_date and not awaiting_sync_window),
                "sla_phase": latest_expectation.get("phase") if is_latest_trade_date else "historical",
                "missing_datasets": [item["dataset"] for item in dataset_items if item.get("state") == "missing"],
                "warning_datasets": [item["dataset"] for item in dataset_items if item.get("state") == "warning"],
                "failed_datasets": [item["dataset"] for item in dataset_items if item.get("state") == "failed"],
                "datasets": dataset_items,
            }
        )

    latest_entry = overview[-1] if overview else None
    ready_trade_dates = [entry["trade_date"] for entry in overview if entry.get("ready")]
    incomplete_trade_dates = [entry["trade_date"] for entry in overview if not entry.get("ready")]
    blocking_incomplete_trade_dates = [
        entry["trade_date"]
        for entry in overview
        if not entry.get("ready") and entry.get("expected_ready")
    ]
    pending_trade_dates = [
        entry["trade_date"]
        for entry in overview
        if not entry.get("expected_ready")
    ]
    return {
        "success": True,
        "days": window_days,
        "latest_trade_date": latest_trade_date,
        "latest_trade_date_expected_ready": latest_expectation.get("expected_ready"),
        "latest_trade_date_awaiting_sync_window": latest_expectation.get("awaiting_sync_window"),
        "latest_trade_date_syncing_window": latest_expectation.get("syncing_window"),
        "latest_trade_date_failed_after_reached": latest_expectation.get("failed_after_reached"),
        "latest_trade_date_sla_phase": latest_expectation.get("phase"),
        "latest_trade_date_check_after": latest_expectation.get("check_after"),
        "latest_trade_date_ready_after": latest_expectation.get("ready_after"),
        "latest_trade_date_fail_after": latest_expectation.get("fail_after"),
        "latest_trade_date_observed_at": latest_expectation.get("observed_at"),
        "trade_dates": trade_dates,
        "listed_stock_count": listed_stock_count,
        "core_datasets": list(CORE_DATASETS),
        "core_dataset_recoverability": {
            dataset: _dataset_recoverability(dataset)
            for dataset in CORE_DATASETS
        },
        "latest_ready": bool(latest_entry and latest_entry.get("ready")),
        "latest_effectively_ready": bool(latest_entry and (latest_entry.get("ready") or not latest_entry.get("expected_ready"))),
        "recent_window_ready": len(blocking_incomplete_trade_dates) == 0,
        "ready_trade_dates": ready_trade_dates,
        "incomplete_trade_dates": incomplete_trade_dates,
        "blocking_incomplete_trade_dates": blocking_incomplete_trade_dates,
        "pending_trade_dates": pending_trade_dates,
        "overview": overview,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _build_latest_trade_date_expectation(latest_trade_date: str) -> Dict[str, Any]:
    now = market_now()
    check_after_local = _parse_local_time(
        settings.data_sync.core_ready_check_after_local_time,
        fallback=time(hour=15, minute=30),
    )
    expected_after_local = _parse_local_time(
        settings.data_sync.core_ready_expected_after_local_time
        or settings.data_sync.core_ready_after_local_time,
        fallback=time(hour=16, minute=10),
    )
    fail_after_local = _parse_local_time(
        settings.data_sync.core_ready_fail_after_local_time,
        fallback=time(hour=17, minute=0),
    )
    trade_date_dt = datetime.strptime(latest_trade_date, "%Y%m%d")
    check_after_dt = _at_trade_date_time(now, trade_date_dt, check_after_local)
    expected_after_dt = _at_trade_date_time(now, trade_date_dt, expected_after_local)
    fail_after_dt = _at_trade_date_time(now, trade_date_dt, fail_after_local)

    is_today = latest_trade_date == market_today_str()
    awaiting_sync_window = bool(is_today and now < check_after_dt)
    syncing_window = bool(is_today and check_after_dt <= now < expected_after_dt)
    failed_after_reached = bool(is_today and now >= fail_after_dt)
    if not is_today:
        phase = "historical"
    elif awaiting_sync_window:
        phase = "waiting_window"
    elif syncing_window:
        phase = "syncing_window"
    elif failed_after_reached:
        phase = "failed"
    else:
        phase = "overdue"
    return {
        "expected_ready": bool((not is_today) or now >= expected_after_dt),
        "awaiting_sync_window": awaiting_sync_window,
        "syncing_window": syncing_window,
        "failed_after_reached": failed_after_reached,
        "phase": phase,
        "check_after": check_after_dt.isoformat(),
        "ready_after": expected_after_dt.isoformat(),
        "fail_after": fail_after_dt.isoformat(),
        "observed_at": now.isoformat(),
    }


def _at_trade_date_time(now: datetime, trade_date_dt: datetime, value: time) -> datetime:
    return now.replace(
        year=trade_date_dt.year,
        month=trade_date_dt.month,
        day=trade_date_dt.day,
        hour=value.hour,
        minute=value.minute,
        second=0,
        microsecond=0,
    )


def _parse_local_time(raw_value: str, fallback: time) -> time:
    try:
        hour_text, minute_text = str(raw_value or "").strip().split(":", 1)
        hour = max(0, min(int(hour_text), 23))
        minute = max(0, min(int(minute_text), 59))
        return time(hour=hour, minute=minute)
    except Exception:
        return fallback


async def _get_recent_trade_dates(latest_trade_date: str, window_days: int) -> List[str]:
    end_dt = datetime.strptime(latest_trade_date, "%Y%m%d")
    start_dt = end_dt - timedelta(days=max(window_days * 4, 10))
    trade_dates, _ = await data_source_manager.get_trade_calendar(
        start_dt.strftime("%Y%m%d"),
        latest_trade_date,
    )
    normalized = sorted({str(item) for item in trade_dates if item})
    if not normalized:
        return [latest_trade_date]
    return normalized[-window_days:]


async def _build_dataset_statuses(trade_date: str, listed_stock_count: int) -> List[Dict[str, Any]]:
    sync_dates = {
        dataset: await mongo_manager.get_last_sync_date(dataset)
        for dataset in CORE_DATASETS
    }
    executions = {
        dataset: await _get_latest_dataset_execution(dataset, trade_date)
        for dataset in CORE_DATASETS
    }

    stock_daily_count, daily_basic_count, index_daily_count, moneyflow_industry_count, moneyflow_concept_count, limit_list_count, daily_stats_count, market_stats_cache_count = await _gather_counts(trade_date)

    statuses = [
        _coverage_status(
            "stock_daily",
            trade_date,
            stock_daily_count,
            listed_stock_count,
            sync_dates["stock_daily"],
            executions["stock_daily"],
        ),
        {
            "dataset": "index_daily",
            "trade_date": trade_date,
            "count": index_daily_count,
            "expected_count": len(CORE_INDEX_CODES),
            "ok": index_daily_count >= len(CORE_INDEX_CODES),
            "sync_date": sync_dates["index_daily"],
            "execution": _summarize_execution(executions["index_daily"]),
            "state": "ready" if index_daily_count >= len(CORE_INDEX_CODES) else ("warning" if index_daily_count > 0 else "missing"),
            "reason": "" if index_daily_count >= len(CORE_INDEX_CODES) else f"expected>={len(CORE_INDEX_CODES)} got={index_daily_count}",
            "recoverability": _dataset_recoverability("index_daily"),
        },
        _coverage_status(
            "daily_basic",
            trade_date,
            daily_basic_count,
            listed_stock_count,
            sync_dates["daily_basic"],
            executions["daily_basic"],
        ),
        _presence_status("moneyflow_industry", trade_date, moneyflow_industry_count, sync_dates["moneyflow_industry"], executions["moneyflow_industry"]),
        _presence_status("moneyflow_concept", trade_date, moneyflow_concept_count, sync_dates["moneyflow_concept"], executions["moneyflow_concept"]),
        _presence_or_executed_status("limit_list", trade_date, limit_list_count, sync_dates["limit_list"], executions["limit_list"]),
        _presence_status("daily_stats", trade_date, daily_stats_count, sync_dates["daily_stats"], executions["daily_stats"], expected_min=1),
        {
            "dataset": "market_statistics_cache",
            "trade_date": trade_date,
            "count": market_stats_cache_count,
            "expected_count": MARKET_STATISTICS_EXPECTED_COUNT,
            "ok": market_stats_cache_count >= MARKET_STATISTICS_EXPECTED_COUNT,
            "sync_date": sync_dates["market_statistics_cache"],
            "execution": _summarize_execution(executions["market_statistics_cache"]),
            "state": (
                "ready"
                if market_stats_cache_count >= MARKET_STATISTICS_EXPECTED_COUNT
                else ("warning" if market_stats_cache_count > 0 else "missing")
            ),
            "reason": (
                ""
                if market_stats_cache_count >= MARKET_STATISTICS_EXPECTED_COUNT
                else f"expected>={MARKET_STATISTICS_EXPECTED_COUNT} got={market_stats_cache_count}"
            ),
            "recoverability": _dataset_recoverability("market_statistics_cache"),
        },
    ]
    return statuses


async def _gather_counts(trade_date: str) -> tuple[int, int, int, int, int, int, int, int]:
    return (
        await mongo_manager.count("stock_daily", {"trade_date": trade_date}),
        await mongo_manager.count("daily_basic", {"trade_date": trade_date}),
        await mongo_manager.count("index_daily", {"trade_date": trade_date, "ts_code": {"$in": CORE_INDEX_CODES}}),
        await mongo_manager.count("moneyflow_industry", {"trade_date": trade_date}),
        await mongo_manager.count("moneyflow_concept", {"trade_date": trade_date}),
        await mongo_manager.count("limit_list", {"trade_date": trade_date}),
        await mongo_manager.count("daily_stats", {"trade_date": trade_date}),
        await mongo_manager.count("market_statistics_cache", {"trade_date": trade_date}),
    )


async def _get_latest_dataset_execution(dataset: str, trade_date: str) -> Dict[str, Any] | None:
    return await mongo_manager.find_one(
        "job_execution_records",
        {
            "job_name": dataset,
            "target_trade_date": trade_date,
        },
        projection={
            "job_name": 1,
            "status": 1,
            "started_at": 1,
            "finished_at": 1,
            "count": 1,
            "duration_ms": 1,
            "error": 1,
            "resource_class": 1,
            "source": 1,
            "_id": 0,
        },
        sort=[("started_at", -1)],
    )


def _summarize_execution(execution: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if not execution:
        return None
    return {
        "status": execution.get("status"),
        "started_at": _stringify_dt(execution.get("started_at")),
        "finished_at": _stringify_dt(execution.get("finished_at")),
        "count": execution.get("count"),
        "duration_ms": execution.get("duration_ms"),
        "error": execution.get("error"),
        "resource_class": execution.get("resource_class"),
        "source": execution.get("source"),
    }


def _dataset_recoverability(dataset: str) -> Dict[str, Any]:
    return dict(CORE_DATASET_RECOVERABILITY.get(dataset, DEFAULT_RECOVERABILITY))


def _stringify_dt(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _execution_succeeded(execution: Dict[str, Any] | None) -> bool:
    return bool(execution and execution.get("status") == "success")


def _coverage_status(
    dataset: str,
    trade_date: str,
    count: int,
    listed_stock_count: int,
    sync_date: str | None,
    execution: Dict[str, Any] | None,
) -> Dict[str, Any]:
    denominator = max(listed_stock_count, 1)
    coverage = count / denominator
    ok = count > 0 and coverage >= STOCK_DATASET_COVERAGE_THRESHOLD
    state = "ready" if ok else ("warning" if count > 0 else "missing")
    return {
        "dataset": dataset,
        "trade_date": trade_date,
        "count": count,
        "expected_count": listed_stock_count,
        "coverage": round(coverage, 4),
        "coverage_threshold": STOCK_DATASET_COVERAGE_THRESHOLD,
        "ok": ok,
        "sync_date": sync_date,
        "execution": _summarize_execution(execution),
        "state": state,
        "reason": "" if ok else f"coverage={coverage:.2%}, threshold={STOCK_DATASET_COVERAGE_THRESHOLD:.0%}",
        "recoverability": _dataset_recoverability(dataset),
    }


def _presence_status(
    dataset: str,
    trade_date: str,
    count: int,
    sync_date: str | None,
    execution: Dict[str, Any] | None,
    *,
    expected_min: int = 1,
) -> Dict[str, Any]:
    ok = count >= expected_min
    return {
        "dataset": dataset,
        "trade_date": trade_date,
        "count": count,
        "expected_count": expected_min,
        "ok": ok,
        "sync_date": sync_date,
        "execution": _summarize_execution(execution),
        "state": "ready" if ok else ("warning" if count > 0 else "missing"),
        "reason": "" if ok else f"expected>={expected_min} got={count}",
        "recoverability": _dataset_recoverability(dataset),
    }


def _presence_or_executed_status(
    dataset: str,
    trade_date: str,
    count: int,
    sync_date: str | None,
    execution: Dict[str, Any] | None,
) -> Dict[str, Any]:
    execution_ok = _execution_succeeded(execution)
    ok = count > 0 or execution_ok
    return {
        "dataset": dataset,
        "trade_date": trade_date,
        "count": count,
        "expected_count": 1,
        "ok": ok,
        "sync_date": sync_date,
        "execution": _summarize_execution(execution),
        "state": "ready" if ok else "missing",
        "reason": "" if ok else "no rows and no successful execution for target_trade_date",
        "recoverability": _dataset_recoverability(dataset),
    }
