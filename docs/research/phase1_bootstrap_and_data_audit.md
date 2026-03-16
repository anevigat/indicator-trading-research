# Phase 1 Bootstrap And Data Audit

## Objective

Establish a clean starting point for `indicator-trading-research`, audit the existing FX source data tree at `/Users/anevigat/FX/eurusd-quant/eurusd_quant/data`, and define a reproducible path to normalized Parquet timeframe datasets.

## Assumptions

- Target pairs: EURUSD, USDJPY, GBPUSD, EURJPY, AUDUSD, USDCAD
- Target timeframes: 1m, 5m, 15m, 30m, 1h, 4h, 1d
- Coverage checks compare observed years against `2018-2024` and `2025-now`.
- Structured parquet files are inspected directly; large parquet timestamp ranges may use first/last row-group boundaries when a full scan would be unnecessarily expensive.
- Raw Dukascopy `.bi5` trees are summarized by root and year coverage instead of expanding every hourly file path into this markdown report.
- Phase 1 timeframe generation reads parquet sources only and does not decode `.bi5` files.

## Existing Data Inventory

Structured files discovered: 83

- `bars/15m/eurjpy_bars_15m_2018_2024.parquet` | pair=EURJPY | timeframe=15m | rows=173642 | coverage=2018-01-01T22:00:00+00:00 -> 2024-12-31T21:45:00+00:00
- `bars/15m/eurjpy_bars_15m_2018_2024_raw.parquet` | pair=EURJPY | timeframe=15m | rows=173642 | coverage=2018-01-01T22:00:00+00:00 -> 2024-12-31T21:45:00+00:00
- `bars/15m/eurjpy_bars_15m_2018_2024_report.json` | pair=EURJPY | timeframe=15m | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `bars/15m/eurjpy_bars_15m_2025_now.parquet` | pair=EURJPY | timeframe=15m | rows=29659 | coverage=2025-01-01T22:00:00+00:00 -> 2026-03-15T23:45:00+00:00
- `bars/15m/eurjpy_bars_15m_2025_now_raw.parquet` | pair=EURJPY | timeframe=15m | rows=29659 | coverage=2025-01-01T22:00:00+00:00 -> 2026-03-15T23:45:00+00:00
- `bars/15m/eurjpy_bars_15m_2025_now_report.json` | pair=EURJPY | timeframe=15m | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `bars/15m/eurusd_bars_15m_2018.parquet` | pair=EURUSD | timeframe=15m | rows=24905 | coverage=2018-01-01T22:00:00+00:00 -> 2018-12-31T22:00:00+00:00
- `bars/15m/eurusd_bars_15m_2018_2024.parquet` | pair=EURUSD | timeframe=15m | rows=174603 | coverage=2018-01-01T22:00:00+00:00 -> 2024-12-31T21:45:00+00:00
- `bars/15m/eurusd_bars_15m_2018_raw.parquet` | pair=EURUSD | timeframe=15m | rows=24905 | coverage=2018-01-01T22:00:00+00:00 -> 2018-12-31T22:00:00+00:00
- `bars/15m/eurusd_bars_15m_2018_report.json` | pair=EURUSD | timeframe=15m | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `bars/15m/eurusd_bars_15m_2019.parquet` | pair=EURUSD | timeframe=15m | rows=24890 | coverage=2019-01-01T22:00:00+00:00 -> 2019-12-31T21:45:00+00:00
- `bars/15m/eurusd_bars_15m_2019_raw.parquet` | pair=EURUSD | timeframe=15m | rows=24890 | coverage=2019-01-01T22:00:00+00:00 -> 2019-12-31T21:45:00+00:00
- `bars/15m/eurusd_bars_15m_2019_report.json` | pair=EURUSD | timeframe=15m | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `bars/15m/eurusd_bars_15m_2020.parquet` | pair=EURUSD | timeframe=15m | rows=24999 | coverage=2020-01-01T22:00:00+00:00 -> 2020-12-31T21:45:00+00:00
- `bars/15m/eurusd_bars_15m_2020_raw.parquet` | pair=EURUSD | timeframe=15m | rows=24999 | coverage=2020-01-01T22:00:00+00:00 -> 2020-12-31T21:45:00+00:00
- `bars/15m/eurusd_bars_15m_2020_report.json` | pair=EURUSD | timeframe=15m | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `bars/15m/eurusd_bars_15m_2021.parquet` | pair=EURUSD | timeframe=15m | rows=24959 | coverage=2021-01-03T22:00:00+00:00 -> 2021-12-31T21:45:00+00:00
- `bars/15m/eurusd_bars_15m_2021_raw.parquet` | pair=EURUSD | timeframe=15m | rows=24959 | coverage=2021-01-03T22:00:00+00:00 -> 2021-12-31T21:45:00+00:00
- `bars/15m/eurusd_bars_15m_2021_report.json` | pair=EURUSD | timeframe=15m | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `bars/15m/eurusd_bars_15m_2022.parquet` | pair=EURUSD | timeframe=15m | rows=24960 | coverage=2022-01-02T22:00:00+00:00 -> 2022-12-30T21:45:00+00:00
- `bars/15m/eurusd_bars_15m_2022_raw.parquet` | pair=EURUSD | timeframe=15m | rows=24960 | coverage=2022-01-02T22:00:00+00:00 -> 2022-12-30T21:45:00+00:00
- `bars/15m/eurusd_bars_15m_2022_report.json` | pair=EURUSD | timeframe=15m | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `bars/15m/eurusd_bars_15m_2023.parquet` | pair=EURUSD | timeframe=15m | rows=24896 | coverage=2023-01-01T22:00:00+00:00 -> 2023-12-29T21:45:00+00:00
- `bars/15m/eurusd_bars_15m_2023_raw.parquet` | pair=EURUSD | timeframe=15m | rows=24896 | coverage=2023-01-01T22:00:00+00:00 -> 2023-12-29T21:45:00+00:00
- `bars/15m/eurusd_bars_15m_2023_report.json` | pair=EURUSD | timeframe=15m | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `bars/15m/eurusd_bars_15m_2024.parquet` | pair=EURUSD | timeframe=15m | rows=24994 | coverage=2024-01-01T22:00:00+00:00 -> 2024-12-31T21:45:00+00:00
- `bars/15m/eurusd_bars_15m_2024_raw.parquet` | pair=EURUSD | timeframe=15m | rows=24994 | coverage=2024-01-01T22:00:00+00:00 -> 2024-12-31T21:45:00+00:00
- `bars/15m/eurusd_bars_15m_2024_report.json` | pair=EURUSD | timeframe=15m | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `bars/15m/eurusd_bars_15m_2025_now.parquet` | pair=EURUSD | timeframe=15m | rows=29520 | coverage=2025-01-01T22:00:00+00:00 -> 2026-03-10T23:45:00+00:00
- `bars/15m/eurusd_bars_15m_2025_now_raw.parquet` | pair=EURUSD | timeframe=15m | rows=29520 | coverage=2025-01-01T22:00:00+00:00 -> 2026-03-10T23:45:00+00:00
- `bars/15m/eurusd_bars_15m_2025_now_report.json` | pair=EURUSD | timeframe=15m | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `bars/15m/eurusd_bars_15m_recent.parquet` | pair=EURUSD | timeframe=15m | rows=440 | coverage=2026-03-10T00:00:00+00:00 -> 2026-03-16T14:45:00+00:00
- `bars/15m/eurusd_bars_15m_recent_raw.parquet` | pair=EURUSD | timeframe=15m | rows=440 | coverage=2026-03-10T00:00:00+00:00 -> 2026-03-16T14:45:00+00:00
- `bars/15m/eurusd_bars_15m_recent_report.json` | pair=EURUSD | timeframe=15m | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `bars/15m/eurusd_bars_latest.parquet` | pair=EURUSD | timeframe=15m | rows=820 | coverage=2024-12-31T00:00:00+00:00 -> 2026-03-16T14:45:00+00:00
- `bars/15m/gbpusd_bars_15m_2018_2024.parquet` | pair=GBPUSD | timeframe=15m | rows=174182 | coverage=2018-01-01T22:00:00+00:00 -> 2024-12-31T21:45:00+00:00
- `bars/15m/gbpusd_bars_15m_2018_2024_raw.parquet` | pair=GBPUSD | timeframe=15m | rows=174182 | coverage=2018-01-01T22:00:00+00:00 -> 2024-12-31T21:45:00+00:00
- `bars/15m/gbpusd_bars_15m_2018_2024_report.json` | pair=GBPUSD | timeframe=15m | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `bars/15m/gbpusd_bars_15m_2025_now.parquet` | pair=GBPUSD | timeframe=15m | rows=29572 | coverage=2025-01-01T22:00:00+00:00 -> 2026-03-12T23:45:00+00:00
- `bars/15m/gbpusd_bars_15m_2025_now_raw.parquet` | pair=GBPUSD | timeframe=15m | rows=29572 | coverage=2025-01-01T22:00:00+00:00 -> 2026-03-12T23:45:00+00:00
- `bars/15m/gbpusd_bars_15m_2025_now_report.json` | pair=GBPUSD | timeframe=15m | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `bars/15m/usdjpy_bars_15m_2018_2024.parquet` | pair=USDJPY | timeframe=15m | rows=173659 | coverage=2018-01-01T22:00:00+00:00 -> 2024-12-31T21:45:00+00:00
- `bars/15m/usdjpy_bars_15m_2018_2024_raw.parquet` | pair=USDJPY | timeframe=15m | rows=173659 | coverage=2018-01-01T22:00:00+00:00 -> 2024-12-31T21:45:00+00:00
- `bars/15m/usdjpy_bars_15m_2018_2024_report.json` | pair=USDJPY | timeframe=15m | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `bars/15m/usdjpy_bars_15m_2025_now.parquet` | pair=USDJPY | timeframe=15m | rows=29659 | coverage=2025-01-01T22:00:00+00:00 -> 2026-03-13T20:45:00+00:00
- `bars/15m/usdjpy_bars_15m_2025_now_raw.parquet` | pair=USDJPY | timeframe=15m | rows=29659 | coverage=2025-01-01T22:00:00+00:00 -> 2026-03-13T20:45:00+00:00
- `bars/15m/usdjpy_bars_15m_2025_now_report.json` | pair=USDJPY | timeframe=15m | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `bars/1d/eurusd_bars_1d_2018_2024.parquet` | pair=EURUSD | timeframe=1d | rows=2190 | coverage=2018-01-01T00:00:00+00:00 -> 2024-12-31T00:00:00+00:00
- `bars/1d/gbpusd_bars_1d_2018_2024.parquet` | pair=GBPUSD | timeframe=1d | rows=2188 | coverage=2018-01-01T00:00:00+00:00 -> 2024-12-31T00:00:00+00:00
- `cleaned_ticks/EURJPY/2018_2024/eurjpy_ticks_2018_2024.parquet` | pair=EURJPY | timeframe=n/a | rows=322065633 | coverage=2018-01-01T22:01:00.850000+00:00 -> 2024-12-31T21:59:58.077000+00:00 | notes: timestamp coverage estimated from first/last row group boundaries
- `cleaned_ticks/EURJPY/2025_now/eurjpy_ticks_2025_now.parquet` | pair=EURJPY | timeframe=n/a | rows=57222404 | coverage=2025-01-01T22:11:10.788000+00:00 -> 2026-03-15T23:59:59.796000+00:00 | notes: timestamp coverage estimated from first/last row group boundaries
- `cleaned_ticks/EURUSD/2018/eurusd_ticks_2018.parquet` | pair=EURUSD | timeframe=n/a | rows=26048775 | coverage=2018-01-01T22:00:08.661000+00:00 -> 2018-12-31T22:00:03.048000+00:00
- `cleaned_ticks/EURUSD/2019/eurusd_ticks_2019.parquet` | pair=EURUSD | timeframe=n/a | rows=29186310 | coverage=2019-01-01T22:02:37.254000+00:00 -> 2019-12-31T21:59:57.829000+00:00
- `cleaned_ticks/EURUSD/2020/eurusd_ticks_2020.parquet` | pair=EURUSD | timeframe=n/a | rows=32763638 | coverage=2020-01-01T22:01:12.821000+00:00 -> 2020-12-31T21:59:59.120000+00:00 | notes: timestamp coverage estimated from first/last row group boundaries
- `cleaned_ticks/EURUSD/2021/eurusd_ticks_2021.parquet` | pair=EURUSD | timeframe=n/a | rows=16797607 | coverage=2021-01-03T22:00:00.040000+00:00 -> 2021-12-31T21:59:56.170000+00:00
- `cleaned_ticks/EURUSD/2022/eurusd_ticks_2022.parquet` | pair=EURUSD | timeframe=n/a | rows=36946763 | coverage=2022-01-02T22:03:54.650000+00:00 -> 2022-12-30T21:59:57.894000+00:00 | notes: timestamp coverage estimated from first/last row group boundaries
- `cleaned_ticks/EURUSD/2023/eurusd_ticks_2023.parquet` | pair=EURUSD | timeframe=n/a | rows=27545689 | coverage=2023-01-01T22:04:01.067000+00:00 -> 2023-12-29T21:59:59.385000+00:00
- `cleaned_ticks/EURUSD/2024/eurusd_ticks_2024.parquet` | pair=EURUSD | timeframe=n/a | rows=20686503 | coverage=2024-01-01T22:00:12.108000+00:00 -> 2024-12-31T21:59:58.249000+00:00
- `cleaned_ticks/EURUSD/2025_now/eurusd_ticks_2025_now.parquet` | pair=EURUSD | timeframe=n/a | rows=27257336 | coverage=2025-01-01T22:00:14.647000+00:00 -> 2026-03-10T23:59:55.121000+00:00
- `cleaned_ticks/EURUSD/eurusd_ticks_recent.parquet` | pair=EURUSD | timeframe=n/a | rows=490377 | coverage=2026-03-10T00:00:00.147000+00:00 -> 2026-03-16T14:59:57.224000+00:00
- `cleaned_ticks/GBPUSD/2018_2024/gbpusd_ticks_2018_2024.parquet` | pair=GBPUSD | timeframe=n/a | rows=204412177 | coverage=2018-01-01T22:00:07.594000+00:00 -> 2024-12-31T21:59:59.120000+00:00 | notes: timestamp coverage estimated from first/last row group boundaries
- `cleaned_ticks/GBPUSD/2025_now/gbpusd_ticks_2025_now.parquet` | pair=GBPUSD | timeframe=n/a | rows=29224098 | coverage=2025-01-01T22:01:23.324000+00:00 -> 2026-03-12T23:59:59.825000+00:00 | notes: timestamp coverage estimated from first/last row group boundaries
- `cleaned_ticks/USDJPY/2018_2024/usdjpy_ticks_2018_2024.parquet` | pair=USDJPY | timeframe=n/a | rows=203447687 | coverage=2018-01-01T22:00:13.088000+00:00 -> 2024-12-31T21:59:58.315000+00:00 | notes: timestamp coverage estimated from first/last row group boundaries
- `cleaned_ticks/USDJPY/2025_now/usdjpy_ticks_2025_now.parquet` | pair=USDJPY | timeframe=n/a | rows=39567605 | coverage=2025-01-01T22:04:01.721000+00:00 -> 2026-03-13T20:59:59.784000+00:00 | notes: timestamp coverage estimated from first/last row group boundaries
- `raw/dukascopy/download_manifest_2018.jsonl` | pair=n/a | timeframe=n/a | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `raw/dukascopy/download_manifest_2018_2024.jsonl` | pair=n/a | timeframe=n/a | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `raw/dukascopy/download_manifest_2019.jsonl` | pair=n/a | timeframe=n/a | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `raw/dukascopy/download_manifest_2020.jsonl` | pair=n/a | timeframe=n/a | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `raw/dukascopy/download_manifest_2020_2023.jsonl` | pair=n/a | timeframe=n/a | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `raw/dukascopy/download_manifest_2021.jsonl` | pair=n/a | timeframe=n/a | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `raw/dukascopy/download_manifest_2022.jsonl` | pair=n/a | timeframe=n/a | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `raw/dukascopy/download_manifest_2023.jsonl` | pair=n/a | timeframe=n/a | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `raw/dukascopy/download_manifest_2024.jsonl` | pair=n/a | timeframe=n/a | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `raw/dukascopy/download_manifest_2026.jsonl` | pair=n/a | timeframe=n/a | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `raw/dukascopy/download_manifest_AUDUSD_2018_2024.jsonl` | pair=AUDUSD | timeframe=n/a | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `raw/dukascopy/download_manifest_EURJPY_2018_2024.jsonl` | pair=EURJPY | timeframe=n/a | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `raw/dukascopy/download_manifest_EURJPY_2025_now.jsonl` | pair=EURJPY | timeframe=n/a | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `raw/dukascopy/download_manifest_EURUSD_2025_now.jsonl` | pair=EURUSD | timeframe=n/a | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `raw/dukascopy/download_manifest_GBPUSD_2018_2024.jsonl` | pair=GBPUSD | timeframe=n/a | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `raw/dukascopy/download_manifest_GBPUSD_2025_now.jsonl` | pair=GBPUSD | timeframe=n/a | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `raw/dukascopy/download_manifest_USDJPY_2018_2024.jsonl` | pair=USDJPY | timeframe=n/a | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `raw/dukascopy/download_manifest_USDJPY_2025_now.jsonl` | pair=USDJPY | timeframe=n/a | rows=n/a | coverage=n/a | notes: timestamp range not inferred for this file type
- `ticks/clean/eurusd_ticks_2023.parquet` | pair=EURUSD | timeframe=n/a | rows=13475002 | coverage=2023-01-01T22:04:01.067000+00:00 -> 2023-06-22T18:59:59.626000+00:00

