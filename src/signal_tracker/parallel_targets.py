"""Independent equal-size target orders with fixed original stops; gross R only."""

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from .checker import MINUTE, Bar, Execution, first_full_minute, quote_offsets
from .signal import Signal, utc

SCHEMA = """CREATE TABLE IF NOT EXISTS parallel_targets (
    signal_id TEXT PRIMARY KEY REFERENCES signals(signal_id), targets TEXT NOT NULL,
    statuses TEXT NOT NULL, phase TEXT NOT NULL DEFAULT 'PENDING',
    checked_until TEXT, unresolved TEXT
)"""


@dataclass(frozen=True)
class TargetPlan:
    targets: tuple[Decimal, ...]
    statuses: tuple[str, ...]
    phase: str = "PENDING"
    checked_until: datetime | None = None


def create(connection: sqlite3.Connection, signal: Signal, tp3: Decimal | None) -> None:
    targets = (signal.tp1, signal.tp2) if tp3 is None else (signal.tp1, signal.tp2, tp3)
    connection.execute(SCHEMA)
    connection.execute("INSERT INTO parallel_targets (signal_id, targets, statuses) VALUES (?, ?, ?)",
                       (signal.signal_id, json.dumps([str(x) for x in targets]), json.dumps(["OPEN"] * len(targets))))


def records(connection: sqlite3.Connection, cutoff: datetime) -> list[sqlite3.Row]:
    return connection.execute(
        """SELECT signal_records.*, versions.specification, targets, statuses, phase,
                  parallel_targets.checked_until AS plan_until, parallel_targets.unresolved AS plan_gap
           FROM parallel_targets JOIN signal_records USING (signal_id) JOIN versions USING (strategy_code)
           WHERE mode = 'LIVE' AND issued_at_utc <= ? AND phase IN ('PENDING','ACTIVE')
           ORDER BY issued_at_utc, signal_id""", (utc(cutoff),),
    ).fetchall()


def read_plan(row: sqlite3.Row) -> TargetPlan:
    return TargetPlan(tuple(map(Decimal, json.loads(row["targets"]))), tuple(json.loads(row["statuses"])), row["phase"],
                      datetime.fromisoformat(row["plan_until"]) if row["plan_until"] else None)


def advance_plan(signal: Signal, plan: TargetPlan, model: Execution, cutoff: datetime,
                 get_bar: Callable[[datetime], Bar | None]) -> tuple[TargetPlan, datetime | None]:
    expected = plan.checked_until or first_full_minute(signal.issued_at_utc)
    deadline = signal.expires_at_utc.replace(second=0, microsecond=0)
    buy = signal.direction == "BUY"
    entry_offset, exit_offset = quote_offsets(signal.direction, model)
    while plan.phase in ("PENDING", "ACTIVE") and expected + MINUTE <= cutoff:
        if plan.phase == "PENDING" and expected + MINUTE > signal.expires_at_utc:
            break
        bar = get_bar(expected)
        if bar is None:
            return plan, expected
        expected += MINUTE
        plan = replace(plan, checked_until=expected)
        entering = plan.phase == "PENDING"
        if entering:
            if not bar.low + entry_offset <= signal.entry <= bar.high + entry_offset:
                continue
            plan = replace(plan, phase="ACTIVE")
        stop = bar.low + exit_offset <= signal.sl if buy else bar.high + exit_offset >= signal.sl
        extreme = bar.high + exit_offset if buy else bar.low + exit_offset
        statuses = tuple(
            status if status != "OPEN" else "SL" if stop else
            "TP" if not entering and (extreme >= target if buy else extreme <= target) else "OPEN"
            for status, target in zip(plan.statuses, plan.targets, strict=True)
        )
        plan = replace(plan, statuses=statuses, phase="ACTIVE" if "OPEN" in statuses else "CLOSED")
    if plan.phase == "PENDING" and cutoff >= signal.expires_at_utc and expected >= deadline:
        plan = replace(plan, phase="EXPIRED", statuses=("EXPIRED",) * len(plan.targets))
    return plan, None


def save(connection: sqlite3.Connection, signal_id: str, plan: TargetPlan, reason: str | None) -> None:
    connection.execute(
        "UPDATE parallel_targets SET statuses=?, phase=?, checked_until=?, unresolved=? WHERE signal_id=?",
        (json.dumps(plan.statuses), plan.phase, utc(plan.checked_until) if plan.checked_until else None, reason, signal_id),
    )


def target_order_r(entry: Decimal, sl: Decimal, target: Decimal, status: str) -> Decimal | None:
    if status == "TP":
        return abs(target - entry) / abs(entry - sl)
    return Decimal(-1) if status == "SL" else None


def public_plans(connection: sqlite3.Connection) -> dict[str, dict]:
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='parallel_targets'").fetchone():
        return {}
    results = {}
    for signal_id, entry, sl, raw_targets, raw_statuses, phase, gap in connection.execute(
        "SELECT signal_id, entry, sl, targets, statuses, phase, unresolved FROM parallel_targets JOIN signals USING (signal_id)"
    ):
        legs = []
        for index, (target, status) in enumerate(zip(json.loads(raw_targets), json.loads(raw_statuses), strict=True), 1):
            value = target_order_r(Decimal(entry), Decimal(sl), Decimal(target), status)
            legs.append({"target": index, "status": status, "result_r": value})
        closed = [leg["result_r"] for leg in legs if leg["result_r"] is not None]
        total = sum(closed, Decimal(0)) if closed else None
        results[signal_id] = {
            "phase": phase, "legs": legs, "realized_r": total,
            "per_total_risk_r": total / len(legs) if total is not None else None,
            "unresolved_reason": gap,
        }
    return results
