#!/usr/bin/env python3
"""Run a minimal backtest and save standardized outputs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

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
from indicator_trading_research.strategies import SMACrossoverStrategy  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, help="Root processed data directory.")
    parser.add_argument("--pair", required=True, help="Pair to backtest, for example EURUSD.")
    parser.add_argument("--timeframe", required=True, help="Timeframe to backtest, for example 15m.")
    parser.add_argument("--strategy", required=True, choices=["sma_crossover"], help="Strategy to run.")
    parser.add_argument("--start-date", required=True, help="UTC start date.")
    parser.add_argument("--end-date", required=True, help="UTC end date.")
    parser.add_argument("--short-window", type=int, required=True, help="Short SMA window.")
    parser.add_argument("--long-window", type=int, required=True, help="Long SMA window.")
    parser.add_argument("--initial-capital", type=float, required=True, help="Initial capital.")
    parser.add_argument("--fixed-position-size", type=float, required=True, help="Fixed position size.")
    parser.add_argument("--spread", type=float, default=0.0, help="Absolute spread in price units.")
    parser.add_argument("--slippage", type=float, default=0.0, help="Absolute slippage in price units.")
    parser.add_argument("--output-root", required=True, help="Root directory for saved backtest outputs.")
    parser.add_argument("--fee-per-trade", type=float, default=0.0, help="Flat fee applied per completed trade.")
    parser.add_argument("--allow-long", dest="allow_long", action="store_true", help="Allow long trades.")
    parser.add_argument("--no-allow-long", dest="allow_long", action="store_false", help="Disable long trades.")
    parser.add_argument("--allow-short", dest="allow_short", action="store_true", help="Allow short trades.")
    parser.add_argument("--no-allow-short", dest="allow_short", action="store_false", help="Disable short trades.")
    parser.set_defaults(allow_long=True, allow_short=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        candles = load_backtest_candles(
            data_root=args.data_root,
            pair=args.pair,
            timeframe=args.timeframe,
            start_date=args.start_date,
            end_date=args.end_date,
        )

        if args.strategy == "sma_crossover":
            strategy = SMACrossoverStrategy(
                short_window=args.short_window,
                long_window=args.long_window,
                allow_long=args.allow_long,
                allow_short=args.allow_short,
            )
        else:
            raise ValueError(f"Unsupported strategy: {args.strategy}")

        signals = strategy.generate_signals(candles)
        config = BacktestConfig(
            pair=args.pair.upper(),
            timeframe=args.timeframe.lower(),
            strategy_name=strategy.strategy_name,
            start_date=args.start_date,
            end_date=args.end_date,
            initial_capital=args.initial_capital,
            fixed_position_size=args.fixed_position_size,
            strategy_params={
                "short_window": args.short_window,
                "long_window": args.long_window,
            },
            spread=args.spread,
            slippage=args.slippage,
            fee_per_trade=args.fee_per_trade,
            allow_long=args.allow_long,
            allow_short=args.allow_short,
        )
        result = run_backtest(candles, signals, config)
        output_path = save_backtest_result(result, args.output_root)
    except Exception as exc:
        print(f"run_backtest error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    metrics = result.metrics
    print(
        "Backtest summary: "
        f"trades={metrics['total_trades']} "
        f"net_pnl={metrics['net_pnl']:.6f} "
        f"profit_factor={metrics['profit_factor']} "
        f"max_drawdown={metrics['max_drawdown']:.6f} "
        f"output={output_path}"
    )


if __name__ == "__main__":
    main()

