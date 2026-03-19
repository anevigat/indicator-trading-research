#!/usr/bin/env python3
"""Run a batch MA-strategy experiment matrix with resume support."""

from __future__ import annotations

import argparse
from collections import OrderedDict
import hashlib
import json
import multiprocessing
import shutil
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import pandas as pd
import pyarrow.dataset as ds

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from indicator_trading_research.backtest import (  # noqa: E402
    BacktestConfig,
    load_backtest_candles,
    run_backtest,
    save_backtest_result,
)
from indicator_trading_research.strategies import MAStrategy, build_ma_cache  # noqa: E402

EXPERIMENT_VERSION = "v1"

PAIRS = [
    "EURUSD",
    "EURJPY",
    "AUDUSD",
    "GBPJPY",
    "GBPUSD",
    "USDCAD",
    "USDJPY",
]

TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]

MA_PERIODS_2 = [(25, 50), (50, 100), (100, 200)]
MA_PERIODS_3 = [(25, 50, 100), (50, 100, 200)]

MA_TYPES_2 = [
    ("sma", "sma"),
    ("sma", "ema"),
    ("sma", "wma"),
    ("ema", "ema"),
    ("ema", "sma"),
    ("ema", "wma"),
    ("wma", "wma"),
    ("wma", "ema"),
    ("wma", "sma"),
]

MA_TYPES_3 = [
    ("sma", "sma", "sma"),
    ("ema", "ema", "ema"),
    ("ema", "sma", "sma"),
    ("wma", "sma", "sma"),
]

ENTRY_TYPES_2 = ["crossover", "crossover_breakout", "price_above_all"]
ENTRY_TYPES_3 = ["crossover", "crossover_breakout", "price_above_all"]

EXIT_PROFILES = [
    # "none",
    "fixed1010",
    "fixed1020",
    "fixed1030",
    "fixed2020",
    "fixed2040",
    "fixed2060",
    "atr051",
    "atr12",
    "atr13",
    # "atr_trailing",
    # "atr_trailing_be",
    # "atr_ma_stop",
]

TRAILING_TYPES = ["standard", "chandelier"]

DEFAULT_BACKTEST_SETTINGS: dict[str, Any] = {
    "strategy": "ma_strategy",
    "start_date": "2019-01-01",
    "end_date": "2025-12-31",
    "initial_capital": 100.0,
    "fixed_position_size": 1.0,
    "position_sizing_mode": "risk_percent",
    "risk_percent": 0.01,
    # "initial_capital": 10_000.0,
    # "fixed_position_size": 1.0,
    # "position_sizing_mode": "fixed",
    # "risk_percent": None,
    "account_currency": "USD",
    "spread": 0.0001,
    "slippage": 0.00002,
    "fee_per_trade": 0.0,
    "allow_long": True,
    "allow_short": True,
    "atr_period": 14,
    "atr_method": "wilder",
}

EXIT_PROFILE_SETTINGS: dict[str, dict[str, Any]] = {
    "none": {},
    "fixed1010": {
        "stop_loss": 0.0010,
        "stop_loss_mode": "absolute",
        "take_profit": 0.0010,
        "take_profit_mode": "absolute",
    },
    "fixed1020": {
        "stop_loss": 0.0010,
        "stop_loss_mode": "absolute",
        "take_profit": 0.0020,
        "take_profit_mode": "absolute",
    },
    "fixed1030": {
        "stop_loss": 0.0010,
        "stop_loss_mode": "absolute",
        "take_profit": 0.0030,
        "take_profit_mode": "absolute",
    },
    "fixed2020": {
        "stop_loss": 0.0020,
        "stop_loss_mode": "absolute",
        "take_profit": 0.0020,
        "take_profit_mode": "absolute",
    },
    "fixed2040": {
        "stop_loss": 0.0020,
        "stop_loss_mode": "absolute",
        "take_profit": 0.0040,
        "take_profit_mode": "absolute",
    },
    "fixed2060": {
        "stop_loss": 0.0020,
        "stop_loss_mode": "absolute",
        "take_profit": 0.0060,
        "take_profit_mode": "absolute",
    },
    "atr051": {
        "stop_loss": 0.5,
        "stop_loss_mode": "atr",
        "take_profit": 1.0,
        "take_profit_mode": "atr",
    },
    "atr12": {
        "stop_loss": 1.0,
        "stop_loss_mode": "atr",
        "take_profit": 2.0,
        "take_profit_mode": "atr",
    },
    "atr13": {
        "stop_loss": 1.0,
        "stop_loss_mode": "atr",
        "take_profit": 3.0,
        "take_profit_mode": "atr",
    },
    "atr_trailing": {
        "stop_loss": 1.0,
        "stop_loss_mode": "atr",
        "take_profit": 2.0,
        "take_profit_mode": "atr",
        "trailing_stop": 1.5,
        "trailing_stop_mode": "atr",
        "trailing_activation": 1.0,
        "trailing_activation_mode": "atr",
    },
    "atr_trailing_be": {
        "stop_loss": 1.0,
        "stop_loss_mode": "atr",
        "take_profit": 2.0,
        "take_profit_mode": "atr",
        "trailing_stop": 1.5,
        "trailing_stop_mode": "atr",
        "trailing_activation": 1.0,
        "trailing_activation_mode": "atr",
        "break_even": 1.0,
        "break_even_mode": "atr",
        "break_even_buffer": 0.25,
        "break_even_buffer_mode": "atr",
    },
    "atr_ma_stop": {
        "stop_loss": 1.0,
        "stop_loss_mode": "atr",
        "take_profit": 2.0,
        "take_profit_mode": "atr",
        "ma_stop": True,
        "ma_stop_source": "short",
        "ma_stop_buffer": 0.25,
        "ma_stop_buffer_mode": "atr",
    },
}

