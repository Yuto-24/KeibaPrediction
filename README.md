# 競馬予測のバックテスト基盤（初版）

2026年菊花賞の**実際にレース前に保存された主観評価モデル**を出発点として、確率の校正とリークのない時系列検証を行うための最小構成です。外部パッケージなしのPython 3.10以降で実行できます。データの自動スクレイピング、馬券購入、結果を使った新規予想は行いません。

## 今回の到達点

- 2026-10-23に保存された菊花賞予想の入力から、18頭の勝率／連対率／3着以内率を再現。
- 2026-10-25のJRA確定着順と照合。元モデルのLog Loss / multiclass Brier Scoreを算出。
- 実際の馬場を使った計算や温度変更は**結果判明後の感度分析**として明示的に隔離。
- 確率校正・レース単位の信頼性集計・ブートストラップ・ウォークフォワード検証のコードを実装。
- 事前予測が現在1レースしかないため、**学習・校正・統計的有意性評価はまだ実施できない**。最小30レースの初期ガードレールにより校正が自動スキップされる。
- 過去年3レース（2023～2025）の**結果ラベルのみ**保存。事前予測がない以上、これらを独立モデルのバックテストに使わない。
- 判断時点に保存された実売オッズのスナップショットがなく、同時点での公平な市場比較は**未実施**。
- 過去の**最終単勝オッズ**を独立した市場ベンチマークとしてインポート・採点できるようにした。これは購入時価格ではない。

## 動作確認

ZIPを展開したフォルダーで次を実行します。すべて標準ライブラリのみで動作します。

```bash
python -m unittest discover -s tests -v
PYTHONPATH=src python -m keiba_backtest.cli validate \
  --forecast data/forecasts/2026_kikka_forecast.json \
  --outcome data/outcomes/2026_kikka_result.json
PYTHONPATH=src python -m keiba_backtest.cli evaluate \
  --forecast data/forecasts/2026_kikka_forecast.json \
  --outcome data/outcomes/2026_kikka_result.json
PYTHONPATH=src python -m keiba_backtest.cli sensitivity \
  --model-inputs data/2026_kikka_original_model_inputs.json \
  --outcome data/outcomes/2026_kikka_result.json
PYTHONPATH=src python -m keiba_backtest.cli walk-forward \
  --forecasts data/forecasts --outcomes data/outcomes \
  --min-train-races 30
```

Windows PowerShellでは各実行コマンドの先頭の `PYTHONPATH=src` の代わりに、最初に `$env:PYTHONPATH='src'` を設定します。あるいは `python -m pip install -e .` を実行すれば `PYTHONPATH` 指定は不要です。

## ファイル案内

| パス | 内容 |
|---|---|
| `archive/2026_kikka_sho_report.md` | 2026-10-23の元予測レポート原本コピー |
| `data/2026_kikka_original_model_inputs.json` | 元モデルの独自能力点・展開シナリオ・係数 |
| `data/forecasts/2026_kikka_forecast.json` | 原本から復元した事前予測（全18頭、非丸め） |
| `data/outcomes/2026_kikka_result.json` | 2026年JRA公式着順 |
| `data/2023_2025_results_labels_only.json` | 2023～2025結果の上位3頭（予測ではない） |
| `src/keiba_backtest/probability.py` | 元の6シナリオ・Plackett-Luceの確率計算 |
| `src/keiba_backtest/scoring.py` | Log Loss、Brier、均等・市場オッズ基準 |
| `src/keiba_backtest/temporal.py` | 過去のみで校正するウォークフォワード実装 |
| `src/keiba_backtest/diagnostics.py` | 信頼性区間表・レース単位ブートストラップ |
| `src/keiba_backtest/records.py` | 日時・リーク・馬番・確率の入力検査 |
| `results/` | 実際の再計算結果（JSON） |
| `docs/DECISIONS.md` | 設計判断・確認済みの問題・次の課題 |
| `docs/DATA_CONTRACT.md` | 新しいレースの予測・結果・市場データの入れ方 |
| `src/keiba_backtest/final_odds.py` | 過去の最終単勝オッズを収集時刻付きで保存し、独立モデルと比較 |
| `docs/FINAL_ODDS.md` | 過去確定オッズの利用条件・実行手順・禁止事項 |

