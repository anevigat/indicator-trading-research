#!/usr/bin/env python3
"""Audit FX source data layout and write a reusable markdown report."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

TARGET_PAIRS = ["EURUSD", "USDJPY", "GBPUSD", "EURJPY", "AUDUSD", "USDCAD"]
TARGET_TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]
TARGET_TIMEFRAME_SET = set(TARGET_TIMEFRAMES)
STRUCTURED_SUFFIXES = {".parquet", ".csv", ".json", ".jsonl"}
TIMESTAMP_CANDIDATES = (
    "timestamp",
    "datetime",
    "time",
    "date",
    "ts",
)
WINDOWS = {
    "2018-2024": set(range(2018, 2025)),
    "2025-now": set(range(2025, datetime.now(tz=UTC).year + 1)),
}
TIMEFRAME_PATTERN = re.compile(r"(?<!\d)(1m|5m|15m|30m|1h|4h|1d)(?!\d)", re.IGNORECASE)
PAIR_PATTERN = re.compile(r"\b([A-Z]{6})\b")


@dataclass
class FileRecord:
    relative_path: str
    suffix: str
    size_bytes: int
    pair: str | None = None
    inferred_timeframes: list[str] = field(default_factory=list)
    row_count: int | None = None
    timestamp_column: str | None = None
    min_timestamp: str | None = None
    max_timestamp: str | None = None
    coverage_mode: str | None = None
    notes: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    inferred_years: set[int] = field(default_factory=set)


@dataclass
class RawRootSummary:
    relative_root: str
    pair: str | None
    file_count: int = 0
    years: set[int] = field(default_factory=set)
    first_path: str | None = None
    last_path: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True, help="Source data root to audit.")
    parser.add_argument(
        "--output-file",
        default="docs/research/phase1_bootstrap_and_data_audit.md",
        help="Markdown file to write.",
    )
    return parser.parse_args()


def normalize_pair(text: str) -> str | None:
    upper_text = text.upper()
    for pair in TARGET_PAIRS:
        if pair in upper_text:
            return pair
    match = PAIR_PATTERN.search(upper_text.replace("-", "_").replace("/", "_"))
    if match:
        return match.group(1)
    return None


def infer_timeframes(text: str) -> list[str]:
    found = {match.lower() for match in TIMEFRAME_PATTERN.findall(text.lower())}
    return sorted(found, key=TARGET_TIMEFRAMES.index) if found else []


def infer_years_from_text(text: str) -> set[int]:
    years = {int(year) for year in re.findall(r"\b(20\d{2})\b", text)}
    return {year for year in years if 2010 <= year <= datetime.now(tz=UTC).year + 1}


def format_timestamp(value: pd.Timestamp | None) -> str | None:
    if value is None or pd.isna(value):
        return None
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.isoformat()


def summarize_range(path: Path, row_count: int | None, timestamp_column: str | None) -> tuple[str | None, str | None, str | None]:
    if not timestamp_column or row_count in (None, 0):
        return None, None, None

    parquet_file = pq.ParquetFile(path)
    if row_count <= 2_000_000 or path.stat().st_size <= 256 * 1024 * 1024:
        min_ts: pd.Timestamp | None = None
        max_ts: pd.Timestamp | None = None
        for batch in parquet_file.iter_batches(columns=[timestamp_column], batch_size=500_000):
            values = pd.to_datetime(batch.column(0).to_pandas(), utc=True, errors="coerce")
            if values.empty:
                continue
            batch_min = values.min()
            batch_max = values.max()
            if pd.notna(batch_min) and (min_ts is None or batch_min < min_ts):
                min_ts = batch_min
            if pd.notna(batch_max) and (max_ts is None or batch_max > max_ts):
                max_ts = batch_max
        return format_timestamp(min_ts), format_timestamp(max_ts), "exact_scan"

    first_group = parquet_file.read_row_group(0, columns=[timestamp_column]).column(0).to_pandas()
    last_group = parquet_file.read_row_group(parquet_file.num_row_groups - 1, columns=[timestamp_column]).column(0).to_pandas()
    first_values = pd.to_datetime(first_group, utc=True, errors="coerce").dropna()
    last_values = pd.to_datetime(last_group, utc=True, errors="coerce").dropna()
    min_ts = first_values.iloc[0] if not first_values.empty else None
    max_ts = last_values.iloc[-1] if not last_values.empty else None
    return format_timestamp(min_ts), format_timestamp(max_ts), "boundary_sample"


def inspect_parquet(path: Path, relative_path: str) -> FileRecord:
    parquet_file = pq.ParquetFile(path)
    schema = parquet_file.schema_arrow
    columns = list(schema.names)
    timestamp_column = next((column for column in TIMESTAMP_CANDIDATES if column in columns), None)
    min_ts, max_ts, coverage_mode = summarize_range(path, parquet_file.metadata.num_rows, timestamp_column)
    inferred_years = infer_years_from_text(relative_path)
    if min_ts:
        inferred_years.update(range(pd.Timestamp(min_ts).year, pd.Timestamp(max_ts).year + 1))
    notes: list[str] = []
    if coverage_mode == "boundary_sample":
        notes.append("timestamp coverage estimated from first/last row group boundaries")
    return FileRecord(
        relative_path=relative_path,
        suffix=path.suffix.lower(),
        size_bytes=path.stat().st_size,
        pair=normalize_pair(relative_path),
        inferred_timeframes=infer_timeframes(relative_path),
        row_count=parquet_file.metadata.num_rows,
        timestamp_column=timestamp_column,
        min_timestamp=min_ts,
        max_timestamp=max_ts,
        coverage_mode=coverage_mode,
        notes=notes,
        columns=columns,
        inferred_years=inferred_years,
    )


def inspect_csv(path: Path, relative_path: str) -> FileRecord:
    row_count = 0
    timestamp_column = None
    min_ts: pd.Timestamp | None = None
    max_ts: pd.Timestamp | None = None
    columns: list[str] = []
    for chunk in pd.read_csv(path, chunksize=250_000):
        if not columns:
            columns = list(chunk.columns)
            timestamp_column = next((column for column in TIMESTAMP_CANDIDATES if column in columns), None)
        row_count += len(chunk)
        if timestamp_column and timestamp_column in chunk.columns:
            values = pd.to_datetime(chunk[timestamp_column], utc=True, errors="coerce")
            chunk_min = values.min()
            chunk_max = values.max()
            if pd.notna(chunk_min) and (min_ts is None or chunk_min < min_ts):
                min_ts = chunk_min
            if pd.notna(chunk_max) and (max_ts is None or chunk_max > max_ts):
                max_ts = chunk_max
    inferred_years = infer_years_from_text(relative_path)
    if min_ts and max_ts:
        inferred_years.update(range(min_ts.year, max_ts.year + 1))
    return FileRecord(
        relative_path=relative_path,
        suffix=path.suffix.lower(),
        size_bytes=path.stat().st_size,
        pair=normalize_pair(relative_path),
        inferred_timeframes=infer_timeframes(relative_path),
        row_count=row_count,
        timestamp_column=timestamp_column,
        min_timestamp=format_timestamp(min_ts),
        max_timestamp=format_timestamp(max_ts),
        coverage_mode="exact_scan",
        columns=columns,
        inferred_years=inferred_years,
    )


def inspect_other_structured(path: Path, relative_path: str) -> FileRecord:
    return FileRecord(
        relative_path=relative_path,
        suffix=path.suffix.lower(),
        size_bytes=path.stat().st_size,
        pair=normalize_pair(relative_path),
        inferred_timeframes=infer_timeframes(relative_path),
        inferred_years=infer_years_from_text(relative_path),
        notes=["timestamp range not inferred for this file type"],
    )


def inspect_file(path: Path, input_root: Path) -> FileRecord | None:
    relative_path = path.relative_to(input_root).as_posix()
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return inspect_parquet(path, relative_path)
    if suffix == ".csv":
        return inspect_csv(path, relative_path)
    if suffix in {".json", ".jsonl"}:
        return inspect_other_structured(path, relative_path)
    if suffix in STRUCTURED_SUFFIXES:
        return inspect_other_structured(path, relative_path)
    return None


def to_years(record: FileRecord) -> set[int]:
    return set(record.inferred_years)


def describe_record(record: FileRecord) -> str:
    timeframe_text = ", ".join(record.inferred_timeframes) if record.inferred_timeframes else "n/a"
    row_text = str(record.row_count) if record.row_count is not None else "n/a"
    range_text = "n/a"
    if record.min_timestamp or record.max_timestamp:
        range_text = f"{record.min_timestamp or '?'} -> {record.max_timestamp or '?'}"
    note_text = f" | notes: {'; '.join(record.notes)}" if record.notes else ""
    return (
        f"- `{record.relative_path}` | pair={record.pair or 'n/a'} | timeframe={timeframe_text} "
        f"| rows={row_text} | coverage={range_text}{note_text}"
    )


def describe_raw_root(summary: RawRootSummary) -> str:
    years = ", ".join(str(year) for year in sorted(summary.years)) or "n/a"
    first_path = summary.first_path or "n/a"
    last_path = summary.last_path or "n/a"
    return (
        f"- `{summary.relative_root}` | pair={summary.pair or 'n/a'} | raw_files={summary.file_count} "
        f"| years={years} | first={first_path} | last={last_path}"
    )


def timeframe_rank(timeframe: str) -> int:
    return TARGET_TIMEFRAMES.index(timeframe)


def derive_buildable_timeframes(direct_timeframes: set[str], has_cleaned_ticks: bool) -> list[str]:
    if has_cleaned_ticks:
        return list(TARGET_TIMEFRAMES)
    if not direct_timeframes:
        return []
    smallest_rank = min(timeframe_rank(timeframe) for timeframe in direct_timeframes)
    return [timeframe for timeframe in TARGET_TIMEFRAMES if timeframe_rank(timeframe) >= smallest_rank]


def format_missing_years(missing_years: set[int]) -> str:
    return ", ".join(str(year) for year in sorted(missing_years)) if missing_years else "none"


def build_report(input_root: Path, structured_records: list[FileRecord], raw_roots: dict[str, RawRootSummary]) -> tuple[str, dict[str, dict[str, object]]]:
    pair_summary: dict[str, dict[str, object]] = {}
    all_pairs = sorted({record.pair for record in structured_records if record.pair} | {summary.pair for summary in raw_roots.values() if summary.pair})
    for pair in sorted(set(TARGET_PAIRS) | set(all_pairs)):
        matching_records = [record for record in structured_records if record.pair == pair]
        usable_records = [record for record in matching_records if record.suffix in {".parquet", ".csv"}]
        matching_raw = [summary for summary in raw_roots.values() if summary.pair == pair]
        direct_timeframes = {
            timeframe
            for record in usable_records
            for timeframe in record.inferred_timeframes
            if timeframe in TARGET_TIMEFRAME_SET
        }
        years = set()
        years.update(*(to_years(record) for record in matching_records))
        for raw_root in matching_raw:
            years.update(raw_root.years)
        has_cleaned_ticks = any(record.relative_path.startswith("cleaned_ticks/") for record in usable_records)
        has_raw_only = bool(matching_raw) and not usable_records
        buildable_timeframes = derive_buildable_timeframes(direct_timeframes, has_cleaned_ticks)
        missing_buildable = sorted(set(TARGET_TIMEFRAMES) - set(buildable_timeframes), key=timeframe_rank)
        window_gaps = {label: sorted(required_years - years) for label, required_years in WINDOWS.items()}
        min_timestamp = min((record.min_timestamp for record in usable_records if record.min_timestamp), default=None)
        max_timestamp = max((record.max_timestamp for record in usable_records if record.max_timestamp), default=None)
        pair_summary[pair] = {
            "structured_files": len(matching_records),
            "usable_structured_files": len(usable_records),
            "raw_roots": len(matching_raw),
            "direct_timeframes": sorted(direct_timeframes, key=timeframe_rank),
            "buildable_timeframes": buildable_timeframes,
            "missing_buildable_timeframes": missing_buildable,
            "observed_years": sorted(years),
            "window_gaps": window_gaps,
            "has_cleaned_ticks": has_cleaned_ticks,
            "has_raw_only": has_raw_only,
            "min_timestamp": min_timestamp,
            "max_timestamp": max_timestamp,
        }

    missing_pairs = [pair for pair in TARGET_PAIRS if pair_summary.get(pair, {}).get("usable_structured_files", 0) == 0 and pair_summary.get(pair, {}).get("raw_roots", 0) == 0]
    raw_only_pairs = [pair for pair, summary in pair_summary.items() if summary.get("has_raw_only")]
    incomplete_pairs = [
        pair for pair, summary in pair_summary.items()
        if pair in TARGET_PAIRS and summary.get("missing_buildable_timeframes")
    ]

    quality_issues = []
    if any("recent" in record.relative_path for record in structured_records):
        quality_issues.append("auxiliary 'recent' datasets exist and likely overlap the canonical year-bucketed files")
    if any(record.relative_path.endswith("_raw.parquet") for record in structured_records):
        quality_issues.append("raw and cleaned parquet variants coexist under bars/15m, so downstream consumers need a clear primary-source rule")
    if any(record.relative_path == "bars/15m/eurusd_bars_latest.parquet" for record in structured_records):
        quality_issues.append("EURUSD includes a latest snapshot file with inconsistent naming versus the rest of the tree")
    if pair_summary.get("AUDUSD", {}).get("usable_structured_files", 0) == 0 and pair_summary.get("AUDUSD", {}).get("raw_roots", 0) > 0:
        quality_issues.append("AUDUSD is present only as raw Dukascopy `.bi5` files in the audited tree, not as cleaned parquet or normalized bars")
    if "USDCAD" in missing_pairs:
        quality_issues.append("USDCAD is absent from the audited source tree")

    structured_lines = [describe_record(record) for record in sorted(structured_records, key=lambda record: record.relative_path)]
    raw_lines = [describe_raw_root(raw_roots[key]) for key in sorted(raw_roots)]
    pair_lines = []
    for pair in TARGET_PAIRS:
        summary = pair_summary[pair]
        direct = ", ".join(summary["direct_timeframes"]) or "none"
        buildable = ", ".join(summary["buildable_timeframes"]) or "none"
        missing_tfs = ", ".join(summary["missing_buildable_timeframes"]) or "none"
        years = ", ".join(str(year) for year in summary["observed_years"]) or "none"
        pair_lines.append(
            f"- `{pair}` | structured_files={summary['structured_files']} | usable_structured_files={summary['usable_structured_files']} "
            f"| raw_roots={summary['raw_roots']} "
            f"| direct_timeframes={direct} | buildable_now={buildable} | missing_buildable={missing_tfs} "
            f"| observed_years={years} | coverage={summary['min_timestamp'] or '?'} -> {summary['max_timestamp'] or '?'}"
        )

    missing_pair_lines = [f"- `{pair}`" for pair in missing_pairs] or ["- none"]
    missing_timeframe_lines = [
        f"- `{pair}` missing buildable timeframes: {', '.join(pair_summary[pair]['missing_buildable_timeframes'])}"
        for pair in incomplete_pairs
    ] or ["- none"]
    date_gap_lines = []
    for pair in TARGET_PAIRS:
        summary = pair_summary[pair]
        for window, missing_years in summary["window_gaps"].items():
            if missing_years:
                date_gap_lines.append(f"- `{pair}` missing years in {window}: {format_missing_years(set(missing_years))}")
    if not date_gap_lines:
        date_gap_lines = ["- none"]

    quality_lines = [f"- {issue}" for issue in quality_issues] or ["- no material issues were detected automatically"]

    markdown = f"""# Phase 1 Bootstrap And Data Audit

