"""Strategy V2 API skeleton."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

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
