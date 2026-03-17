"""Reusable indicator overlays for candle charts."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

SMA_COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#9467bd"]
EMA_COLORS = ["#d62728", "#17becf", "#8c564b", "#7f7f7f"]


def _as_sorted_windows(values: list[int]) -> list[int]:
    return sorted({int(value) for value in values if int(value) > 0})


def compute_sma(frame: pd.DataFrame, window: int) -> pd.Series:
    return frame["close"].rolling(window=window, min_periods=window).mean()


def compute_ema(frame: pd.DataFrame, window: int) -> pd.Series:
    return frame["close"].ewm(span=window, adjust=False, min_periods=window).mean()


def add_moving_average_traces(
    figure: go.Figure,
    frame: pd.DataFrame,
    *,
    sma_windows: list[int],
    ema_windows: list[int],
) -> None:
    for index, window in enumerate(_as_sorted_windows(sma_windows)):
        figure.add_trace(
            go.Scatter(
                x=frame["timestamp"],
                y=compute_sma(frame, window),
                mode="lines",
                name=f"SMA {window}",
                line=dict(color=SMA_COLORS[index % len(SMA_COLORS)], width=1.5),
            )
        )
    for index, window in enumerate(_as_sorted_windows(ema_windows)):
        figure.add_trace(
            go.Scatter(
                x=frame["timestamp"],
                y=compute_ema(frame, window),
                mode="lines",
                name=f"EMA {window}",
                line=dict(color=EMA_COLORS[index % len(EMA_COLORS)], width=1.5, dash="dot"),
            )
        )