Raw Dukascopy roots discovered: 9

- `raw/dukascopy/AUDUSD_2018_2024` | pair=AUDUSD | raw_files=18997 | years=2018, 2019, 2020, 2021 | first=raw/dukascopy/AUDUSD_2018_2024/2018/01/01/22h_ticks.bi5 | last=raw/dukascopy/AUDUSD_2018_2024/2021/02/08/00h_ticks.bi5
- `raw/dukascopy/EURJPY_2018_2024` | pair=EURJPY | raw_files=43417 | years=2018, 2019, 2020, 2021, 2022, 2023, 2024 | first=raw/dukascopy/EURJPY_2018_2024/2018/01/01/22h_ticks.bi5 | last=raw/dukascopy/EURJPY_2018_2024/2024/12/31/21h_ticks.bi5
- `raw/dukascopy/EURJPY_2025_now` | pair=EURJPY | raw_files=7417 | years=2025, 2026 | first=raw/dukascopy/EURJPY_2025_now/2025/01/01/22h_ticks.bi5 | last=raw/dukascopy/EURJPY_2025_now/2026/03/15/23h_ticks.bi5
- `raw/dukascopy/EURUSD` | pair=EURUSD | raw_files=43838 | years=2018, 2019, 2020, 2021, 2022, 2023, 2024, 2026 | first=raw/dukascopy/EURUSD/2018/01/01/22h_ticks.bi5 | last=raw/dukascopy/EURUSD/2026/03/16/14h_ticks.bi5
- `raw/dukascopy/EURUSD_2025_now` | pair=EURUSD | raw_files=7381 | years=2025, 2026 | first=raw/dukascopy/EURUSD_2025_now/2025/01/01/22h_ticks.bi5 | last=raw/dukascopy/EURUSD_2025_now/2026/03/10/23h_ticks.bi5
- `raw/dukascopy/GBPUSD_2018_2024` | pair=GBPUSD | raw_files=43549 | years=2018, 2019, 2020, 2021, 2022, 2023, 2024 | first=raw/dukascopy/GBPUSD_2018_2024/2018/01/01/22h_ticks.bi5 | last=raw/dukascopy/GBPUSD_2018_2024/2024/12/31/21h_ticks.bi5
- `raw/dukascopy/GBPUSD_2025_now` | pair=GBPUSD | raw_files=7394 | years=2025, 2026 | first=raw/dukascopy/GBPUSD_2025_now/2025/01/01/22h_ticks.bi5 | last=raw/dukascopy/GBPUSD_2025_now/2026/03/12/23h_ticks.bi5
- `raw/dukascopy/USDJPY_2018_2024` | pair=USDJPY | raw_files=43417 | years=2018, 2019, 2020, 2021, 2022, 2023, 2024 | first=raw/dukascopy/USDJPY_2018_2024/2018/01/01/22h_ticks.bi5 | last=raw/dukascopy/USDJPY_2018_2024/2024/12/31/21h_ticks.bi5
- `raw/dukascopy/USDJPY_2025_now` | pair=USDJPY | raw_files=7415 | years=2025, 2026 | first=raw/dukascopy/USDJPY_2025_now/2025/01/01/22h_ticks.bi5 | last=raw/dukascopy/USDJPY_2025_now/2026/03/13/20h_ticks.bi5

