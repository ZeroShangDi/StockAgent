"""
DataSync 运维总览服务

聚合当前最重要的几类运行态信息：
- 核心链路完整性概览
- 主库 / 镜像库同步目标状态
- 最近任务执行记录
- 最近失败任务
- 当前运维告警信号
- 最新 readiness marker
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from statistics import mean
from typing import Any, Dict, Iterable, List

from core.managers.data_source_manager import data_source_manager
from core.managers.mongo_manager import mongo_manager
from core.settings import settings
from .core_integrity import build_core_integrity_overview


CORE_JOB_NAMES = {
    "stock_daily",
    "index_daily",
    "daily_basic",
    "moneyflow_industry",
    "moneyflow_concept",
    "limit_list",
    "daily_stats",
    "market_statistics_cache",
}
CORE_JOB_LATEST_EXECUTED_OUTLIER_MS = 10 * 60 * 1000
CORE_JOB_P95_OUTLIER_MS = 5 * 60 * 1000
BACKFILL_QUEUE_STATUSES = ("pending", "running", "failed", "paused", "done")


def _normalize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in value.items() if key != "_id"}
    return value


def _derive_duration_ms(record: Dict[str, Any]) -> float | None:
    raw_duration = record.get("duration_ms")
    if isinstance(raw_duration, (int, float)):
        return float(raw_duration)

    started_at = record.get("started_at")
    finished_at = record.get("finished_at")
    if isinstance(started_at, datetime) and isinstance(finished_at, datetime):
        return max((finished_at - started_at).total_seconds() * 1000, 0.0)

    return None


def _percentile(sorted_values: List[float], percentile: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])

    rank = max(0.0, min(1.0, percentile)) * (len(sorted_values) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = rank - lower
    return float(sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight)


def _summarize_job_details(record: Dict[str, Any] | None) -> Dict[str, Any] | None:
    if not isinstance(record, dict):
        return None

    details = record.get("details")
    if not isinstance(details, dict):
        return None

    summary: Dict[str, Any] = {}
    for key in ("message", "trade_date", "start_date", "end_date", "sync_type", "reason"):
        if key in details:
            summary[key] = details.get(key)

    index_results = details.get("index_results")
    if isinstance(index_results, list):
        summary["index_results"] = [
            {
                "ts_code": item.get("ts_code"),
                "source": item.get("source"),
                "record_count": item.get("record_count"),
                "write_count": item.get("write_count"),
                "duration_ms": item.get("duration_ms"),
            }
            for item in index_results[:10]
            if isinstance(item, dict)
        ]

    failed_items = details.get("failed_items")
    if isinstance(failed_items, list):
        summary["failed_items"] = failed_items[:10]

    return summary or None


async def get_recent_failed_job_executions(
    *,
    limit: int = 10,
    lookback_hours: int = 24,
    core_jobs_only: bool = False,
) -> Dict[str, Any]:
    """获取最近失败任务记录，便于运维快速排查。"""
    safe_limit = max(1, min(int(limit or 10), 100))
    safe_hours = max(1, min(int(lookback_hours or 24), 24 * 30))
    cutoff = datetime.now(UTC) - timedelta(hours=safe_hours)

    query: Dict[str, Any] = {
        "status": "failed",
        "started_at": {"$gte": cutoff},
    }
    if core_jobs_only:
        query["job_name"] = {"$in": sorted(CORE_JOB_NAMES)}

    records = await mongo_manager.find_many(
        "job_execution_records",
        query,
        sort=[("started_at", -1)],
        limit=safe_limit,
    )
    normalized = [_normalize(record) for record in records]
    return {
        "success": True,
        "count": len(normalized),
        "lookback_hours": safe_hours,
        "core_jobs_only": core_jobs_only,
        "records": normalized,
    }


async def get_recent_ops_events(
    *,
    limit: int = 10,
    severities: Iterable[str] | None = None,
    lookback_hours: int = 24,
) -> Dict[str, Any]:
    """获取最近运维事件。"""
    safe_limit = max(1, min(int(limit or 10), 100))
    safe_hours = max(1, min(int(lookback_hours or 24), 24 * 30))
    cutoff = datetime.now(UTC) - timedelta(hours=safe_hours)
    query: Dict[str, Any] = {}
    normalized_severities = [
        str(item).strip().lower()
        for item in (severities or [])
        if str(item).strip()
    ]
    query["created_at"] = {"$gte": cutoff}
    if normalized_severities:
        query["severity"] = {"$in": normalized_severities}

    records = await mongo_manager.find_many(
        "ops_events",
        query,
        sort=[("created_at", -1)],
        limit=safe_limit,
    )
    normalized = [_normalize(record) for record in records]
    return {
        "success": True,
        "count": len(normalized),
        "lookback_hours": safe_hours,
        "severities": normalized_severities,
        "records": normalized,
    }


async def get_recent_dead_letters(
    *,
    limit: int = 10,
    lookback_hours: int = 24,
) -> Dict[str, Any]:
    """获取最近死信/脏数据样本，避免坏数据只停留在日志里。"""
    safe_limit = max(1, min(int(limit or 10), 100))
    safe_hours = max(1, min(int(lookback_hours or 24), 24 * 30))
    cutoff = datetime.now(UTC) - timedelta(hours=safe_hours)
    query = {"created_at": {"$gte": cutoff}}

    records = await mongo_manager.find_many(
        "datasync_dead_letters",
        query,
        projection={
            "dead_letter_id": 1,
            "job_name": 1,
            "collection": 1,
            "source": 1,
            "target_trade_date": 1,
            "reason": 1,
            "error_type": 1,
            "created_at": 1,
            "raw_item": 1,
        },
        sort=[("created_at", -1)],
        limit=safe_limit,
    )
    count = await mongo_manager.count("datasync_dead_letters", query)
    normalized = [_normalize(record) for record in records]
    core_records = [
        record for record in normalized
        if str(record.get("job_name") or "") in CORE_JOB_NAMES
    ]
    return {
        "success": True,
        "count": count,
        "sample_count": len(normalized),
        "core_count_in_sample": len(core_records),
        "lookback_hours": safe_hours,
        "records": normalized,
    }


async def get_core_job_runtime_summary(
    *,
    lookback_hours: int = 24,
) -> Dict[str, Any]:
    """汇总最近窗口内核心任务的运行表现。"""
    safe_hours = max(1, min(int(lookback_hours or 24), 24 * 30))
    cutoff = datetime.now(UTC) - timedelta(hours=safe_hours)

    records = await mongo_manager.find_many(
        "job_execution_records",
        {
            "job_name": {"$in": sorted(CORE_JOB_NAMES)},
            "started_at": {"$gte": cutoff},
        },
        sort=[("started_at", -1)],
        limit=1000,
    )

    grouped: Dict[str, List[Dict[str, Any]]] = {job_name: [] for job_name in sorted(CORE_JOB_NAMES)}
    for record in records:
        job_name = str(record.get("job_name") or "").strip()
        if job_name in grouped:
            grouped[job_name].append(record)

    jobs: List[Dict[str, Any]] = []
    for job_name, job_records in grouped.items():
        success_count = sum(1 for record in job_records if str(record.get("status") or "") == "success")
        failure_count = sum(1 for record in job_records if str(record.get("status") or "") == "failed")
        skipped_count = sum(1 for record in job_records if str(record.get("status") or "") == "skipped")
        executed_records = [
            record for record in job_records if str(record.get("status") or "") in {"success", "failed"}
        ]
        durations = sorted(
            duration
            for duration in (_derive_duration_ms(record) for record in executed_records)
            if duration is not None
        )
        latest = job_records[0] if job_records else None
        total_runs = len(job_records)
        executed_runs = success_count + failure_count
        success_rate = round(success_count / executed_runs, 4) if executed_runs else None
        latest_executed = next(
            (record for record in job_records if str(record.get("status") or "") in {"success", "failed"}),
            None,
        )

        jobs.append(
            {
                "job_name": job_name,
                "total_runs": total_runs,
                "executed_runs": executed_runs,
                "success_count": success_count,
                "failure_count": failure_count,
                "skipped_count": skipped_count,
                "success_rate": success_rate,
                "latest_status": latest.get("status") if latest else None,
                "latest_started_at": _normalize(latest.get("started_at")) if latest else None,
                "latest_finished_at": _normalize(latest.get("finished_at")) if latest else None,
                "latest_trigger": latest.get("trigger") if latest else None,
                "latest_trade_date": latest.get("target_trade_date") if latest else None,
                "latest_executed_status": latest_executed.get("status") if latest_executed else None,
                "latest_executed_started_at": _normalize(latest_executed.get("started_at")) if latest_executed else None,
                "latest_executed_finished_at": _normalize(latest_executed.get("finished_at")) if latest_executed else None,
                "latest_executed_trigger": latest_executed.get("trigger") if latest_executed else None,
                "latest_executed_trade_date": latest_executed.get("target_trade_date") if latest_executed else None,
                "latest_executed_details_summary": _summarize_job_details(latest_executed),
                "duration_sample_count": len(durations),
                "duration_samples_from_executed_runs": True,
                "avg_duration_ms": round(mean(durations), 3) if durations else None,
                "p95_duration_ms": round(_percentile(durations, 0.95), 3) if durations else None,
                "max_duration_ms": round(durations[-1], 3) if durations else None,
                "min_duration_ms": round(durations[0], 3) if durations else None,
            }
        )

    ranked_jobs = sorted(
        jobs,
        key=lambda item: (
            item.get("p95_duration_ms") is None,
            -(item.get("p95_duration_ms") or 0.0),
            -(item.get("avg_duration_ms") or 0.0),
        ),
    )
    active_jobs = [item["job_name"] for item in ranked_jobs if int(item.get("total_runs") or 0) > 0]
    inactive_jobs = [item["job_name"] for item in ranked_jobs if int(item.get("total_runs") or 0) == 0]
    outlier_jobs = _identify_core_runtime_outliers({"jobs": ranked_jobs})

    return {
        "success": True,
        "lookback_hours": safe_hours,
        "job_count": len(ranked_jobs),
        "active_job_count": len(active_jobs),
        "inactive_job_count": len(inactive_jobs),
        "active_jobs": active_jobs,
        "inactive_jobs": inactive_jobs,
        "outlier_job_count": len(outlier_jobs),
        "outlier_jobs": outlier_jobs,
        "jobs": ranked_jobs,
    }


async def get_backfill_queue_status(limit: int = 10) -> Dict[str, Any]:
    """获取补缺队列摘要，避免 ops-summary 输出过大明细。"""
    safe_limit = max(1, min(int(limit or 10), 20))
    status_counts: Dict[str, int] = {}
    for status in BACKFILL_QUEUE_STATUSES:
        status_counts[status] = await mongo_manager.count("datasync_backfill_jobs", {"status": status})

    recent_jobs = await mongo_manager.find_many(
        "datasync_backfill_jobs",
        {},
        projection={
            "job_id": 1,
            "dataset": 1,
            "target_trade_date": 1,
            "status": 1,
            "priority": 1,
            "attempts": 1,
            "last_error": 1,
            "created_at": 1,
            "updated_at": 1,
            "finished_at": 1,
        },
        sort=[("updated_at", -1), ("created_at", -1)],
        limit=safe_limit,
    )
    recent_budgets = await mongo_manager.find_many(
        "datasync_backfill_budgets",
        {},
        sort=[("budget_date", -1)],
        limit=3,
    )
    limits = {
        "jobs_per_round": int(settings.data_sync.backfill_jobs_per_round or 0),
        "max_attempts": int(settings.data_sync.backfill_max_attempts or 0),
        "max_jobs_per_night": int(settings.data_sync.backfill_max_jobs_per_night or 0),
        "max_external_requests_per_night": int(settings.data_sync.backfill_max_external_requests_per_night or 0),
        "consecutive_failure_limit": int(settings.data_sync.backfill_consecutive_failure_limit or 0),
    }
    latest_budget = recent_budgets[0] if recent_budgets else None
    budget_exhausted = False
    consecutive_failure_exhausted = False
    if latest_budget:
        budget_exhausted = bool(
            int(latest_budget.get("jobs_consumed") or 0) >= max(1, limits["max_jobs_per_night"])
            or int(latest_budget.get("external_requests") or 0) >= max(1, limits["max_external_requests_per_night"])
        )
        consecutive_failure_exhausted = bool(
            int(latest_budget.get("consecutive_failures") or 0) >= max(1, limits["consecutive_failure_limit"])
        )

    pending_count = status_counts.get("pending", 0)
    running_count = status_counts.get("running", 0)
    failed_count = status_counts.get("failed", 0)
    operational = not consecutive_failure_exhausted
    return {
        "success": True,
        "operational": operational,
        "status_counts": status_counts,
        "active_count": pending_count + running_count,
        "failed_count": failed_count,
        "limits": limits,
        "latest_budget": _normalize(latest_budget) if latest_budget else None,
        "recent_budgets": _normalize(recent_budgets),
        "recent_jobs": _normalize(recent_jobs),
        "budget_exhausted": budget_exhausted,
        "consecutive_failure_exhausted": consecutive_failure_exhausted,
        "sample_limit": safe_limit,
    }


def _collect_failure_job_names(records: Iterable[Dict[str, Any]]) -> List[str]:
    names: List[str] = []
    seen = set()
    for record in records:
        job_name = str(record.get("job_name") or "").strip()
        if not job_name or job_name in seen:
            continue
        seen.add(job_name)
        names.append(job_name)
    return names


def _collect_event_types(records: Iterable[Dict[str, Any]]) -> List[str]:
    event_types: List[str] = []
    seen = set()
    for record in records:
        event_type = str(record.get("event_type") or "").strip()
        if not event_type or event_type in seen:
            continue
        seen.add(event_type)
        event_types.append(event_type)
    return event_types


def build_probe_checks(
    *,
    summary_success: bool,
    sync_targets: Dict[str, Any],
    core_integrity: Dict[str, Any],
    unresolved_recent_failures: Dict[str, Any],
    unresolved_recent_ops_events: Dict[str, Any],
    data_source_runtime_stats: Dict[str, Any],
    core_job_runtime_summary: Dict[str, Any],
    backfill_queue_status: Dict[str, Any],
) -> Dict[str, bool]:
    """生成稳定的总探针布尔检查，供 CLI 严格模式和监控系统读取。"""
    return {
        "summary_success": bool(summary_success),
        "primary_target_healthy": bool(sync_targets.get("primary", {}).get("healthy")),
        "latest_core_effectively_ready": bool(core_integrity.get("latest_effectively_ready")),
        "recent_window_ready": bool(core_integrity.get("recent_window_ready")),
        "no_unresolved_recent_failures": int(unresolved_recent_failures.get("count") or 0) == 0,
        "no_unresolved_warning_events": int(unresolved_recent_ops_events.get("unresolved_warning_count") or 0) == 0,
        "no_core_data_source_degradation": int(data_source_runtime_stats.get("core_degraded_entry_count") or 0) == 0,
        "no_core_runtime_outliers": int(core_job_runtime_summary.get("outlier_job_count") or 0) == 0,
        "backfill_queue_operational": bool(backfill_queue_status.get("operational", True)),
    }


def derive_operational_status(probe_checks: Dict[str, bool], alerts: List[Dict[str, Any]]) -> str:
    """把总探针折叠成 healthy/degraded/critical 三态。"""
    has_critical_alert = any(
        str(alert.get("severity") or "").lower() == "critical"
        for alert in alerts
    )
    if (
        has_critical_alert
        or not probe_checks.get("summary_success")
        or not probe_checks.get("primary_target_healthy")
        or not probe_checks.get("latest_core_effectively_ready")
    ):
        return "critical"
    if not all(probe_checks.values()):
        return "degraded"
    has_warning_alert = any(
        str(alert.get("severity") or "").lower() == "warning"
        for alert in alerts
    )
    return "degraded" if has_warning_alert else "healthy"


def _collect_data_source_pairs(records: Iterable[Dict[str, Any]]) -> List[str]:
    pairs: List[str] = []
    seen = set()
    for record in records:
        method_name = str(record.get("method_name") or "").strip()
        adapter_name = str(record.get("adapter_name") or "").strip()
        if not method_name or not adapter_name:
            continue
        key = f"{method_name}:{adapter_name}"
        if key in seen:
            continue
        seen.add(key)
        pairs.append(key)
    return pairs


def _identify_core_runtime_outliers(runtime_summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    jobs = runtime_summary.get("jobs", []) if isinstance(runtime_summary, dict) else []
    outliers: List[Dict[str, Any]] = []
    for job in jobs:
        latest_executed_status = str(job.get("latest_executed_status") or "")
        latest_started_at = job.get("latest_executed_started_at")
        latest_finished_at = job.get("latest_executed_finished_at")
        p95_duration_ms = job.get("p95_duration_ms")
        max_duration_ms = job.get("max_duration_ms")
        avg_duration_ms = job.get("avg_duration_ms")

        latest_executed_duration_ms = None
        if latest_started_at and latest_finished_at:
            try:
                latest_executed_duration_ms = max(
                    (datetime.fromisoformat(str(latest_finished_at)) - datetime.fromisoformat(str(latest_started_at))).total_seconds() * 1000,
                    0.0,
                )
            except Exception:
                latest_executed_duration_ms = None

        outlier_reasons: List[str] = []
        if (
            latest_executed_status == "success"
            and isinstance(latest_executed_duration_ms, (int, float))
            and latest_executed_duration_ms >= CORE_JOB_LATEST_EXECUTED_OUTLIER_MS
        ):
            outlier_reasons.append("latest_executed_duration_ms")
        if isinstance(p95_duration_ms, (int, float)) and p95_duration_ms >= CORE_JOB_P95_OUTLIER_MS:
            outlier_reasons.append("p95_duration_ms")

        if not outlier_reasons:
            continue

        outliers.append(
            {
                "job_name": job.get("job_name"),
                "reasons": outlier_reasons,
                "latest_executed_duration_ms": round(latest_executed_duration_ms, 3) if latest_executed_duration_ms is not None else None,
                "latest_executed_started_at": latest_started_at,
                "latest_executed_finished_at": latest_finished_at,
                "latest_executed_trade_date": job.get("latest_executed_trade_date"),
                "latest_executed_trigger": job.get("latest_executed_trigger"),
                "latest_executed_details_summary": job.get("latest_executed_details_summary"),
                "p95_duration_ms": p95_duration_ms,
                "avg_duration_ms": avg_duration_ms,
                "max_duration_ms": max_duration_ms,
                "executed_runs": job.get("executed_runs"),
                "failure_count": job.get("failure_count"),
            }
        )
    return outliers


def _is_effective_execution(record: Dict[str, Any]) -> bool:
    return str(record.get("status") or "") in {"success", "failed"}


def _find_unresolved_failure_records(
    failure_records: Iterable[Dict[str, Any]],
    job_records: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """过滤掉已经被后续成功执行覆盖的失败记录。"""
    normalized_job_records = sorted(
        list(job_records),
        key=lambda item: item.get("started_at") or datetime.min,
        reverse=True,
    )
    unresolved: List[Dict[str, Any]] = []

    for failure in failure_records:
        failure_job = str(failure.get("job_name") or "").strip()
        failure_started_at = failure.get("started_at")
        failure_trade_date = failure.get("target_trade_date")
        resolved = False

        for record in normalized_job_records:
            if str(record.get("job_name") or "").strip() != failure_job:
                continue
            if str(record.get("status") or "") != "success":
                continue

            record_started_at = record.get("started_at")
            if (
                isinstance(failure_started_at, datetime)
                and isinstance(record_started_at, datetime)
                and record_started_at <= failure_started_at
            ):
                continue

            success_trade_date = record.get("target_trade_date")
            if failure_trade_date and success_trade_date and str(success_trade_date) != str(failure_trade_date):
                continue

            resolved = True
            break

        if not resolved:
            unresolved.append(failure)

    return unresolved


def _find_unresolved_warning_ops_records(
    warning_records: Iterable[Dict[str, Any]],
    all_event_records: Iterable[Dict[str, Any]],
    job_records: Iterable[Dict[str, Any]],
    readiness_marker: Dict[str, Any] | None,
) -> List[Dict[str, Any]]:
    """过滤掉已经被后续恢复或 ready marker 覆盖的 warning 事件。"""
    normalized_events = sorted(
        list(all_event_records),
        key=lambda item: item.get("created_at") or datetime.min,
        reverse=True,
    )
    normalized_job_records = sorted(
        list(job_records),
        key=lambda item: item.get("started_at") or datetime.min,
        reverse=True,
    )
    ready_trade_date = str((readiness_marker or {}).get("trade_date") or "")
    ready_status = str((readiness_marker or {}).get("status") or "")
    ready_at_raw = (readiness_marker or {}).get("ready_at")
    ready_at = ready_at_raw if isinstance(ready_at_raw, datetime) else None

    unresolved: List[Dict[str, Any]] = []
    for warning in warning_records:
        event_type = str(warning.get("event_type") or "").strip()
        created_at = warning.get("created_at")
        details = warning.get("details") or {}
        trade_date = str(details.get("trade_date") or "")
        job_name = str(details.get("job_name") or "")
        resolved = False

        if (
            event_type == "core_gap_recovery_completed"
            and trade_date
            and ready_status == "ready"
            and ready_trade_date == trade_date
            and isinstance(created_at, datetime)
            and ready_at
            and ready_at > created_at
        ):
            resolved = True
        elif event_type == "core_job_failed" and job_name:
            for record in normalized_job_records:
                if str(record.get("job_name") or "").strip() != job_name:
                    continue
                if str(record.get("status") or "") != "success":
                    continue
                record_started_at = record.get("started_at")
                if (
                    isinstance(created_at, datetime)
                    and isinstance(record_started_at, datetime)
                    and record_started_at <= created_at
                ):
                    continue
                success_trade_date = str(record.get("target_trade_date") or "")
                target_trade_date = str(details.get("target_trade_date") or "")
                if target_trade_date and success_trade_date and success_trade_date != target_trade_date:
                    continue
                resolved = True
                break
        else:
            for event in normalized_events:
                if str(event.get("event_type") or "").strip() != event_type:
                    continue
                if str(event.get("severity") or "").lower() not in {"info"}:
                    continue
                event_created_at = event.get("created_at")
                if (
                    isinstance(created_at, datetime)
                    and isinstance(event_created_at, datetime)
                    and event_created_at <= created_at
                ):
                    continue
                event_details = event.get("details") or {}
                event_trade_date = str(event_details.get("trade_date") or "")
                if trade_date and event_trade_date and event_trade_date != trade_date:
                    continue
                resolved = True
                break

        if not resolved:
            unresolved.append(warning)

    return unresolved


def _build_alerts(
    *,
    integrity: Dict[str, Any],
    latest_ready: Dict[str, Any] | None,
    sync_targets: Dict[str, Any],
    data_source_runtime_stats: Dict[str, Any],
    recent_failures: Dict[str, Any],
    recent_ops_events: Dict[str, Any],
    recent_dead_letters: Dict[str, Any],
    core_job_runtime_summary: Dict[str, Any],
    readiness_marker: Dict[str, Any] | None,
    backfill_queue_status: Dict[str, Any],
) -> List[Dict[str, Any]]:
    alerts: List[Dict[str, Any]] = []

    primary = sync_targets.get("primary", {}) if isinstance(sync_targets, dict) else {}
    mirror = sync_targets.get("mirror", {}) if isinstance(sync_targets, dict) else {}
    failure_records = recent_failures.get("records", []) if isinstance(recent_failures, dict) else []
    core_failure_records = [
        record for record in failure_records if str(record.get("job_name") or "") in CORE_JOB_NAMES
    ]
    ops_event_records = recent_ops_events.get("records", []) if isinstance(recent_ops_events, dict) else []
    dead_letter_records = recent_dead_letters.get("records", []) if isinstance(recent_dead_letters, dict) else []
    core_dead_letter_records = [
        record for record in dead_letter_records if str(record.get("job_name") or "") in CORE_JOB_NAMES
    ]
    warning_ops_records = [
        record
        for record in ops_event_records
        if str(record.get("severity") or "").lower() in {"warning", "critical"}
    ]
    timeout_entries = data_source_runtime_stats.get("timed_out_entries", []) if isinstance(data_source_runtime_stats, dict) else []
    degraded_source_entries = data_source_runtime_stats.get("degraded_entries", []) if isinstance(data_source_runtime_stats, dict) else []
    core_timeout_entries = data_source_runtime_stats.get("core_timed_out_entries", []) if isinstance(data_source_runtime_stats, dict) else []
    core_degraded_source_entries = data_source_runtime_stats.get("core_degraded_entries", []) if isinstance(data_source_runtime_stats, dict) else []
    unresolved_warning_ops_records = list(
        recent_ops_events.get("unresolved_warning_records", [])
        if isinstance(recent_ops_events, dict)
        else []
    )
    inactive_jobs = core_job_runtime_summary.get("inactive_jobs", []) if isinstance(core_job_runtime_summary, dict) else []
    runtime_outlier_jobs = core_job_runtime_summary.get("outlier_jobs", []) if isinstance(core_job_runtime_summary, dict) else []
    backfill_failed_count = int(backfill_queue_status.get("failed_count") or 0) if isinstance(backfill_queue_status, dict) else 0
    backfill_budget_exhausted = bool(backfill_queue_status.get("budget_exhausted")) if isinstance(backfill_queue_status, dict) else False
    backfill_consecutive_failure_exhausted = bool(backfill_queue_status.get("consecutive_failure_exhausted")) if isinstance(backfill_queue_status, dict) else False
    incomplete_trade_dates = integrity.get("blocking_incomplete_trade_dates", []) if isinstance(integrity, dict) else []
    pending_trade_dates = integrity.get("pending_trade_dates", []) if isinstance(integrity, dict) else []
    latest_expected_ready = bool(integrity.get("latest_trade_date_expected_ready", True)) if isinstance(integrity, dict) else True

    if latest_ready and not latest_ready.get("ready") and latest_expected_ready:
        missing = [
            item.get("dataset")
            for item in latest_ready.get("datasets", [])
            if not item.get("ok")
        ]
        alerts.append(
            {
                "severity": "critical",
                "code": "core_chain_not_ready",
                "trade_date": latest_ready.get("trade_date"),
                "missing_datasets": missing,
                "message": f"Latest core chain is not ready for trade date {latest_ready.get('trade_date')}",
            }
        )

    if pending_trade_dates:
        alerts.append(
            {
                "severity": "info",
                "code": "latest_trade_date_awaiting_sync_window",
                "message": "Latest trade date is still within the expected post-close sync window",
                "trade_dates": pending_trade_dates,
                "ready_after": integrity.get("latest_trade_date_ready_after"),
                "observed_at": integrity.get("latest_trade_date_observed_at"),
            }
        )

    if incomplete_trade_dates:
        alerts.append(
            {
                "severity": "warning",
                "code": "recent_window_incomplete",
                "message": "Recent trade-date window still contains incomplete core days",
                "trade_dates": incomplete_trade_dates,
                "window_days": integrity.get("days"),
            }
        )

    if not primary.get("healthy"):
        alerts.append(
            {
                "severity": "critical",
                "code": "primary_target_unhealthy",
                "message": "Primary Mongo sync target is unhealthy",
                "target": _normalize(primary),
            }
        )

    if mirror.get("enabled") and not mirror.get("healthy"):
        alerts.append(
            {
                "severity": "warning",
                "code": "mirror_target_unhealthy",
                "message": "Mirror Mongo sync target is enabled but unhealthy",
                "target": _normalize(mirror),
            }
        )

    if mirror.get("degraded_since"):
        alerts.append(
            {
                "severity": "warning",
                "code": "mirror_write_path_degraded",
                "message": "Mirror write path is currently degraded",
                "degraded_since": mirror.get("degraded_since"),
                "last_error": mirror.get("last_write_error"),
                "last_error_at": mirror.get("last_write_error_at"),
            }
        )
    elif mirror.get("last_recovered_at"):
        alerts.append(
            {
                "severity": "info",
                "code": "mirror_write_path_recovered",
                "message": "Mirror write path has recovered from a previous degradation",
                "last_recovered_at": mirror.get("last_recovered_at"),
                "last_write_success_at": mirror.get("last_write_success_at"),
            }
        )

    if int(mirror.get("write_failure_count") or 0) > 0:
        alerts.append(
            {
                "severity": "warning",
                "code": "mirror_write_failures_detected",
                "message": "Mirror target has recent write failures",
                "write_failure_count": mirror.get("write_failure_count", 0),
                "last_error": mirror.get("last_write_error"),
                "last_error_at": mirror.get("last_write_error_at"),
            }
        )

    if core_timeout_entries:
        alerts.append(
            {
                "severity": "warning",
                "code": "core_data_source_timeouts_detected",
                "message": "Recent runtime data-source timeouts were observed on core sync methods in the current DataSync process",
                "count": len(core_timeout_entries),
                "sources": _collect_data_source_pairs(core_timeout_entries),
            }
        )
    elif core_degraded_source_entries:
        alerts.append(
            {
                "severity": "warning",
                "code": "core_data_source_degradation_detected",
                "message": "Recent runtime data-source failures or fallbacks were observed on core sync methods in the current DataSync process",
                "count": len(core_degraded_source_entries),
                "sources": _collect_data_source_pairs(core_degraded_source_entries),
            }
        )
    elif timeout_entries:
        alerts.append(
            {
                "severity": "info",
                "code": "non_core_data_source_timeouts_detected",
                "message": "Recent runtime data-source timeouts were observed on non-core methods in the current DataSync process",
                "count": len(timeout_entries),
                "sources": _collect_data_source_pairs(timeout_entries),
            }
        )
    elif degraded_source_entries:
        alerts.append(
            {
                "severity": "info",
                "code": "non_core_data_source_fallbacks_detected",
                "message": "Recent runtime data-source fallbacks or source errors were observed on non-core methods in the current DataSync process",
                "count": len(degraded_source_entries),
                "sources": _collect_data_source_pairs(degraded_source_entries),
            }
        )

    if core_failure_records:
        alerts.append(
            {
                "severity": "warning",
                "code": "recent_core_job_failures",
                "message": "Recent failures detected in core sync jobs",
                "jobs": _collect_failure_job_names(core_failure_records),
                "count": len(core_failure_records),
            }
        )
    elif failure_records:
        alerts.append(
            {
                "severity": "info",
                "code": "recent_non_core_job_failures",
                "message": "Recent failures detected in non-core jobs",
                "jobs": _collect_failure_job_names(failure_records),
                "count": len(failure_records),
            }
        )

    if unresolved_warning_ops_records:
        alerts.append(
            {
                "severity": "warning",
                "code": "recent_warning_ops_events",
                "message": "Recent warning or critical operational events were recorded",
                "count": len(unresolved_warning_ops_records),
                "event_types": _collect_event_types(unresolved_warning_ops_records),
                "lookback_hours": recent_ops_events.get("lookback_hours"),
            }
        )

    if core_dead_letter_records:
        alerts.append(
            {
                "severity": "warning",
                "code": "recent_core_dead_letters",
                "message": "Recent bad records were captured from core DataSync collectors",
                "count": len(core_dead_letter_records),
                "jobs": sorted({str(record.get("job_name")) for record in core_dead_letter_records if record.get("job_name")}),
                "lookback_hours": recent_dead_letters.get("lookback_hours"),
            }
        )
    elif dead_letter_records:
        alerts.append(
            {
                "severity": "info",
                "code": "recent_non_core_dead_letters",
                "message": "Recent bad records were captured from non-core DataSync collectors",
                "count": len(dead_letter_records),
                "jobs": sorted({str(record.get("job_name")) for record in dead_letter_records if record.get("job_name")}),
                "lookback_hours": recent_dead_letters.get("lookback_hours"),
            }
        )

    if inactive_jobs:
        alerts.append(
            {
                "severity": "warning",
                "code": "core_jobs_without_recent_samples",
                "message": "Some core sync jobs have no recent execution samples in the runtime summary window",
                "inactive_jobs": inactive_jobs,
                "lookback_hours": core_job_runtime_summary.get("lookback_hours"),
            }
        )

    if runtime_outlier_jobs:
        alerts.append(
            {
                "severity": "warning",
                "code": "core_job_runtime_outliers",
                "message": "Some core sync jobs show unusually long execution durations in the recent runtime window",
                "count": len(runtime_outlier_jobs),
                "jobs": [item.get("job_name") for item in runtime_outlier_jobs if item.get("job_name")],
                "thresholds": {
                    "latest_executed_duration_ms": CORE_JOB_LATEST_EXECUTED_OUTLIER_MS,
                    "p95_duration_ms": CORE_JOB_P95_OUTLIER_MS,
                },
            }
        )

    if backfill_consecutive_failure_exhausted:
        alerts.append(
            {
                "severity": "warning",
                "code": "backfill_queue_failure_circuit_open",
                "message": "Backfill queue stopped because consecutive failures reached the configured limit",
                "latest_budget": backfill_queue_status.get("latest_budget"),
                "limits": backfill_queue_status.get("limits"),
            }
        )
    elif backfill_budget_exhausted:
        alerts.append(
            {
                "severity": "info",
                "code": "backfill_budget_exhausted",
                "message": "Backfill queue reached the configured nightly budget",
                "latest_budget": backfill_queue_status.get("latest_budget"),
                "limits": backfill_queue_status.get("limits"),
            }
        )

    if backfill_failed_count:
        alerts.append(
            {
                "severity": "warning",
                "code": "backfill_queue_failed_jobs",
                "message": "Backfill queue has failed jobs that need review",
                "failed_count": backfill_failed_count,
                "status_counts": backfill_queue_status.get("status_counts"),
            }
        )

    if readiness_marker and readiness_marker.get("status") == "ready":
        source = str(readiness_marker.get("source") or "")
        if "recovery" in source:
            alerts.append(
                {
                    "severity": "info",
                    "code": "recent_core_gap_recovery",
                    "message": "Core chain was recently marked ready by a recovery flow",
                    "trade_date": readiness_marker.get("trade_date"),
                    "source": source,
                    "ready_at": readiness_marker.get("ready_at"),
                }
            )

    return alerts


async def build_ops_summary(
    *,
    integrity_days: int = 3,
    recent_job_limit: int = 10,
    recent_failure_lookback_hours: int = 24,
    recent_event_lookback_hours: int = 24,
    core_runtime_lookback_hours: int = 24,
) -> Dict[str, Any]:
    """构建一份便于运维查看的总览。"""
    failure_cutoff = datetime.now(UTC) - timedelta(
        hours=max(1, min(int(recent_failure_lookback_hours or 24), 24 * 30))
    )
    integrity = await build_core_integrity_overview(days=integrity_days)
    sync_targets = await mongo_manager.get_target_status()
    readiness_marker = await mongo_manager.find_one(
        "readiness_markers",
        {"marker_type": "market_core_ready"},
        sort=[("trade_date", -1)],
    )
    recent_jobs = await mongo_manager.find_many(
        "job_execution_records",
        {},
        sort=[("started_at", -1)],
        limit=max(1, min(int(recent_job_limit or 10), 50)),
    )
    recent_effective_jobs = await mongo_manager.find_many(
        "job_execution_records",
        {"status": {"$in": ["success", "failed"]}},
        sort=[("started_at", -1)],
        limit=max(1, min(int(recent_job_limit or 10), 50)),
    )
    recent_core_effective_jobs = await mongo_manager.find_many(
        "job_execution_records",
        {
            "job_name": {"$in": sorted(CORE_JOB_NAMES)},
            "status": {"$in": ["success", "failed"]},
        },
        sort=[("started_at", -1)],
        limit=max(1, min(int(recent_job_limit or 10), 50)),
    )
    recent_failures = await get_recent_failed_job_executions(
        limit=min(max(1, int(recent_job_limit or 10)), 20),
        lookback_hours=recent_failure_lookback_hours,
    )
    recent_failure_records_raw = await mongo_manager.find_many(
        "job_execution_records",
        {
            "status": "failed",
            "started_at": {"$gte": failure_cutoff},
        },
        sort=[("started_at", -1)],
        limit=min(max(1, int(recent_job_limit or 10)), 20),
    )
    recent_ops_events = await get_recent_ops_events(
        limit=min(max(1, int(recent_job_limit or 10)), 20),
        lookback_hours=recent_event_lookback_hours,
    )
    recent_dead_letters = await get_recent_dead_letters(
        limit=min(max(1, int(recent_job_limit or 10)), 20),
        lookback_hours=recent_event_lookback_hours,
    )
    backfill_queue_status = await get_backfill_queue_status(limit=min(max(1, int(recent_job_limit or 10)), 20))
    data_source_runtime_stats = data_source_manager.get_call_stats_summary()
    recent_core_job_records = await mongo_manager.find_many(
        "job_execution_records",
        {
            "job_name": {"$in": sorted(CORE_JOB_NAMES)},
            "started_at": {"$gte": failure_cutoff},
        },
        sort=[("started_at", -1)],
        limit=500,
    )
    core_job_runtime_summary = await get_core_job_runtime_summary(
        lookback_hours=core_runtime_lookback_hours,
    )

    latest_ready = None
    if integrity.get("overview"):
        latest_ready = integrity["overview"][-1]

    normalized_targets = _normalize(sync_targets)
    normalized_marker = _normalize(readiness_marker) if readiness_marker else None
    unresolved_warning_records_raw = _find_unresolved_warning_ops_records(
        [
            record
            for record in (recent_ops_events.get("records") or [])
            if str(record.get("severity") or "").lower() in {"warning", "critical"}
        ],
        recent_ops_events.get("records") or [],
        recent_core_job_records,
        readiness_marker,
    )
    unresolved_recent_ops_events = {
        **recent_ops_events,
        "unresolved_warning_records": _normalize(unresolved_warning_records_raw),
        "unresolved_warning_count": len(unresolved_warning_records_raw),
    }
    unresolved_recent_failures = {
        **recent_failures,
        "records": _normalize(
            _find_unresolved_failure_records(
                recent_failure_records_raw,
                recent_core_job_records,
            )
        ),
    }
    unresolved_recent_failures["count"] = len(unresolved_recent_failures.get("records", []))
    alerts = _build_alerts(
        integrity=integrity,
        latest_ready=latest_ready,
        sync_targets=normalized_targets,
        data_source_runtime_stats=_normalize(data_source_runtime_stats),
        recent_failures=unresolved_recent_failures,
        recent_ops_events=unresolved_recent_ops_events,
        recent_dead_letters=recent_dead_letters,
        core_job_runtime_summary=core_job_runtime_summary,
        readiness_marker=normalized_marker,
        backfill_queue_status=backfill_queue_status,
    )
    probe_checks = build_probe_checks(
        summary_success=True,
        sync_targets=normalized_targets,
        core_integrity=integrity,
        unresolved_recent_failures=unresolved_recent_failures,
        unresolved_recent_ops_events=unresolved_recent_ops_events,
        data_source_runtime_stats=_normalize(data_source_runtime_stats),
        core_job_runtime_summary=core_job_runtime_summary,
        backfill_queue_status=backfill_queue_status,
    )
    operational_status = derive_operational_status(probe_checks, alerts)

    return {
        "success": True,
        "generated_at": datetime.now(UTC).isoformat(),
        "operational_status": operational_status,
        "probe_checks": probe_checks,
        "core_integrity": integrity,
        "latest_core_overview": latest_ready,
        "sync_targets": normalized_targets,
        "data_source_runtime_stats": _normalize(data_source_runtime_stats),
        "readiness_marker": normalized_marker,
        "recent_job_executions": _normalize(recent_jobs),
        "recent_effective_job_executions": _normalize(recent_effective_jobs),
        "recent_core_effective_job_executions": _normalize(recent_core_effective_jobs),
        "recent_failed_job_executions": recent_failures,
        "unresolved_recent_failed_job_executions": unresolved_recent_failures,
        "recent_ops_events": recent_ops_events,
        "unresolved_recent_ops_events": unresolved_recent_ops_events,
        "recent_dead_letters": recent_dead_letters,
        "backfill_queue_status": backfill_queue_status,
        "recent_backfill_budgets": backfill_queue_status.get("recent_budgets", []),
        "core_job_runtime_summary": core_job_runtime_summary,
        "alerts": alerts,
    }
