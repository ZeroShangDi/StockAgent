"""Strategy V2 evaluators.

The first real V2 evaluator adapts the existing one-line stock picker into the
unified -1/0/1 strategy contract without changing the legacy picker API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from core.managers import mongo_manager
from src.analysis.stock_picker import stock_picker_service


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class StrategyV2EvaluationContext:
    """Single stock evaluation context used by Strategy V2 runners."""

    user_id: str
    code: str = ""
    ts_code: str = ""
    stock: dict[str, Any] | None = None
    now: datetime | None = None


@dataclass(frozen=True)
class StrategyV2EvaluationResult:
    signal: int
    reason: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class _CandidateCacheEntry:
    expires_at: datetime
    run_id: str
    query_condition: str
    codes: set[str]
    ts_codes: set[str]
    total: int


class _StockPickerService(Protocol):
    async def query(self, input_text: str, user_id: str) -> dict[str, Any]:
        ...


def _normalize_code(value: Any) -> str:
    return str(value or "").strip().upper()


def _extract_stock_codes(context: StrategyV2EvaluationContext) -> tuple[str, str]:
    stock = context.stock or {}
    raw_ts_code = context.ts_code or stock.get("ts_code") or stock.get("TS_CODE") or stock.get("股票代码")
    raw_code = context.code or stock.get("code") or stock.get("代码")
    ts_code = _normalize_code(raw_ts_code)

    if not raw_code and "." in ts_code:
        raw_code = ts_code.split(".", 1)[0]

    return _normalize_code(raw_code), ts_code


def _extract_candidate_codes(result: dict[str, Any]) -> tuple[set[str], set[str]]:
    codes = {_normalize_code(item) for item in result.get("code_list") or [] if _normalize_code(item)}
    ts_codes = {_normalize_code(item) for item in result.get("ts_code_list") or [] if _normalize_code(item)}

    for row in result.get("data_list") or []:
        if not isinstance(row, dict):
            continue
        meta = row.get("__meta") or {}
        code = _normalize_code(meta.get("code") or row.get("code") or row.get("代码"))
        ts_code = _normalize_code(meta.get("ts_code") or row.get("ts_code") or row.get("股票代码"))
        if code:
            codes.add(code)
        if ts_code:
            ts_codes.add(ts_code)

    return codes, ts_codes


class OneLineStockPickerStrategy:
    """Adapt one-line stock picking into a per-stock V2 strategy evaluator."""

    strategy_key = "one_line_stock_picker"

    def __init__(self, service: _StockPickerService | None = None) -> None:
        self._service = service or stock_picker_service
        self._cache: dict[tuple[str, str, str], _CandidateCacheEntry] = {}

    async def evaluate(
        self,
        context: StrategyV2EvaluationContext,
        params: dict[str, Any] | None = None,
    ) -> StrategyV2EvaluationResult:
        params = params or {}
        query_text = self._query_text(params)
        if not query_text:
            return StrategyV2EvaluationResult(signal=-1, reason="一句话选股策略缺少选股语句")

        code, ts_code = _extract_stock_codes(context)
        if not code and not ts_code:
            return StrategyV2EvaluationResult(signal=0, reason="缺少股票代码，无法匹配一句话选股结果")

        entry = await self._get_candidates(
            user_id=context.user_id,
            query_text=query_text,
            ttl_days=int(params.get("cache_ttl_days") or 1),
            now=context.now,
        )
        matched = (ts_code and ts_code in entry.ts_codes) or (code and code in entry.codes)
        if matched:
            return StrategyV2EvaluationResult(
                signal=1,
                reason="股票命中一句话选股候选列表",
                meta={
                    "source_run_id": entry.run_id,
                    "query_condition": entry.query_condition,
                    "candidate_total": entry.total,
                },
            )

        return StrategyV2EvaluationResult(
            signal=0,
            reason="股票未命中一句话选股候选列表",
            meta={
                "source_run_id": entry.run_id,
                "query_condition": entry.query_condition,
                "candidate_total": entry.total,
            },
        )

    async def _get_candidates(
        self,
        *,
        user_id: str,
        query_text: str,
        ttl_days: int,
        now: datetime | None,
    ) -> _CandidateCacheEntry:
        current = now or datetime.now(SHANGHAI_TZ)
        if current.tzinfo is None:
            current = current.replace(tzinfo=SHANGHAI_TZ)
        else:
            current = current.astimezone(SHANGHAI_TZ)
        normalized_query = " ".join(query_text.split())
        cache_key = (user_id, normalized_query, current.date().isoformat())
        cached = self._cache.get(cache_key)
        if cached and cached.expires_at > current:
            return cached

        self._prune_expired(current)
        result = await self._service.query(normalized_query, user_id=user_id)
        codes, ts_codes = _extract_candidate_codes(result)
        entry = _CandidateCacheEntry(
            expires_at=current + timedelta(days=max(ttl_days, 1)),
            run_id=str(result.get("run_id") or ""),
            query_condition=str(result.get("query_condition") or normalized_query),
            codes=codes,
            ts_codes=ts_codes,
            total=int(result.get("total") or len(codes) or len(ts_codes)),
        )
        self._cache[cache_key] = entry
        return entry

    def _prune_expired(self, now: datetime) -> None:
        expired_keys = [key for key, entry in self._cache.items() if entry.expires_at <= now]
        for key in expired_keys:
            self._cache.pop(key, None)

    @staticmethod
    def _query_text(params: dict[str, Any]) -> str:
        return str(params.get("query_text") or params.get("input") or params.get("text") or "").strip()


one_line_stock_picker_strategy = OneLineStockPickerStrategy()


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _daily_pct_change(row: dict[str, Any]) -> float:
    pct = row.get("pct_chg")
    if pct is not None:
        return _to_float(pct)
    pre_close = _to_float(row.get("pre_close"))
    close = _to_float(row.get("close"))
    if pre_close <= 0:
        return 0.0
    return (close - pre_close) / pre_close * 100


def _moving_average(candles: list[dict[str, Any]], period: int) -> float | None:
    if period <= 0 or len(candles) < period:
        return None
    closes = [_to_float(row.get("close")) for row in candles[-period:]]
    if any(close <= 0 for close in closes):
        return None
    return sum(closes) / period


def _has_bullish_ma_alignment(candles: list[dict[str, Any]], short: int, mid: int, long: int) -> bool:
    ma_short = _moving_average(candles, short)
    ma_mid = _moving_average(candles, mid)
    ma_long = _moving_average(candles, long)
    return ma_short is not None and ma_mid is not None and ma_long is not None and ma_short > ma_mid > ma_long


def evaluate_double_cannon_from_candles(
    candles: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
) -> StrategyV2EvaluationResult:
    """Evaluate the double-cannon pattern from ascending daily candles."""
    params = params or {}
    lookback_days = max(_to_int(params.get("lookback_days"), 22), 5)
    min_bull_pct = _to_float(params.get("min_bull_pct"), 5.0)
    max_second_age_days = max(_to_int(params.get("max_second_age_days"), 5), 0)
    require_second_volume_gt_first = _is_enabled(params.get("require_second_volume_gt_first"))
    require_bullish_ma = _is_enabled(params.get("require_bullish_ma"))
    require_pullback_shrink_volume = _is_enabled(params.get("require_pullback_shrink_volume"))
    ma_short = max(_to_int(params.get("ma_short"), 5), 1)
    ma_mid = max(_to_int(params.get("ma_mid"), 10), 1)
    ma_long = max(_to_int(params.get("ma_long"), 20), 1)

    rows = [row for row in candles if row.get("trade_date") and _to_float(row.get("close")) > 0]
    rows.sort(key=lambda item: str(item.get("trade_date")))
    if len(rows) < 3:
        return StrategyV2EvaluationResult(signal=0, reason="历史 K 线不足，无法识别双响炮")

    recent = rows[-lookback_days:]
    latest_index = len(recent) - 1
    strong_indices = [
        index
        for index, row in enumerate(recent)
        if _to_float(row.get("close")) > _to_float(row.get("open"))
        and _daily_pct_change(row) >= min_bull_pct
    ]
    if len(strong_indices) < 2:
        return StrategyV2EvaluationResult(signal=0, reason="近期开盘收阳且涨幅达标的大阳线不足两根")

    for second_pos in reversed(strong_indices):
        if latest_index - second_pos > max_second_age_days:
            continue
        second = recent[second_pos]
        for first_pos in reversed(strong_indices):
            if first_pos >= second_pos - 1:
                continue
            first = recent[first_pos]
            if _to_float(second.get("close")) <= _to_float(first.get("close")):
                continue

            middle = recent[first_pos + 1:second_pos]
            first_low = _to_float(first.get("low"))
            broken_rows = [
                row
                for row in middle
                if first_low > 0 and _to_float(row.get("close")) < first_low
            ]
            meta = {
                "first_trade_date": str(first.get("trade_date")),
                "second_trade_date": str(second.get("trade_date")),
                "latest_trade_date": str(recent[-1].get("trade_date")),
                "first_pct_chg": _daily_pct_change(first),
                "second_pct_chg": _daily_pct_change(second),
                "middle_days": len(middle),
            }
            if broken_rows:
                meta["broken_trade_dates"] = [str(row.get("trade_date")) for row in broken_rows]
                return StrategyV2EvaluationResult(
                    signal=-1,
                    reason="两根大阳线之间出现收盘价跌破第一根最低价，形态结构破坏",
                    meta=meta,
                )

            if require_second_volume_gt_first and _to_float(second.get("vol")) <= _to_float(first.get("vol")):
                return StrategyV2EvaluationResult(signal=0, reason="第二根大阳线成交量未大于第一根", meta=meta)

            if require_pullback_shrink_volume and middle:
                middle_avg_volume = sum(_to_float(row.get("vol")) for row in middle) / len(middle)
                cannon_avg_volume = (_to_float(first.get("vol")) + _to_float(second.get("vol"))) / 2
                meta["middle_avg_volume"] = middle_avg_volume
                meta["cannon_avg_volume"] = cannon_avg_volume
                if middle_avg_volume >= cannon_avg_volume:
                    return StrategyV2EvaluationResult(signal=0, reason="两根大阳线之间调整阶段未缩量", meta=meta)

            if require_bullish_ma:
                if not _has_bullish_ma_alignment(rows, ma_short, ma_mid, ma_long):
                    return StrategyV2EvaluationResult(signal=0, reason="最新交易日均线未形成多头排列", meta=meta)

            return StrategyV2EvaluationResult(signal=1, reason="双响炮形态成立", meta=meta)

    return StrategyV2EvaluationResult(signal=0, reason="未找到距离最新交易日足够近的有效双响炮组合")


class DoubleCannonStrategy:
    """Classic double-cannon candlestick pattern evaluator."""

    strategy_key = "double_cannon"

    async def evaluate(
        self,
        context: StrategyV2EvaluationContext,
        params: dict[str, Any] | None = None,
    ) -> StrategyV2EvaluationResult:
        params = params or {}
        _, ts_code = _extract_stock_codes(context)
        if not ts_code:
            return StrategyV2EvaluationResult(signal=0, reason="缺少股票代码，无法读取历史 K 线")

        lookback_days = max(_to_int(params.get("lookback_days"), 22), 5)
        ma_long = max(_to_int(params.get("ma_long"), 20), 1)
        load_limit = max(lookback_days + ma_long + 5, 40)
        records = await mongo_manager.find_many(
            "stock_daily",
            {"ts_code": ts_code},
            projection={
                "_id": 0,
                "trade_date": 1,
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "pre_close": 1,
                "pct_chg": 1,
                "vol": 1,
            },
            sort=[("trade_date", -1)],
            limit=load_limit,
        )
        if not records:
            return StrategyV2EvaluationResult(signal=0, reason="未找到股票历史 K 线")
        records.sort(key=lambda item: str(item.get("trade_date")))
        return evaluate_double_cannon_from_candles(records, params=params)


double_cannon_strategy = DoubleCannonStrategy()


STRATEGY_V2_EVALUATORS = {
    OneLineStockPickerStrategy.strategy_key: one_line_stock_picker_strategy,
    DoubleCannonStrategy.strategy_key: double_cannon_strategy,
}


async def evaluate_strategy_v2(
    strategy_key: str,
    context: StrategyV2EvaluationContext,
    params: dict[str, Any] | None = None,
) -> StrategyV2EvaluationResult:
    evaluator = STRATEGY_V2_EVALUATORS.get(strategy_key)
    if evaluator is None:
        raise KeyError(f"Strategy V2 evaluator not found: {strategy_key}")
    return await evaluator.evaluate(context, params=params)
