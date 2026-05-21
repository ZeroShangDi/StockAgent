"""
市场分析 API

提供大盘行情分析数据接口

数据源策略:
- 18:00 前 (交易时段/盘后整理中): 使用 Redis 中的实时数据
- 18:00 后 (DataSync 完成后): 使用 MongoDB 中的历史数据
- 指数数据从 index_daily 表获取
- 涨跌统计从 daily_stats 表获取
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta, date
from collections import defaultdict

from core.managers import mongo_manager, theme_manager, redis_manager
from .auth import require_admin, CurrentUser

router = APIRouter(prefix="/market", tags=["Market Analysis"])

# 数据源切换时间点 (18:00)
DATA_SOURCE_SWITCH_HOUR = 18
PERIOD_DAY_MAP = {
    "1w": 5,
    "1m": 22,
    "3m": 66,
    "1y": 250,
}

PERIOD_LABEL_MAP = {
    "1w": "近一周",
    "1m": "近一个月",
    "3m": "近三个月",
    "1y": "近一年",
}


def _safe_float(val, default: float = 0.0) -> float:
    """安全转换为浮点数"""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _normalize_trade_date_input(trade_date: Optional[str]) -> Optional[str]:
    if not trade_date:
        return None
    text = str(trade_date).strip()
    if not text:
        return None
    if "-" in text:
        return text.replace("-", "")
    return text


def _display_trade_date(trade_date: Optional[str]) -> str:
    text = str(trade_date or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def _safe_percent(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator * 100, 1)


def _resolve_period_days(period: str) -> int:
    return PERIOD_DAY_MAP.get(period, PERIOD_DAY_MAP["1m"])


def _resolve_period_trade_dates(trade_dates: List[str], latest_trade_date: str, period: str) -> List[str]:
    if not trade_dates:
        return []
    latest = latest_trade_date or trade_dates[-1]
    if latest not in trade_dates:
        latest = trade_dates[-1]
    latest_index = trade_dates.index(latest)
    days = _resolve_period_days(period)
    start_index = max(0, latest_index - days + 1)
    return trade_dates[start_index: latest_index + 1]


def _resolve_limit_type(limit_doc: Dict[str, Any]) -> str:
    first_time = str(limit_doc.get("first_time") or "")
    last_time = str(limit_doc.get("last_time") or "")
    open_times = int(limit_doc.get("open_times") or 0)
    turnover_ratio = _safe_float(limit_doc.get("turnover_ratio"), 0.0)
    if first_time in {"092500", "093000"} and open_times == 0:
        return "一字板"
    if open_times >= 2:
        return "回封板"
    if last_time and last_time >= "144500":
        return "尾盘板"
    if first_time and first_time <= "093500" and open_times > 0:
        return "T字板"
    if turnover_ratio >= 8 or open_times > 0:
        return "换手板"
    return "换手板"


def _format_limit_time(raw_value: Any) -> str:
    text = str(raw_value or "").strip()
    if len(text) == 6 and text.isdigit():
        return f"{text[:2]}:{text[2:4]}"
    if len(text) == 4 and text.isdigit():
        return f"{text[:2]}:{text[2:4]}"
    return text or "--:--"


def _resolve_theme_name(doc: Dict[str, Any]) -> str:
    return str(doc.get("industry") or doc.get("theme") or doc.get("market") or "未分类")


def _resolve_merged_theme_name(primary: Dict[str, Any], fallback: Dict[str, Any]) -> str:
    return str(
        primary.get("industry")
        or primary.get("theme")
        or fallback.get("industry")
        or fallback.get("theme")
        or primary.get("market")
        or fallback.get("market")
        or "未分类"
    )


def _board_group_label(board_count: int) -> str:
    if board_count >= 7:
        return "7板+"
    if board_count <= 1:
        return "首板"
    return f"{board_count}板"


async def _get_market_trade_dates(limit: int = 260) -> List[str]:
    docs = await mongo_manager.find_many(
        "daily_stats",
        {},
        projection={"trade_date": 1, "_id": 0},
        sort=[("trade_date", -1)],
        limit=limit,
    )
    dates = [str(item.get("trade_date") or "") for item in docs if item.get("trade_date")]
    unique = sorted(set(filter(None, dates)))
    return unique


async def _get_index_trade_dates(limit: int = 260) -> List[str]:
    docs = await mongo_manager.find_many(
        "index_daily",
        {},
        projection={"trade_date": 1, "_id": 0},
        sort=[("trade_date", -1)],
        limit=max(limit * 8, 400),
    )
    dates = [str(item.get("trade_date") or "") for item in docs if item.get("trade_date")]
    unique = sorted(set(filter(None, dates)))
    return unique[-limit:]


def _build_period_coverage_warning(trade_dates: List[str], period: str, source_label: str) -> List[str]:
    expected_days = _resolve_period_days(period)
    if len(trade_dates) >= expected_days:
        return []
    if period == "1w":
        return []
    period_label = PERIOD_LABEL_MAP.get(period, period)
    return [
        f"{source_label} 当前仅覆盖 {len(trade_dates)} 个交易日，{period_label} 统计暂按现有数据展示"
    ]


async def _get_stock_meta_map(ts_codes: List[str]) -> Dict[str, Dict[str, Any]]:
    if not ts_codes:
        return {}
    docs = await mongo_manager.find_many(
        "stock_basic",
        {"ts_code": {"$in": ts_codes}},
        projection={"ts_code": 1, "symbol": 1, "name": 1, "industry": 1, "market": 1, "_id": 0},
    )
    return {str(doc.get("ts_code")): doc for doc in docs if doc.get("ts_code")}


async def _scan_stock_period_metrics(start_date: str, end_date: str) -> List[Dict[str, Any]]:
    pipeline = [
        {"$match": {"trade_date": {"$gte": start_date, "$lte": end_date}}},
        {"$sort": {"ts_code": 1, "trade_date": 1}},
        {"$project": {"ts_code": 1, "trade_date": 1, "open": 1, "close": 1, "low": 1}},
        {"$group": {
            "_id": "$ts_code",
            "first_close": {"$first": "$close"},
            "first_open": {"$first": "$open"},
            "last_close": {"$last": "$close"},
            "items": {"$push": {"low": "$low", "trade_date": "$trade_date"}},
        }},
        {"$addFields": {
            "min_low_item": {
                "$reduce": {
                    "input": "$items",
                    "initialValue": {"low": 999999, "trade_date": ""},
                    "in": {
                        "$cond": [
                            {"$lt": ["$$this.low", "$$value.low"]},
                            "$$this",
                            "$$value"
                        ]
                    }
                }
            }
        }},
        {"$project": {
            "_id": 0,
            "ts_code": "$_id",
            "first_close": 1,
            "first_open": 1,
            "last_close": 1,
            "min_low": "$min_low_item.low",
            "min_low_date": "$min_low_item.trade_date",
        }},
    ]

    raw = await mongo_manager.aggregate("stock_daily", pipeline)

    results: List[Dict[str, Any]] = []
    for doc in raw:
        ts_code = str(doc.get("ts_code") or "")
        first_close = _safe_float(doc.get("first_close"), 0.0)
        last_close = _safe_float(doc.get("last_close"), 0.0)
        min_low = _safe_float(doc.get("min_low"), float("inf"))
        min_low_date = str(doc.get("min_low_date") or "")

        if not ts_code or first_close <= 0 or last_close <= 0 or min_low >= 999998:
            continue

        results.append({
            "ts_code": ts_code,
            "start_price": round(first_close, 2),
            "current_price": round(last_close, 2),
            "lowest_price": round(min_low, 2),
            "lowest_date": min_low_date,
            "gain_pct": round((last_close - first_close) / first_close * 100, 2),
            "max_drawdown_pct": round((min_low - first_close) / first_close * 100, 2),
            "rebound_pct": round((last_close - min_low) / min_low * 100, 2) if min_low > 0 else 0.0,
        })

    return results


async def _build_stage_gain_rankings(start_date: str, end_date: str) -> List[Dict[str, Any]]:
    metrics = await _scan_stock_period_metrics(start_date, end_date)
    metrics = [item for item in metrics if item["gain_pct"] >= 20]
    metrics.sort(key=lambda item: item["gain_pct"], reverse=True)
    top_metrics = metrics[:30]
    meta_map = await _get_stock_meta_map([item["ts_code"] for item in top_metrics])

    result = []
    for index, item in enumerate(top_metrics, start=1):
        meta = meta_map.get(item["ts_code"], {})
        result.append({
            "rank": index,
            "ts_code": item["ts_code"],
            "code": meta.get("symbol") or item["ts_code"].split(".")[0],
            "name": meta.get("name") or item["ts_code"],
            "theme": _resolve_theme_name(meta),
            "start_price": item["start_price"],
            "current_price": item["current_price"],
            "gain_pct": item["gain_pct"],
            "max_drawdown_pct": item["max_drawdown_pct"],
        })
    return result


async def _build_rebound_rankings(start_date: str, end_date: str, period_label: str) -> List[Dict[str, Any]]:
    metrics = await _scan_stock_period_metrics(start_date, end_date)
    metrics.sort(key=lambda item: item["rebound_pct"], reverse=True)
    top_metrics = metrics[:30]
    meta_map = await _get_stock_meta_map([item["ts_code"] for item in top_metrics])

    result = []
    for index, item in enumerate(top_metrics, start=1):
        meta = meta_map.get(item["ts_code"], {})
        result.append({
            "rank": index,
            "ts_code": item["ts_code"],
            "code": meta.get("symbol") or item["ts_code"].split(".")[0],
            "name": meta.get("name") or item["ts_code"],
            "lowest_date": _display_trade_date(item["lowest_date"]),
            "lowest_price": item["lowest_price"],
            "current_price": item["current_price"],
            "rebound_pct": item["rebound_pct"],
            "period_low_label": f"{_display_trade_date(start_date)} 起始 · {period_label}",
        })
    return result


async def _build_nextday_win_rate(start_date: str, end_date: str) -> List[Dict[str, Any]]:
    pipeline = [
        {"$match": {"trade_date": {"$gte": start_date, "$lte": end_date}}},
        {"$sort": {"ts_code": 1, "trade_date": 1}},
        {"$group": {
            "_id": "$ts_code",
            "trade_days": {"$sum": 1},
            "up_days": {"$sum": {"$cond": [{"$gt": ["$pct_chg", 0]}, 1, 0]}},
            "returns": {"$push": "$pct_chg"},
        }},
    ]

    raw = await mongo_manager.aggregate("stock_daily", pipeline)

    period_stats: Dict[str, Dict[str, Any]] = {}
    for doc in raw:
        ts_code = str(doc.get("_id") or "")
        if not ts_code:
            continue
        returns = doc.get("returns", []) or []
        period_stats[ts_code] = {
            "trade_days": int(doc.get("trade_days") or 0),
            "up_days": int(doc.get("up_days") or 0),
            "returns": returns,
        }

    meta_map = await _get_stock_meta_map(list(period_stats.keys()))
    rows = []
    for ts_code, stat in period_stats.items():
        if stat["trade_days"] <= 0:
            continue
        meta = meta_map.get(ts_code, {})
        avg_return = round(sum(stat["returns"]) / len(stat["returns"]), 2) if stat["returns"] else 0.0
        rows.append({
            "ts_code": ts_code,
            "code": meta.get("symbol") or ts_code.split(".")[0],
            "name": meta.get("name") or ts_code,
            "theme": _resolve_theme_name(meta),
            "trade_days": stat["trade_days"],
            "up_days": stat["up_days"],
            "win_rate": _safe_percent(stat["up_days"], stat["trade_days"]),
            "avg_return": avg_return,
        })

    rows.sort(key=lambda item: (item["win_rate"], item["avg_return"], item["trade_days"]), reverse=True)
    return [{
        "rank": index,
        **item,
    } for index, item in enumerate(rows[:30], start=1)]


async def _build_streak_rankings(start_date: str, end_date: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    pipeline = [
        {"$match": {"trade_date": {"$gte": start_date, "$lte": end_date}}},
        {"$sort": {"ts_code": 1, "trade_date": 1}},
        {"$group": {
            "_id": "$ts_code",
            "points": {"$push": {"trade_date": "$trade_date", "pct_chg": "$pct_chg"}},
        }},
    ]

    raw = await mongo_manager.aggregate("stock_daily", pipeline)

    best_up: Dict[str, Dict[str, Any]] = {}
    best_down: Dict[str, Dict[str, Any]] = {}

    for doc in raw:
        ts_code = str(doc.get("_id") or "")
        if not ts_code:
            continue
        points = doc.get("points", []) or []

        up_streak = 0
        up_start = ""
        down_streak = 0
        down_start = ""

        for point in points:
            trade_date = str(point.get("trade_date") or "")
            pct_chg = _safe_float(point.get("pct_chg"), 0.0)

            if pct_chg > 0:
                if up_streak == 0:
                    up_start = trade_date
                up_streak += 1
                if up_streak > best_up.get(ts_code, {}).get("days", 0):
                    best_up[ts_code] = {"days": up_streak, "start": up_start, "end": trade_date}
                down_streak = 0
                down_start = ""
            elif pct_chg < 0:
                if down_streak == 0:
                    down_start = trade_date
                down_streak += 1
                if down_streak > best_down.get(ts_code, {}).get("days", 0):
                    best_down[ts_code] = {"days": down_streak, "start": down_start, "end": trade_date}
                up_streak = 0
                up_start = ""
            else:
                up_streak = 0
                up_start = ""
                down_streak = 0
                down_start = ""

    involved_ts_codes = list(set(best_up.keys()) | set(best_down.keys()))
    meta_map = await _get_stock_meta_map(involved_ts_codes)

    def build_rows(source: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        rows = []
        for ts_code, info in source.items():
            meta = meta_map.get(ts_code, {})
            rows.append({
                "ts_code": ts_code,
                "code": meta.get("symbol") or ts_code.split(".")[0],
                "name": meta.get("name") or ts_code,
                "theme": _resolve_theme_name(meta),
                "days": int(info.get("days") or 0),
                "date_range": f"{_display_trade_date(info.get('start'))} 至 {_display_trade_date(info.get('end'))}",
            })
        rows.sort(key=lambda item: item["days"], reverse=True)
        return [{
            "rank": index,
            **item,
        } for index, item in enumerate(rows[:30], start=1)]

    return build_rows(best_up), build_rows(best_down)


def _should_use_realtime_data() -> bool:
    """
    判断是否应该使用实时数据 (Redis)
    
    18:00 前使用 Redis 实时数据
    18:00 后使用 MongoDB 历史数据
    """
    now = datetime.now()
    return now.hour < DATA_SOURCE_SWITCH_HOUR


async def _get_index_data_from_mongodb(trade_date: Optional[str] = None) -> Dict[str, Any]:
    """
    从 MongoDB 的 index_daily 表获取指数数据
    
    Args:
        trade_date: 交易日期，不传则取最新
        
    Returns:
        {"sh_index": ..., "sh_change": ..., "sz_index": ..., ...}
    """
    result = {
        "sh_index": 0, "sh_change": 0,
        "sz_index": 0, "sz_change": 0,
        "cyb_index": 0, "cyb_change": 0,
    }
    
    # 指数代码映射
    index_map = {
        "000001.SH": ("sh_index", "sh_change"),
        "399001.SZ": ("sz_index", "sz_change"),
        "399006.SZ": ("cyb_index", "cyb_change"),
    }
    
    for ts_code, (index_key, change_key) in index_map.items():
        query = {"ts_code": ts_code}
        if trade_date:
            query["trade_date"] = trade_date
        
        index_data = await mongo_manager.find_one(
            "index_daily",
            query,
            sort=[("trade_date", -1)],
        )
        
        if index_data:
            result[index_key] = _safe_float(index_data.get("close", 0))
            result[change_key] = _safe_float(index_data.get("pct_chg", 0))
    
    return result


@router.get("/overview")
async def get_market_overview(
    trade_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    获取大盘概览数据
    
    数据源策略:
    - 18:00 前: 使用 Redis 中的实时数据 (Listener 节点更新)
    - 18:00 后: 使用 MongoDB 中的历史数据
    - 指数数据: index_daily 表
    - 涨跌统计: daily_stats 表
    
    Args:
        trade_date: 交易日期，不传则取最新
    
    Returns:
        大盘指数、涨跌统计、资金流向等概览数据
    """
    # 如果指定了历史日期，直接从 MongoDB 获取
    today_str = date.today().strftime("%Y%m%d")
    use_realtime = _should_use_realtime_data() and (not trade_date or trade_date == today_str)
    
    # 尝试从 Redis 获取实时数据 (18:00 前)
    if use_realtime:
        realtime_data = await redis_manager.get_realtime_market_data()
        if realtime_data:
            # 获取热门板块（仍从 MongoDB 获取）
            hot_sectors = await _get_hot_sectors(today_str)
            
            return {
                "trade_date": today_str,
                "sh_index": _safe_float(realtime_data.get("sh_index", 0)),
                "sh_change": _safe_float(realtime_data.get("sh_change", 0)),
                "sz_index": _safe_float(realtime_data.get("sz_index", 0)),
                "sz_change": _safe_float(realtime_data.get("sz_change", 0)),
                "cyb_index": _safe_float(realtime_data.get("cyb_index", 0)),
                "cyb_change": _safe_float(realtime_data.get("cyb_change", 0)),
                "up_count": realtime_data.get("up_count", 0),
                "down_count": realtime_data.get("down_count", 0),
                "flat_count": realtime_data.get("flat_count", 0),
                "limit_up": realtime_data.get("limit_up", 0),
                "limit_down": realtime_data.get("limit_down", 0),
                "total_amount": 0,  # 实时数据暂无
                "north_money": 0,   # 实时数据暂无
                "hot_sectors": hot_sectors,
                "data_source": "realtime",
                "update_time": realtime_data.get("update_time", ""),
            }
    
    # 从 MongoDB 获取历史数据 (18:00 后或无实时数据)
    return await _get_market_overview_from_mongodb(trade_date)


