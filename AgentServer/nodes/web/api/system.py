"""系统能力巡检 API。"""

from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.diagnostics import (
    build_automation_overview,
    build_capability_audit,
    build_capability_overview,
    build_capability_section,
    build_coze_plugin_status,
)
from .auth import get_current_user_id
from .system_sync import create_manual_gap_fill_task, get_manual_gap_fill_task


router = APIRouter()


class ManualGapFillRequest(BaseModel):
    """手动补漏同步请求。"""

    lookback_days: int = Field(default=3, ge=1, le=10)


class ManualGapFillTaskResponse(BaseModel):
    """手动补漏同步任务状态。"""

    task_id: str
    task_type: str
    status: str
    progress: int = Field(default=0, ge=0, le=100)
    current_step: str = ""
    message: Optional[str] = None
    params: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


def _serialize_manual_sync_task(task: Dict[str, Any]) -> ManualGapFillTaskResponse:
    return ManualGapFillTaskResponse(
        task_id=task["task_id"],
        task_type=task.get("task_type", "system_gap_fill_sync"),
        status=task.get("status", "queued"),
        progress=int(task.get("progress", 0) or 0),
        current_step=task.get("current_step", ""),
        message=task.get("message"),
        params=task.get("params") or {},
        created_at=task["created_at"],
        started_at=task.get("started_at"),
        completed_at=task.get("completed_at"),
        result=task.get("result"),
        error_message=task.get("error_message"),
    )


@router.get("/status")
async def get_system_status(_user_id: str = Depends(get_current_user_id)):
    """返回当前项目接口与能力状态。"""
    return await build_capability_audit()


@router.get("/status/overview")
async def get_system_status_overview(
    force_refresh: bool = Query(False),
    _user_id: str = Depends(get_current_user_id),
):
    """返回状态页轻量概览。"""
    return await build_capability_overview(force_refresh=force_refresh)


@router.get("/status/sections/{section}")
async def get_system_status_section(
    section: str,
    force_refresh: bool = Query(False),
    _user_id: str = Depends(get_current_user_id),
):
    """按区块返回状态页内容。"""
    try:
        return await build_capability_section(section, force_refresh=force_refresh)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/status/coze")
async def get_coze_plugin_status(
    force_refresh: bool = Query(False),
    _user_id: str = Depends(get_current_user_id),
):
    """返回 Coze 全量插件探测状态，便于单独重复刷新。"""
    return await build_coze_plugin_status(force_refresh=force_refresh)


@router.get("/automations")
async def get_automation_overview(_user_id: str = Depends(get_current_user_id)):
    """返回项目内已启用和预留的自动任务/自动流程总览。"""
    return await build_automation_overview()


@router.post("/manual-sync/gap-fill", response_model=ManualGapFillTaskResponse)
async def start_manual_gap_fill_sync(
    body: ManualGapFillRequest,
    user_id: str = Depends(get_current_user_id),
):
    """手动触发最近交易日轻量补漏同步。"""
    task = await create_manual_gap_fill_task(user_id=user_id, lookback_days=body.lookback_days)
    return _serialize_manual_sync_task(task)


@router.get("/manual-sync/latest", response_model=ManualGapFillTaskResponse)
async def get_latest_manual_gap_fill_sync(
    user_id: str = Depends(get_current_user_id),
):
    """获取最近一次手动补漏同步任务。"""
    task = await get_manual_gap_fill_task(user_id=user_id)
    if not task:
        raise HTTPException(status_code=404, detail="暂无补漏同步任务")
    return _serialize_manual_sync_task(task)


@router.get("/manual-sync/tasks/{task_id}", response_model=ManualGapFillTaskResponse)
async def get_manual_gap_fill_sync_task(
    task_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """获取指定手动补漏同步任务状态。"""
    task = await get_manual_gap_fill_task(user_id=user_id, task_id=task_id)
    if not task:
        raise HTTPException(status_code=404, detail="补漏同步任务不存在")
    return _serialize_manual_sync_task(task)
