"""Reusable strategy interface for minimal backtests."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass
class StrategyContext:
    strategy_name: str
    params: dict[str, Any]


class BaseStrategy(ABC):
    """Strategies generate close-of-bar signals; the engine executes on the next bar."""

    strategy_name: str

    def __init__(self, **params: Any) -> None:
        self.params = params

    @abstractmethod
    def generate_signals(self, candles: pd.DataFrame) -> pd.DataFrame:
        """Return a signal dataframe with at least timestamp, signal, and strategy_name."""