## 2026年の採点

- 原本再現：⑧勝率36.9285%、⑨勝率6.1526%。勝率合計100%、連対率合計200%、3着以内率合計300%。
- ⑨勝利に対するLog Lossは **2.788293**、multiclass Brier（各馬の二乗誤差を合計）は **1.058388**。
- 18頭均等予測のLog Lossは **2.890372**、Brierは **0.944444**。
- 結果を知ってから「乾いた条件のみ」を指定した参考計算は⑨8.37%。これは**モデル改善のバックテスト結果ではありません**。

## 過去レースの追加と検証条件

1. 予想対象の発走前に、予想生成時刻・モデル版・全出走馬の非丸め勝率・データ取得時刻を保存。確率合計は厳密に1とする。
2. 発走後は、対象レースの公式着順と結果が利用可能になった日時を別に記録。
3. **購入戦略**では判断時点以前に取得した全頭の単勝オッズが必要。**予測精度の市場比較**では後から確認した全頭の最終単勝オッズも使える。ただし最終払戻から復元した価格を、購入時に知っていた価格として使用しない。
4. 検証レースより前に予想と結果が存在するデータのみを学習に使用する。過去30レース未満なら校正は行わない（この閾値は十分性を保証するものではない）。
5. 係数を変更する場合は学習・モデル選択・テストを時系列で分離。2026年菊花賞の結果を使って係数を合わせた後、同レースの改善スコアを独立性能として主張しない。

### 評価で比べるもの

- `raw`: 予想当時に保存された独立モデルの確率。
- `uniform`: 全出走馬の勝率を均等にした基準。
- `market`: **レース前に時刻付きで保存した**全頭オッズの逆数を正規化した購入判断用の基準。封印済み観測は自身の `decision_at` を持つ。市場の控除と偏りを完全には補正しない。
- `market_final`: **レース後に取得した確定オッズ**から作る別の予測ベンチマーク。予測と価格の利用可能な情報時点が違う。購入期待値の検証には使わない。
- `calibrated`: 既知の過去レースだけでpower exponentを学習し、未知レースに適用した確率。

`calibrated` と `raw` の比較は**同じテストレース集合**で行います。

## 残る制約

元の独自能力点は過去データから算出した客観指標ではありません。シナリオ重みや距離補正も未校正です。現行基盤が正しく機能することと、元モデルの予測精度が高いことは別です。最終馬場などの結果を事前特徴量へ混ぜることも禁止しています。

本番適用に向けた次の作業は、再現できる特徴量生成（すべて当該レース前日時基準）、十分な過去レースの予測再構築、ウォークフォワード検証、実売価格の時点記録です。まだ市場を上回る優位性を確認できていません。

## Issue #1: historical as-of feature generation

A provider-neutral CLI now builds per-horse features for multiple races from a supplied JSON bundle. The fixture has **3 wholly synthetic races**; it is not a backtest of historical predictions. The CLI rejects future results, late source captures, duplicate horses, target-race outcome fields, and unknown schema fields. Retrospective extracts without proven historical snapshots are disabled by default and **never** marked empirical.

```bash
PYTHONPATH=src python -m keiba_backtest.cli historical-features \
  --input data/fixtures/historical_synthetic.json \
  --output /tmp/keiba_features.json
```

