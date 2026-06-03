"""
核心数据定向恢复契约。

所有按交易日恢复的核心任务都先经过交易日校验，并返回统一的
source/sources/warnings/failed_items 字段，方便回补队列和运维页面判断状态。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from core.managers.data_source_manager import data_source_manager


async def validate_recovery_trade_date(trade_date: str) -> Dict[str, Any]:
    """校验恢复目标是否为明确的交易日，避免在非交易日制造空写入。"""
    normalized = str(trade_date or "").strip()
    warnings: List[str] = []

    if len(normalized) != 8 or not normalized.isdigit():
        return {
            "ok": False,
            "success": True,
            "trade_date": normalized,
            "skipped": True,
            "reason": "invalid_trade_date",
            "source": None,
            "warnings": [f"invalid trade_date: {trade_date!r}"],
        }

    try:
        trade_dates, source = await data_source_manager.get_trade_calendar(
            start_date=normalized,
            end_date=normalized,
        )
    except Exception as exc:
        return {
            "ok": False,
            "success": False,
            "trade_date": normalized,
            "skipped": False,
            "reason": "trade_calendar_error",
            "source": None,
            "warnings": [f"failed to verify trade calendar for {normalized}: {exc}"],
            "error": str(exc),
        }

    if normalized not in set(str(item) for item in (trade_dates or [])):
        warnings.append(f"{normalized} is not a trading day; recovery skipped")
        return {
            "ok": False,
            "success": True,
            "trade_date": normalized,
            "skipped": True,
            "reason": "non_trade_date",
            "source": source,
            "warnings": warnings,
        }

    return {
        "ok": True,
        "success": True,
        "trade_date": normalized,
        "skipped": False,
        "reason": None,
        "source": source,
        "warnings": warnings,
    }


def skipped_recovery_result(job_name: str, guard: Dict[str, Any]) -> Dict[str, Any]:
    """生成统一的跳过/校验失败恢复结果。"""
    success = bool(guard.get("success", True))
    trade_date = guard.get("trade_date")
    reason = guard.get("reason") or "recovery_skipped"
    result = {
        "success": success,
        "count": 0,
        "trade_date": trade_date,
        "skipped": bool(guard.get("skipped", not success)),
        "reason": reason,
        "source": guard.get("source"),
        "sources": compact_sources([guard.get("source")]),
        "warnings": list(guard.get("warnings") or []),
        "message": f"Skipped {job_name} recovery for {trade_date}: {reason}",
    }
    if guard.get("error"):
        result["error"] = guard["error"]
        result["message"] = f"Failed to verify {job_name} recovery for {trade_date}: {guard['error']}"
    return result


def compact_sources(sources: Iterable[Any], default: str | None = None) -> List[str]:
    """把采集结果中的来源压成稳定、去重、可读的列表。"""
    normalized: List[str] = []
    for source in sources:
        if isinstance(source, (list, tuple, set)):
            for nested_source in compact_sources(source):
                if nested_source not in normalized:
                    normalized.append(nested_source)
            continue
        value = str(source or "").strip()
        if value and value not in normalized:
            normalized.append(value)
    if not normalized and default:
        normalized.append(default)
    return normalized


def extract_sources_from_parallel_result(
    result: Dict[str, Any],
    *,
    default: str | None = None,
) -> List[str]:
    sources: List[str] = []
    for item in result.get("results", []) or []:
        if not item.get("success"):
            continue
        payload = item.get("result")
        if isinstance(payload, dict):
            sources.extend(compact_sources([payload.get("source"), payload.get("sources")]))
    return compact_sources(sources, default=default)


def primary_source(sources: List[str], default: str = "unknown") -> str:
    if not sources:
        return default
    if len(sources) == 1:
        return sources[0]
    return "multiple"


def build_recovery_warnings(
    guard: Dict[str, Any],
    *,
    failed_count: int = 0,
    failed_items: Iterable[Dict[str, Any]] | None = None,
) -> List[str]:
    warnings = list(guard.get("warnings") or [])
    if failed_count:
        warnings.append(f"{failed_count} recovery item(s) failed")
    for item in list(failed_items or [])[:3]:
        item_id = item.get("item_id") or item.get("trade_date") or item.get("ts_code") or "unknown"
        error = item.get("error") or item.get("reason") or "unknown error"
        warnings.append(f"{item_id}: {error}")
    return warnings
