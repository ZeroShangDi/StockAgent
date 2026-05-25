"""
股票图表上下文辅助工具。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from core.managers import mongo_manager


def serialize_daily_record(record: Dict[str, Any]) -> Dict[str, Any]:
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


def parse_trade_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y%m%d")
    except Exception:
        return None


def safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def build_period_candles(records: List[Dict[str, Any]], period: str) -> List[Dict[str, Any]]:
    if period not in {"weekly", "monthly"}:
        return [serialize_daily_record(item) for item in records]

    grouped: List[List[Dict[str, Any]]] = []
    current_key: Optional[str] = None
    bucket: List[Dict[str, Any]] = []

    for record in records:
        trade_dt = parse_trade_date(record.get("trade_date"))
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
        open_price = safe_float(first_record.get("open")) or 0.0
        close_price = safe_float(last_record.get("close")) or 0.0
        low_values = [safe_float(item.get("low")) for item in bucket_records]
        high_values = [safe_float(item.get("high")) for item in bucket_records]
        low_price = min([item for item in low_values if item is not None], default=open_price)
        high_price = max([item for item in high_values if item is not None], default=close_price)
        volume = sum((safe_float(item.get("vol")) or 0.0) for item in bucket_records)
        amount = sum((safe_float(item.get("amount")) or 0.0) for item in bucket_records)

        bucket_pre_close = previous_close
        if bucket_pre_close is None:
            bucket_pre_close = safe_float(first_record.get("pre_close"))

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


def calculate_recent_return(records: List[Dict[str, Any]], days: int = 30) -> Optional[float]:
    if len(records) < 2:
        return None

    latest_record = records[-1]
    latest_date = parse_trade_date(latest_record.get("trade_date"))
    latest_close = safe_float(latest_record.get("close"))
    if not latest_date or latest_close is None or latest_close <= 0:
        return None

    target_date = latest_date - timedelta(days=days)
    base_record = next(
        (item for item in records if (parse_trade_date(item.get("trade_date")) or latest_date) >= target_date),
        records[0],
    )
    if base_record.get("trade_date") == latest_record.get("trade_date") and len(records) >= 2:
        base_record = records[-2]

    base_close = safe_float(base_record.get("close"))
    if base_close is None or base_close <= 0:
        return None

    return round(((latest_close / base_close) - 1) * 100, 2)


async def get_stock_sector_context(ts_code: str) -> Dict[str, List[Dict[str, Any]]]:
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
        limit=len(sector_codes),
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
