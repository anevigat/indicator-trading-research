#!/usr/bin/env python3
"""Filter and shortlist experiment results."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

DEFAULT_TOP = 50
DEFAULT_MIN_TRADES = 200
DEFAULT_MIN_PROFIT_FACTOR = 1.03
DEFAULT_MAX_DRAWDOWN = 0.35
DEFAULT_MIN_WIN_RATE = 0.30
DEFAULT_SORT_BY = "profit_factor"
DISPLAY_COLUMNS = ["summary", "trades", "net_pnl", "win_rate", "profit_factor", "rd_ratio"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Input experiment parquet path.")
    parser.add_argument("--output", help="Optional shortlist output path (.parquet or .csv).")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP, help="Maximum number of rows to keep.")
    parser.add_argument("--min-trades", type=int, default=DEFAULT_MIN_TRADES, help="Minimum trade count.")
    parser.add_argument(
        "--min-profit-factor",
        type=float,
        default=DEFAULT_MIN_PROFIT_FACTOR,
        help="Minimum profit factor.",
    )
    parser.add_argument(
        "--max-drawdown",
        type=float,
        default=DEFAULT_MAX_DRAWDOWN,
        help="Maximum absolute drawdown allowed.",
    )
    parser.add_argument("--min-win-rate", type=float, default=DEFAULT_MIN_WIN_RATE, help="Minimum win rate.")
    parser.add_argument("--sort-by", default=DEFAULT_SORT_BY, help="Column to sort by.")
    parser.add_argument("--print-only", action="store_true", help="Print results without writing output files.")
    return parser.parse_args()


def load_results(input_path: Path) -> pd.DataFrame:
    try:
        return pd.read_parquet(input_path)
    except Exception:
        if not input_path.is_dir():
            raise

    parts = sorted(input_path.glob("*.parquet"))
    if not parts:
        raise FileNotFoundError(f"No parquet files found under dataset path: {input_path}")
    frames = [pd.read_parquet(part) for part in parts]
    return pd.concat(frames, ignore_index=True, sort=False)


def resolve_metric_columns(df: pd.DataFrame) -> tuple[str, str]:
    if "win_rate" in df.columns:
        win_col = "win_rate"
    elif "win_rate_pct" in df.columns:
        win_col = "win_rate_pct"
    else:
        raise ValueError("Missing win rate column. Expected one of: win_rate, win_rate_pct")

    if "total_trades" in df.columns:
        trades_col = "total_trades"
    elif "trades" in df.columns:
        trades_col = "trades"
    else:
        raise ValueError("Missing trade count column. Expected one of: total_trades, trades")

    return win_col, trades_col


def validate_columns(df: pd.DataFrame, sort_by: str) -> tuple[str, str]:
    win_col, trades_col = resolve_metric_columns(df)
    required_columns = {
        win_col,
        trades_col,
        "pair",
        "timeframe",
        "entry_type",
        "ma_types",
        "ma_periods",
        "exit_profile",
        "profit_factor",
        "max_drawdown",
        "net_pnl",
    }
    missing = sorted(column for column in required_columns if column not in df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    derived_sort_columns = {"rd_ratio", "avg_trade"}
    if sort_by not in df.columns and sort_by not in derived_sort_columns:
        raise ValueError(f"Missing sort column: {sort_by}")

    return win_col, trades_col


def apply_filters(
    df: pd.DataFrame,
    *,
    min_trades: int,
    min_profit_factor: float,
    max_drawdown: float,
    min_win_rate: float,
    win_col: str,
    trades_col: str,
) -> pd.DataFrame:
    return df[
        (df[trades_col] >= min_trades)
        & (df["profit_factor"] >= min_profit_factor)
        & (df["max_drawdown"] >= -max_drawdown)
        & (df[win_col] >= min_win_rate)
    ].copy()


def add_derived_metrics(df: pd.DataFrame, trades_col: str) -> pd.DataFrame:
    df["rd_ratio"] = df["net_pnl"] / df["max_drawdown"].abs().replace(0, pd.NA)
    df["avg_trade"] = df["net_pnl"] / df[trades_col].replace(0, pd.NA)
    return df


def build_summary(row: pd.Series) -> str:
    ma_types = "/".join(str(row["ma_types"]).split(","))
    ma_periods = "/".join(str(row["ma_periods"]).split(","))
    return f"{row['pair']} {row['timeframe']} {row['entry_type']} {ma_types} {ma_periods} exit={row['exit_profile']}"


def build_display_frame(df: pd.DataFrame) -> pd.DataFrame:
    win_col, trades_col = resolve_metric_columns(df)
    display = df.copy()
    display["summary"] = display.apply(build_summary, axis=1)
    display = display[
        [
            "summary",
            trades_col,
            "net_pnl",
            win_col,
            "profit_factor",
            "rd_ratio",
        ]
    ].copy()
    display = display.rename(columns={trades_col: "trades", win_col: "win_rate"})
    display["net_pnl"] = display["net_pnl"].round(6)
    display["win_rate"] = (display["win_rate"] * 100).round(2)
    display["profit_factor"] = display["profit_factor"].round(3)
    display["rd_ratio"] = display["rd_ratio"].round(3)
    return display[DISPLAY_COLUMNS]


def shortlist_dataframe(
    df: pd.DataFrame,
    *,
    top: int,
    min_trades: int,
    min_profit_factor: float,
    max_drawdown: float,
    min_win_rate: float,
    sort_by: str,
) -> pd.DataFrame:
    win_col, trades_col = validate_columns(df, sort_by)
    filtered = apply_filters(
        df,
        min_trades=min_trades,
        min_profit_factor=min_profit_factor,
        max_drawdown=max_drawdown,
        min_win_rate=min_win_rate,
        win_col=win_col,
        trades_col=trades_col,
    )
    if filtered.empty:
        return filtered

    filtered = add_derived_metrics(filtered, trades_col)
    if sort_by not in filtered.columns:
        raise ValueError(f"Missing sort column after derived metrics: {sort_by}")
    return filtered.sort_values(by=sort_by, ascending=False).head(top)


def save_shortlist(df: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".csv":
        df.to_csv(output_path, index=False)
        return

    df.to_parquet(output_path, index=False)
    if output_path.suffix.lower() == ".parquet":
        csv_path = output_path.with_suffix(".csv")
        df.to_csv(csv_path, index=False)


def main() -> None:
    args = parse_args()
    input_path = Path(args.input).expanduser()
    if not input_path.exists():
        raise FileNotFoundError(f"Input parquet not found: {input_path}")

    df = load_results(input_path)
    shortlist = shortlist_dataframe(
        df,
        top=args.top,
        min_trades=args.min_trades,
        min_profit_factor=args.min_profit_factor,
        max_drawdown=args.max_drawdown,
        min_win_rate=args.min_win_rate,
        sort_by=args.sort_by,
    )

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 200)

    if shortlist.empty:
        print("No strategies passed filters")
        return

    display = build_display_frame(shortlist)
    pd.set_option("display.max_rows", None)
    pd.set_option("display.width", 140)
    print(display.to_string(index=False, justify="left"))

    should_write = not args.print_only and args.output is not None
    if should_write:
        save_shortlist(shortlist, Path(args.output).expanduser())


if __name__ == "__main__":
    main()
