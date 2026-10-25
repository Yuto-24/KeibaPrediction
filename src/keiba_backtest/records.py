"""Strict source/time/identity validation for forecast and outcome snapshots."""
from __future__ import annotations
from datetime import datetime
import json
import math
from pathlib import Path
from typing import Any


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _timestamp(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("timestamps must have timezone offsets: " + value)
    return dt


def validate_forecast(f: dict[str, Any]) -> None:
    if not f.get("race_id") or not f.get("origin_source"):
        raise ValueError("race_id and origin_source required")
    cutoff = _timestamp(f["asof"])
    race_at = _timestamp(f["race_at"])
    if cutoff >= race_at:
        raise ValueError("forecast was not available before race start")
    rows = f["runners"]
    if len(rows) < 2:
        raise ValueError("at least two runners required")
    numbers = [r["number"] for r in rows]
    if any(not isinstance(i, int) or isinstance(i, bool) or i < 1 for i in numbers):
        raise ValueError("invalid horse number")
    if len(set(numbers)) != len(numbers):
        raise ValueError("duplicate horse number")
    p = [r["win_probability"] for r in rows]
    if any(not isinstance(q, (float, int)) or isinstance(q, bool) or not math.isfinite(q) or q < 0 or q > 1 for q in p):
        raise ValueError("invalid win probability")
    if not math.isclose(sum(p), 1., abs_tol=1e-9):
        raise ValueError("win probabilities must sum to one")
    for key, k in [("top2_probability", 2), ("top3_probability", 3)]:
        present = [key in r for r in rows]
        if any(present) != all(present):
            raise ValueError("incomplete " + key)
        if all(present):
            if len(rows) < k:
                raise ValueError("not enough runners")
            vals = [r[key] for r in rows]
            if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 or v > 1+1e-9 for v in vals):
                raise ValueError("invalid " + key)
            if not math.isclose(sum(vals), k, abs_tol=1e-9):
                raise ValueError(f"{key} must sum to {k}")
    for r in rows:
        if not r.get("name"):
            raise ValueError("missing horse name")
        a, b = r["win_probability"], r.get("top2_probability", 1)
        c = r.get("top3_probability", 1)
        if not (a <= b + 1e-9 and b <= c + 1e-9):
            raise ValueError("inconsistent marginal probabilities")
    # Optional source timestamps (must be observed by cutoff).
    for fpart in f.get("features", []):
        if _timestamp(fpart["available_at"]) > cutoff:
            raise ValueError("feature lookahead: " + str(fpart.get("name")))


def validate_outcome(outcome: dict[str, Any], forecast: dict[str, Any]) -> None:
    validate_forecast(forecast)
    if outcome["race_id"] != forecast["race_id"]:
        raise ValueError("outcome race_id does not match")
    if not outcome.get("source_url") or outcome.get("status") != "official_final":
        raise ValueError("official final source required")
    results = outcome["finishing_order"]
    runners = forecast["runners"]
    expected = {r["number"] for r in runners}
    if set(results) != expected or len(results) != len(expected):
        raise ValueError("finishing order must contain exactly the runners once")


def validate_market(quote: dict[str, Any], forecast: dict[str, Any],
                    *, decision_at: str | None = None) -> None:
    validate_forecast(forecast)
    if quote["race_id"] != forecast["race_id"]:
        raise ValueError("market race mismatch")
    cutoff = _timestamp(decision_at or forecast["asof"])
    if cutoff >= _timestamp(forecast["race_at"]):
        raise ValueError("decision cutoff must be before race start")
    if _timestamp(forecast["asof"]) > cutoff:
        raise ValueError("forecast was not available at decision cutoff")
    # Caller must explicitly request a decision later than the archived forecast.
    if _timestamp(quote["observed_at"]) > cutoff:
        raise ValueError("market quote after decision cutoff (lookahead)")
    if not quote.get("source_url"):
        raise ValueError("market source URL missing")
    values = quote["decimal_win_odds"]
    expected = {str(r["number"]) for r in forecast["runners"]}
    if set(values) != expected:
        raise ValueError("missing/unknown market odds for runners")
    if any(not isinstance(x, (int,float)) or isinstance(x,bool) or not math.isfinite(x) or x < 1.0 for x in values.values()):
        raise ValueError("invalid decimal odds")


def forecast_from_legacy(inputs: dict[str, Any], race_id: str, race_at: str,
                         asof: str, source: str, source_sha256: str) -> dict[str, Any]:
    from .probability import model_probabilities
    probs = model_probabilities(inputs)
    rows = [{"number": i+1, "name": name,
             "win_probability": probs["win"][i],
             "top2_probability": probs["top2"][i],
             "top3_probability": probs["top3"][i]}
            for i, name in enumerate(inputs["names"])]
    f = {"race_id": race_id, "race_at": race_at, "asof": asof,
         "origin_source": source, "original_model_sha256": source_sha256,
         "model_version": "2026-kikka-subjective-PL-T3.75-frozen",
         "reconstruction_note": "Retrospectively regenerated verbatim from a pre-race archived report. Not a new ex-ante prediction.",
         "runners": rows}
    validate_forecast(f)
    return f
