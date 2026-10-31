"""Historical *settled* win odds for a market forecasting baseline.

Final odds are an outcome-era market summary, never a tradable pre-race quote.
Import does not access websites; licensing and source authenticity remain external.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Callable
from urllib.parse import urlsplit

from .market_capture import canonical_bytes
from .records import _timestamp, validate_forecast, validate_outcome
from .scoring import loss, normalize, score_forecast

_VERSION = 1
_INPUT_KEYS = {"race_id", "source_url", "source_label", "status", "decimal_win_odds", "reason"}
_HEX_SHA = re.compile(r"[0-9a-f]{64}\Z")
_FILENAME_ID = re.compile(r"[A-Za-z0-9:_-]{1,128}\Z")


def validate_final_odds(data: dict[str, Any], forecast: dict[str, Any]) -> None:
    """Validate completeness and integrity but never claim source authentication."""
    validate_forecast(forecast)
    if not isinstance(data, dict):
        raise ValueError("final odds must be a JSON object")
    expected_keys = {"schema_version", "odds_kind", "race_id", "source_url", "retrieved_at",
                     "collection_method", "provenance", "status", "input_sha256", "snapshot_sha256",
                     "decimal_win_odds", "reason", "source_label"}
    if set(data) - expected_keys:
        raise ValueError("unknown final odds field(s)")
    if data.get("schema_version") != _VERSION or type(data.get("schema_version")) is not int:
        raise ValueError("unsupported final odds schema")
    if data.get("odds_kind") != "settled_final_win_odds":
        raise ValueError("expected settled final win odds")
    if data.get("race_id") != forecast["race_id"]:
        raise ValueError("final odds race mismatch")
    if data.get("collection_method") != "retrospective_manual_import":
        raise ValueError("unsupported final odds collection method")
    if data.get("provenance") != "MANUALLY_TRANSCRIBED_POST_RACE_NOT_SOURCE_VERIFIED":
        raise ValueError("invalid final odds provenance")
    source = data.get("source_url")
    if not isinstance(source, str) or urlsplit(source).scheme != "https" or not urlsplit(source).hostname:
        raise ValueError("final odds requires HTTPS source_url")
    if "source_label" in data and (not isinstance(data["source_label"], str) or not data["source_label"].strip()):
        raise ValueError("invalid final odds source_label")
    retrieved = _timestamp(data["retrieved_at"])
    if retrieved < _timestamp(forecast["race_at"]):
        raise ValueError("final odds cannot be collected before race start")
    if retrieved > datetime.now(timezone.utc):
        raise ValueError("final odds retrieved_at cannot be in the future")
    for name in ("snapshot_sha256", "input_sha256"):
        val = data.get(name)
        if not isinstance(val, str) or not _HEX_SHA.fullmatch(val):
            raise ValueError("invalid " + name)
    actual = hashlib.sha256(canonical_bytes({k: v for k, v in data.items() if k != "snapshot_sha256"})).hexdigest()
    if actual != data["snapshot_sha256"]:
        raise ValueError("final odds snapshot integrity check failed")
    status = data.get("status")
    if status == "not_available":
        if "decimal_win_odds" in data or not isinstance(data.get("reason"), str) or not data["reason"].strip():
            raise ValueError("unavailable final odds require a reason and no prices")
        return
    if status != "available" or "reason" in data:
        raise ValueError("invalid final odds status")
    odds = data.get("decimal_win_odds")
    required = {str(r["number"]) for r in forecast["runners"]}
    if not isinstance(odds, dict) or set(odds) != required:
        raise ValueError("final odds must cover exactly all forecast runners")
    if any(type(x) not in (int, float) or not math.isfinite(x) or x < 1.0 for x in odds.values()):
        raise ValueError("final win odds must be finite decimal values >= 1.0")


def build_final_odds_snapshot(input_data: dict[str, Any], forecast: dict[str, Any],
                              *, retrieved_at: datetime,
                              input_sha256: str | None = None) -> dict[str, Any]:
    """Construct a retrospective quote; the timestamp is *import time*, not betting time."""
    validate_forecast(forecast)
    if not isinstance(input_data, dict) or set(input_data) - _INPUT_KEYS:
        raise ValueError("unknown final odds input field(s)")
    if input_data.get("race_id") != forecast["race_id"]:
        raise ValueError("final odds race mismatch")
    if not isinstance(retrieved_at, datetime) or retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise ValueError("retrieved_at must be timezone-aware")
    retrieved_utc = retrieved_at.astimezone(timezone.utc).isoformat(timespec="microseconds")
    if input_sha256 is None:
        # Only in-memory callers without a source file use canonical JSON hashing.
        input_sha256 = hashlib.sha256(canonical_bytes(input_data)).hexdigest()
    if not _HEX_SHA.fullmatch(input_sha256):
        raise ValueError("input_sha256 must be SHA-256 of original input bytes")
    output = {
        "schema_version": _VERSION,
        "odds_kind": "settled_final_win_odds",
        "race_id": input_data["race_id"],
        "source_url": input_data.get("source_url"),
        "retrieved_at": retrieved_utc,
        "collection_method": "retrospective_manual_import",
        "provenance": "MANUALLY_TRANSCRIBED_POST_RACE_NOT_SOURCE_VERIFIED",
        "status": input_data.get("status"),
        "input_sha256": input_sha256,
    }
    if "source_label" in input_data:
        output["source_label"] = input_data["source_label"]
    if input_data.get("status") == "available":
        output["decimal_win_odds"] = input_data.get("decimal_win_odds")
    elif input_data.get("status") == "not_available":
        output["reason"] = input_data.get("reason")
    output["snapshot_sha256"] = hashlib.sha256(canonical_bytes(output)).hexdigest()
    validate_final_odds(output, forecast)
    return output


def import_final_odds(input_file: str | Path, forecast: dict[str, Any], output_dir: str | Path,
                      *, clock: Callable[[], datetime] | None = None) -> Path:
    """Append-only local import. No network access; no user-supplied backdated clock."""
    if clock is None:
        clock = lambda: datetime.now(timezone.utc)
    raw = Path(input_file).read_bytes()
    data = json.loads(raw)
    snapshot = build_final_odds_snapshot(data, forecast, retrieved_at=clock(),
                                         input_sha256=hashlib.sha256(raw).hexdigest())
    race_id = snapshot["race_id"]
    if not _FILENAME_ID.fullmatch(race_id):
        raise ValueError("race_id is not filename-safe")
    directory = Path(output_dir) / (race_id.replace(":", "-") + "_" + hashlib.sha256(race_id.encode()).hexdigest()[:12])
    directory.mkdir(parents=True, exist_ok=True)
    stamp = _timestamp(snapshot["retrieved_at"]).strftime("%Y%m%dT%H%M%S%fZ")
    dest = directory / (stamp + "_" + snapshot["snapshot_sha256"] + ".json")
    payload = json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False).encode() + b"\n"
    fd = os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return dest


def score_against_final_odds(forecast: dict[str, Any], outcome: dict[str, Any],
                            final: dict[str, Any]) -> dict[str, Any]:
    """Compare two *information windows*, never estimate a tradable return."""
    validate_outcome(outcome, forecast)
    validate_final_odds(final, forecast)
    out = score_forecast(forecast, outcome)
    out.pop("market")  # This market is NOT a pre-race, time-aligned quote.
    result = {"status": "not_available", "reason": final.get("reason"),
              "odds_kind": "settled_final_win_odds", "source_url": final["source_url"]}
    if final["status"] == "available":
        numbers = [row["number"] for row in forecast["runners"]]
        odds = [final["decimal_win_odds"][str(n)] for n in numbers]
        probabilities = normalize([1 / odd for odd in odds])
        winner_index = numbers.index(outcome["finishing_order"][0])
        result = {"status": "available_retrospective_benchmark", "odds_kind": "settled_final_win_odds",
                  "source_url": final["source_url"], "retrieved_at": final["retrieved_at"],
                  "implied_inverse_odds_sum": sum(1 / odd for odd in odds),
                  **loss(probabilities, winner_index),
                  "information_window": "final-market prices include information later than the archived model forecast",
                  "not_a_purchase_backtest": True,
                  "source_verified": False}
        out["difference_model_minus_final_market"] = {
            "log_loss": out["model"]["log_loss"] - result["log_loss"],
            "brier_multiclass_sum": out["model"]["brier_multiclass_sum"] - result["brier_multiclass_sum"],
        }
    out["market_final"] = result
    out["comparison_note"] = "Retrospective forecasting benchmark only. Final odds are not executable earlier quotes; never use to validate betting EV."
    return out


def batch_compare_final_odds(forecasts_dir: str | Path, outcomes_dir: str | Path,
                             final_odds_dir: str | Path,
                             *, selection: dict[str, str] | None = None) -> dict[str, Any]:
    """Batch audit: score only races with matching forecasts, outcomes and final odds.

    Explicitly report missing files; never fill missing final odds with the
    winning price or assign an unsupported provider quote to a different race.
    """
    from .records import load_json

    def read_index(directory: str | Path, required_field: str, recursive: bool) -> dict[str, dict[str, Any]]:
        indexed = {}
        for file in sorted(Path(directory).rglob("*.json") if recursive else Path(directory).glob("*.json")):
            record = load_json(file)
            if required_field not in record:
                raise ValueError(f"{file}: missing {required_field}")
            race_id = record.get("race_id")
            if not isinstance(race_id, str) or not race_id:
                raise ValueError(f"{file}: invalid race_id")
            if race_id in indexed:
                raise ValueError(f"duplicate race_id {race_id} in {directory}")
            indexed[race_id] = record
        return indexed

    forecasts = read_index(forecasts_dir, "runners", recursive=False)
    outcomes = read_index(outcomes_dir, "finishing_order", recursive=False)
    # Retain all immutable snapshots. Select an exact relative path when more
    # than one version exists; choosing newest implicitly would change history.
    final_root = Path(final_odds_dir)
    candidate_odds: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for path in sorted(final_root.rglob("*.json")):
        record = load_json(path)
        if record.get("odds_kind") != "settled_final_win_odds":
            raise ValueError(f"{path}: missing or invalid odds_kind")
        race_id = record.get("race_id")
        if not isinstance(race_id, str) or not race_id:
            raise ValueError(f"{path}: invalid race_id")
        relative = path.relative_to(final_root).as_posix()
        # Validate every alternate snapshot before considering it for selection.
        if race_id in forecasts:
            validate_final_odds(record, forecasts[race_id])
        candidate_odds.setdefault(race_id, []).append((relative, record))
    selection = {} if selection is None else selection
    if set(selection) - set(candidate_odds):
        raise ValueError("selection refers to unknown race_id")
    final_odds: dict[str, dict[str, Any]] = {}
    for race_id, candidates in candidate_odds.items():
        if race_id in selection:
            matched = [rec for path, rec in candidates if path == selection[race_id]]
            if len(matched) != 1:
                raise ValueError(f"{race_id}: selected odds path not found")
            final_odds[race_id] = matched[0]
        elif len(candidates) == 1:
            final_odds[race_id] = candidates[0][1]
        else:
            raise ValueError(f"duplicate race_id {race_id}; provide --selection with exact snapshot path")
    scored = []
    unavailable = []
    for race_id in sorted(set(forecasts) & set(outcomes)):
        if race_id not in final_odds:
            unavailable.append({"race_id": race_id, "reason": "no_final_odds_record"})
            continue
        result = score_against_final_odds(forecasts[race_id], outcomes[race_id], final_odds[race_id])
        if result["market_final"]["status"] != "available_retrospective_benchmark":
            unavailable.append({"race_id": race_id, "reason": result["market_final"]["reason"]})
            continue
        scored.append(result)
    output = {
        "status": "available" if scored else "not_available",
        "paired_forecast_outcome_races": len(set(forecasts) & set(outcomes)),
        "market_scored_races": len(scored),
        "market_not_available": unavailable,
        "forecast_without_outcome": sorted(set(forecasts) - set(outcomes)),
        "outcome_without_forecast": sorted(set(outcomes) - set(forecasts)),
        "final_odds_without_paired_forecast_outcome": sorted(set(final_odds) - (set(forecasts) & set(outcomes))),
        "evaluation": "retrospective_final_market_benchmark_not_tradable_quotes",
        "race_scores": scored,
    }
    if scored:
        n = len(scored)
        output["matched_race_mean_scores"] = {
            name: {metric: sum(r[name][metric] for r in scored) / n
                   for metric in ("log_loss", "brier_multiclass_sum")}
            for name in ("model", "uniform", "market_final")
        }
        if n < 30:
            output["sample_size_warning"] = "Fewer than 30 paired races: descriptive comparison, not evidence of calibration skill."
    return output
