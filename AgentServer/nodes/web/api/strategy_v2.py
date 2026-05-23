"""Strategy V2 API skeleton."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
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

from .auth import get_current_user_id


router = APIRouter(prefix="/strategy-v2", tags=["Strategy V2"])

TASK_COLLECTION = "strategy_v2_scene_tasks"
STOCK_POOL_COLLECTION = "stock_pools"


class StrategyV2TaskStockRequest(BaseModel):
    ts_code: str = Field(..., pattern=r"^\d{6}\.(SH|SZ|BJ)$")
    config: Optional[Dict[str, Any]] = None


class StrategyV2StockConfigRequest(BaseModel):
    config: Dict[str, Any] = Field(default_factory=dict)


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


async def _get_user_task_or_404(task_id: str, user_id: str) -> Dict[str, Any]:
    task = await mongo_manager.find_one(
        TASK_COLLECTION,
        {"task_id": task_id, "user_id": user_id},
        projection={"_id": 0},
    )
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


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
        "created_at": now,
        "updated_at": now,
    }

    await mongo_manager.insert_one(TASK_COLLECTION, doc)
    return StrategyV2SceneTaskResponse(**doc)
