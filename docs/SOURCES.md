# Source register

- 2026 original forecast: `archive/2026_kikka_sho_report.md`, archived 2026-10-23 before the race (original file creation metadata 2026-10-23T05:49:45Z). The probability inputs are directly extracted from its appendix, not reconstructed from post-race performance. Hash preserved in `data/forecasts/2026_kikka_forecast.json`.
- 2026 official race result: https://www.jra.go.jp/datafile/seiseki/g1/kikka/result/kikka2026.html
- 2023 official race result: https://www.jra.go.jp/datafile/seiseki/g1/kikka/result/kikka2023.html
- 2024 official race result: https://www.jra.go.jp/datafile/seiseki/g1/kikka/result/kikka2024.html
- 2025 official race result: https://www.jra.go.jp/datafile/seiseki/g1/kikka/result/kikka2025.html

The 2023–25 files contain only verified top-three result labels. They are not archived forecasts. No as-of market odds have been collected. The 2026 official result snapshot includes an outcome availability *policy cutoff* of the next day at 00:00 JST, not a claimed timestamp when JRA first published results.

## Issue #1: source-permission review (2026-10-25)

- JRA website: https://www.jra.go.jp/use/index.html — official race facts and source links are useful, but JRA explicitly reserves rights to its authored articles/media. **No automated extraction or broad raw-data redistribution is enabled here.**
- JRA-VAN terms: https://jra-van.jp/info/rule.html — article 7 restricts received information to personal/private use and forbids redistribution/publication without relevant agreements. Official developer guidance: https://developer.jra-van.jp/t/topic/899. Do **not** put JRA-VAN data exports in a public repo.
- JBIS terms: https://www.jbis.or.jp/terms/ — article 8 limits use/redistribution of obtained data. **Do not** commit bulk JBIS extracts into a public repo without prior consent.
- JRA race-card definition: https://www.jra.go.jp/JRADB/mikata/index.html — illustrates what historical fields may be available in a race-card, but current display is not proof of what was available at a historical forecast cutoff.

Selected implementation: provider-neutral, manually-supplied JSON with explicit capture/source provenance. Public repository includes **synthetic test races only**, not historical bulk vendor data. A real as-of corpus and external permission/evidence are required to complete Issue #1; no backtest skill claim is made at this stage. See `docs/HISTORICAL_FEATURES.md`.

## Issue #2: pre-race win odds (2026-10-26)

- The code ships **no automatic market-data acquisition**. Candidate primary
  sources include JRA's official displayed odds or an expressly licensed
  quote feed. A provider-specific adapter and redistribution/automation
  permissions must be reviewed before ingestion or publication.
- JRA site terms: https://www.jra.go.jp/use/index.html . Published materials
  and structured displays are not a blanket license to scrape/republish.
- JRA-VAN terms: https://jra-van.jp/info/rule.html . Redistribution or
  derivative public quote dumps should not be assumed permitted.
- JBIS terms: https://www.jbis.or.jp/terms/ . Third-party bulk extracts are
  not bundled with this project.
- `capture-market` reads **manual local input only**, timestamps it at local
  invocation, and labels resulting evidence as self-reported rather than
  independently verified provider capture. No real odds snapshot is committed.
- A quote's timestamp must be before the race and after the independent
  forecast's asof. Closing dividends and retrospectively viewed odds are not
  substituted for the decision-time prices.
