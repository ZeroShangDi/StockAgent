"""
持仓总盈亏阈值策略

针对交割单推导出的当前持仓，按持仓成本计算整体浮盈亏比例。
适合做持仓级别的止盈 / 止损提醒。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from common.enums import StrategyType
from core.managers import mongo_manager
from core.protocols import MarketSnapshot, StrategyAlert, StrategySubscription

from .base import BaseStrategy


class PositionPnlStrategy(BaseStrategy):
    @property
    def strategy_type(self) -> str:
        return StrategyType.POSITION_PNL.value

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

            loss_threshold = abs(self._get_numeric_param(subscription.params, "loss_threshold_pct", 3.0))
            profit_threshold = abs(self._get_numeric_param(subscription.params, "profit_threshold_pct", 8.0))
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
                if current_price is None or current_price <= 0:
                    continue

                market_value = current_price * quantity
                pnl_amount = market_value - total_cost
                pnl_pct = pnl_amount / total_cost * 100

                threshold_states = self._load_threshold_states(subscription, ts_code, today_key)
                original_threshold_states = dict(threshold_states)
                loss_crossed = self._set_threshold_state(
                    threshold_states,
                    "position_pnl_loss",
                    loss_threshold > 0 and pnl_pct <= -loss_threshold,
                )
                profit_crossed = self._set_threshold_state(
                    threshold_states,
                    "position_pnl_profit",
                    profit_threshold > 0 and pnl_pct >= profit_threshold,
                )

                trigger_type = ""
                if loss_crossed:
                    trigger_type = "loss"
                elif profit_crossed:
                    trigger_type = "profit"

                if self._should_skip_by_alert_frequency(subscription, ts_code, today_key):
                    continue

                if not trigger_type:
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
                            f"持仓盈亏达到阈值，当前盈亏 {pnl_pct:.2f}%，"
                            f"持仓成本 {total_cost:.2f}，现价 {current_price:.2f}"
                        ),
                        extra_data={
                            "event_type": "position_pnl",
                            "trigger_type": trigger_type,
                            "quantity": quantity,
                            "total_cost": round(total_cost, 2),
                            "market_value": round(market_value, 2),
                            "pnl_amount": round(pnl_amount, 2),
                            "pnl_pct": round(pnl_pct, 2),
                            "position_group_id": group_id,
                            "position_group_name": subscription.params.get("position_group_name"),
                        },
                    )
                )

                await self._record_alert_trigger(
                    subscription=subscription,
                    ts_code=ts_code,
                    today_key=today_key,
                    extra_updates={
                        "last_trigger_type": trigger_type,
                        **self._build_threshold_state_updates(today_key, threshold_states),
                    },
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
