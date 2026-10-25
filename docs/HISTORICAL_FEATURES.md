# Point-in-time historical feature pipeline (Issue #1)

## Scope

`historical-features` builds deterministic runner-level features **only** from user-supplied, licensed / permissible race snapshots and past-start records. It does **not** scrape JRA, JRA-VAN, JBIS, netkeiba or third-party websites. It does not produce a forecast and does not learn a model. Outcomes for the *target* race are forbidden in the input schema.

The first release intentionally includes **three synthetic races only** (`data/fixtures/historical_synthetic.json`). They exercise as-of reconstruction, not demonstrate model skill. `data/2023_2025_results_labels_only.json` remains outcomes-only; no historical 2023–2025 forecasts have been inferred from it.

## Import format (schema v1)

Top level:

- `schema_version: 1`, `dataset_id`, `dataset_kind`, `races[]`.
- `dataset_kind: synthetic_fixture | historical_archive | retrospective_research`.
- Each `race` requires `race_id`, timezone-aware `race_at` and `asof`, `surface: turf | dirt`, `distance_m`, `snapshot` evidence, and `entries[]`.
- Each `entry` has a stable `horse_id`, integer `number`, `name`, `status: declared | withdrawn | excluded`, `past_starts[]`. Optional entry-snapshot facts: `draw`, `carried_weight_kg`, `jockey_id`. The **entire entry list is a pre-race snapshot**; do not fill it using final official starters after the fact.
- Each `past_start` includes `race_id`, `race_at`, `result_available_at`, `surface`, `distance_m`, `status`, `finish_position`, `field_size` and `evidence`. `last3f_seconds` and `dead_heat` are optional. Finishing position is `null` for `did_not_finish` and `disqualified`; previous races with declared dead heats have a numeric shared rank and `dead_heat: true`.
- Evidence object: `{ "kind": "captured_pre_race", "observed_at": "ISO-8601", "source_url": "https://...", "source_sha256": "..." }`. `source_sha256` is required for `captured_pre_race` and binds a preserved source snapshot to the observation if its redistribution is permitted. The original captured timestamp must be proven independently; a digest or handwritten timestamp alone does not prove contemporaneous capture.

Sample fixture illustrates the contract without using external racing data. Unknown fields are rejected, specifically to avoid accidental injection of target results into predictor inputs. All timestamp comparisons respect time zone offsets.

## Temporal validation and evidence classes

**Strict default**:

1. `asof < race_at`. Every roster/source capture `observed_at <= asof`.
2. Every past start `past_start.race_at < asof` and `past_start.result_available_at <= asof`, with publication after that start's scheduled `race_at`.
3. No past start may reference the target race ID; no duplicates per horse or duplicated race/horse/number identities. The same horse's past-race facts must also be consistent across target-race snapshots; corrected results require a separate, explicit versioned data source.
4. `captured_pre_race` means genuinely captured before the prediction cutoff. `historical_archive` requires this evidence for the roster and every historical start. These conditions are *assertions checked by code*, not independently certified timestamps.
5. Later-downloaded or potentially revised public historical pages are **not** evidence of what a pre-race user saw. For exploratory reconstruction only, use `dataset_kind: retrospective_research`, `kind: retrospective_unverified`, and `--allow-unverified`. The output is explicitly marked `RETROSPECTIVE_UNVERIFIED_NOT_EMPIRICAL` and `empirical_backtest_eligible: false`, **even if the race event itself was earlier**.
6. Synthetic fixtures are explicitly marked `SYNTHETIC_NOT_EMPIRICAL` and always have `empirical_backtest_eligible: false`.

`VERIFIED_PRE_RACE` denotes an **input contract claim**. It does not mean the code independently confirmed a web archive, license, timestamp, or correctness of the source; such evidence must be externally reviewed before empirical use. In particular, if an external provider permits personal use but prohibits republication, no provider raw files or derived bulk table should be committed to a public repository without permission.

### Known limitations

- `race_at` and `result_available_at` are input-provided. Only a verified captured/published source establishes their authenticity. Do not auto-infer publication time from event date.
- Entry cancellation/exclusion known at snapshot time is preserved under `excluded_entries` and is not included among declared runners. **Later** cancellation cannot be backfilled into an earlier roster. Whole-race abandonment, target dead heat, and non-completion require outcome-layer changes before ordinary score evaluation; existing scorer intentionally rejects unsupported final outcomes.
- The history features treat prior disqualification / DNF as a start but not a completed finish. Previous dead heats can be represented with equal ranks; a finish of `1` counts as a win for this descriptive aggregate.
- `mean_last3f_seconds` is an unadjusted arithmetic average across races, not a pace/track/going-adjusted speed figure. `first_time_target_distance_or_more` considers distance experience **on the target surface**, not genomic or pedigree suitability.
- Dataset `historical_archive` can contain copied data for internal licensed analysis. Before making **feature outputs** public, verify the redistribution rights of the source and its transformed content; this CLI does not grant them.

## Generated features

Per declared runner: `past_starts`, `completed_finishes`, `wins`, `top3_finishes`, `starts_last_365d`, `last_start_days_ago`, `max_prior_distance_m`, `turf_2400m_plus_starts`, `first_time_target_distance_or_more`, `mean_finish_fraction`, and `mean_last3f_seconds`. Missing past observations produce `null` for relevant descriptive summaries (never zero-fill unknown previous-race metrics). Output contains source past-race IDs and a SHA-256 of the imported JSON bytes; it never includes target results, odds, or target winner labels.

## CLI

```bash
PYTHONPATH=src python -m keiba_backtest.cli historical-features \
  --input data/fixtures/historical_synthetic.json \
  --output /tmp/keiba_features.json
python -m unittest discover -s tests -v
```

To inspect a later-collected historical extract **without** using it as empirical backtest evidence:

```bash
PYTHONPATH=src python -m keiba_backtest.cli historical-features \
  --input /private/retrospective_dataset.json \
  --allow-unverified --output /tmp/research_only.json
```

Do not pass the synthetic output into the walk-forward forecast calibration CLI. `historical-features` is a feature builder, not `forecast` data, and the current version has no trained historical prediction generator.

## Next milestone to finish Issue #1

1. Select an approved, auditable historical data provider or an original capture stream, with explicit terms for public feature publication.
2. Capture **multiple complete actual pre-race rosters**, horse identifiers, and their prior-start records **before** the relevant `asof`, including source artifact hash and trusted capture times. Do not retrofit the current JRA results pages as historical pre-race captures.
3. Add a provider-specific adapter and source contract tests with approved data. Keep any restricted raw data outside the public repository.
4. Verify real-world coverage, duplicates, cancellation handling and reproducibility on at least 3 actual races. This remains open until achieved.
