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
    }
    payload.update(overrides)
    return BacktestConfig(**payload)


def test_next_bar_long_entry_pricing() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 1.1000, 1.1004, 1.0995, 1.1001),
            ("2025-01-01T00:15:00Z", 1.1010, 1.1015, 1.1006, 1.1012),
            ("2025-01-01T00:30:00Z", 1.1013, 1.1018, 1.1009, 1.1014),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", 1)])
    config = build_config(spread=0.0002, slippage=0.0001)

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["side"] == "long"
    assert trade["entry_time"] == pd.Timestamp("2025-01-01T00:15:00Z")
    assert trade["entry_price"] == pytest.approx(1.1012)


def test_next_bar_short_entry_pricing() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 1.2000, 1.2004, 1.1997, 1.2001),
            ("2025-01-01T00:15:00Z", 1.2010, 1.2013, 1.2002, 1.2008),
            ("2025-01-01T00:30:00Z", 1.2007, 1.2010, 1.2000, 1.2005),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", -1)])
    config = build_config(spread=0.0002, slippage=0.00005)

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["side"] == "short"
    assert trade["entry_time"] == pd.Timestamp("2025-01-01T00:15:00Z")
    assert trade["entry_price"] == pytest.approx(1.20085)


def test_opposite_signal_exit_happens_on_next_open_and_flips_same_bar() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 1.1000, 1.1004, 1.0997, 1.1002),
            ("2025-01-01T00:15:00Z", 1.1010, 1.1014, 1.1008, 1.1011),
            ("2025-01-01T00:30:00Z", 1.0990, 1.0993, 1.0984, 1.0987),
            ("2025-01-01T00:45:00Z", 1.0985, 1.0988, 1.0980, 1.0983),
        ]
    )
    signals = build_signals(
        [
            ("2025-01-01T00:00:00Z", 1),
            ("2025-01-01T00:15:00Z", -1),
        ]
    )
    config = build_config(spread=0.0002, slippage=0.00005)

    result = run_backtest(candles, signals, config)

    first_trade = result.trades.iloc[0]
    second_trade = result.trades.iloc[1]
    assert first_trade["exit_time"] == pd.Timestamp("2025-01-01T00:30:00Z")
    assert first_trade["exit_reason"] == "signal_exit"
    assert first_trade["exit_price"] == pytest.approx(1.09885)
    assert second_trade["entry_time"] == pd.Timestamp("2025-01-01T00:30:00Z")
    assert second_trade["side"] == "short"


def test_end_of_data_forces_flat_on_final_close() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 1.1000, 1.1003, 1.0997, 1.1001),
            ("2025-01-01T00:15:00Z", 1.1010, 1.1015, 1.1008, 1.1012),
            ("2025-01-01T00:30:00Z", 1.1015, 1.1020, 1.1011, 1.1018),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", 1)])
    config = build_config(spread=0.0002, slippage=0.00005)

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["exit_time"] == pd.Timestamp("2025-01-01T00:30:00Z")
    assert trade["exit_reason"] == "forced_end"
    assert trade["exit_price"] == pytest.approx(1.10165)
    assert result.equity_curve.iloc[-1]["equity"] == pytest.approx(config.initial_capital + trade["net_pnl"])


@pytest.mark.parametrize(
    ("side_signal", "entry_open", "high", "low", "expected_stop", "expected_exit_price"),
    [
        (-1, 1.2000, 1.2015, 1.1980, 1.2010, 1.2010),
        (1, 1.1000, 1.1020, 1.0985, 1.0990, 1.0990),
    ],
)
def test_stop_loss_takes_precedence_when_stop_and_target_both_hit(
    side_signal: int,
    entry_open: float,
    high: float,
    low: float,
    expected_stop: float,
    expected_exit_price: float,
) -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", entry_open, entry_open, entry_open, entry_open),
            ("2025-01-01T00:15:00Z", entry_open, high, low, entry_open),
            ("2025-01-01T00:30:00Z", entry_open, entry_open, entry_open, entry_open),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", side_signal)])
    config = build_config(stop_loss_mode="absolute", stop_loss=0.0010, take_profit_mode="absolute", take_profit=0.0015)

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["stop_loss"] == pytest.approx(expected_stop)
    assert trade["exit_reason"] == "stop_loss"
    assert trade["exit_time"] == pd.Timestamp("2025-01-01T00:15:00Z")
    assert trade["exit_price"] == pytest.approx(expected_exit_price)


def test_repeated_same_direction_signals_do_not_create_duplicate_entries() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 1.1000, 1.1002, 1.0998, 1.1001),
            ("2025-01-01T00:15:00Z", 1.1005, 1.1009, 1.1002, 1.1007),
            ("2025-01-01T00:30:00Z", 1.1010, 1.1012, 1.1006, 1.1008),
            ("2025-01-01T00:45:00Z", 1.1012, 1.1015, 1.1007, 1.1011),
            ("2025-01-01T01:00:00Z", 1.1014, 1.1018, 1.1010, 1.1016),
        ]
    )
    signals = build_signals(
        [
            ("2025-01-01T00:00:00Z", 1),
            ("2025-01-01T00:15:00Z", 1),
            ("2025-01-01T00:30:00Z", 1),
        ]
    )
    config = build_config()

    result = run_backtest(candles, signals, config)

    assert len(result.trades) == 1
    assert result.trades.iloc[0]["side"] == "long"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"stop_loss_mode": "percent", "stop_loss": 0.0010}, "Unsupported stop_loss_mode"),
        ({"stop_loss_mode": "absolute", "stop_loss": -0.0010}, "stop_loss must be positive"),
        ({"take_profit_mode": "absolute", "take_profit": None}, "take_profit_mode requires take_profit"),
    ],
)
def test_invalid_stop_take_profit_config_fails_clearly(overrides: dict[str, object], message: str) -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 1.1000, 1.1001, 1.0999, 1.1000),
            ("2025-01-01T00:15:00Z", 1.1005, 1.1006, 1.1004, 1.1005),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", 1)])
    config = build_config(**overrides)

    with pytest.raises(ValueError, match=message):
        run_backtest(candles, signals, config)