@router.get("/realtime/snapshot")
async def get_realtime_market_snapshot() -> Dict[str, Any]:
    """获取 Listener 生成的分层实时快照。"""
    snapshot = await redis_manager.get_realtime_market_layered_snapshot()
    if not snapshot:
        raise HTTPException(status_code=404, detail="No realtime layered snapshot available")
    return snapshot


@router.get("/realtime/deltas")
async def get_realtime_market_deltas(
    limit: int = Query(default=20, ge=1, le=100, description="最近增量事件数量"),
) -> Dict[str, Any]:
    """获取最近的实时市场增量事件流。"""
    latest = await redis_manager.get_realtime_market_delta()
    events = await redis_manager.get_recent_realtime_market_deltas(limit=limit)
    return {
        "latest": latest,
        "events": events,
        "count": len(events),
    }


async def _get_hot_sectors(trade_date: str) -> List[str]:
    """获取热门板块"""
    hot_sectors_data = await mongo_manager.find_many(
        "sector_ranking",
        {"trade_date": trade_date, "ranking_type": "industry_top"},
        sort=[("rank", 1)],
        limit=5,
        projection={"name": 1, "_id": 0},
    )
    return [s.get("name", "") for s in hot_sectors_data if s.get("name")]


async def _get_market_overview_from_mongodb(trade_date: Optional[str] = None) -> Dict[str, Any]:
    """
    从 MongoDB 获取大盘概览数据
    
    指数数据从 index_daily 表获取
    涨跌统计从 daily_stats 表获取
    """
    # 构建查询条件
    query = {}
    if trade_date:
        query["trade_date"] = trade_date
    
    # 获取 daily_stats (涨跌统计)
    stats = await mongo_manager.find_one(
        "daily_stats",
        query,
        sort=[("trade_date", -1)],
    )
    
    # 确定交易日期
    actual_trade_date = stats.get("trade_date", "") if stats else trade_date or ""
    
    # 获取指数数据 (从 index_daily 表)
    index_data = await _get_index_data_from_mongodb(actual_trade_date)
    
    if not stats:
        # 只有指数数据，没有统计数据
        return {
            "trade_date": actual_trade_date,
            **index_data,
            "up_count": 0,
            "down_count": 0,
            "flat_count": 0,
            "limit_up": 0,
            "limit_down": 0,
            "total_amount": 0,
            "north_money": 0,
            "hot_sectors": [],
            "data_source": "mongodb",
        }
    
    # 获取热门板块
    hot_sectors = await _get_hot_sectors(stats.get("trade_date", ""))
    
    # 构建响应
    return {
        "trade_date": stats.get("trade_date", ""),
        **index_data,  # 指数数据从 index_daily 表获取
        "up_count": stats.get("up_count", 0),
        "down_count": stats.get("down_count", 0),
        "flat_count": stats.get("flat_count", 0),
        "limit_up": stats.get("limit_up_count", 0),
        "limit_down": stats.get("limit_down_count", 0),
        "total_amount": _safe_float(stats.get("total_amount", 0)),
        "north_money": _safe_float(stats.get("north_money", 0)),
        "hot_sectors": hot_sectors,
        "data_source": "mongodb",
    }


