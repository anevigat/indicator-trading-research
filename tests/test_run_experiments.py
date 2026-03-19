from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

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
            experiment_version="v1",
        )
    )

    assert configs
    assert all(
        not (len(config["ma_periods"]) == 3 and config["entry_type"] == "crossover")
        for config in configs
    )
    assert all(config["version"] == "v1" for config in configs)
    assert all(
        config["trailing_type_variant"] in {None, "standard", "chandelier"}
        for config in configs
    )


def test_group_experiments_by_slice_preserves_order_and_hashes() -> None:
    configs = list(
        MODULE.iter_experiment_configs(
            pairs=["USDJPY", "EURUSD"],
            timeframes=["4h", "1h"],
            exit_profiles=["none"],
            start_date="2025-01-01",
            end_date="2025-02-15",
            experiment_version="v1",
        )
    )

    grouped = MODULE.group_experiments_by_slice(configs)

    grouped_hashes = [config["config_hash"] for _, slice_configs in grouped for config in slice_configs]
    assert grouped_hashes == [config["config_hash"] for config in configs]
    assert [slice_key[:2] for slice_key, _ in grouped] == [
        ("EURUSD", "1h"),
        ("EURUSD", "4h"),
        ("USDJPY", "1h"),
        ("USDJPY", "4h"),
    ]


def test_experiment_hash_changes_when_version_changes() -> None:
    config = {"pair": "EURUSD", "timeframe": "1h", "ma_types": ["ema", "sma"], "ma_periods": [20, 50]}

    assert MODULE.experiment_hash(config, "v1") != MODULE.experiment_hash(config, "v2")


def test_flush_result_buffer_writes_rows_to_dataset_directory(tmp_path: Path) -> None:
    output_path = tmp_path / "ma_matrix.parquet"
    rows = [
        {column: None for column in MODULE.RESULT_COLUMNS},
        {column: None for column in MODULE.RESULT_COLUMNS},
    ]
    rows[0]["config_hash"] = "a"
    rows[1]["config_hash"] = "b"

    next_index = MODULE.flush_result_buffer(output_path, rows, part_index=0)

    assert next_index == 1
    assert rows == []
    frame = pd.read_parquet(output_path)
    assert sorted(frame["config_hash"].tolist()) == ["a", "b"]


def test_load_completed_hashes_reads_only_written_hashes(tmp_path: Path) -> None:
    output_path = tmp_path / "ma_matrix.parquet"
    rows = [{column: None for column in MODULE.RESULT_COLUMNS}]
    rows[0]["config_hash"] = "hash-1"
    MODULE.flush_result_buffer(output_path, rows, part_index=0)

    assert MODULE.load_completed_hashes(output_path) == {"hash-1"}


def test_resume_skips_preexisting_config_hashes(tmp_path: Path) -> None:
    output_path = tmp_path / "ma_matrix.parquet"
    configs = list(
        MODULE.iter_experiment_configs(
            pairs=["EURUSD"],
            timeframes=["1h"],
            exit_profiles=["none"],
            start_date="2025-01-01",
            end_date="2025-01-15",
            experiment_version="v1",
        )
    )
    existing_hash = configs[0]["config_hash"]
    rows = [{column: None for column in MODULE.RESULT_COLUMNS}]
    rows[0]["config_hash"] = existing_hash
    MODULE.flush_result_buffer(output_path, rows, part_index=0)

    completed_hashes = MODULE.load_completed_hashes(output_path)
    pending = [config for config in configs if config["config_hash"] not in completed_hashes]

    assert len(pending) == len(configs) - 1
    assert all(config["config_hash"] != existing_hash for config in pending)


