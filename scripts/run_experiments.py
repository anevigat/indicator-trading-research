#!/usr/bin/env python3
"""Run a batch MA-strategy experiment matrix with resume support."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

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
from indicator_trading_research.strategies import MAStrategy  # noqa: E402

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

MA_PERIODS_2 = [(10, 50), (20, 50), (25, 50)]
MA_PERIODS_3 = [(10, 20, 50), (20, 50, 100), (25, 50, 200)]

MA_TYPES_2 = [
    ("sma", "sma"),
    ("ema", "ema"),
    ("wma", "wma"),
    ("ema", "sma"),
    ("wma", "sma"),
]

MA_TYPES_3 = [
    ("sma", "sma", "sma"),
    ("ema", "sma", "sma"),
    ("wma", "sma", "sma"),
]

ENTRY_TYPES_2 = ["crossover", "crossover_breakout"]
ENTRY_TYPES_3 = ["crossover", "crossover_breakout", "price_above_all"]

EXIT_PROFILES = [
    "none",
    "fixed",
    "atr",
    "atr_trailing",
    "atr_trailing_be",
    "atr_ma_stop",
]

TRAILING_TYPES = ["standard", "chandelier"]

DEFAULT_BACKTEST_SETTINGS: dict[str, Any] = {
    "strategy": "ma_strategy",
    "start_date": "2019-01-01",
    "end_date": "2025-12-31",
    "initial_capital": 10_000.0,
    "fixed_position_size": 1.0,
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
    "fixed": {
        "stop_loss": 0.0020,
        "stop_loss_mode": "absolute",
        "take_profit": 0.0040,
        "take_profit_mode": "absolute",
    },
    "atr": {
        "stop_loss": 1.0,
        "stop_loss_mode": "atr",
        "take_profit": 2.0,
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, help="Root processed data directory.")
    parser.add_argument("--output-root", default="outputs/backtests", help="Root directory for saved backtest outputs.")
    parser.add_argument(
        "--results-path",
        default="outputs/experiments/ma_matrix.parquet",
        help="Parquet file that stores flattened experiment results.",
    )
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
    parser.add_argument("--overwrite-results", action="store_true", help="Delete existing result parquet before running.")
    return parser.parse_args()


def normalize_selection(values: list[str] | None, allowed: list[str]) -> list[str]:
    if not values:
        return allowed[:]
    allowed_map: dict[str, str] = {}
    for allowed_value in allowed:
        allowed_map[allowed_value] = allowed_value
        allowed_map[allowed_value.upper()] = allowed_value
        allowed_map[allowed_value.lower()] = allowed_value
    normalized: list[str] = []
    for value in values:
        if value in allowed_map:
            normalized.append(allowed_map[value])
            continue
        raise ValueError(f"Unsupported selection value: {value!r}. Allowed values: {allowed}")
    return normalized


def experiment_hash(config: dict[str, Any]) -> str:
    payload = json.dumps(config, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


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
    if exit_profile not in {"atr_trailing_be"}:
        config["break_even"] = None
        config["break_even_mode"] = None
        config["break_even_buffer"] = None
        config["break_even_buffer_mode"] = None
    config["config_hash"] = experiment_hash(
        {
            "pair": pair,
            "timeframe": timeframe,
            "ma_types": list(ma_types),
            "ma_periods": list(ma_periods),
            "entry_type": entry_type,
            "exit_profile": exit_profile,
            "trailing_type_variant": trailing_type,
            "start_date": start_date,
            "end_date": end_date,
        }
    )
    return config


def iter_experiment_configs(*, pairs: list[str], timeframes: list[str], exit_profiles: list[str], start_date: str, end_date: str) -> Iterator[dict[str, Any]]:
    for pair in pairs:
        for timeframe in timeframes:
            for ma_periods in MA_PERIODS_2:
                for ma_types in MA_TYPES_2:
                    for entry_type in ENTRY_TYPES_2:
                        for exit_profile in exit_profiles:
                            if exit_profile in {"atr_trailing", "atr_trailing_be"}:
                                for trailing_type in TRAILING_TYPES:
                                    yield build_experiment_config(
                                        pair=pair,
                                        timeframe=timeframe,
                                        ma_types=ma_types,
                                        ma_periods=ma_periods,
                                        entry_type=entry_type,
                                        exit_profile=exit_profile,
                                        trailing_type=trailing_type,
                                        start_date=start_date,
                                        end_date=end_date,
                                    )
                            else:
                                yield build_experiment_config(
                                    pair=pair,
                                    timeframe=timeframe,
                                    ma_types=ma_types,
                                    ma_periods=ma_periods,
                                    entry_type=entry_type,
                                    exit_profile=exit_profile,
                                    trailing_type=None,
                                    start_date=start_date,
                                    end_date=end_date,
                                )
            for ma_periods in MA_PERIODS_3:
                for ma_types in MA_TYPES_3:
                    for entry_type in ENTRY_TYPES_3:
                        if entry_type == "crossover":
                            continue
                        for exit_profile in exit_profiles:
                            if exit_profile in {"atr_trailing", "atr_trailing_be"}:
                                for trailing_type in TRAILING_TYPES:
                                    yield build_experiment_config(
                                        pair=pair,
                                        timeframe=timeframe,
                                        ma_types=ma_types,
                                        ma_periods=ma_periods,
                                        entry_type=entry_type,
                                        exit_profile=exit_profile,
                                        trailing_type=trailing_type,
                                        start_date=start_date,
                                        end_date=end_date,
                                    )
                            else:
                                yield build_experiment_config(
                                    pair=pair,
                                    timeframe=timeframe,
                                    ma_types=ma_types,
                                    ma_periods=ma_periods,
                                    entry_type=entry_type,
                                    exit_profile=exit_profile,
                                    trailing_type=None,
                                    start_date=start_date,
                                    end_date=end_date,
                                )


def load_existing_results(results_path: Path) -> pd.DataFrame:
    if not results_path.exists():
        return pd.DataFrame()
    return pd.read_parquet(results_path)


def append_result_row(results_path: Path, row: dict[str, Any]) -> None:
    results_path.parent.mkdir(parents=True, exist_ok=True)
    if results_path.exists():
        existing = pd.read_parquet(results_path)
        updated = pd.concat([existing, pd.DataFrame([row])], ignore_index=True)
    else:
        updated = pd.DataFrame([row])
    updated.to_parquet(results_path, index=False)


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


def flatten_result(experiment: dict[str, Any], metrics: dict[str, Any], output_path: Path) -> dict[str, Any]:
    row = {
        **experiment,
        **metrics,
        "output_path": str(output_path),
        "ma_types_csv": ",".join(experiment["ma_types"]),
        "ma_periods_csv": ",".join(str(period) for period in experiment["ma_periods"]),
        "ma_count": len(experiment["ma_periods"]),
    }
    return row


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


def main() -> None:
    args = parse_args()
    results_path = Path(args.results_path).expanduser().resolve()
    failed_log_path = Path(args.failed_log_path).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    data_root = Path(args.data_root).expanduser().resolve()

    pairs = normalize_selection(args.pairs, PAIRS)
    timeframes = normalize_selection(args.timeframes, TIMEFRAMES)
    exit_profiles = normalize_selection(args.exit_profiles, EXIT_PROFILES)

    if args.overwrite_results and results_path.exists():
        results_path.unlink()

    existing_results = load_existing_results(results_path)
    completed_hashes = set(existing_results["config_hash"].tolist()) if "config_hash" in existing_results.columns else set()

    experiments = list(
        iter_experiment_configs(
            pairs=pairs,
            timeframes=timeframes,
            exit_profiles=exit_profiles,
            start_date=args.start_date,
            end_date=args.end_date,
        )
    )
    pending = [experiment for experiment in experiments if experiment["config_hash"] not in completed_hashes]
    if args.max_runs is not None:
        pending = pending[: args.max_runs]

    print(
        f"Experiment matrix: total={len(experiments)} completed={len(completed_hashes)} pending={len(pending)} "
        f"results={results_path}"
    )
    if not pending:
        print("No pending experiment configs. Resume is already up to date.")
        return

    current_cache_key: tuple[str, str] | None = None
    current_candles: pd.DataFrame | None = None

    for index, experiment in enumerate(pending, start=1):
        print(f"[{index}/{len(pending)}] {experiment_summary(experiment)}")
        try:
            cache_key = (experiment["pair"], experiment["timeframe"])
            if current_cache_key != cache_key or current_candles is None:
                current_candles = load_backtest_candles(
                    data_root=data_root,
                    pair=experiment["pair"],
                    timeframe=experiment["timeframe"],
                    start_date=experiment["start_date"],
                    end_date=experiment["end_date"],
                )
                current_cache_key = cache_key

            strategy = MAStrategy(
                ma_types=experiment["ma_types"],
                ma_periods=experiment["ma_periods"],
                entry_type=experiment["entry_type"],
                allow_long=experiment["allow_long"],
                allow_short=experiment["allow_short"],
            )
            signals = strategy.generate_signals(current_candles)
            config = build_backtest_config(experiment)
            result = run_backtest(current_candles, signals, config)
            output_path = save_backtest_result(result, output_root)
            row = flatten_result(experiment, result.metrics, output_path)
            append_result_row(results_path, row)
            completed_hashes.add(experiment["config_hash"])
        except Exception as exc:
            append_failed_run(
                failed_log_path,
                {
                    "config_hash": experiment["config_hash"],
                    "config": experiment,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
            )
            print(f"  failed: {exc}")


if __name__ == "__main__":
    main()
