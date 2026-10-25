"""Proper scoring rules and market-only baseline (not a betting-profit proxy)."""
from __future__ import annotations
import math
from typing import Any
from .records import validate_forecast, validate_outcome, validate_market, _timestamp


def normalize(values: list[float]) -> list[float]:
    if not values or any(not math.isfinite(x) or x < 0 for x in values):
        raise ValueError("invalid probabilities")
    total = sum(values)
    if total <= 0:
        raise ValueError("all probability mass is zero")
    return [v / total for v in values]


def uniform_probabilities(n: int) -> list[float]:
    if n < 2:
        raise ValueError("at least 2 starters")
    return [1.0/n] * n


def market_probabilities(quote: dict[str, Any], forecast: dict[str, Any],
                         *, decision_at: str | None = None) -> list[float]:
    """Normalized inverse odds, with an explicit as-of trading decision cutoff."""
    validate_market(quote, forecast, decision_at=decision_at)
    return normalize([1./quote["decimal_win_odds"][str(r["number"])] for r in forecast["runners"]])


def power_calibrate(p: list[float], exponent: float) -> list[float]:
    """Power calibration on a race simplex. >1 sharpens, <1 flattens."""
    if not math.isfinite(exponent) or exponent <= 0:
        raise ValueError("exponent must be positive")
    # Stable log normalization supports distributions with tiny but nonzero values.
    transformed = [exponent * math.log(max(x, 1e-300)) for x in p]
    max_t = max(transformed)
    return normalize([math.exp(x-max_t) for x in transformed])


def loss(p: list[float], winner_index: int) -> dict[str, float]:
    if len(p) < 2 or not 0 <= winner_index < len(p) or any(not math.isfinite(x) or x < 0 for x in p):
        raise ValueError("invalid win probabilities")
    if not math.isclose(sum(p), 1, abs_tol=1e-9):
        raise ValueError("win probabilities not normalized")
    target = [float(i == winner_index) for i in range(len(p))]
    return {"log_loss": -math.log(max(p[winner_index], 1e-300)),
            "brier_multiclass_sum": sum((pi-ti)**2 for pi,ti in zip(p,target)),
            "winner_probability": p[winner_index]}


def score_forecast(forecast: dict[str, Any], outcome: dict[str, Any],
                   market: dict[str, Any] | None = None,
                   *, decision_at: str | None = None) -> dict[str, Any]:
    validate_outcome(outcome, forecast)
    numbers = [r["number"] for r in forecast["runners"]]
    win_index = numbers.index(outcome["finishing_order"][0])
    p = [r["win_probability"] for r in forecast["runners"]]
    out = {"race_id": forecast["race_id"], "asof": forecast["asof"],
           "n_runners": len(numbers), "winner_number": numbers[win_index],
           "model": loss(p, win_index),
           "uniform": loss(uniform_probabilities(len(numbers)), win_index)}
    if market is not None:
        out["market"] = loss(market_probabilities(market, forecast, decision_at=decision_at), win_index)
        out["market"]["observed_at"] = market["observed_at"]
        out["market"]["decision_at"] = decision_at or forecast["asof"]
        out["market"]["forecast_asof"] = forecast["asof"]
        out["market"]["market_has_later_information"] = _timestamp(market["observed_at"]) > _timestamp(forecast["asof"])
    for key, top_k in (("top2_probability",2),("top3_probability",3)):
        if all(key in r for r in forecast["runners"]):
            subset = set(outcome["finishing_order"][:top_k])
            out["model"][f"top{top_k}_brier_multilabel_sum"] = sum(
                (r[key] - (r["number"] in subset))**2 for r in forecast["runners"])
            out["uniform"][f"top{top_k}_brier_multilabel_sum"] = sum(
                (top_k/len(numbers) - (number in subset))**2 for number in numbers)
    return out
