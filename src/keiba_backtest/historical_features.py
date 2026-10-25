"""Build provenance-aware, point-in-time horse features from supplied JSON.

This module does NOT fetch racing data or infer publication timestamps.
`captured_pre_race` evidence requires an actual pre-cutoff capture; a later
reconstruction can only run with an explicit diagnostic-only opt-in.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .records import _timestamp

SCHEMA_VERSION = 1
GENERATOR_VERSION = "historical-features-v1"
DATASET_KINDS = {"synthetic_fixture", "historical_archive", "retrospective_research"}
EVIDENCE_KINDS = {"synthetic", "captured_pre_race", "retrospective_unverified"}
FINISH_STATUSES = {"finished", "did_not_finish", "disqualified"}
ENTRY_STATUSES = {"declared", "withdrawn", "excluded"}
SURFACES = {"turf", "dirt"}


def _fail(message: str) -> None:
    raise ValueError(message)


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{name} must be an object")
    return value


def _required_keys(value: dict[str, Any], allowed: set[str], required: set[str], name: str) -> None:
    missing = required - set(value)
    extras = set(value) - allowed
    if missing or extras:
        _fail(f"{name}: missing fields={sorted(missing)}; unknown fields={sorted(extras)}")


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{name} must be a nonempty string")
    return value


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        _fail(f"{name} must be a positive integer")
    return value


def _number(value: Any, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _fail(f"{name} must be a finite number")
    if not low <= value <= high:
        _fail(f"{name} must be in [{low}, {high}]")
    return float(value)


def _timestamp_field(value: Any, name: str) -> datetime:
    return _timestamp(_string(value, name))


def _validate_evidence(
    evidence: dict[str, Any], asof: datetime, dataset_kind: str,
    allow_unverified: bool, description: str,
) -> str:
    _required_keys(evidence, {"kind", "observed_at", "source_url", "source_sha256"},
                   {"kind", "source_url"}, description)
    kind = evidence["kind"]
    if kind not in EVIDENCE_KINDS:
        _fail(f"{description}: unknown evidence kind {kind}")
    _string(evidence["source_url"], f"{description}.source_url")
    if "source_sha256" in evidence:
        digest = evidence["source_sha256"]
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            _fail(f"{description}: source_sha256 must be lowercase SHA-256 hex")
    if kind == "captured_pre_race" and "source_sha256" not in evidence:
        _fail(f"{description}: captured_pre_race requires source_sha256 for auditability")
    if dataset_kind == "synthetic_fixture" and kind != "synthetic":
        _fail(f"{description}: synthetic dataset may only contain synthetic evidence")
    if dataset_kind == "historical_archive" and kind != "captured_pre_race":
        _fail(f"{description}: historical archive requires captured_pre_race evidence")
    if dataset_kind != "synthetic_fixture" and kind == "synthetic":
        _fail(f"{description}: synthetic evidence in real dataset")
    observed = evidence.get("observed_at")
    if kind in {"synthetic", "captured_pre_race"}:
        if observed is None:
            _fail(f"{description}: observed_at required for pre-race evidence")
        if _timestamp_field(observed, f"{description}.observed_at") > asof:
            _fail(f"{description}: observed_at after asof (lookahead)")
    else:
        if not allow_unverified:
            _fail(f"{description}: retrospective evidence requires --allow-unverified")
        if observed is not None:
            _timestamp_field(observed, f"{description}.observed_at")
    return kind


def _validate_start(start: dict[str, Any], horse_id: str, target_race_id: str,
                    asof: datetime, dataset_kind: str, allow_unverified: bool, index: int) -> str:
    place = f"{target_race_id}/{horse_id}/past_starts[{index}]"
    _required_keys(start,
                   {"race_id", "race_at", "result_available_at", "surface", "distance_m",
                    "status", "finish_position", "field_size", "last3f_seconds", "evidence", "dead_heat"},
                   {"race_id", "race_at", "result_available_at", "surface", "distance_m",
                    "status", "finish_position", "field_size", "evidence"}, place)
    prior_id = _string(start["race_id"], f"{place}.race_id")
    if prior_id == target_race_id:
        _fail(f"{place}: target race result used as a past start (target leakage)")
    event_at = _timestamp_field(start["race_at"], f"{place}.race_at")
    released = _timestamp_field(start["result_available_at"], f"{place}.result_available_at")
    if event_at >= asof:
        _fail(f"{place}: past start is on/after asof (future result leakage)")
    if released <= event_at:
        _fail(f"{place}: result_available_at must be after prior race start")
    if released > asof:
        _fail(f"{place}: result_available_at after asof (lookahead)")
    if start["surface"] not in SURFACES:
        _fail(f"{place}: invalid surface")
    _positive_int(start["distance_m"], f"{place}.distance_m")
    _positive_int(start["field_size"], f"{place}.field_size")
    status = start["status"]
    if status not in FINISH_STATUSES:
        _fail(f"{place}: invalid start status")
    pos = start["finish_position"]
    if status == "finished":
        rank = _positive_int(pos, f"{place}.finish_position")
        if rank > start["field_size"]:
            _fail(f"{place}: position exceeds field_size")
    elif pos is not None:
        _fail(f"{place}: non-finish status must have null finish_position")
    if start.get("dead_heat", False) not in (True, False) or not isinstance(start.get("dead_heat", False), bool):
        _fail(f"{place}: dead_heat must be boolean")
    if status != "finished" and start.get("dead_heat", False):
        _fail(f"{place}: dead heat requires finished status")
    if start.get("last3f_seconds") is not None:
        if status != "finished":
            _fail(f"{place}: non-finish cannot have a last3f_seconds value")
        _number(start["last3f_seconds"], f"{place}.last3f_seconds", 10, 200)
    kind = _validate_evidence(_object(start["evidence"], f"{place}.evidence"),
                              asof, dataset_kind, allow_unverified, f"{place}.evidence")
    if kind != "retrospective_unverified":
        captured = _timestamp(start["evidence"]["observed_at"])
        if captured < released:
            _fail(f"{place}: observed_at before result_available_at (chronology contradiction)")
    return kind


def build_features(dataset: dict[str, Any], *, allow_unverified: bool = False,
                   input_sha256: str | None = None) -> dict[str, Any]:
    """Validate the complete import then emit a deterministic, outcome-free feature set.

    `synthetic_fixture` and `retrospective_research` outputs are NEVER eligible
    as empirical ex-ante training/validation evidence.
    """
    dataset = _object(dataset, "dataset")
    _required_keys(dataset, {"schema_version", "dataset_id", "dataset_kind", "races"},
                   {"schema_version", "dataset_id", "dataset_kind", "races"}, "dataset")
    if dataset["schema_version"] != SCHEMA_VERSION or isinstance(dataset["schema_version"], bool):
        _fail("unsupported schema_version")
    _string(dataset["dataset_id"], "dataset_id")
    kind = dataset["dataset_kind"]
    if kind not in DATASET_KINDS:
        _fail("invalid dataset_kind")
    if not isinstance(dataset["races"], list) or len(dataset["races"]) == 0:
        _fail("races must be a nonempty list")
    race_ids = set()
    # A past performance repeated in several snapshots must be consistent.
    # Revisions require an explicit versioned import, not silent overwrites.
    historical_identity: dict[tuple[str, str], tuple[Any, ...]] = {}
    outputs = []
    overall_quality = "VERIFIED_PRE_RACE" if kind == "historical_archive" else (
        "SYNTHETIC_NOT_EMPIRICAL" if kind == "synthetic_fixture" else "RETROSPECTIVE_UNVERIFIED_NOT_EMPIRICAL")
    for index, race_raw in enumerate(dataset["races"]):
        race = _object(race_raw, f"races[{index}]")
        _required_keys(race,
                       {"race_id", "race_at", "asof", "surface", "distance_m", "entries", "snapshot"},
                       {"race_id", "race_at", "asof", "surface", "distance_m", "entries", "snapshot"},
                       f"races[{index}]")
        race_id = _string(race["race_id"], "race_id")
        if race_id in race_ids:
            _fail(f"duplicate race_id {race_id}")
        race_ids.add(race_id)
        race_at = _timestamp_field(race["race_at"], f"{race_id}.race_at")
        asof = _timestamp_field(race["asof"], f"{race_id}.asof")
        if asof >= race_at:
            _fail(f"{race_id}: asof must be before race_at")
        if race["surface"] not in SURFACES:
            _fail(f"{race_id}: invalid surface")
        _positive_int(race["distance_m"], f"{race_id}.distance_m")
        snap_kind = _validate_evidence(_object(race["snapshot"], f"{race_id}.snapshot"),
                                       asof, kind, allow_unverified, f"{race_id}.snapshot")
        if not isinstance(race["entries"], list) or len(race["entries"]) < 2:
            _fail(f"{race_id}: at least 2 entries required")
        seen_horses, seen_numbers = set(), set()
        excluded = []
        runner_outputs = []
        has_unverified = snap_kind == "retrospective_unverified"
        for j, entry_raw in enumerate(race["entries"]):
            entry = _object(entry_raw, f"{race_id}/entries[{j}]")
            _required_keys(entry,
                           {"number", "horse_id", "name", "status", "past_starts", "draw", "carried_weight_kg", "jockey_id"},
                           {"number", "horse_id", "name", "status", "past_starts"},
                           f"{race_id}/entries[{j}]")
            number = _positive_int(entry["number"], "entry.number")
            horse_id = _string(entry["horse_id"], "entry.horse_id")
            name = _string(entry["name"], "entry.name")
            if number in seen_numbers or horse_id in seen_horses:
                _fail(f"{race_id}: duplicate number or horse_id")
            seen_numbers.add(number)
            seen_horses.add(horse_id)
            if entry["status"] not in ENTRY_STATUSES:
                _fail(f"{race_id}/{horse_id}: invalid entry status")
            if "draw" in entry:
                _positive_int(entry["draw"], "entry.draw")
            if "jockey_id" in entry and entry["jockey_id"] is not None:
                _string(entry["jockey_id"], "entry.jockey_id")
            if "carried_weight_kg" in entry and entry["carried_weight_kg"] is not None:
                _number(entry["carried_weight_kg"], "entry.carried_weight_kg", 30, 75)
            starts = entry["past_starts"]
            if not isinstance(starts, list):
                _fail(f"{race_id}/{horse_id}: past_starts must be a list")
            seen_past = set()
            for k, start_raw in enumerate(starts):
                start = _object(start_raw, f"{race_id}/{horse_id}/past_starts[{k}]")
                past_id = _string(start.get("race_id"), "past start race_id")
                if past_id in seen_past:
                    _fail(f"{race_id}/{horse_id}: duplicate past race_id {past_id}")
                seen_past.add(past_id)
                evidence = _validate_start(start, horse_id, race_id, asof, kind, allow_unverified, k)
                identity_key = (horse_id, past_id)
                fact_keys = ("race_at", "result_available_at", "surface", "distance_m",
                             "status", "finish_position", "field_size", "last3f_seconds", "dead_heat")
                fact_signature = tuple(start.get(key) for key in fact_keys)
                if identity_key in historical_identity and historical_identity[identity_key] != fact_signature:
                    _fail(f"{race_id}/{horse_id}: conflicting prior start across snapshots {past_id}")
                historical_identity[identity_key] = fact_signature
                has_unverified = has_unverified or evidence == "retrospective_unverified"
            if entry["status"] != "declared":
                excluded.append({"number": number, "horse_id": horse_id, "entry_status": entry["status"]})
                continue
            started = sorted(starts, key=lambda s: (_timestamp(s["race_at"]), s["race_id"]))
            completed = [s for s in started if s["status"] == "finished"]
            turf = [s for s in started if s["surface"] == "turf"]
            latest = started[-1] if started else None
            last_year = [s for s in started if 0 <= (asof-_timestamp(s["race_at"])).total_seconds() <= 365*86400]
            feat = {
                "past_starts": len(started),
                "completed_finishes": len(completed),
                "wins": sum(s["finish_position"] == 1 for s in completed),
                "top3_finishes": sum(s["finish_position"] <= 3 for s in completed),
                "starts_last_365d": len(last_year),
                "last_start_days_ago": (asof-_timestamp(latest["race_at"])).total_seconds()/86400 if latest else None,
                "max_prior_distance_m": max((s["distance_m"] for s in started), default=None),
                "turf_2400m_plus_starts": sum(s["distance_m"] >= 2400 for s in turf),
                "first_time_target_distance_or_more": not any(
                    s["surface"] == race["surface"] and s["distance_m"] >= race["distance_m"]
                    for s in started
                ),
                "mean_finish_fraction": (
                    sum((s["field_size"]-s["finish_position"])/(s["field_size"]-1)
                        for s in completed if s["field_size"] > 1) /
                    len([s for s in completed if s["field_size"] > 1])
                ) if any(s["field_size"] > 1 for s in completed) else None,
                "mean_last3f_seconds": (
                    sum(s["last3f_seconds"] for s in completed if s.get("last3f_seconds") is not None) /
                    sum(s.get("last3f_seconds") is not None for s in completed)
                ) if any(s.get("last3f_seconds") is not None for s in completed) else None,
            }
            runner_outputs.append({
                "number": number, "horse_id": horse_id, "name": name,
                "draw": entry.get("draw"), "jockey_id": entry.get("jockey_id"),
                "carried_weight_kg": entry.get("carried_weight_kg"),
                "features": feat,
                "source_past_race_ids": [s["race_id"] for s in started],
            })
        if len(runner_outputs) < 2:
            _fail(f"{race_id}: less than two declared runners")
        if kind == "historical_archive" and has_unverified:
            _fail(f"{race_id}: cannot put unverified sources in historical_archive")
        if has_unverified:
            overall_quality = "RETROSPECTIVE_UNVERIFIED_NOT_EMPIRICAL"
        outputs.append({
            "race_id": race_id, "race_at": race["race_at"], "asof": race["asof"],
            "surface": race["surface"], "distance_m": race["distance_m"],
            "quality": "RETROSPECTIVE_UNVERIFIED_NOT_EMPIRICAL" if has_unverified else (
                "SYNTHETIC_NOT_EMPIRICAL" if kind == "synthetic_fixture" else "VERIFIED_PRE_RACE"),
            "runners": sorted(runner_outputs, key=lambda x: x["number"]),
            "excluded_entries": sorted(excluded, key=lambda x: x["number"]),
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "dataset_id": dataset["dataset_id"],
        "input_sha256": input_sha256,
        "quality": overall_quality,
        "empirical_backtest_eligible": overall_quality == "VERIFIED_PRE_RACE",
        "warning": ("Synthetic tests are not empirical backtest observations" if overall_quality == "SYNTHETIC_NOT_EMPIRICAL" else
                    "Retrospective evidence cannot establish contemporaneous availability" if overall_quality == "RETROSPECTIVE_UNVERIFIED_NOT_EMPIRICAL" else None),
        "races": sorted(outputs, key=lambda x: (_timestamp(x["race_at"]), x["race_id"])),
    }


def build_from_file(input_file: str | Path, *, allow_unverified: bool = False) -> dict[str, Any]:
    payload = Path(input_file).read_bytes()
    dataset = json.loads(payload)
    return build_features(dataset, allow_unverified=allow_unverified,
                          input_sha256=hashlib.sha256(payload).hexdigest())
