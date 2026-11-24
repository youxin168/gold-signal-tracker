"""SQLite keeps published records immutable and checkpoints outcomes separately."""

import json
import sqlite3
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import asdict, fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

from .signal import Outcome, Signal, Status, utc

OUTCOMES_SQL = """
CREATE TABLE IF NOT EXISTS outcomes (
    signal_id TEXT PRIMARY KEY REFERENCES signals(signal_id),
    status TEXT NOT NULL CHECK (status IN ('PENDING','ACTIVE','TP1','TP2','TP2_OPEN','TP3','SL','BE','EXPIRED')),
    triggered_at TEXT, tp1_at TEXT, closed_at TEXT, result_r TEXT, checked_until TEXT, tp2_at TEXT
)
"""
RECORDS_SQL = """
CREATE VIEW IF NOT EXISTS signal_records AS
SELECT signals.*, outcomes.status, outcomes.triggered_at, outcomes.tp1_at,
       outcomes.closed_at, outcomes.result_r, outcomes.checked_until, outcomes.tp2_at
FROM signals JOIN outcomes USING (signal_id)
"""

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS versions (
    strategy_code TEXT PRIMARY KEY,
    specification TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS signals (
    signal_id TEXT PRIMARY KEY,
    strategy_code TEXT NOT NULL REFERENCES versions(strategy_code),
    source TEXT NOT NULL, style TEXT NOT NULL, pair TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('BUY', 'SELL')),
    entry TEXT NOT NULL, sl TEXT NOT NULL, tp1 TEXT NOT NULL, tp2 TEXT NOT NULL,
    issued_at_utc TEXT NOT NULL, expires_at_utc TEXT NOT NULL,
    data_source TEXT NOT NULL, notes TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('LIVE', 'REPLAY')),
    setup_closed_at_utc TEXT NOT NULL, recorded_at TEXT NOT NULL, tp3 TEXT,
    CHECK (mode != 'LIVE' OR issued_at_utc = recorded_at),
    UNIQUE (strategy_code, pair, mode, setup_closed_at_utc)
);
CREATE INDEX IF NOT EXISTS signals_issue_lookup
ON signals(strategy_code, pair, mode, issued_at_utc);
{OUTCOMES_SQL};
{RECORDS_SQL};
CREATE TRIGGER IF NOT EXISTS immutable_signal_update BEFORE UPDATE ON signals
BEGIN SELECT RAISE(ABORT, 'Published terms cannot be changed'); END;
CREATE TRIGGER IF NOT EXISTS immutable_signal_delete BEFORE DELETE ON signals
BEGIN SELECT RAISE(ABORT, 'Published terms cannot be deleted'); END;
CREATE TRIGGER IF NOT EXISTS immutable_version_update BEFORE UPDATE ON versions
BEGIN SELECT RAISE(ABORT, 'Frozen strategy cannot be changed'); END;
CREATE TRIGGER IF NOT EXISTS immutable_version_delete BEFORE DELETE ON versions
BEGIN SELECT RAISE(ABORT, 'Frozen strategy cannot be deleted'); END;
"""


def _migrate_tp3(connection: sqlite3.Connection) -> None:
    if "tp3" not in {row["name"] for row in connection.execute("PRAGMA table_info(signals)")}:
        connection.execute("ALTER TABLE signals ADD COLUMN tp3 TEXT")
    if "tp2_at" not in {row["name"] for row in connection.execute("PRAGMA table_info(outcomes)")}:
        # SQLite cannot edit a CHECK constraint. Copy every outcome, including
        # timestamps and checkpoints, atomically while keeping published terms intact.
        connection.execute("DROP VIEW signal_records")
        connection.execute("ALTER TABLE outcomes RENAME TO outcomes_before_tp3")
        connection.execute(OUTCOMES_SQL)
        columns = "signal_id, status, triggered_at, tp1_at, closed_at, result_r, checked_until"
        connection.execute(f"INSERT INTO outcomes ({columns}) SELECT {columns} FROM outcomes_before_tp3")
        connection.execute("DROP TABLE outcomes_before_tp3")
        connection.execute(RECORDS_SQL)


@contextmanager
def transaction(path: Path) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA recursive_triggers = ON")
        connection.executescript(SCHEMA)
        # Daily limits, duplicate detection, and checkpoints are serialized.
        connection.execute("BEGIN IMMEDIATE")
        with connection:
            _migrate_tp3(connection)
            yield connection
    finally:
        connection.close()


def freeze(connection: sqlite3.Connection, spec: dict[str, Any]) -> None:
    code = spec["strategy_code"]
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"), allow_nan=False)
    row = connection.execute("SELECT specification FROM versions WHERE strategy_code = ?", (code,)).fetchone()
    if row is None:
        connection.execute("INSERT INTO versions VALUES (?, ?)", (code, canonical))
    elif row["specification"] != canonical:
        raise ValueError(f"{code} is already frozen in this database; create a new version for rule changes")


def _value(value: Any) -> Any:
    if isinstance(value, datetime):
        return utc(value)
    return str(value) if isinstance(value, Decimal) else value


def publish(connection: sqlite3.Connection, signal: Signal, spec: dict[str, Any]) -> str:
    if signal.mode not in ("LIVE", "REPLAY"):
        raise ValueError("Backtests belong in separate reports, never in the signal database")
    if signal.strategy_code != spec["strategy_code"] or spec["version_state"] != "FROZEN":
        raise ValueError("Publication requires matching frozen rules")
    freeze(connection, spec)
    key = (signal.strategy_code, signal.pair, signal.mode)
    duplicate = connection.execute(
        """SELECT 1 FROM signals WHERE strategy_code = ? AND pair = ? AND mode = ?
           AND setup_closed_at_utc = ?""", (*key, utc(signal.setup_closed_at_utc)),
    ).fetchone()
    if duplicate:
        return f"Already recorded for this {spec['entry_timeframe']} setup"
    day = signal.issued_at_utc.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    count = connection.execute(
        """SELECT COUNT(*) FROM signals WHERE strategy_code = ? AND pair = ? AND mode = ?
           AND issued_at_utc >= ? AND issued_at_utc < ?""", (*key, utc(day), utc(day + timedelta(days=1))),
    ).fetchone()[0]
    if count >= spec["max_signals_per_utc_day"]:
        return "Daily UTC signal limit reached"
    values = tuple(_value(value) for value in asdict(signal).values())
    connection.execute(
        """INSERT INTO signals (
           signal_id, strategy_code, source, style, pair, direction, entry, sl, tp1, tp2,
           issued_at_utc, expires_at_utc, data_source, notes, mode, setup_closed_at_utc, recorded_at, tp3
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", values,
    )
    connection.execute("INSERT INTO outcomes(signal_id, status) VALUES (?, 'PENDING')", (signal.signal_id,))
    return "Published"