## Objective

Establish a clean starting point for `indicator-trading-research`, audit the existing FX source data tree at `{input_root}`, and define a reproducible path to normalized Parquet timeframe datasets.

## Assumptions

- Target pairs: {", ".join(TARGET_PAIRS)}
- Target timeframes: {", ".join(TARGET_TIMEFRAMES)}
- Coverage checks compare observed years against `2018-2024` and `2025-now`.
- Structured parquet files are inspected directly; large parquet timestamp ranges may use first/last row-group boundaries when a full scan would be unnecessarily expensive.
- Raw Dukascopy `.bi5` trees are summarized by root and year coverage instead of expanding every hourly file path into this markdown report.
- Phase 1 timeframe generation reads parquet sources only and does not decode `.bi5` files.

## Existing Data Inventory

Structured files discovered: {len(structured_records)}

{chr(10).join(structured_lines) if structured_lines else "- none"}

Raw Dukascopy roots discovered: {len(raw_roots)}

{chr(10).join(raw_lines) if raw_lines else "- none"}

## Pair Summary

{chr(10).join(pair_lines)}

## Missing Pairs

{chr(10).join(missing_pair_lines)}

## Missing Timeframes

These are missing relative to what Phase 1 can build directly from the currently available cleaned parquet or prebuilt bar sources.

