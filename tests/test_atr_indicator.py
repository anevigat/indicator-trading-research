from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from indicator_trading_research.indicators import compute_atr, compute_true_range


def build_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01", periods=4, freq="1h", tz="UTC"),
            "open": [9.0, 9.5, 10.5, 11.0],
            "high": [10.0, 11.0, 12.0, 13.0],
            "low": [8.0, 8.0, 9.0, 10.0],
            "close": [9.0, 10.0, 11.0, 12.0],
        }
    )


def test_true_range_uses_standard_definition() -> None:
    frame = build_frame()
    true_range = compute_true_range(frame)
    assert true_range.tolist() == pytest.approx([2.0, 3.0, 3.0, 3.0])


def test_atr_wilder_matches_seeded_recursive_definition() -> None:
    frame = build_frame()
    atr = compute_atr(frame, period=3, method="wilder")
    assert atr.tolist() == pytest.approx([float("nan"), float("nan"), 8.0 / 3.0, 25.0 / 9.0], nan_ok=True)


def test_atr_sma_matches_simple_rolling_average() -> None:
    frame = build_frame()
    atr = compute_atr(frame, period=3, method="sma")
    assert atr.tolist() == pytest.approx([float("nan"), float("nan"), 8.0 / 3.0, 3.0], nan_ok=True)


def test_atr_ema_matches_span_based_exponential_average() -> None:
    frame = build_frame()
    atr = compute_atr(frame, period=3, method="ema")
    assert atr.tolist() == pytest.approx([float("nan"), float("nan"), 2.75, 2.875], nan_ok=True)


def test_invalid_atr_method_fails_clearly() -> None:
    frame = build_frame()
    with pytest.raises(ValueError, match="Unsupported ATR method"):
        compute_atr(frame, period=3, method="bad_method")
