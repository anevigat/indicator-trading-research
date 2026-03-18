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


def build_signals(rows: list[tuple[str, int, float | None, float | None]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["timestamp", "signal", "short_sma", "long_sma"])
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
        "ma_stop": False,
        "ma_stop_source": "short",
        "ma_stop_buffer_mode": None,
        "ma_stop_buffer": None,
        "atr_period": 14,
        "atr_method": "wilder",
    }
    payload.update(overrides)
    return BacktestConfig(**payload)


def test_long_ma_stop_ratchets_upward_only() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 10.0, 10.1, 9.9, 10.0),
            ("2025-01-01T01:00:00Z", 10.0, 10.5, 9.95, 10.4),
            ("2025-01-01T02:00:00Z", 10.4, 10.9, 10.3, 10.8),
            ("2025-01-01T03:00:00Z", 10.8, 11.0, 10.7, 10.9),
            ("2025-01-01T04:00:00Z", 10.9, 11.1, 10.8, 10.95),
        ]
    )
    signals = build_signals(
        [
            ("2025-01-01T00:00:00Z", 1, 9.9, 9.8),
            ("2025-01-01T01:00:00Z", 0, 10.2, 10.0),
            ("2025-01-01T02:00:00Z", 0, 10.6, 10.2),
            ("2025-01-01T03:00:00Z", 0, 10.5, 10.3),
            ("2025-01-01T04:00:00Z", 0, 10.4, 10.4),
        ]
    )
    config = build_config(ma_stop=True, ma_stop_source="short")

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["ma_stop_initial"] == pytest.approx(10.2)
    assert trade["ma_stop_final"] == pytest.approx(10.6)
    assert trade["ma_stop_exit_hit"] == False
    assert trade["exit_reason"] == "forced_end"


def test_short_ma_stop_ratchets_downward_only() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 20.0, 20.1, 19.9, 20.0),
            ("2025-01-01T01:00:00Z", 20.0, 20.05, 19.5, 19.6),
            ("2025-01-01T02:00:00Z", 19.6, 19.7, 19.0, 19.1),
            ("2025-01-01T03:00:00Z", 19.1, 19.2, 18.8, 18.95),
            ("2025-01-01T04:00:00Z", 18.95, 19.0, 18.7, 18.9),
        ]
    )
    signals = build_signals(
        [
            ("2025-01-01T00:00:00Z", -1, 20.2, 20.1),
            ("2025-01-01T01:00:00Z", 0, 19.8, 19.9),
            ("2025-01-01T02:00:00Z", 0, 19.4, 19.6),
            ("2025-01-01T03:00:00Z", 0, 19.5, 19.4),
            ("2025-01-01T04:00:00Z", 0, 19.6, 19.3),
        ]
    )
    config = build_config(ma_stop=True, ma_stop_source="long")

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["ma_stop_initial"] == pytest.approx(19.9)
    assert trade["ma_stop_final"] == pytest.approx(19.3)
    assert trade["ma_stop_exit_hit"] == False
    assert trade["exit_reason"] == "forced_end"


def test_ma_stop_buffer_is_applied_for_long_trades() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 10.0, 10.1, 9.9, 10.0),
            ("2025-01-01T01:00:00Z", 10.0, 10.5, 9.95, 10.4),
            ("2025-01-01T02:00:00Z", 10.4, 10.6, 10.3, 10.5),
        ]
    )
    signals = build_signals(
        [
            ("2025-01-01T00:00:00Z", 1, 9.8, 9.7),
            ("2025-01-01T01:00:00Z", 0, 10.5, 10.0),
            ("2025-01-01T02:00:00Z", 0, 10.6, 10.1),
        ]
    )
    config = build_config(ma_stop=True, ma_stop_source="short", ma_stop_buffer=0.2, ma_stop_buffer_mode="absolute")

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["ma_stop_initial"] == pytest.approx(10.3)


