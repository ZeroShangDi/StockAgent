"""
K 线盘感练习 API
"""

from __future__ import annotations

import math
import random
import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.managers import mongo_manager
from src.analysis.stock_chart_context import build_period_candles
from src.strategy_v2.evaluator import (
    StrategyV2EvaluationResult,
    evaluate_double_cannon_from_candles,
    evaluate_turtle_trading_from_candles,
)
from src.strategy_v2.rules import get_strategy_definition
from .auth import get_current_user_id


router = APIRouter()

DEFAULT_INITIAL_CAPITAL = 100000.0
DEFAULT_INIT_BARS = 80
DEFAULT_FUTURE_BARS = 120
MIN_TOTAL_BARS = 180
MAX_ACTIVE_SESSIONS_TO_CLOSE = 20
PRACTICE_STRATEGY_EVALUATORS = {
    "double_cannon": evaluate_double_cannon_from_candles,
    "turtle_trading": evaluate_turtle_trading_from_candles,
}


class PracticeStartRequest(BaseModel):
    """开始练习请求"""

    init_bars: int = Field(default=DEFAULT_INIT_BARS, ge=30, le=200)
    future_bars: int = Field(default=DEFAULT_FUTURE_BARS, ge=20, le=240)
    initial_capital: float = Field(default=DEFAULT_INITIAL_CAPITAL, ge=10000, le=10000000)
    sample_mode: Literal["random", "strategy"] = "random"
    strategy_key: Optional[str] = None


class PracticeTradeRequest(BaseModel):
    """练习交易请求"""

    action: Literal["buy", "sell", "close"]
    allocation_pct: float = Field(default=1.0, gt=0, le=1.0)


class PracticeCandle(BaseModel):
    ts_code: str
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    pre_close: Optional[float] = None
    change: Optional[float] = None
    pct_chg: Optional[float] = None
    vol: Optional[float] = None
    amount: Optional[float] = None


class PracticeTrade(BaseModel):
    trade_id: str
    action: str
    trade_date: str
    price: float
    shares: int
    amount: float
    allocation_pct: float
    realized_pnl: float = 0.0
    note: Optional[str] = None


class PracticeReveal(BaseModel):
    ts_code: str
    name: str
    industry: Optional[str] = None
    market: Optional[str] = None
    segment_start_date: str
    segment_end_date: str


class PracticeTradeMarker(BaseModel):
    trade_date: str
    price: float
    side: Optional[str] = None
    label: str


class PracticeSessionState(BaseModel):
    session_id: str
    label: str
    status: Literal["active", "completed"]
    initial_capital: float
    cash: float
    position_shares: int
    avg_cost: float
    market_value: float
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    position_pct: float
    total_return_pct: float
    step: int
    total_steps: int
    visible_candles: List[PracticeCandle]
    visible_weekly_candles: List[PracticeCandle]
    visible_monthly_candles: List[PracticeCandle]
    trades: List[PracticeTrade]
    trade_markers: List[PracticeTradeMarker]
    current_trade_date: Optional[str] = None
    latest_close: Optional[float] = None
    can_step: bool
    can_buy: bool
    can_sell: bool
    is_revealed: bool
    sample_mode: Literal["random", "strategy"] = "random"
    strategy_key: Optional[str] = None
    strategy_name: Optional[str] = None
    strategy_signal_date: Optional[str] = None
    strategy_reason: Optional[str] = None
    strategy_meta: Dict[str, Any] = Field(default_factory=dict)
    reveal: Optional[PracticeReveal] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class PracticeSessionSummary(BaseModel):
    session_id: str
    label: str
    status: Literal["active", "completed"]
    total_return_pct: float
    realized_pnl: float
    trade_count: int
    current_trade_date: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    reveal: Optional[PracticeReveal] = None


class PracticeSessionHistoryResult(BaseModel):
    items: List[PracticeSessionSummary]
    total: int
    skip: int
    limit: int


def _sanitize_candle(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ts_code": record["ts_code"],
        "trade_date": record["trade_date"],
        "open": float(record.get("open", 0) or 0),
        "high": float(record.get("high", 0) or 0),
        "low": float(record.get("low", 0) or 0),
        "close": float(record.get("close", 0) or 0),
        "pre_close": record.get("pre_close"),
        "change": record.get("change"),
        "pct_chg": record.get("pct_chg"),
        "vol": record.get("vol"),
        "amount": record.get("amount"),
    }


