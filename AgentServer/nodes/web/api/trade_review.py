"""
交割单复盘 API。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from src.analysis.trade_review import trade_review_service
from .auth import get_current_user_id


router = APIRouter(prefix="/trade-review", tags=["Trade Review"])


class TradeReviewGroupCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    description: Optional[str] = Field(default=None, max_length=200)


class TradeReviewReasonsPayload(BaseModel):
    verdict: str = ""
    reasons: List[str] = Field(default_factory=list)


class TradeReviewUpdateRequest(BaseModel):
    operation_reason: str = ""
    mindset: str = ""
    market_context: str = ""
    result_reasons: TradeReviewReasonsPayload = Field(default_factory=TradeReviewReasonsPayload)


@router.get("/groups")
async def list_trade_review_groups(user_id: str = Depends(get_current_user_id)) -> Dict[str, Any]:
    return {"items": await trade_review_service.list_groups(user_id)}


@router.post("/groups")
async def create_trade_review_group(
    body: TradeReviewGroupCreateRequest,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    return await trade_review_service.create_group(user_id, body.name, body.description)


@router.get("/groups/{group_id}")
async def get_trade_review_group(
    group_id: str,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    group = await trade_review_service.get_group(user_id, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="交割单分组不存在")
    return group


@router.post("/groups/{group_id}/import")
async def import_trade_review_csv(
    group_id: str,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    filename = file.filename or "trade-review.csv"
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="当前只支持导入 CSV 文件")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")

    try:
        return await trade_review_service.import_csv(
            user_id=user_id,
            group_id=group_id,
            filename=filename,
            content=content,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/groups/{group_id}/records")
async def list_trade_review_records(
    group_id: str,
    category: str = Query(default="trade"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    keyword: Optional[str] = Query(default=None),
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    return await trade_review_service.list_records(
        user_id=user_id,
        group_id=group_id,
        category=category,
        skip=skip,
        limit=limit,
        keyword=keyword,
    )


@router.patch("/records/{record_id}")
async def update_trade_review_record(
    record_id: str,
    body: TradeReviewUpdateRequest,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    try:
        return await trade_review_service.update_review(
            user_id=user_id,
            record_id=record_id,
            operation_reason=body.operation_reason,
            mindset=body.mindset,
            market_context=body.market_context,
            result_reasons=body.result_reasons.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/groups/{group_id}/stats")
async def get_trade_review_stats(
    group_id: str,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    return await trade_review_service.get_stats(user_id=user_id, group_id=group_id)


@router.get("/groups/{group_id}/positions")
async def get_trade_review_positions(
    group_id: str,
    force_refresh: bool = Query(default=False),
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    try:
        return await trade_review_service.get_positions(
            user_id=user_id,
            group_id=group_id,
            force_refresh=force_refresh,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/groups/{group_id}/positions/rebuild")
async def rebuild_trade_review_positions(
    group_id: str,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    try:
        return await trade_review_service.rebuild_positions(user_id=user_id, group_id=group_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/records/{record_id}/kline")
async def get_trade_review_kline_context(
    record_id: str,
    window: int = Query(default=50, ge=10, le=250),
    category: str = Query(default="trade"),
    keyword: Optional[str] = Query(default=None),
    anchor_record_id: Optional[str] = Query(default=None),
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    try:
        return await trade_review_service.get_kline_context(
            user_id=user_id,
            record_id=record_id,
            window=window,
            category=category,
            keyword=keyword,
            anchor_record_id=anchor_record_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
