"""Write sealed, append-only pre-race market observations from supplied input.

No website is accessed. The system capture clock is recorded, rather than an
operator-editable historical `observed_at`. This proves neither the source's
publication time nor independent authenticity of manually transcribed odds.
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

from .records import _timestamp, validate_forecast, validate_market

SCHEMA_VERSION = 1
_CAPTURE_METHOD = "manual_transcription"
_ALLOWED_INPUT = {"race_id", "source_url", "status", "decimal_win_odds", "reason", "source_label"}
_ID = re.compile(r"^[A-Za-z0-9:_-]{1,128}$")


def canonical_bytes(obj: dict[str, Any]) -> bytes:
    """Stable JSON representation for the integrity seal, not a signature."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def verify_seal(snapshot: dict[str, Any]) -> None:
    claimed = snapshot.get("snapshot_sha256")
    if not isinstance(claimed, str) or not re.fullmatch(r"[0-9a-f]{64}", claimed):
        raise ValueError("invalid snapshot_sha256")
    material = {k: v for k, v in snapshot.items() if k != "snapshot_sha256"}
    actual = hashlib.sha256(canonical_bytes(material)).hexdigest()
    if actual != claimed:
        raise ValueError("market snapshot integrity check failed")


def create_snapshot(input_data: dict[str, Any], forecast: dict[str, Any],
                    *, captured_at: datetime) -> dict[str, Any]:
    """Construct one live observation (captured_at is injectable for tests only)."""
    validate_forecast(forecast)
    if not isinstance(input_data, dict) or set(input_data) - _ALLOWED_INPUT:
        raise ValueError("unknown market input field")
    if input_data.get("race_id") != forecast["race_id"]:
        raise ValueError("market race mismatch")
    race_id = forecast["race_id"]
    if not isinstance(race_id, str) or not _ID.fullmatch(race_id):
        raise ValueError("race_id must be filename-safe")
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise ValueError("capture clock must include timezone")
    # Monotonicity is against the *actual invocation time*, not user-provided asof.
    if not _timestamp(forecast["asof"]) <= captured_at < _timestamp(forecast["race_at"]):
        raise ValueError("live capture must occur after forecast asof and before race start")
    status = input_data.get("status")
    if status not in ("available", "not_available"):
        raise ValueError("market status must be available or not_available")
    source_url = input_data.get("source_url")
    if (not isinstance(source_url, str) or
            urlsplit(source_url).scheme != "https" or not urlsplit(source_url).hostname):
        raise ValueError("https source_url with hostname is required")
    if "source_label" in input_data and (not isinstance(input_data["source_label"], str) or
                                         not input_data["source_label"].strip()):
        raise ValueError("invalid source_label")
    if status == "available":
        if "reason" in input_data:
            raise ValueError("available market must not have reason")
        odds = input_data.get("decimal_win_odds")
        if not isinstance(odds, dict):
            raise ValueError("decimal_win_odds must be a full-field mapping")
        expected = {str(r["number"]) for r in forecast["runners"]}
        if set(odds) != expected:
            raise ValueError("missing/unknown market odds for runners")
        if any(not isinstance(x, (int, float)) or isinstance(x, bool) or
               not math.isfinite(x) or x < 1 for x in odds.values()):
            raise ValueError("invalid decimal odds")
    else:
        if "decimal_win_odds" in input_data:
            raise ValueError("not_available must not carry odds")
        if not isinstance(input_data.get("reason"), str) or not input_data["reason"].strip():
            raise ValueError("not_available must carry a reason")

    stamped = captured_at.astimezone(timezone.utc).isoformat(timespec="microseconds")
    snapshot: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "race_id": race_id,
        "status": status,
        "observed_at": stamped,
        "captured_at": stamped,
        "decision_at": stamped,
        "capture_method": _CAPTURE_METHOD,
        "source_url": source_url,
        "evidence_level": "SELF_REPORTED_NOT_INDEPENDENTLY_VERIFIED",
        "input_sha256": hashlib.sha256(canonical_bytes(input_data)).hexdigest(),
    }
    if "source_label" in input_data:
        snapshot["source_label"] = input_data["source_label"].strip()
    if status == "available":
        snapshot["decimal_win_odds"] = odds.copy()
    else:
        snapshot["reason"] = input_data["reason"].strip()
    snapshot["snapshot_sha256"] = hashlib.sha256(canonical_bytes(snapshot)).hexdigest()
    validate_market(snapshot, forecast)
    return snapshot


def capture_to_directory(input_file: str | Path, forecast: dict[str, Any],
                         output_dir: str | Path,
                         *, clock: Callable[[], datetime] | None = None) -> Path:
    """Create a new content-addressed snapshot; never overwrite an existing file.

    The CLI does not expose `clock` or any historical timestamp parameter.
    `clock` exists solely for repeatable unit tests.
    """
    if clock is None:
        clock = lambda: datetime.now(timezone.utc)
    # Read the bytes immediately before obtaining the local capture timestamp.
    raw = Path(input_file).read_bytes()
    incoming = json.loads(raw)
    captured_at = clock()
    snapshot = create_snapshot(incoming, forecast, captured_at=captured_at)
    # JRA-style IDs contain colons (invalid in Windows directory names).
    # Add a digest suffix to avoid collisions between sanitized IDs.
    race_id = snapshot["race_id"]
    directory_name = (race_id.replace(":", "-") + "_" +
                      hashlib.sha256(race_id.encode("utf-8")).hexdigest()[:12])
    race_dir = Path(output_dir) / directory_name
    race_dir.mkdir(parents=True, exist_ok=True)
    stamp = captured_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    dst = race_dir / f"{stamp}_{snapshot['snapshot_sha256']}.json"
    # Atomic exclusive creation prevents accidental overwrite even across processes.
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True,
                         allow_nan=False).encode("utf-8") + b"\n"
    fd = os.open(dst, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        dst.unlink(missing_ok=True)
        raise
    return dst
