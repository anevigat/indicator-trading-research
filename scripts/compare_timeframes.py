#!/usr/bin/env python3
"""Generate comparable candle charts for multiple processed timeframes."""

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
    parser.add_argument("--pair", required=True, help="Pair to compare, for example EURUSD.")
    parser.add_argument("--timeframes", nargs="+", required=True, help="Timeframes to compare.")
    parser.add_argument("--start-date", help="Optional UTC start date.")
    parser.add_argument("--end-date", help="Optional UTC end date.")
    parser.add_argument("--output-dir", required=True, help="Directory for HTML outputs.")
    parser.add_argument("--sma", nargs="*", type=int, default=[], help="Optional SMA windows.")
    parser.add_argument("--ema", nargs="*", type=int, default=[], help="Optional EMA windows.")
    parser.add_argument("--max-bars", type=int, default=5000, help="Maximum bars to plot per chart before failing.")
    parser.add_argument("--truncate", action="store_true", help="Truncate to max-bars instead of failing.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    summaries: list[str] = []

    try:
        for timeframe in args.timeframes:
            frame, warnings, _ = load_processed_candles(
                data_root=args.data_root,
                pair=args.pair,
                timeframe=timeframe,
                start_date=args.start_date,
                end_date=args.end_date,
                max_bars=args.max_bars,
                truncate=args.truncate,
            )
            figure = create_candlestick_figure(
                frame,
                pair=args.pair,
                timeframe=timeframe,
                sma_windows=args.sma,
                ema_windows=args.ema,
            )
            output_path = output_dir / f"{args.pair.lower()}_{timeframe.lower()}.html"
            save_figure_html(figure, output_path)
            summaries.append(
                f"{timeframe}: bars={len(frame)} warnings={len(warnings)} output={output_path}"
            )
            if warnings:
                print(f"{timeframe} warnings:")
                for warning in format_warnings(warnings):
                    print(f"- {warning['code']}: {warning['message']} {warning['details']}")
    except Exception as exc:
        print(f"compare_timeframes error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print("Compare summary")
    for summary in summaries:
        print(f"- {summary}")


if __name__ == "__main__":
    main()
