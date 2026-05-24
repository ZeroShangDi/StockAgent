from src.strategy_v2.evaluator import (
    evaluate_double_cannon_from_candles,
    evaluate_turtle_trading_from_candles,
)


def _row(
    trade_date: str,
    open_price: float,
    close: float,
    low: float,
    pct_chg: float,
    vol: float = 100,
    high: float | None = None,
) -> dict:
    return {
        "trade_date": trade_date,
        "open": open_price,
        "high": high if high is not None else max(open_price, close),
        "close": close,
        "low": low,
        "pct_chg": pct_chg,
        "vol": vol,
    }


def test_double_cannon_returns_positive_for_valid_pattern() -> None:
    candles = [
        _row("20260401", 10.0, 10.7, 9.9, 6.2, 120),
        _row("20260402", 10.6, 10.4, 10.1, -1.2, 80),
        _row("20260403", 10.4, 10.2, 10.0, -0.5, 75),
        _row("20260406", 10.5, 11.3, 10.4, 6.5, 150),
        _row("20260407", 11.1, 11.0, 10.8, -0.8, 90),
        _row("20260408", 11.0, 11.1, 10.9, 0.9, 95),
    ]

    result = evaluate_double_cannon_from_candles(candles)

    assert result.signal == 1
    assert result.meta["first_trade_date"] == "20260401"
    assert result.meta["second_trade_date"] == "20260406"


def test_double_cannon_returns_negative_when_middle_breaks_first_low() -> None:
    candles = [
        _row("20260401", 10.0, 10.7, 9.9, 6.2, 120),
        _row("20260402", 10.6, 9.8, 9.7, -4.0, 90),
        _row("20260403", 10.0, 10.2, 9.9, 1.0, 80),
        _row("20260406", 10.5, 11.3, 10.4, 6.5, 150),
        _row("20260407", 11.1, 11.0, 10.8, -0.8, 90),
    ]

    result = evaluate_double_cannon_from_candles(candles)

    assert result.signal == -1
    assert result.meta["broken_trade_dates"] == ["20260402"]


def test_double_cannon_optional_second_volume_filter() -> None:
    candles = [
        _row("20260401", 10.0, 10.7, 9.9, 6.2, 200),
        _row("20260402", 10.6, 10.4, 10.1, -1.2, 80),
        _row("20260403", 10.4, 10.2, 10.0, -0.5, 75),
        _row("20260406", 10.5, 11.3, 10.4, 6.5, 150),
        _row("20260407", 11.1, 11.0, 10.8, -0.8, 90),
    ]

    result = evaluate_double_cannon_from_candles(
        candles,
        {"require_second_volume_gt_first": True},
    )

    assert result.signal == 0
    assert result.reason == "第二根大阳线成交量未大于第一根"


def test_turtle_trading_returns_positive_on_entry_breakout() -> None:
    candles = [
        _row("20260401", 10.0, 10.2, 9.8, 1.0, 100, 10.4),
        _row("20260402", 10.2, 10.4, 10.0, 1.5, 100, 10.6),
        _row("20260403", 10.4, 10.3, 10.1, -0.5, 100, 10.5),
        _row("20260406", 10.3, 10.5, 10.2, 1.0, 100, 10.7),
        _row("20260407", 10.5, 10.6, 10.3, 0.8, 100, 10.8),
        _row("20260408", 10.6, 11.0, 10.5, 3.8, 180, 11.1),
    ]

    result = evaluate_turtle_trading_from_candles(
        candles,
        {"entry_window": 3, "exit_window": 2, "atr_period": 3, "volume_window": 3},
    )

    assert result.signal == 1
    assert result.meta["entry_channel_high"] == 10.8


def test_turtle_trading_returns_negative_on_exit_breakdown() -> None:
    candles = [
        _row("20260401", 10.0, 10.4, 9.8, 2.0, 100, 10.6),
        _row("20260402", 10.4, 10.5, 10.1, 1.0, 100, 10.7),
        _row("20260403", 10.5, 10.3, 10.0, -1.0, 100, 10.6),
        _row("20260406", 10.3, 10.2, 9.9, -0.8, 100, 10.4),
        _row("20260407", 10.2, 10.1, 9.8, -0.5, 100, 10.3),
        _row("20260408", 10.0, 9.6, 9.5, -5.0, 120, 10.1),
    ]

    result = evaluate_turtle_trading_from_candles(
        candles,
        {"entry_window": 3, "exit_window": 2, "atr_period": 3, "volume_window": 3},
    )

    assert result.signal == -1
    assert result.meta["exit_channel_low"] == 9.8


def test_turtle_trading_volume_filter_can_block_breakout() -> None:
    candles = [
        _row("20260401", 10.0, 10.2, 9.8, 1.0, 200, 10.4),
        _row("20260402", 10.2, 10.4, 10.0, 1.5, 200, 10.6),
        _row("20260403", 10.4, 10.3, 10.1, -0.5, 200, 10.5),
        _row("20260406", 10.3, 10.5, 10.2, 1.0, 200, 10.7),
        _row("20260407", 10.5, 10.6, 10.3, 0.8, 200, 10.8),
        _row("20260408", 10.6, 11.0, 10.5, 3.8, 100, 11.1),
    ]

    result = evaluate_turtle_trading_from_candles(
        candles,
        {
            "entry_window": 3,
            "exit_window": 2,
            "atr_period": 3,
            "volume_window": 3,
            "require_volume_confirm": True,
            "volume_multiplier": 1.2,
        },
    )

    assert result.signal == 0
    assert result.reason == "突破成立但成交量未达到确认阈值"