## Pair Summary

- `EURUSD` | structured_files=41 | usable_structured_files=31 | raw_roots=2 | direct_timeframes=15m, 1d | buildable_now=1m, 5m, 15m, 30m, 1h, 4h, 1d | missing_buildable=none | observed_years=2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026 | coverage=2018-01-01T00:00:00+00:00 -> 2026-03-16T14:59:57.224000+00:00
- `USDJPY` | structured_files=10 | usable_structured_files=6 | raw_roots=2 | direct_timeframes=15m | buildable_now=1m, 5m, 15m, 30m, 1h, 4h, 1d | missing_buildable=none | observed_years=2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026 | coverage=2018-01-01T22:00:00+00:00 -> 2026-03-13T20:59:59.784000+00:00
- `GBPUSD` | structured_files=11 | usable_structured_files=7 | raw_roots=2 | direct_timeframes=15m, 1d | buildable_now=1m, 5m, 15m, 30m, 1h, 4h, 1d | missing_buildable=none | observed_years=2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026 | coverage=2018-01-01T00:00:00+00:00 -> 2026-03-12T23:59:59.825000+00:00
- `EURJPY` | structured_files=10 | usable_structured_files=6 | raw_roots=2 | direct_timeframes=15m | buildable_now=1m, 5m, 15m, 30m, 1h, 4h, 1d | missing_buildable=none | observed_years=2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026 | coverage=2018-01-01T22:00:00+00:00 -> 2026-03-15T23:59:59.796000+00:00
- `AUDUSD` | structured_files=1 | usable_structured_files=0 | raw_roots=1 | direct_timeframes=none | buildable_now=none | missing_buildable=1m, 5m, 15m, 30m, 1h, 4h, 1d | observed_years=2018, 2019, 2020, 2021 | coverage=? -> ?
- `USDCAD` | structured_files=0 | usable_structured_files=0 | raw_roots=0 | direct_timeframes=none | buildable_now=none | missing_buildable=1m, 5m, 15m, 30m, 1h, 4h, 1d | observed_years=none | coverage=? -> ?

