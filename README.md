# 競馬予測のバックテスト基盤（初版）

2026年菊花賞の**実際にレース前に保存された主観評価モデル**を出発点として、確率の校正とリークのない時系列検証を行うための最小構成です。外部パッケージなしのPython 3.10以降で実行できます。データの自動スクレイピング、馬券購入、結果を使った新規予想は行いません。

## 今回の到達点

- 2026-10-23に保存された菊花賞予想の入力から、18頭の勝率／連対率／3着以内率を再現。
- 2026-10-25のJRA確定着順と照合。元モデルのLog Loss / multiclass Brier Scoreを算出。
- 実際の馬場を使った計算や温度変更は**結果判明後の感度分析**として明示的に隔離。
- 確率校正・レース単位の信頼性集計・ブートストラップ・ウォークフォワード検証のコードを実装。
- 事前予測が現在1レースしかないため、**学習・校正・統計的有意性評価はまだ実施できない**。最小30レースの初期ガードレールにより校正が自動スキップされる。
- 過去年3レース（2023～2025）の**結果ラベルのみ**保存。事前予測がない以上、これらを独立モデルのバックテストに使わない。
- 購入判断時点の実売オッズのスナップショットがなく、市場モデルとの公正な比較は**未実施**。

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

## 2026年の採点

- 原本再現：⑧勝率36.9285%、⑨勝率6.1526%。勝率合計100%、連対率合計200%、3着以内率合計300%。
- ⑨勝利に対するLog Lossは **2.788293**、multiclass Brier（各馬の二乗誤差を合計）は **1.058388**。
- 18頭均等予測のLog Lossは **2.890372**、Brierは **0.944444**。
- 結果を知ってから「乾いた条件のみ」を指定した参考計算は⑨8.37%。これは**モデル改善のバックテスト結果ではありません**。

## 過去レースの追加と検証条件

1. 予想対象の発走前に、予想生成時刻・モデル版・全出走馬の非丸め勝率・データ取得時刻を保存。確率合計は厳密に1とする。
2. 発走後は、対象レースの公式着順と結果が利用可能になった日時を別に記録。
3. 市場オッズを比較する場合、**判断時点以前に実際に取得した全頭の単勝オッズ**を保存する。最終払戻から復元した価格を、購入時に知っていた価格として使用しない。
4. 検証レースより前に予想と結果が存在するデータのみを学習に使用する。過去30レース未満なら校正は行わない（この閾値は十分性を保証するものではない）。
5. 係数を変更する場合は学習・モデル選択・テストを時系列で分離。2026年菊花賞の結果を使って係数を合わせた後、同レースの改善スコアを独立性能として主張しない。

### 評価で比べるもの

- `raw`: 予想当時に保存された独立モデルの確率。
- `uniform`: 全出走馬の勝率を均等にした基準。
- `market`: **レース前に時刻付きで保存した**全頭オッズの逆数を正規化した基準。市場の控除と偏りを完全には補正しない。モデルが先に確定していた場合、後の価格と比較するには `--decision-at` を明示し、情報時点の違いを記録する。
- `calibrated`: 既知の過去レースだけでpower exponentを学習し、未知レースに適用した確率。

`calibrated` と `raw` の比較は**同じテストレース集合**で行います。

## 残る制約

元の独自能力点は過去データから算出した客観指標ではありません。シナリオ重みや距離補正も未校正です。現行基盤が正しく機能することと、元モデルの予測精度が高いことは別です。最終馬場などの結果を事前特徴量へ混ぜることも禁止しています。

本番適用に向けた次の作業は、再現できる特徴量生成（すべて当該レース前日時基準）、十分な過去レースの予測再構築、ウォークフォワード検証、実売価格の時点記録です。まだ市場を上回る優位性を確認できていません。
