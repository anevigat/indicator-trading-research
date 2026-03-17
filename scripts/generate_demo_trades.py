#!/usr/bin/env python3
"""Generate deterministic synthetic trade overlays for chart demos."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from indicator_trading_research.visualization import load_processed_candles  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, help="Root processed data directory.")
    parser.add_argument("--pair", required=True, help="Pair to use for demo trades.")
    parser.add_argument("--timeframe", required=True, help="Timeframe to align trades against.")
    parser.add_argument("--start-date", required=True, help="UTC start date for the demo window.")
    parser.add_argument("--end-date", required=True, help="UTC end date for the demo window.")
    parser.add_argument("--output", required=True, help="Output parquet or csv path.")
    return parser.parse_args()


def build_demo_trades(frame: pd.DataFrame, pair: str, timeframe: str) -> pd.DataFrame:
    if len(frame) < 80:
        raise ValueError("Not enough candle rows to generate deterministic demo trades.")

    indices = [10, len(frame) // 4, len(frame) // 2, int(len(frame) * 0.75)]
    holding_periods = [8, 12, 10, 14]
    sides = ["long", "short", "long", "short"]
    trades = []

    for trade_number, (entry_index, duration, side) in enumerate(zip(indices, holding_periods, sides), start=1):
        exit_index = min(entry_index + duration, len(frame) - 1)
        entry_row = frame.iloc[entry_index]
        exit_row = frame.iloc[exit_index]
        candle_range = max(entry_row["high"] - entry_row["low"], 1e-6)

        if side == "long":
            stop_loss = entry_row["low"] - candle_range * 0.4
            take_profit = entry_row["close"] + candle_range * 1.2
            pnl = exit_row["close"] - entry_row["close"]
        else:
            stop_loss = entry_row["high"] + candle_range * 0.4
            take_profit = entry_row["close"] - candle_range * 1.2
            pnl = entry_row["close"] - exit_row["close"]

        outcome = "win" if pnl > 0 else "loss" if pnl < 0 else "breakeven"
        trades.append(
            {
                "trade_id": f"demo_{pair.lower()}_{timeframe.lower()}_{trade_number}",
                "pair": pair.upper(),
                "timeframe": timeframe.lower(),
                "side": side,
                "entry_time": entry_row["timestamp"],
                "entry_price": float(entry_row["close"]),
                "exit_time": exit_row["timestamp"],
                "exit_price": float(exit_row["close"]),
                "stop_loss": float(stop_loss),
                "take_profit": float(take_profit),
                "size": 1.0,
                "pnl": float(pnl),
                "outcome": outcome,
                "strategy_name": "synthetic_demo",
                "notes": "Synthetic demo trade for overlay testing.",
            }
        )

    return pd.DataFrame(trades)


def write_output(frame: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".parquet":
        frame.to_parquet(output_path, index=False)
        return
    if output_path.suffix.lower() == ".csv":
        frame.to_csv(output_path, index=False)
        return
    raise ValueError("Output path must end with .parquet or .csv")


def main() -> None:
    args = parse_args()
    try:
        candles, warnings, source_path = load_processed_candles(
            data_root=args.data_root,
            pair=args.pair,
            timeframe=args.timeframe,
            start_date=args.start_date,
            end_date=args.end_date,
            max_bars=1_000_000,
            truncate=False,
        )
        trades = build_demo_trades(candles, args.pair, args.timeframe)
        output_path = Path(args.output).expanduser().resolve()
        write_output(trades, output_path)
    except Exception as exc:
        print(f"generate_demo_trades error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"Loaded {len(candles)} candles from {source_path}")
    if warnings:
        print(f"Candle warnings carried into demo generation: {len(warnings)}")
    print(f"Wrote {len(trades)} synthetic demo trades to {output_path}")


if __name__ == "__main__":
    main()
