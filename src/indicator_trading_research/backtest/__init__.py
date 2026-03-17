"""Minimal backtesting framework contracts and helpers."""

from .contracts import BacktestConfig, BacktestResult, TradeRecord
from .engine import run_backtest
from .io import load_backtest_candles, save_backtest_result
from .metrics import compute_backtest_metrics

__all__ = [
    "BacktestConfig",
    "BacktestResult",
    "TradeRecord",
    "compute_backtest_metrics",
    "load_backtest_candles",
    "run_backtest",
    "save_backtest_result",
]

