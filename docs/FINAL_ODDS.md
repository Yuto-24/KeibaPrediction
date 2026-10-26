# Settled final win odds: historical **forecasting benchmark** (Issue #2)

This is a separate pathway from `capture-market`, which is restricted to
**observed pre-race** prices. Historical *final/settled* win odds are useful
for judging whether an independent forecast contains signal beyond the final
betting market, **not** for proving the expected return of any bet available
before a race. A Friday forecast and Sunday closing prices have different
information sets. Report that difference and score on identical race sets.

## Input and source handling

The CLI does not scrape vendor websites or read proprietary databases. Supply
one manually reviewed JSON per race from a source whose **private analytical
use** you have confirmed. The `race_id` and all runner numbers must match the
existing immutable original forecast (`data/forecasts`), not the final payout.
Example with **invented numbers** (a production file must cover the full field):

```json
{
  "race_id": "SYNTHETIC_3_RUNNERS",
  "source_url": "https://example.org/synthetic-demo",
  "source_label": "synthetic illustration only",
  "status": "available",
  "decimal_win_odds": {"1": 2.5, "2": 4.0, "3": 12.0}
}
```

The `decimal_win_odds` are *gross* single-win payback multipliers for every
entrant. No values can be missing or zero; all must be finite and >= 1.0.
If the source does not give the **entire** field, instead submit
`{"race_id": "...", "source_url": "https://...", "status": "not_available", "reason": "incomplete field"}`.
No outcome labels, predicted winning chances, manual timestamp, or purchased
bet prices are permitted in the input.

`import-final-odds` seals the supplied bytes and stamps the **actual import
clock**, producing a new file under `.local_final_odds/` with `O_EXCL`
(non-overwrite). Its SHA-256 detects accidental modification, **not** a forged
source, data error, or truly independent collection time. Status is
`MANUALLY_TRANSCRIBED_POST_RACE_NOT_SOURCE_VERIFIED`. The input is a
*retrospective* final price even when captured seconds after the finish.
Keep licensed raw odds and output snapshots private; this public repository
contains no provider extracts. Check provider permissions separately.

## CLI (external packages not required)

```bash
PYTHONPATH=src python -m keiba_backtest.cli import-final-odds \
  --forecast data/forecasts/2026_kikka_forecast.json \
  --input /private/kikka-2026-final-win.json \
  --output-dir .local_final_odds

PYTHONPATH=src python -m keiba_backtest.cli evaluate-final-odds \
  --forecast data/forecasts/2026_kikka_forecast.json \
  --outcome data/outcomes/2026_kikka_result.json \
  --final-odds .local_final_odds/<race-folder>/<snapshot>.json

PYTHONPATH=src python -m keiba_backtest.cli compare-final-odds-batch \
  --forecasts-dir data/forecasts --outcomes-dir data/outcomes \
  --final-odds-dir .local_final_odds
```

The last command requires unique `race_id` within each folder and reports
missing market prices or missing forecast/outcome pairs; it never fills gaps
using win payout or the winner's price. The `matched_race_mean_scores` refer
to **only the races with all three records**, using equal weight per race.
The market model uses `1/odds` normalized over all horses: its sum of inverse
odds is also reported, but this is **not** a fully calibrated bookmaker/JRA
probability model. Compare Log Loss and full-field multiclass Brier on the same
sample; do not compare means from different coverage subsets. A single race is
only a diagnostic, not evidence of market outperformance.

## Strict separation from betting-price evaluation

The saved snapshot has `odds_kind: settled_final_win_odds` and `retrieved_at`.
It **never** has pre-race `observed_at` / `decision_at`. Submitting this file
to `evaluate --market` is an error. Use `evaluate-final-odds`, which emits
`market_final` and `not_a_purchase_backtest: true`. Final odds are **not**
substitutes for purchase-time prices. The normal `evaluate --market` and
`capture-market` workflows remain available for later ticket-EV research.

## Current evidence gap

Retrospectively sourced records do **not** create historical model forecasts.
2023–2025 Kikuka Sho still have results-only labels in this repository, so the
model cannot be fairly tested against their market odds until genuine as-of
predictions or leakage-controlled ex-ante reconstructions exist. Data acquisition
for broader samples is tracked in Issue #1; no claim of a calibration advantage
or a profitable strategy is made here.
