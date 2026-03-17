# Trade Overlay Schema

## Purpose

This schema defines the normalized trade/event data consumed by the candle visualization layer for chart overlays. It is intended for candle validation, backtest debugging, and later paper-trading review.

## Supported file formats

- Parquet preferred
- CSV also supported

## Required columns

- `trade_id`
  Stable unique identifier for a trade row.
- `side`
  `long` or `short`.
- `entry_time`
  UTC timestamp for the entry marker.
- `entry_price`
  Entry price used for plotting.

## Strongly recommended normalized columns

- `pair`
  Instrument symbol such as `EURUSD`.
- `timeframe`
  Candle timeframe such as `15m` or `1h`.

If these are missing, the current plotting CLI assumes the requested chart pair and timeframe and emits a warning.

## Optional columns

- `exit_time`
  UTC timestamp for the exit marker.
- `exit_price`
  Exit price used for plotting. If `exit_time` exists without `exit_price`, the row is downgraded to entry-only plotting.
- `stop_loss`
  Optional stop-loss price for a light horizontal overlay.
- `take_profit`
  Optional take-profit price for a light horizontal overlay.
- `size`
  Optional position size.
- `pnl`
  Optional realized or marked PnL.
- `outcome`
  Optional categorical outcome such as `win`, `loss`, or `breakeven`.
- `strategy_name`
  Optional strategy identifier.
- `notes`
  Optional free-form notes.

## Timestamp semantics

- Timestamps should be stored in UTC.
- ISO-8601 is preferred for CSV input.
- `entry_time` and `exit_time` are treated as point markers at the exact timestamps provided.
- Trade lines span from `entry_time` to `exit_time`.
- Stop-loss and take-profit guide lines span from `entry_time` to `exit_time` when an exit exists, otherwise to the right edge of the current chart.

## Validation rules

- required columns must exist
- `side` must be `long` or `short`
- `entry_time` must parse correctly
- `entry_price` must be non-null and numeric
- `entry_time <= exit_time` when both exist
- `pair` and `timeframe`, when present, must match the requested chart
- malformed rows are skipped with explicit warnings rather than plotted silently

## Suggested normalized schema

| column | required | dtype suggestion | notes |
| --- | --- | --- | --- |
| `trade_id` | yes | string | unique row id |
| `pair` | recommended | string | chart filter key |
| `timeframe` | recommended | string | chart filter key |
| `side` | yes | string | `long` / `short` |
| `entry_time` | yes | timestamp | UTC |
| `entry_price` | yes | float | required for marker |
| `exit_time` | no | timestamp | UTC |
| `exit_price` | no | float | required for exit marker |
| `stop_loss` | no | float | optional |
| `take_profit` | no | float | optional |
| `size` | no | float | optional |
| `pnl` | no | float | optional |
| `outcome` | no | string | `win` / `loss` / `breakeven` |
| `strategy_name` | no | string | optional |
| `notes` | no | string | optional |
