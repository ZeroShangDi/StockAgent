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

        position_map = await self._load_position_map(group_id)
        if not position_map:
            return []

        once_per_day = bool(subscription.params.get("once_per_day", True))
        threshold_pct = abs(self._get_numeric_param(subscription.params, "swing_threshold_pct", 2.0))
        direction = str(subscription.params.get("direction") or "both").strip().lower()
        today_key = date.today().strftime("%Y%m%d")
        stock_configs = subscription.params.get("stock_configs", {}) or {}

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
            config = stock_configs.get(ts_code, {}) if isinstance(stock_configs, dict) else {}
            last_triggered_date = str((config or {}).get("last_triggered_date") or "")

            triggered = False
            if direction in {"both", "up"} and intraday_pnl_pct >= threshold_pct:
                triggered = True
            if direction in {"both", "down"} and intraday_pnl_pct <= -threshold_pct:
                triggered = True
            if not triggered:
                continue

            if once_per_day and last_triggered_date == today_key:
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

            await self._persist_runtime_fields(
                subscription=subscription,
                ts_code=ts_code,
                updates={"last_triggered_date": today_key},
            )

        return alerts

    async def _load_position_map(self, group_id: str) -> Dict[str, Dict[str, Any]]:
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

    async def _persist_runtime_fields(
        self,
        subscription: StrategySubscription,
        ts_code: str,
        updates: Dict[str, Any],
    ) -> None:
        record = await mongo_manager.find_one(
            "strategy_subscriptions",
            {"strategy_id": subscription.strategy_id},
            projection={"params": 1},
        )
        if not record:
            return

        params = dict(record.get("params", {}) or {})
        stock_configs = dict(params.get("stock_configs", {}) or {})
        current_config = dict(stock_configs.get(ts_code, {}) or {})
        current_config.update(updates)
        stock_configs[ts_code] = current_config
        params["stock_configs"] = stock_configs

        await mongo_manager.update_one(
            "strategy_subscriptions",
            {"strategy_id": subscription.strategy_id},
            {"$set": {"params": params}},
        )

    def _safe_float(self, value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
