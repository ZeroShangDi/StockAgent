"""系统能力巡检 API。"""

from fastapi import APIRouter, Depends, HTTPException, Query

from src.diagnostics import build_capability_audit, build_capability_overview, build_capability_section
from .auth import get_current_user_id


router = APIRouter()


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
