"""Optional third price target, independent of the frozen trade's exits and R."""

import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Callable

import pandas as pd

from .checker import Bar, Execution, advance
from .config import TIMEFRAMES
from .signal import Outcome, Signal, Status, utc

SCHEMA = """CREATE TABLE IF NOT EXISTS tp3_watch (
    signal_id TEXT PRIMARY KEY REFERENCES signals(signal_id), target TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'PENDING', checked_until TEXT, hit_at TEXT, unresolved TEXT
)"""
WATCHING = ("PENDING", "ACTIVE", "TP1")
PIVOT_WINDOW = 20
MIN_GAP_R = Decimal("0.25")
MAX_TARGET_R = Decimal("5")


def suggest(signal: Signal, candles: pd.DataFrame, frame: str, tick: Decimal) -> Decimal | None:
    """Nearest confirmed trend-frame pivot from 0.25R beyond TP2 to 5R."""
    direction = 1 if signal.direction == "BUY" else -1
    risk = abs(signal.entry - signal.sl)
    closes = candles.loc[candles["closed_at_utc"] <= signal.setup_closed_at_utc].sort_values("closed_at_utc").tail(PIVOT_WINDOW)
    step = timedelta(minutes=TIMEFRAMES[frame])
    field = "high" if direction == 1 else "low"
    stamps = closes["closed_at_utc"].tolist()
    values = closes[field].tolist()
    candidates = []
    for i in range(1, len(values) - 1):
        if stamps[i] - stamps[i - 1] != step or stamps[i + 1] - stamps[i] != step:
            continue
        window = values[i - 1:i + 2]
        if any(pd.isna(raw) for raw in window):
            continue
        left, pivot, right = (Decimal(str(raw)) for raw in window)
        if not all(value.is_finite() for value in (left, pivot, right)):
            continue
        if direction * (pivot - left) <= 0 or direction * (pivot - right) <= 0:
            continue
        # Place the target one tick inside the pivot, rounded toward entry.
        price = ((pivot / tick).to_integral_value(rounding=ROUND_FLOOR if direction == 1 else ROUND_CEILING)
                 - direction) * tick
        if price > 0 and direction * (price - signal.tp2) >= MIN_GAP_R * risk \
                and direction * (price - signal.entry) <= MAX_TARGET_R * risk:
            candidates.append(price)
    return min(candidates, key=lambda price: direction * price) if candidates else None


def open_watches(connection: sqlite3.Connection, cutoff: datetime) -> list[sqlite3.Row]:
    return connection.execute(
        """SELECT signal_records.*, versions.specification, target, tp3_watch.state AS watch_state,
                  tp3_watch.checked_until AS watch_until, tp3_watch.unresolved AS watch_unresolved
           FROM tp3_watch JOIN signal_records USING (signal_id) JOIN versions USING (strategy_code)
           WHERE mode = 'LIVE' AND issued_at_utc <= ? AND tp3_watch.state IN ('PENDING','ACTIVE','TP1')
           ORDER BY issued_at_utc, signal_id""", (utc(cutoff),),
    ).fetchall()


def watch_outcome(row: sqlite3.Row) -> Outcome:
    return Outcome(status=Status(row["watch_state"]),
                   checked_until=datetime.fromisoformat(row["watch_until"]) if row["watch_until"] else None)


def advance_watch(signal: Signal, state: Outcome, target: Decimal, model: Execution,
                  as_of: datetime, get_bar: Callable[[datetime], Bar | None]) -> tuple[Outcome, datetime | None]:
    # Use the same execution-side prices, conservative candle ordering and BE
    # rule. This independent model's R is never stored or used in statistics.
    return advance(replace(signal, tp2=target, tp3=None), state, replace(model, tp2_fraction=None), as_of, get_bar)


def public_watches(connection: sqlite3.Connection) -> dict[str, dict]:
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='tp3_watch'").fetchone():
        return {}
    labels = {"TP2": "HIT", "BE": "STOPPED", "SL": "STOPPED", "EXPIRED": "EXPIRED"}
    return {
        signal_id: {"price": target, "state": "UNRESOLVED" if unresolved else labels.get(state, "WATCHING"),
                    "hit_at": hit_at, "unresolved_reason": unresolved}
        for signal_id, target, state, hit_at, unresolved in connection.execute(
            "SELECT signal_id, target, state, hit_at, unresolved FROM tp3_watch")
    }
