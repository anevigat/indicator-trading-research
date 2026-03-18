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
        "trailing_type": "chandelier",
        "trailing_activation_mode": None,
        "trailing_activation": None,
        "chandelier_multiplier": 1.0,
        "chandelier_atr_period": 2,
        "chandelier_atr_method": "sma",
        "break_even_mode": None,
        "break_even": None,
        "break_even_buffer_mode": None,
        "break_even_buffer": None,
        "atr_period": 14,
        "atr_method": "wilder",
    }
    payload.update(overrides)
    return BacktestConfig(**payload)


def test_long_chandelier_ratchets_upward_only() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 9.0, 10.0, 8.0, 9.0),
            ("2025-01-01T01:00:00Z", 10.0, 12.0, 9.0, 11.0),
            ("2025-01-01T02:00:00Z", 11.0, 13.0, 10.0, 12.0),
            ("2025-01-01T03:00:00Z", 12.0, 12.5, 9.0, 10.0),
            ("2025-01-01T04:00:00Z", 10.0, 10.1, 9.9, 10.0),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", 1)])
    config = build_config()

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["trailing_stop_initial"] == pytest.approx(9.5)
    assert trade["trailing_stop_final"] == pytest.approx(10.0)
    assert trade["exit_reason"] == "chandelier_trailing_stop"


def test_short_chandelier_ratchets_downward_only() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 19.0, 20.0, 18.0, 19.0),
            ("2025-01-01T01:00:00Z", 20.0, 21.0, 18.0, 19.0),
            ("2025-01-01T02:00:00Z", 19.0, 20.0, 17.0, 18.0),
            ("2025-01-01T03:00:00Z", 18.0, 21.0, 17.5, 20.0),
            ("2025-01-01T04:00:00Z", 20.0, 20.1, 19.9, 20.0),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", -1)])
    config = build_config()

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["trailing_stop_initial"] == pytest.approx(20.5)
    assert trade["trailing_stop_final"] == pytest.approx(20.0)
    assert trade["exit_reason"] == "chandelier_trailing_stop"


def test_chandelier_activation_does_not_trigger_early() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 9.0, 10.0, 8.0, 9.0),
            ("2025-01-01T01:00:00Z", 10.0, 10.8, 9.5, 10.4),
            ("2025-01-01T02:00:00Z", 10.4, 12.2, 10.0, 11.1),
            ("2025-01-01T03:00:00Z", 11.1, 11.2, 11.0, 11.1),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", 1)])
    config = build_config(trailing_activation=2.0, trailing_activation_mode="absolute")

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["trailing_stop_initial"] == pytest.approx(10.2)


def test_long_chandelier_exit_occurs_with_next_bar_application() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 9.0, 10.0, 8.0, 9.0),
            ("2025-01-01T01:00:00Z", 10.0, 12.0, 9.0, 11.0),
            ("2025-01-01T02:00:00Z", 11.0, 13.0, 10.0, 12.0),
            ("2025-01-01T03:00:00Z", 12.0, 12.4, 9.9, 10.5),
            ("2025-01-01T04:00:00Z", 10.5, 10.6, 10.4, 10.5),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", 1)])
    config = build_config()

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["exit_reason"] == "chandelier_trailing_stop"
    assert trade["exit_time"] == pd.Timestamp("2025-01-01T03:00:00Z")
    assert trade["exit_price"] == pytest.approx(10.0)


def test_short_chandelier_exit_occurs_correctly() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 19.0, 20.0, 18.0, 19.0),
            ("2025-01-01T01:00:00Z", 20.0, 21.0, 18.0, 19.0),
            ("2025-01-01T02:00:00Z", 19.0, 20.0, 17.0, 18.0),
            ("2025-01-01T03:00:00Z", 18.0, 20.1, 17.5, 19.5),
            ("2025-01-01T04:00:00Z", 19.5, 19.6, 19.4, 19.5),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", -1)])
    config = build_config()

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["exit_reason"] == "chandelier_trailing_stop"
    assert trade["exit_time"] == pd.Timestamp("2025-01-01T03:00:00Z")
    assert trade["exit_price"] == pytest.approx(20.0)


def test_chandelier_stop_can_be_tighter_than_static_stop_loss() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 9.0, 10.0, 8.0, 9.0),
            ("2025-01-01T01:00:00Z", 10.0, 12.0, 9.0, 11.0),
            ("2025-01-01T02:00:00Z", 11.0, 12.1, 9.4, 10.5),
            ("2025-01-01T03:00:00Z", 10.5, 10.6, 10.4, 10.5),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", 1)])
    config = build_config(stop_loss=2.0, stop_loss_mode="absolute")

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["exit_reason"] == "chandelier_trailing_stop"
    assert trade["exit_price"] == pytest.approx(9.5)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"chandelier_multiplier": None}, "requires a positive chandelier_multiplier"),
        ({"trailing_stop": 1.0}, "not used with trailing_type='chandelier'"),
        ({"chandelier_atr_method": "bad_method"}, "Unsupported chandelier_atr_method"),
    ],
)
def test_invalid_chandelier_config_fails_clearly(overrides: dict[str, object], message: str) -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 9.0, 10.0, 8.0, 9.0),
            ("2025-01-01T01:00:00Z", 10.0, 12.0, 9.0, 11.0),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", 1)])
    config = build_config(**overrides)

    with pytest.raises(ValueError, match=message):
        run_backtest(candles, signals, config)
