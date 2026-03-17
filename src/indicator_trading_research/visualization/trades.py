"""Standardized trade overlay loading, validation, and plotting helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

REQUIRED_TRADE_COLUMNS = ("trade_id", "side", "entry_time", "entry_price")


@dataclass
class TradeWarning:
    code: str
    message: str
    details: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class TradeOverlayColumns:
    trade_id: str = "trade_id"
    pair: str = "pair"
    timeframe: str = "timeframe"
    side: str = "side"
    entry_time: str = "entry_time"
    entry_price: str = "entry_price"
    exit_time: str = "exit_time"
    exit_price: str = "exit_price"
    stop_loss: str = "stop_loss"
    take_profit: str = "take_profit"
    size: str = "size"
    pnl: str = "pnl"
    outcome: str = "outcome"
    strategy_name: str = "strategy_name"
    notes: str = "notes"


@dataclass
class TradeOverlayOptions:
    show_entries: bool = True
    show_exits: bool = True
    show_stop_loss: bool = False
    show_take_profit: bool = False
    show_trade_lines: bool = False


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


def _read_trade_file(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"Unsupported trades file format: {path.suffix}")


def _warn(
    warnings: list[TradeWarning],
    *,
    code: str,
    message: str,
    count: int | None = None,
) -> None:
    details = {"count": count} if count is not None else {}
    warnings.append(TradeWarning(code=code, message=message, details=details))


def load_trade_overlays(
    *,
    trades_file: str | Path,
    pair: str,
    timeframe: str,
    start_date: str | None = None,
    end_date: str | None = None,
    columns: TradeOverlayColumns | None = None,
) -> tuple[pd.DataFrame, list[TradeWarning], Path]:
    column_map = columns or TradeOverlayColumns()
    trade_path = Path(trades_file).expanduser().resolve()
    if not trade_path.exists():
        raise FileNotFoundError(f"Trades file not found: {trade_path}")

    frame = _read_trade_file(trade_path)
    missing_columns = [column for column in REQUIRED_TRADE_COLUMNS if column not in frame.columns]
    if missing_columns:
        raise ValueError(f"Missing required trade columns: {missing_columns}")

    warnings: list[TradeWarning] = []
    result = frame.copy()

    missing_trade_id = result[column_map.trade_id].isna() | (result[column_map.trade_id].astype(str).str.strip() == "")
    if missing_trade_id.any():
        result.loc[missing_trade_id, column_map.trade_id] = [
            f"trade_{index}" for index in result.index[missing_trade_id]
        ]
        _warn(
            warnings,
            code="missing_trade_id",
            message="Some trades were missing trade_id and were assigned synthetic identifiers.",
            count=int(missing_trade_id.sum()),
        )

    result[column_map.entry_time] = pd.to_datetime(result[column_map.entry_time], utc=True, errors="coerce")
    invalid_entry_time = result[column_map.entry_time].isna()
    if invalid_entry_time.any():
        _warn(
            warnings,
            code="invalid_entry_time",
            message="Trades with invalid entry_time were skipped.",
            count=int(invalid_entry_time.sum()),
        )
        result = result.loc[~invalid_entry_time].copy()

    result[column_map.entry_price] = pd.to_numeric(result[column_map.entry_price], errors="coerce")
    invalid_entry_price = result[column_map.entry_price].isna()
    if invalid_entry_price.any():
        _warn(
            warnings,
            code="invalid_entry_price",
            message="Trades with invalid entry_price were skipped.",
            count=int(invalid_entry_price.sum()),
        )
        result = result.loc[~invalid_entry_price].copy()

    result[column_map.side] = result[column_map.side].astype(str).str.lower()
    invalid_side = ~result[column_map.side].isin({"long", "short"})
    if invalid_side.any():
        _warn(
            warnings,
            code="invalid_side",
            message="Trades with side outside {long, short} were skipped.",
            count=int(invalid_side.sum()),
        )
        result = result.loc[~invalid_side].copy()

    if column_map.exit_time in result.columns:
        result[column_map.exit_time] = pd.to_datetime(result[column_map.exit_time], utc=True, errors="coerce")
    else:
        result[column_map.exit_time] = pd.NaT
        _warn(
            warnings,
            code="missing_exit_time_column",
            message="exit_time column is missing; trades will be plotted as entry-only overlays.",
        )

    if column_map.exit_price in result.columns:
        result[column_map.exit_price] = pd.to_numeric(result[column_map.exit_price], errors="coerce")
    else:
        result[column_map.exit_price] = pd.NA
        _warn(
            warnings,
            code="missing_exit_price_column",
            message="exit_price column is missing; exit markers will be omitted.",
        )

    missing_exit_price = result[column_map.exit_time].notna() & result[column_map.exit_price].isna()
    if missing_exit_price.any():
        result.loc[missing_exit_price, [column_map.exit_time, column_map.exit_price]] = [pd.NaT, pd.NA]
        _warn(
            warnings,
            code="missing_exit_price",
            message="Trades with exit_time but no exit_price were downgraded to entry-only overlays.",
            count=int(missing_exit_price.sum()),
        )

    invalid_duration = result[column_map.exit_time].notna() & (result[column_map.exit_time] < result[column_map.entry_time])
    if invalid_duration.any():
        _warn(
            warnings,
            code="invalid_trade_duration",
            message="Trades with exit_time earlier than entry_time were skipped.",
            count=int(invalid_duration.sum()),
        )
        result = result.loc[~invalid_duration].copy()

    for optional_numeric in (column_map.stop_loss, column_map.take_profit, column_map.size, column_map.pnl):
        if optional_numeric in result.columns:
            parsed = pd.to_numeric(result[optional_numeric], errors="coerce")
            invalid_numeric = result[optional_numeric].notna() & parsed.isna()
            if invalid_numeric.any():
                _warn(
                    warnings,
                    code=f"invalid_{optional_numeric}",
                    message=f"Some {optional_numeric} values were invalid and will be omitted.",
                    count=int(invalid_numeric.sum()),
                )
            result[optional_numeric] = parsed
        else:
            result[optional_numeric] = pd.NA

    chart_pair = pair.upper()
    chart_timeframe = timeframe.lower()
    if column_map.pair in result.columns:
        pair_mismatch = result[column_map.pair].astype(str).str.upper() != chart_pair
        if pair_mismatch.any():
            _warn(
                warnings,
                code="pair_mismatch",
                message="Trades with a non-matching pair were skipped.",
                count=int(pair_mismatch.sum()),
            )
            result = result.loc[~pair_mismatch].copy()
    else:
        result[column_map.pair] = chart_pair
        _warn(
            warnings,
            code="missing_pair_column",
            message="pair column is missing; the requested chart pair is assumed for all trades.",
        )

    if column_map.timeframe in result.columns:
        timeframe_mismatch = result[column_map.timeframe].astype(str).str.lower() != chart_timeframe
        if timeframe_mismatch.any():
            _warn(
                warnings,
                code="timeframe_mismatch",
                message="Trades with a non-matching timeframe were skipped.",
                count=int(timeframe_mismatch.sum()),
            )
            result = result.loc[~timeframe_mismatch].copy()
    else:
        result[column_map.timeframe] = chart_timeframe
        _warn(
            warnings,
            code="missing_timeframe_column",
            message="timeframe column is missing; the requested chart timeframe is assumed for all trades.",
        )

    chart_start = parse_bound(start_date, is_end=False)
    chart_end = parse_bound(end_date, is_end=True)
    if chart_start is not None or chart_end is not None:
        in_window = pd.Series(True, index=result.index)
        if chart_end is not None:
            in_window &= result[column_map.entry_time] <= chart_end
        if chart_start is not None:
            exit_or_entry = result[column_map.exit_time].fillna(result[column_map.entry_time])
            in_window &= exit_or_entry >= chart_start
        skipped_outside_window = (~in_window).sum()
        if skipped_outside_window:
            _warn(
                warnings,
                code="trade_outside_chart_window",
                message="Trades outside the requested chart window were skipped.",
                count=int(skipped_outside_window),
            )
            result = result.loc[in_window].copy()

    open_trades = result[column_map.exit_time].isna()
    if open_trades.any():
        _warn(
            warnings,
            code="open_trade",
            message="Some trades have no exit and will be plotted as entry-only overlays.",
            count=int(open_trades.sum()),
        )

    missing_stop = result[column_map.stop_loss].isna().sum()
    if missing_stop:
        _warn(
            warnings,
            code="missing_stop_loss",
            message="Some trades are missing stop_loss; stop-loss lines will be omitted for those trades.",
            count=int(missing_stop),
        )

    missing_take_profit = result[column_map.take_profit].isna().sum()
    if missing_take_profit:
        _warn(
            warnings,
            code="missing_take_profit",
            message="Some trades are missing take_profit; take-profit lines will be omitted for those trades.",
            count=int(missing_take_profit),
        )

    result = result.sort_values([column_map.entry_time, column_map.trade_id]).reset_index(drop=True)
    return result, warnings, trade_path


def add_trade_overlays(
    figure: go.Figure,
    *,
    trades: pd.DataFrame | None = None,
    columns: TradeOverlayColumns | None = None,
    options: TradeOverlayOptions | None = None,
    chart_end: pd.Timestamp | None = None,
) -> None:
    if trades is None or trades.empty:
        return

    column_map = columns or TradeOverlayColumns()
    overlay_options = options or TradeOverlayOptions()
    frame = trades.copy()
    frame[column_map.entry_time] = pd.to_datetime(frame[column_map.entry_time], utc=True)
    frame[column_map.exit_time] = pd.to_datetime(frame[column_map.exit_time], utc=True, errors="coerce")

    if overlay_options.show_entries:
        long_entries = frame[frame[column_map.side] == "long"]
        short_entries = frame[frame[column_map.side] == "short"]
        if not long_entries.empty:
            figure.add_trace(
                go.Scatter(
                    x=long_entries[column_map.entry_time],
                    y=long_entries[column_map.entry_price],
                    mode="markers",
                    name="Long entry",
                    marker=dict(color="#2ca02c", size=10, symbol="triangle-up"),
                    text=long_entries[column_map.trade_id].astype(str),
                    hovertemplate="Long entry<br>%{text}<br>%{x}<br>%{y}<extra></extra>",
                )
            )
        if not short_entries.empty:
            figure.add_trace(
                go.Scatter(
                    x=short_entries[column_map.entry_time],
                    y=short_entries[column_map.entry_price],
                    mode="markers",
                    name="Short entry",
                    marker=dict(color="#d62728", size=10, symbol="triangle-down"),
                    text=short_entries[column_map.trade_id].astype(str),
                    hovertemplate="Short entry<br>%{text}<br>%{x}<br>%{y}<extra></extra>",
                )
            )

    completed = frame[frame[column_map.exit_time].notna() & frame[column_map.exit_price].notna()]
    if overlay_options.show_exits and not completed.empty:
        figure.add_trace(
            go.Scatter(
                x=completed[column_map.exit_time],
                y=completed[column_map.exit_price],
                mode="markers",
                name="Exit",
                marker=dict(color="#111111", size=8, symbol="x"),
                text=completed[column_map.trade_id].astype(str),
                hovertemplate="Exit<br>%{text}<br>%{x}<br>%{y}<extra></extra>",
            )
        )

    for _, trade in frame.iterrows():
        trade_color = "#2ca02c" if trade[column_map.side] == "long" else "#d62728"
        segment_end = trade[column_map.exit_time] if pd.notna(trade[column_map.exit_time]) else chart_end
        if segment_end is None or pd.isna(segment_end):
            segment_end = trade[column_map.entry_time]

        if overlay_options.show_trade_lines and pd.notna(trade[column_map.exit_time]) and pd.notna(trade[column_map.exit_price]):
            figure.add_shape(
                type="line",
                x0=trade[column_map.entry_time],
                y0=trade[column_map.entry_price],
                x1=trade[column_map.exit_time],
                y1=trade[column_map.exit_price],
                line=dict(color=trade_color, width=1.5, dash="dash"),
            )

        if overlay_options.show_stop_loss and pd.notna(trade[column_map.stop_loss]):
            figure.add_shape(
                type="line",
                x0=trade[column_map.entry_time],
                y0=trade[column_map.stop_loss],
                x1=segment_end,
                y1=trade[column_map.stop_loss],
                line=dict(color="#d62728", width=1, dash="dot"),
            )

        if overlay_options.show_take_profit and pd.notna(trade[column_map.take_profit]):
            figure.add_shape(
                type="line",
                x0=trade[column_map.entry_time],
                y0=trade[column_map.take_profit],
                x1=segment_end,
                y1=trade[column_map.take_profit],
                line=dict(color="#2ca02c", width=1, dash="dot"),
            )
