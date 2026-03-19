"""Reference strategies for the minimal backtesting framework."""

from .base import BaseStrategy
from .ma_strategy import MAStrategy, build_ma_cache, compute_ma
from .sma_crossover import SMACrossoverStrategy

__all__ = ["BaseStrategy", "MAStrategy", "SMACrossoverStrategy", "build_ma_cache", "compute_ma"]
