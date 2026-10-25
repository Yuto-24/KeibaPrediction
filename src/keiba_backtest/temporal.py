"""Walk-forward probability recalibration; each validation race is future-held-out.

The only fit here is a power exponent learned on PAST forecasts/outcomes.
It cannot create historical forecasts that did not exist. Minimum race count is
explicit and enforced. No lookahead or final-odds substitution is supported.
"""
from __future__ import annotations
from collections.abc import Iterable
from typing import Any
from .records import _timestamp, validate_outcome
from .scoring import loss, power_calibrate, score_forecast

CANDIDATE_EXPONENTS = (0.4, 0.55, 0.7, 0.85, 1., 1.15, 1.3, 1.5, 1.75, 2.0)


def _paired_losses(records: Iterable[tuple[dict[str, Any], dict[str, Any]]],
                   exponent: float) -> list[float]:
    values = []
    for f, o in records:
        numbers = [r["number"] for r in f["runners"]]
        p = [r["win_probability"] for r in f["runners"]]
        winner_index = numbers.index(o["finishing_order"][0])
        values.append(loss(power_calibrate(p, exponent), winner_index)["log_loss"])
    return values


def fit_exponent(records: list[tuple[dict[str, Any],dict[str, Any]]],
                 *, min_train_races: int = 30) -> dict[str, Any]:
    if min_train_races < 2:
        raise ValueError("min_train_races must be at least 2")
    for f, o in records:
        validate_outcome(o, f)
    if len({f["race_id"] for f, _ in records}) != len(records):
        raise ValueError("duplicate race in calibration training data")
    if len(records) < min_train_races:
        raise ValueError(f"Insufficient historical forecasts: {len(records)} < {min_train_races}")
    scores = {a: sum(_paired_losses(records,a))/len(records) for a in CANDIDATE_EXPONENTS}
    exponent = min(CANDIDATE_EXPONENTS, key=lambda v: (scores[v], abs(v-1)))
    return {"exponent": exponent, "training_races": len(records),
            "train_mean_log_loss": scores[exponent],
            "method": "fixed-grid power calibration; training data ONLY"}


def walk_forward(records: list[tuple[dict[str, Any],dict[str, Any]]],
                 *, min_train_races: int = 30) -> list[dict[str, Any]]:
    """Test in chronological order; train only outcomes usable before forecast asof."""
    if min_train_races < 2:
        raise ValueError("min_train_races must be >= 2")
    seen = set()
    for f,o in records:
        validate_outcome(o,f)
        if f["race_id"] in seen:
            raise ValueError("duplicate forecast for race")
        seen.add(f["race_id"])
        if "result_usable_after" not in o:
            raise ValueError("outcome result_usable_after required for walk-forward")
        if _timestamp(o["result_usable_after"]) <= _timestamp(f["race_at"]):
            raise ValueError("outcome must become usable after race start")
    ordered = sorted(records, key=lambda x: _timestamp(x[0]["race_at"]))
    outputs = []
    for forecast, outcome in ordered:
        cutoff = _timestamp(forecast["asof"])
        past = [(f,o) for f,o in ordered if
                f["race_id"] != forecast["race_id"] and
                _timestamp(f["race_at"]) < cutoff and
                _timestamp(o["result_usable_after"]) <= cutoff]
        base = score_forecast(forecast, outcome)
        result = {"race_id": forecast["race_id"], "forecast_asof": forecast["asof"],
                  "raw": base["model"], "uniform": base["uniform"],
                  "n_train_races": len(past), "calibrated": None}
        if len(past) >= min_train_races:
            info = fit_exponent(past, min_train_races=min_train_races)
            numbers = [r["number"] for r in forecast["runners"]]
            p = power_calibrate([r["win_probability"] for r in forecast["runners"]], info["exponent"])
            result["calibrated"] = {
                **loss(p, numbers.index(outcome["finishing_order"][0])), **info}
        else:
            result["calibration_skipped"] = (
                f"past races with pre-race forecast + settled result: {len(past)}; "
                f"need at least {min_train_races}. No parameter tuned.")
        outputs.append(result)
    return outputs
