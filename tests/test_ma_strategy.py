from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from indicator_trading_research.strategies import MAStrategy, compute_ma


def build_candles(closes: list[float]) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01", periods=len(closes), freq="1h", tz="UTC"),
            "close": closes,
        }
    )
    return frame


def test_compute_ma_supports_sma_and_ema() -> None:
    series = pd.Series([1.0, 2.0, 3.0, 4.0])

    sma = compute_ma(series, period=2, ma_type="sma")
    ema = compute_ma(series, period=2, ma_type="ema")

    assert pd.isna(sma.iloc[0])
    assert sma.iloc[1] == pytest.approx(1.5)
    assert sma.iloc[2] == pytest.approx(2.5)
    assert sma.iloc[3] == pytest.approx(3.5)
    assert pd.isna(ema.iloc[0])
    assert ema.iloc[1] == pytest.approx(1.6666666667)
    assert ema.iloc[2] == pytest.approx(2.5555555556)
    assert ema.iloc[3] == pytest.approx(3.5185185185)


def test_compute_ma_supports_wma() -> None:
    series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])

    wma = compute_ma(series, period=3, ma_type="wma")

    assert pd.isna(wma.iloc[0])
    assert pd.isna(wma.iloc[1])
    assert wma.iloc[2] == pytest.approx((1.0 * 1 + 2.0 * 2 + 3.0 * 3) / 6.0)
    assert wma.iloc[3] == pytest.approx((2.0 * 1 + 3.0 * 2 + 4.0 * 3) / 6.0)
    assert wma.iloc[4] == pytest.approx((3.0 * 1 + 4.0 * 2 + 5.0 * 3) / 6.0)


def test_compute_ma_supports_hma() -> None:
    series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])

    hma = compute_ma(series, period=4, ma_type="hma")

    assert pd.isna(hma.iloc[0])
    assert pd.isna(hma.iloc[1])
    assert pd.isna(hma.iloc[2])
    assert pd.isna(hma.iloc[3])
    assert hma.iloc[4] == pytest.approx(5.0)
    assert hma.iloc[5] == pytest.approx(6.0)


def test_crossover_signals_with_two_mas() -> None:
    candles = build_candles([5.0, 4.0, 3.0, 4.0, 5.0, 4.0, 3.0])
    strategy = MAStrategy(
        ma_types=["sma", "sma"],
        ma_periods=[2, 3],
        entry_type="crossover",
    )

    signals = strategy.generate_signals(candles)
    non_zero = signals.loc[signals["signal"] != 0, ["timestamp", "signal"]]

    assert list(non_zero["signal"]) == [1, -1]
    assert list(non_zero["timestamp"]) == [
        pd.Timestamp("2025-01-01T04:00:00Z"),
        pd.Timestamp("2025-01-01T06:00:00Z"),
    ]
    assert {"ma_1", "ma_2", "ma_fast", "ma_slow"}.issubset(signals.columns)


def test_wma_crossover_signals_with_two_mas() -> None:
    candles = build_candles([5.0, 4.0, 3.0, 4.0, 5.0, 4.0, 3.0])
    strategy = MAStrategy(
        ma_types=["wma", "wma"],
        ma_periods=[2, 3],
        entry_type="crossover",
    )

    signals = strategy.generate_signals(candles)
    non_zero = signals.loc[signals["signal"] != 0, ["timestamp", "signal"]]

    assert list(non_zero["signal"]) == [1, -1]
    assert list(non_zero["timestamp"]) == [
        pd.Timestamp("2025-01-01T04:00:00Z"),
        pd.Timestamp("2025-01-01T06:00:00Z"),
    ]


def test_hma_crossover_signals_with_two_mas() -> None:
    candles = build_candles([8.0, 7.0, 6.0, 5.0, 6.0, 7.0, 8.0, 7.0, 6.0, 5.0])
    strategy = MAStrategy(
        ma_types=["hma", "hma"],
        ma_periods=[3, 5],
        entry_type="crossover",
    )

    signals = strategy.generate_signals(candles)
    non_zero = signals.loc[signals["signal"] != 0, ["timestamp", "signal"]]

    assert list(non_zero["signal"]) == [-1]
    assert list(non_zero["timestamp"]) == [pd.Timestamp("2025-01-01T07:00:00Z")]


def test_price_above_all_uses_sorted_periods_not_input_order() -> None:
    candles = build_candles([1.0, 2.0, 3.0, 4.0, 5.0, 1.0, 0.5, 0.25])
    strategy = MAStrategy(
        ma_types=["ema", "sma", "sma"],
        ma_periods=[5, 2, 3],
        entry_type="price_above_all",
    )

    signals = strategy.generate_signals(candles)
    non_zero = signals.loc[signals["signal"] != 0, "signal"].tolist()

    assert non_zero == [1, -1]
    assert signals["ma_fast"].equals(signals["ma_1"])
    assert signals["ma_slow"].equals(signals["ma_3"])


def test_crossover_breakout_requires_crossover_and_price_position() -> None:
    candles = build_candles([5.0, 4.0, 3.0, 4.0, 6.0, 7.0, 6.0, 5.0])
    strategy = MAStrategy(
        ma_types=["sma", "sma", "ema"],
        ma_periods=[4, 2, 3],
        entry_type="crossover_breakout",
    )

    signals = strategy.generate_signals(candles)
    non_zero = signals.loc[signals["signal"] != 0, ["timestamp", "signal"]]

    assert list(non_zero["signal"]) == [1, -1]
    assert list(non_zero["timestamp"]) == [
        pd.Timestamp("2025-01-01T04:00:00Z"),
        pd.Timestamp("2025-01-01T07:00:00Z"),
    ]


def test_hma_sma_crossover_breakout_is_supported() -> None:
    candles = build_candles([7.0, 6.0, 5.0, 4.0, 5.0, 7.0, 9.0, 8.0, 7.0, 6.0])
    strategy = MAStrategy(
        ma_types=["hma", "sma"],
        ma_periods=[3, 5],
        entry_type="crossover_breakout",
    )

    signals = strategy.generate_signals(candles)
    assert {"ma_1", "ma_2", "ma_fast", "ma_slow", "signal"}.issubset(signals.columns)
    assert len(signals) == len(candles)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {"ma_types": ["sma", "ema"], "ma_periods": [10], "entry_type": "price_above_all"},
            "ma_types and ma_periods must have the same length",
        ),
        (
            {"ma_types": ["sma", "bad_ma"], "ma_periods": [10, 20], "entry_type": "price_above_all"},
            "Unsupported ma_type",
        ),
        (
            {"ma_types": ["sma", "ema", "sma"], "ma_periods": [10, 20, 50], "entry_type": "crossover"},
            "entry_type='crossover' currently supports exactly 2 moving averages",
        ),
    ],
)
def test_invalid_ma_strategy_configs_fail_clearly(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        MAStrategy(**kwargs)
