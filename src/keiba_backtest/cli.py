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
    eval_.add_argument("--decision-at",help="Trading cutoff earlier than race start; defaults to forecast asof")
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
    args=parser.parse_args(argv)
    if args.command=="historical-features":
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
