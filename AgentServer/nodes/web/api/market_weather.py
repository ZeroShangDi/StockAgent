"""
市场晴雨表 API。
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from core.managers import mongo_manager
from src.analysis.market_weather import market_weather_service
from .auth import CurrentUser, get_current_user


router = APIRouter(prefix="/market/weather", tags=["Market Weather"])
CORE_BENCHMARKS = ["000001.SH", "399001.SZ", "399006.SZ"]


def _serialize_record(record: Dict[str, Any]) -> Dict[str, Any]:
    signal = market_weather_service.rebuild_signal_for_record(record)
    return {
        "trade_date": record.get("trade_date"),
        "display_trade_date": record.get("display_trade_date"),
        "source": record.get("source"),
        "temperature_index": float(record.get("temperature_index", 0) or 0),
        "limit_premium_factor": float(record.get("limit_premium_factor", 0) or 0),
        "trend_factor": float(record.get("trend_factor", 0) or 0),
        "volume_factor": float(record.get("volume_factor", 0) or 0),
        "breadth_factor": float(record.get("breadth_factor", 0) or 0),
        "momentum_factor": float(record.get("momentum_factor", 0) or 0),
        "indicator": record.get("indicator") or {},
        "signal": signal,
        "synced_at": record.get("synced_at"),
        "updated_at": record.get("updated_at"),
    }


def _to_display_trade_date(value: Optional[str]) -> str:
    if not value:
        return ""
    trade_date = value.replace("-", "")
    if len(trade_date) == 8:
        return f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
    return value


def _calc_max_drawdown(nav_values: List[float]) -> float:
    peak = 0.0
    max_drawdown = 0.0
    for value in nav_values:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - value) / peak)
    return max_drawdown


def _safe_round(value: Optional[float], digits: int = 2) -> Optional[float]:
    if value is None:
        return None
    return round(value, digits)


async def _load_index_rows(start_date: str, end_date: str) -> List[Dict[str, Any]]:
    return await mongo_manager.find_many(
        "index_daily",
        {
            "ts_code": {"$in": CORE_BENCHMARKS},
            "trade_date": {"$gte": start_date, "$lte": end_date},
        },
        projection={
            "_id": 0,
            "ts_code": 1,
            "trade_date": 1,
            "close": 1,
            "pct_chg": 1,
        },
        sort=[("trade_date", 1)],
        limit=len(CORE_BENCHMARKS) * 700,
    )


async def _build_index_coverage_summary() -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    collection = mongo_manager.db["index_daily"]
    for ts_code in CORE_BENCHMARKS:
        count = await collection.count_documents({"ts_code": ts_code})
        earliest = await mongo_manager.find_one("index_daily", {"ts_code": ts_code}, sort=[("trade_date", 1)])
        latest = await mongo_manager.find_one("index_daily", {"ts_code": ts_code}, sort=[("trade_date", -1)])
        summary[ts_code] = {
            "count": count,
            "earliest_trade_date": earliest.get("trade_date") if earliest else None,
            "latest_trade_date": latest.get("trade_date") if latest else None,
        }
    return summary


def _build_dashboard_payload(
    weather_history: List[Dict[str, Any]],
    index_rows: List[Dict[str, Any]],
    benchmark: str = "composite",
) -> Dict[str, Any]:
    index_by_date: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for row in index_rows:
        index_by_date.setdefault(row["trade_date"], {})[row["ts_code"]] = row

    dashboard_history: List[Dict[str, Any]] = []
    strategy_nav = 1.0
    benchmark_nav = 1.0
    nav_values = [1.0]
    benchmark_nav_values = [1.0]

    benchmark_daily_returns: List[float] = []
    positions: List[float] = []
    actions: List[str] = []
    trade_dates: List[str] = []

    previous_position = None

    for record in weather_history:
        trade_date = record.get("trade_date", "")
        date_rows = index_by_date.get(trade_date, {})
        if benchmark == "composite":
            returns = [float(item.get("pct_chg", 0) or 0) / 100 for item in date_rows.values()]
            benchmark_return = sum(returns) / len(returns) if returns else 0.0
            benchmark_close = None
        else:
            benchmark_row = date_rows.get(benchmark)
            benchmark_return = float(benchmark_row.get("pct_chg", 0) or 0) / 100 if benchmark_row else 0.0
            benchmark_close = float(benchmark_row.get("close", 0) or 0) if benchmark_row else None

        exposure = float(record.get("signal", {}).get("做多少", 0) or 0) / 100
        effective_exposure = previous_position if previous_position is not None else exposure
        strategy_daily_return = benchmark_return * effective_exposure

        benchmark_nav *= 1 + benchmark_return
        strategy_nav *= 1 + strategy_daily_return

        benchmark_daily_returns.append(benchmark_return)
        positions.append(exposure)
        actions.append(str(record.get("signal", {}).get("做不做", "")))
        trade_dates.append(trade_date)
        nav_values.append(strategy_nav)
        benchmark_nav_values.append(benchmark_nav)

        dashboard_history.append(
            {
                "trade_date": trade_date,
                "display_trade_date": record.get("display_trade_date") or _to_display_trade_date(trade_date),
                "temperature_index": float(record.get("temperature_index", 0) or 0),
                "position_pct": round(exposure * 100, 2),
                "action": record.get("signal", {}).get("做不做"),
                "strategy": record.get("signal", {}).get("做什么"),
                "benchmark_return_pct": round(benchmark_return * 100, 2),
                "strategy_return_pct": round(strategy_daily_return * 100, 2),
                "benchmark_nav": round(benchmark_nav, 4),
                "strategy_nav": round(strategy_nav, 4),
                "benchmark_close": benchmark_close,
                "limit_premium_factor": float(record.get("limit_premium_factor", 0) or 0),
                "trend_factor": float(record.get("trend_factor", 0) or 0),
                "volume_factor": float(record.get("volume_factor", 0) or 0),
                "breadth_factor": float(record.get("breadth_factor", 0) or 0),
                "momentum_factor": float(record.get("momentum_factor", 0) or 0),
            }
        )

        previous_position = exposure

    total_return_pct = (strategy_nav - 1) * 100
    benchmark_return_pct = (benchmark_nav - 1) * 100
    excess_return_pct = total_return_pct - benchmark_return_pct
    positive_days = sum(1 for item in dashboard_history if item["strategy_return_pct"] > 0)
    invested_days_pct = (sum(positions) / len(positions) * 100) if positions else 0.0

    high_forward_returns: List[float] = []
    low_forward_returns: List[float] = []
    high_forward_wins = 0
    low_forward_wins = 0
    for idx, exposure in enumerate(positions):
        if idx + 5 >= len(benchmark_daily_returns):
            break
        future_return = 1.0
        for future_idx in range(idx + 1, idx + 6):
            future_return *= 1 + benchmark_daily_returns[future_idx]
        future_return -= 1
        if exposure >= 0.6:
            high_forward_returns.append(future_return)
            if future_return > 0:
                high_forward_wins += 1
        if exposure <= 0.3:
            low_forward_returns.append(future_return)
            if future_return > 0:
                low_forward_wins += 1

    confidence = {
        "strategy_return_pct": _safe_round(total_return_pct),
        "benchmark_return_pct": _safe_round(benchmark_return_pct),
        "excess_return_pct": _safe_round(excess_return_pct),
        "strategy_max_drawdown_pct": _safe_round(_calc_max_drawdown(nav_values) * 100),
        "benchmark_max_drawdown_pct": _safe_round(_calc_max_drawdown(benchmark_nav_values) * 100),
        "strategy_win_rate_pct": _safe_round((positive_days / len(dashboard_history) * 100) if dashboard_history else 0.0),
        "average_position_pct": _safe_round(invested_days_pct),
        "high_position_signal_count": len(high_forward_returns),
        "high_position_avg_forward_5d_pct": _safe_round(
            (sum(high_forward_returns) / len(high_forward_returns) * 100) if high_forward_returns else None
        ),
        "high_position_win_rate_5d_pct": _safe_round(
            (high_forward_wins / len(high_forward_returns) * 100) if high_forward_returns else None
        ),
        "low_position_signal_count": len(low_forward_returns),
        "low_position_avg_forward_5d_pct": _safe_round(
            (sum(low_forward_returns) / len(low_forward_returns) * 100) if low_forward_returns else None
        ),
        "low_position_win_rate_5d_pct": _safe_round(
            (low_forward_wins / len(low_forward_returns) * 100) if low_forward_returns else None
        ),
    }

    return {
        "history": dashboard_history,
        "confidence": confidence,
    }


@router.get("/latest")
async def get_market_weather_latest() -> Dict[str, Any]:
    """获取最新市场晴雨表记录。若本地没有，则自动拉取一次最新数据。"""
    record = await market_weather_service.ensure_latest()
    return _serialize_record(record)


@router.get("/history")
async def get_market_weather_history(
    days: int = Query(default=30, ge=5, le=600, description="最近 N 个交易日"),
) -> Dict[str, List[Dict[str, Any]]]:
    history = await market_weather_service.list_history(days)
    return {"history": [_serialize_record(item) for item in history]}


@router.get("/dashboard")
async def get_market_weather_dashboard(
    start_date: Optional[str] = Query(default=None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(default=None, description="结束日期 YYYYMMDD"),
    benchmark: str = Query(default="composite", description="基准: composite / 000001.SH / 399001.SZ / 399006.SZ"),
) -> Dict[str, Any]:
    history = await market_weather_service.list_history_range(start_date=start_date, end_date=end_date, limit=600)
    serialized_history = [_serialize_record(item) for item in history]
    coverage = await market_weather_service.get_coverage_summary()

    if not serialized_history:
        return {
            "coverage": coverage,
            "benchmark_coverage": await _build_index_coverage_summary(),
            "history": [],
            "confidence": {},
        }

    history_start = serialized_history[0]["trade_date"]
    history_end = serialized_history[-1]["trade_date"]
    index_rows = await _load_index_rows(history_start, history_end)
    dashboard = _build_dashboard_payload(serialized_history, index_rows, benchmark=benchmark)

    return {
        "coverage": coverage,
        "benchmark": benchmark,
        "benchmark_coverage": await _build_index_coverage_summary(),
        **dashboard,
    }


@router.post("/sync")
async def sync_market_weather(
    days: int = Query(default=30, ge=1, le=90, description="补最近 N 个交易日"),
    overwrite: bool = Query(default=False, description="是否覆盖已存在记录"),
    current_user: CurrentUser = Depends(get_current_user),
) -> Dict[str, Any]:
    _ = current_user
    return await market_weather_service.sync_recent(days=days, overwrite=overwrite)


@router.post("/sync-range")
async def sync_market_weather_range(
    start_date: str = Query(..., description="开始日期 YYYYMMDD"),
    end_date: str = Query(..., description="结束日期 YYYYMMDD"),
    overwrite: bool = Query(default=False, description="是否覆盖已存在记录"),
    descending: bool = Query(default=True, description="是否从后往前补"),
    sleep_seconds: float = Query(default=0.35, ge=0, le=5, description="每次请求间隔秒数"),
    stop_on_empty_streak: int = Query(default=30, ge=0, le=120, description="连续空结果达到阈值后提前停止"),
    request_timeout_seconds: float = Query(default=12.0, ge=3, le=60, description="单次请求超时秒数"),
    current_user: CurrentUser = Depends(get_current_user),
) -> Dict[str, Any]:
    _ = current_user
    return await market_weather_service.sync_range(
        start_date=start_date,
        end_date=end_date,
        overwrite=overwrite,
        descending=descending,
        sleep_seconds=sleep_seconds,
        stop_on_empty_streak=stop_on_empty_streak or None,
        request_timeout_seconds=request_timeout_seconds,
    )