@router.get("/latest")
async def get_latest_market_data() -> Dict[str, Any]:
    """
    获取最新市场分析数据
    
    Returns:
        包含评分、周期、统计数据的完整市场分析
    """
    # 获取最新的 daily_stats
    latest_stats = await mongo_manager.find_one(
        "daily_stats",
        {},
        sort=[("trade_date", -1)],
    )
    
    if not latest_stats:
        raise HTTPException(status_code=404, detail="No market data available")
    
    trade_date = latest_stats.get("trade_date", "")
    
    # 获取最新的 market_analysis
    latest_analysis = await mongo_manager.find_one(
        "market_analysis",
        {"trade_date": trade_date},
    )
    
    # 构建响应 - 使用 EMA 平滑后的情绪分数保持一致
    sentiment_ema = latest_analysis.get("sentiment_score_ema") if latest_analysis else None
    sentiment_raw = latest_analysis.get("sentiment_score", 0) if latest_analysis else 0
    sentiment = sentiment_ema if sentiment_ema is not None else sentiment_raw
    
    # total_amount 存储单位是千元
    total_amount = _safe_float(latest_stats.get("total_amount", 0))
    
    response = {
        "trade_date": trade_date,
        "scores": {
            "sentiment": sentiment,
            "strength": latest_analysis.get("strength_score", 0) if latest_analysis else 0,
        },
        "cycle": latest_analysis.get("cycle", "unknown") if latest_analysis else "unknown",
        "cycle_name": latest_analysis.get("cycle_name", "") if latest_analysis else "",
        "cycle_reason": latest_analysis.get("cycle_reason", "") if latest_analysis else "",
        "stats": {
            "up_count": latest_stats.get("up_count", 0),
            "down_count": latest_stats.get("down_count", 0),
            "flat_count": latest_stats.get("flat_count", 0),
            "total_stocks": latest_stats.get("total_stocks", 0),
            "up_ratio": latest_stats.get("up_ratio", 0),
            "down_ratio": latest_stats.get("down_ratio", 0),
            "limit_up_count": latest_stats.get("limit_up_count", 0),
            "limit_down_count": latest_stats.get("limit_down_count", 0),
            "broken_limit_count": latest_stats.get("broken_limit_count", 0),
            "max_limit_height": latest_stats.get("max_limit_height", 0),
            "limit_1": latest_stats.get("limit_1", 0),
            "limit_2": latest_stats.get("limit_2", 0),
            "limit_3": latest_stats.get("limit_3", 0),
            "limit_4": latest_stats.get("limit_4", 0),
            "limit_5": latest_stats.get("limit_5", 0),
            "limit_6_plus": latest_stats.get("limit_6_plus", 0),
            "total_limit_up": latest_stats.get("total_limit_up", 0),
            "total_amount": total_amount,  # 保持千元单位，前端处理显示
            "sh_amount": _safe_float(latest_stats.get("sh_amount", 0)),
            "sz_amount": _safe_float(latest_stats.get("sz_amount", 0)),
            "north_money": _safe_float(latest_stats.get("north_money", 0)),  # 保持原单位
            "hgt": latest_stats.get("hgt"),
            "sgt": latest_stats.get("sgt"),
        },
    }
    
    return response


