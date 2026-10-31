"""Offline, no-cost retrospective CSV importer for a *private* local odds index.

No network access. Data provenance, table meaning, and any original source
license must be reviewed by the operator; a CSV file is not an ex-ante quote.
"""
from __future__ import annotations

import csv
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
from typing import Any
from urllib.parse import urlsplit

from .scoring import loss, normalize

_RACE_ID = re.compile(r"[A-Za-z0-9:_-]{1,128}\Z")
_DIGITS = re.compile(r"[0-9]+\Z")
_MISSING = {"", "-", "--", "---", "取消", "除外", "不明", "null", "nan", "NaN"}


def inspect_csv(path: str | Path, *, encoding: str = "utf-8-sig") -> dict[str, Any]:
    """Return just headers and first 2 row shapes; do not copy raw vendor data."""
    with Path(path).open("r", encoding=encoding, newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError("missing or duplicate CSV header names")
        for _ in range(2):
            if next(reader, None) is None:
                break
    return {"columns": reader.fieldnames, "encoding": encoding,
            "notice": "Column mapping must be checked against actual downloaded dataset; no automatic assumptions."}


def _mapping(data: dict[str, Any], kind: str) -> dict[str, str]:
    if not isinstance(data, dict) or kind not in data:
        raise ValueError(f"mapping requires {kind} section")
    cols = data[kind]
    expected = {"race_id", "number", "odds"} if kind == "odds" else {"race_id", "number", "finish"}
    if not isinstance(cols, dict) or set(cols) != expected:
        raise ValueError(f"mapping.{kind} requires exactly {sorted(expected)}")
    if any(not isinstance(c, str) or not c.strip() for c in cols.values()):
        raise ValueError("CSV column names must be nonblank")
    if len(set(cols.values())) != len(cols):
        raise ValueError("mapping fields must refer to unique CSV columns")
    return cols


def _source(source_url: str) -> str:
    if not isinstance(source_url, str):
        raise ValueError("source_url must be an HTTPS URL")
    parsed = urlsplit(source_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("source_url must be a non-credentialed HTTPS URL")
    return source_url


def _sha_file(path: Path) -> str:
    dig = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            dig.update(block)
    return dig.hexdigest()


def _race_id(value: Any) -> str:
    if not isinstance(value, str) or not _RACE_ID.fullmatch(value.strip()):
        raise ValueError(f"invalid race ID: {value!r}")
    return value.strip()


def _number(value: Any) -> int:
    if not isinstance(value, str) or not _DIGITS.fullmatch(value.strip()):
        raise ValueError(f"invalid horse number: {value!r}")
    number = int(value.strip())
    if number < 1 or number > 99:
        raise ValueError("horse number must be between 1 and 99")
    return number


def _odds(value: Any) -> float | None:
    if not isinstance(value, str):
        raise ValueError("missing win odds column value")
    text = value.strip()
    if text in _MISSING:
        return None
    # Prevent a mistaken locale/date/percentage string from being parsed as odds.
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", text):
        raise ValueError(f"unrecognised win odds: {text!r}")
    val = float(text)
    if not math.isfinite(val) or val < 1:
        raise ValueError("win odds must be finite decimal odds >= 1; zero is not a price")
    return val


def _finish(value: Any) -> int | None:
    if value is None:
        raise ValueError("missing finish column")
    text = value.strip()
    if text in _MISSING or text in {"中止", "失格", "除外", "取消"}:
        return None
    if not _DIGITS.fullmatch(text) or int(text) < 1:
        raise ValueError(f"unexpected finishing position: {text!r}; audit manually")
    return int(text)


def _csv_records(file: Path, cols: dict[str, str], encoding: str):
    with file.open("r", encoding=encoding, newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError(f"{file}: missing or duplicate CSV headers")
        missing = set(cols.values()) - set(reader.fieldnames)
        if missing:
            raise ValueError(f"{file}: columns not found: {sorted(missing)}")
        for line, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(f"{file}:{line}: CSV row has extra unmapped cells")
            try:
                rid = _race_id(row[cols["race_id"]])
                num = _number(row[cols["number"]])
                yield rid, num, row[cols["odds" if "odds" in cols else "finish"]]
            except (ValueError, TypeError) as err:
                raise ValueError(f"{file}:{line}: {err}") from err


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    PRAGMA foreign_keys = ON;
    CREATE TABLE IF NOT EXISTS csv_imports (
        import_id TEXT PRIMARY KEY,
        source_url TEXT NOT NULL,
        source_label TEXT,
        odds_sha256 TEXT NOT NULL,
        roster_sha256 TEXT,
        mapping_sha256 TEXT NOT NULL,
        imported_at TEXT NOT NULL,
        provenance TEXT NOT NULL,
        is_actual_prepublished_snapshot INTEGER NOT NULL DEFAULT 0 CHECK (is_actual_prepublished_snapshot=0),
        authorisation_to_redistribute INTEGER NOT NULL DEFAULT 0 CHECK (authorisation_to_redistribute=0)
    );
    CREATE TABLE IF NOT EXISTS csv_win_odds (
        import_id TEXT NOT NULL REFERENCES csv_imports(import_id),
        race_id TEXT NOT NULL,
        horse_number INTEGER NOT NULL,
        decimal_win_odds REAL,
        PRIMARY KEY(import_id, race_id, horse_number)
    );
    CREATE TABLE IF NOT EXISTS csv_race_roster (
        import_id TEXT NOT NULL REFERENCES csv_imports(import_id),
        race_id TEXT NOT NULL,
        horse_number INTEGER NOT NULL,
        finishing_position INTEGER,
        PRIMARY KEY(import_id, race_id, horse_number)
    );
    CREATE INDEX IF NOT EXISTS idx_odds_race ON csv_win_odds(import_id,race_id);
    CREATE INDEX IF NOT EXISTS idx_roster_race ON csv_race_roster(import_id,race_id);
    """)


def import_free_csv(
    *, odds_csv: str | Path, db: str | Path, mapping_file: str | Path,
    source_url: str, roster_csv: str | Path | None = None,
    source_label: str = "free historical CSV; provenance not independently verified",
    encoding: str = "utf-8-sig",
) -> dict[str, Any]:
    """Import whole race-level odds CSV into local SQLite without downloading data.

    An independently mapped complete roster is required for benchmark scoring.
    The archive is *retrospective*, never a purchasable price series.
    """
    source_url = _source(source_url)
    odds_csv = Path(odds_csv)
    roster_csv = Path(roster_csv) if roster_csv is not None else None
    mapping_file = Path(mapping_file)
    mapping_bytes = mapping_file.read_bytes()
    maps = json.loads(mapping_bytes)
    if not isinstance(maps, dict) or set(maps) != ({"odds", "roster"} if roster_csv else {"odds"}):
        raise ValueError("mapping sections must exactly match supplied files")
    odds_map = _mapping(maps, "odds")
    roster_map = _mapping(maps, "roster") if roster_csv else None
    odds_sha = _sha_file(odds_csv)
    roster_sha = _sha_file(roster_csv) if roster_csv else None
    map_sha = hashlib.sha256(mapping_bytes).hexdigest()
    import_id = hashlib.sha256(json.dumps({"odds":odds_sha,"roster":roster_sha,"mapping":map_sha,
                                            "url":source_url},sort_keys=True).encode()).hexdigest()
    db = Path(db)
    db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db)) as conn:
        _init_db(conn)
        if conn.execute("SELECT 1 FROM csv_imports WHERE import_id=?", (import_id,)).fetchone():
            raise ValueError("identical CSV import already recorded; not overwriting private historical data")
        # Explicit all-or-nothing transaction, preserving the previous DB on invalid data.
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("INSERT INTO csv_imports VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (import_id,source_url,source_label,odds_sha,roster_sha,map_sha,
                          datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                          "RETROSPECTIVE_CSV_SELF_REPORTED_NOT_SOURCE_VERIFIED",0,0))
            odds_count=0
            for race_id, number, value in _csv_records(odds_csv, odds_map, encoding):
                odds_value = _odds(value)
                try:
                    conn.execute("INSERT INTO csv_win_odds VALUES(?,?,?,?)",
                                 (import_id, race_id, number, odds_value))
                except sqlite3.IntegrityError as exc:
                    raise ValueError(f"duplicate odds row for {race_id} #{number}") from exc
                odds_count += 1
            roster_count=0
            if roster_csv is not None:
                assert roster_map is not None
                for race_id, number, value in _csv_records(roster_csv, roster_map, encoding):
                    rank = _finish(value)
                    try:
                        conn.execute("INSERT INTO csv_race_roster VALUES(?,?,?,?)",
                                     (import_id, race_id, number, rank))
                    except sqlite3.IntegrityError as exc:
                        raise ValueError(f"duplicate roster row for {race_id} #{number}") from exc
                    roster_count += 1
            race_count=conn.execute("SELECT COUNT(DISTINCT race_id) FROM csv_win_odds WHERE import_id=?",
                                    (import_id,)).fetchone()[0]
        except BaseException:
            conn.rollback()
            raise
        conn.commit()
    return {"status":"imported_retrospective_not_source_verified", "import_id":import_id,
            "database":str(db), "odds_rows":odds_count,"roster_rows":roster_count,
            "odds_races":race_count,"source_url":source_url,"original_odds_sha256":odds_sha,
            "original_roster_sha256":roster_sha,"market_is_pre_race_quote":False,
            "can_publish_original_data":False,"can_score_without_roster":False}


def score_free_csv(*, db: str | Path, import_id: str, limit: int = 50) -> dict[str, Any]:
    """Independent market-only diagnostic: requires full roster and one clear winner.

    Does NOT compare the archived user model unless contemporaneous forecasts exist.
    """
    if limit < 0:
        raise ValueError("limit must be >= 0")
    with closing(sqlite3.connect(db)) as conn:
        _init_db(conn)
        if not conn.execute("SELECT 1 FROM csv_imports WHERE import_id=?",(import_id,)).fetchone():
            raise ValueError("unknown local odds import_id")
        races=conn.execute("SELECT DISTINCT race_id FROM csv_win_odds WHERE import_id=? ORDER BY race_id",
                           (import_id,)).fetchall()
        scored=[]
        missing={}
        examples=[]
        for (race_id,) in races:
            odds=conn.execute("SELECT horse_number,decimal_win_odds FROM csv_win_odds WHERE import_id=? AND race_id=? ORDER BY horse_number",
                              (import_id,race_id)).fetchall()
            roster=conn.execute("SELECT horse_number,finishing_position FROM csv_race_roster WHERE import_id=? AND race_id=?",
                                (import_id,race_id)).fetchall()
            reason=None
            if not roster:
                reason="no_complete_result_roster"
            elif len(odds) != len(roster) or {o[0] for o in odds} != {r[0] for r in roster}:
                reason="incomplete_odds_or_roster_mismatch"
            elif len(odds) < 2 or any(row[1] is None for row in odds):
                reason="missing_prices"
            else:
                winners=[num for num,position in roster if position==1]
                if len(winners)!=1:
                    reason="not_exactly_one_winner"
            if reason:
                missing[reason]=missing.get(reason,0)+1
                if len(examples)<limit:examples.append({"race_id":race_id,"reason":reason})
                continue
            prices=[float(row[1]) for row in odds]
            prob=normalize([1.0/x for x in prices])
            winner_index=[row[0] for row in odds].index(winners[0])
            market=loss(prob,winner_index)
            uniform=loss([1/len(odds)]*len(odds),winner_index)
            scored.append({"race_id":race_id,"model_market_log_loss":market["log_loss"],
                           "uniform_log_loss":uniform["log_loss"],
                           "model_market_brier":market["brier_multiclass_sum"],
                           "uniform_brier":uniform["brier_multiclass_sum"],
                           "overround":sum(1/x for x in prices)})
        n=len(scored)
        return {"status":"market_only_retrospective_diagnostic" if n else "not_available",
                "import_id":import_id,"odds_races":len(races),"scored_races":n,
                "skipped_races":len(races)-n,"skipped_by_reason":missing,
                "skipped_examples":examples,
                "market_vs_archived_model":"not_available_without_archived_asof_forecasts",
                "not_a_purchase_backtest":True,
                "source_verified":False,
                "mean_scores":({
                    key:sum(row[key] for row in scored)/n
                    for key in ("model_market_log_loss","uniform_log_loss","model_market_brier","uniform_brier","overround")
                } if n else None),
                "small_sample_warning": "Fewer than 30 races: descriptive only" if n<30 else None}
