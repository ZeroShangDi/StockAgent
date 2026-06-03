"""系统页手动补漏同步后台任务。"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.managers import (
    analysis_manager,
    data_source_manager,
    mongo_manager,
    stock_relation_manager,
)
from nodes.data_sync.collectors.stock.daily_basic import _clean_daily_basic_record
from scripts.sync_stock_daily import (
    sync_index_daily_for_date,
    sync_limit_list_for_date,
    sync_stock_daily_for_date,
)


_RUNTIME_TASKS: set[asyncio.Task] = set()
_TASK_TYPE = "system_gap_fill_sync"
_CORE_INDEX_CODES = ("000001.SH", "399001.SZ", "399006.SZ")
_MARKET_CORE_READY_MARKER_TYPE = "market_core_ready"
_READY_MARKER_STATUSES = {"missing", "waiting_window", "building", "ready", "degraded", "failed"}
_DATASYNC_STATUS_RECENT_LIMIT = 5
_DATASYNC_STATUS_FAILURE_LOOKBACK_DAYS = 7
_DATASYNC_STATUS_OPS_LOOKBACK_HOURS = 72
_BACKFILL_QUEUE_STATUSES = ("pending", "running", "failed", "paused", "done")
_BACKFILL_JOB_ACTIONS = {"pause", "resume", "retry"}


def _json_safe(value: Any) -> Any:
    """把 Mongo 文档转为 API 可稳定返回的结构，避免 ObjectId/日期序列化问题。"""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items() if key != "_id"}
    return value


def _serialize_market_core_readiness(marker: Optional[Dict[str, Any]], trade_date: Optional[str] = None) -> Dict[str, Any]:
    """统一核心市场数据可用性标记的 API 输出契约。"""
    if not marker:
        return {
            "marker_type": _MARKET_CORE_READY_MARKER_TYPE,
            "trade_date": trade_date,
            "status": "missing",
            "ready_at": None,
            "ready_datasets": [],
            "pending_datasets": [],
            "warnings": [],
            "last_checked_at": None,
            "usable": False,
            "source": None,
            "node_id": None,
            "details": {
                "message": "暂无核心市场数据可用性标记",
            },
        }

    status = str(marker.get("status") or "missing")
    if status not in _READY_MARKER_STATUSES:
        status = "failed"

    return {
        "marker_type": marker.get("marker_type") or _MARKET_CORE_READY_MARKER_TYPE,
        "trade_date": marker.get("trade_date") or trade_date,
        "status": status,
        "ready_at": _json_safe(marker.get("ready_at")),
        "ready_datasets": _json_safe(marker.get("ready_datasets") or []),
        "pending_datasets": _json_safe(marker.get("pending_datasets") or []),
        "warnings": _json_safe(marker.get("warnings") or []),
        "last_checked_at": _json_safe(marker.get("last_checked_at") or marker.get("updated_at")),
        "usable": status in {"ready", "degraded"},
        "source": marker.get("source"),
        "node_id": marker.get("node_id"),
        "details": _json_safe(marker.get("details") or {}),
    }


async def get_market_core_readiness_marker(trade_date: Optional[str] = None) -> Dict[str, Any]:
    """读取最新或指定交易日的核心市场数据 ready marker。"""
    query: Dict[str, Any] = {"marker_type": _MARKET_CORE_READY_MARKER_TYPE}
    normalized_trade_date = str(trade_date or "").strip() or None
    if normalized_trade_date:
        query["trade_date"] = normalized_trade_date

    marker = await mongo_manager.find_one(
        "readiness_markers",
        query,
        sort=[("trade_date", -1), ("updated_at", -1)],
    )
    return _serialize_market_core_readiness(marker, trade_date=normalized_trade_date)


async def get_datasync_status_panel() -> Dict[str, Any]:
    """返回系统页展示 DataSync 状态所需的轻量汇总。

    这个接口只做小范围读取和有限列表，避免系统状态页本身给 Mongo 带来额外压力。
    """
    generated_at = datetime.now(UTC)
    readiness = await get_market_core_readiness_marker()
    capability_catalog = _load_datasync_capability_catalog()
    expected_datasets = _get_expected_core_datasets(capability_catalog, readiness)
    ready_datasets = _normalize_dataset_list(readiness.get("ready_datasets"))
    pending_datasets = _normalize_dataset_list(readiness.get("pending_datasets"))
    missing_datasets = sorted((set(expected_datasets) - set(ready_datasets)) | set(pending_datasets))
    recoverability_summary = _build_recoverability_summary(capability_catalog, missing_datasets)

    recent_failures = await _get_recent_datasync_failures(capability_catalog)
    backfill_queue = await _get_backfill_queue_status()
    recent_ops_events = await _get_recent_ops_events()

    return {
        "generated_at": _json_safe(generated_at),
        "core_readiness": readiness,
        "core_status": {
            "trade_date": readiness.get("trade_date"),
            "status": readiness.get("status"),
            "usable": bool(readiness.get("usable")),
            "expected_datasets": expected_datasets,
            "ready_datasets": ready_datasets,
            "pending_datasets": pending_datasets,
            "missing_datasets": missing_datasets,
            "warnings": _json_safe(readiness.get("warnings") or []),
        },
        "capability_catalog": capability_catalog,
        "recoverability_summary": recoverability_summary,
        "recent_failures": recent_failures,
        "backfill_queue": backfill_queue,
        "recent_ops_events": recent_ops_events,
        "actions": {
            "manual_gap_fill": {
                "method": "POST",
                "endpoint": "/api/v1/system/manual-sync/gap-fill",
                "description": "安全补最近 1-10 个交易日核心数据，默认 3 天。",
            },
            "enqueue_backfill_job": {
                "method": "POST",
                "endpoint": "/api/v1/system/datasync/backfill-jobs",
                "description": "把支持补缺的数据集按交易日加入 DataSync 夜间补缺队列。",
            },
            "operate_backfill_job": {
                "method": "PATCH",
                "endpoint": "/api/v1/system/datasync/backfill-jobs/{job_id}/action",
                "description": "暂停、恢复或重试补缺队列任务；不支持直接中断 running 任务。",
            },
            "core_readiness": {
                "method": "GET",
                "endpoint": "/api/v1/system/data-readiness/market-core",
                "description": "查看最新或指定交易日核心 ready marker。",
            },
        },
    }


def _load_datasync_capability_catalog() -> Dict[str, Any]:
    """读取独立 DataSync 生成的能力目录；不可用时返回最小结构。"""
    catalog_path = Path(__file__).resolve().parents[4] / "DataSync" / "config" / "datasync_capabilities.yaml"
    fallback = {
        "success": False,
        "profile": None,
        "count": 0,
        "core_ready_marker": _MARKET_CORE_READY_MARKER_TYPE,
        "core_ready_datasets": [],
        "core_recoverable_datasets": [],
        "capabilities": [],
        "error": "datasync_capability_catalog_unavailable",
    }
    if not catalog_path.exists():
        fallback["path"] = str(catalog_path)
        return fallback

    try:
        import yaml

        with catalog_path.open("r", encoding="utf-8") as fp:
            raw_catalog = yaml.safe_load(fp) or {}
    except Exception as exc:
        fallback["error"] = str(exc)
        fallback["path"] = str(catalog_path)
        return fallback

    capabilities = raw_catalog.get("capabilities") or []
    return {
        "success": bool(raw_catalog.get("success", True)),
        "profile": raw_catalog.get("profile"),
        "count": int(raw_catalog.get("count") or len(capabilities)),
        "core_ready_marker": raw_catalog.get("core_ready_marker") or _MARKET_CORE_READY_MARKER_TYPE,
        "core_ready_datasets": _normalize_dataset_list(raw_catalog.get("core_ready_datasets")),
        "core_recoverable_datasets": _normalize_dataset_list(raw_catalog.get("core_recoverable_datasets")),
        "capabilities": [
            {
                "name": item.get("name"),
                "description": item.get("description"),
                "dataset_name": item.get("dataset_name") or item.get("name"),
                "resource_class": item.get("resource_class"),
                "effective_schedule": item.get("effective_schedule") or item.get("default_schedule"),
                "supports_backfill": bool(item.get("supports_backfill")),
                "supports_recover_trade_date": bool(item.get("supports_recover_trade_date")),
                "recoverability": _json_safe(item.get("recoverability") or {}),
                "target_collections": _json_safe(item.get("target_collections") or []),
            }
            for item in capabilities[:50]
            if isinstance(item, dict)
        ],
    }


def _normalize_dataset_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(item) for item in value if item})


def _get_expected_core_datasets(catalog: Dict[str, Any], readiness: Dict[str, Any]) -> List[str]:
    catalog_datasets = _normalize_dataset_list(catalog.get("core_ready_datasets"))
    if catalog_datasets:
        return catalog_datasets
    return _normalize_dataset_list(
        list(readiness.get("ready_datasets") or []) + list(readiness.get("pending_datasets") or [])
    )


def _build_capability_index(catalog: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    for item in catalog.get("capabilities") or []:
        if not isinstance(item, dict):
            continue
        for key in (item.get("name"), item.get("dataset_name")):
            if key:
                index[str(key)] = item
    return index


def _get_backfill_capability(catalog: Dict[str, Any], dataset: str) -> Optional[Dict[str, Any]]:
    normalized = str(dataset or "").strip()
    if not normalized:
        return None
    return _build_capability_index(catalog).get(normalized)


def _normalize_trade_date(trade_date: str) -> str:
    normalized = str(trade_date or "").strip()
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError("交易日格式必须为 YYYYMMDD")
    return normalized


def _build_backfill_dedupe_key(
    dataset: str,
    target_trade_date: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    safe_dataset = str(dataset or "").strip()
    safe_trade_date = _normalize_trade_date(target_trade_date)
    safe_start = str(start_date or "").strip()
    safe_end = str(end_date or "").strip()
    if not safe_dataset:
        raise ValueError("补缺数据集不能为空")
    return f"{safe_dataset}:{safe_trade_date}:{safe_start}:{safe_end}"


def _build_recoverability_summary(catalog: Dict[str, Any], missing_datasets: List[str]) -> Dict[str, Any]:
    mode_counts: Dict[str, int] = {"full": 0, "best_effort": 0, "none": 0, "unknown": 0}
    warning_or_critical = []
    non_recoverable = []
    capability_index = _build_capability_index(catalog)

    for item in catalog.get("capabilities") or []:
        if not isinstance(item, dict):
            continue
        recoverability = item.get("recoverability") if isinstance(item.get("recoverability"), dict) else {}
        mode = str(recoverability.get("mode") or "unknown")
        mode_counts[mode if mode in mode_counts else "unknown"] += 1
        severity = str(recoverability.get("severity_on_missing") or "").lower()
        if severity in {"warning", "critical"}:
            warning_or_critical.append(item.get("name"))
        if mode == "none":
            non_recoverable.append(
                {
                    "name": item.get("name"),
                    "dataset_name": item.get("dataset_name"),
                    "severity_on_missing": severity or None,
                    "reason": recoverability.get("reason"),
                }
            )

    missing_with_recoverability = []
    for dataset in missing_datasets:
        capability = capability_index.get(dataset) or {}
        recoverability = capability.get("recoverability") if isinstance(capability.get("recoverability"), dict) else {}
        missing_with_recoverability.append(
            {
                "dataset": dataset,
                "mode": recoverability.get("mode") or "unknown",
                "severity_on_missing": recoverability.get("severity_on_missing"),
                "reason": recoverability.get("reason"),
            }
        )

    return {
        "mode_counts": mode_counts,
        "warning_or_critical_count": len([item for item in warning_or_critical if item]),
        "non_recoverable_capabilities": non_recoverable[:20],
        "missing_datasets": missing_with_recoverability,
    }


async def _get_recent_datasync_failures(catalog: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    cutoff = datetime.now(UTC) - timedelta(days=_DATASYNC_STATUS_FAILURE_LOOKBACK_DAYS)
    records = await mongo_manager.find_many(
        "job_execution_records",
        {"status": "failed", "started_at": {"$gte": cutoff}},
        projection={
            "_id": 0,
            "job_name": 1,
            "status": 1,
            "trigger": 1,
            "pipeline_name": 1,
            "target_trade_date": 1,
            "started_at": 1,
            "completed_at": 1,
            "duration_ms": 1,
            "error": 1,
            "error_message": 1,
            "result": 1,
        },
        sort=[("started_at", -1)],
        limit=_DATASYNC_STATUS_RECENT_LIMIT,
    )
    capability_index = _build_capability_index(catalog or {})
    return [_summarize_execution_record(record, capability_index) for record in records]


def _summarize_execution_record(
    record: Dict[str, Any],
    capability_index: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    result = record.get("result") if isinstance(record.get("result"), dict) else {}
    error = record.get("error") or record.get("error_message") or result.get("error") or result.get("reason")
    job_name = record.get("job_name")
    capability = (capability_index or {}).get(str(job_name)) if job_name else None
    recoverability = capability.get("recoverability") if isinstance(capability, dict) else None
    return {
        "job_name": job_name,
        "status": record.get("status"),
        "trigger": record.get("trigger"),
        "pipeline_name": record.get("pipeline_name"),
        "target_trade_date": record.get("target_trade_date"),
        "started_at": _json_safe(record.get("started_at")),
        "completed_at": _json_safe(record.get("completed_at")),
        "duration_ms": record.get("duration_ms"),
        "error": str(error)[:300] if error else None,
        "recoverability": _json_safe(recoverability or result.get("recoverability") or {}),
    }


async def _get_recent_ops_events() -> List[Dict[str, Any]]:
    cutoff = datetime.now(UTC) - timedelta(hours=_DATASYNC_STATUS_OPS_LOOKBACK_HOURS)
    records = await mongo_manager.find_many(
        "ops_events",
        {
            "created_at": {"$gte": cutoff},
            "source": {"$in": ["datasync", "web"]},
        },
        projection={
            "_id": 0,
            "event_id": 1,
            "event_type": 1,
            "severity": 1,
            "message": 1,
            "source": 1,
            "node_id": 1,
            "details": 1,
            "created_at": 1,
        },
        sort=[("created_at", -1)],
        limit=_DATASYNC_STATUS_RECENT_LIMIT,
    )
    return [_summarize_ops_event(record) for record in records]


def _summarize_ops_event(record: Dict[str, Any]) -> Dict[str, Any]:
    details = record.get("details") if isinstance(record.get("details"), dict) else {}
    return {
        "event_id": record.get("event_id"),
        "event_type": record.get("event_type"),
        "severity": record.get("severity"),
        "message": str(record.get("message"))[:300] if record.get("message") else None,
        "source": record.get("source"),
        "node_id": record.get("node_id"),
        "created_at": _json_safe(record.get("created_at")),
        "details": _json_safe(
            {
                key: details.get(key)
                for key in (
                    "job_id",
                    "dataset",
                    "target_trade_date",
                    "action",
                    "previous_status",
                    "next_status",
                    "user_id",
                    "failure_point",
                    "failed_trade_dates",
                )
                if key in details
            }
        ),
    }


async def _get_backfill_queue_status() -> Dict[str, Any]:
    status_counts: Dict[str, int] = {}
    for status in _BACKFILL_QUEUE_STATUSES:
        try:
            status_counts[status] = await mongo_manager.count("datasync_backfill_jobs", {"status": status})
        except Exception:
            status_counts[status] = 0

    recent_jobs = await mongo_manager.find_many(
        "datasync_backfill_jobs",
        {},
        projection={
            "_id": 0,
            "job_id": 1,
            "dataset": 1,
            "target_trade_date": 1,
            "status": 1,
            "priority": 1,
            "attempts": 1,
            "max_attempts": 1,
            "error": 1,
            "last_error": 1,
            "updated_at": 1,
            "created_at": 1,
        },
        sort=[("updated_at", -1), ("created_at", -1)],
        limit=_DATASYNC_STATUS_RECENT_LIMIT,
    )

    return {
        "status_counts": status_counts,
        "pending_total": int(status_counts.get("pending", 0) or 0),
        "running_total": int(status_counts.get("running", 0) or 0),
        "failed_total": int(status_counts.get("failed", 0) or 0),
        "recent_jobs": [_summarize_backfill_job(job) for job in recent_jobs],
    }


def _summarize_backfill_job(job: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "job_id": job.get("job_id"),
        "dataset": job.get("dataset"),
        "target_trade_date": job.get("target_trade_date"),
        "status": job.get("status"),
        "priority": job.get("priority"),
        "attempts": job.get("attempts"),
        "max_attempts": job.get("max_attempts"),
        "error": str(job.get("error") or job.get("last_error"))[:300] if job.get("error") or job.get("last_error") else None,
        "updated_at": _json_safe(job.get("updated_at")),
        "created_at": _json_safe(job.get("created_at")),
    }


async def create_datasync_backfill_job(
    *,
    user_id: str,
    dataset: str,
    trade_date: str,
    priority: int = 100,
) -> Dict[str, Any]:
    """把指定数据集和交易日加入 DataSync 夜间补缺队列。

    Web 只负责安全入队，不直接消费队列；实际补缺仍由 DataSync worker 在预算和闲时窗口内执行。
    """
    catalog = _load_datasync_capability_catalog()
    capability = _get_backfill_capability(catalog, dataset)
    if not capability:
        raise ValueError("数据集不在 DataSync 能力目录中，不能创建补缺任务")

    recoverability = capability.get("recoverability") if isinstance(capability.get("recoverability"), dict) else {}
    mode = str(recoverability.get("mode") or "unknown")
    supports_recover = bool(capability.get("supports_recover_trade_date") or capability.get("supports_backfill"))
    if mode == "none" or not supports_recover:
        raise ValueError("该数据集不支持可靠补缺，不能加入补缺队列")

    job_name = str(capability.get("name") or dataset).strip()
    normalized_trade_date = _normalize_trade_date(trade_date)
    safe_priority = max(1, min(int(priority or 100), 999))
    dedupe_key = _build_backfill_dedupe_key(job_name, normalized_trade_date)
    existing = await mongo_manager.find_one("datasync_backfill_jobs", {"dedupe_key": dedupe_key})

    now = datetime.now(UTC)
    job_id = uuid.uuid4().hex
    await mongo_manager.update_one(
        "datasync_backfill_jobs",
        {"dedupe_key": dedupe_key},
        {
            "$setOnInsert": {
                "job_id": job_id,
                "dedupe_key": dedupe_key,
                "dataset": job_name,
                "target_trade_date": normalized_trade_date,
                "start_date": None,
                "end_date": None,
                "status": "pending",
                "priority": safe_priority,
                "attempts": 0,
                "last_error": None,
                "created_by": f"web:{user_id}",
                "payload": {
                    "source": "system_status_panel",
                    "requested_dataset": str(dataset or "").strip(),
                    "recoverability": _json_safe(recoverability),
                },
                "created_at": now,
            },
        },
        upsert=True,
    )
    row = await mongo_manager.find_one("datasync_backfill_jobs", {"dedupe_key": dedupe_key}) or {}
    summarized = _summarize_backfill_job(row)
    summarized["already_exists"] = bool(existing)
    summarized["recoverability"] = _json_safe(recoverability)
    return summarized


async def update_datasync_backfill_job_action(
    *,
    user_id: str,
    job_id: str,
    action: str,
) -> Dict[str, Any]:
    """人工管理补缺队列任务。

    只允许暂停待执行/失败任务、恢复暂停任务、重试失败任务；running/done 任务不在 Web 侧强制修改。
    """
    safe_job_id = str(job_id or "").strip()
    safe_action = str(action or "").strip().lower()
    if not safe_job_id:
        raise ValueError("补缺任务 ID 不能为空")
    if safe_action not in _BACKFILL_JOB_ACTIONS:
        raise ValueError("不支持的补缺任务操作")

    job = await mongo_manager.find_one("datasync_backfill_jobs", {"job_id": safe_job_id})
    if not job:
        raise ValueError("补缺任务不存在")

    current_status = str(job.get("status") or "unknown")
    update: Dict[str, Any]
    next_status: str
    if safe_action == "pause":
        if current_status not in {"pending", "failed"}:
            raise ValueError("只有待处理或失败的补缺任务可以暂停")
        next_status = "paused"
        update = {
            "$set": {
                "status": next_status,
                "locked_by": None,
                "last_manual_action": safe_action,
                "last_manual_action_by": user_id,
                "last_manual_action_at": datetime.now(UTC),
            }
        }
    elif safe_action == "resume":
        if current_status != "paused":
            raise ValueError("只有暂停中的补缺任务可以恢复")
        next_status = "pending"
        update = {
            "$set": {
                "status": next_status,
                "locked_by": None,
                "last_manual_action": safe_action,
                "last_manual_action_by": user_id,
                "last_manual_action_at": datetime.now(UTC),
            }
        }
    else:
        if current_status != "failed":
            raise ValueError("只有失败的补缺任务可以重试")
        next_status = "pending"
        update = {
            "$set": {
                "status": next_status,
                "attempts": 0,
                "locked_by": None,
                "finished_at": None,
                "last_error": None,
                "last_manual_action": safe_action,
                "last_manual_action_by": user_id,
                "last_manual_action_at": datetime.now(UTC),
            }
        }

    await mongo_manager.update_one("datasync_backfill_jobs", {"job_id": safe_job_id}, update)
    updated = await mongo_manager.find_one("datasync_backfill_jobs", {"job_id": safe_job_id}) or {}
    await _record_web_ops_event(
        event_type="backfill_queue_manual_action",
        severity="info",
        message=f"Backfill job {safe_job_id} manual action {safe_action}: {current_status} -> {next_status}",
        details={
            "job_id": safe_job_id,
            "dataset": job.get("dataset"),
            "target_trade_date": job.get("target_trade_date"),
            "action": safe_action,
            "previous_status": current_status,
            "next_status": next_status,
            "user_id": user_id,
        },
    )
    return _summarize_backfill_job(updated)


async def _record_web_ops_event(
    *,
    event_type: str,
    severity: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    now = datetime.now(UTC)
    try:
        await mongo_manager.insert_one(
            "ops_events",
            {
                "event_id": uuid.uuid4().hex,
                "event_type": event_type,
                "severity": severity,
                "message": message,
                "source": "web",
                "node_id": "web",
                "details": details or {},
                "created_at": now,
                "updated_at": now,
            },
        )
    except Exception:
        # 审计失败不能阻断队列操作；状态变更本身仍由 Mongo 原子更新保障。
        return


async def create_manual_gap_fill_task(user_id: str, lookback_days: int = 3) -> Dict[str, Any]:
    """创建最近交易日补漏同步任务。"""
    normalized_days = max(1, min(int(lookback_days or 3), 10))

    existing_task = await mongo_manager.find_one(
        "tasks",
        {
            "user_id": user_id,
            "task_type": _TASK_TYPE,
            "status": {"$in": ["pending", "queued", "running"]},
        },
        sort=[("created_at", -1)],
    )
    if existing_task:
        return existing_task

    now = datetime.now(UTC)
    task_id = uuid.uuid4().hex
    task_doc = {
        "task_id": task_id,
        "trace_id": uuid.uuid4().hex,
        "task_type": _TASK_TYPE,
        "status": "queued",
        "progress": 0,
        "current_step": "排队中",
        "message": f"已创建最近 {normalized_days} 个交易日的轻量补漏同步任务",
        "params": {
            "mode": "gap_fill_recent_days",
            "lookback_days": normalized_days,
        },
        "user_id": user_id,
        "node_id": "web",
        "ts_codes": [],
        "stock_names": [],
        "query": None,
        "started_at": None,
        "completed_at": None,
        "result": None,
        "error_message": None,
        "execution_time_ms": 0,
        "created_at": now,
    }
    await mongo_manager.insert_one("tasks", task_doc)

    runtime_task = asyncio.create_task(
        _run_manual_gap_fill_task(task_id=task_id, user_id=user_id, lookback_days=normalized_days)
    )
    _RUNTIME_TASKS.add(runtime_task)
    runtime_task.add_done_callback(_RUNTIME_TASKS.discard)
    return task_doc


async def get_manual_gap_fill_task(user_id: str, task_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """查询手动补漏同步任务状态。"""
    query: Dict[str, Any] = {
        "user_id": user_id,
        "task_type": _TASK_TYPE,
    }
    if task_id:
        query["task_id"] = task_id
        return await mongo_manager.find_one("tasks", query)
    return await mongo_manager.find_one("tasks", query, sort=[("created_at", -1)])


async def _run_manual_gap_fill_task(task_id: str, user_id: str, lookback_days: int) -> None:
    started_at = datetime.now(UTC)
    initialized_managers: List[Any] = []
    step_errors: List[Dict[str, str]] = []
    completed_dates: List[str] = []

    async def step(progress: int, current_step: str, message: Optional[str] = None) -> None:
        payload: Dict[str, Any] = {
            "status": "running",
            "progress": progress,
            "current_step": current_step,
            "started_at": started_at,
        }
        if message is not None:
            payload["message"] = message
        await _update_manual_gap_fill_task(task_id, **payload)

    try:
        await step(5, "初始化依赖", "正在准备数据源与分析管理器")
        initialized_managers = await _initialize_optional_managers()

        trade_dates = await _get_recent_trade_dates(lookback_days)
        await step(12, "检查缺口", f"正在检查最近 {len(trade_dates)} 个交易日的数据完整性")

        if not trade_dates:
            await _finalize_manual_gap_fill_task(
                task_id,
                status="completed",
                started_at=started_at,
                message="最近交易日列表为空，无需补漏",
                result={
                    "lookback_days": lookback_days,
                    "checked_dates": [],
                    "pending_dates": [],
                    "completed_dates": [],
                    "step_errors": [],
                },
            )
            return

        active_stock_count = await mongo_manager.count("stock_basic", {"list_status": "L"})
        gap_plans = []
        for trade_date in trade_dates:
            plan = await _inspect_gap_for_trade_date(trade_date, active_stock_count)
            if plan["required_steps"]:
                gap_plans.append(plan)

        if not gap_plans:
            await _finalize_manual_gap_fill_task(
                task_id,
                status="completed",
                started_at=started_at,
                message=f"最近 {len(trade_dates)} 个交易日未发现明显缺口",
                result={
                    "lookback_days": lookback_days,
                    "checked_dates": trade_dates,
                    "pending_dates": [],
                    "completed_dates": [],
                    "step_errors": [],
                },
            )
            return

        total_dates = len(gap_plans)
        for index, plan in enumerate(gap_plans, start=1):
            trade_date = plan["trade_date"]
            required_steps = plan["required_steps"]
            base_progress = 15 + int(((index - 1) / max(total_dates, 1)) * 70)
            await step(
                base_progress,
                f"补最近交易日 ({index}/{total_dates})",
                f"{trade_date} 待补步骤：{' / '.join(required_steps)}",
            )

            date_errors = await _sync_trade_date_gap(trade_date, plan)
            if date_errors:
                step_errors.extend(date_errors)
            else:
                completed_dates.append(trade_date)

        has_partial_errors = bool(step_errors)
        summary_message = (
            f"补漏完成，成功处理 {len(completed_dates)} 个交易日"
            if not has_partial_errors
            else f"补漏完成，但仍有 {len(step_errors)} 个步骤失败"
        )
        await _finalize_manual_gap_fill_task(
            task_id,
            status="completed",
            started_at=started_at,
            message=summary_message,
            result={
                "lookback_days": lookback_days,
                "checked_dates": trade_dates,
                "pending_dates": [plan["trade_date"] for plan in gap_plans],
                "completed_dates": completed_dates,
                "step_errors": step_errors,
                "plans": [
                    {
                        "trade_date": plan["trade_date"],
                        "required_steps": plan["required_steps"],
                    }
                    for plan in gap_plans
                ],
            },
        )
    except Exception as exc:
        await _finalize_manual_gap_fill_task(
            task_id,
            status="failed",
            started_at=started_at,
            message="补漏同步失败",
            error_message=str(exc),
            result={
                "lookback_days": lookback_days,
                "completed_dates": completed_dates,
                "step_errors": step_errors,
            },
        )
    finally:
        await _shutdown_optional_managers(initialized_managers)


async def _initialize_optional_managers() -> List[Any]:
    initialized_managers: List[Any] = []
    for manager in (data_source_manager, analysis_manager, stock_relation_manager):
        if getattr(manager, "_initialized", False):
            continue
        await manager.initialize()
        initialized_managers.append(manager)
    return initialized_managers


async def _shutdown_optional_managers(managers: List[Any]) -> None:
    for manager in reversed(managers):
        try:
            await manager.shutdown()
        except Exception:
            continue


async def _update_manual_gap_fill_task(task_id: str, **fields: Any) -> None:
    await mongo_manager.update_one("tasks", {"task_id": task_id}, {"$set": fields})


async def _finalize_manual_gap_fill_task(
    task_id: str,
    status: str,
    started_at: datetime,
    message: str,
    result: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
) -> None:
    completed_at = datetime.now(UTC)
    execution_time_ms = int((completed_at - started_at).total_seconds() * 1000)
    payload: Dict[str, Any] = {
        "status": status,
        "progress": 100,
        "current_step": "完成" if status == "completed" else "失败",
        "message": message,
        "completed_at": completed_at,
        "execution_time_ms": execution_time_ms,
        "result": result,
        "error_message": error_message,
    }
    await _update_manual_gap_fill_task(task_id, **payload)


async def _get_recent_trade_dates(days: int) -> List[str]:
    latest_trade_date, _ = await data_source_manager.get_latest_trade_date()
    if not latest_trade_date:
        return []

    latest_dt = datetime.strptime(latest_trade_date, "%Y%m%d")
    start_date = (latest_dt - timedelta(days=max(days, 1) * 3)).strftime("%Y%m%d")
    trade_dates, _ = await data_source_manager.get_trade_calendar(start_date, latest_trade_date)
    if not trade_dates:
        return []
    sorted_dates = sorted(trade_dates)
    return sorted_dates[-days:]


async def _inspect_gap_for_trade_date(trade_date: str, active_stock_count: int) -> Dict[str, Any]:
    stock_threshold = max(int(active_stock_count * 0.7), 1000) if active_stock_count else 1000
    basic_threshold = max(int(active_stock_count * 0.6), 1000) if active_stock_count else 1000

    stock_daily_count = await mongo_manager.count("stock_daily", {"trade_date": trade_date})
    daily_basic_count = await mongo_manager.count("daily_basic", {"trade_date": trade_date})
    index_daily_count = await mongo_manager.count(
        "index_daily",
        {"trade_date": trade_date, "ts_code": {"$in": list(_CORE_INDEX_CODES)}},
    )
    limit_list_count = await mongo_manager.count("limit_list", {"trade_date": trade_date})
    daily_stats_count = await mongo_manager.count("daily_stats", {"trade_date": trade_date})
    market_analysis_count = await mongo_manager.count("market_analysis", {"trade_date": trade_date})
    relation_count = await mongo_manager.count(
        "stock_relations",
        {"source": "limit_list", "source_trade_date": trade_date},
    )

    required_steps: List[str] = []
    if stock_daily_count < stock_threshold:
        required_steps.append("stock_daily")
    if daily_basic_count < basic_threshold:
        required_steps.append("daily_basic")
    if index_daily_count < len(_CORE_INDEX_CODES):
        required_steps.append("index_daily")
    if limit_list_count <= 0:
        required_steps.append("limit_list")
    if daily_stats_count <= 0:
        required_steps.append("daily_stats")
    if market_analysis_count <= 0:
        required_steps.append("market_analysis")
    if limit_list_count > 0 and relation_count <= 0:
        required_steps.append("stock_relations")

    return {
        "trade_date": trade_date,
        "required_steps": required_steps,
        "counts": {
            "stock_daily": stock_daily_count,
            "daily_basic": daily_basic_count,
            "index_daily": index_daily_count,
            "limit_list": limit_list_count,
            "daily_stats": daily_stats_count,
            "market_analysis": market_analysis_count,
            "stock_relations": relation_count,
        },
    }


async def _sync_trade_date_gap(trade_date: str, plan: Dict[str, Any]) -> List[Dict[str, str]]:
    required_steps = plan["required_steps"]
    errors: List[Dict[str, str]] = []
    failed_steps: set[str] = set()

    async def run_step(step_name: str, coro: Any) -> None:
        try:
            result = await coro
            if step_name in {"stock_daily", "index_daily", "limit_list"}:
                count = int(result.get("count", 0) or 0)
                if count > 0:
                    await mongo_manager.record_sync(step_name, trade_date, count=count)
            elif step_name == "daily_basic":
                count = int(result.get("count", 0) or 0)
                if count > 0:
                    await mongo_manager.record_sync("daily_basic", trade_date, count=count)
            elif step_name == "daily_stats":
                await mongo_manager.record_sync("daily_stats", trade_date, count=1)
            elif step_name == "market_analysis":
                await mongo_manager.record_sync("market_analysis", trade_date, count=1)
            elif step_name == "stock_relations":
                count = int(result.get("dynamic_docs", 0) or 0) + int(result.get("static_docs", 0) or 0)
                if count > 0:
                    await mongo_manager.record_sync("stock_relations", trade_date, count=count)
        except Exception as exc:
            failed_steps.add(step_name)
            errors.append(
                {
                    "trade_date": trade_date,
                    "step": step_name,
                    "error": str(exc),
                }
            )

    if "stock_daily" in required_steps:
        await run_step("stock_daily", sync_stock_daily_for_date(trade_date))
    if "daily_basic" in required_steps:
        await run_step("daily_basic", _sync_daily_basic_for_date(trade_date))
    if "index_daily" in required_steps:
        await run_step("index_daily", sync_index_daily_for_date(trade_date))
    if "limit_list" in required_steps:
        await run_step("limit_list", sync_limit_list_for_date(trade_date))
    if "daily_stats" in required_steps and not (failed_steps & {"stock_daily", "index_daily", "limit_list"}):
        await run_step("daily_stats", _recalc_daily_stats_for_date(trade_date))
    elif "daily_stats" in required_steps:
        errors.append(
            {
                "trade_date": trade_date,
                "step": "daily_stats",
                "error": "前置数据同步失败，已跳过 daily_stats 重算",
            }
        )
        failed_steps.add("daily_stats")
    if "market_analysis" in required_steps and "daily_stats" not in failed_steps:
        await run_step("market_analysis", _recalc_market_analysis_for_date(trade_date))
    elif "market_analysis" in required_steps:
        errors.append(
            {
                "trade_date": trade_date,
                "step": "market_analysis",
                "error": "daily_stats 重算未完成，已跳过 market_analysis 重算",
            }
        )
        failed_steps.add("market_analysis")
    if (("stock_relations" in required_steps) or ("limit_list" in required_steps)) and "limit_list" not in failed_steps:
        await run_step("stock_relations", stock_relation_manager.sync_relations(snapshot_trade_date=trade_date))
    elif ("stock_relations" in required_steps) or ("limit_list" in required_steps):
        errors.append(
            {
                "trade_date": trade_date,
                "step": "stock_relations",
                "error": "limit_list 同步未完成，已跳过股票关系快照同步",
            }
        )

    return errors


async def _sync_daily_basic_for_date(trade_date: str) -> Dict[str, Any]:
    records, source = await data_source_manager.get_daily_basic(
        trade_date=trade_date,
        preferred_source="tushare",
    )
    if not records:
        return {"date": trade_date, "count": 0, "source": source}

    cleaned_records: List[Dict[str, Any]] = []
    now = datetime.now(UTC)
    for record in records:
        cleaned = _clean_daily_basic_record(record)
        if not cleaned.get("trade_date") or not cleaned.get("ts_code"):
            continue
        cleaned["updated_at"] = now
        cleaned_records.append(cleaned)

    if not cleaned_records:
        return {"date": trade_date, "count": 0, "source": source}

    result = await mongo_manager.bulk_upsert(
        collection="daily_basic",
        documents=cleaned_records,
        key_fields=["ts_code", "trade_date"],
        batch_size=5000,
    )
    count = result.get("upserted", 0) + result.get("modified", 0)
    return {"date": trade_date, "count": count, "source": source}


async def _recalc_daily_stats_for_date(trade_date: str) -> Dict[str, Any]:
    from scripts.recalc_daily_stats import compute_daily_stats_for_date

    stats = await compute_daily_stats_for_date(trade_date)
    stats["updated_at"] = datetime.utcnow()
    await mongo_manager.update_one(
        "daily_stats",
        {"trade_date": trade_date},
        {"$set": stats},
        upsert=True,
    )
    return {"trade_date": trade_date, "count": 1}


async def _recalc_market_analysis_for_date(trade_date: str) -> Dict[str, Any]:
    stats = await mongo_manager.find_one("daily_stats", {"trade_date": trade_date})
    if not stats:
        raise ValueError(f"{trade_date} 缺少 daily_stats，无法重算 market_analysis")

    prev_stats = await mongo_manager.find_one(
        "daily_stats",
        {"trade_date": {"$lt": trade_date}},
        sort=[("trade_date", -1)],
    )
    await analysis_manager.analyze_and_store(
        stats=stats,
        prev_stats=prev_stats,
        mongo_manager=mongo_manager,
    )
    return {"trade_date": trade_date, "count": 1}