## Missing Pairs

- `USDCAD`

## Missing Timeframes

These are missing relative to what Phase 1 can build directly from the currently available cleaned parquet or prebuilt bar sources.

- `AUDUSD` missing buildable timeframes: 1m, 5m, 15m, 30m, 1h, 4h, 1d
- `USDCAD` missing buildable timeframes: 1m, 5m, 15m, 30m, 1h, 4h, 1d

## Missing Date Coverage

- `AUDUSD` missing years in 2018-2024: 2022, 2023, 2024
- `AUDUSD` missing years in 2025-now: 2025, 2026
- `USDCAD` missing years in 2018-2024: 2018, 2019, 2020, 2021, 2022, 2023, 2024
- `USDCAD` missing years in 2025-now: 2025, 2026

## Data Quality Issues

- auxiliary 'recent' datasets exist and likely overlap the canonical year-bucketed files
- raw and cleaned parquet variants coexist under bars/15m, so downstream consumers need a clear primary-source rule
- EURUSD includes a latest snapshot file with inconsistent naming versus the rest of the tree
- AUDUSD is present only as raw Dukascopy `.bi5` files in the audited tree, not as cleaned parquet or normalized bars
- USDCAD is absent from the audited source tree

## Generation Approach For Derived Timeframes

- Prefer `cleaned_ticks/<PAIR>/.../*.parquet` when available.
- Build `1m` bars from tick `mid` prices and mean `spread`.
- Derive `5m`, `15m`, `30m`, `1h`, `4h`, and `1d` from the lowest reliable source available per pair.
- Use deterministic OHLC aggregation: `open=first`, `high=max`, `low=min`, `close=last`.
- Sum `volume` only when a source volume column exists. Otherwise omit volume and carry `tick_count` when the source is tick data.
- Skip target timeframes that are lower than the best available source timeframe.

