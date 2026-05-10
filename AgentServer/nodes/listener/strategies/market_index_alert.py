"""
指数指标预警策略

对市场整体指标进行监听：
- 三大指数涨跌幅
- 涨跌家数 / 涨跌比
- 涨跌停家数
- 北向资金净流入/净流出

任一启用条件首次越线时触发一条合并预警。
"""

from __future__ import annotations

from datetime import date
import logging
from typing import Any, Dict, List, Optional, Tuple

from core.managers import mongo_manager, redis_manager
from core.protocols import MarketSnapshot, StrategyAlert, StrategySubscription, StrategyType

from .base import BaseStrategy


INDEX_FIELD_MAP = {
    "000001.SH": ("sh_index", "sh_change", "上证指数"),
    "399001.SZ": ("sz_index", "sz_change", "深证成指"),
    "399006.SZ": ("cyb_index", "cyb_change", "创业板指"),
}


class MarketIndexAlertStrategy(BaseStrategy):
    def __init__(self) -> None:
        self.logger = logging.getLogger("strategy.market_index_alert")

    @property
    def strategy_type(self) -> str:
        return StrategyType.MARKET_INDEX_ALERT.value

    async def evaluate(
        self,
        subscription: StrategySubscription,
        snapshot: MarketSnapshot,
        previous_snapshot: Optional[MarketSnapshot] = None,
    ) -> List[StrategyAlert]:
        today_key = date.today().strftime("%Y%m%d")
        market_key = "__MARKET__"
        if self._should_skip_by_alert_frequency(subscription, market_key, today_key):
            return []

        realtime_market = await redis_manager.get_realtime_market_data() or {}
        daily_stats = await self._get_latest_daily_stats()
        index_code = str(subscription.params.get("index_code") or "000001.SH").strip().upper()
        index_value, index_change, index_name = self._resolve_index_metrics(index_code, realtime_market)

        up_count = self._to_float(realtime_market.get("up_count"), snapshot.up_count)
        down_count = self._to_float(realtime_market.get("down_count"), snapshot.down_count)
        limit_up_count = self._to_float(realtime_market.get("limit_up"), snapshot.limit_up_count)
        limit_down_count = self._to_float(realtime_market.get("limit_down"), snapshot.limit_down_count)
        north_money = self._to_float(daily_stats.get("north_money"), 0.0)
        threshold_states = self._load_threshold_states(subscription, market_key, today_key)
        original_threshold_states = dict(threshold_states)
        triggered_conditions: List[Dict[str, Any]] = []

        self._append_condition_if_triggered(
            threshold_states,
            triggered_conditions,
            key="index_rise",
            enabled=bool(subscription.params.get("index_rise_enabled", True)),
            current_value=index_change,
            threshold=self._get_numeric_param(subscription.params, "index_rise_threshold", 1.5),
            comparator="gte",
            label=f"{index_name}涨幅",
            unit="%",
        )
        self._append_condition_if_triggered(
            threshold_states,
            triggered_conditions,
            key="index_fall",
            enabled=bool(subscription.params.get("index_fall_enabled", True)),
            current_value=index_change,
            threshold=self._get_numeric_param(subscription.params, "index_fall_threshold", 1.5),
            comparator="lte_negative",
            label=f"{index_name}跌幅",
            unit="%",
        )
        self._append_condition_if_triggered(
            threshold_states,
            triggered_conditions,
            key="up_count",
            enabled=bool(subscription.params.get("up_count_enabled", False)),
            current_value=up_count,
            threshold=self._get_numeric_param(subscription.params, "up_count_threshold", 3000.0),
            comparator="gte",
            label="上涨家数",
            unit="家",
        )
        self._append_condition_if_triggered(
            threshold_states,
            triggered_conditions,
            key="down_count",
            enabled=bool(subscription.params.get("down_count_enabled", False)),
            current_value=down_count,
            threshold=self._get_numeric_param(subscription.params, "down_count_threshold", 3000.0),
            comparator="gte",
            label="下跌家数",
            unit="家",
        )
        self._append_condition_if_triggered(
            threshold_states,
            triggered_conditions,
            key="limit_up_count",
            enabled=bool(subscription.params.get("limit_up_enabled", False)),
            current_value=limit_up_count,
            threshold=self._get_numeric_param(subscription.params, "limit_up_threshold", 80.0),
            comparator="gte",
            label="涨停家数",
            unit="家",
        )
        self._append_condition_if_triggered(
            threshold_states,
            triggered_conditions,
            key="limit_down_count",
            enabled=bool(subscription.params.get("limit_down_enabled", False)),
            current_value=limit_down_count,
            threshold=self._get_numeric_param(subscription.params, "limit_down_threshold", 20.0),
            comparator="gte",
            label="跌停家数",
            unit="家",
        )
        self._append_condition_if_triggered(
            threshold_states,
            triggered_conditions,
            key="north_money_in",
            enabled=bool(subscription.params.get("north_money_in_enabled", False)),
            current_value=north_money,
            threshold=self._get_numeric_param(subscription.params, "north_money_in_threshold", 20.0),
            comparator="gte",
            label="北向资金净流入",
            unit="亿",
        )
        self._append_condition_if_triggered(
            threshold_states,
            triggered_conditions,
            key="north_money_out",
            enabled=bool(subscription.params.get("north_money_out_enabled", False)),
            current_value=north_money,
            threshold=self._get_numeric_param(subscription.params, "north_money_out_threshold", 20.0),
            comparator="lte_negative",
            label="北向资金净流出",
            unit="亿",
        )

        if not triggered_conditions:
            await self._persist_threshold_states_if_changed(
                subscription=subscription,
                ts_code=market_key,
                today_key=today_key,
                original_states=original_threshold_states,
                states=threshold_states,
            )
            return []

        reason = "；".join(item["reason"] for item in triggered_conditions)
        alert = self._create_alert(
            subscription=subscription,
            ts_code=index_code,
            stock_name=index_name,
            price=index_value,
            reason=reason,
            extra_data={
                "index_code": index_code,
                "index_name": index_name,
                "index_pct_chg": round(index_change, 4),
                "up_count": int(up_count),
                "down_count": int(down_count),
                "limit_up_count": int(limit_up_count),
                "limit_down_count": int(limit_down_count),
                "north_money": round(north_money, 4),
                "triggered_conditions": triggered_conditions,
            },
        )
        await self._record_alert_trigger(
            subscription=subscription,
            ts_code=market_key,
            today_key=today_key,
            extra_updates=self._build_threshold_state_updates(today_key, threshold_states),
        )
        return [alert]

    async def _get_latest_daily_stats(self) -> Dict[str, Any]:
        record = await mongo_manager.find_one(
            "daily_stats",
            {},
            sort=[("trade_date", -1)],
            projection={"trade_date": 1, "north_money": 1, "_id": 0},
        )
        return dict(record or {})

    def _resolve_index_metrics(self, index_code: str, market_data: Dict[str, Any]) -> Tuple[float, float, str]:
        index_field, change_field, index_name = INDEX_FIELD_MAP.get(
            index_code,
            ("sh_index", "sh_change", "上证指数"),
        )
        return (
            self._to_float(market_data.get(index_field), 0.0),
            self._to_float(market_data.get(change_field), 0.0),
            index_name,
        )

    def _append_condition_if_triggered(
        self,
        states: Dict[str, bool],
        bucket: List[Dict[str, Any]],
        *,
        key: str,
        enabled: bool,
        current_value: float,
        threshold: float,
        comparator: str,
        label: str,
        unit: str,
    ) -> None:
        is_active = enabled and self._is_threshold_active(current_value, threshold, comparator)
        crossed = self._set_threshold_state(states, key, is_active)
        if not crossed:
            return
        display_threshold = -threshold if comparator == "lte_negative" else threshold
        bucket.append(
            {
                "key": key,
                "current_value": round(current_value, 4),
                "threshold": round(display_threshold, 4),
                "reason": f"{label} {current_value:.2f}{unit} 触发阈值 {display_threshold:.2f}{unit}",
            }
        )

    def _is_threshold_active(self, current_value: float, threshold: float, comparator: str) -> bool:
        if comparator == "gte":
            return current_value >= threshold
        if comparator == "lte_negative":
            target = -abs(threshold)
            return current_value <= target
        return False

    def _to_float(self, value: Any, default: float) -> float:
        try:
            if value is None:
                return float(default)
            return float(value)
        except (TypeError, ValueError):
            return float(default)