def open_records(connection: sqlite3.Connection, mode: str, as_of: datetime) -> list[sqlite3.Row]:
    return connection.execute(
        """SELECT signal_records.*, versions.specification FROM signal_records
           JOIN versions USING (strategy_code)
           WHERE mode = ? AND issued_at_utc <= ? AND status IN ('PENDING','ACTIVE','TP1','TP2_OPEN')
           ORDER BY issued_at_utc, signal_id""", (mode, utc(as_of)),
    ).fetchall()


def from_record(row: sqlite3.Row | Mapping[str, Any]) -> tuple[Signal, Outcome]:
    keys = row.keys()
    terms = {field.name: row[field.name] for field in fields(Signal) if field.name in keys}
    for key in ("entry", "sl", "tp1", "tp2"):
        terms[key] = Decimal(terms[key])
    if terms.get("tp3") is not None:
        terms["tp3"] = Decimal(terms["tp3"])
    for key in ("issued_at_utc", "expires_at_utc", "setup_closed_at_utc", "recorded_at"):
        terms[key] = datetime.fromisoformat(terms[key])
    return Signal(**terms), Outcome(
        status=Status(row["status"]),
        triggered_at=datetime.fromisoformat(row["triggered_at"]) if row["triggered_at"] else None,
        tp1_at=datetime.fromisoformat(row["tp1_at"]) if row["tp1_at"] else None,
        closed_at=datetime.fromisoformat(row["closed_at"]) if row["closed_at"] else None,
        result_r=Decimal(row["result_r"]) if row["result_r"] is not None else None,
        checked_until=datetime.fromisoformat(row["checked_until"]) if row["checked_until"] else None,
        tp2_at=datetime.fromisoformat(row["tp2_at"]) if "tp2_at" in keys and row["tp2_at"] else None,
    )


def save_outcome(connection: sqlite3.Connection, signal_id: str, state: Outcome) -> None:
    connection.execute(
        """UPDATE outcomes SET status = ?, triggered_at = ?, tp1_at = ?, closed_at = ?,
           result_r = ?, checked_until = ?, tp2_at = ?
           WHERE signal_id = ? AND status IN ('PENDING','ACTIVE','TP1','TP2_OPEN')""",
        (*(_value(value) for value in asdict(state).values()), signal_id),
    )