def test_build_strategy_cache_collects_unique_strategies_and_ma_keys() -> None:
    configs = [
        MODULE.build_experiment_config(
            pair="EURUSD",
            timeframe="1h",
            ma_types=("ema", "sma"),
            ma_periods=(20, 50),
            entry_type="crossover",
            exit_profile="none",
            trailing_type=None,
            start_date="2025-01-01",
            end_date="2025-02-15",
            experiment_version="v1",
        ),
        MODULE.build_experiment_config(
            pair="EURUSD",
            timeframe="1h",
            ma_types=("ema", "sma"),
            ma_periods=(20, 50),
            entry_type="crossover_breakout",
            exit_profile="fixed1010",
            trailing_type=None,
            start_date="2025-01-01",
            end_date="2025-02-15",
            experiment_version="v1",
        ),
    ]

    strategies = MODULE.build_strategy_cache(configs)
    required_ma_keys = MODULE.collect_required_ma_keys(strategies)

    assert len(strategies) == 2
    assert required_ma_keys == {("ema", 20), ("sma", 50)}


def test_validate_metrics_file_rejects_missing_required_keys(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "metrics.json").write_text(json.dumps({"total_trades": 1, "net_pnl": 1.0}), encoding="utf-8")

    with pytest.raises(ValueError, match="metrics.json is missing required keys"):
        MODULE.validate_metrics_file(run_dir)


def test_append_failed_run_writes_timestamp_and_config(tmp_path: Path) -> None:
    failed_log_path = tmp_path / "failed_runs.jsonl"
    payload = {
        "config_hash": "abc",
        "config": {"pair": "EURUSD"},
        "error": "boom",
        "timestamp": "2026-01-01T00:00:00+00:00",
    }

    MODULE.append_failed_run(failed_log_path, payload)

    entries = failed_log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(entries) == 1
    parsed = json.loads(entries[0])
    assert parsed["config_hash"] == "abc"
    assert parsed["config"]["pair"] == "EURUSD"
    assert parsed["timestamp"] == "2026-01-01T00:00:00+00:00"


def test_normalize_selection_supports_case_insensitive_pairs_and_exact_timeframes() -> None:
    assert MODULE.normalize_selection(["eurusd", "USDJPY"], MODULE.PAIRS) == ["EURUSD", "USDJPY"]
    assert MODULE.normalize_selection(["1h", "4h"], MODULE.TIMEFRAMES) == ["1h", "4h"]


def test_parse_args_defaults_data_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_experiments.py",
            "--pairs",
            "EURUSD",
            "--timeframes",
            "1h",
        ],
    )

    args = MODULE.parse_args()

    assert args.data_root == "data/processed"


def test_flatten_result_keeps_expected_schema_columns() -> None:
    experiment = MODULE.build_experiment_config(
        pair="EURUSD",
        timeframe="1h",
        ma_types=("ema", "sma"),
        ma_periods=(20, 50),
        entry_type="crossover",
        exit_profile="none",
        trailing_type=None,
        start_date="2025-01-01",
        end_date="2025-02-15",
        experiment_version="v1",
    )
    metrics = {
        "total_trades": 10,
        "gross_pnl": 1.0,
        "net_pnl": 0.9,
        "win_rate": 0.5,
        "average_win": 0.2,
        "average_loss": -0.1,
        "profit_factor": 1.5,
        "expectancy": 0.09,
        "max_drawdown": -0.2,
        "ending_equity": 10000.9,
        "average_trade_duration_bars": 3.0,
        "long_trades_count": 5,
        "short_trades_count": 5,
        "stop_loss_exits": 1,
        "trailing_stop_exits": 0,
        "chandelier_trailing_exits": 0,
        "break_even_exits": 0,
        "ma_stop_exits": 0,
        "take_profit_exits": 1,
        "signal_exits": 8,
        "forced_end_exits": 0,
    }

    row = MODULE.flatten_result(
        experiment,
        metrics,
        Path("/tmp/run"),
        run_started_at="2026-01-01T00:00:00+00:00",
        run_duration_sec=1.23,
    )

    assert set(MODULE.RESULT_COLUMNS).issubset(row.keys())
