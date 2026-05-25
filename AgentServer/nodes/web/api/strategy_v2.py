"""Strategy V2 API skeleton."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional
import re

from fastapi import APIRouter, Body, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from common.models.strategy_v2 import (
    StrategyV2CreateTaskRequest,
    StrategyV2RuleDictionary,
    StrategyV2SceneTaskResponse,
    StrategyV2TaskStatus,
)
from core.managers import mongo_manager, notification_manager
from core.protocols import StrategyAlert
from src.strategy_v2.rules import (
    BUILTIN_STRATEGY_DEFINITIONS,
    build_rule_dictionary,
    get_strategy_definition,
    validate_task_config,
)
from src.strategy_v2.evaluator import (
    StrategyV2EvaluationContext,
    evaluate_strategy_v2,
)

from .auth import get_current_user_id


router = APIRouter(prefix="/strategy-v2", tags=["Strategy V2"])
logger = logging.getLogger("api.strategy_v2")

TASK_COLLECTION = "strategy_v2_scene_tasks"
RUN_COLLECTION = "strategy_v2_task_runs"
RUN_ITEM_COLLECTION = "strategy_v2_task_run_items"
RUN_LOG_COLLECTION = "strategy_v2_task_run_logs"
ACTION_AUDIT_COLLECTION = "strategy_v2_action_audits"
STOCK_POOL_COLLECTION = "stock_pools"
RUN_STALE_AFTER_SECONDS = 30 * 60
ACTIVE_RUN_STATUSES = {"running"}
SCHEDULER_POLL_SECONDS = 30
SCHEDULE_SLOT_GRACE_SECONDS = 10 * 60
MAX_TASK_LIST_ITEMS = 500
MAX_RUN_RESULT_ITEMS = 6000
MAX_TARGET_STOCKS = 6000
MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")
SCHEDULE_SLOT_TIMES = {
    "pre_market_0900": (9, 0),
    "call_auction_0925": (9, 25),
    "morning_turn_1000": (10, 0),
    "midday_close_1130": (11, 30),
    "afternoon_turn_1400": (14, 0),
    "post_market_1505": (15, 5),
    "weekly_sat_1200": (12, 0),
}
SCHEDULE_SLOT_INTERVALS = {
    "intraday_1m": 60,
    "intraday_5m": 5 * 60,
    "intraday_30m": 30 * 60,
}
_SCHEDULER_TASK: Optional[asyncio.Task] = None
try:
    _MAX_CONCURRENT_RUNS = max(1, int(os.environ.get("STRATEGY_V2_MAX_CONCURRENT_RUNS", "1")))
except ValueError:
    _MAX_CONCURRENT_RUNS = 1
_RUN_SEMAPHORE = asyncio.Semaphore(_MAX_CONCURRENT_RUNS)


class StrategyV2RunCancelled(Exception):
    """Raised inside the cooperative runner when a run is cancelled by user."""


class StrategyV2RunRequest(BaseModel):
    trigger_source: str = Field(default="manual", pattern=r"^(manual|schedule|retry)$")
    parent_run_id: Optional[str] = None


class StrategyV2TaskStockRequest(BaseModel):
    ts_code: str = Field(..., pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    config: Optional[Dict[str, Any]] = None


class StrategyV2StockConfigRequest(BaseModel):
    config: Dict[str, Any] = Field(default_factory=dict)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc_datetime(value: Any) -> Optional[datetime]:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_weekday(value: datetime) -> bool:
    return value.weekday() < 5


def _is_intraday_session(value: datetime) -> bool:
    minutes = value.hour * 60 + value.minute
    return (9 * 60 + 15 <= minutes <= 11 * 60 + 30) or (13 * 60 <= minutes <= 15 * 60 + 5)


@router.get("/rules", response_model=StrategyV2RuleDictionary)
async def get_strategy_v2_rules() -> StrategyV2RuleDictionary:
    """Return the frontend/backend shared creation rules."""
    return build_rule_dictionary()


@router.get("/strategies")
async def list_strategy_v2_definitions() -> Dict[str, Any]:
    """Return built-in strategy definitions known by the V2 skeleton."""
    return {"items": BUILTIN_STRATEGY_DEFINITIONS}


@router.get("/tasks")
async def list_strategy_v2_tasks(user_id: str = Depends(get_current_user_id)) -> Dict[str, List[Dict[str, Any]]]:
    await _mark_stale_running_runs(user_id=user_id)
    items = await mongo_manager.find_many(
        TASK_COLLECTION,
        {"user_id": user_id},
        sort=[("updated_at", -1)],
        projection={"_id": 0},
        limit=MAX_TASK_LIST_ITEMS,
    )
    return {"items": items}


@router.get("/tasks/{task_id}", response_model=StrategyV2SceneTaskResponse)
async def get_strategy_v2_task(
    task_id: str,
    user_id: str = Depends(get_current_user_id),
) -> StrategyV2SceneTaskResponse:
    task = await mongo_manager.find_one(
        TASK_COLLECTION,
        {"task_id": task_id, "user_id": user_id},
        projection={"_id": 0},
    )
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return StrategyV2SceneTaskResponse(**task)


@router.delete("/tasks/{task_id}")
async def delete_strategy_v2_task(
    task_id: str,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    task = await _get_user_task_or_404(task_id, user_id)
    await _mark_stale_running_runs(user_id=user_id, task_id=task_id)
    running_run = await mongo_manager.find_one(
        RUN_COLLECTION,
        {"task_id": task_id, "user_id": user_id, "run_status": "running"},
        projection={"_id": 0, "run_id": 1},
    )
    if running_run or task.get("active_run_id"):
        raise HTTPException(status_code=409, detail="任务正在运行，请先取消或等待完成后再删除")

    await mongo_manager.delete_one(TASK_COLLECTION, {"task_id": task_id, "user_id": user_id})
    deleted_runs = await mongo_manager.delete_many(RUN_COLLECTION, {"task_id": task_id, "user_id": user_id})
    deleted_items = await mongo_manager.delete_many(RUN_ITEM_COLLECTION, {"task_id": task_id, "user_id": user_id})
    deleted_logs = await mongo_manager.delete_many(RUN_LOG_COLLECTION, {"task_id": task_id, "user_id": user_id})
    deleted_audits = await mongo_manager.delete_many(ACTION_AUDIT_COLLECTION, {"task_id": task_id, "user_id": user_id})
    return {
        "message": f"已删除任务「{task.get('name') or task_id}」",
        "task_id": task_id,
        "deleted_runs": deleted_runs,
        "deleted_items": deleted_items,
        "deleted_logs": deleted_logs,
        "deleted_audits": deleted_audits,
    }


@router.get("/tasks/{task_id}/runs")
async def list_strategy_v2_task_runs(
    task_id: str,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, List[Dict[str, Any]]]:
    await _get_user_task_or_404(task_id, user_id)
    await _mark_stale_running_runs(user_id=user_id, task_id=task_id)
    items = await mongo_manager.find_many(
        RUN_COLLECTION,
        {"task_id": task_id, "user_id": user_id},
        projection={"_id": 0},
        sort=[("started_at", -1)],
        limit=30,
    )
    return {"items": items}


@router.get("/runs/{run_id}")
async def get_strategy_v2_run(
    run_id: str,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    await _mark_stale_running_runs(user_id=user_id, run_id=run_id)
    run = await mongo_manager.find_one(
        RUN_COLLECTION,
        {"run_id": run_id, "user_id": user_id},
        projection={"_id": 0},
    )
    if not run:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return run


@router.get("/runs/{run_id}/items")
async def list_strategy_v2_run_items(
    run_id: str,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, List[Dict[str, Any]]]:
    run = await mongo_manager.find_one(
        RUN_COLLECTION,
        {"run_id": run_id, "user_id": user_id},
        projection={"_id": 0, "run_id": 1},
    )
    if not run:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    items = await mongo_manager.find_many(
        RUN_ITEM_COLLECTION,
        {"run_id": run_id, "user_id": user_id},
        projection={"_id": 0},
        sort=[("signal", -1), ("score", -1), ("entity_key", 1)],
        limit=MAX_RUN_RESULT_ITEMS,
    )
    return {"items": items}


@router.get("/runs/{run_id}/logs")
async def list_strategy_v2_run_logs(
    run_id: str,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, List[Dict[str, Any]]]:
    await _get_user_run_or_404(run_id, user_id, projection={"_id": 0, "run_id": 1})
    items = await mongo_manager.find_many(
        RUN_LOG_COLLECTION,
        {"run_id": run_id, "user_id": user_id},
        projection={"_id": 0},
        sort=[("created_at", 1)],
        limit=200,
    )
    return {"items": items}


@router.get("/runs/{run_id}/action-audits")
async def list_strategy_v2_run_action_audits(
    run_id: str,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, List[Dict[str, Any]]]:
    await _get_user_run_or_404(run_id, user_id, projection={"_id": 0, "run_id": 1})
    items = await mongo_manager.find_many(
        ACTION_AUDIT_COLLECTION,
        {"run_id": run_id, "user_id": user_id},
        projection={"_id": 0},
        sort=[("created_at", 1), ("entity_key", 1)],
        limit=500,
    )
    return {"items": items}


@router.post("/tasks/{task_id}/runs")
async def run_strategy_v2_task(
    task_id: str,
    body: Optional[StrategyV2RunRequest] = Body(default=None),
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    task = await _get_user_task_or_404(task_id, user_id)
    await _mark_stale_running_runs(user_id=user_id, task_id=task_id)
    request = body or StrategyV2RunRequest()
    return await _start_strategy_v2_run(
        task,
        user_id,
        trigger_source=request.trigger_source,
        parent_run_id=request.parent_run_id,
    )


@router.post("/runs/{run_id}/cancel")
async def cancel_strategy_v2_run(
    run_id: str,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    run = await mongo_manager.find_one(
        RUN_COLLECTION,
        {"run_id": run_id, "user_id": user_id},
        projection={"_id": 0},
    )
    if not run:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    if run.get("run_status") != "running":
        return run

    finished_at = _utc_now()
    await mongo_manager.update_one(
        RUN_COLLECTION,
        {"run_id": run_id, "user_id": user_id, "run_status": "running"},
        {
            "$set": {
                "run_status": "cancelled",
                "summary": "运行已取消：用户手动停止了本次任务。",
                "finished_at": finished_at,
                "cancel_requested_at": finished_at,
                "progress_label": "已取消",
                "summary_metrics": [
                    {"label": "状态", "value": "已取消", "tone": "warning"},
                    {"label": "已扫描", "value": f"{int(run.get('progress_current') or 0)}/{int(run.get('progress_total') or 0)}"},
                ],
                "next_action_hint": "如需重新执行，可在本页或任务详情页点击重试。",
                "updated_at": finished_at,
            }
        },
    )
    await _release_task_run_lock(str(run.get("task_id") or ""), user_id, run_id, "cancelled", finished_at)
    if run.get("task_id"):
        await _append_run_log(
            run_id,
            str(run.get("task_id")),
            user_id,
            level="warning",
            stage="cancel",
            message="用户请求取消运行",
            meta={"cancel_requested_at": finished_at.isoformat()},
        )
    updated = await mongo_manager.find_one(
        RUN_COLLECTION,
        {"run_id": run_id, "user_id": user_id},
        projection={"_id": 0},
    )
    return updated or run


@router.post("/runs/{run_id}/retry")
async def retry_strategy_v2_run(
    run_id: str,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    run = await mongo_manager.find_one(
        RUN_COLLECTION,
        {"run_id": run_id, "user_id": user_id},
        projection={"_id": 0},
    )
    if not run:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    if run.get("run_status") == "running":
        raise HTTPException(status_code=409, detail="当前运行仍在执行，不能重试")
    task = await _get_user_task_or_404(str(run.get("task_id") or ""), user_id)
    await _mark_stale_running_runs(user_id=user_id, task_id=task["task_id"])
    return await _start_strategy_v2_run(
        task,
        user_id,
        trigger_source="retry",
        parent_run_id=run_id,
    )


async def _get_user_task_or_404(task_id: str, user_id: str) -> Dict[str, Any]:
    task = await mongo_manager.find_one(
        TASK_COLLECTION,
        {"task_id": task_id, "user_id": user_id},
        projection={"_id": 0},
    )
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


async def _get_user_run_or_404(
    run_id: str,
    user_id: str,
    projection: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    run = await mongo_manager.find_one(
        RUN_COLLECTION,
        {"run_id": run_id, "user_id": user_id},
        projection=projection or {"_id": 0},
    )
    if not run:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return run


async def _start_strategy_v2_run(
    task: Dict[str, Any],
    user_id: str,
    *,
    trigger_source: str,
    parent_run_id: Optional[str] = None,
) -> Dict[str, Any]:
    task_id = str(task.get("task_id") or "")
    if not task_id:
        raise HTTPException(status_code=400, detail="任务缺少 task_id")

    active_run = await mongo_manager.find_one(
        RUN_COLLECTION,
        {"task_id": task_id, "user_id": user_id, "run_status": {"$in": list(ACTIVE_RUN_STATUSES)}},
        projection={"_id": 0, "run_id": 1},
        sort=[("started_at", -1)],
    )
    if active_run:
        raise HTTPException(status_code=409, detail=f"任务已有运行中的记录：{active_run['run_id']}")

    run_id = f"sv2_run_{uuid.uuid4().hex[:12]}"
    now = _utc_now()
    run_doc = _build_running_doc(
        task,
        run_id,
        now,
        trigger_source=trigger_source,
        parent_run_id=parent_run_id,
    )

    acquired = await mongo_manager.update_one(
        TASK_COLLECTION,
        {
            "task_id": task_id,
            "user_id": user_id,
            "$or": [
                {"active_run_id": {"$exists": False}},
                {"active_run_id": None},
                {"active_run_id": ""},
            ],
        },
        {
            "$set": {
                "active_run_id": run_id,
                "last_run_id": run_id,
                "last_run_status": "running",
                "updated_at": now,
            }
        },
    )
    if acquired <= 0:
        latest = await mongo_manager.find_one(
            TASK_COLLECTION,
            {"task_id": task_id, "user_id": user_id},
            projection={"_id": 0, "active_run_id": 1},
        )
        raise HTTPException(status_code=409, detail=f"任务正在运行：{(latest or {}).get('active_run_id') or '未知运行'}")

    try:
        await mongo_manager.insert_one(RUN_COLLECTION, run_doc)
    except Exception:
        await _release_task_run_lock(task_id, user_id, run_id, "failed", now)
        raise

    asyncio.create_task(_execute_strategy_v2_run(run_id, user_id))
    return run_doc


async def start_strategy_v2_scheduler() -> None:
    global _SCHEDULER_TASK
    if _SCHEDULER_TASK and not _SCHEDULER_TASK.done():
        return
    _SCHEDULER_TASK = asyncio.create_task(_strategy_v2_scheduler_loop())


async def stop_strategy_v2_scheduler() -> None:
    global _SCHEDULER_TASK
    if not _SCHEDULER_TASK:
        return
    _SCHEDULER_TASK.cancel()
    try:
        await _SCHEDULER_TASK
    except asyncio.CancelledError:
        pass
    _SCHEDULER_TASK = None


async def _strategy_v2_scheduler_loop() -> None:
    while True:
        try:
            await _scan_due_strategy_v2_tasks()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Keep the lightweight scheduler alive; individual failures are
            # reflected on task/run records when a run is actually created.
            logger.warning("Strategy V2 scheduler tick failed: %s", exc)
        await asyncio.sleep(SCHEDULER_POLL_SECONDS)


async def _scan_due_strategy_v2_tasks() -> None:
    now = _utc_now()
    local_now = now.astimezone(MARKET_TIMEZONE)
    await _mark_stale_running_runs()
    tasks = await mongo_manager.find_many(
        TASK_COLLECTION,
        {
            "status": StrategyV2TaskStatus.ACTIVE.value,
            "schedule.mode": "scheduled",
        },
        projection={"_id": 0},
        sort=[("updated_at", 1)],
        limit=100,
    )

    for task in tasks:
        due = _resolve_schedule_due(task, local_now, now)
        if not due:
            continue
        fire_key = due["fire_key"]
        claimed = await mongo_manager.update_one(
            TASK_COLLECTION,
            {
                "task_id": task.get("task_id"),
                "user_id": task.get("user_id"),
                "schedule.mode": "scheduled",
                "status": StrategyV2TaskStatus.ACTIVE.value,
                "last_scheduled_fire_key": {"$ne": fire_key},
                "$or": [
                    {"active_run_id": {"$exists": False}},
                    {"active_run_id": None},
                    {"active_run_id": ""},
                ],
            },
            {
                "$set": {
                    "last_scheduled_fire_key": fire_key,
                    "last_scheduled_run_at": now,
                    "last_scheduled_label": due["label"],
                    "updated_at": now,
                }
            },
        )
        if claimed <= 0:
            continue

        fresh_task = await _get_user_task_or_404(str(task.get("task_id") or ""), str(task.get("user_id") or ""))
        try:
            await _start_strategy_v2_run(
                fresh_task,
                str(fresh_task.get("user_id") or ""),
                trigger_source="schedule",
                parent_run_id=None,
            )
        except HTTPException:
            continue


def _resolve_schedule_due(
    task: Dict[str, Any],
    local_now: datetime,
    utc_now: datetime,
) -> Optional[Dict[str, str]]:
    schedule = task.get("schedule") or {}
    if schedule.get("mode") != "scheduled":
        return None
    if schedule.get("trading_day_only") and not _is_weekday(local_now):
        return None

    slot = str(schedule.get("slot") or "")
    interval_seconds = _schedule_interval_seconds(schedule)
    if interval_seconds:
        if slot.startswith("intraday") and (not _is_weekday(local_now) or not _is_intraday_session(local_now)):
            return None
        last_run_at = _as_utc_datetime(task.get("last_scheduled_run_at"))
        if last_run_at and (utc_now - last_run_at).total_seconds() < interval_seconds:
            return None
        bucket = int(utc_now.timestamp() // interval_seconds)
        return {
            "fire_key": f"{task.get('task_id')}:{slot or 'interval'}:{bucket}",
            "label": schedule.get("label") or slot or f"{interval_seconds}s",
        }

    slot_time = SCHEDULE_SLOT_TIMES.get(slot)
    if not slot_time:
        return None
    if slot == "weekly_sat_1200":
        if local_now.weekday() != 5:
            return None
    elif not _is_weekday(local_now):
        return None

    scheduled_at = local_now.replace(
        hour=slot_time[0],
        minute=slot_time[1],
        second=0,
        microsecond=0,
    )
    delta = (local_now - scheduled_at).total_seconds()
    if delta < 0 or delta > SCHEDULE_SLOT_GRACE_SECONDS:
        return None
    return {
        "fire_key": f"{task.get('task_id')}:{slot}:{scheduled_at.strftime('%Y%m%d%H%M')}",
        "label": schedule.get("label") or slot,
    }


def _schedule_interval_seconds(schedule: Dict[str, Any]) -> int:
    raw_interval = schedule.get("interval_seconds")
    try:
        interval = int(raw_interval or 0)
    except (TypeError, ValueError):
        interval = 0
    if interval > 0:
        return max(interval, SCHEDULER_POLL_SECONDS)
    slot = str(schedule.get("slot") or "")
    return SCHEDULE_SLOT_INTERVALS.get(slot, 0)


async def _mark_stale_running_runs(
    *,
    user_id: Optional[str] = None,
    task_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> None:
    query: Dict[str, Any] = {"run_status": "running"}
    if user_id:
        query["user_id"] = user_id
    if task_id:
        query["task_id"] = task_id
    if run_id:
        query["run_id"] = run_id

    running_runs = await mongo_manager.find_many(
        RUN_COLLECTION,
        query,
        projection={"_id": 0, "run_id": 1, "task_id": 1, "user_id": 1, "started_at": 1, "progress_current": 1, "progress_total": 1},
        sort=[("started_at", 1)],
        limit=200,
    )
    now = _utc_now()
    for run in running_runs:
        run_user_id = str(run.get("user_id") or user_id or "")
        if not run_user_id:
            continue
        started_at = _as_utc_datetime(run.get("started_at"))
        if not started_at or (now - started_at).total_seconds() < RUN_STALE_AFTER_SECONDS:
            continue

        finished_at = _utc_now()
        progress_current = int(run.get("progress_current") or 0)
        progress_total = int(run.get("progress_total") or 0)
        summary = "运行超时：后台任务长时间未更新，可能由服务重启或后台任务中断导致。"
        await mongo_manager.update_one(
            RUN_COLLECTION,
            {"run_id": run.get("run_id"), "user_id": run_user_id},
            {
                "$set": {
                    "run_status": "failed",
                    "summary": summary,
                    "finished_at": finished_at,
                    "progress_label": "运行超时",
                    "summary_metrics": [
                        {"label": "状态", "value": "超时失败", "tone": "negative"},
                        {"label": "已扫描", "value": f"{progress_current}/{progress_total}"},
                    ],
                    "next_action_hint": "这通常表示 Web 服务重启或后台执行被中断，建议重新运行任务。",
                    "updated_at": finished_at,
                }
            },
        )

        await _release_task_run_lock(
            str(run.get("task_id") or ""),
            run_user_id,
            str(run.get("run_id") or ""),
            "failed",
            finished_at,
        )


async def _release_task_run_lock(
    task_id: str,
    user_id: str,
    run_id: str,
    final_status: str,
    finished_at: datetime,
    *,
    signal_count: Optional[int] = None,
) -> None:
    if not task_id:
        return
    set_doc: Dict[str, Any] = {
        "last_run_id": run_id,
        "last_run_status": final_status,
        "active_run_id": None,
        "updated_at": finished_at,
    }
    if signal_count is not None:
        set_doc["last_signal_count"] = signal_count
    modified = await mongo_manager.update_one(
        TASK_COLLECTION,
        {"task_id": task_id, "user_id": user_id, "active_run_id": run_id},
        {"$set": set_doc},
    )
    if modified > 0:
        return

    # Older runs may not have acquired active_run_id. Keep recovery safe by
    # only updating the task when this run is still the latest known run and
    # no newer active run has taken the lock.
    await mongo_manager.update_one(
        TASK_COLLECTION,
        {
            "task_id": task_id,
            "user_id": user_id,
            "last_run_id": run_id,
            "$or": [
                {"active_run_id": {"$exists": False}},
                {"active_run_id": None},
                {"active_run_id": ""},
                {"active_run_id": run_id},
            ],
        },
        {"$set": set_doc},
    )


async def _is_run_cancelled(run_id: str, user_id: str) -> bool:
    run = await mongo_manager.find_one(
        RUN_COLLECTION,
        {"run_id": run_id, "user_id": user_id},
        projection={"_id": 0, "run_status": 1},
    )
    return not run or run.get("run_status") == "cancelled"


async def _ensure_run_can_continue(run_id: str, user_id: str) -> None:
    if await _is_run_cancelled(run_id, user_id):
        raise StrategyV2RunCancelled()


def _build_running_doc(
    task: Dict[str, Any],
    run_id: str,
    now: datetime,
    *,
    trigger_source: str = "manual",
    parent_run_id: Optional[str] = None,
) -> Dict[str, Any]:
    trigger_labels = {
        "manual": "手动运行",
        "schedule": "定时运行",
        "retry": "重试运行",
    }
    return {
        "run_id": run_id,
        "task_id": task.get("task_id"),
        "user_id": task.get("user_id"),
        "scene_type": task.get("scene_type"),
        "strategy_key": task.get("strategy_key"),
        "strategy_name": task.get("strategy_name"),
        "trigger_source": trigger_source,
        "parent_run_id": parent_run_id,
        "run_status": "running",
        "title": f"{task.get('name') or 'V2 任务'} · {trigger_labels.get(trigger_source, trigger_source)}",
        "summary": "任务已进入运行队列，正在生成结果。",
        "started_at": now,
        "finished_at": None,
        "progress_current": 0,
        "progress_total": 0,
        "progress_pct": 0,
        "progress_label": "等待解析目标范围",
        "signal_breakdown": {"positive": 0, "neutral": 0, "negative": 0},
        "summary_metrics": [
            {"label": "状态", "value": "运行中", "tone": "warning"},
        ],
        "related_pool_id": None,
        "related_pool_name": None,
        "next_action_hint": "运行完成后可在本页查看命中股票和临时清单入口。",
        "created_at": now,
        "updated_at": now,
    }


async def _update_run_progress(
    run_id: str,
    user_id: str,
    *,
    current: int,
    total: int,
    label: str,
) -> None:
    progress_pct = round((current / total * 100) if total else 0, 2)
    await mongo_manager.update_one(
        RUN_COLLECTION,
        {"run_id": run_id, "user_id": user_id, "run_status": "running"},
        {
            "$set": {
                "progress_current": current,
                "progress_total": total,
                "progress_pct": progress_pct,
                "progress_label": label,
                "updated_at": _utc_now(),
            }
        },
    )


async def _append_run_log(
    run_id: str,
    task_id: str,
    user_id: str,
    *,
    level: str,
    stage: str,
    message: str,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    now = _utc_now()
    await mongo_manager.insert_one(
        RUN_LOG_COLLECTION,
        {
            "log_id": f"sv2_log_{uuid.uuid4().hex[:12]}",
            "run_id": run_id,
            "task_id": task_id,
            "user_id": user_id,
            "level": level,
            "stage": stage,
            "message": message,
            "meta": meta or {},
            "created_at": now,
        },
    )


def _stock_identity(stock: Dict[str, Any]) -> Dict[str, str]:
    ts_code = str(stock.get("ts_code") or "").upper()
    code = str(stock.get("symbol") or stock.get("code") or (ts_code.split(".")[0] if "." in ts_code else ts_code))
    name = str(stock.get("name") or ts_code)
    return {"ts_code": ts_code, "code": code, "name": name}


def _score_for_signal(signal: int) -> float:
    if signal == 1:
        return 1.0
    if signal == -1:
        return 0.8
    return 0.2


def _action_accepts_signal(action: Dict[str, Any], signal: int) -> bool:
    if not action.get("enabled", True):
        return False
    trigger_signals = action.get("trigger_signals")
    if not trigger_signals:
        return True
    return signal in {int(item) for item in trigger_signals}


def _has_enabled_action(task: Dict[str, Any], action_type: str, signal: int | None = None) -> bool:
    for action in task.get("actions") or []:
        if action.get("action_type") != action_type:
            continue
        if signal is None:
            if action.get("enabled", True):
                return True
        elif _action_accepts_signal(action, signal):
            return True
    return False


def _stock_payload_from_run_item(
    item_doc: Dict[str, Any],
    *,
    source_module: str,
    source_query: str,
    source_pool_name: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    now = _utc_now()
    payload = {
        "ts_code": item_doc.get("entity_key"),
        "code": item_doc.get("code") or str(item_doc.get("entity_key") or "").split(".")[0],
        "name": item_doc.get("entity_name") or item_doc.get("entity_key"),
        "status": "active",
        "source_module": source_module,
        "source_run_id": item_doc.get("run_id"),
        "source_query": source_query,
        "source_pool_name": source_pool_name,
        "source_type": "strategy_v2",
        "source_strategy": (item_doc.get("tags") or [""])[0],
        "operator_type": "auto",
        "last_transition_at": now,
        "added_at": now,
    }
    payload.update(extra or {})
    return payload


async def _load_user_pool(pool_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    if not pool_id:
        return None
    return await mongo_manager.find_one(
        STOCK_POOL_COLLECTION,
        {"pool_id": pool_id, "user_id": user_id},
        projection={"_id": 0},
    )


async def _upsert_stock_into_pool(
    pool: Dict[str, Any],
    user_id: str,
    stock_payload: Dict[str, Any],
    *,
    duplicate_policy: str,
) -> Dict[str, Any]:
    pool_id = str(pool.get("pool_id") or "")
    ts_code = str(stock_payload.get("ts_code") or "").upper()
    stocks = list(pool.get("stocks") or [])
    existing_index = next(
        (
            index for index, item in enumerate(stocks)
            if str(item.get("ts_code") or "").upper() == ts_code
        ),
        None,
    )
    now = _utc_now()
    if existing_index is not None and duplicate_policy == "skip":
        return {
            "status": "skipped",
            "summary": f"{stock_payload.get('name') or ts_code} 已存在于股池「{pool.get('name') or pool_id}」",
            "changed": False,
        }

    if existing_index is None:
        stock_payload["entered_at"] = stock_payload.get("entered_at") or now
        stocks.append(stock_payload)
        status = "executed"
        summary = f"已加入股池「{pool.get('name') or pool_id}」"
    else:
        existing = dict(stocks[existing_index])
        stock_payload["entered_at"] = existing.get("entered_at") or existing.get("added_at") or now
        stock_payload["added_at"] = existing.get("added_at") or now
        stocks[existing_index] = {**existing, **stock_payload}
        status = "executed"
        summary = f"已刷新股池「{pool.get('name') or pool_id}」中的入池原因"

    await mongo_manager.update_one(
        STOCK_POOL_COLLECTION,
        {"pool_id": pool_id, "user_id": user_id},
        {"$set": {"stocks": stocks, "updated_at": now}},
    )
    return {"status": status, "summary": summary, "changed": True}


async def _remove_stock_from_pool(pool: Dict[str, Any], user_id: str, ts_code: str) -> Dict[str, Any]:
    pool_id = str(pool.get("pool_id") or "")
    normalized = ts_code.upper()
    stocks = list(pool.get("stocks") or [])
    filtered = [item for item in stocks if str(item.get("ts_code") or "").upper() != normalized]
    if len(filtered) == len(stocks):
        return {
            "status": "skipped",
            "summary": f"{normalized} 不在股池「{pool.get('name') or pool_id}」中",
            "changed": False,
        }
    await mongo_manager.update_one(
        STOCK_POOL_COLLECTION,
        {"pool_id": pool_id, "user_id": user_id},
        {"$set": {"stocks": filtered, "updated_at": _utc_now()}},
    )
    return {
        "status": "executed",
        "summary": f"已从股池「{pool.get('name') or pool_id}」移出",
        "changed": True,
    }


def _normalize_alert_frequency(action_params: Dict[str, Any]) -> str:
    frequency = str(action_params.get("alert_frequency") or "daily_once").strip().lower()
    if frequency in {"daily_once", "once_then_disable", "unlimited"}:
        return frequency
    return "daily_once"


def _market_today_key() -> str:
    return datetime.now(MARKET_TIMEZONE).strftime("%Y%m%d")


def _notify_stock_config(task: Dict[str, Any], entity_key: str) -> Dict[str, Any]:
    params = task.get("params") or {}
    stock_configs = params.get("stock_configs") or {}
    current = stock_configs.get(entity_key) or {}
    return dict(current) if isinstance(current, dict) else {}


def _notify_skip_reason(task: Dict[str, Any], entity_key: str, frequency: str, today_key: str) -> Optional[str]:
    config = _notify_stock_config(task, entity_key)
    if config.get("enabled") is False:
        return "通知跳过：股票级监听配置已停用"
    if frequency == "unlimited":
        return None
    if frequency == "daily_once" and config.get("last_notified_date") == today_key:
        return "通知跳过：今日已提醒过"
    if frequency == "once_then_disable":
        if config.get("frequency_disabled"):
            return "通知跳过：提醒后关闭规则已生效"
        if config.get("last_notified_date") == today_key:
            return "通知跳过：今日已提醒过"
    return None


async def _record_notify_state(task: Dict[str, Any], entity_key: str, frequency: str, today_key: str) -> None:
    params = dict(task.get("params") or {})
    stock_configs = dict(params.get("stock_configs") or {})
    current = dict(stock_configs.get(entity_key) or {})
    current["ts_code"] = current.get("ts_code") or entity_key
    current["last_notified_date"] = today_key
    current["last_notified_at"] = _utc_now()
    try:
        current["notify_count"] = int(current.get("notify_count") or 0) + 1
    except (TypeError, ValueError):
        current["notify_count"] = 1
    if frequency == "once_then_disable":
        current["enabled"] = False
        current["frequency_disabled"] = True
        current["disabled_reason"] = "once_then_disable"
    stock_configs[entity_key] = current
    params["stock_configs"] = stock_configs
    task["params"] = params
    await mongo_manager.update_one(
        TASK_COLLECTION,
        {"task_id": task.get("task_id"), "user_id": task.get("user_id")},
        {"$set": {"params": params, "updated_at": _utc_now()}},
    )


def _float_from_meta(meta: Dict[str, Any], keys: List[str], default: float = 0.0) -> float:
    for key in keys:
        try:
            value = meta.get(key)
            if value not in (None, ""):
                return float(value)
        except (TypeError, ValueError):
            continue
    return default


def _build_notify_alert(task: Dict[str, Any], item_doc: Dict[str, Any], action: Dict[str, Any]) -> StrategyAlert:
    meta = item_doc.get("meta") or {}
    strategy_name = str(task.get("strategy_name") or task.get("strategy_key") or "Strategy V2")
    action_label = str(action.get("label") or "通知")
    reason = str(item_doc.get("reason") or "策略信号触发")
    return StrategyAlert(
        subscription_id=str(task.get("task_id") or ""),
        strategy_id=f"strategy_v2:{task.get('task_id')}:{action.get('action_id') or 'notify'}:{item_doc.get('entity_key')}",
        strategy_name=f"{strategy_name} · {action_label}",
        ts_code=str(item_doc.get("entity_key") or ""),
        stock_name=str(item_doc.get("entity_name") or item_doc.get("entity_key") or ""),
        trigger_price=_float_from_meta(meta, ["current_price", "price", "close", "latest_price"]),
        trigger_reason=f"信号 {item_doc.get('signal')}：{reason}",
        extra_data={
            "run_id": item_doc.get("run_id"),
            "task_id": task.get("task_id"),
            "action_id": action.get("action_id"),
            "score": item_doc.get("score"),
            "strategy_v2": True,
        },
        triggered_at=_utc_now(),
    )


async def _build_action_audits_for_item(
    task: Dict[str, Any],
    item_doc: Dict[str, Any],
    temp_pool: Optional[Dict[str, str]],
) -> tuple[str, List[Dict[str, Any]]]:
    action_results: List[str] = []
    audit_docs: List[Dict[str, Any]] = []
    signal = int(item_doc.get("signal") or 0)
    now = _utc_now()
    for action in task.get("actions") or []:
        action_type = action.get("action_type")
        if not _action_accepts_signal(action, signal):
            continue
        audit_status = "planned"
        result_summary = "动作已命中，等待执行器接入"
        related_resource: Dict[str, Any] = {}
        if action_type == "temp_list":
            if temp_pool:
                audit_status = "executed"
                result_summary = f"已生成临时清单：{temp_pool['pool_name']}"
                related_resource = {"pool_id": temp_pool["pool_id"], "pool_name": temp_pool["pool_name"]}
            else:
                audit_status = "skipped"
                result_summary = "未生成临时清单：没有正向命中或动作未启用"
            action_results.append(result_summary)
        elif action_type == "add_to_pool":
            target_pool_id = str((action.get("params") or {}).get("target_pool_id") or "").strip()
            duplicate_policy = str((action.get("params") or {}).get("duplicate_policy") or "skip")
            target_pool = await _load_user_pool(target_pool_id, str(task.get("user_id") or ""))
            if not target_pool:
                audit_status = "failed"
                result_summary = "加入股池失败：目标股池不存在"
            else:
                stock_payload = _stock_payload_from_run_item(
                    item_doc,
                    source_module="strategy_v2_add_to_pool",
                    source_query=task.get("name") or task.get("strategy_name") or "Strategy V2",
                    extra={"source_action_id": action.get("action_id")},
                )
                result = await _upsert_stock_into_pool(
                    target_pool,
                    str(task.get("user_id") or ""),
                    stock_payload,
                    duplicate_policy=duplicate_policy,
                )
                audit_status = result["status"]
                result_summary = result["summary"]
                related_resource = {"pool_id": target_pool_id, "pool_name": target_pool.get("name")}
            action_results.append(result_summary)
        elif action_type == "notify":
            action_params = action.get("params") or {}
            entity_key = str(item_doc.get("entity_key") or "")
            frequency = _normalize_alert_frequency(action_params)
            today_key = _market_today_key()
            channel_id = str(action_params.get("notification_channel_id") or "").strip() or None
            related_resource = {
                "notification_channel_id": channel_id,
                "alert_frequency": frequency,
            }
            skip_reason = _notify_skip_reason(task, entity_key, frequency, today_key)
            if skip_reason:
                audit_status = "skipped"
                result_summary = skip_reason
            else:
                alert = _build_notify_alert(task, item_doc, action)
                try:
                    sent = await notification_manager.send_alert(
                        alert,
                        user_id=str(task.get("user_id") or ""),
                        channel_id=channel_id,
                    )
                except Exception as exc:
                    logger.exception("Strategy V2 notify action failed: %s", exc)
                    sent = False
                    result_summary = f"通知发送失败：{exc}"
                if sent:
                    await _record_notify_state(task, entity_key, frequency, today_key)
                    audit_status = "executed"
                    result_summary = "通知已发送"
                    related_resource["alert_id"] = alert.alert_id
                elif not result_summary.startswith("通知发送失败"):
                    audit_status = "failed"
                    result_summary = "通知发送失败：通知渠道未配置、未启用或被通道限流"
                else:
                    audit_status = "failed"
            action_results.append(result_summary)
        elif action_type == "paper_trade":
            result_summary = "命中模拟成交动作，待接入交割单写入"
            action_results.append(result_summary)
        elif action_type == "pool_transition":
            action_params = action.get("params") or {}
            transition_mode = str(action_params.get("transition_mode") or "copy").strip().lower()
            source_scope = task.get("target_scope") or {}
            source_pool_id = str(source_scope.get("scope_id") or (source_scope.get("params") or {}).get("stock_pool_id") or "")
            target_pool_id = str(action_params.get("target_pool_id") or "").strip()
            source_pool = await _load_user_pool(source_pool_id, str(task.get("user_id") or ""))
            target_pool = None if transition_mode == "delete" else await _load_user_pool(target_pool_id, str(task.get("user_id") or ""))
            if transition_mode not in {"copy", "move", "delete"}:
                audit_status = "failed"
                result_summary = f"股池流转失败：不支持的流转方式 {transition_mode}"
            elif not source_pool:
                audit_status = "failed"
                result_summary = "股池流转失败：来源股池不存在"
            elif transition_mode != "delete" and not target_pool:
                audit_status = "failed"
                result_summary = "股池流转失败：目标股池不存在"
            elif transition_mode in {"copy", "move"} and source_pool_id == target_pool_id:
                audit_status = "skipped"
                result_summary = "股池流转跳过：来源股池和目标股池相同"
            else:
                summaries: List[str] = []
                if transition_mode in {"copy", "move"} and target_pool:
                    stock_payload = _stock_payload_from_run_item(
                        item_doc,
                        source_module="strategy_v2_pool_transition",
                        source_query=task.get("name") or task.get("strategy_name") or "Strategy V2",
                        source_pool_name=source_pool.get("name"),
                        extra={"source_action_id": action.get("action_id"), "transition_mode": transition_mode},
                    )
                    upsert_result = await _upsert_stock_into_pool(
                        target_pool,
                        str(task.get("user_id") or ""),
                        stock_payload,
                        duplicate_policy="refresh_reason",
                    )
                    summaries.append(upsert_result["summary"])
                if transition_mode in {"move", "delete"}:
                    remove_result = await _remove_stock_from_pool(
                        source_pool,
                        str(task.get("user_id") or ""),
                        str(item_doc.get("entity_key") or ""),
                    )
                    summaries.append(remove_result["summary"])
                audit_status = "executed" if any("已" in summary for summary in summaries) else "skipped"
                result_summary = "；".join(summaries) or "股池流转未产生变化"
                related_resource = {
                    "source_pool_id": source_pool_id,
                    "source_pool_name": source_pool.get("name") if source_pool else None,
                    "target_pool_id": target_pool_id if transition_mode != "delete" else None,
                    "target_pool_name": target_pool.get("name") if target_pool else None,
                    "transition_mode": transition_mode,
                }
            action_results.append(result_summary)
        else:
            result_summary = f"命中未知动作：{action_type}"
            action_results.append(result_summary)

        audit_docs.append(
            {
                "audit_id": f"sv2_audit_{uuid.uuid4().hex[:12]}",
                "run_id": item_doc.get("run_id"),
                "task_id": task.get("task_id"),
                "user_id": item_doc.get("user_id"),
                "item_id": item_doc.get("item_id"),
                "entity_key": item_doc.get("entity_key"),
                "entity_name": item_doc.get("entity_name"),
                "signal": signal,
                "action_id": action.get("action_id"),
                "action_type": action_type,
                "action_label": action.get("label") or action_type,
                "status": audit_status,
                "result_summary": result_summary,
                "trigger_signals": action.get("trigger_signals") or [],
                "params": action.get("params") or {},
                "related_resource": related_resource,
                "created_at": now,
            }
        )
    if action_results:
        return "；".join(action_results), audit_docs
    if signal == 1:
        return "正向信号，未配置动作", audit_docs
    if signal == -1:
        return "负向信号，未配置动作", audit_docs
    return "无动作", audit_docs


async def _resolve_task_targets(task: Dict[str, Any]) -> List[Dict[str, Any]]:
    scope = task.get("target_scope") or {}
    scope_type = scope.get("scope_type")
    projection = {"_id": 0, "ts_code": 1, "symbol": 1, "code": 1, "name": 1}

    if scope_type == "custom_stock_list":
        ts_codes = [str(item).upper() for item in scope.get("ts_codes") or [] if item]
        if not ts_codes:
            return []
        ts_codes = ts_codes[:MAX_TARGET_STOCKS]
        return await mongo_manager.find_many(
            "stock_basic",
            {"ts_code": {"$in": ts_codes}},
            projection=projection,
            sort=[("ts_code", 1)],
            limit=MAX_TARGET_STOCKS,
        )

    if scope_type == "stock_pool":
        pool_id = scope.get("scope_id") or (scope.get("params") or {}).get("stock_pool_id")
        if not pool_id:
            return []
        pool = await mongo_manager.find_one(
            STOCK_POOL_COLLECTION,
            {"pool_id": pool_id, "user_id": task.get("user_id")},
            projection={"_id": 0, "stocks": 1},
        )
        ts_codes = [str(item.get("ts_code") or "").upper() for item in (pool or {}).get("stocks", []) if item.get("ts_code")]
        if not ts_codes:
            return []
        ts_codes = ts_codes[:MAX_TARGET_STOCKS]
        return await mongo_manager.find_many(
            "stock_basic",
            {"ts_code": {"$in": ts_codes}},
            projection=projection,
            sort=[("ts_code", 1)],
            limit=MAX_TARGET_STOCKS,
        )

    if scope_type == "watchlist":
        user = await mongo_manager.find_one(
            "users",
            {"user_id": task.get("user_id")},
            projection={"_id": 0, "watchlist": 1},
        )
        ts_codes = [str(item).upper() for item in (user or {}).get("watchlist", []) if item]
        if not ts_codes:
            return []
        ts_codes = ts_codes[:MAX_TARGET_STOCKS]
        return await mongo_manager.find_many(
            "stock_basic",
            {"ts_code": {"$in": ts_codes}},
            projection=projection,
            sort=[("ts_code", 1)],
            limit=MAX_TARGET_STOCKS,
        )

    if scope_type == "all_market":
        params = scope.get("params") or {}
        filters = scope.get("filters") or {}
        query: Dict[str, Any] = {}
        if filters.get("exclude_st", True):
            query["name"] = {"$not": re.compile("ST", re.IGNORECASE)}
        max_count = int(params.get("max_stock_count") or 0)
        target_limit = min(max_count, MAX_TARGET_STOCKS) if max_count > 0 else MAX_TARGET_STOCKS
        return await mongo_manager.find_many(
            "stock_basic",
            query,
            projection=projection,
            sort=[("ts_code", 1)],
            limit=target_limit,
        )

    return []


async def _create_temp_stock_pool(
    task: Dict[str, Any],
    run_id: str,
    positive_items: List[Dict[str, Any]],
) -> Optional[Dict[str, str]]:
    if not positive_items:
        return None
    if not _has_enabled_action(task, "temp_list", 1):
        return None

    action = next(
        (
            item for item in task.get("actions") or []
            if item.get("action_type") == "temp_list" and _action_accepts_signal(item, 1)
        ),
        {},
    )
    ttl_days = int((action.get("params") or {}).get("ttl_days") or 1)
    now = _utc_now()
    pool_id = f"sv2_temp_{uuid.uuid4().hex[:12]}"
    pool_name = f"{task.get('name') or task.get('strategy_name') or '策略'}临时清单-{now.strftime('%m%d%H%M')}"
    stocks = [
        {
            "ts_code": item["entity_key"],
            "code": item.get("code") or item["entity_key"].split(".")[0],
            "name": item.get("entity_name") or item["entity_key"],
            "status": "active",
            "source_module": "strategy_v2_temp_list",
            "source_run_id": run_id,
            "source_query": task.get("name") or task.get("strategy_name"),
            "source_pool_name": pool_name,
            "added_at": now,
        }
        for item in positive_items
    ]
    record = {
        "pool_id": pool_id,
        "user_id": task.get("user_id"),
        "name": pool_name,
        "pool_type": "候选池",
        "description": f"由 V2 任务 {task.get('name') or task.get('task_id')} 一次性运行生成，默认保留 {ttl_days} 天。",
        "stocks": stocks,
        "source_module": "strategy_v2_temp_list",
        "source_run_id": run_id,
        "expires_at": now + timedelta(days=max(ttl_days, 1)),
        "created_at": now,
        "updated_at": now,
    }
    await mongo_manager.insert_one(STOCK_POOL_COLLECTION, record)
    return {"pool_id": pool_id, "pool_name": pool_name}


async def _execute_strategy_v2_run(run_id: str, user_id: str) -> None:
    async with _RUN_SEMAPHORE:
        await _execute_strategy_v2_run_inner(run_id, user_id)


async def _execute_strategy_v2_run_inner(run_id: str, user_id: str) -> None:
    now = _utc_now()
    task_id = ""
    try:
        run = await mongo_manager.find_one(
            RUN_COLLECTION,
            {"run_id": run_id, "user_id": user_id},
            projection={"_id": 0},
        )
        if not run:
            return
        task = await mongo_manager.find_one(
            TASK_COLLECTION,
            {"task_id": run.get("task_id"), "user_id": user_id},
            projection={"_id": 0},
        )
        if not task:
            raise RuntimeError("任务不存在或已被删除")
        task_id = str(task.get("task_id") or "")
        await _append_run_log(
            run_id,
            task_id,
            user_id,
            level="info",
            stage="start",
            message=f"开始运行任务：{task.get('name') or task_id}",
            meta={"trigger_source": run.get("trigger_source"), "strategy_key": task.get("strategy_key")},
        )

        await _ensure_run_can_continue(run_id, user_id)
        await _update_run_progress(
            run_id,
            user_id,
            current=0,
            total=0,
            label="正在解析目标范围",
        )
        await _append_run_log(
            run_id,
            task_id,
            user_id,
            level="info",
            stage="resolve_targets",
            message="正在解析目标范围",
            meta={"scope_type": (task.get("target_scope") or {}).get("scope_type")},
        )
        targets = await _resolve_task_targets(task)
        await _ensure_run_can_continue(run_id, user_id)
        total_targets = len(targets)
        await _update_run_progress(
            run_id,
            user_id,
            current=0,
            total=total_targets,
            label=f"已加载 {total_targets} 个目标，开始评估",
        )
        await _append_run_log(
            run_id,
            task_id,
            user_id,
            level="info",
            stage="resolve_targets",
            message=f"目标解析完成，共 {total_targets} 个",
            meta={"total_targets": total_targets},
        )
        params = dict(task.get("params") or {})
        item_docs: List[Dict[str, Any]] = []
        positive_items: List[Dict[str, Any]] = []
        action_audit_docs: List[Dict[str, Any]] = []
        positive = neutral = negative = 0

        for index, stock in enumerate(targets, start=1):
            if index == 1 or index % 25 == 0:
                await _ensure_run_can_continue(run_id, user_id)
            identity = _stock_identity(stock)
            if not identity["ts_code"]:
                continue
            try:
                result = await evaluate_strategy_v2(
                    str(task.get("strategy_key") or ""),
                    StrategyV2EvaluationContext(
                        user_id=user_id,
                        code=identity["code"],
                        ts_code=identity["ts_code"],
                        stock=stock,
                        now=now,
                    ),
                    params=params,
                )
                signal = int(result.signal)
                reason = result.reason
                meta = result.meta
            except Exception as exc:
                signal = 0
                reason = f"策略评估失败：{exc}"
                meta = {}

            if signal > 0:
                positive += 1
            elif signal < 0:
                negative += 1
            else:
                neutral += 1

            item_doc = {
                "item_id": f"sv2_item_{uuid.uuid4().hex[:12]}",
                "run_id": run_id,
                "task_id": task.get("task_id"),
                "user_id": user_id,
                "entity_key": identity["ts_code"],
                "entity_name": identity["name"],
                "code": identity["code"],
                "signal": signal,
                "score": _score_for_signal(signal),
                "reason": reason,
                "tags": [str(task.get("strategy_name") or task.get("strategy_key") or "")],
                "action_result": "待生成动作结果",
                "state_writeback": signal != 0,
                "meta": meta,
                "created_at": now,
            }
            if signal == 1:
                positive_items.append(item_doc)
            item_docs.append(item_doc)
            if index == 1 or index == total_targets or index % 25 == 0:
                await _update_run_progress(
                    run_id,
                    user_id,
                    current=index,
                    total=total_targets,
                    label=f"正在评估 {index}/{total_targets}",
                )

        await _ensure_run_can_continue(run_id, user_id)
        await _update_run_progress(
            run_id,
            user_id,
            current=total_targets,
            total=total_targets,
            label="策略评估完成，正在处理动作产物",
        )
        await _append_run_log(
            run_id,
            task_id,
            user_id,
            level="info",
            stage="evaluate",
            message=f"策略评估完成：正向 {positive}，中性 {neutral}，负向 {negative}",
            meta={"positive": positive, "neutral": neutral, "negative": negative},
        )
        temp_pool = await _create_temp_stock_pool(task, run_id, positive_items)
        await _ensure_run_can_continue(run_id, user_id)
        for item_doc in item_docs:
            item_doc["action_result"], audits = await _build_action_audits_for_item(task, item_doc, temp_pool)
            action_audit_docs.extend(audits)
        notify_audits = [audit for audit in action_audit_docs if audit.get("action_type") == "notify"]
        await _append_run_log(
            run_id,
            task_id,
            user_id,
            level="info",
            stage="actions",
            message=f"动作审计生成完成，共 {len(action_audit_docs)} 条",
            meta={
                "audit_count": len(action_audit_docs),
                "temp_pool_id": temp_pool["pool_id"] if temp_pool else None,
                "temp_pool_name": temp_pool["pool_name"] if temp_pool else None,
                "notify_executed": sum(1 for audit in notify_audits if audit.get("status") == "executed"),
                "notify_skipped": sum(1 for audit in notify_audits if audit.get("status") == "skipped"),
                "notify_failed": sum(1 for audit in notify_audits if audit.get("status") == "failed"),
            },
        )

        if item_docs:
            await mongo_manager.insert_many(RUN_ITEM_COLLECTION, item_docs)
        if action_audit_docs:
            await mongo_manager.insert_many(ACTION_AUDIT_COLLECTION, action_audit_docs)

        await _ensure_run_can_continue(run_id, user_id)
        finished_at = _utc_now()
        run_status = "success"
        summary = f"完成 {len(targets)} 个目标评估，正向 {positive}，中性 {neutral}，负向 {negative}。"
        if temp_pool:
            summary += f" 已生成临时清单「{temp_pool['pool_name']}」。"
        run_update = {
            "run_status": run_status,
            "summary": summary,
            "finished_at": finished_at,
            "progress_current": total_targets,
            "progress_total": total_targets,
            "progress_pct": 100,
            "progress_label": "运行完成",
            "signal_breakdown": {"positive": positive, "neutral": neutral, "negative": negative},
            "summary_metrics": [
                {"label": "评估目标", "value": str(len(targets))},
                {"label": "正向信号", "value": str(positive), "tone": "positive"},
                {"label": "负向信号", "value": str(negative), "tone": "negative" if negative else "default"},
                {"label": "临时清单", "value": str(positive if temp_pool else 0), "tone": "warning" if temp_pool else "default"},
                {"label": "动作审计", "value": str(len(action_audit_docs))},
            ],
            "related_pool_id": temp_pool["pool_id"] if temp_pool else None,
            "related_pool_name": temp_pool["pool_name"] if temp_pool else None,
            "next_action_hint": "打开临时清单进入股池复盘，或在下方结果表逐只查看命中原因。" if temp_pool else "本次未生成临时清单，可检查策略参数和目标范围。",
            "updated_at": finished_at,
        }
        await mongo_manager.update_one(
            RUN_COLLECTION,
            {"run_id": run_id, "user_id": user_id, "run_status": "running"},
            {"$set": run_update},
        )
        await _release_task_run_lock(
            task_id,
            user_id,
            run_id,
            run_status,
            finished_at,
            signal_count=positive + negative,
        )
        await _append_run_log(
            run_id,
            task_id,
            user_id,
            level="info",
            stage="finish",
            message="运行完成",
            meta={"run_status": run_status, "finished_at": finished_at.isoformat()},
        )
    except StrategyV2RunCancelled:
        finished_at = _utc_now()
        await mongo_manager.update_one(
            RUN_COLLECTION,
            {"run_id": run_id, "user_id": user_id, "run_status": "running"},
            {
                "$set": {
                    "run_status": "cancelled",
                    "summary": "运行已取消：后台执行已停止。",
                    "finished_at": finished_at,
                    "progress_label": "已取消",
                    "summary_metrics": [{"label": "状态", "value": "已取消", "tone": "warning"}],
                    "next_action_hint": "如需重新执行，可在本页或任务详情页点击重试。",
                    "updated_at": finished_at,
                }
            },
        )
        if not task_id:
            run = await mongo_manager.find_one(
                RUN_COLLECTION,
                {"run_id": run_id, "user_id": user_id},
                projection={"_id": 0, "task_id": 1},
            )
            task_id = str((run or {}).get("task_id") or "")
        await _release_task_run_lock(task_id, user_id, run_id, "cancelled", finished_at)
        if task_id:
            await _append_run_log(
                run_id,
                task_id,
                user_id,
                level="warning",
                stage="cancel",
                message="运行已取消",
                meta={"finished_at": finished_at.isoformat()},
            )
    except Exception as exc:
        finished_at = _utc_now()
        await mongo_manager.update_one(
            RUN_COLLECTION,
            {"run_id": run_id, "user_id": user_id, "run_status": "running"},
            {
                "$set": {
                    "run_status": "failed",
                    "summary": f"运行失败：{exc}",
                    "finished_at": finished_at,
                    "progress_label": "运行失败",
                    "summary_metrics": [{"label": "状态", "value": "失败", "tone": "negative"}],
                    "next_action_hint": "请检查目标范围、策略参数和后端日志。",
                    "updated_at": finished_at,
                }
            },
        )
        if not task_id:
            run = await mongo_manager.find_one(
                RUN_COLLECTION,
                {"run_id": run_id, "user_id": user_id},
                projection={"_id": 0, "task_id": 1},
            )
            task_id = str((run or {}).get("task_id") or "")
        await _release_task_run_lock(task_id, user_id, run_id, "failed", finished_at)
        if task_id:
            await _append_run_log(
                run_id,
                task_id,
                user_id,
                level="error",
                stage="failed",
                message=f"运行失败：{exc}",
                meta={"finished_at": finished_at.isoformat()},
            )


async def _validate_stock_exists(ts_code: str) -> Dict[str, Any]:
    stock = await mongo_manager.find_one(
        "stock_basic",
        {"ts_code": ts_code},
        projection={"_id": 0, "ts_code": 1, "name": 1},
    )
    if not stock:
        raise HTTPException(status_code=400, detail=f"股票 {ts_code} 不存在")
    return stock


def _ensure_listen_task(task: Dict[str, Any]) -> None:
    if task.get("scene_type") != "listen":
        raise HTTPException(status_code=400, detail="只有监听任务支持股票级监听配置")


def _task_scope(task: Dict[str, Any]) -> Dict[str, Any]:
    scope = task.get("target_scope") or {}
    if not isinstance(scope, dict):
        raise HTTPException(status_code=400, detail="任务目标范围格式异常")
    return scope


def _default_stock_config(task: Dict[str, Any], ts_code: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    strategy = get_strategy_definition(str(task.get("strategy_key") or "")) or {}
    task_params = dict(task.get("params") or {})
    base: Dict[str, Any] = {
        "enabled": True,
        "note": "",
    }
    for item in strategy.get("param_schema", []) or []:
        key = item.get("key")
        if not key or key in {"stock_configs", "query_text", "cache_ttl_days"}:
            continue
        base[key] = task_params.get(key, item.get("default"))
    base.update(config or {})
    base["ts_code"] = ts_code
    return base


def _normalize_stock_config(config: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(config or {})
    normalized["enabled"] = bool(normalized.get("enabled", True))
    normalized["note"] = str(normalized.get("note", "") or "").strip()
    return normalized


async def _assert_task_contains_stock(task: Dict[str, Any], ts_code: str) -> None:
    scope = _task_scope(task)
    scope_type = scope.get("scope_type")
    if scope_type == "custom_stock_list":
        ts_codes = [str(item).upper() for item in scope.get("ts_codes", []) or []]
        if ts_code not in ts_codes:
            raise HTTPException(status_code=400, detail=f"{ts_code} 不在该任务的自定义股票列表中")
        return

    if scope_type == "stock_pool":
        pool_id = scope.get("scope_id") or (scope.get("params") or {}).get("stock_pool_id")
        if not pool_id:
            raise HTTPException(status_code=400, detail="股池任务缺少股池 ID")
        pool = await mongo_manager.find_one(
            STOCK_POOL_COLLECTION,
            {"pool_id": pool_id, "user_id": task.get("user_id")},
            projection={"_id": 0, "stocks.ts_code": 1},
        )
        if not pool:
            raise HTTPException(status_code=404, detail="任务关联股池不存在")
        pool_codes = {
            str(item.get("ts_code") or "").upper()
            for item in pool.get("stocks", []) or []
        }
        if ts_code not in pool_codes:
            raise HTTPException(status_code=400, detail=f"{ts_code} 不在该任务关联股池中")
        return

    raise HTTPException(status_code=400, detail="当前目标范围暂不支持股票级监听配置")


@router.post("/tasks/{task_id}/stocks", response_model=StrategyV2SceneTaskResponse)
async def add_stock_to_strategy_v2_task(
    task_id: str = Path(...),
    body: StrategyV2TaskStockRequest = Body(...),
    user_id: str = Depends(get_current_user_id),
) -> StrategyV2SceneTaskResponse:
    """Add a stock to a V2 custom-stock listener task."""
    task = await _get_user_task_or_404(task_id, user_id)
    _ensure_listen_task(task)
    scope = _task_scope(task)
    if scope.get("scope_type") != "custom_stock_list":
        raise HTTPException(status_code=400, detail="添加股票只支持自定义股票列表监听任务")

    ts_code = body.ts_code.upper()
    if not re.match(r"^\d{6}\.(SH|SZ|BJ)$", ts_code):
        raise HTTPException(status_code=400, detail="股票代码格式不正确")
    stock = await _validate_stock_exists(ts_code)

    ts_codes = [str(item).upper() for item in scope.get("ts_codes", []) or []]
    if ts_code not in ts_codes:
        ts_codes.append(ts_code)
    scope["ts_codes"] = ts_codes
    scope["summary"] = f"自定义股票列表 · {len(ts_codes)} 只"

    params = dict(task.get("params") or {})
    stock_configs = dict(params.get("stock_configs") or {})
    if ts_code in stock_configs and body.config:
        current_config = dict(stock_configs.get(ts_code) or {})
        current_config.update(_normalize_stock_config(body.config))
        current_config["ts_code"] = ts_code
        current_config["name"] = stock.get("name") or current_config.get("name") or ts_code
        stock_configs[ts_code] = current_config
    else:
        current_config = stock_configs.get(ts_code) or _default_stock_config(task, ts_code, body.config)
        current_config["name"] = stock.get("name") or current_config.get("name") or ts_code
        stock_configs[ts_code] = current_config
    params["stock_configs"] = stock_configs

    now = datetime.now(UTC)
    await mongo_manager.update_one(
        TASK_COLLECTION,
        {"task_id": task_id, "user_id": user_id},
        {
            "$set": {
                "target_scope": scope,
                "target_scope_summary": scope["summary"],
                "params": params,
                "updated_at": now,
            }
        },
    )
    updated = await _get_user_task_or_404(task_id, user_id)
    return StrategyV2SceneTaskResponse(**updated)


@router.put("/tasks/{task_id}/stocks/{ts_code}/config", response_model=StrategyV2SceneTaskResponse)
async def update_strategy_v2_task_stock_config(
    task_id: str = Path(...),
    ts_code: str = Path(..., pattern=r"^\d{6}\.(SH|SZ|BJ)$"),
    body: StrategyV2StockConfigRequest = Body(...),
    user_id: str = Depends(get_current_user_id),
) -> StrategyV2SceneTaskResponse:
    """Persist per-stock strategy params under task.params.stock_configs."""
    task = await _get_user_task_or_404(task_id, user_id)
    _ensure_listen_task(task)
    ts_code = ts_code.upper()
    await _validate_stock_exists(ts_code)
    await _assert_task_contains_stock(task, ts_code)

    params = dict(task.get("params") or {})
    stock_configs = dict(params.get("stock_configs") or {})
    current_config = dict(stock_configs.get(ts_code) or _default_stock_config(task, ts_code))
    current_config.update(_normalize_stock_config(body.config))
    current_config["ts_code"] = ts_code
    stock_configs[ts_code] = current_config
    params["stock_configs"] = stock_configs

    await mongo_manager.update_one(
        TASK_COLLECTION,
        {"task_id": task_id, "user_id": user_id},
        {
            "$set": {
                "params": params,
                "updated_at": datetime.now(UTC),
            }
        },
    )
    updated = await _get_user_task_or_404(task_id, user_id)
    return StrategyV2SceneTaskResponse(**updated)


@router.delete("/tasks/{task_id}/stocks/{ts_code}", response_model=StrategyV2SceneTaskResponse)
async def remove_stock_from_strategy_v2_task(
    task_id: str = Path(...),
    ts_code: str = Path(..., pattern=r"^\d{6}\.(SH|SZ|BJ)$"),
    user_id: str = Depends(get_current_user_id),
) -> StrategyV2SceneTaskResponse:
    """Remove a stock and its per-stock config from a V2 custom-stock listener task."""
    task = await _get_user_task_or_404(task_id, user_id)
    _ensure_listen_task(task)
    scope = _task_scope(task)
    if scope.get("scope_type") != "custom_stock_list":
        raise HTTPException(status_code=400, detail="移除股票只支持自定义股票列表监听任务")

    normalized = ts_code.upper()
    ts_codes = [str(item).upper() for item in scope.get("ts_codes", []) or [] if item]
    if normalized not in ts_codes:
        raise HTTPException(status_code=404, detail=f"{normalized} 不在该任务监听列表中")

    scope["ts_codes"] = [item for item in ts_codes if item != normalized]
    scope["summary"] = f"自定义股票列表 · {len(scope['ts_codes'])} 只"

    params = dict(task.get("params") or {})
    stock_configs = dict(params.get("stock_configs") or {})
    stock_configs.pop(normalized, None)
    params["stock_configs"] = stock_configs

    await mongo_manager.update_one(
        TASK_COLLECTION,
        {"task_id": task_id, "user_id": user_id},
        {
            "$set": {
                "target_scope": scope,
                "target_scope_summary": scope["summary"],
                "params": params,
                "updated_at": datetime.now(UTC),
            }
        },
    )
    updated = await _get_user_task_or_404(task_id, user_id)
    return StrategyV2SceneTaskResponse(**updated)


@router.post("/tasks", response_model=StrategyV2SceneTaskResponse)
async def create_strategy_v2_task(
    body: StrategyV2CreateTaskRequest,
    user_id: str = Depends(get_current_user_id),
) -> StrategyV2SceneTaskResponse:
    errors = validate_task_config(body)
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})

    strategy = get_strategy_definition(body.strategy_key)
    now = datetime.now(UTC)
    task_id = f"sv2_{uuid.uuid4().hex[:12]}"
    actions = []
    action_labels = {
        "notify": "通知",
        "add_to_pool": "加入股池",
        "pool_transition": "股池流转",
        "temp_list": "临时清单",
        "paper_trade": "模拟成交",
    }
    for action in body.actions:
        action_doc = action.model_dump(mode="json")
        action_doc["action_id"] = action_doc.get("action_id") or f"act_{uuid.uuid4().hex[:10]}"
        action_doc["label"] = action_doc.get("label") or action_labels.get(action.action_type.value, action.action_type.value)
        action_doc["summary"] = action_doc.get("summary") or f"信号 {'/'.join(str(item) for item in action.trigger_signals)} 时执行 {action_doc['label']}"
        actions.append(action_doc)

    doc = {
        **body.model_dump(mode="json"),
        "actions": actions,
        "task_id": task_id,
        "user_id": user_id,
        "strategy_name": (strategy or {}).get("name") or body.strategy_key,
        "status": StrategyV2TaskStatus.DRAFT.value if body.scene_type.value == "backtest" else StrategyV2TaskStatus.ACTIVE.value,
        "target_scope_summary": body.target_scope.summary or "",
        "schedule_label": body.schedule.label,
        "tags": [body.scene_type.value, *list((strategy or {}).get("tags", []))[:2]],
        "last_signal_count": 0,
        "last_run_id": None,
        "last_run_status": None,
        "active_run_id": None,
        "created_at": now,
        "updated_at": now,
    }

    await mongo_manager.insert_one(TASK_COLLECTION, doc)
    return StrategyV2SceneTaskResponse(**doc)