Read [historical feature schema and proof rules](docs/HISTORICAL_FEATURES.md) and [data license/source review](docs/SOURCES.md) before using real racing data. Historical real-race ingestion is intentionally **not yet complete**. Redistribution restrictions mean raw vendor extracts must not be committed here without permission. See [Issue #1](https://github.com/Yuto-24/KeibaPrediction/issues/1) for the outstanding real-data source and coverage milestone.

## Issue #2: record pre-race single-win odds without lookahead

`capture-market` records **operator-provided** (not scraped) full-field decimal
win odds at the current UTC clock time. It refuses backdating and post-race
capture. The public repository includes no real vendor prices; local quote
files are kept under Git-ignored `.local_market/`.

```bash
PYTHONPATH=src python -m keiba_backtest.cli capture-market \
  --forecast /private/forecast-upcoming.json \
  --input /private/full-field-odds.json \
  --output-dir .local_market

PYTHONPATH=src python -m keiba_backtest.cli evaluate \
  --forecast /private/forecast-upcoming.json \
  --outcome /private/official-result.json \
  --market .local_market/<race-folder>/<saved-snapshot>.json
```

A missing market file now explicitly reports `market.status=not_available`.
The example is a command template, **not executable with the finished 2026
Kikuka Sho as a new live observation**. Manually transcribed odds remain
self-reported even with a checksum; source authentication, data rights,
provider-specific integration and actual market comparison remain open.
See [Market capture contract and limitations](docs/MARKET_SNAPSHOTS.md) and
[Issue #2](https://github.com/Yuto-24/KeibaPrediction/issues/2).

## Issue #2: historical final odds benchmark (priority)

Historical **final/settled single-win odds** are imported separately from
`capture-market`; the new data carry `odds_kind=settled_final_win_odds` and
an actual **post-race import** timestamp. They are NOT executable pre-race
odds and cannot be passed to `evaluate --market`.

```bash
PYTHONPATH=src python -m keiba_backtest.cli import-final-odds \
  --forecast data/forecasts/2026_kikka_forecast.json \
  --input /private/full-field-final-odds.json \
  --output-dir .local_final_odds

PYTHONPATH=src python -m keiba_backtest.cli evaluate-final-odds \
  --forecast data/forecasts/2026_kikka_forecast.json \
  --outcome data/outcomes/2026_kikka_result.json \
  --final-odds .local_final_odds/<race-folder>/<snapshot>.json

PYTHONPATH=src python -m keiba_backtest.cli compare-final-odds-batch \
  --forecasts-dir data/forecasts --outcomes-dir data/outcomes \
  --final-odds-dir .local_final_odds
```

The `/private` odds input above must be provided by an authorized analyst;
no vendor odds are supplied by this public repository and no automatic scraping
occurs. Missing data stay missing. See [retrospective market contract](docs/FINAL_ODDS.md).

## 無料の過去最終オッズを使う（Issue #2）

有料のJRA-VAN Data Lab.等を使わない、**ローカルCSV専用**のインポートを追加しました。取得候補は公開KaggleのJRA歴史データ（～2021年）。CSVはPublicのGitHubへアップロードせず、`.local_free_odds/` のローカルDBとして管理します。提供元・元サイトのデータ再配布条件と、実際に取得したCSVの列名を確認してから利用してください。

```bash
PYTHONPATH=src python -m keiba_backtest.cli inspect-free-csv --input /private/odds.csv
PYTHONPATH=src python -m keiba_backtest.cli import-free-csv \
  --odds-csv /private/odds.csv --roster-csv /private/results.csv \
  --mapping /private/columns.json \
  --source-url 'https://www.kaggle.com/datasets/takamotoki/jra-horse-racing-dataset' \
  --db .local_free_odds/market.sqlite3
```

`score-free-csv --db .local_free_odds/market.sqlite3 --import-id <ID>` で全頭突合済みのレースに限り市場単独の診断ができます。**過去の独立モデル予測がない限り、市場と独立モデルの複数レース比較は実施できません。** 実際のKaggleデータの列構造は未確認のため、データのスキーマを仮定せず列名マッピングを指定する契約です。詳細は [無償データ活用手順](docs/FREE_HISTORICAL_CSV.md) を参照してください。
