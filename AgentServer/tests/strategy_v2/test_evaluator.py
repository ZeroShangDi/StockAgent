from src.strategy_v2.evaluator import evaluate_double_cannon_from_candles


def _row(
    trade_date: str,
    open_price: float,
    close: float,
    low: float,
    pct_chg: float,
    vol: float = 100,
) -> dict:
    return {
        "trade_date": trade_date,
        "open": open_price,
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
