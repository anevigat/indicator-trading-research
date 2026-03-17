#!/usr/bin/env python3
"""Build normalized FX timeframe parquet datasets with bounded memory usage."""

from __future__ import annotations

import argparse
import re
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

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
BASE_COLUMNS = ["timestamp", "pair", "timeframe", "open", "high", "low", "close"]
TICK_CANDIDATE_COLUMNS = ("mid", "spread", "bid", "ask")
BAR_CANDIDATE_COLUMNS = (
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
)


@dataclass
class BuildConfig:
    input_root: Path
    output_root: Path
    tmp_dir: Path
    timeframes: list[str]
    start_date: pd.Timestamp | None
    end_date: pd.Timestamp | None
    batch_size: int
    skip_existing: bool
    overwrite: bool
    validate_only: bool
    sample_validate: bool
    source_timeframe: str | None
    pair_workers: int


@dataclass
class SourceSelection:
    pair: str
    source_kind: str
    source_timeframe: str
    paths: list[Path]


@dataclass
class BuildResult:
    pair: str
    built: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    validated: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


@dataclass
class OutputTarget:
    pair: str
    timeframe: str
    source_kind: str
    source_timeframe: str
    final_path: Path
    temp_path: Path
    builder_mode: str
    batch_resampler: Callable[[pd.DataFrame], pd.DataFrame]
    writer: pq.ParquetWriter | None = None
    pending: pd.DataFrame = field(default_factory=pd.DataFrame)
    rows_written: int = 0
    last_timestamp: pd.Timestamp | None = None
    skipped: bool = False

    @property
    def rule(self) -> str:
        return TIMEFRAME_RULES[self.timeframe]

    def _write_frame(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        frame = finalize_output_frame(frame, self.pair, self.timeframe, self.source_kind, self.source_timeframe)
        validate_output_frame(frame, self.pair, self.timeframe, previous_timestamp=self.last_timestamp)
        table = pa.Table.from_pandas(frame, preserve_index=False)
        if self.writer is None:
            self.temp_path.parent.mkdir(parents=True, exist_ok=True)
            self.writer = pq.ParquetWriter(self.temp_path, table.schema, compression="snappy")
        self.writer.write_table(table)
        self.rows_written += len(frame)
        self.last_timestamp = pd.Timestamp(frame["timestamp"].iloc[-1])

    def consume(self, batch: pd.DataFrame, *, finalize_all: bool = False) -> None:
        if self.skipped or batch.empty:
            return
        if self.builder_mode == "identity":
            self._write_frame(batch)
            return

        combined = pd.concat([self.pending, batch], ignore_index=True) if not self.pending.empty else batch
        if combined.empty:
            return
        combined = combined.sort_values("timestamp").reset_index(drop=True)
        if finalize_all:
            finalized = self.batch_resampler(combined)
            self.pending = empty_like(combined)
            self._write_frame(finalized)
            return

        cutoff = floor_timestamp(pd.Timestamp(combined["timestamp"].iloc[-1]), self.rule)
        finalizable = combined[combined["timestamp"] < cutoff].copy()
        self.pending = combined[combined["timestamp"] >= cutoff].copy()
        if finalizable.empty:
            return
        self._write_frame(self.batch_resampler(finalizable))

    def finalize(self) -> None:
        if self.skipped:
            return
        if not self.pending.empty:
            self._write_frame(self.batch_resampler(self.pending))
            self.pending = empty_like(self.pending)
        if self.writer is not None:
            self.writer.close()
            self.writer = None
            self.final_path.parent.mkdir(parents=True, exist_ok=True)
            self.temp_path.replace(self.final_path)

    def abort(self) -> None:
        if self.writer is not None:
            self.writer.close()
            self.writer = None
        if self.temp_path.exists():
            self.temp_path.unlink()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True, help="Root source data directory.")
    parser.add_argument("--output-root", required=True, help="Output directory for normalized parquet datasets.")
    parser.add_argument("--pairs", nargs="+", default=TARGET_PAIRS, help="Pairs to build or validate.")
    parser.add_argument("--timeframes", nargs="+", default=TARGET_TIMEFRAMES, help="Target timeframes to build or validate.")
    parser.add_argument("--start-date", help="Optional UTC lower bound, inclusive.")
    parser.add_argument("--end-date", help="Optional UTC upper bound, inclusive for date-only input.")
    parser.add_argument("--batch-size", type=int, default=250_000, help="Scanner batch size in source rows.")
    parser.add_argument("--pair-workers", type=int, default=1, help="How many pairs to process concurrently. Use 1 on laptops.")
    parser.add_argument("--tmp-dir", help="Temporary directory for in-progress parquet files.")
    parser.add_argument("--source-timeframe", help="Force a source granularity such as tick or 15m.")
    parser.add_argument("--validate-only", action="store_true", help="Validate requested outputs without rebuilding.")
    parser.add_argument("--sample-validate", action="store_true", help="Use a lightweight sampled validator instead of a full scan.")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--skip-existing", action="store_true", help="Skip outputs that already exist and validate cleanly.")
    mode_group.add_argument("--overwrite", action="store_true", help="Rebuild requested outputs even if they already exist.")
    return parser.parse_args()