def _build_state(session: Dict[str, Any]) -> PracticeSessionState:
    candles = session["candles"]
    revealed_count = int(session["revealed_count"])
    visible_candles = candles[:revealed_count]
    latest_close = float(visible_candles[-1]["close"]) if visible_candles else None
    position_shares = int(session.get("position_shares", 0))
    avg_cost = float(session.get("avg_cost", 0.0))
    cash = float(session.get("cash", 0.0))
    market_value = (latest_close or 0.0) * position_shares
    realized_pnl = float(session.get("realized_pnl", 0.0))
    unrealized_pnl = ((latest_close or 0.0) - avg_cost) * position_shares if position_shares else 0.0
    equity = cash + market_value
    position_pct = (market_value / equity * 100) if equity > 0 else 0.0
    initial_capital = float(session["initial_capital"])
    reveal = None
    is_revealed = session["status"] == "completed"

    if is_revealed:
        reveal = PracticeReveal(
            ts_code=session["ts_code"],
            name=session.get("stock_name", session["ts_code"]),
            industry=session.get("industry"),
            market=session.get("market"),
            segment_start_date=candles[0]["trade_date"],
            segment_end_date=candles[-1]["trade_date"],
        )

    action_label_map = {
        "buy": "买入",
        "sell": "卖出",
        "close": "平仓",
        "auto_close": "自动平仓",
    }
    trade_markers = [
        PracticeTradeMarker(
            trade_date=trade.get("trade_date"),
            price=float(trade.get("price", 0) or 0),
            side=trade.get("action"),
            label=(
                f"{action_label_map.get(trade.get('action'), '操作')}"
                f" {round(float(trade.get('allocation_pct', 0) or 0) * 100)}%"
            ),
        )
        for trade in session.get("trades", [])
        if trade.get("trade_date") and trade.get("price")
    ]
    weekly_candles = build_period_candles(visible_candles, "weekly")
    monthly_candles = build_period_candles(visible_candles, "monthly")

    return PracticeSessionState(
        session_id=session["session_id"],
        label=session["label"],
        status=session["status"],
        initial_capital=initial_capital,
        cash=round(cash, 2),
        position_shares=position_shares,
        avg_cost=round(avg_cost, 4),
        market_value=round(market_value, 2),
        equity=round(equity, 2),
        realized_pnl=round(realized_pnl, 2),
        unrealized_pnl=round(unrealized_pnl, 2),
        position_pct=round(position_pct, 2),
        total_return_pct=round((equity - initial_capital) / initial_capital * 100, 2),
        step=revealed_count,
        total_steps=len(candles),
        visible_candles=[PracticeCandle(**_sanitize_candle(item)) for item in reversed(visible_candles)],
        visible_weekly_candles=[PracticeCandle(**_sanitize_candle(item)) for item in weekly_candles],
        visible_monthly_candles=[PracticeCandle(**_sanitize_candle(item)) for item in monthly_candles],
        trades=[PracticeTrade(**trade) for trade in session.get("trades", [])],
        trade_markers=trade_markers,
        current_trade_date=visible_candles[-1]["trade_date"] if visible_candles else None,
        latest_close=round(latest_close, 4) if latest_close is not None else None,
        can_step=revealed_count < len(candles) and session["status"] == "active",
        can_buy=session["status"] == "active" and latest_close is not None and cash >= (latest_close * 100),
        can_sell=session["status"] == "active" and position_shares > 0,
        is_revealed=is_revealed,
        sample_mode=session.get("sample_mode", "random"),
        strategy_key=session.get("strategy_key"),
        strategy_name=session.get("strategy_name"),
        strategy_signal_date=session.get("strategy_signal_date"),
        strategy_reason=session.get("strategy_reason"),
        strategy_meta=session.get("strategy_meta") or {},
        reveal=reveal,
        created_at=session.get("created_at"),
        completed_at=session.get("completed_at"),
    )


def _build_history_summary(session: Dict[str, Any]) -> PracticeSessionSummary:
    state = _build_state(session)
    return PracticeSessionSummary(
        session_id=state.session_id,
        label=state.label,
        status=state.status,
        total_return_pct=state.total_return_pct,
        realized_pnl=state.realized_pnl,
        trade_count=len(state.trades),
        current_trade_date=state.current_trade_date,
        created_at=state.created_at,
        completed_at=state.completed_at,
        reveal=state.reveal,
    )


async def _load_session(session_id: str, user_id: str) -> Dict[str, Any]:
    session = await mongo_manager.find_one(
        "kline_practice_sessions",
        {"session_id": session_id, "user_id": user_id},
    )
    if not session:
        raise HTTPException(status_code=404, detail="练习会话不存在")
    return session


