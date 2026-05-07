"""
固定止损策略

从加入监听时的参考价开始，若后续价格下跌到固定阈值，则触发预警。

特点:
- 每只股票单独保存参考价与止损比例
- 状态持久化到 strategy_subscriptions.params.stock_configs
- 节点重启后仍能继续使用原有止损基准
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from common.enums import StrategyType
from core.protocols import MarketSnapshot, StrategyAlert, StrategySubscription

from .base import BaseStrategy


class FixedStopLossStrategy(BaseStrategy):
    """固定止损监听策略"""

    def __init__(self) -> None:
        self.logger = logging.getLogger("strategy.fixed_stop_loss")

    @property
    def strategy_type(self) -> str:
        return StrategyType.FIXED_STOP_LOSS.value

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

        watch_stocks = self._get_watch_stocks(subscription, snapshot)
        today_key = date.today().strftime("%Y%m%d")

        for ts_code, quote in watch_stocks.items():
            config = stock_configs.get(ts_code)
            if not isinstance(config, dict) or not config.get("enabled", True):
                continue

            current_price = self._safe_float(quote.get("price") or quote.get("close"))
            current_low = self._safe_float(quote.get("low")) or current_price
            if current_price is None or current_price <= 0:
                continue

            reference_price = self._safe_float(config.get("reference_price"))
            if reference_price is None or reference_price <= 0:
                continue

            stop_loss_pct = max(
                self._normalize_percent_value(
                    self._get_numeric_param(config, "stop_loss_pct", 8.0)
                ),
                0.0,
            )
            trigger_price = reference_price * (1 - stop_loss_pct)
            if self._should_skip_by_alert_frequency(subscription, ts_code, today_key):
                continue

            if current_price > trigger_price and (current_low is None or current_low > trigger_price):
                continue

            alerts.append(
                self._create_alert(
                    subscription=subscription,
                    ts_code=ts_code,
                    stock_name=str(quote.get("name") or ts_code),
                    price=current_price,
                    reason=(
                        f"价格触发固定止损，当前 {current_price:.2f}，"
                        f"参考价 {reference_price:.2f}，止损线 {trigger_price:.2f}"
                    ),
                    extra_data={
                        "event_type": "fixed_stop_loss",
                        "reference_price": round(reference_price, 4),
                        "reference_date": config.get("reference_date"),
                        "stop_loss_pct": round(stop_loss_pct * 100, 4),
                        "stop_loss_price": round(trigger_price, 4),
                        "current_low": current_low,
                    },
                )
            )

            await self._record_alert_trigger(
                subscription=subscription,
                ts_code=ts_code,
                today_key=today_key,
            )

        return alerts

    def _safe_float(self, value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
