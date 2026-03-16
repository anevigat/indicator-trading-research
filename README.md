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

The timeframe builder prefers cleaned tick parquet when available, then falls back to the lowest reliable bar timeframe already present in the source tree. It currently reads parquet input and writes deterministic Parquet outputs.

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

For large multi-year tick histories, run the builder pair-by-pair or with date bounds first. The Phase 1 validation run used a bounded smoke build for `EURUSD` and `GBPUSD` before attempting any broader rebuild.

## Notes

- The audit note at `docs/research/phase1_bootstrap_and_data_audit.md` is generated from the reusable audit script.
- The build utility does not ingest raw `.bi5` files in Phase 1; pairs that only exist in raw Dukascopy form remain flagged as missing normalized inputs.
- Any strategy implementation comes after the data layer is stable.
