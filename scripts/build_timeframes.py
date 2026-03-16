#!/usr/bin/env python3
"""Build normalized FX timeframe parquet datasets from source bars or ticks."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds

TARGET_TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
TARGET_PAIRS = ["EURUSD", "USDJPY", "GBPUSD", "EURJPY", "AUDUSD", "USDCAD"]
TIMEFRAME_ORDER = {timeframe: index for index, timeframe in enumerate(TARGET_TIMEFRAMES)}
TIMEFRAME_RULES = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1D",
}
PAIR_PATTERN = re.compile(r"\b([A-Z]{6})\b")


@dataclass
class SourceSelection:
    pair: str
    source_kind: str
    source_timeframe: str
    paths: list[Path]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True, help="Root source data directory.")
    parser.add_argument("--output-root", required=True, help="Output directory for normalized parquet datasets.")
    parser.add_argument("--pairs", nargs="+", default=TARGET_PAIRS, help="Pairs to build.")
    parser.add_argument("--timeframes", nargs="+", default=TARGET_TIMEFRAMES, help="Target timeframes to generate.")
    parser.add_argument("--start-date", help="Optional UTC lower bound, inclusive.")
    parser.add_argument("--end-date", help="Optional UTC upper bound, inclusive for date-only input.")
    parser.add_argument(
        "--source-timeframe",
        help="Force a source granularity such as tick or 15m when needed.",
    )
    return parser.parse_args()


def normalize_pair(text: str) -> str | None:
    upper_text = text.upper()
    for pair in TARGET_PAIRS:
        if pair in upper_text:
            return pair
    match = PAIR_PATTERN.search(upper_text.replace("-", "_").replace("/", "_"))
    return match.group(1) if match else None


def infer_bar_timeframe(path: Path) -> str | None:
    for timeframe in TARGET_TIMEFRAMES:
        if f"/{timeframe}/" in path.as_posix() or f"_{timeframe}_" in path.name.lower():
            return timeframe
    return None


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


def list_tick_paths(input_root: Path, pair: str) -> list[Path]:
    base = input_root / "cleaned_ticks" / pair
    if not base.exists():
        return []
    return sorted(
        path for path in base.rglob("*.parquet")
        if "recent" not in path.name.lower()
    )


def list_bar_paths(input_root: Path, pair: str) -> dict[str, list[Path]]:
    bar_paths: dict[str, list[Path]] = {}
    bars_root = input_root / "bars"
    if not bars_root.exists():
        return bar_paths
    for path in sorted(bars_root.rglob("*.parquet")):
        name = path.name.lower()
        if "_raw" in name or "latest" in name:
            continue
        if normalize_pair(path.as_posix()) != pair:
            continue
        timeframe = infer_bar_timeframe(path)
        if timeframe is None:
            continue
        bar_paths.setdefault(timeframe, []).append(path)
    return bar_paths


def choose_source(input_root: Path, pair: str, forced_source_timeframe: str | None) -> SourceSelection | None:
    tick_paths = list_tick_paths(input_root, pair)
    bar_paths = list_bar_paths(input_root, pair)

    if forced_source_timeframe:
        forced = forced_source_timeframe.lower()
        if forced == "tick":
            return SourceSelection(pair=pair, source_kind="ticks", source_timeframe="tick", paths=tick_paths) if tick_paths else None
        return SourceSelection(pair=pair, source_kind="bars", source_timeframe=forced, paths=bar_paths.get(forced, [])) if bar_paths.get(forced) else None

    if tick_paths:
        return SourceSelection(pair=pair, source_kind="ticks", source_timeframe="tick", paths=tick_paths)

    if not bar_paths:
        return None

    source_timeframe = min(bar_paths, key=lambda timeframe: TIMEFRAME_ORDER[timeframe])
    return SourceSelection(pair=pair, source_kind="bars", source_timeframe=source_timeframe, paths=bar_paths[source_timeframe])


def build_filter(start_date: pd.Timestamp | None, end_date: pd.Timestamp | None) -> ds.Expression | None:
    expression: ds.Expression | None = None
    if start_date is not None:
        expression = ds.field("timestamp") >= start_date.to_pydatetime()
    if end_date is not None:
        end_expression = ds.field("timestamp") <= end_date.to_pydatetime()
        expression = end_expression if expression is None else expression & end_expression
    return expression


def read_tick_source(selection: SourceSelection, start_date: pd.Timestamp | None, end_date: pd.Timestamp | None) -> pd.DataFrame:
    dataset = ds.dataset(selection.paths, format="parquet")
    schema_names = set(dataset.schema.names)
    columns = ["timestamp"]
    for column in ("mid", "spread", "bid", "ask"):
        if column in schema_names:
            columns.append(column)
    table = dataset.to_table(columns=columns, filter=build_filter(start_date, end_date))
    frame = table.to_pandas()
    if frame.empty:
        return frame
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    if "mid" not in frame.columns:
        if {"bid", "ask"}.issubset(frame.columns):
            frame["mid"] = (frame["bid"] + frame["ask"]) / 2.0
        else:
            raise ValueError(f"{selection.pair} tick source does not contain mid or bid/ask columns")
    if "spread" not in frame.columns and {"bid", "ask"}.issubset(frame.columns):
        frame["spread"] = frame["ask"] - frame["bid"]
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    return frame


def read_bar_source(selection: SourceSelection, start_date: pd.Timestamp | None, end_date: pd.Timestamp | None) -> pd.DataFrame:
    dataset = ds.dataset(selection.paths, format="parquet")
    schema_names = set(dataset.schema.names)
    required_columns = ["timestamp"]
    preferred_columns = [
        "open",
        "high",
        "low",
        "close",
        "mid_open",
        "mid_high",
        "mid_low",
        "mid_close",
        "spread",
        "spread_open",
        "spread_high",
        "spread_low",
        "spread_close",
        "volume",
        "tick_volume",
    ]
    required_columns.extend(column for column in preferred_columns if column in schema_names)
    table = dataset.to_table(columns=required_columns, filter=build_filter(start_date, end_date))
    frame = table.to_pandas()
    if frame.empty:
        return frame
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    return frame


def standardize_bar_source(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    standardized = pd.DataFrame({"timestamp": frame["timestamp"]})
    if {"mid_open", "mid_high", "mid_low", "mid_close"}.issubset(frame.columns):
        standardized["open"] = frame["mid_open"]
        standardized["high"] = frame["mid_high"]
        standardized["low"] = frame["mid_low"]
        standardized["close"] = frame["mid_close"]
    elif {"open", "high", "low", "close"}.issubset(frame.columns):
        standardized["open"] = frame["open"]
        standardized["high"] = frame["high"]
        standardized["low"] = frame["low"]
        standardized["close"] = frame["close"]
    else:
        raise ValueError("Bar source is missing OHLC columns")

    if "spread" in frame.columns:
        standardized["spread"] = frame["spread"]
    else:
        spread_columns = [column for column in ("spread_open", "spread_high", "spread_low", "spread_close") if column in frame.columns]
        if spread_columns:
            standardized["spread"] = frame[spread_columns].mean(axis=1)

    if "volume" in frame.columns:
        standardized["volume"] = frame["volume"]
    elif "tick_volume" in frame.columns:
        standardized["volume"] = frame["tick_volume"]

    return standardized


def resample_ticks(frame: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    indexed = frame.set_index("timestamp").sort_index()
    resampler = indexed["mid"].resample(TIMEFRAME_RULES[timeframe], label="left", closed="left")
    ohlc = resampler.ohlc().dropna()
    result = ohlc.rename(columns={"open": "open", "high": "high", "low": "low", "close": "close"})
    if "spread" in indexed.columns:
        result["spread"] = indexed["spread"].resample(TIMEFRAME_RULES[timeframe], label="left", closed="left").mean().reindex(result.index)
    result["tick_count"] = indexed["mid"].resample(TIMEFRAME_RULES[timeframe], label="left", closed="left").size().reindex(result.index).fillna(0).astype("int64")
    return result.reset_index()


def resample_bars(frame: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    indexed = frame.set_index("timestamp").sort_index()
    aggregation = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    }
    if "spread" in indexed.columns:
        aggregation["spread"] = "mean"
    if "volume" in indexed.columns:
        aggregation["volume"] = "sum"
    result = indexed.resample(TIMEFRAME_RULES[timeframe], label="left", closed="left").agg(aggregation).dropna(subset=["open", "high", "low", "close"])
    return result.reset_index()


def validate_output(frame: pd.DataFrame, pair: str, timeframe: str) -> None:
    timestamps = pd.to_datetime(frame["timestamp"], utc=True)
    if not timestamps.is_monotonic_increasing:
        raise ValueError(f"{pair} {timeframe} output timestamps are not sorted")
    if timestamps.duplicated().any():
        raise ValueError(f"{pair} {timeframe} output contains duplicate timestamps")


def target_is_buildable(source_timeframe: str, target_timeframe: str) -> bool:
    if source_timeframe == "tick":
        return True
    return TIMEFRAME_ORDER[target_timeframe] >= TIMEFRAME_ORDER[source_timeframe]


def write_output(
    frame: pd.DataFrame,
    output_root: Path,
    pair: str,
    timeframe: str,
    source_kind: str,
    source_timeframe: str,
) -> tuple[Path, int]:
    frame = frame.copy()
    frame["pair"] = pair
    frame["timeframe"] = timeframe
    frame["source_kind"] = source_kind
    frame["source_timeframe"] = source_timeframe
    ordered_columns = [
        "timestamp",
        "pair",
        "timeframe",
        "open",
        "high",
        "low",
        "close",
    ]
    for optional_column in ("spread", "tick_count", "volume", "source_kind", "source_timeframe"):
        if optional_column in frame.columns:
            ordered_columns.append(optional_column)
    frame = frame[ordered_columns]
    pair_dir = output_root / pair / timeframe
    pair_dir.mkdir(parents=True, exist_ok=True)
    output_path = pair_dir / f"{pair.lower()}_{timeframe}.parquet"
    frame.to_parquet(output_path, index=False)
    return output_path, len(frame)


def main() -> None:
    args = parse_args()
    input_root = Path(args.input_root).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    pairs = [pair.upper() for pair in args.pairs]
    timeframes = [timeframe.lower() for timeframe in args.timeframes]
    invalid = [timeframe for timeframe in timeframes if timeframe not in TIMEFRAME_RULES]
    if invalid:
        raise ValueError(f"Unsupported target timeframes: {invalid}")

    start_date = parse_bound(args.start_date, is_end=False)
    end_date = parse_bound(args.end_date, is_end=True)
    results: list[str] = []

    for pair in pairs:
        selection = choose_source(input_root, pair, args.source_timeframe)
        if selection is None or not selection.paths:
            print(f"{pair}: no usable parquet source found")
            continue

        if selection.source_kind == "ticks":
            source_frame = read_tick_source(selection, start_date, end_date)
        else:
            source_frame = standardize_bar_source(read_bar_source(selection, start_date, end_date))

        if source_frame.empty:
            print(f"{pair}: source selection {selection.source_kind}/{selection.source_timeframe} returned no rows for the requested range")
            continue

        for timeframe in timeframes:
            if not target_is_buildable(selection.source_timeframe, timeframe):
                print(f"{pair}: skipping {timeframe}, source timeframe is {selection.source_timeframe}")
                continue

            if selection.source_kind == "ticks":
                output_frame = resample_ticks(source_frame, timeframe)
            elif timeframe == selection.source_timeframe:
                output_frame = source_frame.copy()
            else:
                output_frame = resample_bars(source_frame, timeframe)

            if output_frame.empty:
                print(f"{pair}: no rows generated for {timeframe}")
                continue

            validate_output(output_frame, pair, timeframe)
            output_path, row_count = write_output(
                output_frame,
                output_root,
                pair,
                timeframe,
                selection.source_kind,
                selection.source_timeframe,
            )
            results.append(f"{pair} {timeframe}: {row_count} rows -> {output_path}")

    if results:
        print("Build summary")
        for line in results:
            print(line)
    else:
        print("No outputs were generated")


if __name__ == "__main__":
    main()
