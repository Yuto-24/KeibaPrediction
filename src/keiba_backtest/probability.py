"""Original Kikka Sho score-to-probability model; no parameter learning occurs here.

The functions are pure and require no third-party packages. Each race is
represented as one mutually exclusive winner distribution. Top-2 / top-3
probabilities are calculated under the SAME scenario mixture and ranking law,
not by multiplying win probabilities.
"""
from __future__ import annotations
import math
from typing import Any


def _softmax(scores: list[float], temperature: float) -> list[float]:
    if not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("temperature must be finite and positive")
    center = max(scores)
    weights = [math.exp((x - center) / temperature) for x in scores]
    z = sum(weights)
    return [x / z for x in weights]


def model_probabilities(inputs: dict[str, Any], temperature: float | None = None,
                        *, scenarios: list[dict[str, Any]] | None = None
                        ) -> dict[str, list[float]]:
    """Compute exact top-1/2/3 marginals of a mixture of Plackett-Luce laws."""
    base = inputs["scores"]
    n = len(inputs["names"])
    if n < 2 or len(base) != n or len(inputs["wet"]) != n:
        raise ValueError("invalid runner arrays")
    t = inputs["temperature"] if temperature is None else temperature
    selected = scenarios if scenarios is not None else inputs["scenarios"]
    if not selected or not math.isclose(sum(s["p"] for s in selected), 1., abs_tol=1e-9):
        raise ValueError("scenario weights must sum to 1")
    win, top2, top3 = ([0.] * n for _ in range(3))
    for scenario in selected:
        if len(scenario["pace"]) != n or scenario["p"] < 0:
            raise ValueError("invalid scenario")
        scores = [base[i] + scenario["pace"][i]
                  + scenario["wet"] * inputs["wet"][i] for i in range(n)]
        p = _softmax(scores, t)
        weight = scenario["p"]
        for i in range(n):
            win[i] += weight * p[i]
            top2[i] += weight * p[i]
            top3[i] += weight * p[i]
        for first in range(n):
            p_first = p[first]
            den1 = 1. - p_first
            for second in range(n):
                if second == first:
                    continue
                pair = weight * p_first * p[second] / den1
                top2[second] += pair
                top3[second] += pair
                den2 = den1 - p[second]
                for third in range(n):
                    if third == first or third == second:
                        continue
                    top3[third] += pair * p[third] / den2
    assert math.isclose(sum(win), 1, abs_tol=1e-10)
    assert math.isclose(sum(top2), 2, abs_tol=1e-10)
    assert math.isclose(sum(top3), 3, abs_tol=1e-10)
    assert all(0 <= win[i] <= top2[i] <= top3[i] <= 1 + 1e-10 for i in range(n))
    return {"win": win, "top2": top2, "top3": top3}


def scenario_subset(inputs: dict[str, Any], label: str) -> list[dict[str, Any]]:
    """Filter frozen scenario inputs (diagnostic, NEVER an ex-ante update)."""
    if label == "all":
        return inputs["scenarios"]
    wet = {"dry": 0, "wet": 1}.get(label)
    if wet is None:
        raise ValueError("subset must be all, dry or wet")
    candidates = [s for s in inputs["scenarios"] if s["wet"] == wet]
    total = sum(s["p"] for s in candidates)
    return [{**s, "p": s["p"] / total} for s in candidates]