async def _pick_random_segment(required_bars: int) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    sample_size = 40
    for _ in range(6):
        candidates = await mongo_manager.aggregate(
            "stock_basic",
            [
                {"$match": {"ts_code": {"$exists": True, "$ne": None}}},
                {"$sample": {"size": sample_size}},
                {"$project": {"ts_code": 1, "name": 1, "industry": 1, "market": 1}},
            ],
        )

        for candidate in candidates:
            ts_code = candidate["ts_code"]
            candle_count = await mongo_manager.count("stock_daily", {"ts_code": ts_code})
            if candle_count < required_bars:
                continue

            start_max = candle_count - required_bars
            start_index = random.randint(0, max(start_max, 0))
            segment = await mongo_manager.find_many(
                "stock_daily",
                {"ts_code": ts_code},
                sort=[("trade_date", 1)],
                skip=start_index,
                limit=required_bars,
            )
            if len(segment) >= required_bars:
                return candidate, segment

    raise HTTPException(status_code=404, detail="没有找到足够历史数据的股票样本")


def _default_strategy_params(strategy: Dict[str, Any]) -> Dict[str, Any]:
    return {
        str(item.get("key")): item.get("default")
        for item in strategy.get("param_schema", []) or []
        if item.get("key") and "default" in item
    }


def _practice_strategy(strategy_key: str) -> Tuple[Dict[str, Any], Any]:
    strategy = get_strategy_definition(strategy_key)
    evaluator = PRACTICE_STRATEGY_EVALUATORS.get(strategy_key)
    if not strategy or not evaluator:
        raise HTTPException(status_code=400, detail="当前策略暂不支持盘感策略双盲")
    if "scan" not in (strategy.get("supported_scenes") or []):
        raise HTTPException(status_code=400, detail="策略双盲只支持选股策略")
    return strategy, evaluator


