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
        "timeframe": "15m",
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
        "trailing_activation_mode": None,
        "trailing_activation": None,
        "atr_period": 14,
        "atr_method": "wilder",
    }
    payload.update(overrides)
    return BacktestConfig(**payload)


def test_long_absolute_trailing_ratchets_upward_only() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 10.0, 10.2, 9.8, 10.0),
            ("2025-01-01T00:15:00Z", 10.0, 11.2, 9.4, 11.0),
            ("2025-01-01T00:30:00Z", 11.0, 11.6, 10.1, 11.4),
            ("2025-01-01T00:45:00Z", 11.4, 11.5, 10.6, 10.8),
            ("2025-01-01T01:00:00Z", 10.8, 10.9, 10.7, 10.85),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", 1)])
    config = build_config(trailing_stop=1.0, trailing_stop_mode="absolute")

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["trailing_stop_initial"] == pytest.approx(10.0)
    assert trade["trailing_stop_final"] == pytest.approx(10.4)
    assert trade["exit_reason"] == "forced_end"


def test_short_absolute_trailing_ratchets_downward_only() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 20.0, 20.2, 19.8, 20.0),
            ("2025-01-01T00:15:00Z", 20.0, 20.5, 18.7, 19.0),
            ("2025-01-01T00:30:00Z", 19.0, 19.2, 18.1, 18.6),
            ("2025-01-01T00:45:00Z", 18.6, 18.9, 18.4, 19.3),
            ("2025-01-01T01:00:00Z", 19.3, 19.4, 19.2, 19.25),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", -1)])
    config = build_config(trailing_stop=1.0, trailing_stop_mode="absolute")

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["trailing_stop_initial"] == pytest.approx(20.0)
    assert trade["trailing_stop_final"] == pytest.approx(19.6)
    assert trade["exit_reason"] == "forced_end"


def test_activated_trailing_does_not_activate_early_and_then_triggers() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 10.0, 10.1, 9.9, 10.0),
            ("2025-01-01T00:15:00Z", 10.0, 10.8, 9.9, 10.4),
            ("2025-01-01T00:30:00Z", 10.4, 11.2, 10.2, 10.9),
            ("2025-01-01T00:45:00Z", 10.9, 10.95, 10.0, 10.2),
            ("2025-01-01T01:00:00Z", 10.2, 10.3, 10.1, 10.25),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", 1)])
    config = build_config(
        trailing_stop=1.0,
        trailing_stop_mode="absolute",
        trailing_activation=1.0,
        trailing_activation_mode="absolute",
    )

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["trailing_stop_initial"] == pytest.approx(9.9)
    assert trade["trailing_stop_final"] == pytest.approx(9.9)


def test_trailing_stop_exit_for_long_uses_next_bar_after_update() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 10.0, 10.2, 9.8, 10.0),
            ("2025-01-01T00:15:00Z", 10.0, 11.2, 9.5, 11.0),
            ("2025-01-01T00:30:00Z", 11.0, 11.1, 9.8, 10.5),
            ("2025-01-01T00:45:00Z", 10.5, 10.6, 10.4, 10.5),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", 1)])
    config = build_config(trailing_stop=1.0, trailing_stop_mode="absolute")

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["exit_reason"] == "trailing_stop"
    assert trade["exit_time"] == pd.Timestamp("2025-01-01T00:30:00Z")
    assert trade["exit_price"] == pytest.approx(10.0)
    assert bool(trade["trailing_stop_exit_hit"]) is True


def test_trailing_stop_exit_for_short() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 20.0, 20.2, 19.8, 20.0),
            ("2025-01-01T00:15:00Z", 20.0, 20.3, 18.8, 19.0),
            ("2025-01-01T00:30:00Z", 19.0, 20.2, 18.7, 19.5),
            ("2025-01-01T00:45:00Z", 19.5, 19.6, 19.4, 19.45),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", -1)])
    config = build_config(trailing_stop=1.0, trailing_stop_mode="absolute")

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["exit_reason"] == "trailing_stop"
    assert trade["exit_time"] == pd.Timestamp("2025-01-01T00:30:00Z")
    assert trade["exit_price"] == pytest.approx(20.0)
    assert bool(trade["trailing_stop_exit_hit"]) is True


def test_static_stop_loss_remains_effective_before_trailing_activates() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 10.0, 10.2, 9.8, 10.0),
            ("2025-01-01T00:15:00Z", 10.0, 11.0, 9.4, 10.1),
            ("2025-01-01T00:30:00Z", 10.1, 10.2, 10.0, 10.15),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", 1)])
    config = build_config(
        stop_loss=0.5,
        stop_loss_mode="absolute",
        trailing_stop=1.0,
        trailing_stop_mode="absolute",
        trailing_activation=2.0,
        trailing_activation_mode="absolute",
    )

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["exit_reason"] == "stop_loss"
    assert trade["exit_price"] == pytest.approx(9.5)