## Validation Performed

- Repository bootstrap completed with `.venv`, `requirements.txt`, package scaffold, `.gitignore`, README updates, and permanent data utilities.
- Audit utility executed against the full source data root to generate this note.
- Timeframe builder smoke test executed successfully:
  - `python scripts/build_timeframes.py --input-root /Users/anevigat/FX/eurusd-quant/eurusd_quant/data --output-root data/processed --pairs EURUSD GBPUSD --start-date 2025-01-01 --end-date 2025-01-07`
  - Generated all target timeframes for `EURUSD` and `GBPUSD`: `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d`
  - Example row counts from the smoke build:
    - `EURUSD`: `1m=5871`, `5m=1176`, `15m=392`, `30m=196`, `1h=98`, `4h=26`, `1d=6`
    - `GBPUSD`: `1m=5862`, `5m=1176`, `15m=392`, `30m=196`, `1h=98`, `4h=26`, `1d=6`
  - Output sanity check passed for sample files: timestamps sorted, timestamps unique, normalized schema present
- A full multi-pair full-history build was not run in Phase 1 because the cleaned tick source tree is large; broader rebuilds should be executed pair-by-pair or with date bounds first.

## Open Questions / Next Actions

- Decide whether Phase 2 should decode raw Dukascopy `.bi5` files so `AUDUSD` can join the normalized pipeline.
- Decide whether `USDCAD` should be sourced from Dukascopy, another vendor, or excluded from the first research batch.
- Resolve overlapping auxiliary datasets such as `recent`, `latest`, and `_raw` variants before relying on fully automated full-history rebuilds.
- After the data layer is stable, add indicator research notebooks or scripts on top of the normalized Parquet outputs.
