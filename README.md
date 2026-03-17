# indicator-trading-research

Indicator-focused FX research workspace for building normalized market datasets and evaluating technical signals. Phase 1 is limited to repository bootstrap, source-data audit, and reproducible timeframe generation.

## Phase 1 scope

- bootstrap the repository for indicator research
- audit the existing FX source data inventory
- identify missing pairs, timeframes, and coverage windows
- normalize research datasets into Parquet
- add permanent utility scripts for future audits and rebuilds

Strategy logic, backtesting, optimization, and live/paper trading are intentionally out of scope for this phase.

## Normalized data standard

Parquet is the normalized research data format from day one.

The Phase 1 build pipeline writes normalized bars to:

`data/processed/<PAIR>/<TIMEFRAME>/`

Each output parquet contains:

- `timestamp`
- `pair`
- `timeframe`
- `open`
- `high`
- `low`
- `close`
- `spread` when available
- `tick_count` when derivable from tick data
- `source_kind`
- `source_timeframe`

Current target pairs:

- `EURUSD`
- `USDJPY`
- `GBPUSD`
- `EURJPY`
- `AUDUSD`
- `USDCAD`

Current target timeframes:

- `1m`
- `5m`
- `15m`
- `30m`
- `1h`
- `4h`
- `1d`

## Environment setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If you need to refresh dependencies from scratch:

```bash
pip install pandas numpy pyarrow scipy matplotlib tqdm pyyaml pandas-ta
pip freeze > requirements.txt
```

## Data audit

The audit utility is a permanent project tool. It recursively inspects the source data tree, inventories structured datasets and raw Dukascopy roots, infers pairs/timeframes/coverage, and writes a markdown audit note.

```bash
source .venv/bin/activate
python scripts/audit_data_layout.py \
  --input-root ~/FX/eurusd-quant/eurusd_quant/data \
  --output-file docs/research/phase1_bootstrap_and_data_audit.md
```

## Timeframe build

The timeframe builder prefers cleaned tick parquet when available, then falls back to the lowest reliable bar timeframe already present in the source tree. It reads parquet input and writes deterministic Parquet outputs.

```bash
source .venv/bin/activate
python scripts/build_timeframes.py \
  --input-root ~/FX/eurusd-quant/eurusd_quant/data \
  --output-root data/processed
```

Useful subsets:

```bash
python scripts/build_timeframes.py \
  --input-root ~/FX/eurusd-quant/eurusd_quant/data \
  --output-root data/processed \
  --pairs EURUSD GBPUSD \
  --start-date 2025-01-01 \
  --end-date 2025-01-31
```

## Memory-Efficient Local Timeframe Builds

The builder was refactored for laptop-friendly execution because the earlier version materialized entire pair histories in pandas before resampling. The current implementation streams parquet fragments in bounded batches, keeps only a small carry-over buffer per timeframe, and writes final parquet outputs incrementally.

Recommended local pattern:

- build one pair at a time
- keep `--pair-workers 1` unless you have headroom
- start with a bounded date window
- use `--skip-existing` to resume safely
- use `--validate-only` after a build or before relying on existing outputs

Safest first command:

```bash
source .venv/bin/activate
python scripts/build_timeframes.py \
  --input-root ~/FX/eurusd-quant/eurusd_quant/data \
  --output-root data/processed \
  --pairs EURUSD \
  --timeframes 1m 5m \
  --start-date 2025-01-01 \
  --end-date 2025-01-07 \
  --batch-size 100000 \
  --pair-workers 1 \
  --overwrite \
  --sample-validate
```

Build one pair at a time:

```bash
python scripts/build_timeframes.py \
  --input-root ~/FX/eurusd-quant/eurusd_quant/data \
  --output-root data/processed \
  --pairs GBPUSD \
  --timeframes 1m 15m 1h \
  --start-date 2025-01-01 \
  --end-date 2025-03-31 \
  --batch-size 100000 \
  --pair-workers 1 \
  --overwrite
```

Resume safely:

```bash
python scripts/build_timeframes.py \
  --input-root ~/FX/eurusd-quant/eurusd_quant/data \
  --output-root data/processed \
  --pairs EURUSD \
  --timeframes 1m 5m \
  --start-date 2025-01-01 \
  --end-date 2025-01-07 \
  --batch-size 100000 \
  --pair-workers 1 \
  --skip-existing \
  --sample-validate
```

Validate outputs only:

```bash
python scripts/build_timeframes.py \
  --input-root ~/FX/eurusd-quant/eurusd_quant/data \
  --output-root data/processed \
  --pairs EURUSD \
  --timeframes 1m 5m \
  --validate-only
```

Aggressive parallelism is discouraged on laptops. The builder supports `--pair-workers`, but the safe default is sequential pair-by-pair execution.

The local wrapper script provides ready-to-run examples:

```bash
scripts/build_timeframes_local.sh single-pair EURUSD
scripts/build_timeframes_local.sh single-year GBPUSD 2025
scripts/build_timeframes_local.sh all-sequential
scripts/build_timeframes_local.sh validate EURUSD 1m 5m
scripts/build_timeframes_local.sh resume EURUSD
```

## Visual Validation Of Processed Candles

This exists so we can visually confirm that generated candles look correct across timeframes before we build more strategy logic on top of them. The plotting layer is intentionally lightweight and local-first, and the same framework is structured to accept future trade, stop, take-profit, and indicator overlays.

Generate a single chart:

```bash
source .venv/bin/activate
python scripts/plot_candles.py \
  --data-root data/processed \
  --pair EURUSD \
  --timeframe 15m \
  --start-date 2025-01-01 \
  --end-date 2025-01-05 \
  --sma 20 50 \
  --ema 9 21 \
  --output outputs/charts/eurusd_15m.html
```

Compare multiple timeframes for the same window:

```bash
python scripts/compare_timeframes.py \
  --data-root data/processed \
  --pair EURUSD \
  --timeframes 15m 1h 4h \
  --start-date 2025-01-01 \
  --end-date 2025-01-21 \
  --sma 20 \
  --output-dir outputs/charts/eurusd_compare
```

Safeguards:

- both plotting CLIs validate `timestamp`, `open`, `high`, `low`, and `close` before plotting
- warnings are surfaced for unsorted timestamps, duplicate timestamps, and missing OHLC values
- `--max-bars` defaults to a safe chart size and will fail unless `--truncate` is explicitly set

Future trade overlays will plug into the same `indicator_trading_research.visualization` package rather than requiring a redesign later.

## Notes

- The audit note at `docs/research/phase1_bootstrap_and_data_audit.md` is generated from the reusable audit script.
- The build utility does not ingest raw `.bi5` files in Phase 1; pairs that only exist in raw Dukascopy form remain flagged as missing normalized inputs.
- Any strategy implementation comes after the data layer is stable.
