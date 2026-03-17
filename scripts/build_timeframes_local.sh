#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INPUT_ROOT="${INPUT_ROOT:-$HOME/FX/eurusd-quant/eurusd_quant/data}"
OUTPUT_ROOT="${OUTPUT_ROOT:-$ROOT_DIR/data/processed}"
TMP_DIR="${TMP_DIR:-/tmp/indicator-trading-research-timeframes}"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing virtualenv python at $PYTHON_BIN" >&2
  exit 1
fi

run_builder() {
  "$PYTHON_BIN" "$ROOT_DIR/scripts/build_timeframes.py" \
    --input-root "$INPUT_ROOT" \
    --output-root "$OUTPUT_ROOT" \
    --tmp-dir "$TMP_DIR" \
    --batch-size "${BATCH_SIZE:-100000}" \
    --pair-workers "${PAIR_WORKERS:-1}" \
    "$@"
}

show_help() {
  cat <<'EOF'
Usage: scripts/build_timeframes_local.sh <command> [args]

Commands:
  single-pair [PAIR]
    Build 1m, 5m, 15m for one pair over a bounded one-week window.

  single-year [PAIR] [YEAR]
    Build 1m, 5m, 15m, 1h for one pair over a single calendar year.

  all-sequential
    Build EURUSD, USDJPY, GBPUSD, EURJPY sequentially with conservative settings.

  validate [PAIR] [TIMEFRAMES...]
    Run validate-only against existing outputs.

  resume [PAIR]
    Re-run a bounded build with --skip-existing for safe resume behavior.

Examples:
  scripts/build_timeframes_local.sh single-pair EURUSD
  scripts/build_timeframes_local.sh single-year GBPUSD 2025
  scripts/build_timeframes_local.sh all-sequential
  scripts/build_timeframes_local.sh validate EURUSD 1m 5m
  scripts/build_timeframes_local.sh resume EURUSD
EOF
}

command="${1:-help}"

case "$command" in
  single-pair)
    pair="${2:-EURUSD}"
    run_builder \
      --pairs "$pair" \
      --timeframes 1m 5m 15m \
      --start-date "${START_DATE:-2025-01-01}" \
      --end-date "${END_DATE:-2025-01-07}" \
      --overwrite \
      --sample-validate
    ;;
  single-year)
    pair="${2:-EURUSD}"
    year="${3:-2025}"
    run_builder \
      --pairs "$pair" \
      --timeframes 1m 5m 15m 1h \
      --start-date "$year-01-01" \
      --end-date "$year-12-31" \
      --overwrite \
      --sample-validate
    ;;
  all-sequential)
    run_builder \
      --pairs EURUSD USDJPY GBPUSD EURJPY \
      --timeframes 1m 5m 15m 1h \
      --start-date "${START_DATE:-2025-01-01}" \
      --end-date "${END_DATE:-2025-03-31}" \
      --overwrite \
      --sample-validate
    ;;
  validate)
    pair="${2:-EURUSD}"
    shift 2 || true
    if [[ "$#" -eq 0 ]]; then
      set -- 1m 5m
    fi
    run_builder \
      --pairs "$pair" \
      --timeframes "$@" \
      --validate-only
    ;;
  resume)
    pair="${2:-EURUSD}"
    run_builder \
      --pairs "$pair" \
      --timeframes 1m 5m 15m \
      --start-date "${START_DATE:-2025-01-01}" \
      --end-date "${END_DATE:-2025-01-07}" \
      --skip-existing \
      --sample-validate
    ;;
  help|-h|--help)
    show_help
    ;;
  *)
    echo "Unknown command: $command" >&2
    echo >&2
    show_help >&2
    exit 1
    ;;
esac
