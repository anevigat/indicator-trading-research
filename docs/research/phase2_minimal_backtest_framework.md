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
- if an opposite signal is present, the engine closes the current trade and may flip into the new direction on that same next-bar open
- long entries buy at `next_open + spread/2 + slippage`
- long exits sell at `exit_price - spread/2 - slippage`
- short entries sell at `next_open - spread/2 - slippage`
- short exits buy at `exit_price + spread/2 + slippage`
- stop-loss and take-profit support two modes: `absolute` and `atr`
- `absolute` means a fixed price distance from the adjusted entry price
- `atr` means a multiple of ATR from the signal bar close, then frozen at entry for the life of the trade
- ATR uses standard true range: `max(high-low, abs(high-prev_close), abs(low-prev_close))`
- supported ATR smoothing methods are `wilder`, `sma`, and `ema`
- for a long trade, `stop_loss` is placed below entry and `take_profit` is placed above entry
- for a short trade, `stop_loss` is placed above entry and `take_profit` is placed below entry
- mixed modes are supported, for example ATR stop with absolute target or absolute stop with ATR target
- optional trailing stop support exists in Phase T1
- trailing stop supports two modes: `absolute` and `atr`
- Phase T2 also supports `chandelier` trailing and optional `break_even` stop logic
- trailing stop updates use close-only ratcheting after hit checks, so any newly tightened trail applies from the next bar onward
- long trailing update: `max(previous_trailing_stop, close - distance)`
- short trailing update: `min(previous_trailing_stop, close + distance)`
- if no activation threshold is configured, trailing becomes active immediately after entry
- if activation is configured, the engine checks activation using current bar range and then updates the trail after hit checks
- `trailing_activation_mode=atr` uses `atr_at_entry` as the activation reference
- `trailing_stop_mode=atr` uses live ATR on each update bar when ATR is available
- chandelier trailing uses highest-high / lowest-low since entry together with live ATR on each update bar
- long chandelier candidate: `highest_high_since_entry - chandelier_multiplier * ATR`
- short chandelier candidate: `lowest_low_since_entry + chandelier_multiplier * ATR`
- chandelier trailing still ratchets only in the favorable direction and still applies from the next bar because updates happen after hit checks
- if ATR is unavailable for ATR-based trailing updates, the trade stays open and trailing simply does not update on that bar
- break-even can be configured in `absolute` or `atr` mode
- break-even activation is checked using current bar range
- `break_even_mode=atr` uses `atr_at_entry` as the activation reference
- `break_even_buffer_mode=atr` also uses `atr_at_entry`
- when break-even activates, the stop moves to entry plus or minus the configured buffer and never loosens after activation
- intrabar stop-loss and take-profit checks are evaluated on the bar after entry has been established, including the entry bar itself
- if ATR is `NaN` on the signal bar because warmup is incomplete, that signal is skipped only when an entry-time ATR-dependent protection requires `atr_at_entry`
- the effective stop is the tightest active stop among static stop-loss, break-even, and trailing stop
- if both stop-side and take-profit are touched in the same bar, the engine uses the conservative deterministic rule: the active stop side is assumed to trigger first
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

`trades.parquet` includes an `exit_reason` field. Current values are:

- `signal_exit`
- `stop_loss`
- `break_even`
- `trailing_stop`
- `chandelier_trailing_stop`
- `take_profit`
- `forced_end`

When ATR mode is used, `trades.parquet` also includes `atr_at_entry`.

Phase T1 trailing adds these optional output fields:

- `trailing_stop_initial`
- `trailing_stop_final`
- `trailing_stop_exit_hit`
- `break_even_stop_price`
- `break_even_exit_hit`

## Connection To The Visualization Framework

`trades.parquet` is saved in the same normalized schema used by the chart overlay tools, so a completed backtest run can be visualized directly with `scripts/plot_candles.py`.

## Limitations

- only one strategy is implemented in Phase 2
- there is no optimization, walk-forward, or sweep framework yet
- there is no portfolio layer
- there is no partial-fill or order-book modeling
- trailing stop and chandelier updates are close-only in Phase T2
- there is no stepped trailing, break-even-to-trail handoff customization, or trailing-take-profit logic
- there is no higher-timeframe ATR support
- equity is tracked with realized equity plus close-based mark-to-market for an open position

## Next Recommended Extensions

- add more reference strategies behind the same signal contract
- add richer trailing variants only after the close-only baseline is stable
- add richer position sizing modes
- add parameter sweep tooling and experiment summaries
- add walk-forward evaluation and regime segmentation
