"""市场统计预聚合所需的纯数据构建函数。"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from core.managers.mongo_manager import mongo_manager


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


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _display_trade_date(trade_date: str | None) -> str:
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


def _build_period_coverage_warning(trade_dates: List[str], period: str, source_label: str) -> List[str]:
    expected_days = _resolve_period_days(period)
    if len(trade_dates) >= expected_days or period == "1w":
        return []
    period_label = PERIOD_LABEL_MAP.get(period, period)
    return [f"{source_label} 当前仅覆盖 {len(trade_dates)} 个交易日，{period_label} 统计暂按现有数据展示"]


async def _get_market_trade_dates(limit: int = 260) -> List[str]:
    docs = await mongo_manager.find_many(
        "daily_stats",
        {},
        projection={"trade_date": 1, "_id": 0},
        sort=[("trade_date", -1)],
        limit=limit,
    )
    dates = [str(item.get("trade_date") or "") for item in docs if item.get("trade_date")]
    return sorted(set(filter(None, dates)))


async def _get_stock_meta_map(ts_codes: List[str]) -> Dict[str, Dict[str, Any]]:
    if not ts_codes:
        return {}
    docs = await mongo_manager.find_many(
        "stock_basic",
        {"ts_code": {"$in": ts_codes}},
        projection={"ts_code": 1, "symbol": 1, "name": 1, "industry": 1, "market": 1, "_id": 0},
    )
    return {str(doc.get("ts_code")): doc for doc in docs if doc.get("ts_code")}


async def _build_statistics_limit_snapshot_payload(normalized_trade_date: str) -> Dict[str, Any]:
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
        items.append({
            "ts_code": ts_code,
            "code": code,
            "name": meta.get("name") or doc.get("name") or code,
            "theme": _resolve_merged_theme_name(meta, doc),
            "board_count": int(doc.get("limit_times") or 1),
            "limit_type": _resolve_limit_type(doc),
            "limit_time": _format_limit_time(doc.get("first_time")),
            "seal_amount": _safe_float(doc.get("fd_amount"), _safe_float(doc.get("amount"), 0.0)),
        })

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


async def _build_statistics_leader_cycle_payload(period: str, latest_trade_date: str | None = None) -> Dict[str, Any]:
    trade_dates = await _get_market_trade_dates(limit=260)
    if not trade_dates:
        raise RuntimeError("No trade dates available")

    latest_trade_date = latest_trade_date or trade_dates[-1]
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
        "trade_date": latest_trade_date,
        "source": "limit_list",
        "warnings": ([*warnings] if docs else [*warnings, "limit_list 在当前周期内暂无数据"]),
        "rankings": rankings,
        "promotion_trend": promotion_trend,
    }


async def _build_statistics_sentiment_payload(period: str, latest_trade_date: str | None = None) -> Dict[str, Any]:
    trade_dates = await _get_market_trade_dates(limit=260)
    if not trade_dates:
        raise RuntimeError("No trade dates available")

    latest_trade_date = latest_trade_date or trade_dates[-1]
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
    for current_date in period_trade_dates:
        current_index = trade_dates.index(current_date)
        prev_date = trade_dates[current_index - 1] if current_index > 0 else None
        prev_limit_map = limit_map.get(prev_date or "", {})
        current_limit_map = limit_map.get(current_date, {})
        current_daily_map = daily_map.get(current_date, {})

        samples = []
        for ts_code, prev_close in prev_limit_map.items():
            daily = current_daily_map.get(ts_code)
            if not daily or prev_close <= 0:
                continue
            samples.append({
                "open_premium": (_safe_float(daily.get("open"), 0.0) - prev_close) / prev_close * 100,
                "high_premium": (_safe_float(daily.get("high"), 0.0) - prev_close) / prev_close * 100,
                "close_return": (_safe_float(daily.get("close"), 0.0) - prev_close) / prev_close * 100,
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
        "trade_date": latest_trade_date,
        "source": "daily_stats+market_analysis+limit_list",
        "warnings": warnings,
        "latest": latest,
        "trend": trend,
    }