def test_effective_stop_uses_tighter_of_static_and_trailing_stop() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 10.0, 10.2, 9.8, 10.0),
            ("2025-01-01T00:15:00Z", 10.0, 11.2, 9.8, 10.8),
            ("2025-01-01T00:30:00Z", 10.8, 10.9, 9.7, 10.2),
            ("2025-01-01T00:45:00Z", 10.2, 10.3, 10.1, 10.2),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", 1)])
    config = build_config(
        stop_loss=1.0,
        stop_loss_mode="absolute",
        trailing_stop=1.0,
        trailing_stop_mode="absolute",
    )

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["exit_reason"] == "trailing_stop"
    assert trade["exit_price"] == pytest.approx(9.8)


def test_atr_trailing_uses_live_atr_per_bar_for_distance() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 9.0, 10.0, 8.0, 9.0),
            ("2025-01-01T00:15:00Z", 10.0, 11.0, 9.0, 10.0),
            ("2025-01-01T00:30:00Z", 100.0, 101.0, 99.0, 100.0),
            ("2025-01-01T00:45:00Z", 100.0, 100.5, 99.5, 100.0),
        ]
    )
    signals = build_signals([("2025-01-01T00:15:00Z", 1)])
    config = build_config(
        trailing_stop=1.0,
        trailing_stop_mode="atr",
        atr_period=2,
        atr_method="sma",
    )

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["atr_at_entry"] == pytest.approx(2.0)
    assert trade["trailing_stop_initial"] == pytest.approx(53.5)


def test_atr_activation_mode_uses_atr_at_entry() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 9.0, 10.0, 8.0, 9.0),
            ("2025-01-01T00:15:00Z", 10.0, 11.0, 9.0, 10.0),
            ("2025-01-01T00:30:00Z", 10.0, 11.9, 9.9, 11.2),
            ("2025-01-01T00:45:00Z", 11.2, 12.1, 11.0, 11.4),
            ("2025-01-01T01:00:00Z", 11.4, 11.5, 11.3, 11.35),
        ]
    )
    signals = build_signals([("2025-01-01T00:15:00Z", 1)])
    config = build_config(
        trailing_stop=1.0,
        trailing_stop_mode="absolute",
        trailing_activation=1.0,
        trailing_activation_mode="atr",
        atr_period=2,
        atr_method="sma",
    )

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["atr_at_entry"] == pytest.approx(2.0)
    assert trade["trailing_stop_initial"] == pytest.approx(10.4)


def test_atr_trailing_distance_waits_for_atr_warmup_without_blocking_entry() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 10.0, 10.2, 9.8, 10.0),
            ("2025-01-01T00:15:00Z", 10.0, 10.4, 9.9, 10.3),
            ("2025-01-01T00:30:00Z", 10.3, 10.9, 10.2, 10.8),
            ("2025-01-01T00:45:00Z", 10.8, 11.0, 10.7, 10.9),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", 1)])
    config = build_config(trailing_stop=1.0, trailing_stop_mode="atr", atr_period=3, atr_method="sma")

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["entry_time"] == pd.Timestamp("2025-01-01T00:15:00Z")
    assert pd.isna(trade["atr_at_entry"])
    assert trade["trailing_stop_initial"] == pytest.approx(10.266666666666667)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"trailing_activation": 1.0}, "trailing_activation requires trailing_stop"),
        ({"trailing_stop_mode": "bad_mode", "trailing_stop": 1.0}, "Unsupported trailing_stop_mode"),
        ({"trailing_stop_mode": "absolute", "trailing_stop": -1.0}, "trailing_stop must be positive"),
        ({"trailing_activation_mode": "bad_mode", "trailing_stop": 1.0, "trailing_activation": 1.0}, "Unsupported trailing_activation_mode"),
    ],
)
def test_invalid_trailing_config_fails_clearly(overrides: dict[str, object], message: str) -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 10.0, 10.1, 9.9, 10.0),
            ("2025-01-01T00:15:00Z", 10.0, 10.2, 9.8, 10.1),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", 1)])
    config = build_config(**overrides)

    with pytest.raises(ValueError, match=message):
        run_backtest(candles, signals, config)


def test_no_trailing_behavior_remains_unchanged_when_trailing_disabled() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 10.0, 10.1, 9.9, 10.0),
            ("2025-01-01T00:15:00Z", 10.0, 10.2, 9.4, 10.0),
            ("2025-01-01T00:30:00Z", 10.0, 10.1, 9.9, 10.0),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", 1)])
    config = build_config(stop_loss=0.5, stop_loss_mode="absolute")

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["exit_reason"] == "stop_loss"
    assert pd.isna(trade["trailing_stop_initial"])
    assert pd.isna(trade["trailing_stop_final"])
