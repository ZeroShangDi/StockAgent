"""Strategy V2 evaluators.

The first real V2 evaluator adapts the existing one-line stock picker into the
unified -1/0/1 strategy contract without changing the legacy picker API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

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


STRATEGY_V2_EVALUATORS = {
    OneLineStockPickerStrategy.strategy_key: one_line_stock_picker_strategy,
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
