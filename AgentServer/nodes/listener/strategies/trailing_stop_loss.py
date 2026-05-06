"""
移动止损策略

在持仓期间持续追踪最高价，当价格相对最高价回撤到一定比例时触发预警。

特点:
- 每只股票单独保存入场价、最高价和回撤阈值
- 最高价与最后触发日期持久化到 strategy_subscriptions.params.stock_configs
- 节点重启后仍可继续追踪历史最高价
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from common.enums import StrategyType
from core.managers import mongo_manager
from core.protocols import MarketSnapshot, StrategyAlert, StrategySubscription

from .base import BaseStrategy


class TrailingStopLossStrategy(BaseStrategy):
    """移动止损监听策略"""

    def __init__(self) -> None:
        self.logger = logging.getLogger("strategy.trailing_stop_loss")

    @property
    def strategy_type(self) -> str:
        return StrategyType.TRAILING_STOP_LOSS.value

    async def evaluate(
        self,
        subscription: StrategySubscription,
        snapshot: MarketSnapshot,
        previous_snapshot: Optional[MarketSnapshot] = None,
    ) -> List[StrategyAlert]:
        del previous_snapshot

        alerts: List[StrategyAlert] = []
        stock_configs = subscription.params.get("stock_configs", {}) or {}
        if not isinstance(stock_configs, dict):
            return alerts

        once_per_day = bool(subscription.params.get("once_per_day", True))
        today_key = date.today().strftime("%Y%m%d")
        watch_stocks = self._get_watch_stocks(subscription, snapshot)

        for ts_code, quote in watch_stocks.items():
            config = stock_configs.get(ts_code)
            if not isinstance(config, dict) or not config.get("enabled", True):
                continue

            current_price = self._safe_float(quote.get("price") or quote.get("close"))
            current_high = self._safe_float(quote.get("high")) or current_price
            current_low = self._safe_float(quote.get("low")) or current_price
            if current_price is None or current_price <= 0:
                continue

            entry_price = self._safe_float(config.get("entry_price"))
            highest_price = self._safe_float(config.get("highest_price")) or entry_price
            if entry_price is None or entry_price <= 0 or highest_price is None or highest_price <= 0:
                continue

            runtime_updates: Dict[str, Any] = {}
            if current_high is not None and current_high > highest_price:
                highest_price = current_high
                runtime_updates["highest_price"] = round(current_high, 4)
                runtime_updates["highest_price_date"] = today_key

            trail_pct = max(
                self._normalize_percent_value(
                    self._get_numeric_param(config, "trail_pct", 6.0)
                ),
                0.0,
            )
            trigger_price = highest_price * (1 - trail_pct)
            last_triggered_date = str(config.get("last_triggered_date") or "")

            if current_price <= trigger_price or (current_low is not None and current_low <= trigger_price):
                if not (once_per_day and last_triggered_date == today_key):
                    alerts.append(
                        self._create_alert(
                            subscription=subscription,
                            ts_code=ts_code,
                            stock_name=str(quote.get("name") or ts_code),
                            price=current_price,
                            reason=(
                                f"价格触发移动止损，当前 {current_price:.2f}，"
                                f"最高价 {highest_price:.2f}，止损线 {trigger_price:.2f}"
                            ),
                            extra_data={
                                "event_type": "trailing_stop_loss",
                                "entry_price": round(entry_price, 4),
                                "entry_date": config.get("entry_date"),
                                "highest_price": round(highest_price, 4),
                                "highest_price_date": runtime_updates.get(
                                    "highest_price_date",
                                    config.get("highest_price_date"),
                                ),
                                "trail_pct": round(trail_pct * 100, 4),
                                "stop_loss_price": round(trigger_price, 4),
                                "current_low": current_low,
                            },
                        )
                    )
                    runtime_updates["last_triggered_date"] = today_key

            if runtime_updates:
                await self._persist_runtime_fields(
                    subscription=subscription,
                    ts_code=ts_code,
                    updates=runtime_updates,
                )

        return alerts

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
