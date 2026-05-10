"""
一句话选股与最小股池 API。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel, Field

from core.managers import mongo_manager
from src.analysis.stock_picker import stock_picker_service
from .auth import get_current_user_id


router = APIRouter(prefix="/stock-picker", tags=["Stock Picker"])

AUTO_REMOVE_CANDIDATE_POOL_TYPE = "候选池"
AUTO_REMOVE_CANDIDATE_SOURCE_MODULE = "one_line_picker"
AUTO_REMOVE_AFTER_TRADE_DAYS = 5


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


def _parse_added_at(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _format_trade_date_from_datetime(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%d")


def _is_auto_remove_candidate_pool(pool: Dict[str, Any]) -> bool:
    return str(pool.get("pool_type") or "").strip() == AUTO_REMOVE_CANDIDATE_POOL_TYPE


def _is_auto_remove_candidate_stock(stock: Dict[str, Any]) -> bool:
    return str(stock.get("source_module") or "").strip() == AUTO_REMOVE_CANDIDATE_SOURCE_MODULE


async def _get_local_latest_trade_date() -> Optional[str]:
    latest_index = await mongo_manager.find_one(
        "index_daily",
        {"ts_code": "000001.SH"},
        sort=[("trade_date", -1)],
        projection={"trade_date": 1, "_id": 0},
    )
    latest_trade_date = str(latest_index.get("trade_date") or "").strip() if latest_index else ""
    return latest_trade_date or None


async def _get_local_trade_dates(start_date: str, end_date: str) -> List[str]:
    if not start_date or not end_date or start_date > end_date:
        return []
    records = await mongo_manager.find_many(
        "index_daily",
        {
            "ts_code": "000001.SH",
            "trade_date": {"$gte": start_date, "$lte": end_date},
        },
        sort=[("trade_date", 1)],
        projection={"trade_date": 1, "_id": 0},
    )
    return sorted(
        {
            str(item.get("trade_date") or "").strip()
            for item in records
            if str(item.get("trade_date") or "").strip()
        }
    )


def _count_trade_days_since_added(
    added_trade_date: str,
    latest_trade_date: str,
    trade_dates: List[str],
) -> int:
    return len([trade_date for trade_date in trade_dates if added_trade_date <= trade_date <= latest_trade_date])


async def _cleanup_candidate_pool_expired_stocks(
    pool: Dict[str, Any],
    latest_trade_date: Optional[str],
    trade_dates: List[str],
) -> Dict[str, Any]:
    if not _is_auto_remove_candidate_pool(pool):
        return dict(pool)

    if not latest_trade_date or not trade_dates:
        return dict(pool)

    existing_stocks = list(pool.get("stocks", []) or [])
    kept_stocks: List[Dict[str, Any]] = []
    removed_any = False

    for stock in existing_stocks:
        stock_dict = dict(stock)
        if not _is_auto_remove_candidate_stock(stock_dict):
            kept_stocks.append(stock_dict)
            continue

        added_at = _parse_added_at(stock_dict.get("added_at"))
        if not added_at:
            kept_stocks.append(stock_dict)
            continue

        added_trade_date = _format_trade_date_from_datetime(added_at)
        if added_trade_date > latest_trade_date:
            kept_stocks.append(stock_dict)
            continue

        trade_day_count = _count_trade_days_since_added(added_trade_date, latest_trade_date, trade_dates)
        if trade_day_count > AUTO_REMOVE_AFTER_TRADE_DAYS:
            removed_any = True
            continue

        kept_stocks.append(stock_dict)

    if not removed_any:
        return dict(pool)

    updated_pool = dict(pool)
    updated_pool["stocks"] = kept_stocks
    updated_pool["updated_at"] = datetime.now(UTC)

    await mongo_manager.update_one(
        "stock_pools",
        {"pool_id": pool.get("pool_id"), "user_id": pool.get("user_id")},
        {
            "$set": {
                "stocks": kept_stocks,
                "updated_at": updated_pool["updated_at"],
            }
        },
    )
    return updated_pool


async def _cleanup_candidate_pools(pools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidate_pools = [pool for pool in pools if _is_auto_remove_candidate_pool(pool)]
    if not candidate_pools:
        return [dict(pool) for pool in pools]

    earliest_added_trade_date: Optional[str] = None
    for pool in candidate_pools:
        for stock in list(pool.get("stocks", []) or []):
            if not _is_auto_remove_candidate_stock(stock):
                continue
            added_at = _parse_added_at(stock.get("added_at"))
            if not added_at:
                continue
            added_trade_date = _format_trade_date_from_datetime(added_at)
            if earliest_added_trade_date is None or added_trade_date < earliest_added_trade_date:
                earliest_added_trade_date = added_trade_date

    if earliest_added_trade_date is None:
        return [dict(pool) for pool in pools]

    latest_trade_date = await _get_local_latest_trade_date()
    if not latest_trade_date or earliest_added_trade_date > latest_trade_date:
        return [dict(pool) for pool in pools]

    trade_dates = await _get_local_trade_dates(earliest_added_trade_date, latest_trade_date)
    if not trade_dates:
        return [dict(pool) for pool in pools]

    cleaned_pools: List[Dict[str, Any]] = []
    for pool in pools:
        cleaned_pools.append(
            await _cleanup_candidate_pool_expired_stocks(
                pool=pool,
                latest_trade_date=latest_trade_date,
                trade_dates=trade_dates,
            )
        )
    return cleaned_pools


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


def _parse_trade_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y%m%d")
    except Exception:
        return None


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _build_period_candles(records: List[Dict[str, Any]], period: str) -> List[Dict[str, Any]]:
    if period not in {"weekly", "monthly"}:
        return [_serialize_daily_record(item) for item in records]

    grouped: List[Dict[str, Any]] = []
    current_key: Optional[str] = None
    bucket: List[Dict[str, Any]] = []

    for record in records:
        trade_dt = _parse_trade_date(record.get("trade_date"))
        if not trade_dt:
            continue

        if period == "weekly":
            iso_year, iso_week, _ = trade_dt.isocalendar()
            bucket_key = f"{iso_year}-W{iso_week:02d}"
        else:
            bucket_key = trade_dt.strftime("%Y-%m")

        if current_key is None:
            current_key = bucket_key

        if bucket_key != current_key:
            if bucket:
                grouped.append(bucket)
            bucket = []
            current_key = bucket_key

        bucket.append(record)

    if bucket:
        grouped.append(bucket)

    aggregated: List[Dict[str, Any]] = []
    previous_close: Optional[float] = None

    for bucket_records in grouped:
        first_record = bucket_records[0]
        last_record = bucket_records[-1]
        open_price = _safe_float(first_record.get("open")) or 0.0
        close_price = _safe_float(last_record.get("close")) or 0.0
        low_values = [_safe_float(item.get("low")) for item in bucket_records]
        high_values = [_safe_float(item.get("high")) for item in bucket_records]
        low_price = min([item for item in low_values if item is not None], default=open_price)
        high_price = max([item for item in high_values if item is not None], default=close_price)
        volume = sum((_safe_float(item.get("vol")) or 0.0) for item in bucket_records)
        amount = sum((_safe_float(item.get("amount")) or 0.0) for item in bucket_records)

        bucket_pre_close = previous_close
        if bucket_pre_close is None:
            bucket_pre_close = _safe_float(first_record.get("pre_close"))

        change = close_price - bucket_pre_close if bucket_pre_close else None
        pct_chg = ((close_price / bucket_pre_close) - 1) * 100 if bucket_pre_close else None

        aggregated.append(
            {
                "ts_code": first_record.get("ts_code"),
                "trade_date": last_record.get("trade_date"),
                "open": round(open_price, 4),
                "high": round(high_price, 4),
                "low": round(low_price, 4),
                "close": round(close_price, 4),
                "pre_close": round(bucket_pre_close, 4) if bucket_pre_close is not None else None,
                "change": round(change, 4) if change is not None else None,
                "pct_chg": round(pct_chg, 4) if pct_chg is not None else None,
                "vol": round(volume, 4),
                "amount": round(amount, 4),
            }
        )
        previous_close = close_price

    return aggregated


def _calculate_recent_return(records: List[Dict[str, Any]], days: int = 30) -> Optional[float]:
    if len(records) < 2:
        return None

    latest_record = records[-1]
    latest_date = _parse_trade_date(latest_record.get("trade_date"))
    latest_close = _safe_float(latest_record.get("close"))
    if not latest_date or latest_close is None or latest_close <= 0:
        return None

    target_date = latest_date - timedelta(days=days)
    base_record = next(
        (item for item in records if (_parse_trade_date(item.get("trade_date")) or latest_date) >= target_date),
        records[0],
    )
    if base_record.get("trade_date") == latest_record.get("trade_date") and len(records) >= 2:
        base_record = records[-2]

    base_close = _safe_float(base_record.get("close"))
    if base_close is None or base_close <= 0:
        return None

    return round(((latest_close / base_close) - 1) * 100, 2)


async def _get_stock_sector_context(ts_code: str) -> Dict[str, List[Dict[str, Any]]]:
    stock_code = str(ts_code or "").split(".")[0]
    if not stock_code:
        return {"concepts": [], "sectors": []}

    mapping_doc = await mongo_manager.find_one(
        "stock_sector_map",
        {"code": stock_code},
        projection={"sectors": 1, "_id": 0},
    )
    sectors = list(mapping_doc.get("sectors", []) or []) if mapping_doc else []
    if not sectors:
        return {"concepts": [], "sectors": []}

    sector_codes = [str(item.get("ts_code") or "").strip() for item in sectors if str(item.get("ts_code") or "").strip()]
    meta_records = await mongo_manager.find_many(
        "ths_sectors",
        {"ts_code": {"$in": sector_codes}},
        projection={"ts_code": 1, "name": 1, "sector_type": 1, "type_name": 1, "_id": 0},
    )
    meta_map = {str(item.get("ts_code") or ""): item for item in meta_records}

    all_sectors: List[Dict[str, Any]] = []
    concepts: List[Dict[str, Any]] = []
    for sector in sectors:
        sector_code = str(sector.get("ts_code") or "").strip()
        if not sector_code:
            continue
        meta = meta_map.get(sector_code, {})
        item = {
            "ts_code": sector_code,
            "name": sector.get("name") or meta.get("name") or sector_code,
            "sector_type": meta.get("sector_type"),
            "type_name": meta.get("type_name"),
        }
        all_sectors.append(item)
        if item["sector_type"] == "N":
            concepts.append(item)

    return {
        "concepts": concepts[:12],
        "sectors": all_sectors[:20],
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
    pools = await _cleanup_candidate_pools([dict(pool) for pool in pools])
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
    pool = (await _cleanup_candidate_pools([dict(pool)]))[0]
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
    pool = (await _cleanup_candidate_pools([dict(pool)]))[0]

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
    weekly = _build_period_candles(daily_records, "weekly")
    monthly = _build_period_candles(daily_records, "monthly")
    recent_30d_pct_chg = _calculate_recent_return(daily_records, days=30)
    sector_context = await _get_stock_sector_context(normalized_ts_code)

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
            "recent_30d_pct_chg": recent_30d_pct_chg,
            "concepts": sector_context.get("concepts", []),
            "sectors": sector_context.get("sectors", []),
        },
        "daily": daily,
        "weekly": weekly,
        "monthly": monthly,
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
    pool = (await _cleanup_candidate_pools([dict(pool)]))[0]

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
    pool = (await _cleanup_candidate_pools([dict(pool)]))[0]

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