@router.get("/history")
async def get_market_history(
    days: int = Query(default=30, ge=1, le=90, description="历史天数"),
) -> Dict[str, Any]:
    """
    获取市场历史数据 (用于趋势图)
    
    Args:
        days: 查询天数 (默认30天)
    
    Returns:
        历史统计和分析数据列表
    """
    # 获取历史 daily_stats
    stats_list = await mongo_manager.find_many(
        "daily_stats",
        {},
        sort=[("trade_date", -1)],
        limit=days,
    )
    
    if not stats_list:
        return {"history": []}
    
    # 获取对应的 market_analysis
    trade_dates = [s.get("trade_date") for s in stats_list]
    analysis_list = await mongo_manager.find_many(
        "market_analysis",
        {"trade_date": {"$in": trade_dates}},
    )
    
    # 构建分析数据映射
    analysis_map = {a.get("trade_date"): a for a in analysis_list}
    
    # 组装历史数据
    history = []
    for stats in stats_list:
        trade_date = stats.get("trade_date", "")
        analysis = analysis_map.get(trade_date, {})
        
        history.append({
            "trade_date": trade_date,
            "sentiment_score": analysis.get("sentiment_score", 0),
            "sentiment_score_ema": analysis.get("sentiment_score_ema", analysis.get("sentiment_score", 0)),
            "strength_score": analysis.get("strength_score", 0),
            "strength_diff": analysis.get("strength_diff", 0),
            "v_ratio": analysis.get("v_ratio", 1.0),
            "cycle": analysis.get("cycle", "unknown"),
            "cycle_name": analysis.get("cycle_name", ""),
            "up_count": stats.get("up_count", 0),
            "down_count": stats.get("down_count", 0),
            "up_ratio": stats.get("up_ratio", 0),
            "limit_up_count": stats.get("limit_up_count", 0),
            "limit_down_count": stats.get("limit_down_count", 0),
            "broken_limit_count": stats.get("broken_limit_count", 0),
            "max_limit_height": stats.get("max_limit_height", 0),
            "limit_1": stats.get("limit_1", 0),
            "limit_2": stats.get("limit_2", 0),
            "limit_3": stats.get("limit_3", 0),
            "limit_4": stats.get("limit_4", 0),
            "limit_5": stats.get("limit_5", 0),
            "limit_6_plus": stats.get("limit_6_plus", 0),
            "total_amount": _safe_float(stats.get("total_amount", 0)),  # 保持千元单位
            "north_money": _safe_float(stats.get("north_money", 0)),  # 保持百万元单位
        })
    
    # 按日期正序排列 (图表需要从早到晚)
    history.reverse()
    
    return {"history": history}


@router.get("/sector-ranking")
async def get_sector_ranking(
    trade_date: Optional[str] = None,
    ranking_type: str = Query(default="industry_top", description="排名类型: industry_top, concept_top"),
    days: int = Query(default=1, ge=1, le=30, description="获取天数"),
) -> Dict[str, Any]:
    """
    获取板块排名数据（从预计算的 sector_ranking 表直接读取）
    
    Args:
        trade_date: 交易日期 (不传则取最新)
        ranking_type: 排名类型 (industry_top, concept_top)
        days: 获取天数 (默认1天，最多30天)
    
    Returns:
        板块排名列表
    """
    # 如果没有指定日期，获取最新日期
    if not trade_date:
        latest = await mongo_manager.find_one(
            "sector_ranking",
            {"ranking_type": ranking_type},
            sort=[("trade_date", -1)],
            projection={"trade_date": 1},
        )
        if latest:
            trade_date = latest.get("trade_date")
        else:
            return {"rankings": [], "history": []}
    
    # 直接从 sector_ranking 表获取当日预排序数据
    day_data = await mongo_manager.find_many(
        "sector_ranking",
        {"trade_date": trade_date, "ranking_type": ranking_type},
        projection={"rank": 1, "ts_code": 1, "name": 1, "pct_change": 1, "net_amount": 1, "lead_stock": 1, "_id": 0},
        sort=[("rank", 1)],  # 按排名升序
    )
    
    # 直接返回预排序的数据
    result = []
    for item in day_data:
        result.append({
            "rank": item.get("rank"),
            "ts_code": item.get("ts_code"),
            "name": item.get("name") or item.get("ts_code", "未知"),
            "pct_change": _safe_float(item.get("pct_change")),
            "net_amount": _safe_float(item.get("net_amount")),
            "lead_stock": item.get("lead_stock", ""),
        })
    
    # 如果需要获取多天历史数据
    history = []
    if days > 1:
        # 获取最近 N 天的交易日（从 sector_ranking 表）
        all_dates = await mongo_manager.find_many(
            "sector_ranking",
            {"ranking_type": ranking_type},
            projection={"trade_date": 1, "_id": 0},
            sort=[("trade_date", -1)],
        )
        # 去重并排序
        unique_dates = sorted(list(set(d.get("trade_date") for d in all_dates if d.get("trade_date"))), reverse=True)[:days]
        
        for dt in unique_dates:
            dt_data = await mongo_manager.find_many(
                "sector_ranking",
                {"trade_date": dt, "ranking_type": ranking_type},
                projection={"rank": 1, "ts_code": 1, "name": 1, "pct_change": 1, "lead_stock": 1, "_id": 0},
                sort=[("rank", 1)],
            )
            history.append({
                "trade_date": dt,
                "rankings": [{
                    "rank": r.get("rank"),
                    "ts_code": r.get("ts_code"),
                    "name": r.get("name") or r.get("ts_code", "未知"),
                    "pct_change": _safe_float(r.get("pct_change")),
                    "lead_stock": r.get("lead_stock", ""),
                } for r in dt_data]
            })
    
    return {"trade_date": trade_date, "rankings": result, "history": history}


