from datetime import date

import pytest

from core.protocols import MarketSnapshot, StrategySubscription, StrategyType
from nodes.listener.strategies.ma5_buy import MA5BuyStrategy, StockState
from nodes.listener.strategies.price_change import PriceChangeStrategy


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
