# Phase 2 Minimal Backtest Framework

## Objective

Establish a small reusable backtesting layer on top of processed parquet candles so future strategy research can share one strategy contract, one execution contract, one trade schema, and one output layout.

## Scope Of The V1 Engine

- one strategy interface that returns close-of-bar signals
- next-bar execution only
- one open position at a time
- long and short support
- fixed-size position sizing
- optional spread, slippage, and flat fee assumptions
- optional stop-loss / take-profit hooks in the config contract
- deterministic outputs saved to a standardized run folder
- one complete reference strategy: `sma_crossover`

## Explicit Assumptions

- signals are generated using information available up to the signal bar close
- the engine executes entries and opposite-signal exits on the next bar open
- long entries buy at `next_open + spread/2 + slippage`
- long exits sell at `exit_price - spread/2 - slippage`
- short entries sell at `next_open - spread/2 - slippage`
- short exits buy at `exit_price + spread/2 + slippage`
- if both stop-loss and take-profit are touched in the same bar, the engine uses the conservative deterministic rule: stop-loss is assumed to trigger first
- if a position is still open at the end of the data window, it is closed on the final bar close using the configured execution adjustments

## Output Contracts

Outputs are written to:

`outputs/backtests/<strategy_name>/<pair>/<timeframe>/<run_id>/`

Each run folder contains:

- `config.json`
- `metrics.json`
- `trades.parquet`
- `signals.parquet`
- `equity_curve.parquet`

The `run_id` is deterministic from the serialized config payload so repeated identical runs land in the same path.

## Connection To The Visualization Framework

`trades.parquet` is saved in the same normalized schema used by the chart overlay tools, so a completed backtest run can be visualized directly with `scripts/plot_candles.py`.

## Limitations

- only one strategy is implemented in Phase 2
- there is no optimization, walk-forward, or sweep framework yet
- there is no portfolio layer
- there is no partial-fill or order-book modeling
- stop-loss and take-profit config fields are defined, but the CLI does not expose them yet
- equity is tracked with realized equity plus close-based mark-to-market for an open position

## Next Recommended Extensions

- add more reference strategies behind the same signal contract
- expose stop-loss and take-profit configuration via the CLI
- add richer position sizing modes
- add parameter sweep tooling and experiment summaries
- add walk-forward evaluation and regime segmentation
