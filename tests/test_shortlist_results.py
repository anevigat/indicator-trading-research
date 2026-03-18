from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "shortlist_results.py"
SPEC = importlib.util.spec_from_file_location("shortlist_results_module", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def make_results_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "strategy": "a",
                "total_trades": 250,
                "profit_factor": 1.50,
                "max_drawdown": -0.10,
                "win_rate": 0.45,
                "net_pnl": 0.20,
            },
            {
                "strategy": "b",
                "total_trades": 300,
                "profit_factor": 1.10,
                "max_drawdown": -0.20,
                "win_rate": 0.35,
                "net_pnl": 0.10,
            },
            {
                "strategy": "c",
                "total_trades": 100,
                "profit_factor": 2.00,
                "max_drawdown": -0.05,
                "win_rate": 0.60,
                "net_pnl": 0.30,
            },
            {
                "strategy": "d",
                "total_trades": 260,
                "profit_factor": 0.90,
                "max_drawdown": -0.08,
                "win_rate": 0.50,
                "net_pnl": 0.05,
            },
        ]
    )


def test_shortlist_filters_and_sorts_results() -> None:
    shortlist = MODULE.shortlist_dataframe(
        make_results_frame(),
        top=10,
        min_trades=200,
        min_profit_factor=1.03,
        max_drawdown=0.35,
        min_win_rate=0.30,
        sort_by="profit_factor",
    )

    assert shortlist["strategy"].tolist() == ["a", "b"]
    assert "rd_ratio" in shortlist.columns
    assert "avg_trade" in shortlist.columns


def test_shortlist_supports_fallback_column_names() -> None:
    df = pd.DataFrame(
        [
            {
                "strategy": "fallback",
                "trades": 250,
                "profit_factor": 1.25,
                "max_drawdown": -0.12,
                "win_rate_pct": 0.40,
                "net_pnl": 0.11,
            }
        ]
    )

    shortlist = MODULE.shortlist_dataframe(
        df,
        top=5,
        min_trades=200,
        min_profit_factor=1.03,
        max_drawdown=0.35,
        min_win_rate=0.30,
        sort_by="rd_ratio",
    )

    assert shortlist["strategy"].tolist() == ["fallback"]


def test_shortlist_raises_for_missing_required_columns() -> None:
    df = pd.DataFrame([{"total_trades": 250, "profit_factor": 1.2, "net_pnl": 0.1}])

    with pytest.raises(ValueError, match="Missing win rate column"):
        MODULE.shortlist_dataframe(
            df,
            top=5,
            min_trades=200,
            min_profit_factor=1.03,
            max_drawdown=0.35,
            min_win_rate=0.30,
            sort_by="profit_factor",
        )


def test_load_results_falls_back_for_partitioned_dataset(tmp_path: Path) -> None:
    dataset_path = tmp_path / "results.parquet"
    dataset_path.mkdir()
    pd.DataFrame(
        [
            {
                "strategy": "a",
                "total_trades": 250,
                "profit_factor": 1.50,
                "max_drawdown": -0.10,
                "win_rate": 0.45,
                "net_pnl": 0.20,
                "optional_metric": 1.0,
            }
        ]
    ).to_parquet(dataset_path / "part-000000.parquet", index=False)
    pd.DataFrame(
        [
            {
                "strategy": "b",
                "total_trades": 260,
                "profit_factor": 1.20,
                "max_drawdown": -0.15,
                "win_rate": 0.35,
                "net_pnl": 0.09,
            }
        ]
    ).to_parquet(dataset_path / "part-000001.parquet", index=False)

    loaded = MODULE.load_results(dataset_path)

    assert sorted(loaded["strategy"].tolist()) == ["a", "b"]
    assert "optional_metric" in loaded.columns


def test_print_only_does_not_write_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    input_path = tmp_path / "results.parquet"
    output_path = tmp_path / "shortlist.parquet"
    make_results_frame().to_parquet(input_path, index=False)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "shortlist_results.py",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--print-only",
        ],
    )

    MODULE.main()

    captured = capsys.readouterr()
    assert "strategy" in captured.out
    assert not output_path.exists()


def test_output_file_is_created_when_requested(tmp_path: Path) -> None:
    output_path = tmp_path / "shortlist.parquet"

    MODULE.save_shortlist(make_results_frame().head(2), output_path)

    assert output_path.exists()
    assert output_path.with_suffix(".csv").exists()


def test_empty_shortlist_prints_clean_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    input_path = tmp_path / "results.parquet"
    make_results_frame().to_parquet(input_path, index=False)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "shortlist_results.py",
            "--input",
            str(input_path),
            "--min-profit-factor",
            "9.99",
        ],
    )

    MODULE.main()

    captured = capsys.readouterr()
    assert "No strategies passed filters" in captured.out
