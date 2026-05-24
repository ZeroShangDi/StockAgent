"""Strategy V2 API skeleton."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
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
from core.managers import mongo_manager
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

TASK_COLLECTION = "strategy_v2_scene_tasks"
RUN_COLLECTION = "strategy_v2_task_runs"
RUN_ITEM_COLLECTION = "strategy_v2_task_run_items"
STOCK_POOL_COLLECTION = "stock_pools"
RUN_STALE_AFTER_SECONDS = 30 * 60
ACTIVE_RUN_STATUSES = {"running"}


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


async def _mark_stale_running_runs(
    *,
    user_id: str,
    task_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> None:
    query: Dict[str, Any] = {"user_id": user_id, "run_status": "running"}
    if task_id:
        query["task_id"] = task_id
    if run_id:
        query["run_id"] = run_id

    running_runs = await mongo_manager.find_many(
        RUN_COLLECTION,
        query,
        projection={"_id": 0, "run_id": 1, "task_id": 1, "started_at": 1, "progress_current": 1, "progress_total": 1},
    )
    now = _utc_now()
    for run in running_runs:
        started_at = _as_utc_datetime(run.get("started_at"))
        if not started_at or (now - started_at).total_seconds() < RUN_STALE_AFTER_SECONDS:
            continue

        finished_at = _utc_now()
        progress_current = int(run.get("progress_current") or 0)
        progress_total = int(run.get("progress_total") or 0)
        summary = "运行超时：后台任务长时间未更新，可能由服务重启或后台任务中断导致。"
        await mongo_manager.update_one(
            RUN_COLLECTION,
            {"run_id": run.get("run_id"), "user_id": user_id},
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
            user_id,
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


def _action_result_for_signal(task: Dict[str, Any], signal: int, temp_pool_name: Optional[str]) -> str:
    action_results: List[str] = []
    for action in task.get("actions") or []:
        action_type = action.get("action_type")
        if not _action_accepts_signal(action, signal):
            continue
        if action_type == "temp_list":
            action_results.append(f"已加入临时清单：{temp_pool_name or '待生成'}")
        elif action_type == "add_to_pool":
            action_results.append("命中加入股池动作")
        elif action_type == "notify":
            action_results.append("命中通知动作")
        elif action_type == "paper_trade":
            action_results.append("命中模拟成交动作")
        elif action_type == "pool_transition":
            action_results.append("命中股池流转动作")
    if action_results:
        return "；".join(action_results)
    if signal == 1:
        return "正向信号，未配置动作"
    if signal == -1:
        return "负向信号，未配置动作"
    return "无动作"


async def _resolve_task_targets(task: Dict[str, Any]) -> List[Dict[str, Any]]:
    scope = task.get("target_scope") or {}
    scope_type = scope.get("scope_type")
    projection = {"_id": 0, "ts_code": 1, "symbol": 1, "code": 1, "name": 1}

    if scope_type == "custom_stock_list":
        ts_codes = [str(item).upper() for item in scope.get("ts_codes") or [] if item]
        if not ts_codes:
            return []
        return await mongo_manager.find_many(
            "stock_basic",
            {"ts_code": {"$in": ts_codes}},
            projection=projection,
            sort=[("ts_code", 1)],
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
        return await mongo_manager.find_many(
            "stock_basic",
            {"ts_code": {"$in": ts_codes}},
            projection=projection,
            sort=[("ts_code", 1)],
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
        return await mongo_manager.find_many(
            "stock_basic",
            {"ts_code": {"$in": ts_codes}},
            projection=projection,
            sort=[("ts_code", 1)],
        )

    if scope_type == "all_market":
        params = scope.get("params") or {}
        filters = scope.get("filters") or {}
        query: Dict[str, Any] = {}
        if filters.get("exclude_st", True):
            query["name"] = {"$not": re.compile("ST", re.IGNORECASE)}
        max_count = int(params.get("max_stock_count") or 0)
        return await mongo_manager.find_many(
            "stock_basic",
            query,
            projection=projection,
            sort=[("ts_code", 1)],
            limit=max_count,
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

        await _ensure_run_can_continue(run_id, user_id)
        await _update_run_progress(
            run_id,
            user_id,
            current=0,
            total=0,
            label="正在解析目标范围",
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
        params = dict(task.get("params") or {})
        item_docs: List[Dict[str, Any]] = []
        positive_items: List[Dict[str, Any]] = []
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
        temp_pool = await _create_temp_stock_pool(task, run_id, positive_items)
        await _ensure_run_can_continue(run_id, user_id)
        temp_pool_name = temp_pool["pool_name"] if temp_pool else None
        for item_doc in item_docs:
            item_doc["action_result"] = _action_result_for_signal(task, int(item_doc["signal"]), temp_pool_name)

        if item_docs:
            await mongo_manager.insert_many(RUN_ITEM_COLLECTION, item_docs)

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
    await _validate_stock_exists(ts_code)

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
        stock_configs[ts_code] = current_config
    else:
        stock_configs.setdefault(ts_code, _default_stock_config(task, ts_code, body.config))
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
