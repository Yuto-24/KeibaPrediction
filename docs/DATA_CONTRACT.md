# Data contract: version 0.1

## Forecast (`data/forecasts/<race-id>.json`)

Required fields: `race_id`, `race_at`, `asof`, `origin_source`, `runners`. All timestamps must be ISO 8601 with offset, e.g. `2026-10-23T14:47:00+09:00`.

`race_at`: scheduled local race-start timestamp. `asof`: latest time at which all inputs and the prediction were available; `asof < race_at`.

`runners` is a list of unique `{number, name, win_probability}`, with optional `top2_probability`, `top3_probability`. Probabilities are proportions (0 to 1), not percent. Sum of `win_probability` must be exactly 1 within a floating tolerance; top2 sum 2, top3 sum 3. Marginals satisfy win <= top2 <= top3.

Optional `features` is a list of `{name, available_at, ...}`. Every feature `available_at` must be on or before `asof`. When adding engineered features, provide availability metadata rather than silently substituting post-race observations.

`model_version`, `source_url`, `source_sha256` are recommended to preserve provenance.

## Outcome (`data/outcomes/<race-id>.json`)

Required: `race_id`, `status:"official_final"`, `source_url`, `finishing_order`, `result_usable_after` (for walk-forward only). `finishing_order` must list **every** horse number exactly once in 1st, 2nd, ... order. No automatic missing-runner or dead-heat support in v0.1; return an explicit error instead of mis-scoring.

`result_usable_after` is a **conservative training eligibility cutoff**, not necessarily the exact publication time. If the official publication timestamp is not verifiable, use a later safe date, not a fabricated source time. This prevents a future forecast from training on outcomes that might not yet have been available.

## Market quote (optional for `evaluate --market`)

Required: `race_id`, `observed_at`, `source_url`, `decimal_win_odds`, where `decimal_win_odds` is a mapping of horse numbers as strings to decimal odds, e.g. 1.8 means a 1.8x gross payout. All runners must be present. The quote must be observed at or before the **decision cutoff**, and the decision cutoff must precede race start. For a sealed `capture-market` quote the default decision cutoff is its own `decision_at` (equal to capture time), while legacy unsealed quotes default to the model `asof`. `--decision-at` overrides this cutoff. Valid chronology is `forecast.asof <= quote.observed_at <= decision_at < race_at`. A later captured market quote is flagged as having a different information window from the earlier frozen model.

A closing/settled odds sheet first retrieved after the race is not valid for an ex-ante decision-time comparison. Archived real pre-race quotes are required.

For comparison, `market_probabilities` normalizes `1/decimal_odds` across the field. This removes aggregate overround as a baseline but does not empirically correct favourite–longshot bias or tote rounding.

## Evaluation rules

- 1 outcome per race is the evaluation unit for Log Loss and multiclass Brier; sum the squared forecast error over the entire field. Report `brier_multiclass_sum` rather than unqualified Brier.
- Rolling calibration is fitted to previous **paired forecast + final outcome** records only. Outcome's `result_usable_after <= next_forecast.asof` is checked.
- Bin summaries are descriptive; individual horses in the same race are not independent samples. Bootstrap resamples races, not horses.
- If the sample is smaller than the configured initial threshold of 30 races, calibration and significance checks are skipped without adding artificial data.

## Historical feature input / output (v1, Issue #1)

See `docs/HISTORICAL_FEATURES.md` for the complete historical import contract and sample fixture. It uses its own CLI (`historical-features`), not the v0.1 `data/forecasts/` probability schema. `historical_archive` requires contemporaneous capture of full entrant rosters and prior race facts. `retrospective_research` and `synthetic_fixture` never become empirical validation samples, even when they generate plausible numerical features. Historic features must not contain target-race labels.

## Market capture v1 (Issue #2; manual input and append-only snapshot)

`capture-market` stamps the actual invocation time; users cannot pass an
historical observed timestamp via this CLI. Required manual input:
`race_id`, `source_url` (https), optional `source_label`, `status:"available"` and the complete
`decimal_win_odds` mapping; or `status:"not_available"` plus a reason and
no odds mapping. Unknown input keys, including post-race labels, are rejected.

The resulting sealed snapshot records a provider-neutral `capture_method`,
`observed_at == captured_at == decision_at`, `input_sha256`, `snapshot_sha256`
and `evidence_level: SELF_REPORTED_NOT_INDEPENDENTLY_VERIFIED`. It is written
exclusively to a new filename and must never be committed without appropriate
licensing review. Source labels, odds contents, origin and contemporaneous
publication are not independently authenticated by a local SHA-256 hash.

For market scoring, strict comparison requires
`forecast.asof <= observed_at <= decision_at < race_at`. A sealed snapshot
uses its own `decision_at` unless overridden by `--decision-at`. A legacy
unsealed quote defaults to the forecast `asof`. The historical
legacy market format without a seal is still accepted for diagnostic backwards
compatibility but clearly marked `unverified_legacy_quote`. Missing market
data yield explicit `not_available`, never fabricated probabilities. See
`docs/MARKET_SNAPSHOTS.md` for safeguards and reproducible CLI examples.

## Historical settled final odds (Issue #2, retrospective benchmark only)

This is **not** the pre-race market quote format. Import operator-provided
`race_id`, HTTPS `source_url`, optional `source_label`, `status:"available"`,
and complete `decimal_win_odds` (or `not_available` plus a reason). The CLI
adds import-time `retrieved_at`, `odds_kind:"settled_final_win_odds"`,
`collection_method:"retrospective_manual_import"`, provenance warning, and
integrity digest. It never invents `observed_at` or `decision_at` before race.

`evaluate-final-odds` requires a race's original immutable forecast, official
outcome and all-runner final odds. It reports `market_final` rather than
`market`, with a warning about unmatched information windows and
`not_a_purchase_backtest:true`. `compare-final-odds-batch` uses only complete
forecast/outcome/market triplets and reports data gaps. It cannot validate
buyable price or past expected returns. See `docs/FINAL_ODDS.md`.

## Offline free historical CSV index (Issue #2)

A free local CSV archive, unlike a pre-race forecast or quote, is retrospective research data. `import-free-csv` creates private `csv_imports`, `csv_win_odds`, and `csv_race_roster` SQLite tables. It stores the original odds CSV / roster CSV SHA-256, exact column-mapping SHA-256, dataset URL and import clock; it does **not** create or backdate an `observed_at` for the historical event.

Each source CSV must be a **long-format** table with one `(race_id, horse_number)` per row. Mapping JSON binds the exact source headers for race ID, horse number, decimal single-win odds, and optionally official finishing position in a separate roster file. Duplicate identities fail atomically, missing prices remain missing, and race/field mismatch is excluded from scoring. `score-free-csv` requires a complete roster and a unique winner and reports market-only retrospective scores against uniform probabilities. Historic forecasts must be independently generated and time-consistent before evaluating model skill; `score-free-csv` is not a simulation of realizable bets. Consult `docs/FREE_HISTORICAL_CSV.md` for safe usage and license caveats.
