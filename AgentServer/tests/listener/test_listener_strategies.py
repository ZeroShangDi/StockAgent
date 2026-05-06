from datetime import date
from unittest.mock import AsyncMock

import pytest

from core.protocols import MarketSnapshot, StrategySubscription, StrategyType
from nodes.listener.strategies.fixed_stop_loss import FixedStopLossStrategy
from nodes.listener.strategies.ma5_buy import MA5BuyStrategy, StockState
from nodes.listener.strategies.price_change import PriceChangeStrategy
from nodes.listener.strategies.support_resistance import SupportResistanceStrategy
from nodes.listener.strategies.trailing_stop_loss import TrailingStopLossStrategy


@pytest.mark.asyncio
async def test_price_change_strategy_supports_legacy_change_threshold() -> None:
    strategy = PriceChangeStrategy()
    subscription = StrategySubscription(
        strategy_name="涨跌幅阈值",
        strategy_type=StrategyType.PRICE_CHANGE,
        watch_list=["600000.SH"],
        params={"change_threshold": 5},
    )
    snapshot = MarketSnapshot(
        quotes={
            "600000.SH": {
                "ts_code": "600000.SH",
                "name": "浦发银行",
                "price": 8.2,
                "pct_chg": 5.2,
            }
        }
    )

    alerts = await strategy.evaluate(subscription=subscription, snapshot=snapshot)

    assert len(alerts) == 1
    assert alerts[0].ts_code == "600000.SH"


@pytest.mark.asyncio
async def test_ma5_strategy_normalizes_percent_touch_range() -> None:
    strategy = MA5BuyStrategy()
    strategy._cache_date = date.today().strftime("%Y%m%d")
    strategy._stock_data["000001.SZ"] = {
        "ma5": 10.0,
        "prev_close": 10.5,
    }

    subscription = StrategySubscription(
        strategy_name="5日线低吸",
        strategy_type=StrategyType.MA5_BUY,
        watch_list=["000001.SZ"],
        params={"touch_range": 2, "stable_periods": 2},
    )
    snapshot = MarketSnapshot(
        quotes={
            "000001.SZ": {
                "ts_code": "000001.SZ",
                "name": "平安银行",
                "price": 10.6,
                "pct_chg": 0.5,
            }
        }
    )

    alerts = await strategy.evaluate(subscription=subscription, snapshot=snapshot)

    assert alerts == []
    assert strategy._trackers["000001.SZ"].state == StockState.NORMAL


@pytest.mark.asyncio
async def test_support_resistance_strategy_uses_effective_trade_dates() -> None:
    strategy = SupportResistanceStrategy()
    today_key = date.today().strftime("%Y%m%d")
    strategy._get_trade_dates_for_stock = AsyncMock(  # type: ignore[method-assign]
        return_value=["20240401", "20240402", "20240408", today_key]
    )

    subscription = StrategySubscription(
        strategy_name="撑压线",
        strategy_type=StrategyType.SUPPORT_RESISTANCE,
        watch_list=["000001.SZ"],
        params={
            "near_threshold_pct": 1.0,
            "breakout_threshold_pct": 0.5,
            "stock_configs": {
                "000001.SZ": {
                    "trend_type": "uptrend",
                    "support_enabled": True,
                    "resistance_enabled": False,
                "support_points": [
                    {"date": "20240401", "price": 10.0},
                    {"date": "20240408", "price": 10.6},
                    ],
                    "resistance_points": [],
                }
            },
        },
    )
    snapshot = MarketSnapshot(
        quotes={
            "000001.SZ": {
                "ts_code": "000001.SZ",
                "name": "平安银行",
                "price": 10.82,
                "high": 10.86,
                "low": 10.8,
            }
        }
    )

    alerts = await strategy.evaluate(subscription=subscription, snapshot=snapshot)

    assert len(alerts) == 1
    assert alerts[0].extra_data["line_type"] == "support"
    assert alerts[0].extra_data["event_type"] == "near_support"