def log(message: str) -> None:
    print(message, flush=True)


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


def floor_timestamp(timestamp: pd.Timestamp, rule: str) -> pd.Timestamp:
    return timestamp.floor(rule)


def normalize_pair(text: str) -> str | None:
    upper_text = text.upper()
    for pair in TARGET_PAIRS:
        if pair in upper_text:
            return pair
    return None


def infer_bar_timeframe(path: Path) -> str | None:
    path_text = path.as_posix().lower()
    for timeframe in TARGET_TIMEFRAMES:
        if f"/{timeframe}/" in path_text or f"_{timeframe}_" in path.name.lower():
            return timeframe
    return None


def canonicalize_bar_paths(paths: list[Path]) -> list[Path]:
    granular = []
    for path in paths:
        stem = path.stem.lower()
        if any(stem.endswith(f"_{year}") for year in range(2018, 2030)) or stem.endswith("_2025_now"):
            granular.append(path)
    if granular:
        return sorted(path for path in granular if "recent" not in path.stem.lower())
    return sorted(path for path in paths if "recent" not in path.stem.lower())


def infer_path_year_window(path: Path) -> tuple[int, int] | None:
    text = path.as_posix()
    if "2025_now" in text:
        return 2025, datetime.now(tz=UTC).year + 1
    years = sorted({int(year) for year in re.findall(r"(20\d{2})", text)})
    if not years:
        return None
    return years[0], years[-1]


def filter_paths_for_window(paths: list[Path], start_date: pd.Timestamp | None, end_date: pd.Timestamp | None) -> list[Path]:
    if start_date is None and end_date is None:
        return paths
    start_year = start_date.year if start_date is not None else 2010
    end_year = end_date.year if end_date is not None else datetime.now(tz=UTC).year + 1
    filtered = []
    for path in paths:
        window = infer_path_year_window(path)
        if window is None:
            filtered.append(path)
            continue
        window_start, window_end = window
        if window_end < start_year or window_start > end_year:
            continue
        filtered.append(path)
    return filtered


def list_tick_paths(input_root: Path, pair: str) -> list[Path]:
    base = input_root / "cleaned_ticks" / pair
    if not base.exists():
        return []
    return sorted(path for path in base.rglob("*.parquet") if "recent" not in path.name.lower())


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
    return {timeframe: canonicalize_bar_paths(paths) for timeframe, paths in bar_paths.items()}


def choose_source(input_root: Path, pair: str, forced_source_timeframe: str | None) -> SourceSelection | None:
    tick_paths = list_tick_paths(input_root, pair)
    bar_paths = list_bar_paths(input_root, pair)

    if forced_source_timeframe:
        forced = forced_source_timeframe.lower()
        if forced == "tick":
            return SourceSelection(pair=pair, source_kind="ticks", source_timeframe="tick", paths=tick_paths) if tick_paths else None
        if bar_paths.get(forced):
            return SourceSelection(pair=pair, source_kind="bars", source_timeframe=forced, paths=bar_paths[forced])
        return None

    if tick_paths:
        return SourceSelection(pair=pair, source_kind="ticks", source_timeframe="tick", paths=tick_paths)
    if not bar_paths:
        return None

    source_timeframe = min(bar_paths, key=lambda timeframe: TIMEFRAME_ORDER[timeframe])
    return SourceSelection(pair=pair, source_kind="bars", source_timeframe=source_timeframe, paths=bar_paths[source_timeframe])


