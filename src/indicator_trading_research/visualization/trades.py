"""Minimal trade overlay hooks for future chart annotations."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import plotly.graph_objects as go


@dataclass
class TradeOverlayColumns:
    entry_time: str = "entry_time"
    entry_price: str = "entry_price"
    direction: str = "direction"
    exit_time: str = "exit_time"
    exit_price: str = "exit_price"
    stop_price: str = "stop_price"
    take_profit_price: str = "take_profit_price"


def add_trade_overlays(
    figure: go.Figure,
    *,
    trades: pd.DataFrame | None = None,
    columns: TradeOverlayColumns | None = None,
) -> None:
    if trades is None or trades.empty:
        return

    column_map = columns or TradeOverlayColumns()
    frame = trades.copy()

    if {column_map.entry_time, column_map.entry_price}.issubset(frame.columns):
        if column_map.direction in frame.columns:
            direction = frame[column_map.direction].astype(str).str.lower()
            long_entries = frame[direction == "long"]
            short_entries = frame[direction == "short"]
        else:
            long_entries = frame.iloc[0:0]
            short_entries = frame.iloc[0:0]

        if not long_entries.empty:
            figure.add_trace(
                go.Scatter(
                    x=pd.to_datetime(long_entries[column_map.entry_time], utc=True),
                    y=long_entries[column_map.entry_price],
                    mode="markers",
                    name="Long entry",
                    marker=dict(color="#2ca02c", size=10, symbol="triangle-up"),
                )
            )
        if not short_entries.empty:
            figure.add_trace(
                go.Scatter(
                    x=pd.to_datetime(short_entries[column_map.entry_time], utc=True),
                    y=short_entries[column_map.entry_price],
                    mode="markers",
                    name="Short entry",
                    marker=dict(color="#d62728", size=10, symbol="triangle-down"),
                )
            )

    if {column_map.exit_time, column_map.exit_price}.issubset(frame.columns):
        figure.add_trace(
            go.Scatter(
                x=pd.to_datetime(frame[column_map.exit_time], utc=True),
                y=frame[column_map.exit_price],
                mode="markers",
                name="Exit",
                marker=dict(color="#111111", size=8, symbol="x"),
            )
        )
