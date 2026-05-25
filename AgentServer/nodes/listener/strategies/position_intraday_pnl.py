"""
盘中持仓盈亏变化策略

根据持仓数量、当前价和昨收价，计算“今天这一天”对持仓浮盈亏的影响。
适合监控盘中持仓收益大幅变动。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from common.enums import StrategyType
from core.managers import mongo_manager
from core.protocols import MarketSnapshot, StrategyAlert, StrategySubscription

from .base import BaseStrategy

MAX_POSITION_ROWS = 5000


class PositionIntradayPnlStrategy(BaseStrategy):
    @property
    def strategy_type(self) -> str:
        return StrategyType.POSITION_INTRADAY_PNL.value

    async def evaluate(
        self,
        subscription: StrategySubscription,
        snapshot: MarketSnapshot,
        previous_snapshot: Optional[MarketSnapshot] = None,
    ) -> List[StrategyAlert]:
        del previous_snapshot

        group_id = str(subscription.params.get("position_group_id") or "").strip()
        if not group_id:
            return []

        self._current_runtime_position_map = subscription.params.get("_runtime_position_map")
        try:
            position_map = await self._load_position_map(group_id)
            if not position_map:
                return []

            threshold_pct = abs(self._get_numeric_param(subscription.params, "swing_threshold_pct", 2.0))
            direction = str(subscription.params.get("direction") or "both").strip().lower()
            today_key = date.today().strftime("%Y%m%d")

            alerts: List[StrategyAlert] = []
            for ts_code, position in position_map.items():
                quote = snapshot.quotes.get(ts_code)
                if not quote:
                    continue

                quantity = int(position.get("quantity", 0) or 0)
                total_cost = float(position.get("total_cost", 0) or 0)
                if quantity <= 0 or total_cost <= 0:
                    continue

                current_price = self._safe_float(quote.get("price") or quote.get("close"))
                pre_close = self._safe_float(quote.get("pre_close"))
                if current_price is None or current_price <= 0 or pre_close is None or pre_close <= 0:
                    continue

                intraday_pnl_amount = (current_price - pre_close) * quantity
                intraday_pnl_pct = intraday_pnl_amount / total_cost * 100

                if self._should_skip_by_alert_frequency(subscription, ts_code, today_key):
                    continue

                threshold_states = self._load_threshold_states(subscription, ts_code, today_key)
                original_threshold_states = dict(threshold_states)
                up_crossed = self._set_threshold_state(
                    threshold_states,
                    "position_intraday_pnl_up",
                    direction in {"both", "up"} and intraday_pnl_pct >= threshold_pct,
                )
                down_crossed = self._set_threshold_state(
                    threshold_states,
                    "position_intraday_pnl_down",
                    direction in {"both", "down"} and intraday_pnl_pct <= -threshold_pct,
                )
                triggered = up_crossed or down_crossed
                if not triggered:
                    await self._persist_threshold_states_if_changed(
                        subscription=subscription,
                        ts_code=ts_code,
                        today_key=today_key,
                        original_states=original_threshold_states,
                        states=threshold_states,
                    )
                    continue

                alerts.append(
                    self._create_alert(
                        subscription=subscription,
                        ts_code=ts_code,
                        stock_name=str(position.get("name") or quote.get("name") or ts_code),
                        price=current_price,
                        reason=(
                            f"盘中持仓盈亏变动达到阈值，今日影响 {intraday_pnl_pct:.2f}%，"
                            f"昨收 {pre_close:.2f}，现价 {current_price:.2f}"
                        ),
                        extra_data={
                            "event_type": "position_intraday_pnl",
                            "quantity": quantity,
                            "total_cost": round(total_cost, 2),
                            "pre_close": round(pre_close, 4),
                            "current_price": round(current_price, 4),
                            "intraday_pnl_amount": round(intraday_pnl_amount, 2),
                            "intraday_pnl_pct": round(intraday_pnl_pct, 2),
                            "position_group_id": group_id,
                            "position_group_name": subscription.params.get("position_group_name"),
                        },
                    )
                )

                await self._record_alert_trigger(
                    subscription=subscription,
                    ts_code=ts_code,
                    today_key=today_key,
                    extra_updates=self._build_threshold_state_updates(today_key, threshold_states),
                )

            return alerts
        finally:
            self._current_runtime_position_map = None

    async def _load_position_map(self, group_id: str) -> Dict[str, Dict[str, Any]]:
        runtime_position_map = self._resolve_runtime_position_map(group_id)
        if runtime_position_map is not None:
            return runtime_position_map

        docs = await mongo_manager.find_many(
            "trade_review_positions",
            {
                "group_id": group_id,
                "quantity": {"$gt": 0},
                "$or": [
                    {"security_type": {"$exists": False}},
                    {"security_type": "stock"},
                ],
            },
            projection={
                "ts_code": 1,
                "name": 1,
                "quantity": 1,
                "total_cost": 1,
            },
            limit=MAX_POSITION_ROWS,
        )
        return {
            str(doc.get("ts_code")): doc
            for doc in docs
            if doc.get("ts_code")
        }

    def _resolve_runtime_position_map(self, group_id: str) -> Optional[Dict[str, Dict[str, Any]]]:
        del group_id
        runtime_map = getattr(self, "_current_runtime_position_map", None)
        if runtime_map is not None:
            return runtime_map
        return None

    def _safe_float(self, value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