@router.get("/stats-table")
async def get_stats_table(
    days: int = Query(default=15, ge=1, le=30, description="天数"),
) -> Dict[str, Any]:
    """
    获取统计表格数据 (用于顶部表格展示)
    
    Args:
        days: 查询天数
    
    Returns:
        表格数据
    """
    stats_list = await mongo_manager.find_many(
        "daily_stats",
        {},
        sort=[("trade_date", -1)],
        limit=days,
    )
    
    # 获取对应的 market_analysis
    trade_dates = [s.get("trade_date") for s in stats_list]
    analysis_list = await mongo_manager.find_many(
        "market_analysis",
        {"trade_date": {"$in": trade_dates}},
    )
    analysis_map = {a.get("trade_date"): a for a in analysis_list}
    
    table_data = []
    for stats in stats_list:
        trade_date = stats.get("trade_date", "")
        analysis = analysis_map.get(trade_date, {})
        
        table_data.append({
            "trade_date": trade_date,
            "up_count": stats.get("up_count", 0),
            "down_count": stats.get("down_count", 0),
            "limit_up_count": stats.get("limit_up_count", 0),
            "limit_down_count": stats.get("limit_down_count", 0),
            "limit_1": stats.get("limit_1", 0),
            "limit_2": stats.get("limit_2", 0),
            "limit_3": stats.get("limit_3", 0),
            "limit_4": stats.get("limit_4", 0),
            "limit_5": stats.get("limit_5", 0),
            "limit_6_plus": stats.get("limit_6_plus", 0),
            "max_limit_height": stats.get("max_limit_height", 0),
            "strength_score": analysis.get("strength_score"),
            "sentiment_score": analysis.get("sentiment_score_ema", analysis.get("sentiment_score")),
            "cycle": analysis.get("cycle"),
        })
    
    return {"data": table_data}


@router.get("/statistics/calendar")
async def get_statistics_calendar() -> Dict[str, Any]:
    trade_dates = await _get_market_trade_dates(limit=260)
    if not trade_dates:
        raise HTTPException(status_code=404, detail="No market trade calendar available")

    latest_trade_date = trade_dates[-1]
    recent_trade_dates = trade_dates[-30:]
    return {
        "latest_trade_date": _display_trade_date(latest_trade_date),
        "trade_dates": [_display_trade_date(item) for item in recent_trade_dates],
        "source": "daily_stats",
    }


@router.get("/statistics/limit-snapshot")
async def get_statistics_limit_snapshot(
    trade_date: Optional[str] = Query(default=None, description="交易日，支持 YYYYMMDD 或 YYYY-MM-DD"),
) -> Dict[str, Any]:
    trade_dates = await _get_market_trade_dates(limit=60)
    if not trade_dates:
        raise HTTPException(status_code=404, detail="No trade dates available")

    normalized_trade_date = _normalize_trade_date_input(trade_date) or trade_dates[-1]
    if normalized_trade_date not in trade_dates:
        normalized_trade_date = trade_dates[-1]

    docs = await mongo_manager.find_many(
        "limit_list",
        {"trade_date": normalized_trade_date, "limit": "U"},
        projection={
            "ts_code": 1,
            "name": 1,
            "industry": 1,
            "close": 1,
            "amount": 1,
            "fd_amount": 1,
            "first_time": 1,
            "last_time": 1,
            "open_times": 1,
            "turnover_ratio": 1,
            "limit_times": 1,
            "_id": 0,
        },
        sort=[("limit_times", -1), ("first_time", 1)],
    )

    meta_map = await _get_stock_meta_map([
        str(doc.get("ts_code") or "")
        for doc in docs
        if doc.get("ts_code")
    ])

    items = []
    for doc in docs:
        ts_code = str(doc.get("ts_code") or "")
        code = ts_code.split(".")[0] if "." in ts_code else ts_code
        meta = meta_map.get(ts_code, {})
        item = {
            "ts_code": ts_code,
            "code": code,
            "name": meta.get("name") or doc.get("name") or code,
            "theme": _resolve_merged_theme_name(meta, doc),
            "board_count": int(doc.get("limit_times") or 1),
            "limit_type": _resolve_limit_type(doc),
            "limit_time": _format_limit_time(doc.get("first_time")),
            "seal_amount": _safe_float(doc.get("fd_amount"), _safe_float(doc.get("amount"), 0.0)),
        }
        items.append(item)

    groups = []
    for label in ["7板+", "6板", "5板", "4板", "3板", "2板", "首板"]:
        if label == "7板+":
            grouped_items = [item for item in items if int(item["board_count"]) >= 7]
        elif label == "首板":
            grouped_items = [item for item in items if int(item["board_count"]) <= 1]
        else:
            step = int(label[0])
            grouped_items = [item for item in items if int(item["board_count"]) == step]
        groups.append({
            "key": label,
            "label": label,
            "count": len(grouped_items),
            "items": grouped_items,
        })

    total = max(1, len(items))
    type_groups = []
    for limit_type in ["一字板", "T字板", "换手板", "回封板", "尾盘板"]:
        grouped_items = [item for item in items if item["limit_type"] == limit_type]
        type_groups.append({
            "type": limit_type,
            "count": len(grouped_items),
            "share": round(len(grouped_items) / total * 100, 1),
            "items": grouped_items,
        })

    return {
        "trade_date": _display_trade_date(normalized_trade_date),
        "source": "limit_list",
        "warnings": [] if items else ["limit_list 当前交易日无涨停数据"],
        "limit_fleet": {
            "total_count": len(items),
            "groups": groups,
            "detail": items,
        },
        "limit_types": {
            "groups": type_groups,
            "detail": [
                {
                    **item,
                    "type": item["limit_type"],
                    "board_band_label": _board_group_label(int(item["board_count"])),
                }
                for item in items
            ],
        },
    }


@router.get("/statistics/leader-cycle")
async def get_statistics_leader_cycle(
    period: str = Query(default="1m", description="1w/1m/3m/1y"),
) -> Dict[str, Any]:
    trade_dates = await _get_market_trade_dates(limit=260)
    if not trade_dates:
        raise HTTPException(status_code=404, detail="No trade dates available")

    latest_trade_date = trade_dates[-1]
    period_trade_dates = _resolve_period_trade_dates(trade_dates, latest_trade_date, period)
    warnings = _build_period_coverage_warning(period_trade_dates, period, "涨停梯队数据")
    start_trade_date = period_trade_dates[0]
    end_trade_date = period_trade_dates[-1]

    docs = await mongo_manager.find_many(
        "limit_list",
        {"trade_date": {"$gte": start_trade_date, "$lte": end_trade_date}, "limit": "U"},
        projection={"ts_code": 1, "trade_date": 1, "name": 1, "industry": 1, "market": 1, "limit_times": 1, "_id": 0},
    )

    stock_summary: Dict[str, Dict[str, Any]] = {}
    docs_by_date: Dict[str, Dict[str, int]] = defaultdict(dict)
    for doc in docs:
        ts_code = str(doc.get("ts_code") or "")
        if not ts_code:
            continue
        board_count = int(doc.get("limit_times") or 1)
        docs_by_date[str(doc.get("trade_date") or "")][ts_code] = board_count
        summary = stock_summary.setdefault(ts_code, {
            "count": 0,
            "max_board": 0,
            "name": doc.get("name") or ts_code,
            "theme": _resolve_theme_name(doc),
        })
        summary["count"] += 1
        summary["max_board"] = max(summary["max_board"], board_count)

    meta_map = await _get_stock_meta_map(list(stock_summary.keys()))

    rankings = []
    for index, (ts_code, info) in enumerate(
        sorted(stock_summary.items(), key=lambda item: (item[1]["count"], item[1]["max_board"]), reverse=True)[:30],
        start=1,
    ):
        meta = meta_map.get(ts_code, {})
        rankings.append({
            "rank": index,
            "ts_code": ts_code,
            "code": meta.get("symbol") or ts_code.split(".")[0],
            "name": meta.get("name") or info["name"],
            "theme": _resolve_merged_theme_name(meta, {"theme": info["theme"]}),
            "limit_count": info["count"],
            "max_board": info["max_board"],
        })

    promotion_trend = []
    for index, current_date in enumerate(period_trade_dates):
        current_map = docs_by_date.get(current_date, {})
        if index == 0:
            promotion_trend.append({
                "date": _display_trade_date(current_date),
                "total": 0.0,
                "step12": 0.0,
                "step23": 0.0,
                "step34": 0.0,
                "step45": 0.0,
                "step56": 0.0,
                "step67": 0.0,
                "step7Plus": 0.0,
            })
            continue

        previous_map = docs_by_date.get(period_trade_dates[index - 1], {})
        total_promotions = sum(1 for ts_code in previous_map if ts_code in current_map)

        def lane_rate(step: int) -> float:
            denominator = sum(1 for prev_step in previous_map.values() if prev_step == step)
            numerator = sum(1 for ts_code, prev_step in previous_map.items() if prev_step == step and current_map.get(ts_code) == step + 1)
            return _safe_percent(numerator, denominator)

        denom_7_plus = sum(1 for prev_step in previous_map.values() if prev_step >= 7)
        num_7_plus = sum(
            1
            for ts_code, prev_step in previous_map.items()
            if prev_step >= 7 and current_map.get(ts_code) == prev_step + 1
        )

        promotion_trend.append({
            "date": _display_trade_date(current_date),
            "total": _safe_percent(total_promotions, len(previous_map)),
            "step12": lane_rate(1),
            "step23": lane_rate(2),
            "step34": lane_rate(3),
            "step45": lane_rate(4),
            "step56": lane_rate(5),
            "step67": lane_rate(6),
            "step7Plus": _safe_percent(num_7_plus, denom_7_plus),
        })

    return {
        "period": period,
        "source": "limit_list",
        "warnings": ([*warnings] if docs else [*warnings, "limit_list 在当前周期内暂无数据"]),
        "rankings": rankings,
        "promotion_trend": promotion_trend,
    }