def test_ma_stop_buffer_atr_mode_uses_live_atr() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 10.0, 11.0, 9.0, 10.0),
            ("2025-01-01T01:00:00Z", 10.0, 11.0, 9.0, 10.0),
            ("2025-01-01T02:00:00Z", 10.0, 11.0, 9.0, 10.4),
            ("2025-01-01T03:00:00Z", 10.4, 11.4, 10.2, 11.0),
            ("2025-01-01T04:00:00Z", 11.0, 11.2, 10.9, 11.1),
        ]
    )
    signals = build_signals(
        [
            ("2025-01-01T00:00:00Z", 0, 9.8, 9.7),
            ("2025-01-01T01:00:00Z", 1, 10.0, 9.8),
            ("2025-01-01T02:00:00Z", 0, 11.0, 10.1),
            ("2025-01-01T03:00:00Z", 0, 12.5, 10.8),
            ("2025-01-01T04:00:00Z", 0, 11.9, 11.0),
        ]
    )
    config = build_config(
        ma_stop=True,
        ma_stop_source="short",
        ma_stop_buffer=0.5,
        ma_stop_buffer_mode="atr",
        atr_period=2,
        atr_method="sma",
    )

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["ma_stop_initial"] == pytest.approx(10.0)
    assert trade["ma_stop_final"] == pytest.approx(11.7)


def test_ma_stop_can_be_tighter_than_static_stop_loss() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 10.0, 10.1, 9.9, 10.0),
            ("2025-01-01T01:00:00Z", 10.0, 11.0, 9.9, 10.8),
            ("2025-01-01T02:00:00Z", 10.8, 10.9, 10.35, 10.4),
            ("2025-01-01T03:00:00Z", 10.4, 10.5, 10.3, 10.4),
        ]
    )
    signals = build_signals(
        [
            ("2025-01-01T00:00:00Z", 1, 9.9, 9.8),
            ("2025-01-01T01:00:00Z", 0, 10.6, 10.1),
            ("2025-01-01T02:00:00Z", 0, 10.55, 10.2),
            ("2025-01-01T03:00:00Z", 0, 10.5, 10.3),
        ]
    )
    config = build_config(
        stop_loss=1.0,
        stop_loss_mode="absolute",
        ma_stop=True,
        ma_stop_source="short",
    )

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["exit_reason"] == "ma_stop"
    assert trade["exit_price"] == pytest.approx(10.6)
    assert result.metrics["ma_stop_exits"] == 1


def test_ma_stop_skips_entry_when_selected_ma_is_unavailable_at_signal_bar() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 10.0, 10.1, 9.9, 10.0),
            ("2025-01-01T01:00:00Z", 10.0, 10.2, 9.8, 10.1),
            ("2025-01-01T02:00:00Z", 10.1, 10.3, 9.9, 10.2),
        ]
    )
    signals = build_signals(
        [
            ("2025-01-01T00:00:00Z", 1, None, 9.8),
            ("2025-01-01T01:00:00Z", 0, 10.0, 9.9),
            ("2025-01-01T02:00:00Z", 0, 10.1, 10.0),
        ]
    )
    config = build_config(ma_stop=True, ma_stop_source="short")

    result = run_backtest(candles, signals, config)

    assert result.trades.empty


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"ma_stop": True, "ma_stop_source": "bad"}, "Unsupported ma_stop_source"),
        ({"ma_stop": True, "ma_stop_buffer": -0.1, "ma_stop_buffer_mode": "absolute"}, "ma_stop_buffer must be zero or positive"),
        ({"ma_stop": False, "ma_stop_buffer": 0.1, "ma_stop_buffer_mode": "absolute"}, "ma_stop_buffer and ma_stop_buffer_mode require ma_stop to be enabled"),
    ],
)
def test_invalid_ma_stop_config_fails_clearly(overrides: dict[str, object], message: str) -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 10.0, 10.1, 9.9, 10.0),
            ("2025-01-01T01:00:00Z", 10.0, 10.2, 9.8, 10.1),
        ]
    )
    signals = build_signals(
        [
            ("2025-01-01T00:00:00Z", 1, 9.9, 9.8),
            ("2025-01-01T01:00:00Z", 0, 10.0, 9.9),
        ]
    )
    config = build_config(**overrides)

    with pytest.raises(ValueError, match=message):
        run_backtest(candles, signals, config)
