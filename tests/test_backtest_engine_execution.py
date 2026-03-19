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
        "position_sizing_mode": "fixed",
        "risk_percent": None,
        "account_currency": "USD",
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
        "atr_period": 14,
        "atr_method": "wilder",
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


def test_atr_long_stop_and_target_are_placed_from_signal_bar_atr() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 10.0, 11.0, 9.0, 10.0),
            ("2025-01-01T00:15:00Z", 12.0, 15.0, 11.0, 13.0),
            ("2025-01-01T00:30:00Z", 20.0, 20.5, 19.5, 20.1),
            ("2025-01-01T00:45:00Z", 20.2, 20.4, 19.9, 20.0),
        ]
    )
    signals = build_signals([("2025-01-01T00:15:00Z", 1)])
    config = build_config(
        stop_loss_mode="atr",
        stop_loss=1.0,
        take_profit_mode="atr",
        take_profit=2.0,
        atr_period=2,
        atr_method="sma",
    )

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["atr_at_entry"] == pytest.approx(3.5)
    assert trade["entry_time"] == pd.Timestamp("2025-01-01T00:30:00Z")
    assert trade["stop_loss"] == pytest.approx(16.5)
    assert trade["take_profit"] == pytest.approx(27.0)


def test_atr_short_stop_and_target_are_placed_from_signal_bar_atr() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 9.0, 10.0, 8.0, 9.0),
            ("2025-01-01T00:15:00Z", 9.5, 13.0, 8.0, 10.0),
            ("2025-01-01T00:30:00Z", 20.0, 20.5, 19.5, 19.9),
            ("2025-01-01T00:45:00Z", 19.8, 20.0, 19.4, 19.7),
        ]
    )
    signals = build_signals([("2025-01-01T00:15:00Z", -1)])
    config = build_config(
        stop_loss_mode="atr",
        stop_loss=1.0,
        take_profit_mode="atr",
        take_profit=2.0,
        atr_period=2,
        atr_method="sma",
    )

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["atr_at_entry"] == pytest.approx(3.5)
    assert trade["entry_time"] == pd.Timestamp("2025-01-01T00:30:00Z")
    assert trade["stop_loss"] == pytest.approx(23.5)
    assert trade["take_profit"] == pytest.approx(13.0)


@pytest.mark.parametrize(
    ("stop_mode", "stop_value", "expected_stop", "take_mode", "take_value", "expected_take"),
    [
        ("atr", 1.5, 14.75, "absolute", 0.75, 20.75),
        ("absolute", 0.5, 19.5, "atr", 2.0, 27.0),
    ],
)
def test_mixed_absolute_and_atr_modes_work_together(
    stop_mode: str,
    stop_value: float,
    expected_stop: float,
    take_mode: str,
    take_value: float,
    expected_take: float,
) -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 10.0, 11.0, 9.0, 10.0),
            ("2025-01-01T00:15:00Z", 12.0, 15.0, 11.0, 13.0),
            ("2025-01-01T00:30:00Z", 20.0, 20.4, 19.8, 20.1),
            ("2025-01-01T00:45:00Z", 20.2, 20.5, 19.9, 20.0),
        ]
    )
    signals = build_signals([("2025-01-01T00:15:00Z", 1)])
    config = build_config(
        stop_loss_mode=stop_mode,
        stop_loss=stop_value,
        take_profit_mode=take_mode,
        take_profit=take_value,
        atr_period=2,
        atr_method="sma",
    )

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["stop_loss"] == pytest.approx(expected_stop)
    assert trade["take_profit"] == pytest.approx(expected_take)


def test_atr_warmup_skips_signal_until_atr_is_available() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 10.0, 11.0, 9.0, 10.0),
            ("2025-01-01T00:15:00Z", 10.1, 10.5, 9.9, 10.2),
            ("2025-01-01T00:30:00Z", 10.2, 10.6, 10.0, 10.3),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", 1)])
    config = build_config(stop_loss_mode="atr", stop_loss=1.0, atr_period=3, atr_method="wilder")

    result = run_backtest(candles, signals, config)

    assert result.trades.empty


