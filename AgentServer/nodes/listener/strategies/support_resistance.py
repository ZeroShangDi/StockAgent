"""
撑压线策略

根据两组点位分别构成支撑线和压力线，在最新价格接近或突破线位时触发预警。

特点:
- 每只股票单独配置点位
- 线的横轴使用股票实际交易日序列，不包含节假日和停牌日
- 支撑点未填价格时默认取当日最低价
- 压力点未填价格时默认取当日最高价
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import logging
from typing import Any, Dict, List, Optional

from common.enums import StrategyType
from core.managers import mongo_manager
from core.protocols import MarketSnapshot, StrategyAlert, StrategySubscription

from .base import BaseStrategy


@dataclass
class LineDefinition:
    line_type: str
    points: List[Dict[str, Any]]


class SupportResistanceStrategy(BaseStrategy):
    """撑压线监听策略"""

    def __init__(self) -> None:
        self.logger = logging.getLogger("strategy.support_resistance")
        self._trade_date_cache: Dict[str, List[str]] = {}
        self._cache_date: Optional[str] = None

    @property
    def strategy_type(self) -> str:
        return StrategyType.SUPPORT_RESISTANCE.value

    async def evaluate(
        self,
        subscription: StrategySubscription,
        snapshot: MarketSnapshot,
        previous_snapshot: Optional[MarketSnapshot] = None,
    ) -> List[StrategyAlert]:
        del previous_snapshot
        self._ensure_daily_state()

        alerts: List[StrategyAlert] = []
        near_threshold = self._normalize_percentage_param(
            self._get_numeric_param(subscription.params, "near_threshold_pct", 1.0)
        )
        breakout_threshold = self._normalize_percentage_param(
            self._get_numeric_param(subscription.params, "breakout_threshold_pct", 0.5)
        )
        stock_configs = subscription.params.get("stock_configs", {}) or {}
        if not isinstance(stock_configs, dict):
            return alerts

        watch_stocks = self._get_watch_stocks(subscription, snapshot)
        today_key = date.today().strftime("%Y%m%d")

        for ts_code, quote in watch_stocks.items():
            config = stock_configs.get(ts_code)
            if not isinstance(config, dict):
                continue

            stock_alerts = await self._evaluate_stock(
                subscription=subscription,
                ts_code=ts_code,
                quote=quote,
                config=config,
                near_threshold=near_threshold,
                breakout_threshold=breakout_threshold,
                today_key=today_key,
            )
            alerts.extend(stock_alerts)

        return alerts

    def _ensure_daily_state(self) -> None:
        today = date.today().strftime("%Y%m%d")
        if self._cache_date == today:
            return
        self._cache_date = today
        self._trade_date_cache.clear()

    async def _evaluate_stock(
        self,
        subscription: StrategySubscription,
        ts_code: str,
        quote: Dict[str, Any],
        config: Dict[str, Any],
        near_threshold: float,
        breakout_threshold: float,
        today_key: str,
    ) -> List[StrategyAlert]:
        stock_name = quote.get("name", ts_code)
        current_price = self._safe_float(quote.get("price") or quote.get("close"))
        if current_price is None or current_price <= 0:
            return []

        if self._should_skip_by_alert_frequency(subscription, ts_code, today_key):
            return []

        current_high = self._safe_float(quote.get("high")) or current_price
        current_low = self._safe_float(quote.get("low")) or current_price

        trade_dates = await self._get_trade_dates_for_stock(ts_code, today_key)
        if not trade_dates:
            return []

        line_defs: List[LineDefinition] = []
        if config.get("support_enabled"):
            support_points = config.get("support_points") or []
            if len(support_points) == 2:
                line_defs.append(LineDefinition("support", support_points))
        if config.get("resistance_enabled"):
            resistance_points = config.get("resistance_points") or []
            if len(resistance_points) == 2:
                line_defs.append(LineDefinition("resistance", resistance_points))

        alerts: List[StrategyAlert] = []
        frequency = self._get_alert_frequency(subscription.params)
        for line_def in line_defs:
            line_price = self._project_line_price(line_def.points, trade_dates, today_key)
            if line_price is None or line_price <= 0:
                continue

            event_type, reason = self._detect_event(
                line_type=line_def.line_type,
                current_price=current_price,
                current_high=current_high,
                current_low=current_low,
                line_price=line_price,
                near_threshold=near_threshold,
                breakout_threshold=breakout_threshold,
            )
            if not event_type or not reason:
                continue

            alerts.append(
                self._create_alert(
                    subscription=subscription,
                    ts_code=ts_code,
                    stock_name=stock_name,
                    price=current_price,
                    reason=reason,
                    extra_data={
                        "line_type": line_def.line_type,
                        "trend_type": config.get("trend_type", "custom"),
                        "event_type": event_type,
                        "line_price": round(line_price, 4),
                        "near_threshold_pct": round(near_threshold * 100, 4),
                        "breakout_threshold_pct": round(breakout_threshold * 100, 4),
                        "current_high": current_high,
                        "current_low": current_low,
                        "points": line_def.points,
                    },
                )
            )
            if frequency != self.ALERT_FREQUENCY_UNLIMITED:
                await self._record_alert_trigger(
                    subscription=subscription,
                    ts_code=ts_code,
                    today_key=today_key,
                    extra_updates={
                        "last_trigger_line_type": line_def.line_type,
                        "last_trigger_event_type": event_type,
                    },
                )
                break

        return alerts

    async def _get_trade_dates_for_stock(self, ts_code: str, today_key: str) -> List[str]:
        if ts_code not in self._trade_date_cache:
            records = await mongo_manager.find_many(
                "stock_daily",
                {"ts_code": ts_code},
                projection={"trade_date": 1},
                sort=[("trade_date", 1)],
            )
            dates = [record.get("trade_date") for record in records if record.get("trade_date")]
            self._trade_date_cache[ts_code] = dates

        dates = list(self._trade_date_cache.get(ts_code, []))
        if dates and today_key > dates[-1]:
            dates.append(today_key)
        return dates

    def _project_line_price(
        self,
        points: List[Dict[str, Any]],
        trade_dates: List[str],
        eval_date: str,
    ) -> Optional[float]:
        normalized_points = []
        for point in points:
            point_date = point.get("date")
            price = self._safe_float(point.get("price"))
            if not point_date or price is None:
                return None
            normalized_points.append({"date": point_date, "price": price})

        normalized_points.sort(key=lambda item: item["date"])
        point1, point2 = normalized_points
        if point1["date"] not in trade_dates or point2["date"] not in trade_dates or eval_date not in trade_dates:
            return None

        index1 = trade_dates.index(point1["date"])
        index2 = trade_dates.index(point2["date"])
        eval_index = trade_dates.index(eval_date)
        if index1 == index2:
            return None

        slope = (point2["price"] - point1["price"]) / (index2 - index1)
        return point1["price"] + slope * (eval_index - index1)

    def _detect_event(
        self,
        line_type: str,
        current_price: float,
        current_high: float,
        current_low: float,
        line_price: float,
        near_threshold: float,
        breakout_threshold: float,
    ) -> tuple[Optional[str], Optional[str]]:
        distance_values = [
            abs(value - line_price) / line_price
            for value in (current_price, current_high, current_low)
            if value and line_price
        ]
        near_hit = any(distance <= near_threshold for distance in distance_values)

        if line_type == "support":
            breakout_price = line_price * (1 - breakout_threshold)
            if current_low <= breakout_price or current_price <= breakout_price:
                return "breakdown", f"价格跌破支撑线，当前 {current_price:.2f}，支撑位 {line_price:.2f}"
            if near_hit:
                return "near_support", f"价格接近支撑线，当前 {current_price:.2f}，支撑位 {line_price:.2f}"
        else:
            breakout_price = line_price * (1 + breakout_threshold)
            if current_high >= breakout_price or current_price >= breakout_price:
                return "breakout", f"价格突破压力线，当前 {current_price:.2f}，压力位 {line_price:.2f}"
            if near_hit:
                return "near_resistance", f"价格接近压力线，当前 {current_price:.2f}，压力位 {line_price:.2f}"

        return None, None

    def _normalize_percentage_param(self, value: float) -> float:
        """
        撑压线策略的页面参数以“百分比数值”输入。

        例如：
        - 1.0 表示 1%
        - 0.5 表示 0.5%
        """
        return max(float(value), 0.0) / 100

    def _safe_float(self, value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
