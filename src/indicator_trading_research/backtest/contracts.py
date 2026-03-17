"""Typed contracts for the minimal backtesting framework."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd


@dataclass
class BacktestConfig:
    pair: str
    timeframe: str
    strategy_name: str
    start_date: str
    end_date: str
    initial_capital: float
    fixed_position_size: float
    strategy_params: dict[str, Any] = field(default_factory=dict)
    spread: float = 0.0
    slippage: float = 0.0
    fee_per_trade: float = 0.0
    allow_long: bool = True
    allow_short: bool = True
    one_position_at_a_time: bool = True
    stop_loss_mode: str | None = None
    stop_loss: float | None = None
    take_profit_mode: str | None = None
    take_profit: float | None = None
    trailing_stop_mode: str | None = None
    trailing_stop: float | None = None
    trailing_activation_mode: str | None = None
    trailing_activation: float | None = None
    atr_period: int = 14
    atr_method: str = "wilder"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TradeRecord:
    trade_id: str
    pair: str
    timeframe: str
    side: str
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    size: float | None = None
    pnl: float | None = None
    outcome: str | None = None
    strategy_name: str | None = None
    notes: str | None = None
    atr_at_entry: float | None = None
    trailing_stop_initial: float | None = None
    trailing_stop_final: float | None = None
    trailing_stop_exit_hit: bool | None = None
    exit_reason: str | None = None
    duration_bars: int | None = None
    gross_pnl: float | None = None
    net_pnl: float | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in ("entry_time", "exit_time"):
            value = payload[key]
            if value is not None:
                payload[key] = pd.Timestamp(value)
        return payload


@dataclass
class BacktestResult:
    config: BacktestConfig
    trades: pd.DataFrame
    metrics: dict[str, Any]
    equity_curve: pd.DataFrame | None = None
    signals: pd.DataFrame | None = None
    candles: pd.DataFrame | None = None
