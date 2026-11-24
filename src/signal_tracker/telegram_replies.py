"""Private preview delivery state: only reply to a confirmed signal post."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Literal

from .parallel_targets import SCHEMA as PLAN_SCHEMA, read_plan
from .signal import now_utc
from .store import from_record, transaction
from .telegram_format import format_data_gap, format_fixed_result, format_trade_result

ReplyKind = Literal["trade", "fixed", "gap"]
SCHEMA = """CREATE TABLE IF NOT EXISTS telegram_preview_threads (
    signal_id TEXT NOT NULL REFERENCES signals(signal_id),
    destination TEXT NOT NULL, message_id INTEGER NOT NULL,
    trade_sent INTEGER NOT NULL DEFAULT 0, fixed_sent INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (signal_id, destination)
)"""


@dataclass(frozen=True)
class Reply:
    signal_id: str
    message_id: int
    kind: ReplyKind
    text: str


def destination_key(chat: str) -> str:
    return sha256(f"telegram-preview:{chat}".encode()).hexdigest()


def remember_post(connection: sqlite3.Connection, signal_id: str, chat: str, message_id: int) -> None:
    connection.execute(SCHEMA)
    connection.execute(
        "INSERT OR IGNORE INTO telegram_preview_threads (signal_id, destination, message_id) VALUES (?, ?, ?)",
        (signal_id, destination_key(chat), message_id),
    )


def _ensure_gap_flag(connection: sqlite3.Connection) -> None:
    connection.execute(SCHEMA)
    if "gap_sent" not in {row["name"] for row in connection.execute("PRAGMA table_info(telegram_preview_threads)")}:
        connection.execute("ALTER TABLE telegram_preview_threads ADD COLUMN gap_sent INTEGER NOT NULL DEFAULT 0")


def pending_replies(db: Path, chat: str, enabled: set[str], at: datetime | None = None,
                    *, since: str | None = None) -> list[Reply]:
    replies: list[Reply] = []
    at = at or now_utc()
    with transaction(db) as connection:
        _ensure_gap_flag(connection)
        connection.execute(PLAN_SCHEMA)
        has_gaps = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='signal_gaps'").fetchone()
        gap_query = "(SELECT reason FROM signal_gaps g WHERE g.signal_id = ledger.signal_id)" if has_gaps else "NULL"
        rows = connection.execute(
            f"""SELECT ledger.*, versions.specification, message_id, trade_sent, fixed_sent, gap_sent,
                       {gap_query} AS official_gap,
                       plan.targets, plan.statuses, plan.phase, plan.checked_until AS plan_until,
                       plan.unresolved AS plan_gap
                FROM telegram_preview_threads
                JOIN signal_records ledger USING (signal_id)
                JOIN versions USING (strategy_code) LEFT JOIN parallel_targets plan USING (signal_id)
                WHERE destination = ? AND ledger.mode = 'LIVE' AND ledger.pair = 'XAUUSD'
                  AND (? IS NULL OR ledger.issued_at_utc >= ?)
                  AND (trade_sent = 0 OR fixed_sent = 0)
                ORDER BY ledger.issued_at_utc, ledger.signal_id""", (destination_key(chat), since, since)
        )
        for row in rows:
            signal, outcome = from_record(row)
            name = json.loads(row["specification"]).get("name") or signal.strategy_code
            ids = (signal.signal_id, row["message_id"])
            # A transient latest-minute delay is normal. Warn only after 15 minutes
            # of missing coverage, once per published signal, without inventing an exit.
            gap = row["official_gap"] if not row["trade_sent"] else None
            checkpoint = outcome.checked_until or signal.issued_at_utc
            scope = "Trade result"
            if not gap and "fixed" in enabled and not row["fixed_sent"] and row["plan_gap"]:
                gap = row["plan_gap"]
                checkpoint = datetime.fromisoformat(row["plan_until"]) if row["plan_until"] else signal.issued_at_utc
                scope = "Fixed-SL result"
            if gap and not row["gap_sent"] and at - checkpoint >= timedelta(minutes=15):
                replies.append(Reply(*ids, "gap", format_data_gap(signal, name, checkpoint, scope)))
            if row["official_gap"]:
                continue
            trade = format_trade_result(signal, name, outcome)
            if trade is None:
                continue
            if "trade" in enabled and not row["trade_sent"]:
                replies.append(Reply(*ids, "trade", trade))
            if "fixed" in enabled and not row["fixed_sent"] and row["phase"] == "CLOSED" and not row["plan_gap"]:
                fixed = format_fixed_result(signal, name, read_plan(row))
                if fixed is not None:
                    replies.append(Reply(*ids, "fixed", fixed))
    return replies


def acknowledge_reply(db: Path, chat: str, reply: Reply) -> None:
    column = {"trade": "trade_sent", "fixed": "fixed_sent", "gap": "gap_sent"}[reply.kind]
    with transaction(db) as connection:
        connection.execute(
            f"UPDATE telegram_preview_threads SET {column} = 1 WHERE signal_id = ? AND destination = ?",
            (reply.signal_id, destination_key(chat)),
        )
