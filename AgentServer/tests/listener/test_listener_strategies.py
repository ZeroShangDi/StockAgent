from datetime import date
from unittest.mock import AsyncMock

import pytest

from core.protocols import MarketSnapshot, StrategySubscription, StrategyType
from nodes.listener.strategies.fixed_stop_loss import FixedStopLossStrategy
from nodes.listener.strategies.ma5_buy import MA5BuyStrategy, StockState
from nodes.listener.strategies.market_index_alert import MarketIndexAlertStrategy
from nodes.listener.strategies.price_change import PriceChangeStrategy
from nodes.listener.strategies.support_resistance import SupportResistanceStrategy
from nodes.listener.strategies.trailing_stop_loss import TrailingStopLossStrategy


@pytest.mark.asyncio
async def test_price_change_strategy_supports_legacy_change_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy = PriceChangeStrategy()
    update_mock = AsyncMock()
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
    monkeypatch.setattr(
        "nodes.listener.strategies.base.mongo_manager.update_one",
        update_mock,
    )
    alerts = await strategy.evaluate(subscription=subscription, snapshot=snapshot)

    assert len(alerts) == 1
    assert alerts[0].ts_code == "600000.SH"
    assert subscription.params["stock_configs"]["600000.SH"]["threshold_states"]["price_change_up"] is True


