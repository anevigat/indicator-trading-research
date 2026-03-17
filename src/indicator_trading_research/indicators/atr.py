"""Average True Range helpers.

True range uses the standard definition:

- high - low
- abs(high - previous_close)
- abs(low - previous_close)

ATR methods supported:

- ``wilder``: seed with SMA(period) of true range, then recurse with
  ``((previous_atr * (period - 1)) + current_tr) / period``
- ``sma``: simple moving average of true range over ``period``
- ``ema``: exponential moving average of true range with ``span=period`` and
  ``adjust=False``
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SUPPORTED_ATR_METHODS = {"wilder", "sma", "ema"}


def compute_true_range(frame: pd.DataFrame) -> pd.Series:
    """Return true range aligned to ``frame``."""

    required = {"high", "low", "close"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Cannot compute true range without columns: {missing}")

    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    previous_close = frame["close"].astype(float).shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rename("true_range")


def _compute_wilder_atr(true_range: pd.Series, period: int) -> pd.Series:
    values = true_range.astype(float).to_numpy()
    result = np.full(len(values), np.nan, dtype=float)
    if len(values) < period:
        return pd.Series(result, index=true_range.index, name="atr")

    seed = float(np.mean(values[:period]))
    result[period - 1] = seed
    for index in range(period, len(values)):
        result[index] = ((result[index - 1] * (period - 1)) + values[index]) / period
    return pd.Series(result, index=true_range.index, name="atr")


def compute_atr(frame: pd.DataFrame, *, period: int = 14, method: str = "wilder") -> pd.Series:
    """Return ATR aligned to ``frame`` using the requested smoothing method."""

    if not isinstance(period, int) or period <= 0:
        raise ValueError("ATR period must be a positive integer.")

    normalized_method = method.strip().lower()
    if normalized_method not in SUPPORTED_ATR_METHODS:
        supported = ", ".join(sorted(SUPPORTED_ATR_METHODS))
        raise ValueError(f"Unsupported ATR method: {method!r}. Supported methods: {supported}.")

    true_range = compute_true_range(frame)
    if normalized_method == "wilder":
        return _compute_wilder_atr(true_range, period)
    if normalized_method == "sma":
        return true_range.rolling(window=period, min_periods=period).mean().rename("atr")
    return true_range.ewm(span=period, adjust=False, min_periods=period).mean().rename("atr")
