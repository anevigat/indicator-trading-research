"""Reference strategies for the minimal backtesting framework."""

from .base import BaseStrategy
from .sma_crossover import SMACrossoverStrategy

__all__ = ["BaseStrategy", "SMACrossoverStrategy"]