REQUIRED_METRIC_KEYS = [
    "total_trades",
    "net_pnl",
    "profit_factor",
    "max_drawdown",
]

RESULT_COLUMNS = [
    "config_hash",
    "version",
    "strategy",
    "pair",
    "timeframe",
    "start_date",
    "end_date",
    "initial_capital",
    "fixed_position_size",
    "position_sizing_mode",
    "risk_percent",
    "account_currency",
    "spread",
    "slippage",
    "fee_per_trade",
    "allow_long",
    "allow_short",
    "ma_types",
    "ma_periods",
    "ma_count",
    "entry_type",
    "exit_profile",
    "trailing_type",
    "stop_loss",
    "stop_loss_mode",
    "take_profit",
    "take_profit_mode",
    "trailing_stop",
    "trailing_stop_mode",
    "trailing_activation",
    "trailing_activation_mode",
    "chandelier_multiplier",
    "chandelier_atr_period",
    "chandelier_atr_method",
    "break_even",
    "break_even_mode",
    "break_even_buffer",
    "break_even_buffer_mode",
    "ma_stop",
    "ma_stop_source",
    "ma_stop_buffer",
    "ma_stop_buffer_mode",
    "atr_period",
    "atr_method",
    "config_json",
    "output_path",
    "run_started_at",
    "run_duration_sec",
    "final_capital",
    "total_return_pct",
    "total_trades",
    "gross_pnl",
    "net_pnl",
    "win_rate",
    "average_win",
    "average_loss",
    "profit_factor",
    "expectancy",
    "max_drawdown",
    "max_drawdown_pct",
    "ending_equity",
    "average_trade_duration_bars",
    "average_risk_amount",
    "average_position_size_used",
    "long_trades_count",
    "short_trades_count",
    "stop_loss_exits",
    "trailing_stop_exits",
    "chandelier_trailing_exits",
    "break_even_exits",
    "ma_stop_exits",
    "take_profit_exits",
    "signal_exits",
    "forced_end_exits",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        default="data/processed",
        help="Root processed data directory. Defaults to data/processed.",
    )
    parser.add_argument("--output-root", default="outputs/backtests", help="Root directory for saved backtest outputs.")
    parser.add_argument(
        "--output-path",
        default="outputs/experiments/ma_matrix.parquet",
        help="Parquet dataset path that stores flattened experiment rows.",
    )
    parser.add_argument("--results-path", dest="output_path", help=argparse.SUPPRESS)
    parser.add_argument(
        "--failed-log-path",
        default="outputs/experiments/failed_runs.jsonl",
        help="JSONL file that stores failed experiment configs.",
    )
    parser.add_argument("--start-date", default=DEFAULT_BACKTEST_SETTINGS["start_date"], help="UTC start date.")
    parser.add_argument("--end-date", default=DEFAULT_BACKTEST_SETTINGS["end_date"], help="UTC end date.")
    parser.add_argument("--pairs", nargs="*", default=None, help="Optional subset of pairs.")
    parser.add_argument("--timeframes", nargs="*", default=None, help="Optional subset of timeframes.")
    parser.add_argument("--exit-profiles", nargs="*", default=None, help="Optional subset of exit profiles.")
    parser.add_argument("--max-runs", type=int, default=None, help="Optional cap on pending runs for smoke testing.")
    parser.add_argument("--flush-every", type=int, default=20, help="Number of successful rows to buffer before flushing.")
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of dataset-slice worker processes. Defaults to 1 for single-process execution.",
    )
    parser.add_argument(
        "--experiment-version",
        default=EXPERIMENT_VERSION,
        help="Version label included in config hashes for cache invalidation.",
    )
    parser.add_argument("--overwrite-results", action="store_true", help="Delete existing result dataset before running.")
    return parser.parse_args()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expand_selection_values(values: list[str] | None) -> list[str]:
    if not values:
        return []
    expanded: list[str] = []
    for value in values:
        parts = [part.strip() for part in value.split(",")]
        expanded.extend(part for part in parts if part)
    return expanded


def normalize_selection(values: list[str] | None, allowed: list[str]) -> list[str]:
    expanded_values = _expand_selection_values(values)
    if not expanded_values:
        return allowed[:]
    allowed_map: dict[str, str] = {}
    for allowed_value in allowed:
        allowed_map[allowed_value] = allowed_value
        allowed_map[allowed_value.upper()] = allowed_value
        allowed_map[allowed_value.lower()] = allowed_value
    normalized: list[str] = []
    for value in expanded_values:
        if value in allowed_map:
            normalized.append(allowed_map[value])
            continue
        raise ValueError(f"Unsupported selection value: {value!r}. Allowed values: {allowed}")
    return normalized


