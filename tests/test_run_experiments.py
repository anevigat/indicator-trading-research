from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "run_experiments.py"
SPEC = importlib.util.spec_from_file_location("run_experiments_module", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_iter_experiment_configs_excludes_invalid_three_ma_crossover() -> None:
    configs = list(
        MODULE.iter_experiment_configs(
            pairs=["EURUSD"],
            timeframes=["1h"],
            exit_profiles=["none", "atr_trailing"],
            start_date="2025-01-01",
            end_date="2025-02-15",
        )
    )

    assert configs
    assert all(
        not (len(config["ma_periods"]) == 3 and config["entry_type"] == "crossover")
        for config in configs
    )
    assert all(
        config["trailing_type_variant"] in {None, "standard", "chandelier"}
        for config in configs
    )
    assert all(
        config["trailing_type_variant"] is None
        if config["exit_profile"] == "none"
        else True
        for config in configs
    )


def test_experiment_hash_is_stable_for_equivalent_payloads() -> None:
    config_a = {"pair": "EURUSD", "timeframe": "1h", "ma_types": ["ema", "sma"], "ma_periods": [20, 50]}
    config_b = {"ma_periods": [20, 50], "ma_types": ["ema", "sma"], "timeframe": "1h", "pair": "EURUSD"}

    assert MODULE.experiment_hash(config_a) == MODULE.experiment_hash(config_b)


def test_append_result_row_round_trips_parquet(tmp_path: Path) -> None:
    results_path = tmp_path / "ma_matrix.parquet"

    MODULE.append_result_row(results_path, {"config_hash": "a", "net_pnl": 1.23})
    MODULE.append_result_row(results_path, {"config_hash": "b", "net_pnl": 4.56})

    frame = pd.read_parquet(results_path)
    assert list(frame["config_hash"]) == ["a", "b"]
    assert list(frame["net_pnl"]) == [1.23, 4.56]


def test_normalize_selection_supports_case_insensitive_pairs_and_exact_timeframes() -> None:
    assert MODULE.normalize_selection(["eurusd", "USDJPY"], MODULE.PAIRS) == ["EURUSD", "USDJPY"]
    assert MODULE.normalize_selection(["1h", "4h"], MODULE.TIMEFRAMES) == ["1h", "4h"]