@router.get("/statistics/sentiment")
async def get_statistics_sentiment(
    period: str = Query(default="1m", description="1w/1m/3m/1y"),
) -> Dict[str, Any]:
    trade_dates = await _get_market_trade_dates(limit=260)
    if not trade_dates:
        raise HTTPException(status_code=404, detail="No trade dates available")

    latest_trade_date = trade_dates[-1]
    period_trade_dates = _resolve_period_trade_dates(trade_dates, latest_trade_date, period)
    warnings = _build_period_coverage_warning(period_trade_dates, period, "市场情绪数据")
    previous_trade_dates = trade_dates[max(0, trade_dates.index(period_trade_dates[0]) - 1):]
    window_dates = previous_trade_dates[:len(period_trade_dates) + 1] if previous_trade_dates else period_trade_dates
    needed_dates = sorted(set(window_dates))

    stats_docs = await mongo_manager.find_many(
        "daily_stats",
        {"trade_date": {"$in": needed_dates}},
        sort=[("trade_date", 1)],
    )
    analysis_docs = await mongo_manager.find_many(
        "market_analysis",
        {"trade_date": {"$in": needed_dates}},
    )
    limit_docs = await mongo_manager.find_many(
        "limit_list",
        {"trade_date": {"$in": needed_dates}, "limit": "U"},
        projection={"ts_code": 1, "trade_date": 1, "close": 1, "_id": 0},
    )

    stats_map = {str(doc.get("trade_date")): doc for doc in stats_docs if doc.get("trade_date")}
    analysis_map = {str(doc.get("trade_date")): doc for doc in analysis_docs if doc.get("trade_date")}
    limit_map: Dict[str, Dict[str, float]] = defaultdict(dict)
    limit_ts_codes: Dict[str, List[str]] = defaultdict(list)
    for doc in limit_docs:
        trade_date = str(doc.get("trade_date") or "")
        ts_code = str(doc.get("ts_code") or "")
        if not trade_date or not ts_code:
            continue
        limit_map[trade_date][ts_code] = _safe_float(doc.get("close"), 0.0)
        limit_ts_codes[trade_date].append(ts_code)

    current_trade_dates = period_trade_dates
    current_daily_docs = await mongo_manager.find_many(
        "stock_daily",
        {"trade_date": {"$in": current_trade_dates}, "ts_code": {"$in": sorted({code for values in limit_ts_codes.values() for code in values})}},
        projection={"ts_code": 1, "trade_date": 1, "open": 1, "high": 1, "close": 1, "_id": 0},
    ) if limit_ts_codes else []
    daily_map: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    for doc in current_daily_docs:
        daily_map[str(doc.get("trade_date") or "")][str(doc.get("ts_code") or "")] = doc

    trend = []
    for index, current_date in enumerate(period_trade_dates):
        prev_date = trade_dates[trade_dates.index(current_date) - 1] if trade_dates.index(current_date) > 0 else None
        prev_limit_map = limit_map.get(prev_date or "", {})
        current_limit_map = limit_map.get(current_date, {})
        current_daily_map = daily_map.get(current_date, {})

        samples = []
        for ts_code, prev_close in prev_limit_map.items():
            daily = current_daily_map.get(ts_code)
            if not daily or prev_close <= 0:
                continue
            samples.append({
                "open_premium": ( _safe_float(daily.get("open"), 0.0) - prev_close ) / prev_close * 100,
                "high_premium": ( _safe_float(daily.get("high"), 0.0) - prev_close ) / prev_close * 100,
                "close_return": ( _safe_float(daily.get("close"), 0.0) - prev_close ) / prev_close * 100,
            })

        stats = stats_map.get(current_date, {})
        analysis = analysis_map.get(current_date, {})
        limit_up_count = int(stats.get("limit_up_count") or 0)
        broken_count = int(stats.get("broken_limit_count") or 0)
        exploded_denominator = max(1, limit_up_count + broken_count)
        total_promotions = sum(1 for ts_code in prev_limit_map if ts_code in current_limit_map)

        trend.append({
            "date": _display_trade_date(current_date),
            "promotion_rate": round(_safe_float(analysis.get("promotion_rate"), _safe_percent(total_promotions, len(prev_limit_map))), 1),
            "total_promotion_rate": round(_safe_percent(total_promotions, len(prev_limit_map)), 1),
            "explosion_rate": round(_safe_percent(broken_count, exploded_denominator), 1),
            "exploded_count": broken_count,
            "try_limit_count": limit_up_count + broken_count,
            "avg_follow_return": round(sum(item["close_return"] for item in samples) / len(samples), 2) if samples else 0.0,
            "open_premium": round(sum(item["open_premium"] for item in samples) / len(samples), 2) if samples else 0.0,
            "high_premium": round(sum(item["high_premium"] for item in samples) / len(samples), 2) if samples else 0.0,
            "limit_count": limit_up_count,
            "prev_limit_count": int(stats_map.get(prev_date or "", {}).get("limit_up_count") or 0),
        })

    latest = trend[-1] if trend else {
        "date": _display_trade_date(latest_trade_date),
        "promotion_rate": 0.0,
        "total_promotion_rate": 0.0,
        "explosion_rate": 0.0,
        "exploded_count": 0,
        "try_limit_count": 0,
        "avg_follow_return": 0.0,
        "open_premium": 0.0,
        "high_premium": 0.0,
        "limit_count": 0,
        "prev_limit_count": 0,
    }

    return {
        "period": period,
        "latest_trade_date": _display_trade_date(latest_trade_date),
        "source": "daily_stats+market_analysis+limit_list+stock_daily",
        "warnings": ([*warnings] if trend else [*warnings, "情绪趋势数据不足"]),
        "latest": latest,
        "trend": trend,
    }


