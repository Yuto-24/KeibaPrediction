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
    """Check chronological validity and complete, non-corrupted odds.

    Sealed snapshots have their own decision time. Legacy unsealed quotes remain
    available only for compatibility/testing; scoring labels them unverified.
    """
    validate_forecast(forecast)
    if quote.get("odds_kind") == "settled_final_win_odds":
        raise ValueError("settled final odds are not an observed pre-race market quote")
    if quote["race_id"] != forecast["race_id"]:
        raise ValueError("market race mismatch")
    start = _timestamp(forecast["race_at"])
    forecast_at = _timestamp(forecast["asof"])
    cutoff = _timestamp(decision_at or quote.get("decision_at") or forecast["asof"])
    observed = _timestamp(quote["observed_at"])
    if not (forecast_at <= observed <= cutoff < start):
        raise ValueError("market chronology violation: forecast.asof <= observed_at <= decision_at < race_at required")
    if not isinstance(quote.get("source_url"), str) or not quote["source_url"]:
        raise ValueError("market source URL missing")
    if "schema_version" in quote or "snapshot_sha256" in quote:
        from .market_capture import verify_seal
        if quote.get("schema_version") != 1 or quote.get("capture_method") != "manual_transcription":
            raise ValueError("unsupported sealed market snapshot")
        if quote.get("evidence_level") != "SELF_REPORTED_NOT_INDEPENDENTLY_VERIFIED":
            raise ValueError("invalid market provenance classification")
        if not isinstance(quote.get("input_sha256"), str) or len(quote["input_sha256"]) != 64:
            raise ValueError("invalid market input digest")
        if _timestamp(quote["captured_at"]) != observed:
            raise ValueError("sealed snapshot captured_at must match observed_at")
        sealed_decision = _timestamp(quote["decision_at"])
        if sealed_decision != observed:
            raise ValueError("sealed snapshot decision_at must equal capture time")
        verify_seal(quote)
    status = quote.get("status", "available")
    if status == "not_available":
        if "decimal_win_odds" in quote or not quote.get("reason"):
            raise ValueError("not_available must have a reason and no odds")
        return
    if status != "available":
        raise ValueError("invalid market status")
    values = quote["decimal_win_odds"]
    if not isinstance(values, dict):
        raise ValueError("decimal_win_odds must be a mapping")
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
