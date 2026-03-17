#!/usr/bin/env python3
"""Render a processed parquet candle chart to HTML."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from indicator_trading_research.visualization import (  # noqa: E402
    create_candlestick_figure,
    format_warnings,
    load_processed_candles,
    save_figure_html,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, help="Root processed data directory.")
    parser.add_argument("--pair", required=True, help="Pair to load, for example EURUSD.")
    parser.add_argument("--timeframe", required=True, help="Timeframe to plot, for example 15m.")
    parser.add_argument("--start-date", help="Optional UTC start date.")
    parser.add_argument("--end-date", help="Optional UTC end date.")
    parser.add_argument("--output", required=True, help="HTML output path.")
    parser.add_argument("--sma", nargs="*", type=int, default=[], help="Optional SMA windows.")
    parser.add_argument("--ema", nargs="*", type=int, default=[], help="Optional EMA windows.")
    parser.add_argument("--max-bars", type=int, default=5000, help="Maximum bars to plot before failing.")
    parser.add_argument("--truncate", action="store_true", help="Truncate to max-bars instead of failing.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        frame, warnings, source_path = load_processed_candles(
            data_root=args.data_root,
            pair=args.pair,
            timeframe=args.timeframe,
            start_date=args.start_date,
            end_date=args.end_date,
            max_bars=args.max_bars,
            truncate=args.truncate,
        )
        figure = create_candlestick_figure(
            frame,
            pair=args.pair,
            timeframe=args.timeframe,
            sma_windows=args.sma,
            ema_windows=args.ema,
        )
        output_path = save_figure_html(figure, args.output)
    except Exception as exc:
        print(f"plot_candles error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"Loaded {len(frame)} bars from {source_path}")
    if warnings:
        print("Warnings:")
        for warning in format_warnings(warnings):
            print(f"- {warning['code']}: {warning['message']} {warning['details']}")
    print(f"Chart saved to {output_path}")


if __name__ == "__main__":
    main()
