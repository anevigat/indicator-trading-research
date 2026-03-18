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
    parser.add_argument("--stop-loss", type=float, default=None, help="Stop-loss distance or ATR multiple, depending on stop-loss mode.")
    parser.add_argument("--take-profit", type=float, default=None, help="Take-profit distance or ATR multiple, depending on take-profit mode.")
    parser.add_argument("--stop-loss-mode", choices=["absolute", "atr"], default=None, help="Stop-loss mode.")
    parser.add_argument("--take-profit-mode", choices=["absolute", "atr"], default=None, help="Take-profit mode.")
    parser.add_argument("--trailing-stop", type=float, default=None, help="Trailing-stop distance or ATR multiple, depending on trailing-stop mode.")
    parser.add_argument("--trailing-stop-mode", choices=["absolute", "atr"], default=None, help="Trailing-stop mode.")
    parser.add_argument("--trailing-type", choices=["standard", "chandelier"], default="standard", help="Trailing-stop implementation type.")
    parser.add_argument("--trailing-activation", type=float, default=None, help="Optional activation threshold for trailing stop.")
    parser.add_argument("--trailing-activation-mode", choices=["absolute", "atr"], default=None, help="Trailing-stop activation mode.")
    parser.add_argument("--chandelier-multiplier", type=float, default=None, help="ATR multiplier used for chandelier trailing.")
    parser.add_argument("--chandelier-atr-period", type=int, default=14, help="ATR period for chandelier trailing.")
    parser.add_argument("--chandelier-atr-method", choices=["wilder", "sma", "ema"], default="wilder", help="ATR method for chandelier trailing.")
    parser.add_argument("--break-even", type=float, default=None, help="Profit threshold for activating break-even stop.")
    parser.add_argument("--break-even-mode", choices=["absolute", "atr"], default=None, help="Break-even activation mode.")
    parser.add_argument("--break-even-buffer", type=float, default=None, help="Optional buffer added beyond entry when break-even activates.")
    parser.add_argument("--break-even-buffer-mode", choices=["absolute", "atr"], default=None, help="Break-even buffer mode.")
    parser.add_argument("--atr-period", type=int, default=14, help="ATR period used when any protection mode is 'atr'.")
    parser.add_argument("--atr-method", choices=["wilder", "sma", "ema"], default="wilder", help="ATR smoothing method.")
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
            stop_loss_mode=args.stop_loss_mode if args.stop_loss is not None else None,
            stop_loss=args.stop_loss,
            take_profit_mode=args.take_profit_mode if args.take_profit is not None else None,
            take_profit=args.take_profit,
            trailing_stop_mode=args.trailing_stop_mode if args.trailing_stop is not None else None,
            trailing_stop=args.trailing_stop,
            trailing_type=args.trailing_type,
            trailing_activation_mode=args.trailing_activation_mode if args.trailing_activation is not None else None,
            trailing_activation=args.trailing_activation,
            chandelier_multiplier=args.chandelier_multiplier,
            chandelier_atr_period=args.chandelier_atr_period,
            chandelier_atr_method=args.chandelier_atr_method,
            break_even_mode=args.break_even_mode if args.break_even is not None else None,
            break_even=args.break_even,
            break_even_buffer_mode=args.break_even_buffer_mode if args.break_even is not None or args.break_even_buffer is not None else None,
            break_even_buffer=args.break_even_buffer,
            atr_period=args.atr_period,
            atr_method=args.atr_method,
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
        f"win_rate={metrics['win_rate']:.2%} "
        f"net_pnl={metrics['net_pnl']:.6f} "
        f"profit_factor={metrics['profit_factor']} "
        f"max_drawdown={metrics['max_drawdown']:.6f} "
        f"stop_loss={config.stop_loss} "
        f"take_profit={config.take_profit} "
        f"stop_loss_mode={config.stop_loss_mode} "
        f"take_profit_mode={config.take_profit_mode} "
        f"trailing_type={config.trailing_type} "
        f"trailing_stop={config.trailing_stop} "
        f"trailing_stop_mode={config.trailing_stop_mode} "
        f"trailing_activation={config.trailing_activation} "
        f"trailing_activation_mode={config.trailing_activation_mode} "
        f"chandelier_multiplier={config.chandelier_multiplier} "
        f"chandelier_atr_period={config.chandelier_atr_period if config.trailing_type == 'chandelier' else 'n/a'} "
        f"chandelier_atr_method={config.chandelier_atr_method if config.trailing_type == 'chandelier' else 'n/a'} "
        f"break_even={config.break_even} "
        f"break_even_mode={config.break_even_mode} "
        f"break_even_buffer={config.break_even_buffer} "
        f"break_even_buffer_mode={config.break_even_buffer_mode} "
        f"atr_period={config.atr_period if any(mode == 'atr' for mode in (config.stop_loss_mode, config.take_profit_mode, config.trailing_stop_mode, config.trailing_activation_mode, config.break_even_mode, config.break_even_buffer_mode)) else 'n/a'} "
        f"atr_method={config.atr_method if any(mode == 'atr' for mode in (config.stop_loss_mode, config.take_profit_mode, config.trailing_stop_mode, config.trailing_activation_mode, config.break_even_mode, config.break_even_buffer_mode)) else 'n/a'} "
        f"output={output_path}"
    )


if __name__ == "__main__":
    main()