@router.get("/statistics/stage-gainers")
async def get_statistics_stage_gainers(
    period: str = Query(default="1m", description="1w/1m/3m/1y"),
) -> Dict[str, Any]:
    trade_dates = await _get_index_trade_dates(limit=260)
    if not trade_dates:
        raise HTTPException(status_code=404, detail="No trade dates available")
    latest_trade_date = trade_dates[-1]
    period_trade_dates = _resolve_period_trade_dates(trade_dates, latest_trade_date, period)
    warnings = _build_period_coverage_warning(period_trade_dates, period, "股票日线数据")
    rankings = await _build_stage_gain_rankings(period_trade_dates[0], period_trade_dates[-1])
    return {
        "period": period,
        "source": "stock_daily+stock_basic",
        "warnings": ([*warnings] if rankings else [*warnings, "当前周期内暂无阶段涨幅数据"]),
        "rankings": rankings,
    }


@router.get("/statistics/nextday-win-rate")
async def get_statistics_nextday_win_rate(
    period: str = Query(default="1m", description="1w/1m/3m/1y"),
) -> Dict[str, Any]:
    trade_dates = await _get_index_trade_dates(limit=260)
    if not trade_dates:
        raise HTTPException(status_code=404, detail="No trade dates available")
    latest_trade_date = trade_dates[-1]
    period_trade_dates = _resolve_period_trade_dates(trade_dates, latest_trade_date, period)
    warnings = _build_period_coverage_warning(period_trade_dates, period, "股票日线数据")
    rankings = await _build_nextday_win_rate(period_trade_dates[0], period_trade_dates[-1])
    return {
        "period": period,
        "source": "stock_daily+stock_basic",
        "warnings": ([*warnings] if rankings else [*warnings, "当前周期内暂无足够的交易数据"]),
        "rankings": rankings,
    }


@router.get("/statistics/streak-board")
async def get_statistics_streak_board(
    period: str = Query(default="1m", description="1w/1m/3m/1y"),
) -> Dict[str, Any]:
    trade_dates = await _get_index_trade_dates(limit=260)
    if not trade_dates:
        raise HTTPException(status_code=404, detail="No trade dates available")
    latest_trade_date = trade_dates[-1]
    streak_trade_dates = _resolve_period_trade_dates(trade_dates, latest_trade_date, period)
    warnings = _build_period_coverage_warning(streak_trade_dates, period, "股票日线数据")
    up_rows, down_rows = await _build_streak_rankings(streak_trade_dates[0], streak_trade_dates[-1])
    return {
        "period": period,
        "source": "stock_daily+stock_basic",
        "warnings": ([*warnings] if (up_rows or down_rows) else [*warnings, "当前周期内连涨连跌统计为空"]),
        "up": up_rows,
        "down": down_rows,
    }


@router.get("/statistics/rebound")
async def get_statistics_rebound(
    period: str = Query(default="1m", description="1w/1m/3m/1y"),
) -> Dict[str, Any]:
    trade_dates = await _get_index_trade_dates(limit=260)
    if not trade_dates:
        raise HTTPException(status_code=404, detail="No trade dates available")
    latest_trade_date = trade_dates[-1]
    period_trade_dates = _resolve_period_trade_dates(trade_dates, latest_trade_date, period)
    warnings = _build_period_coverage_warning(period_trade_dates, period, "股票日线数据")
    period_label = PERIOD_LABEL_MAP.get(period, "近一个月")
    rankings = await _build_rebound_rankings(period_trade_dates[0], period_trade_dates[-1], period_label)
    return {
        "period": period,
        "source": "stock_daily+stock_basic",
        "warnings": ([*warnings] if rankings else [*warnings, "当前周期内暂无高低点反弹数据"]),
        "rankings": rankings,
    }