{chr(10).join(missing_timeframe_lines)}

## Missing Date Coverage

{chr(10).join(date_gap_lines)}

## Data Quality Issues

{chr(10).join(quality_lines)}

## Generation Approach For Derived Timeframes

- Prefer `cleaned_ticks/<PAIR>/.../*.parquet` when available.
- Build `1m` bars from tick `mid` prices and mean `spread`.
- Derive `5m`, `15m`, `30m`, `1h`, `4h`, and `1d` from the lowest reliable source available per pair.
- Use deterministic OHLC aggregation: `open=first`, `high=max`, `low=min`, `close=last`.
- Sum `volume` only when a source volume column exists. Otherwise omit volume and carry `tick_count` when the source is tick data.
- Skip target timeframes that are lower than the best available source timeframe.

## Validation Performed

- Repository bootstrap completed with `.venv`, `requirements.txt`, package scaffold, `.gitignore`, README updates, and permanent data utilities.
- Audit utility executed against the full source data root to generate this note.
- Timeframe builder validation is documented separately in the Phase 1 work summary and PR.

## Open Questions / Next Actions

- Decide whether Phase 2 should decode raw Dukascopy `.bi5` files so `AUDUSD` can join the normalized pipeline.
- Decide whether `USDCAD` should be sourced from Dukascopy, another vendor, or excluded from the first research batch.
- Resolve overlapping auxiliary datasets such as `recent`, `latest`, and `_raw` variants before relying on fully automated full-history rebuilds.
- After the data layer is stable, add indicator research notebooks or scripts on top of the normalized Parquet outputs.
"""
    return markdown, pair_summary


def print_terminal_summary(structured_records: list[FileRecord], raw_roots: dict[str, RawRootSummary], pair_summary: dict[str, dict[str, object]]) -> None:
    print("Audit complete")
    print(f"Structured files: {len(structured_records)}")
    print(f"Raw Dukascopy roots: {len(raw_roots)}")
    for pair in TARGET_PAIRS:
        summary = pair_summary[pair]
        print(
            f"{pair}: direct={','.join(summary['direct_timeframes']) or 'none'} | "
            f"buildable={','.join(summary['buildable_timeframes']) or 'none'} | "
            f"missing={','.join(summary['missing_buildable_timeframes']) or 'none'}"
        )


def main() -> None:
    args = parse_args()
    input_root = Path(args.input_root).expanduser().resolve()
    output_file = Path(args.output_file).expanduser().resolve()
    output_file.parent.mkdir(parents=True, exist_ok=True)

    structured_records: list[FileRecord] = []
    raw_roots: dict[str, RawRootSummary] = {}
    other_files = Counter()

    for path in sorted(input_root.rglob("*")):
        if not path.is_file():
            continue
        relative_path = path.relative_to(input_root).as_posix()
        if path.suffix.lower() == ".bi5":
            parts = relative_path.split("/")
            raw_root = "/".join(parts[:3]) if len(parts) >= 3 else relative_path
            summary = raw_roots.setdefault(
                raw_root,
                RawRootSummary(relative_root=raw_root, pair=normalize_pair(raw_root)),
            )
            summary.file_count += 1
            summary.years.update(infer_years_from_text(relative_path))
            summary.first_path = relative_path if summary.first_path is None else min(summary.first_path, relative_path)
            summary.last_path = relative_path if summary.last_path is None else max(summary.last_path, relative_path)
            continue
        record = inspect_file(path, input_root)
        if record is not None:
            structured_records.append(record)
        else:
            other_files[path.suffix.lower() or "[no_suffix]"] += 1

    markdown, pair_summary = build_report(input_root, structured_records, raw_roots)
    output_file.write_text(markdown, encoding="utf-8")
    print_terminal_summary(structured_records, raw_roots, pair_summary)
    if other_files:
        print("Other file suffix counts:", json.dumps(dict(other_files), sort_keys=True))
    print(f"Markdown report written to {output_file}")


if __name__ == "__main__":
    main()
