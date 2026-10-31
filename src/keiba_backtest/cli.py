"""CLI for sealed historical forecast snapshots and proper score evaluation."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .records import load_json, validate_forecast, validate_outcome
from .probability import model_probabilities, scenario_subset
from .scoring import score_forecast, loss
from .temporal import walk_forward
from .diagnostics import reliability_bins, race_bootstrap_loss_difference, summarize_walk_forward
from .historical_features import build_from_file
from .market_capture import capture_to_directory
from .final_odds import import_final_odds, score_against_final_odds, batch_compare_final_odds
from .free_csv import inspect_csv, import_free_csv, score_free_csv
from .kaggle_archive import inspect_archive
from .kaggle_download import download_and_inventory


def _emit(report: object, output: str | None) -> None:
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if output:
        dst = Path(output)
        dst.parent.mkdir(parents=True,exist_ok=True)
        dst.write_text(payload,encoding="utf-8")
        print("Saved",dst)
    else:
        print(payload)


def main(argv: list[str] | None = None) -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    check=sub.add_parser("validate",help="Check ex-ante chronology, identities and normalization")
    check.add_argument("--forecast",required=True)
    check.add_argument("--outcome")
    eval_=sub.add_parser("evaluate",help="Score one frozen forecast, optionally market snapshot")
    eval_.add_argument("--forecast",required=True)
    eval_.add_argument("--outcome",required=True)
    eval_.add_argument("--market",help="Observed full-field odds at or before --decision-at")
    eval_.add_argument("--decision-at",help="Pre-race trading cutoff: sealed quote decision_at, otherwise forecast asof")
    eval_.add_argument("--output")
    sens=sub.add_parser("sensitivity",help="Post-event scenario/temperature diagnostic; NOT model fitting")
    sens.add_argument("--model-inputs",required=True)
    sens.add_argument("--outcome",required=True)
    sens.add_argument("--temperatures",type=float,nargs="+",default=[3,3.75,4.5,6,8])
    sens.add_argument("--output")
    walk=sub.add_parser("walk-forward",help="Chronological evaluation; calibrate on past forecasts only")
    walk.add_argument("--forecasts",required=True,help="Folder containing race forecast JSONs")
    walk.add_argument("--outcomes",required=True,help="Folder containing official outcome JSONs")
    walk.add_argument("--min-train-races",type=int,default=30)
    walk.add_argument("--output")
    hist=sub.add_parser("historical-features", help="Build audited pre-race features from a supplied JSON source bundle")
    hist.add_argument("--input",required=True,help="Historical bundle JSON; no automatic scraping")
    hist.add_argument("--output",help="Feature JSON output")
    hist.add_argument("--allow-unverified",action="store_true",help="Retrospective sources: diagnostic only, never backtest eligible")
    market_capture = sub.add_parser("capture-market", help="Seal a manually supplied market quote using the current system clock")
    market_capture.add_argument("--forecast", required=True, help="Archived pre-race forecast")
    market_capture.add_argument("--input", required=True, help="Manually transcribed full-field odds or unavailable status JSON")
    market_capture.add_argument("--output-dir", required=True, help="Private location; never commit vendor odds")
    final_import = sub.add_parser("import-final-odds", help="Import historical settled win odds, strictly post-race and non-tradable")
    final_import.add_argument("--forecast", required=True)
    final_import.add_argument("--input", required=True, help="Manually supplied historical complete-field final odds JSON")
    final_import.add_argument("--output-dir", required=True, help="Private storage; never commit restricted provider exports")
    final_eval = sub.add_parser("evaluate-final-odds", help="Compare archived forecast to settled final odds, not purchase EV")
    final_eval.add_argument("--forecast", required=True)
    final_eval.add_argument("--outcome", required=True)
    final_eval.add_argument("--final-odds", required=True)
    final_eval.add_argument("--output")
    final_batch = sub.add_parser("compare-final-odds-batch", help="Compare retrospective final market vs original model on paired races only")
    final_batch.add_argument("--forecasts-dir", required=True)
    final_batch.add_argument("--outcomes-dir", required=True)
    final_batch.add_argument("--final-odds-dir", required=True)
    final_batch.add_argument("--output")
    final_batch.add_argument("--selection", help="JSON map of race_id to exact relative sealed snapshot path when duplicates exist")
    kaggle = sub.add_parser("download-free-kaggle", help="Obtain reviewed free dataset via kagglehub and save local SHA256 manifest")
    kaggle.add_argument("--manifest", required=True, help="New private manifest JSON; refuses to overwrite")
    archive_inspect = sub.add_parser("inspect-free-archive", help="Inspect CSV headers in a manually downloaded ZIP without extracting its files")
    archive_inspect.add_argument("--input", required=True)
    archive_inspect.add_argument("--encoding", default="utf-8-sig")
    free_inspect = sub.add_parser("inspect-free-csv", help="Inspect private offline CSV column names without scraping")
    free_inspect.add_argument("--input", required=True)
    free_inspect.add_argument("--encoding", default="utf-8-sig")
    free_import = sub.add_parser("import-free-csv", help="Import free historical CSV odds into a private, offline SQLite index")
    free_import.add_argument("--odds-csv", required=True)
    free_import.add_argument("--roster-csv", help="Independent result roster CSV for full-field and winner verification")
    free_import.add_argument("--mapping", required=True, help="Exact column-name map; never guess provider schema")
    free_import.add_argument("--source-url", required=True, help="Free dataset webpage HTTPS URL")
    free_import.add_argument("--source-label", default="free historical CSV; provenance not independently verified")
    free_import.add_argument("--db", default=".local_free_odds/market.sqlite3")
    free_import.add_argument("--encoding", default="utf-8-sig")
    free_import.add_argument("--output")
    free_score = sub.add_parser("score-free-csv", help="Market-only retrospective scores for complete roster-matched historical CSV races")
    free_score.add_argument("--db", default=".local_free_odds/market.sqlite3")
    free_score.add_argument("--import-id", required=True)
    free_score.add_argument("--output")
    args=parser.parse_args(argv)
    if args.command=="download-free-kaggle":
        _emit(download_and_inventory(output=args.manifest), None)
    elif args.command=="inspect-free-archive":
        _emit(inspect_archive(args.input, encoding=args.encoding), None)
    elif args.command=="inspect-free-csv":
        _emit(inspect_csv(args.input, encoding=args.encoding), None)
    elif args.command=="import-free-csv":
        report=import_free_csv(odds_csv=args.odds_csv, roster_csv=args.roster_csv,
                               db=args.db, mapping_file=args.mapping, source_url=args.source_url,
                               source_label=args.source_label, encoding=args.encoding)
        _emit(report, args.output)
    elif args.command=="score-free-csv":
        _emit(score_free_csv(db=args.db, import_id=args.import_id), args.output)
    elif args.command=="compare-final-odds-batch":
        selection = load_json(args.selection) if args.selection else None
        result = batch_compare_final_odds(args.forecasts_dir, args.outcomes_dir,
                                          args.final_odds_dir, selection=selection)
        _emit(result, args.output)
    elif args.command=="import-final-odds":
        forecast = load_json(args.forecast)
        saved = import_final_odds(args.input, forecast, args.output_dir)
        print("IMPORTED_FINAL_ODDS", saved)
    elif args.command=="evaluate-final-odds":
        result = score_against_final_odds(load_json(args.forecast), load_json(args.outcome), load_json(args.final_odds))
        _emit(result, args.output)
    elif args.command=="capture-market":
        forecast = load_json(args.forecast)
        saved = capture_to_directory(args.input, forecast, args.output_dir)
        print("CAPTURED", saved)
    elif args.command=="historical-features":
        result=build_from_file(args.input,allow_unverified=args.allow_unverified)
        _emit(result,args.output)
    elif args.command=="validate":
        f=load_json(args.forecast)
        validate_forecast(f)
        if args.outcome:
            validate_outcome(load_json(args.outcome),f)
        print("VALIDATED",f["race_id"],"asof",f["asof"])
    elif args.command=="evaluate":
        f=load_json(args.forecast)
        o=load_json(args.outcome)
        market=load_json(args.market) if args.market else None
        report=score_forecast(f,o,market,decision_at=args.decision_at)
        _emit(report,args.output)
    elif args.command=="sensitivity":
        d=load_json(args.model_inputs)
        o=load_json(args.outcome)
        numbers=list(range(1,len(d["names"])+1))
        winner_index=numbers.index(o["finishing_order"][0])
        report={"race_id":o["race_id"],"status":"HINDSIGHT_DIAGNOSTIC_NOT_TRAINING",
                "warning":"Scenarios are evaluated after race results; no parameter is selected or recommended from this table.",
                "variants":[]}
        for t in args.temperatures:
            for ground in ["all","dry","wet"]:
                p=model_probabilities(d,temperature=t,scenarios=scenario_subset(d,ground))["win"]
                report["variants"].append({"temperature":t,"ground":ground,
                                            "winner_probability":p[winner_index],
                                            **loss(p,winner_index)})
        _emit(report,args.output)
    elif args.command=="walk-forward":
        forecasts = {}
        outcomes = {}
        for path in Path(args.forecasts).glob("*.json"):
            f=load_json(path)
            if "race_id" in f and "runners" in f:
                if f["race_id"] in forecasts:
                    raise ValueError("Duplicate forecast race_id")
                forecasts[f["race_id"]]=f
        for path in Path(args.outcomes).glob("*.json"):
            o=load_json(path)
            if "race_id" in o and "finishing_order" in o:
                if o["race_id"] in outcomes:
                    raise ValueError("Duplicate outcome race_id")
                outcomes[o["race_id"]]=o
        records=[(f,outcomes[race_id]) for race_id,f in forecasts.items() if race_id in outcomes]
        wf=walk_forward(records,min_train_races=args.min_train_races)
        result={"paired_races":len(records),"forecasts_missing_outcomes":sorted(set(forecasts)-set(outcomes)),
                "results_missing_forecasts":sorted(set(outcomes)-set(forecasts)),
                "summary":summarize_walk_forward(wf),
                "calibration_bins":reliability_bins(records),
                "bootstrap_raw_vs_uniform":race_bootstrap_loss_difference(records),
                "walk_forward":wf}
        _emit(result,args.output)

if __name__ == "__main__":
    main()
