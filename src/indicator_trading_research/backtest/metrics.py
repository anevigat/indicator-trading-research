"""Metrics for minimal backtest runs."""

from __future__ import annotations

import math

import pandas as pd


def _safe_float(value: float | int | None) -> float:
    return float(value) if value is not None else 0.0


def compute_backtest_metrics(trades: pd.DataFrame, equity_curve: pd.DataFrame, initial_capital: float) -> dict[str, float | int | None]:
    if trades.empty:
        ending_equity = float(equity_curve["equity"].iloc[-1]) if not equity_curve.empty else float(initial_capital)
        return {
            "total_trades": 0,
            "gross_pnl": 0.0,
            "net_pnl": 0.0,
            "win_rate": 0.0,
            "average_win": 0.0,
            "average_loss": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "max_drawdown": 0.0,
            "ending_equity": ending_equity,
            "average_trade_duration_bars": 0.0,
            "long_trades_count": 0,
            "short_trades_count": 0,
            "stop_loss_exits": 0,
            "trailing_stop_exits": 0,
            "take_profit_exits": 0,
            "signal_exits": 0,
            "forced_end_exits": 0,
        }

    gross_pnl = float(trades["gross_pnl"].fillna(0.0).sum()) if "gross_pnl" in trades.columns else float(trades["pnl"].fillna(0.0).sum())
    net_pnl = float(trades["net_pnl"].fillna(trades.get("pnl", 0.0)).sum())
    wins = trades[trades["net_pnl"] > 0]
    losses = trades[trades["net_pnl"] < 0]
    average_win = float(wins["net_pnl"].mean()) if not wins.empty else 0.0
    average_loss = float(losses["net_pnl"].mean()) if not losses.empty else 0.0
    gross_profit = float(wins["net_pnl"].sum()) if not wins.empty else 0.0
    gross_loss_abs = abs(float(losses["net_pnl"].sum())) if not losses.empty else 0.0
    if gross_loss_abs == 0.0:
        profit_factor = math.inf if gross_profit > 0 else 0.0
    else:
        profit_factor = gross_profit / gross_loss_abs

    if equity_curve.empty:
        max_drawdown = 0.0
        ending_equity = initial_capital + net_pnl
    else:
        running_peak = equity_curve["equity"].cummax()
        drawdown = equity_curve["equity"] - running_peak
        max_drawdown = float(drawdown.min())
        ending_equity = float(equity_curve["equity"].iloc[-1])

    duration = float(trades["duration_bars"].mean()) if "duration_bars" in trades.columns and not trades.empty else 0.0
    return {
        "total_trades": int(len(trades)),
        "gross_pnl": gross_pnl,
        "net_pnl": net_pnl,
        "win_rate": float(len(wins) / len(trades)) if len(trades) else 0.0,
        "average_win": average_win,
        "average_loss": average_loss,
        "profit_factor": profit_factor,
        "expectancy": float(net_pnl / len(trades)) if len(trades) else 0.0,
        "max_drawdown": max_drawdown,
        "ending_equity": ending_equity,
        "average_trade_duration_bars": duration,
        "long_trades_count": int((trades["side"] == "long").sum()),
        "short_trades_count": int((trades["side"] == "short").sum()),
        "stop_loss_exits": int((trades["exit_reason"] == "stop_loss").sum()) if "exit_reason" in trades.columns else 0,
        "trailing_stop_exits": int((trades["exit_reason"] == "trailing_stop").sum()) if "exit_reason" in trades.columns else 0,
        "take_profit_exits": int((trades["exit_reason"] == "take_profit").sum()) if "exit_reason" in trades.columns else 0,
        "signal_exits": int((trades["exit_reason"] == "signal_exit").sum()) if "exit_reason" in trades.columns else 0,
        "forced_end_exits": int((trades["exit_reason"] == "forced_end").sum()) if "exit_reason" in trades.columns else 0,
    }
