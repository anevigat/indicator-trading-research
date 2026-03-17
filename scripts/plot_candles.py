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
    TradeOverlayOptions,
    create_candlestick_figure,
    format_warnings,
    load_processed_candles,
    load_trade_overlays,
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
    parser.add_argument("--trades-file", help="Optional parquet or csv trade overlay file.")
    parser.add_argument("--show-entries", action="store_true", help="Show trade entry markers.")
    parser.add_argument("--show-exits", action="store_true", help="Show trade exit markers.")
    parser.add_argument("--show-stop-loss", action="store_true", help="Show stop-loss lines when present.")
    parser.add_argument("--show-take-profit", action="store_true", help="Show take-profit lines when present.")
    parser.add_argument("--show-trade-lines", action="store_true", help="Show entry-to-exit trade lines.")
    parser.add_argument("--max-bars", type=int, default=5000, help="Maximum bars to plot before failing.")
    parser.add_argument("--truncate", action="store_true", help="Truncate to max-bars instead of failing.")
    return parser.parse_args()


def resolve_trade_options(args: argparse.Namespace) -> TradeOverlayOptions:
    any_toggle = any(
        [
            args.show_entries,
            args.show_exits,
            args.show_stop_loss,
            args.show_take_profit,
            args.show_trade_lines,
        ]
    )
    return TradeOverlayOptions(
        show_entries=args.show_entries or not any_toggle,
        show_exits=args.show_exits or not any_toggle,
        show_stop_loss=args.show_stop_loss,
        show_take_profit=args.show_take_profit,
        show_trade_lines=args.show_trade_lines,
    )


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
        trade_frame = None
        if args.trades_file:
            trade_frame, trade_warnings, trade_source = load_trade_overlays(
                trades_file=args.trades_file,
                pair=args.pair,
                timeframe=args.timeframe,
                start_date=args.start_date,
                end_date=args.end_date,
            )
            warnings.extend(trade_warnings)
            print(f"Loaded {len(trade_frame)} matching trades from {trade_source}")
        figure = create_candlestick_figure(
            frame,
            pair=args.pair,
            timeframe=args.timeframe,
            sma_windows=args.sma,
            ema_windows=args.ema,
            trades=trade_frame,
            trade_options=resolve_trade_options(args) if args.trades_file else None,
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
