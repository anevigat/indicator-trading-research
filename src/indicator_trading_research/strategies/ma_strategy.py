"""Generic moving-average strategy for Phase S1."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

import numpy as np
import pandas as pd

from .base import BaseStrategy

SUPPORTED_MA_TYPES = {"sma", "ema", "wma", "hma"}
SUPPORTED_ENTRY_TYPES = {"crossover", "price_above_all", "crossover_breakout"}


def _compute_wma(series: pd.Series, period: int) -> pd.Series:
    weights = np.arange(1, period + 1, dtype=float)
    denominator = float(weights.sum())
    return series.rolling(window=period, min_periods=period).apply(
        lambda values: float(np.dot(values, weights) / denominator),
        raw=True,
    )


def compute_ma(series: pd.Series, period: int, ma_type: str) -> pd.Series:
    normalized_type = ma_type.strip().lower()
    if period <= 0:
        raise ValueError("MA period must be a positive integer.")
    if normalized_type == "sma":
        return series.rolling(window=period, min_periods=period).mean()
    if normalized_type == "ema":
        return series.ewm(span=period, adjust=False, min_periods=period).mean()
    if normalized_type == "wma":
        return _compute_wma(series, period)
    if normalized_type == "hma":
        half_period = max(period // 2, 1)
        sqrt_period = max(int(math.sqrt(period)), 1)
        wma_half = _compute_wma(series, half_period)
        wma_full = _compute_wma(series, period)
        hull_input = 2.0 * wma_half - wma_full
        return _compute_wma(hull_input, sqrt_period)
    supported = ", ".join(sorted(SUPPORTED_MA_TYPES))
    raise ValueError(f"Unsupported ma_type: {ma_type!r}. Supported types: {supported}.")


@dataclass(frozen=True)
class MASpec:
    period: int
    ma_type: str
    original_index: int


MAKey = tuple[str, int]


def build_ma_cache(candles: pd.DataFrame, required_keys: set[MAKey]) -> dict[MAKey, pd.Series]:
    """Precompute MA series keyed by (ma_type, period) for a candle slice."""
    if not required_keys:
        return {}
    if "close" not in candles.columns:
        raise ValueError("Candles must include a close column to build an MA cache.")

    close = candles["close"]
    cache: dict[MAKey, pd.Series] = {}
    for ma_type, period in sorted(required_keys, key=lambda item: (item[1], item[0])):
        cache[(ma_type, period)] = compute_ma(close, period, ma_type)
    return cache


class MAStrategy(BaseStrategy):
    strategy_name = "ma_strategy"

    def __init__(
        self,
        *,
        ma_types: list[str],
        ma_periods: list[int],
        entry_type: str,
        allow_long: bool = True,
        allow_short: bool = True,
    ) -> None:
        if len(ma_types) != len(ma_periods):
            raise ValueError("ma_types and ma_periods must have the same length.")
        if len(ma_types) not in {2, 3}:
            raise ValueError("Phase S1 supports exactly 2 or 3 moving averages.")

        normalized_entry_type = entry_type.strip().lower()
        if normalized_entry_type not in SUPPORTED_ENTRY_TYPES:
            supported = ", ".join(sorted(SUPPORTED_ENTRY_TYPES))
            raise ValueError(f"Unsupported entry_type: {entry_type!r}. Supported types: {supported}.")
        if normalized_entry_type == "crossover" and len(ma_types) != 2:
            raise ValueError("entry_type='crossover' currently supports exactly 2 moving averages.")

        specs: list[MASpec] = []
        for index, (ma_type, period) in enumerate(zip(ma_types, ma_periods, strict=True)):
            normalized_type = ma_type.strip().lower()
            if normalized_type not in SUPPORTED_MA_TYPES:
                supported = ", ".join(sorted(SUPPORTED_MA_TYPES))
                raise ValueError(f"Unsupported ma_type: {ma_type!r}. Supported types: {supported}.")
            if period <= 0:
                raise ValueError("All ma_periods must be positive integers.")
            specs.append(MASpec(period=int(period), ma_type=normalized_type, original_index=index))

        self.ma_specs = sorted(specs, key=lambda spec: (spec.period, spec.original_index))
        self.entry_type = normalized_entry_type
        self.allow_long = allow_long
        self.allow_short = allow_short
        super().__init__(
            ma_types=[spec.ma_type for spec in self.ma_specs],
            ma_periods=[spec.period for spec in self.ma_specs],
            entry_type=self.entry_type,
            allow_long=allow_long,
            allow_short=allow_short,
        )

    def required_ma_keys(self) -> set[MAKey]:
        return {(spec.ma_type, spec.period) for spec in self.ma_specs}

    def generate_signals(
        self,
        candles: pd.DataFrame,
        *,
        indicator_cache: Mapping[MAKey, pd.Series] | None = None,
    ) -> pd.DataFrame:
        if candles.empty:
            raise ValueError("Cannot generate signals from an empty candle dataframe.")

        frame = candles[["timestamp", "close"]].copy()
        ma_columns: list[str] = []
        for index, spec in enumerate(self.ma_specs, start=1):
            column = f"ma_{index}"
            cache_key = (spec.ma_type, spec.period)
            if indicator_cache is not None and cache_key in indicator_cache:
                frame[column] = indicator_cache[cache_key]
            else:
                frame[column] = compute_ma(frame["close"], spec.period, spec.ma_type)
            ma_columns.append(column)

        frame["ma_fast"] = frame[ma_columns[0]]
        frame["ma_slow"] = frame[ma_columns[-1]]
        ma_values = frame[ma_columns]
        all_available = ma_values.notna().all(axis=1)
        above_all = all_available & (frame["close"].to_numpy()[:, None] > ma_values.to_numpy()).all(axis=1)
        below_all = all_available & (frame["close"].to_numpy()[:, None] < ma_values.to_numpy()).all(axis=1)

        fast = frame["ma_fast"]
        slow = frame["ma_slow"]
        previous_fast = fast.shift(1)
        previous_slow = slow.shift(1)
        crossover_up = (fast > slow) & (previous_fast <= previous_slow)
        crossover_down = (fast < slow) & (previous_fast >= previous_slow)

        frame["signal"] = 0
        tag_suffix = "_".join(f"{spec.ma_type}{spec.period}" for spec in self.ma_specs)
        if self.entry_type == "crossover":
            if self.allow_long:
                frame.loc[crossover_up.fillna(False), "signal"] = 1
            if self.allow_short:
                frame.loc[crossover_down.fillna(False), "signal"] = -1
        elif self.entry_type == "price_above_all":
            frame["regime"] = 0
            frame.loc[above_all, "regime"] = 1
            frame.loc[below_all, "regime"] = -1
            frame["previous_regime"] = frame["regime"].shift(1).fillna(0)
            if self.allow_long:
                frame.loc[(frame["regime"] == 1) & (frame["previous_regime"] <= 0), "signal"] = 1
            if self.allow_short:
                frame.loc[(frame["regime"] == -1) & (frame["previous_regime"] >= 0), "signal"] = -1
            frame = frame.drop(columns=["regime", "previous_regime"])
        else:
            if self.allow_long:
                frame.loc[crossover_up.fillna(False) & above_all, "signal"] = 1
            if self.allow_short:
                frame.loc[crossover_down.fillna(False) & below_all, "signal"] = -1

        frame["side"] = "flat"
        frame.loc[frame["signal"] > 0, "side"] = "long"
        frame.loc[frame["signal"] < 0, "side"] = "short"
        frame["tag"] = ""
        frame.loc[frame["signal"] > 0, "tag"] = f"{self.entry_type}_long_{tag_suffix}"
        frame.loc[frame["signal"] < 0, "tag"] = f"{self.entry_type}_short_{tag_suffix}"
        frame["strategy_name"] = self.strategy_name

        output_columns = ["timestamp", "signal", "side", "tag", "strategy_name", *ma_columns, "ma_fast", "ma_slow"]
        return frame[output_columns].copy()