def test_atr_is_frozen_from_signal_bar_and_does_not_look_ahead_to_entry_bar() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 9.5, 10.0, 8.0, 9.0),
            ("2025-01-01T00:15:00Z", 10.0, 11.0, 9.0, 10.0),
            ("2025-01-01T00:30:00Z", 100.0, 110.0, 90.0, 100.0),
            ("2025-01-01T00:45:00Z", 100.0, 101.0, 99.0, 100.0),
        ]
    )
    signals = build_signals([("2025-01-01T00:15:00Z", 1)])
    config = build_config(stop_loss_mode="atr", stop_loss=1.0, atr_period=2, atr_method="sma")

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["atr_at_entry"] == pytest.approx(2.0)
    assert trade["stop_loss"] == pytest.approx(98.0)


def test_invalid_atr_method_in_engine_config_fails_clearly() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 1.1000, 1.1001, 1.0999, 1.1000),
            ("2025-01-01T00:15:00Z", 1.1005, 1.1006, 1.1004, 1.1005),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", 1)])
    config = build_config(stop_loss_mode="atr", stop_loss=1.0, atr_method="bad_method")

    with pytest.raises(ValueError, match="Unsupported atr_method"):
        run_backtest(candles, signals, config)


def test_fixed_position_size_mode_keeps_existing_size_behavior() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 1.1000, 1.1002, 1.0998, 1.1000),
            ("2025-01-01T00:15:00Z", 1.1010, 1.1015, 1.1009, 1.1012),
            ("2025-01-01T00:30:00Z", 1.1020, 1.1024, 1.1018, 1.1021),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", 1)])
    config = build_config(fixed_position_size=2.5)

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    assert trade["position_size_used"] == pytest.approx(2.5)
    assert trade["capital_before"] == pytest.approx(10_000.0)


def test_risk_percent_position_size_uses_capital_and_stop_distance() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 1.1000, 1.1002, 1.0998, 1.1000),
            ("2025-01-01T00:15:00Z", 1.1000, 1.1006, 1.0994, 1.1003),
            ("2025-01-01T00:30:00Z", 1.1008, 1.1010, 1.1004, 1.1009),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", 1)])
    config = build_config(
        initial_capital=100.0,
        fixed_position_size=1.0,
        position_sizing_mode="risk_percent",
        risk_percent=0.01,
        stop_loss_mode="absolute",
        stop_loss=0.0020,
    )

    result = run_backtest(candles, signals, config)

    trade = result.trades.iloc[0]
    expected_risk = 1.0
    expected_size = expected_risk / 0.0020
    assert trade["risk_amount"] == pytest.approx(expected_risk)
    assert trade["stop_distance_at_entry"] == pytest.approx(0.0020)
    assert trade["position_size_used"] == pytest.approx(expected_size)


def test_risk_percent_capital_compounds_between_trades() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 10.0, 10.0, 10.0, 10.0),
            ("2025-01-01T00:15:00Z", 10.0, 11.5, 9.9, 11.2),
            ("2025-01-01T00:30:00Z", 11.0, 11.0, 11.0, 11.0),
            ("2025-01-01T00:45:00Z", 11.0, 12.5, 10.9, 12.2),
            ("2025-01-01T01:00:00Z", 12.0, 12.0, 12.0, 12.0),
        ]
    )
    signals = build_signals(
        [
            ("2025-01-01T00:00:00Z", 1),
            ("2025-01-01T00:30:00Z", 1),
        ]
    )
    config = build_config(
        initial_capital=100.0,
        position_sizing_mode="risk_percent",
        risk_percent=0.01,
        stop_loss_mode="absolute",
        stop_loss=1.0,
        take_profit_mode="absolute",
        take_profit=1.0,
    )

    result = run_backtest(candles, signals, config)

    first_trade = result.trades.iloc[0]
    second_trade = result.trades.iloc[1]
    assert first_trade["capital_before"] == pytest.approx(100.0)
    assert first_trade["capital_after"] == pytest.approx(101.0)
    assert second_trade["capital_before"] == pytest.approx(101.0)
    assert second_trade["risk_amount"] == pytest.approx(1.01)
    assert result.metrics["final_capital"] == pytest.approx(float(second_trade["capital_after"]))


def test_risk_percent_requires_entry_time_stop_provider() -> None:
    candles = build_candles(
        [
            ("2025-01-01T00:00:00Z", 1.1000, 1.1001, 1.0999, 1.1000),
            ("2025-01-01T00:15:00Z", 1.1005, 1.1006, 1.1004, 1.1005),
        ]
    )
    signals = build_signals([("2025-01-01T00:00:00Z", 1)])
    config = build_config(position_sizing_mode="risk_percent", risk_percent=0.01, stop_loss=None, stop_loss_mode=None)

    with pytest.raises(ValueError, match="entry-time stop"):
        run_backtest(candles, signals, config)
