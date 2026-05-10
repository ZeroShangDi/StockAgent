"""
分钟异动策略

监控股票在最近 N 分钟内的涨跌幅变化，
当涨跌幅超过设定阈值时触发预警。
"""

from collections import deque
from datetime import date, datetime, timedelta
from typing import Any, Deque, Dict, List, Optional, Tuple
import logging

from common.enums import StrategyType
from core.protocols import MarketSnapshot, StrategyAlert, StrategySubscription

from .base import BaseStrategy


HistoryPoint = Tuple[datetime, float]


class IntradayPriceMoveStrategy(BaseStrategy):
    """
    分钟异动策略

    参数:
    - interval_minutes: 区间分钟数
    - threshold_pct: 涨跌幅阈值 (%)
    - direction: up / down / both
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger("strategy.intraday_price_move")
        self._price_history: Dict[str, Deque[HistoryPoint]] = {}
        self._history_day: Optional[str] = None

    @property
    def strategy_type(self) -> str:
        return StrategyType.INTRADAY_PRICE_MOVE.value

    async def evaluate(
        self,
        subscription: StrategySubscription,
        snapshot: MarketSnapshot,
        previous_snapshot: Optional[MarketSnapshot] = None,
    ) -> List[StrategyAlert]:
        alerts: List[StrategyAlert] = []

        today_key = date.today().strftime("%Y%m%d")
        self._reset_if_new_day(today_key)

        interval_minutes = max(
            1,
            int(self._get_numeric_param(subscription.params, "interval_minutes", 5.0)),
        )
        threshold_pct = abs(
            self._get_numeric_param(subscription.params, "threshold_pct", 2.0)
        )
        direction = str(subscription.params.get("direction") or "both").strip().lower()
        snapshot_time = snapshot.snapshot_time

        watch_stocks = self._get_watch_stocks(subscription, snapshot)
        history_retention_minutes = max(interval_minutes * 3, interval_minutes + 10)

        for ts_code, quote in watch_stocks.items():
            current_price = self._safe_float(quote.get("price"))
            if not current_price or current_price <= 0:
                continue

            history = self._price_history.setdefault(ts_code, deque())
            self._append_history_point(history, snapshot_time, current_price)
            self._trim_history(history, snapshot_time, history_retention_minutes)

            if self._should_skip_by_alert_frequency(subscription, ts_code, today_key):
                continue

            reference_point = self._get_reference_point(history, snapshot_time, interval_minutes)
            if not reference_point:
                continue

            reference_time, reference_price = reference_point
            if reference_price <= 0:
                continue

            move_pct = (current_price / reference_price - 1) * 100
            threshold_states = self._load_threshold_states(subscription, ts_code, today_key)
            original_threshold_states = dict(threshold_states)
            up_crossed = self._set_threshold_state(
                threshold_states,
                "intraday_price_move_up",
                direction in {"up", "both"} and move_pct >= threshold_pct,
            )
            down_crossed = self._set_threshold_state(
                threshold_states,
                "intraday_price_move_down",
                direction in {"down", "both"} and move_pct <= -threshold_pct,
            )

            triggered = False
            reason = ""

            if up_crossed:
                triggered = True
                reason = f"{interval_minutes}分钟涨幅 {move_pct:.2f}% 超过阈值 {threshold_pct:.2f}%"
            elif down_crossed:
                triggered = True
                reason = f"{interval_minutes}分钟跌幅 {abs(move_pct):.2f}% 超过阈值 {threshold_pct:.2f}%"

            if not triggered:
                await self._persist_threshold_states_if_changed(
                    subscription=subscription,
                    ts_code=ts_code,
                    today_key=today_key,
                    original_states=original_threshold_states,
                    states=threshold_states,
                )
                continue

            stock_name = str(quote.get("name") or ts_code)
            alert = self._create_alert(
                subscription=subscription,
                ts_code=ts_code,
                stock_name=stock_name,
                price=current_price,
                reason=reason,
                extra_data={
                    "interval_minutes": interval_minutes,
                    "threshold_pct": threshold_pct,
                    "direction": direction,
                    "move_pct": round(move_pct, 4),
                    "reference_price": round(reference_price, 4),
                    "reference_time": reference_time.isoformat(),
                    "current_price": round(current_price, 4),
                    "snapshot_time": snapshot_time.isoformat(),
                },
            )
            alerts.append(alert)
            await self._record_alert_trigger(
                subscription=subscription,
                ts_code=ts_code,
                today_key=today_key,
                extra_updates={
                    **self._build_threshold_state_updates(today_key, threshold_states),
                    "last_reference_time": reference_time.isoformat(),
                    "last_reference_price": reference_price,
                    "last_move_pct": move_pct,
                },
            )
            self.logger.info(
                "[ALERT] %s %s: %s",
                ts_code,
                stock_name,
                reason,
            )

        return alerts

    def _reset_if_new_day(self, today_key: str) -> None:
        if self._history_day == today_key:
            return
        self._history_day = today_key
        self._price_history.clear()

    def _append_history_point(
        self,
        history: Deque[HistoryPoint],
        snapshot_time: datetime,
        price: float,
    ) -> None:
        if history and history[-1][0] == snapshot_time:
            history[-1] = (snapshot_time, price)
            return
        history.append((snapshot_time, price))

    def _trim_history(
        self,
        history: Deque[HistoryPoint],
        snapshot_time: datetime,
        retention_minutes: int,
    ) -> None:
        cutoff = snapshot_time - timedelta(minutes=retention_minutes)
        while history and history[0][0] < cutoff:
            history.popleft()

    def _get_reference_point(
        self,
        history: Deque[HistoryPoint],
        snapshot_time: datetime,
        interval_minutes: int,
    ) -> Optional[HistoryPoint]:
        target_time = snapshot_time - timedelta(minutes=interval_minutes)
        selected: Optional[HistoryPoint] = None
        for point in history:
            if point[0] <= target_time:
                selected = point
            else:
                break
        return selected

    def _safe_float(self, value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