async def _pick_strategy_segment(
    required_bars: int,
    init_bars: int,
    strategy_key: str,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    strategy, evaluator = _practice_strategy(strategy_key)
    params = _default_strategy_params(strategy)
    sample_size = 60

    for _ in range(10):
        candidates = await mongo_manager.aggregate(
            "stock_basic",
            [
                {"$match": {"ts_code": {"$exists": True, "$ne": None}}},
                {"$sample": {"size": sample_size}},
                {"$project": {"ts_code": 1, "name": 1, "industry": 1, "market": 1}},
            ],
        )

        for candidate in candidates:
            ts_code = candidate["ts_code"]
            candle_count = await mongo_manager.count("stock_daily", {"ts_code": ts_code})
            if candle_count < required_bars:
                continue

            start_max = candle_count - required_bars
            for _attempt in range(3):
                start_index = random.randint(0, max(start_max, 0))
                segment = await mongo_manager.find_many(
                    "stock_daily",
                    {"ts_code": ts_code},
                    sort=[("trade_date", 1)],
                    skip=start_index,
                    limit=required_bars,
                )
                if len(segment) < required_bars:
                    continue

                visible_prefix = segment[:init_bars]
                result: StrategyV2EvaluationResult = evaluator(visible_prefix, params)
                if result.signal == 1:
                    signal_date = str(visible_prefix[-1].get("trade_date"))
                    return candidate, segment, {
                        "sample_mode": "strategy",
                        "strategy_key": strategy_key,
                        "strategy_name": strategy.get("name") or strategy_key,
                        "strategy_signal_date": signal_date,
                        "strategy_reason": result.reason,
                        "strategy_meta": result.meta,
                    }

    raise HTTPException(status_code=404, detail="没有找到符合该策略的练习样本，请稍后重试或更换策略")


async def _persist_session(session: Dict[str, Any]) -> None:
    await mongo_manager.update_one(
        "kline_practice_sessions",
        {"session_id": session["session_id"], "user_id": session["user_id"]},
        {
            "$set": {
                "status": session["status"],
                "revealed_count": session["revealed_count"],
                "cash": session["cash"],
                "position_shares": session["position_shares"],
                "avg_cost": session["avg_cost"],
                "realized_pnl": session["realized_pnl"],
                "trades": session["trades"],
                "completed_at": session.get("completed_at"),
            }
        },
    )


async def _complete_session(session: Dict[str, Any], auto_close: bool = True) -> Dict[str, Any]:
    if session["status"] == "completed":
        return session

    candles = session["candles"]
    latest_visible = candles[session["revealed_count"] - 1]
    latest_price = float(latest_visible["close"])
    latest_date = latest_visible["trade_date"]
    shares = int(session.get("position_shares", 0))

    if auto_close and shares > 0:
        avg_cost = float(session.get("avg_cost", 0.0))
        amount = round(latest_price * shares, 2)
        realized = round((latest_price - avg_cost) * shares, 2)
        session["cash"] = round(float(session["cash"]) + amount, 2)
        session["realized_pnl"] = round(float(session["realized_pnl"]) + realized, 2)
        session["position_shares"] = 0
        session["avg_cost"] = 0.0
        session.setdefault("trades", []).append(
            {
                "trade_id": uuid.uuid4().hex,
                "action": "auto_close",
                "trade_date": latest_date,
                "price": latest_price,
                "shares": shares,
                "amount": amount,
                "allocation_pct": 1.0,
                "realized_pnl": realized,
                "note": "练习结束自动平仓",
            }
        )

    session["status"] = "completed"
    session["revealed_count"] = len(candles)
    session["completed_at"] = datetime.utcnow()
    await _persist_session(session)
    return session


@router.get("/kline/active", response_model=Optional[PracticeSessionState])
async def get_active_practice_session(user_id: str = Depends(get_current_user_id)):
    """获取当前进行中的练习会话"""
    sessions = await mongo_manager.find_many(
        "kline_practice_sessions",
        {"user_id": user_id, "status": "active"},
        sort=[("created_at", -1)],
        limit=1,
    )
    return _build_state(sessions[0]) if sessions else None


@router.get("/kline/latest", response_model=Optional[PracticeSessionState])
async def get_latest_practice_session(user_id: str = Depends(get_current_user_id)):
    """获取最近一局练习会话（优先返回进行中）"""
    active = await mongo_manager.find_one(
        "kline_practice_sessions",
        {"user_id": user_id, "status": "active"},
    )
    if active:
        return _build_state(active)

    recent = await mongo_manager.find_many(
        "kline_practice_sessions",
        {"user_id": user_id},
        sort=[("created_at", -1)],
        limit=1,
    )
    return _build_state(recent[0]) if recent else None


@router.get("/kline/history", response_model=PracticeSessionHistoryResult)
async def get_practice_session_history(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    user_id: str = Depends(get_current_user_id),
):
    history_filter = {"user_id": user_id, "status": "completed"}
    total = await mongo_manager.count("kline_practice_sessions", history_filter)
    sessions = await mongo_manager.find_many(
        "kline_practice_sessions",
        history_filter,
        sort=[("completed_at", -1), ("created_at", -1)],
        skip=skip,
        limit=limit,
    )
    return PracticeSessionHistoryResult(
        items=[_build_history_summary(item) for item in sessions],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/kline/{session_id}", response_model=PracticeSessionState)
async def get_practice_session(session_id: str, user_id: str = Depends(get_current_user_id)):
    """获取练习会话状态"""
    session = await _load_session(session_id, user_id)
    return _build_state(session)


@router.post("/kline/start", response_model=PracticeSessionState)
async def start_practice_session(
    body: Optional[PracticeStartRequest] = None,
    user_id: str = Depends(get_current_user_id),
):
    """开始新的 K 线练习会话"""
    body = body or PracticeStartRequest()
    required_bars = max(body.init_bars + body.future_bars, MIN_TOTAL_BARS)

    active_sessions = await mongo_manager.find_many(
        "kline_practice_sessions",
        {"user_id": user_id, "status": "active"},
        sort=[("created_at", -1)],
        limit=MAX_ACTIVE_SESSIONS_TO_CLOSE,
    )
    for active_session in active_sessions:
        await _complete_session(active_session)

    strategy_sample: Dict[str, Any] = {"sample_mode": "random"}
    if body.sample_mode == "strategy":
        if not body.strategy_key:
            raise HTTPException(status_code=400, detail="策略双盲需要选择策略")
        stock, segment, strategy_sample = await _pick_strategy_segment(
            required_bars,
            body.init_bars,
            body.strategy_key,
        )
    else:
        stock, segment = await _pick_random_segment(required_bars)
    sanitized_segment = [_sanitize_candle(item) for item in segment]

    session = {
        "session_id": uuid.uuid4().hex,
        "user_id": user_id,
        "label": f"{'策略样本' if body.sample_mode == 'strategy' else '训练样本'} {datetime.now().strftime('%m%d')}-{uuid.uuid4().hex[:4].upper()}",
        "status": "active",
        "ts_code": stock["ts_code"],
        "stock_name": stock.get("name", stock["ts_code"]),
        "industry": stock.get("industry"),
        "market": stock.get("market"),
        **strategy_sample,
        "initial_capital": round(body.initial_capital, 2),
        "cash": round(body.initial_capital, 2),
        "position_shares": 0,
        "avg_cost": 0.0,
        "realized_pnl": 0.0,
        "revealed_count": body.init_bars,
        "candles": sanitized_segment,
        "trades": [],
        "created_at": datetime.utcnow(),
        "completed_at": None,
    }
    await mongo_manager.insert_one("kline_practice_sessions", session)
    return _build_state(session)


@router.post("/kline/{session_id}/step", response_model=PracticeSessionState)
async def step_practice_session(
    session_id: str,
    steps: int = Query(default=1, ge=1, le=10),
    user_id: str = Depends(get_current_user_id),
):
    """向前推进若干根 K 线"""
    session = await _load_session(session_id, user_id)
    if session["status"] != "active":
        return _build_state(session)

    session["revealed_count"] = min(
        len(session["candles"]),
        int(session["revealed_count"]) + steps,
    )
    if session["revealed_count"] >= len(session["candles"]):
        await _complete_session(session)
        return _build_state(session)

    await _persist_session(session)
    return _build_state(session)


@router.post("/kline/{session_id}/trade", response_model=PracticeSessionState)
async def trade_practice_session(
    session_id: str,
    body: PracticeTradeRequest,
    user_id: str = Depends(get_current_user_id),
):
    """在当前 K 线位置进行模拟买卖"""
    session = await _load_session(session_id, user_id)
    if session["status"] != "active":
        raise HTTPException(status_code=400, detail="练习已结束，不能继续交易")

    candles = session["candles"]
    current = candles[int(session["revealed_count"]) - 1]
    price = float(current["close"])
    trade_date = current["trade_date"]
    cash = float(session["cash"])
    shares = int(session.get("position_shares", 0))
    avg_cost = float(session.get("avg_cost", 0.0))
    amount = 0.0
    realized_pnl = 0.0
    trade_shares = 0

    if body.action == "buy":
        budget = cash * body.allocation_pct
        trade_shares = math.floor(budget / price / 100) * 100
        if trade_shares <= 0:
            raise HTTPException(status_code=400, detail="可用资金不足，无法按 100 股整数倍买入")
        amount = round(price * trade_shares, 2)
        total_cost = avg_cost * shares + amount
        shares += trade_shares
        session["cash"] = round(cash - amount, 2)
        session["avg_cost"] = round(total_cost / shares, 4)
    elif body.action == "sell":
        if shares <= 0:
            raise HTTPException(status_code=400, detail="当前没有持仓可卖出")
        trade_shares = math.floor((shares * body.allocation_pct) / 100) * 100
        if trade_shares <= 0:
            raise HTTPException(status_code=400, detail="当前持仓不足，无法按 100 股整数倍卖出")
        amount = round(price * trade_shares, 2)
        realized_pnl = round((price - avg_cost) * trade_shares, 2)
        session["cash"] = round(cash + amount, 2)
        session["realized_pnl"] = round(float(session["realized_pnl"]) + realized_pnl, 2)
        shares -= trade_shares
        if shares == 0:
            session["avg_cost"] = 0.0
    else:
        if shares <= 0:
            raise HTTPException(status_code=400, detail="当前没有持仓可平仓")
        trade_shares = shares
        amount = round(price * trade_shares, 2)
        realized_pnl = round((price - avg_cost) * trade_shares, 2)
        session["cash"] = round(cash + amount, 2)
        session["realized_pnl"] = round(float(session["realized_pnl"]) + realized_pnl, 2)
        shares = 0
        session["avg_cost"] = 0.0

    session["position_shares"] = shares
    session.setdefault("trades", []).append(
        {
            "trade_id": uuid.uuid4().hex,
            "action": body.action,
            "trade_date": trade_date,
            "price": round(price, 4),
            "shares": trade_shares,
            "amount": amount,
            "allocation_pct": body.allocation_pct,
            "realized_pnl": realized_pnl,
            "note": None,
        }
    )

    await _persist_session(session)
    return _build_state(session)


@router.post("/kline/{session_id}/finish", response_model=PracticeSessionState)
async def finish_practice_session(session_id: str, user_id: str = Depends(get_current_user_id)):
    """结束练习并揭晓真实股票"""
    session = await _load_session(session_id, user_id)
    session = await _complete_session(session)
    return _build_state(session)
