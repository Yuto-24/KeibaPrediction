# Zero-fee historical win-odds workflow (Issue #2)

## Source decision (2026-10-27)

No JRA-VAN Data Lab., TARGET or other paid/free-trial subscription is required by this workflow. Do not turn on automatic third-party scraping or log into a vendor website with stored credentials.

Candidate free dataset: [takamotoki / JRA日本中央競馬会 Horse Racing Dataset](https://www.kaggle.com/datasets/takamotoki/jra-horse-racing-dataset), released circa 2021. Its four CSV groups are described as **odds, race results, corner passing orders and lap times**, covering races through 2021-07-31 (not 2022–2026). The uploader displays a CC BY 4.0 license in public metadata, **but other public descriptions say the uploader originally scraped netkeiba**. Do not assume the uploader's license overrides underlying provider terms or gives permission to redistribute the underlying race extracts. Consult both the dataset's current license and its original provider conditions. Keep the downloaded data and any full-field extracts in locally ignored directories; commit only code, synthetic fixtures and non-sensitive methodological summaries.

References:
- https://www.kaggle.com/datasets/takamotoki/jra-horse-racing-dataset
- https://github.com/evanfadhil/japan_horse_racing_analysis (four-file grouping and stated origin)
- https://rsp.netkeiba.com/info/kiyaku.html (republication/private use)
- https://www.jra.go.jp/faq/pop02/1_6.html (official historical result viewing)

Other free sources: JRA's public result pages cover historical race results, but the G1 results table contains **popularity** and winning-ticket **payout**, not full-field decimal win prices. Neither is a substitute for a complete market distribution. Manually reviewed, publicly viewable full-field results can be entered locally through `import-final-odds`; no automated web crawler ships here.

## Download/inspect without paid subscriptions

The operator downloads and unpacks the publicly available CSV archive **personally** from the dataset page, if its access/terms permit. Kaggle may request a free account. Raw files must not be added to this public repository.

The actual CSV column names and orientation have **not been inspected in this session**. Do not assume `race_id`, `horse_number` or `win_odds` are the Kaggle names: first inspect each actual downloaded CSV:

```bash
PYTHONPATH=src python -m keiba_backtest.cli inspect-free-csv \
  --input .local_free_odds/odds.csv --encoding utf-8-sig
PYTHONPATH=src python -m keiba_backtest.cli inspect-free-csv \
  --input .local_free_odds/race_results.csv --encoding utf-8-sig
```

Use `--encoding cp932` for Shift-JIS/CP932 CSV as appropriate. Confirm whether the odds are **final settled** prices rather than prior-day / time-series quotes, how `race_id` and horse numbers align between files, and how scratches are represented. If the actual file uses one row per race with many horses as columns (wide CSV), it must be normalized to one row per horse *before* this importer is used; it is not safe to guess wide-schema transformations.

For the supported **long table** input, create an **untracked** JSON mapping with the exact observed column headings:

```json
{
  "odds": {"race_id": "Race", "number": "Horse", "odds": "単勝"},
  "roster": {"race_id": "Race", "number": "Horse", "finish": "着順"}
}
```

These column names are **synthetic illustration only**, not a claim about Kaggle's actual CSV. The optional results roster should contain each actual entrant and its official rank, including horses with missing prices as an incomplete race. Do not convert popularity into a probability or infer absent odds from payouts. Any identifier discrepancy must be resolved explicitly.

## Import and market-only diagnostic

```bash
PYTHONPATH=src python -m keiba_backtest.cli import-free-csv \
  --odds-csv .local_free_odds/odds.csv \
  --roster-csv .local_free_odds/race_results.csv \
  --mapping .local_free_odds/columns.json \
  --source-url 'https://www.kaggle.com/datasets/takamotoki/jra-horse-racing-dataset' \
  --db .local_free_odds/market.sqlite3 \
  --output .local_free_odds/import_summary.json

# Copy the resulting import_id from import_summary.json:
PYTHONPATH=src python -m keiba_backtest.cli score-free-csv \
  --db .local_free_odds/market.sqlite3 \
  --import-id '<import_id_from_summary>' \
  --output .local_free_odds/market_only_scores.json
```

`score-free-csv` requires one observed winner, full race-roster coverage and a valid finite decimal odds price for every entrant. No missing values are filled. It returns retrospective **market-only vs uniform** Log Loss and full-field Brier across usable races, skipping missing/inconsistent races. This is not a comparison with the independently developed user forecast: archived out-of-sample predictions are still absent for 1986–2021. The result is never described as a purchase-time, executable odds backtest or a guaranteed ex-ante decision. The original CSV file hashes, column mapping hash and input source URL are stored locally; a checksum is not source authentication.

This imports a row-oriented CSV only. A separate adapter for an actually inspected Kaggle release, including provider-specific encoding/header/reshaping and cross-source reconciliation, requires the downloaded sample; until then **do not claim the Kaggle dataset itself has passed empirical ingestion**.

## Test with no external input

```bash
PYTHONPATH=src python -m keiba_backtest.cli import-free-csv \
  --odds-csv data/fixtures/free_market_odds_synthetic.csv \
  --roster-csv data/fixtures/free_market_results_synthetic.csv \
  --mapping data/fixtures/free_market_columns_synthetic.json \
  --source-url 'https://example.org/synthetic-only' \
  --db .local_free_odds/synthetic.sqlite3
python -m unittest discover -s tests -v
```

The synthetic fixture **does not measure real JRA model performance**. The private SQLite database and CSV archives must not be committed.

## Remaining research and decision boundary

- Validate the Kaggle CSV's *actual* fields, license/provenance, prices and roster against a few independently checked official JRA races before training.
- Construct leakage-controlled, date-aligned forecasts for historical races (Issue #1) then compare the same holdout set against the market-only baseline.
- Maintain separate `capture-market` snapshots for genuinely observed pre-race prices; settled odds cannot establish attainable ticket returns (Issue #6).
- Later years, especially after 2021, require other freely available sources or separate permitted manually reviewed extracts; do not fake currency or coverage to fill the gap.
