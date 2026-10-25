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

Required: `race_id`, `observed_at`, `source_url`, `decimal_win_odds`, where `decimal_win_odds` is a mapping of horse numbers as strings to decimal odds, e.g. 1.8 means a 1.8x gross payout. All runners must be present. The quote must be observed at or before the **decision cutoff**, and the decision cutoff must precede race start. By default the decision cutoff equals model `asof` (identical information cutoff). A quote collected later than model `asof` can be compared **only when `--decision-at` is explicitly supplied**, with `forecast.asof <= quote.observed_at <= decision_at < race_at`. This compares a frozen early model with a later market and is flagged as having different information windows.

A closing/settled odds sheet first retrieved after the race is not valid for an ex-ante decision-time comparison. Archived real pre-race quotes are required.

For comparison, `market_probabilities` normalizes `1/decimal_odds` across the field. This removes aggregate overround as a baseline but does not empirically correct favourite–longshot bias or tote rounding.

## Evaluation rules

- 1 outcome per race is the evaluation unit for Log Loss and multiclass Brier; sum the squared forecast error over the entire field. Report `brier_multiclass_sum` rather than unqualified Brier.
- Rolling calibration is fitted to previous **paired forecast + final outcome** records only. Outcome's `result_usable_after <= next_forecast.asof` is checked.
- Bin summaries are descriptive; individual horses in the same race are not independent samples. Bootstrap resamples races, not horses.
- If the sample is smaller than the configured initial threshold of 30 races, calibration and significance checks are skipped without adding artificial data.

## Historical feature input / output (v1, Issue #1)

See `docs/HISTORICAL_FEATURES.md` for the complete historical import contract and sample fixture. It uses its own CLI (`historical-features`), not the v0.1 `data/forecasts/` probability schema. `historical_archive` requires contemporaneous capture of full entrant rosters and prior race facts. `retrospective_research` and `synthetic_fixture` never become empirical validation samples, even when they generate plausible numerical features. Historic features must not contain target-race labels.