@pytest.mark.asyncio
async def test_support_resistance_strategy_percent_thresholds_are_percent_values() -> None:
    strategy = SupportResistanceStrategy()
    today_key = date.today().strftime("%Y%m%d")
    strategy._get_trade_dates_for_stock = AsyncMock(  # type: ignore[method-assign]
        return_value=["20240401", "20240402", "20240408", today_key]
    )

    subscription = StrategySubscription(
        strategy_name="撑压线",
        strategy_type=StrategyType.SUPPORT_RESISTANCE,
        watch_list=["000001.SZ"],
        params={
            "near_threshold_pct": 1.0,
            "breakout_threshold_pct": 0.5,
            "stock_configs": {
                "000001.SZ": {
                    "trend_type": "uptrend",
                    "support_enabled": True,
                    "resistance_enabled": False,
                    "support_points": [
                        {"date": "20240401", "price": 10.0},
                        {"date": "20240408", "price": 10.6},
                    ],
                    "resistance_points": [],
                }
            },
        },
    )
    snapshot = MarketSnapshot(
        quotes={
            "000001.SZ": {
                "ts_code": "000001.SZ",
                "name": "平安银行",
                "price": 20.0,
                "high": 20.1,
                "low": 19.9,
            }
        }
    )

    alerts = await strategy.evaluate(subscription=subscription, snapshot=snapshot)

    assert alerts == []


@pytest.mark.asyncio
async def test_fixed_stop_loss_strategy_triggers_and_persists_daily_state() -> None:
    strategy = FixedStopLossStrategy()
    strategy._persist_runtime_fields = AsyncMock()  # type: ignore[method-assign]
    today_key = date.today().strftime("%Y%m%d")

    subscription = StrategySubscription(
        strategy_name="固定止损",
        strategy_type=StrategyType.FIXED_STOP_LOSS,
        watch_list=["000001.SZ"],
        params={
            "once_per_day": True,
            "stock_configs": {
                "000001.SZ": {
                    "enabled": True,
                    "reference_price": 10.0,
                    "reference_date": "20260505",
                    "stop_loss_pct": 8.0,
                    "last_triggered_date": "",
                }
            },
        },
    )
    snapshot = MarketSnapshot(
        quotes={
            "000001.SZ": {
                "ts_code": "000001.SZ",
                "name": "平安银行",
                "price": 9.15,
                "low": 9.12,
            }
        }
    )

    alerts = await strategy.evaluate(subscription=subscription, snapshot=snapshot)

    assert len(alerts) == 1
    assert alerts[0].extra_data["event_type"] == "fixed_stop_loss"
    strategy._persist_runtime_fields.assert_awaited_once_with(  # type: ignore[attr-defined]
        subscription=subscription,
        ts_code="000001.SZ",
        updates={"last_triggered_date": today_key},
    )


@pytest.mark.asyncio
async def test_trailing_stop_loss_strategy_updates_highest_price_and_triggers() -> None:
    strategy = TrailingStopLossStrategy()
    strategy._persist_runtime_fields = AsyncMock()  # type: ignore[method-assign]
    today_key = date.today().strftime("%Y%m%d")

    subscription = StrategySubscription(
        strategy_name="移动止损",
        strategy_type=StrategyType.TRAILING_STOP_LOSS,
        watch_list=["000001.SZ"],
        params={
            "once_per_day": True,
            "stock_configs": {
                "000001.SZ": {
                    "enabled": True,
                    "entry_price": 10.0,
                    "entry_date": "20260505",
                    "highest_price": 12.0,
                    "highest_price_date": "20260505",
                    "trail_pct": 5.0,
                    "last_triggered_date": "",
                }
            },
        },
    )
    snapshot = MarketSnapshot(
        quotes={
            "000001.SZ": {
                "ts_code": "000001.SZ",
                "name": "平安银行",
                "price": 12.1,
                "high": 12.8,
                "low": 12.05,
            }
        }
    )

    alerts = await strategy.evaluate(subscription=subscription, snapshot=snapshot)

    assert len(alerts) == 1
    assert alerts[0].extra_data["event_type"] == "trailing_stop_loss"
    strategy._persist_runtime_fields.assert_awaited_once_with(  # type: ignore[attr-defined]
        subscription=subscription,
        ts_code="000001.SZ",
        updates={
            "highest_price": 12.8,
            "highest_price_date": today_key,
            "last_triggered_date": today_key,
        },
    )
