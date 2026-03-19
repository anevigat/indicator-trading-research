from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from indicator_trading_research.backtest.metrics import compute_backtest_metrics


def test_compute_backtest_metrics_includes_final_capital_and_risk_averages() -> None:
    trades = pd.DataFrame(
        [
            {
                "side": "long",
                "gross_pnl": 1.2,
                "net_pnl": 1.0,
                "duration_bars": 3,
                "exit_reason": "take_profit",
                "risk_amount": 1.0,
                "position_size_used": 10.0,
            },
            {
                "side": "short",
                "gross_pnl": -0.7,
                "net_pnl": -0.5,
                "duration_bars": 2,
                "exit_reason": "stop_loss",
                "risk_amount": 1.5,
                "position_size_used": 12.0,
            },
        ]
    )
    equity_curve = pd.DataFrame(
        [
            {"timestamp": pd.Timestamp("2025-01-01T00:15:00Z"), "equity": 101.0, "capital": 101.0},
            {"timestamp": pd.Timestamp("2025-01-01T00:30:00Z"), "equity": 100.5, "capital": 100.5},
        ]
    )

    metrics = compute_backtest_metrics(trades, equity_curve, initial_capital=100.0)

    assert metrics["initial_capital"] == pytest.approx(100.0)
    assert metrics["final_capital"] == pytest.approx(100.5)
    assert metrics["total_return_pct"] == pytest.approx(0.5)
    assert metrics["average_risk_amount"] == pytest.approx(1.25)
    assert metrics["average_position_size_used"] == pytest.approx(11.0)
    assert metrics["max_drawdown_pct"] == pytest.approx((100.5 / 101.0) - 1.0)
