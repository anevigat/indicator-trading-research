from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from indicator_trading_research.backtest import BacktestConfig, run_backtest


def build_candles(rows: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    return frame


def build_signals(rows: list[tuple[str, int]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["timestamp", "signal"])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["side"] = "flat"
    frame.loc[frame["signal"] > 0, "side"] = "long"
    frame.loc[frame["signal"] < 0, "side"] = "short"
    frame["tag"] = ""
    frame["strategy_name"] = "synthetic_strategy"
    return frame


def build_config(**overrides: object) -> BacktestConfig:
    payload = {
        "pair": "EURUSD",
        "timeframe": "1h",
        "strategy_name": "synthetic_strategy",
        "start_date": "2025-01-01",
        "end_date": "2025-01-02",
        "initial_capital": 10_000.0,
        "fixed_position_size": 1.0,
        "spread": 0.0,
        "slippage": 0.0,
        "fee_per_trade": 0.0,
        "allow_long": True,
        "allow_short": True,
        "one_position_at_a_time": True,
        "stop_loss_mode": None,
        "stop_loss": None,
        "take_profit_mode": None,
        "take_profit": None,
        "trailing_stop_mode": None,
        "trailing_stop": None,
        "trailing_type": "standard",
        "trailing_activation_mode": None,
        "trailing_activation": None,
        "chandelier_multiplier": None,
        "chandelier_atr_period": 14,
        "chandelier_atr_method": "wilder",
        "break_even_mode": None,
        "break_even": None,
        "break_even_buffer_mode": None,
        "break_even_buffer": None,
        "atr_period": 14,
        "atr_method": "wilder",
    }
    payload.update(overrides)
    return BacktestConfig(**payload)


def test_long_break_even_does_not_activate_early_then_exits() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 10.0, 10.1, 9.9, 10.0),
            ("2025-01-01T01:00:00Z", 10.0, 10.8, 9.8, 10.6),
            ("2025-01-01T02:00:00Z", 10.6, 11.2, 10.5, 10.9),
            ("2025-01-01T03:00:00Z", 10.9, 10.95, 10.0, 10.2),
            ("2025-01-01T04:00:00Z", 10.2, 10.3, 10.1, 10.2),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", 1)])
    config = build_config(
        break_even=1.0,
        break_even_mode="absolute",
        break_even_buffer=0.1,
        break_even_buffer_mode="absolute",
    )

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["break_even_stop_price"] == pytest.approx(10.1)
    assert trade["exit_reason"] == "break_even"
    assert trade["exit_time"] == pd.Timestamp("2025-01-01T03:00:00Z")
    assert trade["exit_price"] == pytest.approx(10.1)


def test_short_break_even_exits_correctly() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 20.0, 20.1, 19.9, 20.0),
            ("2025-01-01T01:00:00Z", 20.0, 20.2, 19.2, 19.4),
            ("2025-01-01T02:00:00Z", 19.4, 19.5, 18.8, 19.0),
            ("2025-01-01T03:00:00Z", 19.0, 20.0, 18.9, 19.7),
            ("2025-01-01T04:00:00Z", 19.7, 19.8, 19.6, 19.7),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", -1)])
    config = build_config(
        break_even=1.0,
        break_even_mode="absolute",
        break_even_buffer=0.1,
        break_even_buffer_mode="absolute",
    )

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["break_even_stop_price"] == pytest.approx(19.9)
    assert trade["exit_reason"] == "break_even"
    assert trade["exit_price"] == pytest.approx(19.9)


def test_break_even_can_be_tighter_than_static_stop() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 10.0, 10.1, 9.9, 10.0),
            ("2025-01-01T01:00:00Z", 10.0, 11.2, 9.8, 10.8),
            ("2025-01-01T02:00:00Z", 10.8, 10.9, 10.0, 10.1),
            ("2025-01-01T03:00:00Z", 10.1, 10.2, 10.0, 10.1),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", 1)])
    config = build_config(
        stop_loss=1.0,
        stop_loss_mode="absolute",
        break_even=1.0,
        break_even_mode="absolute",
        break_even_buffer=0.1,
        break_even_buffer_mode="absolute",
    )

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["exit_reason"] == "break_even"
    assert trade["exit_price"] == pytest.approx(10.1)


def test_trailing_can_be_tighter_than_break_even_in_combined_scenario() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 10.0, 10.1, 9.9, 10.0),
            ("2025-01-01T01:00:00Z", 10.0, 11.4, 9.9, 11.2),
            ("2025-01-01T02:00:00Z", 11.2, 11.3, 10.15, 10.8),
            ("2025-01-01T03:00:00Z", 10.8, 10.9, 10.7, 10.8),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", 1)])
    config = build_config(
        trailing_stop=0.5,
        trailing_stop_mode="absolute",
        break_even=1.0,
        break_even_mode="absolute",
        break_even_buffer=0.1,
        break_even_buffer_mode="absolute",
    )

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["break_even_stop_price"] == pytest.approx(10.1)
    assert trade["trailing_stop_initial"] == pytest.approx(10.7)
    assert trade["exit_reason"] == "trailing_stop"
    assert trade["exit_price"] == pytest.approx(10.7)


def test_break_even_atr_mode_uses_atr_at_entry_for_threshold_and_buffer() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 9.0, 10.0, 8.0, 9.0),
            ("2025-01-01T01:00:00Z", 10.0, 11.0, 9.0, 10.0),
            ("2025-01-01T02:00:00Z", 20.0, 21.9, 19.8, 21.0),
            ("2025-01-01T03:00:00Z", 21.0, 22.1, 20.9, 21.4),
            ("2025-01-01T04:00:00Z", 21.4, 21.5, 20.9, 21.2),
            ("2025-01-01T05:00:00Z", 21.2, 21.3, 21.1, 21.2),
        ]
    )
    signals = build_signals([("2025-01-01T01:00:00Z", 1)])
    config = build_config(
        break_even=1.0,
        break_even_mode="atr",
        break_even_buffer=0.5,
        break_even_buffer_mode="atr",
        atr_period=2,
        atr_method="sma",
    )

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["atr_at_entry"] == pytest.approx(2.0)
    assert trade["break_even_stop_price"] == pytest.approx(21.0)
    assert trade["exit_reason"] == "break_even"
    assert trade["exit_price"] == pytest.approx(21.0)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"break_even": -1.0, "break_even_mode": "absolute"}, "break_even must be positive"),
        ({"break_even": 1.0, "break_even_buffer": -0.1, "break_even_buffer_mode": "absolute"}, "break_even_buffer must be zero or positive"),
        ({"break_even_mode": "bad_mode", "break_even": 1.0}, "Unsupported break_even_mode"),
        ({"break_even_buffer_mode": "bad_mode", "break_even": 1.0, "break_even_buffer": 0.1}, "Unsupported break_even_buffer_mode"),
    ],
)
def test_invalid_break_even_config_fails_clearly(overrides: dict[str, object], message: str) -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 10.0, 10.1, 9.9, 10.0),
            ("2025-01-01T01:00:00Z", 10.0, 10.2, 9.8, 10.1),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", 1)])
    config = build_config(**overrides)

    with pytest.raises(ValueError, match=message):
        run_backtest(candles, signals, config)
