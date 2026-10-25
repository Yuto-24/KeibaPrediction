"""Race-clustered evaluation diagnostics (not estimates from one race)."""
from __future__ import annotations
import random
from typing import Any
from .records import validate_outcome
from .scoring import score_forecast

PROBABILITY_BINS = (0., .025, .05, .10, .20, .35, .50, 1.000000001)


def reliability_bins(records: list[tuple[dict[str, Any], dict[str, Any]]],
                     edges: tuple[float, ...] = PROBABILITY_BINS) -> dict[str, Any]:
    """Reliability bins across runners; do not infer CIs treating runners as iid."""
    if len(edges) < 2 or edges[0] != 0 or edges[-1] < 1 or list(edges) != sorted(set(edges)):
        raise ValueError("invalid bin edges")
    if len({f['race_id'] for f,_ in records}) != len(records):
        raise ValueError("duplicate race: do not treat repeated runners as independent evidence")
    acc = [{"lower": edges[i], "upper": edges[i+1], "count": 0,
            "sum_forecast_probability":0., "observed_wins": 0} for i in range(len(edges)-1)]
    for f,o in records:
        validate_outcome(o,f)
        winner = o["finishing_order"][0]
        for runner in f["runners"]:
            probability=runner["win_probability"]
            for b in acc:
                if b['lower'] <= probability < b['upper']:
                    b['count'] += 1
                    b['sum_forecast_probability'] += probability
                    b['observed_wins'] += int(runner['number'] == winner)
                    break
            else:
                raise ValueError("probability not inside bin range")
    for b in acc:
        count = b['count']
        b['mean_forecast_probability'] = b['sum_forecast_probability']/count if count else None
        b['observed_win_rate'] = b['observed_wins']/count if count else None
        b['sum_forecast_probability']=round(b['sum_forecast_probability'],12)
    return {"race_count":len(records),"note":"Exploratory bins only. Runners within a race are dependent; do not use iid horse-level confidence intervals.","bins":acc}


def race_bootstrap_loss_difference(records: list[tuple[dict[str, Any],dict[str, Any]]],
                                   *, baseline: str = "uniform", n_resamples: int = 2000,
                                   seed: int = 42, min_races: int = 30) -> dict[str, Any]:
    """Bootstrap paired race-level raw minus comparison log loss; 95% percentile interval."""
    if baseline not in ('uniform',):
        raise ValueError("available comparator: uniform")
    if n_resamples < 100:
        raise ValueError("minimum 100 bootstrap resamples")
    if len({f['race_id'] for f,_ in records}) != len(records):
        raise ValueError("duplicate race in bootstrap sample")
    n = len(records)
    if n < min_races:
        return {"status":"not_computed","race_count":n,
                "reason":f"Requires at least {min_races} races for this initial guardrail (not a power guarantee)."}
    differences = []
    for f,o in records:
        s=score_forecast(f,o)
        differences.append(s['model']['log_loss']-s[baseline]['log_loss'])
    rng=random.Random(seed)
    means=[]
    for _ in range(n_resamples):
        means.append(sum(differences[rng.randrange(n)] for _ in range(n))/n)
    means.sort()
    return {"status":"computed","race_count":n,"baseline":baseline,
            "mean_log_loss_difference":sum(differences)/n,
            "95pct_percentile_interval":[means[int(n_resamples*.025)],means[int(n_resamples*.975)-1]],
            "method":"paired bootstrap by race; outcome leakage checked separately",
            "n_resamples":n_resamples,"seed":seed}


def summarize_walk_forward(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"race_count":0, "note":"No paired forecasts/outcomes"}
    model_avg = sum(r['raw']['log_loss'] for r in rows) / len(rows)
    uniform_avg = sum(r['uniform']['log_loss'] for r in rows) / len(rows)
    cal_rows = [r for r in rows if r['calibrated'] is not None]
    return {"race_count":len(rows),"calibrated_test_races":len(cal_rows),
            "raw_mean_log_loss":model_avg, "uniform_mean_log_loss":uniform_avg,
            "calibrated_mean_log_loss_on_eligible_races":
                sum(r['calibrated']['log_loss'] for r in cal_rows)/len(cal_rows) if cal_rows else None,
            "raw_mean_log_loss_on_calibration_eligible_races":
                sum(r['raw']['log_loss'] for r in cal_rows)/len(cal_rows) if cal_rows else None,
            "note":"When comparing calibrated vs raw, compare ONLY the common eligible races."}
