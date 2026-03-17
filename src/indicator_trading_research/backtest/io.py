"""IO helpers for backtest inputs and outputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.dataset as ds

from .contracts import BacktestConfig, BacktestResult

REQUIRED_CANDLE_COLUMNS = ("timestamp", "open", "high", "low", "close")
OPTIONAL_CANDLE_COLUMNS = ("pair", "timeframe", "spread", "tick_count", "volume", "source_kind", "source_timeframe")


def _parse_bound(value: str | None, *, is_end: bool) -> pd.Timestamp | None:
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


def _build_filter(start_date: pd.Timestamp | None, end_date: pd.Timestamp | None) -> ds.Expression | None:
    expression: ds.Expression | None = None
    if start_date is not None:
        expression = ds.field("timestamp") >= start_date.to_pydatetime()
    if end_date is not None:
        end_expression = ds.field("timestamp") <= end_date.to_pydatetime()
        expression = end_expression if expression is None else expression & end_expression
    return expression


def processed_parquet_path(data_root: str | Path, pair: str, timeframe: str) -> Path:
    root = Path(data_root).expanduser().resolve()
    return root / pair.upper() / timeframe.lower() / f"{pair.lower()}_{timeframe.lower()}.parquet"


def load_backtest_candles(
    *,
    data_root: str | Path,
    pair: str,
    timeframe: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    parquet_path = processed_parquet_path(data_root, pair, timeframe)
    if not parquet_path.exists():
        raise FileNotFoundError(f"Processed candle parquet not found: {parquet_path}")

    dataset = ds.dataset(parquet_path, format="parquet")
    available_columns = list(dataset.schema.names)
    selected_columns = [column for column in (*REQUIRED_CANDLE_COLUMNS, *OPTIONAL_CANDLE_COLUMNS) if column in available_columns]
    table = dataset.to_table(
        columns=selected_columns,
        filter=_build_filter(_parse_bound(start_date, is_end=False), _parse_bound(end_date, is_end=True)),
    )
    frame = table.to_pandas()
    if frame.empty:
        raise ValueError(f"No candle rows found for {pair} {timeframe} between {start_date} and {end_date}.")

    missing_columns = [column for column in REQUIRED_CANDLE_COLUMNS if column not in frame.columns]
    if missing_columns:
        raise ValueError(f"Missing required candle columns: {missing_columns}")

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    if frame["timestamp"].duplicated().any():
        raise ValueError("Candle input contains duplicate timestamps.")
    return frame


def _json_default(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float):
        return float(value)
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def build_run_id(config: BacktestConfig) -> str:
    payload = json.dumps(config.to_dict(), sort_keys=True, default=_json_default)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]
    start = str(config.start_date).replace(":", "").replace(" ", "_")
    end = str(config.end_date).replace(":", "").replace(" ", "_")
    return f"{config.strategy_name}_{start}_{end}_{digest}"


def save_backtest_result(result: BacktestResult, output_root: str | Path) -> Path:
    output_root_path = Path(output_root).expanduser().resolve()
    run_id = build_run_id(result.config)
    run_dir = output_root_path / result.config.strategy_name / result.config.pair / result.config.timeframe / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "config.json").write_text(
        json.dumps(result.config.to_dict(), indent=2, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )
    (run_dir / "metrics.json").write_text(
        json.dumps(result.metrics, indent=2, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )
    result.trades.to_parquet(run_dir / "trades.parquet", index=False)
    if result.signals is not None:
        result.signals.to_parquet(run_dir / "signals.parquet", index=False)
    if result.equity_curve is not None:
        result.equity_curve.to_parquet(run_dir / "equity_curve.parquet", index=False)
    return run_dir