@pytest.mark.asyncio
async def test_price_change_strategy_unlimited_only_alerts_on_re_cross(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy = PriceChangeStrategy()
    update_mock = AsyncMock()
    subscription = StrategySubscription(
        strategy_name="涨跌幅阈值",
        strategy_type=StrategyType.PRICE_CHANGE,
        watch_list=["600000.SH"],
        params={
            "threshold": 5,
            "alert_frequency": "unlimited",
        },
    )
    monkeypatch.setattr(
        "nodes.listener.strategies.base.mongo_manager.update_one",
        update_mock,
    )

    first_snapshot = MarketSnapshot(
        quotes={
            "600000.SH": {
                "ts_code": "600000.SH",
                "name": "浦发银行",
                "price": 8.2,
                "pct_chg": 5.2,
            }
        }
    )
    second_snapshot = MarketSnapshot(
        quotes={
            "600000.SH": {
                "ts_code": "600000.SH",
                "name": "浦发银行",
                "price": 8.3,
                "pct_chg": 6.1,
            }
        }
    )
    reset_snapshot = MarketSnapshot(
        quotes={
            "600000.SH": {
                "ts_code": "600000.SH",
                "name": "浦发银行",
                "price": 7.9,
                "pct_chg": 3.4,
            }
        }
    )

    first_alerts = await strategy.evaluate(subscription=subscription, snapshot=first_snapshot)
    second_alerts = await strategy.evaluate(subscription=subscription, snapshot=second_snapshot)
    reset_alerts = await strategy.evaluate(subscription=subscription, snapshot=reset_snapshot)
    third_alerts = await strategy.evaluate(subscription=subscription, snapshot=first_snapshot)

    assert len(first_alerts) == 1
    assert second_alerts == []
    assert reset_alerts == []
    assert len(third_alerts) == 1


@pytest.mark.asyncio
async def test_market_index_alert_strategy_triggers_on_any_condition(monkeypatch: pytest.MonkeyPatch) -> None:
    strategy = MarketIndexAlertStrategy()
    subscription = StrategySubscription(
        strategy_name="指数指标预警",
        strategy_type=StrategyType.MARKET_INDEX_ALERT,
        watch_list=["ALL"],
        params={
            "index_code": "000001.SH",
            "index_rise_enabled": True,
            "index_rise_threshold": 1.5,
            "limit_up_enabled": True,
            "limit_up_threshold": 80,
            "alert_frequency": "daily_once",
        },
    )
    snapshot = MarketSnapshot(limit_up_count=82)
    update_mock = AsyncMock()
    monkeypatch.setattr(
        "nodes.listener.strategies.base.mongo_manager.update_one",
        update_mock,
    )

    monkeypatch.setattr(
        "nodes.listener.strategies.market_index_alert.redis_manager.get_realtime_market_data",
        AsyncMock(
            return_value={
                "sh_index": 3320.0,
                "sh_change": 1.82,
                "up_count": 2800,
                "down_count": 1200,
                "limit_up": 86,
                "limit_down": 4,
            }
        ),
    )
    monkeypatch.setattr(
        "nodes.listener.strategies.market_index_alert.mongo_manager.find_one",
        AsyncMock(return_value={"trade_date": "20260510", "north_money": 12.0}),
    )

    alerts = await strategy.evaluate(subscription=subscription, snapshot=snapshot)

    assert len(alerts) == 1
    assert alerts[0].ts_code == "000001.SH"
    assert "上证指数涨幅" in alerts[0].trigger_reason
    assert alerts[0].extra_data["limit_up_count"] == 86


@pytest.mark.asyncio
async def test_market_index_alert_strategy_rearms_after_falling_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy = MarketIndexAlertStrategy()
    subscription = StrategySubscription(
        strategy_name="指数指标预警",
        strategy_type=StrategyType.MARKET_INDEX_ALERT,
        watch_list=["ALL"],
        params={
            "index_code": "000001.SH",
            "north_money_in_enabled": True,
            "north_money_in_threshold": 20,
            "alert_frequency": "unlimited",
        },
    )
    snapshot = MarketSnapshot()
    update_mock = AsyncMock()
    monkeypatch.setattr(
        "nodes.listener.strategies.base.mongo_manager.update_one",
        update_mock,
    )
    monkeypatch.setattr(
        "nodes.listener.strategies.market_index_alert.redis_manager.get_realtime_market_data",
        AsyncMock(return_value={"sh_index": 3320.0, "sh_change": 0.8}),
    )

    daily_stats_mock = AsyncMock(
        side_effect=[
            {"trade_date": "20260510", "north_money": 21.0},
            {"trade_date": "20260510", "north_money": 42.0},
            {"trade_date": "20260510", "north_money": 15.0},
            {"trade_date": "20260510", "north_money": 23.0},
        ]
    )
    monkeypatch.setattr(
        "nodes.listener.strategies.market_index_alert.mongo_manager.find_one",
        daily_stats_mock,
    )

    first_alerts = await strategy.evaluate(subscription=subscription, snapshot=snapshot)
    second_alerts = await strategy.evaluate(subscription=subscription, snapshot=snapshot)
    reset_alerts = await strategy.evaluate(subscription=subscription, snapshot=snapshot)
    third_alerts = await strategy.evaluate(subscription=subscription, snapshot=snapshot)

    assert len(first_alerts) == 1
    assert second_alerts == []
    assert reset_alerts == []
    assert len(third_alerts) == 1


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
async def test_ma5_strategy_supports_stock_specific_ma_period() -> None:
    strategy = MA5BuyStrategy()
    strategy._cache_date = date.today().strftime("%Y%m%d")
    strategy._stock_data["000001.SZ"] = {
        "records": [
            {"trade_date": "20260509", "close": 10.5},
            {"trade_date": "20260508", "close": 10.0},
            {"trade_date": "20260507", "close": 10.0},
            {"trade_date": "20260506", "close": 10.0},
            {"trade_date": "20260505", "close": 10.0},
            {"trade_date": "20260502", "close": 10.0},
            {"trade_date": "20260430", "close": 10.0},
            {"trade_date": "20260429", "close": 10.0},
            {"trade_date": "20260428", "close": 10.0},
        ],
    }

    subscription = StrategySubscription(
        strategy_name="均线低吸",
        strategy_type=StrategyType.MA5_BUY,
        watch_list=["000001.SZ"],
        params={
            "ma_period": 5,
            "touch_range": 2,
            "stable_periods": 2,
            "stock_configs": {
                "000001.SZ": {
                    "enabled": True,
                    "ma_period": 8,
                    "touch_range": 2,
                    "stable_periods": 2,
                }
            },
        },
    )
    snapshot = MarketSnapshot(
        quotes={
            "000001.SZ": {
                "ts_code": "000001.SZ",
                "name": "平安银行",
                "price": 10.1,
                "pct_chg": 0.5,
            }
        }
    )

    alerts = await strategy.evaluate(subscription=subscription, snapshot=snapshot)

    assert alerts == []
    assert strategy._trackers["000001.SZ"].state == StockState.TOUCHED


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
async def test_support_resistance_strategy_supports_horizontal_line() -> None:
    strategy = SupportResistanceStrategy()
    today_key = date.today().strftime("%Y%m%d")
    strategy._get_trade_dates_for_stock = AsyncMock(return_value=["20240401", today_key])  # type: ignore[method-assign]

    subscription = StrategySubscription(
        strategy_name="撑压线",
        strategy_type=StrategyType.SUPPORT_RESISTANCE,
        watch_list=["000001.SZ"],
        params={
            "near_threshold_pct": 1.0,
            "breakout_threshold_pct": 0.5,
            "stock_configs": {
                "000001.SZ": {
                    "trend_type": "custom",
                    "support_enabled": True,
                    "support_mode": "horizontal",
                    "support_price": 10.0,
                    "resistance_enabled": False,
                    "support_points": [],
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
                "price": 10.06,
                "high": 10.1,
                "low": 9.98,
            }
        }
    )

    alerts = await strategy.evaluate(subscription=subscription, snapshot=snapshot)

    assert len(alerts) == 1
    assert alerts[0].extra_data["line_mode"] == "horizontal"
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
