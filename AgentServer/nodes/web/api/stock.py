"""
股票 API
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, UTC
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel, Field

from core.managers import mongo_manager, data_source_manager
from nodes.data_sync.collectors.stock.basic import _add_financial_metrics
from nodes.data_sync.collectors.stock.daily_basic import _clean_daily_basic_record
from src.analysis.stock_chart_context import (
    build_period_candles,
    calculate_recent_return,
    get_stock_sector_context,
    serialize_daily_record,
)
from .auth import get_current_user_id


router = APIRouter()
_stock_repair_runtime_tasks: set[asyncio.Task] = set()
_DEFAULT_STOCK_REPAIR_START_DATE = "19900101"


# ==================== 模型 ====================


class StockBasic(BaseModel):
    """股票基础信息"""
    ts_code: str
    symbol: str
    name: str
    area: Optional[str]
    industry: Optional[str]
    market: Optional[str]
    list_date: Optional[str]


class StockDaily(BaseModel):
    """日线数据"""
    ts_code: str
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    pre_close: Optional[float]
    change: Optional[float]
    pct_chg: Optional[float]
    vol: Optional[float]
    amount: Optional[float]


class StockQuote(BaseModel):
    """股票行情"""
    ts_code: str
    name: str
    price: Optional[float]
    pct_chg: Optional[float]
    vol: Optional[float]
    amount: Optional[float]
    open: Optional[float]
    high: Optional[float]
    low: Optional[float]
    pre_close: Optional[float]


class StockReviewContextResponse(BaseModel):
    """个股详情沉浸上下文"""
    stock: Dict[str, Any]
    daily: List[Dict[str, Any]]
    weekly: List[Dict[str, Any]]
    monthly: List[Dict[str, Any]]


class RealtimeQuoteRequest(BaseModel):
    """实时行情请求"""
    ts_codes: List[str]


class StockRepairTaskStartResponse(BaseModel):
    """单股补数任务启动响应"""
    task_id: str
    status: str
    message: str


class StockRepairTaskStatus(BaseModel):
    """单股补数任务状态"""
    task_id: str
    task_type: str
    ts_code: str
    status: str
    progress: int = Field(default=0, ge=0, le=100)
    current_step: str = ""
    message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


def _normalize_ts_code(code: str) -> str:
    normalized = str(code or "").strip().upper()
    if "." in normalized:
        return normalized
    if normalized.startswith("6"):
        return f"{normalized}.SH"
    if normalized.startswith(("8", "4", "92")):
        return f"{normalized}.BJ"
    if normalized.startswith(("0", "3")):
        return f"{normalized}.SZ"
    return normalized


def _normalize_compact_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    digits = "".join(char for char in text if char.isdigit())
    if len(digits) != 8:
        return ""

    try:
        datetime.strptime(digits, "%Y%m%d")
    except ValueError:
        return ""
    return digits


def _merge_stock_basic_records(*records: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        for key, value in record.items():
            if value in (None, "", [], {}):
                continue
            merged[key] = value
    return merged


def _build_stock_repair_plan(
    list_date: str,
    list_date_source: str,
    existing_daily_start: Optional[str],
) -> Dict[str, Any]:
    normalized_list_date = _normalize_compact_date(list_date)
    normalized_existing_start = _normalize_compact_date(existing_daily_start)

    if normalized_list_date:
        start_date = normalized_list_date
        mode = "full_history_repair"
        start_date_reason = "resolved_list_date"
        start_date_reason_label = "已解析上市日期"
    else:
        start_date = _DEFAULT_STOCK_REPAIR_START_DATE
        mode = "full_history_repair"
        start_date_reason = "fallback_default_history_start"
        start_date_reason_label = f"缺少上市日期，回退到默认历史起点 {_DEFAULT_STOCK_REPAIR_START_DATE}"

    planned_to_extend_earlier = bool(
        normalized_existing_start and start_date < normalized_existing_start
    )

    return {
        "mode": mode,
        "mode_label": "完整补数" if mode == "full_history_repair" else "仅刷新已有区间",
        "start_date": start_date,
        "start_date_reason": start_date_reason,
        "start_date_reason_label": start_date_reason_label,
        "list_date_source": list_date_source or "unknown",
        "resolved_list_date": normalized_list_date or None,
        "existing_daily_start": normalized_existing_start or None,
        "planned_to_extend_earlier": planned_to_extend_earlier,
    }


async def _ensure_data_source_manager_ready() -> None:
    if not getattr(data_source_manager, "_initialized", False):
        await data_source_manager.initialize()


async def _update_stock_repair_task(task_id: str, **fields: Any) -> None:
    await mongo_manager.update_one("tasks", {"task_id": task_id}, {"$set": fields})


async def _get_single_stock_basic_record(
    ts_code: str,
    preferred_source: Optional[str] = None,
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    stock_basic_records, stock_basic_source = await data_source_manager.get_stock_basic(
        ts_code=ts_code,
        preferred_source=preferred_source,
    )
    stock_basic_record = next(
        (item for item in (stock_basic_records or []) if str(item.get("ts_code") or "").upper() == ts_code),
        None,
    )
    return stock_basic_record, stock_basic_source


async def _run_stock_repair_task(task_id: str, user_id: str, ts_code: str) -> None:
    started_at = datetime.now(UTC)
    warnings: List[str] = []

    async def step(progress: int, current_step: str, message: Optional[str] = None) -> None:
        payload: Dict[str, Any] = {
            "status": "running",
            "progress": progress,
            "current_step": current_step,
            "started_at": started_at,
        }
        if message:
            payload["message"] = message
        await _update_stock_repair_task(task_id, **payload)

    try:
        await step(5, "初始化数据源", "正在准备单股补数任务")
        await _ensure_data_source_manager_ready()

        normalized_ts_code = _normalize_ts_code(ts_code)
        existing_basic = await mongo_manager.find_one("stock_basic", {"ts_code": normalized_ts_code})
        existing_daily = await mongo_manager.find_many(
            "stock_daily",
            {"ts_code": normalized_ts_code},
            projection={"trade_date": 1, "_id": 0},
            sort=[("trade_date", 1)],
        )
        existing_daily_start = existing_daily[0]["trade_date"] if existing_daily else None
        existing_basic_count = 1 if existing_basic else 0
        existing_daily_count = len(existing_daily)
        existing_daily_basic_count = await mongo_manager.count("daily_basic", {"ts_code": normalized_ts_code})

        await step(15, "同步基础信息", "正在获取股票基础信息并优先补齐上市日期")
        stock_basic_record, stock_basic_source = await _get_single_stock_basic_record(
            normalized_ts_code,
            preferred_source="tushare",
        )
        stock_basic_doc = _merge_stock_basic_records(existing_basic, stock_basic_record)
        primary_list_date = _normalize_compact_date((stock_basic_record or {}).get("list_date"))
        existing_list_date = _normalize_compact_date((existing_basic or {}).get("list_date"))
        if primary_list_date:
            list_date = primary_list_date
            list_date_source = stock_basic_source or "primary_stock_basic"
        elif existing_list_date:
            list_date = existing_list_date
            list_date_source = "local_cache"
        else:
            list_date = ""
            list_date_source = "unknown"

        if not list_date and stock_basic_source != "tushare":
            tushare_stock_basic_record, tushare_stock_basic_source = await _get_single_stock_basic_record(
                normalized_ts_code,
                preferred_source="tushare",
            )
            stock_basic_doc = _merge_stock_basic_records(stock_basic_doc, tushare_stock_basic_record)
            tushare_list_date = _normalize_compact_date((tushare_stock_basic_record or {}).get("list_date"))
            if tushare_list_date:
                list_date = tushare_list_date
                list_date_source = tushare_stock_basic_source or "tushare"
                warnings.append("基础信息缺少上市日期，已额外通过 Tushare 补齐后执行完整补数")

        if not list_date:
            list_date_source = "default_history_start"
            warnings.append(
                f"基础信息缺少上市日期，已改用默认历史起点 {_DEFAULT_STOCK_REPAIR_START_DATE} 执行完整补数"
            )

        if not stock_basic_record:
            if not stock_basic_doc:
                raise ValueError(f"未找到 {normalized_ts_code} 的基础信息")

        await step(
            28,
            "更新上市日期",
            f"已确定历史补数起点 {list_date or _DEFAULT_STOCK_REPAIR_START_DATE}，正在写入基础信息",
        )
        latest_trade_date, latest_trade_source = await data_source_manager.get_latest_trade_date()
        repair_plan = _build_stock_repair_plan(
            list_date=list_date,
            list_date_source=list_date_source,
            existing_daily_start=existing_daily_start,
        )
        list_date = repair_plan["start_date"]
        end_date = str(latest_trade_date or datetime.now().strftime("%Y%m%d"))

        daily_basic_latest_record = None
        daily_basic_source = None
        if latest_trade_date:
            latest_basic_records, daily_basic_source = await data_source_manager.get_daily_basic(
                ts_code=normalized_ts_code,
                trade_date=latest_trade_date,
                preferred_source="tushare",
            )
            if latest_basic_records:
                daily_basic_latest_record = latest_basic_records[0]

        stock_basic_doc = dict(stock_basic_doc)
        if daily_basic_latest_record:
            _add_financial_metrics(stock_basic_doc, daily_basic_latest_record)
        stock_basic_doc["ts_code"] = normalized_ts_code
        if repair_plan["resolved_list_date"] and not _normalize_compact_date(stock_basic_doc.get("list_date")):
            stock_basic_doc["list_date"] = repair_plan["resolved_list_date"]
        await mongo_manager.bulk_upsert("stock_basic", [stock_basic_doc], key_fields=["ts_code"])

        await _update_stock_repair_task(
            task_id,
            stock_names=[{"ts_code": normalized_ts_code, "name": stock_basic_doc.get("name", normalized_ts_code)}],
            ts_codes=[normalized_ts_code],
        )

        await step(
            45,
            "同步日线数据",
            f"正在按{repair_plan['mode_label']}补充 {list_date} 到 {end_date} 的日线数据",
        )
        daily_records, daily_source = await data_source_manager.get_daily(
            ts_code=normalized_ts_code,
            start_date=list_date,
            end_date=end_date,
            preferred_source="baostock" if repair_plan["mode"] == "full_history_repair" else None,
        )
        if not daily_records:
            raise ValueError(f"未能获取 {normalized_ts_code} 的日线数据")

        for record in daily_records:
            record["ts_code"] = normalized_ts_code
        daily_upsert = await mongo_manager.bulk_upsert(
            "stock_daily",
            daily_records,
            key_fields=["ts_code", "trade_date"],
        )

        await step(80, "同步每日指标", "正在补充单股 daily_basic 数据")
        daily_basic_records, daily_basic_source_range = await data_source_manager.get_daily_basic(
            ts_code=normalized_ts_code,
            start_date=list_date,
            end_date=end_date,
            preferred_source="tushare",
        )
        cleaned_daily_basic_records: List[Dict[str, Any]] = []
        if daily_basic_records:
            for record in daily_basic_records:
                cleaned = _clean_daily_basic_record(record)
                cleaned["ts_code"] = normalized_ts_code
                if cleaned.get("trade_date"):
                    cleaned_daily_basic_records.append(cleaned)
        else:
            warnings.append("未拉取到单股 daily_basic，已完成基础信息与日线补数")

        daily_basic_upsert = {"matched": 0, "modified": 0, "upserted": 0, "total": 0}
        if cleaned_daily_basic_records:
            daily_basic_upsert = await mongo_manager.bulk_upsert(
                "daily_basic",
                cleaned_daily_basic_records,
                key_fields=["ts_code", "trade_date"],
            )

        refreshed_daily = await mongo_manager.find_many(
            "stock_daily",
            {"ts_code": normalized_ts_code},
            projection={"trade_date": 1, "_id": 0},
            sort=[("trade_date", 1)],
        )
        refreshed_daily_start = refreshed_daily[0]["trade_date"] if refreshed_daily else None
        refreshed_daily_end = refreshed_daily[-1]["trade_date"] if refreshed_daily else None
        refreshed_daily_basic_count = await mongo_manager.count("daily_basic", {"ts_code": normalized_ts_code})
        history_extended_earlier = bool(
            refreshed_daily_start and (
                not existing_daily_start or refreshed_daily_start < existing_daily_start
            )
        )

        if repair_plan["planned_to_extend_earlier"] and not history_extended_earlier:
            warnings.append("本次任务已尝试向更早历史补数，但本地最早日线未前移，数据源可能仍未返回更早区间")

        result = {
            "ts_code": normalized_ts_code,
            "date_range": {"start_date": list_date, "end_date": end_date},
            "repair_plan": repair_plan,
            "sources": {
                "stock_basic": stock_basic_source or "unknown",
                "list_date": repair_plan["list_date_source"],
                "latest_trade_date": latest_trade_source or "unknown",
                "stock_daily": daily_source or "unknown",
                "daily_basic": daily_basic_source_range or daily_basic_source or "unknown",
            },
            "counts": {
                "before": {
                    "stock_basic": existing_basic_count,
                    "stock_daily": existing_daily_count,
                    "daily_basic": existing_daily_basic_count,
                },
                "after": {
                    "stock_basic": 1,
                    "stock_daily": len(refreshed_daily),
                    "daily_basic": refreshed_daily_basic_count,
                },
                "upserted": {
                    "stock_daily": daily_upsert["upserted"],
                    "daily_basic": daily_basic_upsert["upserted"],
                },
                "modified": {
                    "stock_daily": daily_upsert["modified"],
                    "daily_basic": daily_basic_upsert["modified"],
                },
            },
            "coverage": {
                "stock_daily_start_before": existing_daily_start,
                "stock_daily_start": refreshed_daily_start,
                "stock_daily_end": refreshed_daily_end,
                "history_extended_earlier": history_extended_earlier,
            },
            "warnings": warnings,
        }

        await _update_stock_repair_task(
            task_id,
            status="completed",
            progress=100,
            current_step="完成",
            message="单股补数完成",
            completed_at=datetime.now(UTC),
            execution_time_ms=(datetime.now(UTC) - started_at).total_seconds() * 1000,
            result=result,
        )
    except Exception as exc:
        await _update_stock_repair_task(
            task_id,
            status="failed",
            progress=100,
            current_step="失败",
            message="单股补数失败",
            completed_at=datetime.now(UTC),
            execution_time_ms=(datetime.now(UTC) - started_at).total_seconds() * 1000,
            error_message=str(exc),
        )
    finally:
        current = asyncio.current_task()
        if current in _stock_repair_runtime_tasks:
            _stock_repair_runtime_tasks.discard(current)


# ==================== API 端点 ====================


@router.get("/search", response_model=List[StockBasic])
async def search_stocks(
    keyword: str = Query(..., min_length=1),
    limit: int = Query(default=20, le=50),
):
    """搜索股票"""
    # 支持代码或名称搜索
    filter_query = {
        "$or": [
            {"ts_code": {"$regex": keyword.upper(), "$options": "i"}},
            {"symbol": {"$regex": keyword, "$options": "i"}},
            {"name": {"$regex": keyword, "$options": "i"}},
        ]
    }
    
    stocks = await mongo_manager.find_many(
        "stock_basic",
        filter_query,
        limit=limit,
    )
    
    return [
        StockBasic(
            ts_code=s["ts_code"],
            symbol=s.get("symbol", ""),
            name=s.get("name", ""),
            area=s.get("area"),
            industry=s.get("industry"),
            market=s.get("market"),
            list_date=s.get("list_date"),
        )
        for s in stocks
    ]


@router.get("/{ts_code}/basic", response_model=StockBasic)
async def get_stock_basic(ts_code: str):
    """获取股票基础信息"""
    stock = await mongo_manager.find_one(
        "stock_basic",
        {"ts_code": ts_code.upper()},
    )
    
    if not stock:
        raise HTTPException(status_code=404, detail="股票不存在")
    
    return StockBasic(
        ts_code=stock["ts_code"],
        symbol=stock.get("symbol", ""),
        name=stock.get("name", ""),
        area=stock.get("area"),
        industry=stock.get("industry"),
        market=stock.get("market"),
        list_date=stock.get("list_date"),
    )


@router.get("/{ts_code}/review-context", response_model=StockReviewContextResponse)
async def get_stock_review_context(ts_code: str):
    """获取个股详情页所需的 K 线与扩展上下文"""
    normalized_ts_code = _normalize_ts_code(ts_code)
    stock = await mongo_manager.find_one(
        "stock_basic",
        {"ts_code": normalized_ts_code},
    )
    if not stock:
        raise HTTPException(status_code=404, detail="股票不存在")

    daily_records = await mongo_manager.find_many(
        "stock_daily",
        {"ts_code": normalized_ts_code},
        sort=[("trade_date", 1)],
        limit=5000,
    )
    if not daily_records:
        raise HTTPException(status_code=404, detail="该股票本地日线数据不完整，请先补充数据")

    daily = [serialize_daily_record(item) for item in daily_records]
    weekly = build_period_candles(daily_records, "weekly")
    monthly = build_period_candles(daily_records, "monthly")
    recent_30d_pct_chg = calculate_recent_return(daily_records, days=30)
    sector_context = await get_stock_sector_context(normalized_ts_code)
    latest_record = daily_records[-1]

    return StockReviewContextResponse(
        stock={
            "ts_code": normalized_ts_code,
            "symbol": stock.get("symbol", ""),
            "name": stock.get("name", normalized_ts_code),
            "area": stock.get("area"),
            "industry": stock.get("industry"),
            "market": stock.get("market"),
            "list_date": stock.get("list_date"),
            "latest_trade_date": latest_record.get("trade_date"),
            "latest_price": latest_record.get("close"),
            "latest_pct_chg": latest_record.get("pct_chg"),
            "recent_30d_pct_chg": recent_30d_pct_chg,
            "concepts": sector_context.get("concepts", []),
            "sectors": sector_context.get("sectors", []),
        },
        daily=daily,
        weekly=weekly,
        monthly=monthly,
    )


@router.post("/{ts_code}/repair-sync", response_model=StockRepairTaskStartResponse)
async def create_stock_repair_task(
    ts_code: str,
    user_id: str = Depends(get_current_user_id),
):
    """发起单股数据补充/更新任务"""
    normalized_ts_code = _normalize_ts_code(ts_code)

    existing_task = await mongo_manager.find_one(
        "tasks",
        {
            "user_id": user_id,
            "task_type": "stock_data_repair",
            "status": {"$in": ["pending", "queued", "running"]},
            "ts_codes": normalized_ts_code,
        },
        sort=[("created_at", -1)],
    )
    if existing_task:
        return StockRepairTaskStartResponse(
            task_id=existing_task["task_id"],
            status=existing_task["status"],
            message=f"{normalized_ts_code} 已有进行中的补数任务",
        )

    task_id = uuid.uuid4().hex
    now = datetime.now(UTC)
    await mongo_manager.insert_one(
        "tasks",
        {
            "task_id": task_id,
            "trace_id": uuid.uuid4().hex,
            "task_type": "stock_data_repair",
            "status": "queued",
            "progress": 0,
            "current_step": "排队中",
            "message": "单股补数任务已创建",
            "ts_codes": [normalized_ts_code],
            "stock_names": [{"ts_code": normalized_ts_code, "name": normalized_ts_code}],
            "query": None,
            "params": {"mode": "full_refresh"},
            "user_id": user_id,
            "node_id": "web",
            "started_at": None,
            "completed_at": None,
            "result": None,
            "error_message": None,
            "execution_time_ms": 0,
            "created_at": now,
        },
    )

    task = asyncio.create_task(_run_stock_repair_task(task_id, user_id, normalized_ts_code))
    _stock_repair_runtime_tasks.add(task)

    return StockRepairTaskStartResponse(
        task_id=task_id,
        status="queued",
        message=f"已开始为 {normalized_ts_code} 异步补充本地数据",
    )


@router.get("/repair-tasks/{task_id}", response_model=StockRepairTaskStatus)
async def get_stock_repair_task_status(
    task_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """获取单股补数任务状态"""
    task = await mongo_manager.find_one(
        "tasks",
        {"task_id": task_id, "user_id": user_id, "task_type": "stock_data_repair"},
    )
    if not task:
        raise HTTPException(status_code=404, detail="补数任务不存在")

    ts_codes = task.get("ts_codes", [])
    return StockRepairTaskStatus(
        task_id=task["task_id"],
        task_type=task.get("task_type", "stock_data_repair"),
        ts_code=(ts_codes[0] if ts_codes else ""),
        status=task.get("status", "queued"),
        progress=int(task.get("progress", 0) or 0),
        current_step=task.get("current_step", ""),
        message=task.get("message"),
        created_at=task["created_at"],
        started_at=task.get("started_at"),
        completed_at=task.get("completed_at"),
        result=task.get("result"),
        error_message=task.get("error_message"),
    )


@router.get("/{ts_code}/daily", response_model=List[StockDaily])
async def get_stock_daily(
    ts_code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = Query(default=100, le=500),
):
    """获取日线数据"""
    filter_query = {"ts_code": ts_code.upper()}
    
    if start_date:
        filter_query["trade_date"] = {"$gte": start_date}
    if end_date:
        filter_query.setdefault("trade_date", {})["$lte"] = end_date
    
    records = await mongo_manager.find_many(
        "stock_daily",
        filter_query,
        sort=[("trade_date", -1)],
        limit=limit,
    )
    
    return [
        StockDaily(
            ts_code=r["ts_code"],
            trade_date=r["trade_date"],
            open=r.get("open", 0),
            high=r.get("high", 0),
            low=r.get("low", 0),
            close=r.get("close", 0),
            pre_close=r.get("pre_close"),
            change=r.get("change"),
            pct_chg=r.get("pct_chg"),
            vol=r.get("vol"),
            amount=r.get("amount"),
        )
        for r in records
    ]


@router.post("/realtime", response_model=List[StockQuote])
async def get_realtime_quotes(body: RealtimeQuoteRequest):
    """获取实时行情（从最新日线数据获取）"""
    if not body.ts_codes:
        return []
    
    # 规范化股票代码
    ts_codes = [code.upper() for code in body.ts_codes]
    
    # 获取股票基本信息
    stocks = await mongo_manager.find_many(
        "stock_basic",
        {"ts_code": {"$in": ts_codes}},
    )
    stock_map = {s["ts_code"]: s for s in stocks}
    
    # 获取最新日线数据
    result = []
    for ts_code in ts_codes:
        stock = stock_map.get(ts_code, {})
        
        # 获取该股票最新的日线数据
        daily = await mongo_manager.find_one(
            "stock_daily",
            {"ts_code": ts_code},
            sort=[("trade_date", -1)],
        )
        
        result.append(StockQuote(
            ts_code=ts_code,
            name=stock.get("name", ts_code),
            price=daily.get("close") if daily else None,
            pct_chg=daily.get("pct_chg") if daily else None,
            vol=daily.get("vol") if daily else None,
            amount=daily.get("amount") if daily else None,
            open=daily.get("open") if daily else None,
            high=daily.get("high") if daily else None,
            low=daily.get("low") if daily else None,
            pre_close=daily.get("pre_close") if daily else None,
        ))
    
    return result


@router.get("/industries", response_model=List[str])
async def get_industries():
    """获取行业列表"""
    industries = await mongo_manager.aggregate(
        "stock_basic",
        [
            {"$match": {"list_status": "L", "industry": {"$ne": None}}},
            {"$group": {"_id": "$industry"}},
            {"$sort": {"_id": 1}},
        ],
    )
    
    return [i["_id"] for i in industries if i["_id"]]


@router.get("/by-industry/{industry}", response_model=List[StockBasic])
async def get_stocks_by_industry(
    industry: str,
    limit: int = Query(default=50, le=100),
):
    """按行业获取股票"""
    stocks = await mongo_manager.find_many(
        "stock_basic",
        {"industry": industry, "list_status": "L"},
        limit=limit,
    )
    
    return [
        StockBasic(
            ts_code=s["ts_code"],
            symbol=s.get("symbol", ""),
            name=s.get("name", ""),
            area=s.get("area"),
            industry=s.get("industry"),
            market=s.get("market"),
            list_date=s.get("list_date"),
        )
        for s in stocks
    ]