def constrain_selection_to_window(selection: SourceSelection, config: BuildConfig) -> SourceSelection:
    constrained_paths = filter_paths_for_window(selection.paths, config.start_date, config.end_date)
    return SourceSelection(
        pair=selection.pair,
        source_kind=selection.source_kind,
        source_timeframe=selection.source_timeframe,
        paths=constrained_paths,
    )


def build_filter(start_date: pd.Timestamp | None, end_date: pd.Timestamp | None) -> ds.Expression | None:
    expression: ds.Expression | None = None
    if start_date is not None:
        expression = ds.field("timestamp") >= start_date.to_pydatetime()
    if end_date is not None:
        end_expression = ds.field("timestamp") <= end_date.to_pydatetime()
        expression = end_expression if expression is None else expression & end_expression
    return expression


def empty_like(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.iloc[0:0].copy()


def resample_ticks(frame: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    indexed = frame.set_index("timestamp").sort_index()
    result = indexed["mid"].resample(TIMEFRAME_RULES[timeframe], label="left", closed="left").ohlc().dropna()
    if "spread" in indexed.columns:
        result["spread"] = indexed["spread"].resample(TIMEFRAME_RULES[timeframe], label="left", closed="left").mean().reindex(result.index)
    result["tick_count"] = (
        indexed["mid"]
        .resample(TIMEFRAME_RULES[timeframe], label="left", closed="left")
        .size()
        .reindex(result.index)
        .fillna(0)
        .astype("int64")
    )
    return result.reset_index()


def resample_bars(frame: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    indexed = frame.set_index("timestamp").sort_index()
    aggregation = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "spread" in indexed.columns:
        aggregation["spread"] = "mean"
    if "volume" in indexed.columns:
        aggregation["volume"] = "sum"
    result = indexed.resample(TIMEFRAME_RULES[timeframe], label="left", closed="left").agg(aggregation)
    result = result.dropna(subset=["open", "high", "low", "close"])
    return result.reset_index()


def finalize_output_frame(
    frame: pd.DataFrame,
    pair: str,
    timeframe: str,
    source_kind: str,
    source_timeframe: str,
) -> pd.DataFrame:
    frame = frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["pair"] = pair
    frame["timeframe"] = timeframe
    frame["source_kind"] = source_kind
    frame["source_timeframe"] = source_timeframe
    ordered_columns = BASE_COLUMNS.copy()
    for optional_column in ("spread", "tick_count", "volume", "source_kind", "source_timeframe"):
        if optional_column in frame.columns:
            ordered_columns.append(optional_column)
    return frame[ordered_columns]


def validate_output_frame(
    frame: pd.DataFrame,
    pair: str,
    timeframe: str,
    *,
    previous_timestamp: pd.Timestamp | None = None,
) -> None:
    timestamps = pd.to_datetime(frame["timestamp"], utc=True)
    if not timestamps.is_monotonic_increasing:
        raise ValueError(f"{pair} {timeframe} output timestamps are not sorted")
    if timestamps.duplicated().any():
        raise ValueError(f"{pair} {timeframe} output contains duplicate timestamps")
    if previous_timestamp is not None and not timestamps.empty and timestamps.iloc[0] <= previous_timestamp:
        raise ValueError(f"{pair} {timeframe} output is not strictly increasing across write batches")
    if frame[["open", "high", "low", "close"]].isna().all(axis=1).any():
        raise ValueError(f"{pair} {timeframe} output contains all-null OHLC rows")


def expected_min_spacing(timeframe: str) -> pd.Timedelta:
    return pd.Timedelta(TIMEFRAME_RULES[timeframe])


def validate_output_file(path: Path, timeframe: str, *, sample_only: bool) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing output file"

    parquet_file = pq.ParquetFile(path)
    names = set(parquet_file.schema_arrow.names)
    missing_columns = [column for column in BASE_COLUMNS if column not in names]
    if missing_columns:
        return False, f"missing required columns: {missing_columns}"

    previous_timestamp: pd.Timestamp | None = None
    min_spacing = expected_min_spacing(timeframe)
    batches = parquet_file.iter_batches(batch_size=200_000)
    total_rows = 0

    if sample_only:
        sampled_batches = []
        row_group_indexes = list(range(min(2, parquet_file.num_row_groups)))
        if parquet_file.num_row_groups > 2:
            row_group_indexes.append(parquet_file.num_row_groups - 1)
        for row_group_index in row_group_indexes:
            row_group = parquet_file.read_row_group(row_group_index)
            sampled_batches.extend(row_group.to_batches(max_chunksize=50_000))
        batch_iterable = sampled_batches
    else:
        batch_iterable = batches

    for batch in batch_iterable:
        frame = batch.to_pandas()
        total_rows += len(frame)
        timestamps = pd.to_datetime(frame["timestamp"], utc=True)
        if not timestamps.is_monotonic_increasing:
            return False, "timestamps are not monotonic"
        if timestamps.duplicated().any():
            return False, "duplicate timestamps detected"
        if previous_timestamp is not None and not timestamps.empty and timestamps.iloc[0] <= previous_timestamp:
            return False, "timestamps are not strictly increasing across row groups"
        if frame[["open", "high", "low", "close"]].isna().all(axis=1).any():
            return False, "all-null OHLC row detected"
        if not timestamps.empty:
            aligned = timestamps == timestamps.dt.floor(TIMEFRAME_RULES[timeframe])
            if not aligned.all():
                return False, "timestamps are not aligned to timeframe boundaries"
            deltas = timestamps.diff().dropna()
            if not deltas.empty and (deltas < min_spacing).any():
                return False, "timestamp spacing is smaller than the target timeframe"
            previous_timestamp = timestamps.iloc[-1]

    if total_rows == 0:
        return False, "output file is empty"
    return True, f"validated {total_rows} rows"


def prepare_existing_output(path: Path, timeframe: str, config: BuildConfig) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    if config.overwrite:
        path.unlink()
        return False, "removed existing output"
    if config.skip_existing:
        valid, message = validate_output_file(path, timeframe, sample_only=config.sample_validate)
        if valid:
            return True, message
        log(f"{path}: existing file failed validation under --skip-existing, rebuilding ({message})")
        return False, message
    return False, "rebuilding existing output"


def standardize_tick_batch(frame: pd.DataFrame, pair: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    if "mid" not in frame.columns:
        if {"bid", "ask"}.issubset(frame.columns):
            frame["mid"] = (frame["bid"] + frame["ask"]) / 2.0
        else:
            raise ValueError(f"{pair}: tick batch is missing mid and bid/ask columns")
    if "spread" not in frame.columns and {"bid", "ask"}.issubset(frame.columns):
        frame["spread"] = frame["ask"] - frame["bid"]
    keep_columns = ["timestamp", "mid"]
    if "spread" in frame.columns:
        keep_columns.append("spread")
    return frame[keep_columns].sort_values("timestamp").reset_index(drop=True)


def standardize_bar_batch(frame: pd.DataFrame, pair: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
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
        raise ValueError(f"{pair}: bar batch is missing OHLC columns")
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
    return standardized.sort_values("timestamp").reset_index(drop=True)


def scanner_columns(selection: SourceSelection, schema_names: set[str]) -> list[str]:
    columns = ["timestamp"]
    if selection.source_kind == "ticks":
        columns.extend(column for column in TICK_CANDIDATE_COLUMNS if column in schema_names)
    else:
        columns.extend(column for column in BAR_CANDIDATE_COLUMNS if column in schema_names)
    return columns


def make_targets(pair: str, selection: SourceSelection, config: BuildConfig) -> tuple[list[OutputTarget], list[str]]:
    requested = sorted(set(config.timeframes), key=lambda timeframe: TIMEFRAME_ORDER[timeframe])
    targets: list[OutputTarget] = []
    skipped_messages: list[str] = []
    for timeframe in requested:
        if selection.source_timeframe != "tick" and TIMEFRAME_ORDER[timeframe] < TIMEFRAME_ORDER[selection.source_timeframe]:
            skipped_messages.append(f"{pair} {timeframe}: skipped, source timeframe is {selection.source_timeframe}")
            continue

        final_path = config.output_root / pair / timeframe / f"{pair.lower()}_{timeframe}.parquet"
        should_skip, message = prepare_existing_output(final_path, timeframe, config)
        temp_path = config.tmp_dir / pair / timeframe / f"{pair.lower()}_{timeframe}.parquet.part"
        if config.overwrite and temp_path.exists():
            temp_path.unlink()

        if should_skip:
            target = OutputTarget(
                pair=pair,
                timeframe=timeframe,
                source_kind=selection.source_kind,
                source_timeframe=selection.source_timeframe,
                final_path=final_path,
                temp_path=temp_path,
                builder_mode="identity",
                batch_resampler=lambda frame: frame,
                skipped=True,
            )
            targets.append(target)
            skipped_messages.append(f"{pair} {timeframe}: skipped existing output ({message})")
            continue

        if selection.source_kind == "bars" and timeframe == selection.source_timeframe:
            mode = "identity"
            resampler = lambda frame: frame
        elif selection.source_kind == "ticks":
            mode = "resample"
            resampler = lambda frame, timeframe=timeframe: resample_ticks(frame, timeframe)
        else:
            mode = "resample"
            resampler = lambda frame, timeframe=timeframe: resample_bars(frame, timeframe)

        targets.append(
            OutputTarget(
                pair=pair,
                timeframe=timeframe,
                source_kind=selection.source_kind,
                source_timeframe=selection.source_timeframe,
                final_path=final_path,
                temp_path=temp_path,
                builder_mode=mode,
                batch_resampler=resampler,
            )
        )
    return targets, skipped_messages


def iter_source_batches(selection: SourceSelection, config: BuildConfig):
    dataset = ds.dataset(selection.paths, format="parquet")
    schema_names = set(dataset.schema.names)
    columns = scanner_columns(selection, schema_names)
    filter_expression = build_filter(config.start_date, config.end_date)
    fragments = sorted(dataset.get_fragments(filter=filter_expression), key=lambda fragment: fragment.path or "")
    log(f"{selection.pair}: source={selection.source_kind}/{selection.source_timeframe} fragments={len(fragments)}")
    for fragment in fragments:
        fragment_path = fragment.path or "<memory>"
        log(f"{selection.pair}: scanning fragment {fragment_path}")
        scanner = fragment.scanner(columns=columns, filter=filter_expression, batch_size=config.batch_size)
        batch_index = 0
        for batch in scanner.to_batches():
            batch_index += 1
            frame = batch.to_pandas()
            if frame.empty:
                continue
            yield fragment_path, batch_index, frame


def process_pair(pair: str, config: BuildConfig) -> BuildResult:
    result = BuildResult(pair=pair)

    if config.validate_only:
        for timeframe in sorted(set(config.timeframes), key=lambda timeframe: TIMEFRAME_ORDER[timeframe]):
            output_path = config.output_root / pair / timeframe / f"{pair.lower()}_{timeframe}.parquet"
            valid, message = validate_output_file(output_path, timeframe, sample_only=config.sample_validate)
            if valid:
                log(f"{pair} {timeframe}: {message}")
                result.validated.append(f"{timeframe}: {message}")
            else:
                failure = f"{pair} {timeframe}: validation failed ({message})"
                log(failure)
                result.failures.append(failure)
        return result

    selection = choose_source(config.input_root, pair, config.source_timeframe)
    if selection is None or not selection.paths:
        message = f"{pair}: no usable parquet source found"
        log(message)
        result.failures.append(message)
        return result
    selection = constrain_selection_to_window(selection, config)
    if not selection.paths:
        message = f"{pair}: no source fragments overlap the requested date window"
        log(message)
        result.failures.append(message)
        return result

    targets, skipped_messages = make_targets(pair, selection, config)
    for message in skipped_messages:
        log(message)
        result.skipped.append(message)

    active_targets = [target for target in targets if not target.skipped]
    if not active_targets:
        return result

    try:
        total_input_rows = 0
        for fragment_path, batch_index, frame in iter_source_batches(selection, config):
            total_input_rows += len(frame)
            if selection.source_kind == "ticks":
                standardized = standardize_tick_batch(frame, pair)
            else:
                standardized = standardize_bar_batch(frame, pair)
            log(
                f"{pair}: fragment={Path(fragment_path).name} batch={batch_index} "
                f"rows_read={len(frame)} standardized_rows={len(standardized)}"
            )
            for target in active_targets:
                log(f"{pair}: building {target.timeframe} from current batch")
                target.consume(standardized)

        for target in active_targets:
            log(f"{pair}: finalizing {target.timeframe}")
            target.finalize()
            if target.rows_written == 0:
                if target.final_path.exists():
                    target.final_path.unlink()
                log(f"{pair} {target.timeframe}: no rows generated for requested window")
                continue
            if config.sample_validate:
                valid, message = validate_output_file(target.final_path, target.timeframe, sample_only=True)
                if not valid:
                    raise ValueError(f"{pair} {target.timeframe}: sampled validation failed after build ({message})")
            result.built.append(f"{target.timeframe}: rows_written={target.rows_written} path={target.final_path}")

        log(f"{pair}: completed with total source rows read={total_input_rows}")
        return result
    except Exception as exc:
        for target in active_targets:
            target.abort()
        failure = f"{pair}: failed with {exc}"
        log(failure)
        log(traceback.format_exc())
        result.failures.append(failure)
        return result


def run_pairs(pairs: list[str], config: BuildConfig) -> list[BuildResult]:
    if config.validate_only or len(pairs) == 1 or config_over_single_worker(config):
        return [process_pair(pair, config) for pair in pairs]

    results: list[BuildResult] = []
    with ThreadPoolExecutor(max_workers=configured_workers(config, len(pairs))) as executor:
        future_map = {executor.submit(process_pair, pair, config): pair for pair in pairs}
        for future in as_completed(future_map):
            results.append(future.result())
    return results


def configured_workers(config: BuildConfig, pair_count: int) -> int:
    return max(1, min(pair_count, config.pair_workers))


def config_over_single_worker(config: BuildConfig) -> bool:
    return config.pair_workers <= 1


def summarize_results(results: list[BuildResult]) -> int:
    failures = 0
    for result in results:
        if result.built:
            for message in result.built:
                log(f"{result.pair}: built {message}")
        if result.validated:
            for message in result.validated:
                log(f"{result.pair}: validated {message}")
        failures += len(result.failures)
    return failures


def main() -> None:
    args = parse_args()
    timeframes = [timeframe.lower() for timeframe in args.timeframes]
    invalid_timeframes = [timeframe for timeframe in timeframes if timeframe not in TIMEFRAME_RULES]
    if invalid_timeframes:
        raise ValueError(f"Unsupported target timeframes: {invalid_timeframes}")
    if args.batch_size <= 0:
        raise ValueError("--batch-size must be positive")
    if args.pair_workers <= 0:
        raise ValueError("--pair-workers must be positive")

    input_root = Path(args.input_root).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    tmp_dir = Path(args.tmp_dir).expanduser().resolve() if args.tmp_dir else (Path.cwd() / ".tmp" / "timeframe_build")
    output_root.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    config = BuildConfig(
        input_root=input_root,
        output_root=output_root,
        tmp_dir=tmp_dir,
        timeframes=timeframes,
        start_date=parse_bound(args.start_date, is_end=False),
        end_date=parse_bound(args.end_date, is_end=True),
        batch_size=args.batch_size,
        skip_existing=args.skip_existing,
        overwrite=args.overwrite,
        validate_only=args.validate_only,
        sample_validate=args.sample_validate,
        source_timeframe=args.source_timeframe.lower() if args.source_timeframe else None,
        pair_workers=args.pair_workers,
    )

    pairs = [pair.upper() for pair in args.pairs]
    log(
        "Build configuration: "
        f"pairs={pairs} timeframes={timeframes} batch_size={args.batch_size} "
        f"pair_workers={args.pair_workers} validate_only={args.validate_only}"
    )

    results = run_pairs(pairs, config)
    failures = summarize_results(results)
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