def build_hash_input(config: dict[str, Any], version: str) -> dict[str, Any]:
    return {"version": version, "config": config}


def experiment_hash(config: dict[str, Any], version: str) -> str:
    payload = json.dumps(build_hash_input(config, version), sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _has_entry_time_stop_provider(config: dict[str, Any]) -> bool:
    return config.get("stop_loss") is not None or bool(config.get("ma_stop"))


def build_experiment_config(
    *,
    pair: str,
    timeframe: str,
    ma_types: tuple[str, ...],
    ma_periods: tuple[int, ...],
    entry_type: str,
    exit_profile: str,
    trailing_type: str | None,
    start_date: str,
    end_date: str,
    experiment_version: str,
) -> dict[str, Any]:
    config: dict[str, Any] = {
        **DEFAULT_BACKTEST_SETTINGS,
        "pair": pair,
        "timeframe": timeframe,
        "ma_types": list(ma_types),
        "ma_periods": list(ma_periods),
        "entry_type": entry_type,
        "exit_profile": exit_profile,
        "trailing_type_variant": trailing_type,
        "start_date": start_date,
        "end_date": end_date,
        "version": experiment_version,
    }
    config.update(EXIT_PROFILE_SETTINGS[exit_profile])
    if exit_profile in {"atr_trailing", "atr_trailing_be"}:
        if trailing_type is None:
            raise ValueError("Trailing profiles require a trailing_type.")
        config["trailing_type"] = trailing_type
        if trailing_type == "chandelier":
            config.pop("trailing_stop", None)
            config.pop("trailing_stop_mode", None)
            config["chandelier_multiplier"] = 1.5
            config["chandelier_atr_period"] = config["atr_period"]
            config["chandelier_atr_method"] = config["atr_method"]
        else:
            config["chandelier_multiplier"] = None
            config["chandelier_atr_period"] = 14
            config["chandelier_atr_method"] = "wilder"
    else:
        config["trailing_type"] = "standard"
        config["chandelier_multiplier"] = None
        config["chandelier_atr_period"] = 14
        config["chandelier_atr_method"] = "wilder"

    if exit_profile != "atr_ma_stop":
        config["ma_stop"] = False
        config["ma_stop_source"] = "short"
        config["ma_stop_buffer"] = None
        config["ma_stop_buffer_mode"] = None
    if exit_profile != "atr_trailing_be":
        config["break_even"] = None
        config["break_even_mode"] = None
        config["break_even_buffer"] = None
        config["break_even_buffer_mode"] = None

    hash_config = {
        "pair": pair,
        "timeframe": timeframe,
        "ma_types": list(ma_types),
        "ma_periods": list(ma_periods),
        "entry_type": entry_type,
        "exit_profile": exit_profile,
        "trailing_type_variant": trailing_type,
        "start_date": start_date,
        "end_date": end_date,
        "strategy": config["strategy"],
        "initial_capital": config["initial_capital"],
        "fixed_position_size": config["fixed_position_size"],
        "position_sizing_mode": config.get("position_sizing_mode", "fixed"),
        "risk_percent": config.get("risk_percent"),
        "account_currency": config.get("account_currency", "USD"),
        "spread": config["spread"],
        "slippage": config["slippage"],
        "fee_per_trade": config["fee_per_trade"],
        "allow_long": config["allow_long"],
        "allow_short": config["allow_short"],
        "stop_loss": config.get("stop_loss"),
        "stop_loss_mode": config.get("stop_loss_mode"),
        "take_profit": config.get("take_profit"),
        "take_profit_mode": config.get("take_profit_mode"),
        "trailing_stop": config.get("trailing_stop"),
        "trailing_stop_mode": config.get("trailing_stop_mode"),
        "trailing_type": config.get("trailing_type"),
        "trailing_activation": config.get("trailing_activation"),
        "trailing_activation_mode": config.get("trailing_activation_mode"),
        "chandelier_multiplier": config.get("chandelier_multiplier"),
        "chandelier_atr_period": config.get("chandelier_atr_period"),
        "chandelier_atr_method": config.get("chandelier_atr_method"),
        "break_even": config.get("break_even"),
        "break_even_mode": config.get("break_even_mode"),
        "break_even_buffer": config.get("break_even_buffer"),
        "break_even_buffer_mode": config.get("break_even_buffer_mode"),
        "ma_stop": config.get("ma_stop"),
        "ma_stop_source": config.get("ma_stop_source"),
        "ma_stop_buffer": config.get("ma_stop_buffer"),
        "ma_stop_buffer_mode": config.get("ma_stop_buffer_mode"),
        "atr_period": config["atr_period"],
        "atr_method": config["atr_method"],
    }
    config["config_hash"] = experiment_hash(hash_config, experiment_version)
    return config


def iter_experiment_configs(
    *,
    pairs: list[str],
    timeframes: list[str],
    exit_profiles: list[str],
    start_date: str,
    end_date: str,
    experiment_version: str,
) -> Iterator[dict[str, Any]]:
    for pair in sorted(pairs):
        for timeframe in sorted(timeframes):
            for ma_periods in sorted(MA_PERIODS_2):
                for ma_types in sorted(MA_TYPES_2):
                    for entry_type in sorted(ENTRY_TYPES_2):
                        for exit_profile in exit_profiles:
                            if exit_profile in {"atr_trailing", "atr_trailing_be"}:
                                for trailing_type in sorted(TRAILING_TYPES):
                                    config = build_experiment_config(
                                        pair=pair,
                                        timeframe=timeframe,
                                        ma_types=ma_types,
                                        ma_periods=ma_periods,
                                        entry_type=entry_type,
                                        exit_profile=exit_profile,
                                        trailing_type=trailing_type,
                                        start_date=start_date,
                                        end_date=end_date,
                                        experiment_version=experiment_version,
                                    )
                                    if config.get("position_sizing_mode") == "risk_percent" and not _has_entry_time_stop_provider(config):
                                        continue
                                    yield config
                            else:
                                config = build_experiment_config(
                                    pair=pair,
                                    timeframe=timeframe,
                                    ma_types=ma_types,
                                    ma_periods=ma_periods,
                                    entry_type=entry_type,
                                    exit_profile=exit_profile,
                                    trailing_type=None,
                                    start_date=start_date,
                                    end_date=end_date,
                                    experiment_version=experiment_version,
                                )
                                if config.get("position_sizing_mode") == "risk_percent" and not _has_entry_time_stop_provider(config):
                                    continue
                                yield config
            for ma_periods in sorted(MA_PERIODS_3):
                for ma_types in sorted(MA_TYPES_3):
                    for entry_type in sorted(ENTRY_TYPES_3):
                        if entry_type == "crossover":
                            continue
                        for exit_profile in exit_profiles:
                            if exit_profile in {"atr_trailing", "atr_trailing_be"}:
                                for trailing_type in sorted(TRAILING_TYPES):
                                    config = build_experiment_config(
                                        pair=pair,
                                        timeframe=timeframe,
                                        ma_types=ma_types,
                                        ma_periods=ma_periods,
                                        entry_type=entry_type,
                                        exit_profile=exit_profile,
                                        trailing_type=trailing_type,
                                        start_date=start_date,
                                        end_date=end_date,
                                        experiment_version=experiment_version,
                                    )
                                    if config.get("position_sizing_mode") == "risk_percent" and not _has_entry_time_stop_provider(config):
                                        continue
                                    yield config
                            else:
                                config = build_experiment_config(
                                    pair=pair,
                                    timeframe=timeframe,
                                    ma_types=ma_types,
                                    ma_periods=ma_periods,
                                    entry_type=entry_type,
                                    exit_profile=exit_profile,
                                    trailing_type=None,
                                    start_date=start_date,
                                    end_date=end_date,
                                    experiment_version=experiment_version,
                                )
                                if config.get("position_sizing_mode") == "risk_percent" and not _has_entry_time_stop_provider(config):
                                    continue
                                yield config


def dataset_slice_key(experiment: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        experiment["pair"],
        experiment["timeframe"],
        experiment["start_date"],
        experiment["end_date"],
    )


def group_experiments_by_slice(
    experiments: list[dict[str, Any]],
) -> list[tuple[tuple[str, str, str, str], list[dict[str, Any]]]]:
    grouped: OrderedDict[tuple[str, str, str, str], list[dict[str, Any]]] = OrderedDict()
    for experiment in experiments:
        grouped.setdefault(dataset_slice_key(experiment), []).append(experiment)
    return list(grouped.items())


def annotate_pending_slices(
    pending_slices: list[tuple[tuple[str, str, str, str], list[dict[str, Any]]]],
    *,
    total_pending: int,
) -> list[tuple[tuple[str, str, str, str], list[tuple[int, int, dict[str, Any]]]]]:
    annotated: list[tuple[tuple[str, str, str, str], list[tuple[int, int, dict[str, Any]]]]] = []
    ordinal = 0
    for slice_key, slice_experiments in pending_slices:
        slice_items: list[tuple[int, int, dict[str, Any]]] = []
        for experiment in slice_experiments:
            ordinal += 1
            slice_items.append((ordinal, total_pending, experiment))
        annotated.append((slice_key, slice_items))
    return annotated


def strategy_cache_key(experiment: dict[str, Any]) -> tuple[tuple[str, ...], tuple[int, ...], str, bool, bool]:
    return (
        tuple(experiment["ma_types"]),
        tuple(int(period) for period in experiment["ma_periods"]),
        experiment["entry_type"],
        bool(experiment["allow_long"]),
        bool(experiment["allow_short"]),
    )


def build_strategy_cache(experiments: list[dict[str, Any]]) -> dict[tuple[tuple[str, ...], tuple[int, ...], str, bool, bool], MAStrategy]:
    cache: dict[tuple[tuple[str, ...], tuple[int, ...], str, bool, bool], MAStrategy] = {}
    for experiment in experiments:
        signature = strategy_cache_key(experiment)
        if signature in cache:
            continue
        cache[signature] = MAStrategy(
            ma_types=list(signature[0]),
            ma_periods=list(signature[1]),
            entry_type=signature[2],
            allow_long=signature[3],
            allow_short=signature[4],
        )
    return cache


def collect_required_ma_keys(
    strategies: dict[tuple[tuple[str, ...], tuple[int, ...], str, bool, bool], MAStrategy],
) -> set[tuple[str, int]]:
    required_keys: set[tuple[str, int]] = set()
    for strategy in strategies.values():
        required_keys.update(strategy.required_ma_keys())
    return required_keys


def remove_output_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def ensure_output_dataset(path: Path) -> None:
    if path.exists() and path.is_file():
        legacy_file = path.with_suffix(path.suffix + ".legacy")
        path.rename(legacy_file)
        path.mkdir(parents=True, exist_ok=True)
        legacy_file.rename(path / "part-000000.parquet")
        return
    path.mkdir(parents=True, exist_ok=True)


def load_completed_hashes(output_path: Path) -> set[str]:
    if not output_path.exists():
        return set()
    if output_path.is_file():
        table = ds.dataset(output_path, format="parquet").to_table(columns=["config_hash"])
        return set(table.column("config_hash").to_pylist())
    dataset = ds.dataset(output_path, format="parquet")
    if "config_hash" not in dataset.schema.names:
        return set()
    table = dataset.to_table(columns=["config_hash"])
    return set(table.column("config_hash").to_pylist())


def load_failed_hashes(failed_log_path: Path) -> set[str]:
    if not failed_log_path.exists():
        return set()
    hashes: set[str] = set()
    for line in failed_log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        config_hash = payload.get("config_hash")
        if isinstance(config_hash, str) and config_hash:
            hashes.add(config_hash)
    return hashes


def next_part_index(output_path: Path) -> int:
    if not output_path.exists():
        return 0
    if output_path.is_file():
        return 1
    indices = []
    for file_path in output_path.glob("part-*.parquet"):
        try:
            indices.append(int(file_path.stem.split("-")[1]))
        except (IndexError, ValueError):
            continue
    return (max(indices) + 1) if indices else 0


def flush_result_buffer(output_path: Path, rows: list[dict[str, Any]], *, part_index: int) -> int:
    if not rows:
        return part_index
    ensure_output_dataset(output_path)
    frame = pd.DataFrame(rows).reindex(columns=RESULT_COLUMNS)
    frame.to_parquet(output_path / f"part-{part_index:06d}.parquet", index=False)
    rows.clear()
    return part_index + 1


def append_failed_run(failed_log_path: Path, payload: dict[str, Any]) -> None:
    failed_log_path.parent.mkdir(parents=True, exist_ok=True)
    with failed_log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def build_backtest_config(experiment: dict[str, Any]) -> BacktestConfig:
    return BacktestConfig(
        pair=experiment["pair"],
        timeframe=experiment["timeframe"],
        strategy_name="ma_strategy",
        start_date=experiment["start_date"],
        end_date=experiment["end_date"],
        initial_capital=experiment["initial_capital"],
        fixed_position_size=experiment["fixed_position_size"],
        position_sizing_mode=experiment.get("position_sizing_mode", "fixed"),
        risk_percent=experiment.get("risk_percent"),
        account_currency=experiment.get("account_currency", "USD"),
        strategy_params={
            "ma_types": experiment["ma_types"],
            "ma_periods": experiment["ma_periods"],
            "entry_type": experiment["entry_type"],
        },
        spread=experiment["spread"],
        slippage=experiment["slippage"],
        fee_per_trade=experiment["fee_per_trade"],
        allow_long=experiment["allow_long"],
        allow_short=experiment["allow_short"],
        stop_loss_mode=experiment.get("stop_loss_mode"),
        stop_loss=experiment.get("stop_loss"),
        take_profit_mode=experiment.get("take_profit_mode"),
        take_profit=experiment.get("take_profit"),
        trailing_stop_mode=experiment.get("trailing_stop_mode"),
        trailing_stop=experiment.get("trailing_stop"),
        trailing_type=experiment.get("trailing_type", "standard"),
        trailing_activation_mode=experiment.get("trailing_activation_mode"),
        trailing_activation=experiment.get("trailing_activation"),
        chandelier_multiplier=experiment.get("chandelier_multiplier"),
        chandelier_atr_period=experiment.get("chandelier_atr_period", 14),
        chandelier_atr_method=experiment.get("chandelier_atr_method", "wilder"),
        break_even_mode=experiment.get("break_even_mode"),
        break_even=experiment.get("break_even"),
        break_even_buffer_mode=experiment.get("break_even_buffer_mode"),
        break_even_buffer=experiment.get("break_even_buffer"),
        ma_stop=experiment.get("ma_stop", False),
        ma_stop_source=experiment.get("ma_stop_source", "short"),
        ma_stop_buffer_mode=experiment.get("ma_stop_buffer_mode"),
        ma_stop_buffer=experiment.get("ma_stop_buffer"),
        atr_period=experiment["atr_period"],
        atr_method=experiment["atr_method"],
    )


def validate_metrics_file(run_dir: Path) -> dict[str, Any]:
    metrics_path = run_dir / "metrics.json"
    if not metrics_path.exists():
        raise ValueError(f"Missing metrics.json: {metrics_path}")
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    missing_keys = [key for key in REQUIRED_METRIC_KEYS if key not in metrics]
    if missing_keys:
        raise ValueError(f"metrics.json is missing required keys: {missing_keys}")
    return metrics


def flatten_result(experiment: dict[str, Any], metrics: dict[str, Any], output_path: Path, *, run_started_at: str, run_duration_sec: float) -> dict[str, Any]:
    row = {
        "config_hash": experiment["config_hash"],
        "version": experiment["version"],
        "strategy": experiment["strategy"],
        "pair": experiment["pair"],
        "timeframe": experiment["timeframe"],
        "start_date": experiment["start_date"],
        "end_date": experiment["end_date"],
        "initial_capital": experiment["initial_capital"],
        "fixed_position_size": experiment["fixed_position_size"],
        "position_sizing_mode": experiment.get("position_sizing_mode", "fixed"),
        "risk_percent": experiment.get("risk_percent"),
        "account_currency": experiment.get("account_currency", "USD"),
        "spread": experiment["spread"],
        "slippage": experiment["slippage"],
        "fee_per_trade": experiment["fee_per_trade"],
        "allow_long": experiment["allow_long"],
        "allow_short": experiment["allow_short"],
        "ma_types": ",".join(experiment["ma_types"]),
        "ma_periods": ",".join(str(period) for period in experiment["ma_periods"]),
        "ma_count": len(experiment["ma_periods"]),
        "entry_type": experiment["entry_type"],
        "exit_profile": experiment["exit_profile"],
        "trailing_type": experiment["trailing_type"],
        "stop_loss": experiment.get("stop_loss"),
        "stop_loss_mode": experiment.get("stop_loss_mode"),
        "take_profit": experiment.get("take_profit"),
        "take_profit_mode": experiment.get("take_profit_mode"),
        "trailing_stop": experiment.get("trailing_stop"),
        "trailing_stop_mode": experiment.get("trailing_stop_mode"),
        "trailing_activation": experiment.get("trailing_activation"),
        "trailing_activation_mode": experiment.get("trailing_activation_mode"),
        "chandelier_multiplier": experiment.get("chandelier_multiplier"),
        "chandelier_atr_period": experiment.get("chandelier_atr_period"),
        "chandelier_atr_method": experiment.get("chandelier_atr_method"),
        "break_even": experiment.get("break_even"),
        "break_even_mode": experiment.get("break_even_mode"),
        "break_even_buffer": experiment.get("break_even_buffer"),
        "break_even_buffer_mode": experiment.get("break_even_buffer_mode"),
        "ma_stop": experiment.get("ma_stop", False),
        "ma_stop_source": experiment.get("ma_stop_source"),
        "ma_stop_buffer": experiment.get("ma_stop_buffer"),
        "ma_stop_buffer_mode": experiment.get("ma_stop_buffer_mode"),
        "atr_period": experiment["atr_period"],
        "atr_method": experiment["atr_method"],
        "config_json": json.dumps(experiment, sort_keys=True),
        "output_path": str(output_path),
        "run_started_at": run_started_at,
        "run_duration_sec": float(run_duration_sec),
    }
    row.update(metrics)
    return {column: row.get(column) for column in RESULT_COLUMNS}


def experiment_summary(experiment: dict[str, Any]) -> str:
    return (
        f"{experiment['pair']} {experiment['timeframe']} "
        f"{experiment['entry_type']} "
        f"{'/'.join(experiment['ma_types'])} "
        f"{'/'.join(str(period) for period in experiment['ma_periods'])} "
        f"exit={experiment['exit_profile']}"
        + (
            f" trailing={experiment['trailing_type_variant']}"
            if experiment["trailing_type_variant"] is not None
            else ""
        )
    )


def slice_summary(slice_key: tuple[str, str, str, str]) -> str:
    pair, timeframe, start_date, end_date = slice_key
    return f"{pair} {timeframe} {start_date}..{end_date}"


def format_experiment_result_line(
    *,
    ordinal: int,
    total: int,
    experiment: dict[str, Any],
    metrics: dict[str, Any],
) -> str:
    win_rate = metrics.get("win_rate")
    final_capital = metrics.get("final_capital")
    return (
        f"[{ordinal}/{total}] {experiment_summary(experiment)} "
        f"win_rate={float(win_rate) * 100:.2f}% "
        f"profit_factor={float(metrics.get('profit_factor', 0.0)):.3f} "
        f"final_capital={float(final_capital):.2f}"
        if win_rate is not None and final_capital is not None
        else f"[{ordinal}/{total}] {experiment_summary(experiment)} completed"
    )


def format_experiment_failure_line(
    *,
    ordinal: int,
    total: int,
    experiment: dict[str, Any],
    error: str,
) -> str:
    return f"[{ordinal}/{total}] {experiment_summary(experiment)} failed: {error}"


def _failure_payload(
    *,
    experiment: dict[str, Any],
    error: str,
    traceback_text: str,
    slice_key: tuple[str, str, str, str],
) -> dict[str, Any]:
    pair, timeframe, start_date, end_date = slice_key
    return {
        "config_hash": experiment["config_hash"],
        "config": experiment,
        "error": error,
        "timestamp": now_iso(),
        "traceback": traceback_text,
        "slice": {
            "pair": pair,
            "timeframe": timeframe,
            "start_date": start_date,
            "end_date": end_date,
        },
    }


def run_slice_worker(
    work_item: tuple[tuple[str, str, str, str], list[tuple[int, int, dict[str, Any]]], str, str],
) -> dict[str, Any]:
    slice_key, slice_items, data_root_str, output_root_str = work_item
    pair, timeframe, start_date, end_date = slice_key
    slice_started = time.time()
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    load_duration = 0.0
    cache_duration = 0.0
    run_duration_total = 0.0

    try:
        load_started = time.time()
        current_candles = load_backtest_candles(
            data_root=data_root_str,
            pair=pair,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
        )
        load_duration = time.time() - load_started

        cache_started = time.time()
        slice_experiments = [experiment for _, _, experiment in slice_items]
        strategies = build_strategy_cache(slice_experiments)
        required_ma_keys = collect_required_ma_keys(strategies)
        ma_cache = build_ma_cache(current_candles, required_ma_keys)
        cache_duration = time.time() - cache_started
        print(
            f"Worker ready {slice_summary(slice_key)} runs={len(slice_items)} "
            f"rows={len(current_candles)} load_sec={load_duration:.3f} ma_cache_sec={cache_duration:.3f}",
            flush=True,
        )

        for ordinal, total, experiment in slice_items:
            run_started_epoch = time.time()
            run_started_at = now_iso()
            try:
                strategy = strategies[strategy_cache_key(experiment)]
                signals = strategy.generate_signals(current_candles, indicator_cache=ma_cache)
                config = build_backtest_config(experiment)
                result = run_backtest(current_candles, signals, config)
                run_dir = save_backtest_result(result, output_root_str)
                run_duration = time.time() - run_started_epoch
                metrics = validate_metrics_file(run_dir)
                rows.append(
                    flatten_result(
                        experiment,
                        metrics,
                        run_dir,
                        run_started_at=run_started_at,
                        run_duration_sec=run_duration,
                    )
                )
                run_duration_total += run_duration
                print(
                    format_experiment_result_line(
                        ordinal=ordinal,
                        total=total,
                        experiment=experiment,
                        metrics=metrics,
                    ),
                    flush=True,
                )
            except Exception as exc:
                failures.append(
                    _failure_payload(
                        experiment=experiment,
                        error=str(exc),
                        traceback_text=traceback.format_exc(),
                        slice_key=slice_key,
                    )
                )
                print(
                    format_experiment_failure_line(
                        ordinal=ordinal,
                        total=total,
                        experiment=experiment,
                        error=str(exc),
                    ),
                    flush=True,
                )
    except Exception as exc:
        error_text = f"slice worker failed for {slice_summary(slice_key)}: {exc}"
        traceback_text = traceback.format_exc()
        for ordinal, total, experiment in slice_items:
            failures.append(
                _failure_payload(
                    experiment=experiment,
                    error=error_text,
                    traceback_text=traceback_text,
                    slice_key=slice_key,
                )
            )
            print(
                format_experiment_failure_line(
                    ordinal=ordinal,
                    total=total,
                    experiment=experiment,
                    error=error_text,
                ),
                flush=True,
            )

    total_duration = time.time() - slice_started
    average_run_duration = run_duration_total / len(slice_items) if slice_items else 0.0
    return {
        "slice_key": slice_key,
        "config_count": len(slice_items),
        "rows": rows,
        "failures": failures,
        "load_duration_sec": load_duration,
        "ma_cache_duration_sec": cache_duration,
        "run_duration_sec": run_duration_total,
        "slice_duration_sec": total_duration,
        "average_run_duration_sec": average_run_duration,
    }


def handle_completed_slice(
    *,
    payload: dict[str, Any],
    failed_log_path: Path,
    result_buffer: list[dict[str, Any]],
    output_path: Path,
    part_index: int,
    flush_every: int,
    slice_index: int,
    total_slices: int,
    completed_configs: int,
    total_configs: int,
) -> tuple[int, int]:
    for failure in payload["failures"]:
        append_failed_run(failed_log_path, failure)
    result_buffer.extend(payload["rows"])
    if len(result_buffer) >= flush_every:
        part_index = flush_result_buffer(output_path, result_buffer, part_index=part_index)

    print(
        f"Slice complete [{slice_index}/{total_slices}] {slice_summary(payload['slice_key'])} "
        f"configs={payload['config_count']} processed={completed_configs}/{total_configs} "
        f"success={len(payload['rows'])} failed={len(payload['failures'])} "
        f"load_sec={payload['load_duration_sec']:.3f} "
        f"ma_cache_sec={payload['ma_cache_duration_sec']:.3f} "
        f"avg_run_sec={payload['average_run_duration_sec']:.3f} "
        f"slice_sec={payload['slice_duration_sec']:.3f}"
    )
    return part_index, completed_configs


def run_pending_slices(
    *,
    pending_slices: list[tuple[tuple[str, str, str, str], list[dict[str, Any]]]],
    data_root: Path,
    output_root: Path,
    failed_log_path: Path,
    output_path: Path,
    part_index: int,
    flush_every: int,
    workers: int,
) -> int:
    result_buffer: list[dict[str, Any]] = []
    total_configs = sum(len(slice_experiments) for _, slice_experiments in pending_slices)
    completed_configs = 0
    completed_slices = 0
    annotated_slices = annotate_pending_slices(pending_slices, total_pending=total_configs)

    try:
        if workers == 1:
            for slice_key, slice_items in annotated_slices:
                print(f"Slice start [{completed_slices + 1}/{len(pending_slices)}] {slice_summary(slice_key)} runs={len(slice_items)}")
                payload = run_slice_worker((slice_key, slice_items, str(data_root), str(output_root)))
                completed_slices += 1
                completed_configs += payload["config_count"]
                part_index, _ = handle_completed_slice(
                    payload=payload,
                    failed_log_path=failed_log_path,
                    result_buffer=result_buffer,
                    output_path=output_path,
                    part_index=part_index,
                    flush_every=flush_every,
                    slice_index=completed_slices,
                    total_slices=len(pending_slices),
                    completed_configs=completed_configs,
                    total_configs=total_configs,
                )
        else:
            start_method = "fork" if "fork" in multiprocessing.get_all_start_methods() else "spawn"
            mp_context = multiprocessing.get_context(start_method)
            work_items = [
                (slice_key, slice_items, str(data_root), str(output_root))
                for slice_key, slice_items in annotated_slices
            ]
            for slice_key, slice_items in annotated_slices:
                print(f"Slice start [{completed_slices + 1}/{len(annotated_slices)}] {slice_summary(slice_key)} runs={len(slice_items)}")
                completed_slices += 1
            completed_slices = 0
            with mp_context.Pool(processes=workers) as pool:
                for payload in pool.imap_unordered(run_slice_worker, work_items):
                    completed_slices += 1
                    completed_configs += payload["config_count"]
                    part_index, _ = handle_completed_slice(
                        payload=payload,
                        failed_log_path=failed_log_path,
                        result_buffer=result_buffer,
                        output_path=output_path,
                        part_index=part_index,
                        flush_every=flush_every,
                        slice_index=completed_slices,
                        total_slices=len(pending_slices),
                        completed_configs=completed_configs,
                        total_configs=total_configs,
                    )
    except KeyboardInterrupt:
        if result_buffer:
            part_index = flush_result_buffer(output_path, result_buffer, part_index=part_index)
        raise

    if result_buffer:
        part_index = flush_result_buffer(output_path, result_buffer, part_index=part_index)
    return part_index


def main() -> None:
    args = parse_args()
    output_path = Path(args.output_path).expanduser().resolve()
    failed_log_path = Path(args.failed_log_path).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    data_root = Path(args.data_root).expanduser().resolve()

    if args.flush_every <= 0:
        raise ValueError("--flush-every must be positive.")
    if args.workers <= 0:
        raise ValueError("--workers must be positive.")

    pairs = normalize_selection(args.pairs, PAIRS)
    timeframes = normalize_selection(args.timeframes, TIMEFRAMES)
    exit_profiles = normalize_selection(args.exit_profiles, EXIT_PROFILES)

    if args.overwrite_results:
        remove_output_path(output_path)

    experiments = list(
        iter_experiment_configs(
            pairs=pairs,
            timeframes=timeframes,
            exit_profiles=exit_profiles,
            start_date=args.start_date,
            end_date=args.end_date,
            experiment_version=args.experiment_version,
        )
    )
    experiment_hashes = {experiment["config_hash"] for experiment in experiments}
    completed_hashes = load_completed_hashes(output_path) & experiment_hashes
    failed_hashes = load_failed_hashes(failed_log_path) & experiment_hashes
    attempted_hashes = completed_hashes | failed_hashes
    pending = [experiment for experiment in experiments if experiment["config_hash"] not in attempted_hashes]
    if args.max_runs is not None:
        pending = pending[: args.max_runs]

    pending_slices = group_experiments_by_slice(pending)
    print(
        f"Experiment matrix: total={len(experiments)} completed={len(completed_hashes)} failed={len(failed_hashes)} pending={len(pending)} "
        f"slices={len(pending_slices)} workers={args.workers} output={output_path} version={args.experiment_version}"
    )
    if not pending:
        print("No pending experiment configs. Resume is already up to date.")
        return

    part_index = next_part_index(output_path)

    try:
        part_index = run_pending_slices(
            pending_slices=pending_slices,
            data_root=data_root,
            output_root=output_root,
            failed_log_path=failed_log_path,
            output_path=output_path,
            part_index=part_index,
            flush_every=args.flush_every,
            workers=args.workers,
        )
    except KeyboardInterrupt:
        print("Interrupted. Any completed slice results already received by the parent were flushed before exit.")
        raise SystemExit(130)


if __name__ == "__main__":
    main()
