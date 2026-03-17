"""Simple SMA crossover reference strategy."""

from __future__ import annotations

import pandas as pd

from .base import BaseStrategy


class SMACrossoverStrategy(BaseStrategy):
    strategy_name = "sma_crossover"

    def __init__(self, *, short_window: int, long_window: int, allow_long: bool = True, allow_short: bool = True) -> None:
        if short_window <= 0 or long_window <= 0:
            raise ValueError("short_window and long_window must be positive integers.")
        if short_window >= long_window:
            raise ValueError("short_window must be strictly less than long_window.")
        super().__init__(
            short_window=short_window,
            long_window=long_window,
            allow_long=allow_long,
            allow_short=allow_short,
        )
        self.short_window = short_window
        self.long_window = long_window
        self.allow_long = allow_long
        self.allow_short = allow_short

    def generate_signals(self, candles: pd.DataFrame) -> pd.DataFrame:
        if candles.empty:
            raise ValueError("Cannot generate signals from an empty candle dataframe.")

        frame = candles[["timestamp", "close"]].copy()
        frame["short_sma"] = frame["close"].rolling(window=self.short_window, min_periods=self.short_window).mean()
        frame["long_sma"] = frame["close"].rolling(window=self.long_window, min_periods=self.long_window).mean()
        frame["regime"] = 0
        frame.loc[frame["short_sma"] > frame["long_sma"], "regime"] = 1
        frame.loc[frame["short_sma"] < frame["long_sma"], "regime"] = -1
        frame["previous_regime"] = frame["regime"].shift(1).fillna(0)
        frame["signal"] = 0

        if self.allow_long:
            frame.loc[(frame["regime"] == 1) & (frame["previous_regime"] <= 0), "signal"] = 1
        if self.allow_short:
            frame.loc[(frame["regime"] == -1) & (frame["previous_regime"] >= 0), "signal"] = -1

        frame["side"] = "flat"
        frame.loc[frame["signal"] > 0, "side"] = "long"
        frame.loc[frame["signal"] < 0, "side"] = "short"
        frame["tag"] = ""
        frame.loc[frame["signal"] > 0, "tag"] = f"sma_cross_up_{self.short_window}_{self.long_window}"
        frame.loc[frame["signal"] < 0, "tag"] = f"sma_cross_down_{self.short_window}_{self.long_window}"
        frame["strategy_name"] = self.strategy_name
        return frame[["timestamp", "signal", "side", "tag", "strategy_name"]].copy()

