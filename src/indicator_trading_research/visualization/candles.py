"""Helpers for loading, validating, and plotting processed candle parquet data."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import pyarrow.dataset as ds

from .overlays import add_moving_average_traces
from .trades import add_trade_overlays

REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close")
OPTIONAL_COLUMNS = ("pair", "timeframe", "spread", "tick_count", "volume", "source_kind", "source_timeframe")
DEFAULT_MAX_BARS = 5_000


@dataclass
class PlotWarning:
    code: str
    message: str
    details: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def processed_parquet_path(data_root: Path, pair: str, timeframe: str) -> Path:
    return data_root / pair.upper() / timeframe.lower() / f"{pair.lower()}_{timeframe.lower()}.parquet"


def parse_bound(value: str | None, *, is_end: bool) -> pd.Timestamp | None:
    if not value:
        return None
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    if is_end and len(value) <= 10:
        timestamp = timestamp + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    return timestamp


def build_filter(start_date: pd.Timestamp | None, end_date: pd.Timestamp | None) -> ds.Expression | None:
    expression: ds.Expression | None = None
    if start_date is not None:
        expression = ds.field("timestamp") >= start_date.to_pydatetime()
    if end_date is not None:
        end_expression = ds.field("timestamp") <= end_date.to_pydatetime()
        expression = end_expression if expression is None else expression & end_expression
    return expression


def validate_candles(frame: pd.DataFrame) -> list[PlotWarning]:
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing_columns:
        raise ValueError(f"Missing required candle columns: {missing_columns}")

    warnings: list[PlotWarning] = []
    timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    if timestamps.isna().any():
        warnings.append(
            PlotWarning(
                code="invalid_timestamp",
                message="Some timestamps could not be parsed as UTC datetimes.",
                details={"count": int(timestamps.isna().sum())},
            )
        )
    if not timestamps.is_monotonic_increasing:
        warnings.append(
            PlotWarning(
                code="timestamps_not_sorted",
                message="Timestamps are not sorted; plotting will use a sorted view.",
            )
        )
    duplicate_count = int(timestamps.duplicated().sum())
    if duplicate_count:
        warnings.append(
            PlotWarning(
                code="duplicate_timestamps",
                message="Duplicate timestamps were detected in the requested window.",
                details={"count": duplicate_count},
            )
        )
    missing_ohlc = frame[list(REQUIRED_COLUMNS[1:])].isna().any(axis=1)
    if missing_ohlc.any():
        warnings.append(
            PlotWarning(
                code="missing_ohlc",
                message="Some rows contain missing OHLC values.",
                details={"count": int(missing_ohlc.sum())},
            )
        )
    return warnings


def enforce_bar_limit(
    frame: pd.DataFrame,
    *,
    max_bars: int,
    truncate: bool,
) -> tuple[pd.DataFrame, list[PlotWarning]]:
    if max_bars <= 0:
        raise ValueError("--max-bars must be positive")

    if len(frame) <= max_bars:
        return frame, []

    if not truncate:
        raise ValueError(
            f"Requested window contains {len(frame)} bars, which exceeds max-bars={max_bars}. "
            "Use a smaller window or pass --truncate."
        )

    truncated = frame.iloc[-max_bars:].copy()
    warning = PlotWarning(
        code="truncated_bars",
        message="Requested window exceeded max-bars and was truncated to the most recent bars.",
        details={"requested_bars": len(frame), "kept_bars": len(truncated)},
    )
    return truncated, [warning]


def load_processed_candles(
    *,
    data_root: str | Path,
    pair: str,
    timeframe: str,
    start_date: str | None = None,
    end_date: str | None = None,
    max_bars: int = DEFAULT_MAX_BARS,
    truncate: bool = False,
) -> tuple[pd.DataFrame, list[PlotWarning], Path]:
    data_root_path = Path(data_root).expanduser().resolve()
    parquet_path = processed_parquet_path(data_root_path, pair, timeframe)
    if not parquet_path.exists():
        raise FileNotFoundError(f"Processed parquet not found: {parquet_path}")

    dataset = ds.dataset(parquet_path, format="parquet")
    available_columns = list(dataset.schema.names)
    selected_columns = [column for column in (*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS) if column in available_columns]
    table = dataset.to_table(
        columns=selected_columns,
        filter=build_filter(parse_bound(start_date, is_end=False), parse_bound(end_date, is_end=True)),
    )
    frame = table.to_pandas()
    if frame.empty:
        raise ValueError(f"No candle rows found for {pair} {timeframe} in the requested window.")

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    warnings = validate_candles(frame)
    frame, limit_warnings = enforce_bar_limit(frame, max_bars=max_bars, truncate=truncate)
    warnings.extend(limit_warnings)
    return frame, warnings, parquet_path


def create_candlestick_figure(
    frame: pd.DataFrame,
    *,
    pair: str,
    timeframe: str,
    title: str | None = None,
    sma_windows: list[int] | None = None,
    ema_windows: list[int] | None = None,
    trades: pd.DataFrame | None = None,
) -> go.Figure:
    chart_title = title or f"{pair.upper()} {timeframe.lower()} candles"
    figure = go.Figure()
    figure.add_trace(
        go.Candlestick(
            x=frame["timestamp"],
            open=frame["open"],
            high=frame["high"],
            low=frame["low"],
            close=frame["close"],
            name="Candles",
        )
    )
    add_moving_average_traces(figure, frame, sma_windows=sma_windows or [], ema_windows=ema_windows or [])
    add_trade_overlays(figure, trades=trades)
    figure.update_layout(
        title=chart_title,
        template="plotly_white",
        xaxis_title="Timestamp (UTC)",
        yaxis_title="Price",
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    return figure


def save_figure_html(figure: go.Figure, output_path: str | Path) -> Path:
    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(destination, include_plotlyjs="cdn")
    return destination


def save_figure_png(figure: go.Figure, output_path: str | Path) -> Path:
    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.write_image(destination)
    return destination


def format_warnings(warnings: list[PlotWarning]) -> list[dict[str, object]]:
    return [warning.to_dict() for warning in warnings]