@router.get("/theme-radar")
async def get_theme_radar(
    trade_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    获取主线雷达数据
    
    展示当前共识度最高的3个板块及其5日位次变化
    """
    # 如果没有指定日期，获取最新日期
    if not trade_date:
        latest = await mongo_manager.find_one(
            "sector_ranking",
            {},
            sort=[("trade_date", -1)],
            projection={"trade_date": 1},
        )
        if latest:
            trade_date = latest.get("trade_date")
        else:
            return {"radar": [], "rotation": []}
    
    # 初始化 theme_manager
    await theme_manager.initialize()
    
    # 获取雷达数据
    radar_data = await theme_manager.get_theme_radar(mongo_manager, trade_date)
    
    return radar_data


@router.get("/theme-analysis")
async def get_theme_analysis(
    trade_date: Optional[str] = None,
    days: int = Query(default=5, ge=1, le=10, description="回看天数"),
) -> Dict[str, Any]:
    """
    获取完整的板块主线分析
    
    包括：主线板块、强势关注、轮动分析
    """
    # 如果没有指定日期，获取最新日期
    if not trade_date:
        latest = await mongo_manager.find_one(
            "sector_ranking",
            {},
            sort=[("trade_date", -1)],
            projection={"trade_date": 1},
        )
        if latest:
            trade_date = latest.get("trade_date")
        else:
            return {"main_themes": [], "strong_focus": [], "rotation_analysis": []}
    
    # 初始化 theme_manager
    await theme_manager.initialize()
    
    # 获取分析数据
    analysis = await theme_manager.analyze_themes(mongo_manager, trade_date, days)
    
    return analysis


@router.get("/sector-timeline")
async def get_sector_timeline(
    ranking_type: str = Query(default="industry_top", description="排名类型"),
    days: int = Query(default=10, ge=1, le=30, description="天数"),
) -> Dict[str, Any]:
    """
    获取板块位次时间线数据
    
    用于展示板块在过去N天的位次迁移
    """
    # 获取最近N天的排名数据
    all_dates = await mongo_manager.find_many(
        "sector_ranking",
        {"ranking_type": ranking_type},
        projection={"trade_date": 1, "_id": 0},
    )
    unique_dates = sorted(
        list(set(d.get("trade_date") for d in all_dates if d.get("trade_date"))),
        reverse=True
    )[:days]
    
    if not unique_dates:
        return {"dates": [], "sectors": []}
    
    # 获取这些日期的排名数据
    rankings = await mongo_manager.find_many(
        "sector_ranking",
        {"trade_date": {"$in": unique_dates}, "ranking_type": ranking_type},
        sort=[("trade_date", -1), ("rank", 1)],
    )
    
    # 构建时间线数据
    # 按板块名称分组
    sector_data = {}
    for r in rankings:
        name = r.get("name", "")
        if not name:
            continue
        
        if name not in sector_data:
            sector_data[name] = {
                "name": name,
                "ts_code": r.get("ts_code"),
                "ranks": {},
            }
        sector_data[name]["ranks"][r.get("trade_date")] = {
            "rank": r.get("rank"),
            "pct_change": _safe_float(r.get("pct_change")),
            "lead_stock": r.get("lead_stock", ""),
        }
    
    # 计算每个板块的出现次数和平均排名
    for name, data in sector_data.items():
        appearances = len(data["ranks"])
        avg_rank = sum(r["rank"] for r in data["ranks"].values()) / max(1, appearances)
        data["appearances"] = appearances
        data["avg_rank"] = round(avg_rank, 1)
    
    # 按出现次数和平均排名排序
    sorted_sectors = sorted(
        sector_data.values(),
        key=lambda x: (-x["appearances"], x["avg_rank"])
    )
    
    return {
        "dates": sorted(unique_dates, reverse=True),
        "sectors": sorted_sectors[:20],  # 返回前20个板块
    }


@router.get("/sector-scores")
async def get_sector_scores(
    trade_date: Optional[str] = None,
    days: int = Query(default=20, ge=5, le=30, description="回看天数"),
) -> Dict[str, Any]:
    """
    获取板块长周期评分
    
    基于 MA20 计算板块综合评分，识别主线/异动/退潮
    """
    # 如果没有指定日期，获取最新日期
    if not trade_date:
        latest = await mongo_manager.find_one(
            "sector_ranking",
            {},
            sort=[("trade_date", -1)],
            projection={"trade_date": 1},
        )
        if latest:
            trade_date = latest.get("trade_date")
        else:
            return {"sectors": [], "main_themes": [], "anomalies": [], "fading": []}
    
    # 初始化 theme_manager
    await theme_manager.initialize()
    
    # 获取评分数据
    result = await theme_manager.calculate_sector_scores(mongo_manager, trade_date, days)
    
    return result


@router.get("/sector-scatter")
async def get_sector_scatter(
    trade_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    获取板块散点图数据
    
    横轴: 20日共识度
    纵轴: 短期强度
    """
    # 如果没有指定日期，获取最新日期
    if not trade_date:
        latest = await mongo_manager.find_one(
            "sector_ranking",
            {},
            sort=[("trade_date", -1)],
            projection={"trade_date": 1},
        )
        if latest:
            trade_date = latest.get("trade_date")
        else:
            return {"scatter": []}
    
    # 初始化 theme_manager
    await theme_manager.initialize()
    
    # 获取散点图数据
    result = await theme_manager.get_scatter_data(mongo_manager, trade_date)
    
    return result


# ==================== 热点新闻 ====================


@router.get("/hot_news")
async def get_hot_news(
    source: Optional[str] = Query(default=None, description="来源过滤 (如 baidu, weibo)"),
    limit: int = Query(default=50, ge=1, le=200, description="返回条数"),
) -> Dict[str, Any]:
    """
    获取热点新闻 (数据源: Redis)
    
    支持的来源:
    - cls: 财联社
    - xueqiu: 雪球
    - wallstreetcn: 华尔街见闻
    - gelonghui: 格隆汇
    - jin10: 金十数据
    - juejin: 稀土掘金
    - ithome: IT之家
    - 36kr: 36氪
    - github: Github
    - douyin: 抖音
    - bilibili: 哔哩哔哩
    - kaopu: 靠谱新闻
    - thepaper: 澎湃新闻
    
    Args:
        source: 可选的来源过滤
        limit: 返回条数
        
    Returns:
        热点新闻列表
    """
    # 确保 Redis 已初始化
    if not redis_manager.is_initialized:
        await redis_manager.initialize()
    
    if source:
        # 获取指定来源
        data = await redis_manager.get_hot_news(source)
        if not data:
            return {"news": [], "total": 0, "updated_at": ""}
        
        news_list = data.get("news", [])[:limit]
        return {
            "news": news_list,
            "total": len(news_list),
            "updated_at": data.get("updated_at", ""),
        }
    else:
        # 获取所有来源
        all_data = await redis_manager.get_all_hot_news()
        
        result = []
        for source_id, data in all_data.items():
            news = data.get("news", [])
            for item in news:
                item["updated_at"] = data.get("updated_at", "")
            result.extend(news)
        
        # 按热度排序
        result.sort(key=lambda x: x.get("hot", 0), reverse=True)
        result = result[:limit]
        
        return {"news": result, "total": len(result)}


@router.get("/hot_news/sources")
async def get_hot_news_sources() -> Dict[str, Any]:
    """
    获取可用的热点新闻来源列表
    """
    sources = [
        # 金融类
        {"id": "cls", "name": "财联社", "color": "#E53935", "column": "finance"},
        {"id": "xueqiu", "name": "雪球", "color": "#1E88E5", "column": "finance"},
        {"id": "wallstreetcn", "name": "华尔街见闻", "color": "#1976D2", "column": "finance"},
        {"id": "gelonghui", "name": "格隆汇", "color": "#1565C0", "column": "finance"},
        {"id": "jin10", "name": "金十数据", "color": "#0D47A1", "column": "finance"},
        # 科技类
        {"id": "juejin", "name": "稀土掘金", "color": "#1E80FF", "column": "tech"},
        {"id": "ithome", "name": "IT之家", "color": "#D32F2F", "column": "tech"},
        {"id": "36kr", "name": "36氪", "color": "#0080FF", "column": "tech"},
        {"id": "github", "name": "Github", "color": "#24292E", "column": "tech"},
        # 娱乐类
        {"id": "douyin", "name": "抖音", "color": "#212121", "column": "entertainment"},
        {"id": "bilibili", "name": "哔哩哔哩", "color": "#00A1D6", "column": "entertainment"},
        # 综合/世界
        {"id": "kaopu", "name": "靠谱新闻", "color": "#607D8B", "column": "world"},
        {"id": "thepaper", "name": "澎湃新闻", "color": "#455A64", "column": "world"},
    ]
    return {"sources": sources}


@router.post("/hot_news/refresh")
async def refresh_hot_news(
    source: Optional[str] = Query(default=None, description="指定来源刷新，不传则刷新全部"),
    admin: CurrentUser = Depends(require_admin),  # 需要管理员权限
) -> Dict[str, Any]:
    """
    手动触发热点新闻刷新（管理员专用）
    
    通过 RPC 调用 DataSync 节点的采集器抓取热点新闻数据。
    
    Args:
        source: 可选的来源过滤，不传则刷新全部
            - cls: 财联社
            - xueqiu: 雪球
            - wallstreetcn: 华尔街见闻
            - gelonghui: 格隆汇
            - jin10: 金十数据
            - juejin: 稀土掘金
            - ithome: IT之家
            - 36kr: 36氪
            - github: Github
            - douyin: 抖音
            - bilibili: 哔哩哔哩
            - kaopu: 靠谱新闻
            - thepaper: 澎湃新闻
        
    Returns:
        刷新结果:
        - success_count: 成功的来源数
        - fail_count: 失败的来源数
        - total_news: 采集的新闻总数
    """
    import logging
    import uuid
    from core.rpc import RPCClient
    
    logger = logging.getLogger("api.market.hot_news")
    trace_id = uuid.uuid4().hex[:16]
    
    logger.info(f"[{trace_id}] Admin {admin.username} triggered refresh_hot_news, source={source or 'ALL'}")
    
    try:
        # 通过 RPC 调用 DataSync 节点
        rpc_client = RPCClient()
        
        # 广播给所有 data_sync 节点（通常只有一个）
        results = await rpc_client.broadcast_by_type(
            node_type="data_sync",
            method="refresh_hot_news",
            params={"source": source} if source else {},
            trace_id=trace_id,
            source_node="web",
            timeout=60.0,  # 采集可能较慢，设置 60 秒超时
        )
        
        if not results:
            logger.warning(f"[{trace_id}] No data_sync nodes available")
            return {
                "success": False,
                "error": "No data_sync nodes available",
            }
        
        # 返回第一个节点的结果
        first_result = results[0]
        logger.info(f"[{trace_id}] RPC result: {first_result}")
        
        if first_result.get("success"):
            return first_result.get("result", {})
        else:
            return {
                "success": False,
                "error": first_result.get("error", "Unknown RPC error"),
            }
        
    except Exception as e:
        logger.exception(f"[{trace_id}] refresh_hot_news RPC failed: {e}")
        return {
            "success": False,
            "error": str(e),
        }


@router.get("/hot_news/stats")
async def get_hot_news_stats() -> Dict[str, Any]:
    """
    获取热点新闻统计 (数据源: Redis)
    """
    return await redis_manager.get_hot_news_stats()
