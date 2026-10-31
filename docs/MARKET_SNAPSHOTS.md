# Market capture and pre-race baseline (Issue #2)

## Scope and provider decision

The repository contains **no odds scraping, vendor login, API client or automated
betting**. Terms need to be reviewed for each actual source and intended use.
This CLI imports an operator-provided, complete field of **decimal single-win
odds**. No archived bookmaker/JRA quotes, settlements or speculative prices
are shipped with this public repository. Refer to [SOURCES.md](SOURCES.md).

The local capture time is assigned by the current system clock, not an
operator-editable input field. This makes backdating through the CLI less
likely but **does not establish** that the manually entered prices were the
ones displayed by the named source at that instant. The local machine clock
is not trusted time-attestation. SHA-256 detects accidental edits; it is
not a digital signature or third-party proof. Evidence level is always
`SELF_REPORTED_NOT_INDEPENDENTLY_VERIFIED` for this adapter. Keep any original
screen capture and permission evidence privately if allowed, and plan a
provider-authenticated adapter before treating collected data as authoritative.

## Capturing a live quote

A previously sealed forecast must already exist and have `asof < race_at`.
Run this **while the race is upcoming**; the 2026-10-25 Kikuka Sho cannot
be captured as a genuine pre-race quote after it has finished.

Supply a local JSON file with the following shape (numbers are **synthetic**):

```json
{
  "race_id": "UNIT_TEST_RACE",
  "source_url": "https://example.org/synthetic-odds",
  "source_label": "test source (not a real quote)",
  "status": "available",
  "decimal_win_odds": {"1": 2.5, "2": 4.0, "3": 6.0}
}
```

The actual file must provide exactly the entrant numbers in the forecast.
Use gross decimal odds (JPY returned per JPY staked, including stake), not
net profit, percentages, or final payoffs. Do not invent odds. Alternatively,
record an unavailable observation (no prices) with:

```json
{
  "race_id": "UNIT_TEST_RACE",
  "source_url": "https://example.org/synthetic-odds",
  "status": "not_available",
  "reason": "no complete field was available at capture"
}
```

Execute in an authorized private working environment:

```bash
PYTHONPATH=src python -m keiba_backtest.cli capture-market \
  --forecast /private/forecast-upcoming.json \
  --input /private/manually-observed-win-odds.json \
  --output-dir .local_market
```

The command reads the input, stamps the current UTC time (microseconds), checks
all 18 (or other field-size) runner numbers and prices, refuses non-finite,
non-positive, extra or missing odds and unknown input fields, then seals a
new JSON snapshot using SHA-256. It creates a previously unused filename with
`O_EXCL` and mode `0600`, without overwriting earlier captures. A missing-price
record also receives a seal but **cannot** be used to compute market loss.

A successful snapshot contains `schema_version`, `race_id`, `status`,
`source_url`, `source_label` (optional), `capture_method`, `evidence_level`,
`observed_at`, `captured_at`, `decision_at`, `input_sha256`,
`decimal_win_odds` (available only), `reason` (unavailable only) and
`snapshot_sha256`. The timestamps all equal the system capture instant for
this adapter; the quote's creation time and later decision time are **not**
asserted to be the vendor's publication and bet execution time.

Snapshots are stored in `.local_market/<sanitized-race-id>_<digest>/` and ignored
by Git. The digest in the directory name prevents collisions from colon
replacement in JRA-like race IDs. Files are append-only at the CLI layer.
OS permissions, Git ignore and checksum are not an immutable storage service:
operators with filesystem write access can still delete or alter data.

## Evaluation and missingness

```bash
PYTHONPATH=src python -m keiba_backtest.cli evaluate \
  --forecast /private/forecast.json \
  --outcome /private/final-outcome.json \
  --market .local_market/<race-id_dir>/<timestamp>_<sha256>.json
```

`evaluate` checks the sealed snapshot hash and:

`forecast.asof <= market.observed_at <= decision_at < race_at`.

By default a sealed snapshot carries `decision_at` equal to its capture time.
For an explicitly later decision point, `--decision-at <ISO-8601>` may be
supplied, but the report flags that the frozen forecast and later price had
different information windows. Earlier-than-forecast prices, post-race captures
and prices observed after the decision are rejected. Comparison is **not**
a backtest of an executable ticket: tote odds can move or a bet may fail,
and the capture does not prove an actual executable quote.

The market probabilities are normalized inverse win odds:

`market_p[i] = (1 / decimal_odds[i]) / sum_j(1 / decimal_odds[j])`.

The inverse-odds sum is reported separately. This is only a baseline; it
is not an empirically validated adjustment for takeout, rounding or
favorite–longshot bias. Do not subtract a takeout percentage twice from
decimal odds that already include market pricing.

No supplied market record leads to `market.status = not_available` with reason
`no_pre_race_full_field_snapshot`. A sealed `not_available` observation is also
explicitly unscored. Unsealed legacy odds still validate chronology and
completeness for backwards compatibility, but are labeled
`unverified_legacy_quote` and are not acceptable as empirical source evidence.

## Acceptance scope and open data gap

The synthetic tests check full-field completeness, time cutoffs, absent quotes,
seal tampering, denied backdating and exclusive write behavior. They do not
constitute comparison of *real* JRA predictions with actual pre-race prices.
Until a lawful source has provided a pre-race quote with external provenance,
Issue #2's real-data verification milestone remains open.
