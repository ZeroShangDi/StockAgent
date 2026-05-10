"""
策略基类

所有策略必须继承此类并实现 evaluate 方法。
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from datetime import UTC, datetime

from core.protocols import (
    StrategySubscription,
    StrategyAlert,
    MarketSnapshot,
)
from core.managers import mongo_manager


class BaseStrategy(ABC):
    ALERT_FREQUENCY_DAILY_ONCE = "daily_once"
    ALERT_FREQUENCY_ONCE_THEN_DISABLE = "once_then_disable"
    ALERT_FREQUENCY_UNLIMITED = "unlimited"
    VALID_ALERT_FREQUENCIES = {
        ALERT_FREQUENCY_DAILY_ONCE,
        ALERT_FREQUENCY_ONCE_THEN_DISABLE,
        ALERT_FREQUENCY_UNLIMITED,
    }
    """
    策略基类
    
    子类必须实现:
    - evaluate(): 评估策略条件是否满足
    
    Example:
        class MyStrategy(BaseStrategy):
            async def evaluate(
                self,
                subscription: StrategySubscription,
                snapshot: MarketSnapshot,
                previous_snapshot: Optional[MarketSnapshot],
            ) -> List[StrategyAlert]:
                # 实现策略逻辑
                alerts = []
                # ...
                return alerts
    """
    
    @property
    @abstractmethod
    def strategy_type(self) -> str:
        """策略类型标识"""
        raise NotImplementedError
    
    @abstractmethod
    async def evaluate(
        self,
        subscription: StrategySubscription,
        snapshot: MarketSnapshot,
        previous_snapshot: Optional[MarketSnapshot] = None,
    ) -> List[StrategyAlert]:
        """
        评估策略条件
        
        Args:
            subscription: 策略订阅配置
            snapshot: 当前市场快照
            previous_snapshot: 上一次市场快照 (可选，用于比较)
            
        Returns:
            触发的预警列表
        """
        raise NotImplementedError
    
    def _get_watch_stocks(
        self,
        subscription: StrategySubscription,
        snapshot: MarketSnapshot,
        exclude_st: bool = False,
    ) -> Dict[str, Dict[str, Any]]:
        """
        获取需要监听的股票数据
        
        Args:
            subscription: 订阅配置
            snapshot: 市场快照
            exclude_st: 是否排除 ST 股票
            
        Returns:
            符合 watch_list 的股票数据
        """
        if subscription.is_all_market():
            stocks = snapshot.quotes
        else:
            stocks = {
                ts_code: quote
                for ts_code, quote in snapshot.quotes.items()
                if ts_code in subscription.watch_list
            }
        
        # 过滤 ST 股票
        if exclude_st:
            stocks = {
                ts_code: quote
                for ts_code, quote in stocks.items()
                if not self._is_st_stock(quote)
            }

        stock_configs = subscription.params.get("stock_configs", {}) or {}
        if isinstance(stock_configs, dict):
            stocks = {
                ts_code: quote
                for ts_code, quote in stocks.items()
                if not (
                    isinstance(stock_configs.get(ts_code), dict)
                    and stock_configs.get(ts_code, {}).get("enabled") is False
                )
            }
        
        return stocks
    
    def _is_st_stock(self, quote: Dict[str, Any]) -> bool:
        """
        判断是否为 ST 股票
        
        根据股票名称判断，包含 ST、*ST、S*ST 等
        """
        name = quote.get("name", "")
        if not name:
            return False
        
        # ST 股票名称特征
        st_patterns = ["ST", "*ST", "S*ST", "SST", "S"]
        name_upper = name.upper()
        
        for pattern in st_patterns:
            if name_upper.startswith(pattern):
                return True
        
        return False
    
    def _create_alert(
        self,
        subscription: StrategySubscription,
        ts_code: str,
        stock_name: str,
        price: float,
        reason: str,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> StrategyAlert:
        """
        创建预警对象
        
        Args:
            subscription: 订阅配置
            ts_code: 股票代码
            stock_name: 股票名称
            price: 当前价格
            reason: 触发原因
            extra_data: 额外数据
            
        Returns:
            预警对象
        """
        return StrategyAlert(
            subscription_id=subscription.subscription_id,
            strategy_id=subscription.strategy_id,
            strategy_name=subscription.strategy_name,
            ts_code=ts_code,
            stock_name=stock_name,
            trigger_price=price,
            trigger_reason=reason,
            extra_data=extra_data or {},
        )

    def _get_numeric_param(
        self,
        params: Dict[str, Any],
        primary_key: str,
        default: float,
        *aliases: str,
    ) -> float:
        """读取数值参数，兼容历史字段名。"""
        for key in (primary_key, *aliases):
            value = params.get(key)
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return float(default)

    def _normalize_percent_value(self, value: float) -> float:
        """
        将百分比参数统一转换为小数。

        兼容两种输入方式：
        - 0.02 表示 2%
        - 2 表示 2%
        """
        return value / 100 if value > 1 else value

    def _get_alert_frequency(self, params: Dict[str, Any]) -> str:
        raw_value = str(params.get("alert_frequency") or "").strip().lower()
        if raw_value in self.VALID_ALERT_FREQUENCIES:
            return raw_value

        if "once_per_day" in params:
            return self.ALERT_FREQUENCY_DAILY_ONCE if bool(params.get("once_per_day", True)) else self.ALERT_FREQUENCY_UNLIMITED

        return self.ALERT_FREQUENCY_DAILY_ONCE

    def _get_stock_runtime_config(
        self,
        subscription: StrategySubscription,
        ts_code: str,
    ) -> Dict[str, Any]:
        stock_configs = subscription.params.get("stock_configs", {}) or {}
        if not isinstance(stock_configs, dict):
            return {}
        config = stock_configs.get(ts_code) or {}
        return dict(config) if isinstance(config, dict) else {}

    def _should_skip_by_alert_frequency(
        self,
        subscription: StrategySubscription,
        ts_code: str,
        today_key: str,
    ) -> bool:
        frequency = self._get_alert_frequency(subscription.params)
        config = self._get_stock_runtime_config(subscription, ts_code)

        if frequency == self.ALERT_FREQUENCY_UNLIMITED:
            return False

        if frequency == self.ALERT_FREQUENCY_ONCE_THEN_DISABLE:
            return config.get("enabled") is False or bool(config.get("frequency_disabled"))

        last_triggered_date = str(config.get("last_triggered_date") or "")
        return last_triggered_date == today_key

    def _load_threshold_states(
        self,
        subscription: StrategySubscription,
        ts_code: str,
        today_key: str,
    ) -> Dict[str, bool]:
        config = self._get_stock_runtime_config(subscription, ts_code)
        state_day = str(config.get("threshold_state_day") or "")
        if state_day != today_key:
            return {}

        raw_states = config.get("threshold_states")
        if not isinstance(raw_states, dict):
            return {}

        return {
            str(key): bool(value)
            for key, value in raw_states.items()
            if value
        }

    def _set_threshold_state(
        self,
        states: Dict[str, bool],
        key: str,
        is_active: bool,
    ) -> bool:
        was_active = bool(states.get(key, False))
        if is_active:
            states[key] = True
        else:
            states.pop(key, None)
        return is_active and not was_active

    def _build_threshold_state_updates(
        self,
        today_key: str,
        states: Dict[str, bool],
    ) -> Dict[str, Any]:
        return {
            "threshold_state_day": today_key,
            "threshold_states": dict(states),
        }

    async def _persist_threshold_states_if_changed(
        self,
        subscription: StrategySubscription,
        ts_code: str,
        today_key: str,
        original_states: Dict[str, bool],
        states: Dict[str, bool],
    ) -> None:
        if states == original_states:
            return

        await self._persist_stock_runtime_fields(
            subscription=subscription,
            ts_code=ts_code,
            updates=self._build_threshold_state_updates(today_key, states),
        )

    async def _record_alert_trigger(
        self,
        subscription: StrategySubscription,
        ts_code: str,
        today_key: str,
        extra_updates: Optional[Dict[str, Any]] = None,
    ) -> None:
        frequency = self._get_alert_frequency(subscription.params)
        current_config = self._get_stock_runtime_config(subscription, ts_code)
        trigger_count = int(current_config.get("trigger_count", 0) or 0) + 1
        updates: Dict[str, Any] = {
            "last_triggered_date": today_key,
            "last_triggered_at": datetime.now(UTC).isoformat(),
            "trigger_count": trigger_count,
        }
        if frequency == self.ALERT_FREQUENCY_ONCE_THEN_DISABLE:
            updates.update(
                {
                    "enabled": False,
                    "frequency_disabled": True,
                    "disabled_reason": "once_then_disable",
                }
            )
        if extra_updates:
            updates.update(extra_updates)
        await self._persist_stock_runtime_fields(subscription, ts_code, updates)

    async def _persist_stock_runtime_fields(
        self,
        subscription: StrategySubscription,
        ts_code: str,
        updates: Dict[str, Any],
    ) -> None:
        params = dict(subscription.params or {})
        stock_configs = dict(params.get("stock_configs", {}) or {})
        current_config = dict(stock_configs.get(ts_code, {}) or {})
        current_config.update(updates)
        stock_configs[ts_code] = current_config
        params["stock_configs"] = stock_configs

        subscription.params = params

        await mongo_manager.update_one(
            "strategy_subscriptions",
            {"strategy_id": subscription.strategy_id},
            {"$set": {"params": params}},
        )
