"""
一句话选股与最小股池 API。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.managers import mongo_manager
from src.analysis.stock_picker import stock_picker_service
from .auth import get_current_user_id


router = APIRouter(prefix="/stock-picker", tags=["Stock Picker"])


class StockPickerQueryRequest(BaseModel):
    input: str = Field(..., min_length=1, description="一句话选股条件")


class PoolStockItem(BaseModel):
    ts_code: str
    code: str
    name: Optional[str] = None


class StockPoolCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    pool_type: str = Field(..., min_length=1, max_length=30)
    description: Optional[str] = Field(default=None, max_length=200)


class StockPoolAddRequest(BaseModel):
    stocks: List[PoolStockItem]
    source_run_id: Optional[str] = None
    source_query: Optional[str] = None
    source_module: str = "one_line_picker"


def _pool_summary(pool: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "pool_id": pool.get("pool_id"),
        "name": pool.get("name"),
        "pool_type": pool.get("pool_type"),
        "description": pool.get("description"),
        "stock_count": len(pool.get("stocks", [])),
        "updated_at": pool.get("updated_at"),
    }


@router.post("/query")
async def query_stock_picker(
    body: StockPickerQueryRequest,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    return await stock_picker_service.query(body.input.strip(), user_id=user_id)


@router.get("/pools")
async def list_stock_pools(user_id: str = Depends(get_current_user_id)) -> Dict[str, Any]:
    pools = await mongo_manager.find_many(
        "stock_pools",
        {"user_id": user_id},
        sort=[("updated_at", -1)],
    )
    return {"items": [_pool_summary(pool) for pool in pools]}


@router.get("/pools/{pool_id}")
async def get_stock_pool_detail(
    pool_id: str,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    pool = await mongo_manager.find_one("stock_pools", {"pool_id": pool_id, "user_id": user_id})
    if not pool:
        raise HTTPException(status_code=404, detail="股池不存在")
    return {
        **_pool_summary(pool),
        "stocks": pool.get("stocks", []),
        "source_module": pool.get("source_module"),
        "created_at": pool.get("created_at"),
    }


@router.post("/pools")
async def create_stock_pool(
    body: StockPoolCreateRequest,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    pool_id = uuid.uuid4().hex
    record = {
        "pool_id": pool_id,
        "user_id": user_id,
        "name": body.name.strip(),
        "pool_type": body.pool_type.strip(),
        "description": body.description.strip() if body.description else None,
        "stocks": [],
        "source_module": "one_line_picker",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    await mongo_manager.update_one(
        "stock_pools",
        {"pool_id": pool_id},
        {"$set": record},
        upsert=True,
    )
    return _pool_summary(record)


@router.post("/pools/{pool_id}/stocks")
async def add_stocks_to_pool(
    pool_id: str,
    body: StockPoolAddRequest,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    if not body.stocks:
        raise HTTPException(status_code=400, detail="至少选择一只股票")

    pool = await mongo_manager.find_one("stock_pools", {"pool_id": pool_id, "user_id": user_id})
    if not pool:
        raise HTTPException(status_code=404, detail="股池不存在")

    existing = {
        str(item.get("ts_code")): item
        for item in pool.get("stocks", [])
        if item.get("ts_code")
    }
    added = 0

    for stock in body.stocks:
        if stock.ts_code in existing:
            continue
        existing[stock.ts_code] = {
            "ts_code": stock.ts_code,
            "code": stock.code,
            "name": stock.name or "",
            "status": "active",
            "source_module": body.source_module,
            "source_run_id": body.source_run_id,
            "source_query": body.source_query,
            "added_at": datetime.now(UTC),
        }
        added += 1

    await mongo_manager.update_one(
        "stock_pools",
        {"pool_id": pool_id, "user_id": user_id},
        {
            "$set": {
                "stocks": list(existing.values()),
                "updated_at": datetime.now(UTC),
            }
        },
    )

    updated_pool = await mongo_manager.find_one("stock_pools", {"pool_id": pool_id, "user_id": user_id})
    return {
        "message": f"已加入 {added} 只股票",
        "added": added,
        "pool": _pool_summary(updated_pool or pool),
    }
