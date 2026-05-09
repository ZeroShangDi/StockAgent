"""
一句话选股与最小股池 API。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Body
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
    source_pool_name: Optional[str] = None


class StockPoolRemoveRequest(BaseModel):
    ts_codes: List[str] = Field(..., min_length=1, description="待移除的股票代码列表")


def _pool_summary(pool: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "pool_id": pool.get("pool_id"),
        "name": pool.get("name"),
        "pool_type": pool.get("pool_type"),
        "description": pool.get("description"),
        "stock_count": len(pool.get("stocks", [])),
        "avg_pct_chg": pool.get("avg_pct_chg"),
        "latest_trade_date": pool.get("latest_trade_date"),
        "updated_at": pool.get("updated_at"),
    }


async def _get_latest_daily_map(ts_codes: List[str]) -> Dict[str, Dict[str, Any]]:
    normalized_codes = [str(code or "").strip().upper() for code in ts_codes if str(code or "").strip()]
    if not normalized_codes:
        return {}

    records = await mongo_manager.aggregate(
        "stock_daily",
        [
            {"$match": {"ts_code": {"$in": normalized_codes}}},
            {"$sort": {"ts_code": 1, "trade_date": -1}},
            {
                "$group": {
                    "_id": "$ts_code",
                    "trade_date": {"$first": "$trade_date"},
                    "close": {"$first": "$close"},
                    "pct_chg": {"$first": "$pct_chg"},
                    "pre_close": {"$first": "$pre_close"},
                }
            },
        ],
    )
    return {str(item["_id"]).upper(): item for item in records if item.get("_id")}


async def _get_stock_basic_map(ts_codes: List[str]) -> Dict[str, Dict[str, Any]]:
    normalized_codes = [str(code or "").strip().upper() for code in ts_codes if str(code or "").strip()]
    if not normalized_codes:
        return {}
    records = await mongo_manager.find_many(
        "stock_basic",
        {"ts_code": {"$in": normalized_codes}},
        projection={"ts_code": 1, "name": 1, "industry": 1, "market": 1, "list_date": 1},
    )
    return {str(item["ts_code"]).upper(): item for item in records if item.get("ts_code")}


def _enrich_pool(pool: Dict[str, Any], latest_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    stocks = list(pool.get("stocks", []) or [])
    pct_values: List[float] = []
    latest_trade_date = ""

    for stock in stocks:
        ts_code = str(stock.get("ts_code") or "").strip().upper()
        latest = latest_map.get(ts_code)
        if not latest:
            stock["latest_pct_chg"] = None
            stock["latest_price"] = None
            stock["latest_trade_date"] = None
            continue

        stock["latest_pct_chg"] = latest.get("pct_chg")
        stock["latest_price"] = latest.get("close")
        stock["latest_trade_date"] = latest.get("trade_date")
        pct = latest.get("pct_chg")
        if isinstance(pct, (int, float)):
            pct_values.append(float(pct))
        trade_date = str(latest.get("trade_date") or "")
        if trade_date and trade_date > latest_trade_date:
            latest_trade_date = trade_date

    pool["stocks"] = stocks
    pool["avg_pct_chg"] = round(sum(pct_values) / len(pct_values), 4) if pct_values else None
    pool["latest_trade_date"] = latest_trade_date or None
    return pool


def _serialize_daily_record(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ts_code": record.get("ts_code"),
        "trade_date": record.get("trade_date"),
        "open": record.get("open"),
        "high": record.get("high"),
        "low": record.get("low"),
        "close": record.get("close"),
        "pre_close": record.get("pre_close"),
        "change": record.get("change"),
        "pct_chg": record.get("pct_chg"),
        "vol": record.get("vol"),
        "amount": record.get("amount"),
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
    all_codes = [
        str(item.get("ts_code") or "").strip().upper()
        for pool in pools
        for item in (pool.get("stocks", []) or [])
        if str(item.get("ts_code") or "").strip()
    ]
    latest_map = await _get_latest_daily_map(all_codes)
    enriched = [_enrich_pool(dict(pool), latest_map) for pool in pools]
    return {"items": [_pool_summary(pool) for pool in enriched]}


@router.get("/pools/{pool_id}")
async def get_stock_pool_detail(
    pool_id: str,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    pool = await mongo_manager.find_one("stock_pools", {"pool_id": pool_id, "user_id": user_id})
    if not pool:
        raise HTTPException(status_code=404, detail="股池不存在")
    latest_map = await _get_latest_daily_map([item.get("ts_code") for item in (pool.get("stocks", []) or [])])
    enriched = _enrich_pool(dict(pool), latest_map)
    return {
        **_pool_summary(enriched),
        "stocks": enriched.get("stocks", []),
        "source_module": enriched.get("source_module"),
        "created_at": enriched.get("created_at"),
    }


@router.get("/pools/{pool_id}/review/{ts_code}")
async def get_stock_pool_review_context(
    pool_id: str,
    ts_code: str,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    normalized_ts_code = ts_code.strip().upper()
    pool = await mongo_manager.find_one("stock_pools", {"pool_id": pool_id, "user_id": user_id})
    if not pool:
        raise HTTPException(status_code=404, detail="股池不存在")

    stocks = list(pool.get("stocks", []) or [])
    selected = next((item for item in stocks if str(item.get("ts_code") or "").upper() == normalized_ts_code), None)
    if not selected:
        raise HTTPException(status_code=404, detail="该股票不在当前股池中")

    latest_map = await _get_latest_daily_map([item.get("ts_code") for item in stocks])
    basic_map = await _get_stock_basic_map([item.get("ts_code") for item in stocks])
    enriched_pool = _enrich_pool(dict(pool), latest_map)

    daily_records = await mongo_manager.find_many(
        "stock_daily",
        {"ts_code": normalized_ts_code},
        sort=[("trade_date", 1)],
        limit=5000,
    )
    if not daily_records:
        raise HTTPException(status_code=404, detail="该股票本地日线数据不完整，请先补充数据")
    daily = [_serialize_daily_record(item) for item in daily_records]

    related_stocks: List[Dict[str, Any]] = []
    for item in enriched_pool.get("stocks", []):
        item_ts_code = str(item.get("ts_code") or "").strip().upper()
        related_stocks.append(
            {
                "ts_code": item_ts_code,
                "code": item.get("code") or item_ts_code.split(".")[0],
                "name": item.get("name") or basic_map.get(item_ts_code, {}).get("name") or item_ts_code,
                "status": item.get("status"),
                "source_module": item.get("source_module"),
                "source_query": item.get("source_query"),
                "source_pool_name": item.get("source_pool_name"),
                "latest_pct_chg": item.get("latest_pct_chg"),
                "latest_price": item.get("latest_price"),
                "latest_trade_date": item.get("latest_trade_date"),
                "is_current": item_ts_code == normalized_ts_code,
            }
        )

    current_index = next(
        (index for index, item in enumerate(related_stocks) if item["ts_code"] == normalized_ts_code),
        0,
    )

    basic_info = basic_map.get(normalized_ts_code, {})
    selected_latest = latest_map.get(normalized_ts_code, {})
    return {
        "pool": _pool_summary(enriched_pool),
        "stock": {
            "ts_code": normalized_ts_code,
            "code": selected.get("code") or normalized_ts_code.split(".")[0],
            "name": selected.get("name") or basic_info.get("name") or normalized_ts_code,
            "status": selected.get("status"),
            "source_module": selected.get("source_module"),
            "source_query": selected.get("source_query"),
            "source_pool_name": selected.get("source_pool_name"),
            "latest_pct_chg": selected_latest.get("pct_chg"),
            "latest_price": selected_latest.get("close"),
            "latest_trade_date": selected_latest.get("trade_date"),
            "industry": basic_info.get("industry"),
            "market": basic_info.get("market"),
            "list_date": basic_info.get("list_date"),
            "added_at": selected.get("added_at"),
        },
        "daily": daily,
        "related_stocks": related_stocks,
        "navigation": {
            "position": current_index + 1,
            "total": len(related_stocks),
            "previous_ts_code": related_stocks[current_index - 1]["ts_code"] if current_index > 0 else None,
            "next_ts_code": related_stocks[current_index + 1]["ts_code"] if current_index < len(related_stocks) - 1 else None,
        },
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
            "source_pool_name": body.source_pool_name,
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


@router.delete("/pools/{pool_id}")
async def delete_stock_pool(
    pool_id: str,
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    pool = await mongo_manager.find_one("stock_pools", {"pool_id": pool_id, "user_id": user_id})
    if not pool:
        raise HTTPException(status_code=404, detail="股池不存在")

    await mongo_manager.delete_one("stock_pools", {"pool_id": pool_id, "user_id": user_id})
    return {
        "message": f"已删除股池 {pool.get('name', pool_id)}",
        "pool_id": pool_id,
    }


@router.delete("/pools/{pool_id}/stocks")
async def remove_stocks_from_pool(
    pool_id: str,
    body: StockPoolRemoveRequest = Body(...),
    user_id: str = Depends(get_current_user_id),
) -> Dict[str, Any]:
    pool = await mongo_manager.find_one("stock_pools", {"pool_id": pool_id, "user_id": user_id})
    if not pool:
        raise HTTPException(status_code=404, detail="股池不存在")

    if not body.ts_codes:
        raise HTTPException(status_code=400, detail="至少选择一只股票")

    remove_set = {str(code or "").strip().upper() for code in body.ts_codes if str(code or "").strip()}
    existing_stocks = pool.get("stocks", [])
    filtered_stocks = [item for item in existing_stocks if str(item.get("ts_code", "")).upper() not in remove_set]
    removed = len(existing_stocks) - len(filtered_stocks)

    await mongo_manager.update_one(
        "stock_pools",
        {"pool_id": pool_id, "user_id": user_id},
        {
            "$set": {
                "stocks": filtered_stocks,
                "updated_at": datetime.now(UTC),
            }
        },
    )

    updated_pool = await mongo_manager.find_one("stock_pools", {"pool_id": pool_id, "user_id": user_id})
    return {
        "message": f"已移除 {removed} 只股票",
        "removed": removed,
        "pool": _pool_summary(updated_pool or pool),
    }
