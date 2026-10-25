# Design decisions, observations and open work

## Observation O-01: existing model is reproducible, but not calibrated

The 2026-10-23 report contains exact 18-runner `scores`, `wet`, `paceS/M/H`, six scenario probabilities, and T=3.75. SHA256 of the archived Markdown original is recorded in the forecast JSON. Recomputed winning probability for no.8 is approximately 0.369285 and no.9 is 0.061526. The total probabilities are 1/2/3 for first, top2, top3 respectively.

**Learning:** Reproduce immutable source before modifying the forecast method; rounded table percentages are insufficient for proper scoring.

## Observation O-02: a one-race diagnostic cannot establish general calibration

2026 observed winner no.9 yields Log Loss 2.788293, multiclass Brier 1.058388. Uniform yields 2.890372 and 0.944444 respectively. These metrics disagree on which predictor did better in one race; no claim about general skill or calibration follows.

**Decision:** Show both proper scoring rules and require multi-race out-of-sample validation before changing coefficients. Current `min_train_races=30` is an initial conservative engineering guardrail, NOT a sample-size power calculation.

## Observation O-03: retrospective weather updates would leak future knowledge

The original 2026 report weighted dry/wet 40/60. The actual day was JRA `良`. Replacing the weights with 100% dry after observing that result improves the winning horse's assigned probability (about 6.15% to 8.37%), but this is hindsight and no evidence of predictive improvement.

**Decision:** Diagnostic CLI has explicit `HINDSIGHT_DIAGNOSTIC_NOT_TRAINING` status. Only archived as-of forecasts enter the official walk-forward set.

## Observation O-04: historical labels do not create historical predictions

2023, 2024 and 2025 JRA official finishers have been recorded as labels. The original 2026 model did not produce saved pre-race probabilities in those years. Training/evaluating it by inventing ratings for those years using knowledge of the outcomes would be biased.

**Decision:** Results-only labels are stored separately and ignored by the scorer. Next milestone is an as-of historical feature construction process with source timestamps and an independent holdout.

## Observation O-05: ground truth from JRA takes priority over commentary

For 2026 no.6 バステール, JRA has 16-16-16-12 at four recorded corners. A later commentary message incorrectly said 5-5-4-3. Store official rank and provenance as structured truth; do not treat comments as ground truth.

## Observation O-06: Python minor versions differ in last-bit float results

The initial GitHub Actions run on 2026-10-25 passed all 17 tests on Python 3.12 but failed `test_sha_source_frozen_and_reconstruct` on Python 3.10. The mismatches were at the final few binary-float digits (e.g. 0.22216305378253037 versus 0.22216305378253035). The archived report SHA256 and model-input SHA256 were already compared exactly. This is a strict-test equality defect, not evidence of a changed historical forecast.

**Fix:** Preserve exact source hashes, runner numbers and names, but compare reconstructed floating marginals to the frozen snapshot with a `1e-12` absolute tolerance. Do not rewrite archived probabilities to suit an interpreter. Keep both Python versions in CI to detect genuine differences.

## Open work (not completed)

1. Historical as-of per-horse feature extraction: past races only, rating, 2400m+ experience, market snapshots, weather forecast as of decision, course and rider conditions.
2. Cross-race power/temperature calibration with nested chronological model selection and preferably tens to hundreds of independent race outcomes.
3. Model calibration on first-time distance/conditions, using shrinkage/partial pooling; test out of sample before declaring gains.
4. Market comparison using usable **pre-race** full-field odds snapshots; final market odds are not substitutable in buying-strategy backtests.
5. Robust top-2/top-3 and combination modeling, race-correlated bootstrap confidence intervals, and bet-sizing constraints.

Never promote these observations into general rules without independent replication on other races.

## Observation O-07: historical results are not contemporaneous data snapshots (Issue #1)

2026-10-25 source-permission review found express redistribution restrictions for JRA-VAN data and JBIS extracts. Present-day official race pages also do not establish their exact historic publication/version timestamps.

**Decision:** Ship a source-neutral, user-supplied as-of feature generator and synthetic multi-race contract tests before connecting a real data provider. Default refuses records retrieved only after the historical `asof`; an explicit retrospective mode produces diagnostic-only output. Do not make claims of empirical calibration or quietly use now-visible result pages as pre-race snapshots. This is an **Issue-specific observation**, not a proven pattern across independent repositories.

**Still open:** obtain permitted genuine pre-race captures for several real races and build/test an adapter; do not close Issue #1 solely because synthetic tests pass.
