"""Immutable published terms and separate, evolving outcomes."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum


class Status(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    TP1 = "TP1"
    TP2 = "TP2"
    TP2_OPEN = "TP2_OPEN"
    TP3 = "TP3"
    SL = "SL"
    BE = "BE"
    EXPIRED = "EXPIRED"


TERMINAL = {Status.TP2, Status.TP3, Status.SL, Status.BE, Status.EXPIRED}


def now_utc() -> datetime:
    return datetime.now(UTC)


def utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Expected a timezone-aware timestamp")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


@dataclass(frozen=True)
class Signal:
    signal_id: str
    strategy_code: str
    source: str
    style: str
    pair: str
    direction: str
    entry: Decimal
    sl: Decimal
    tp1: Decimal
    tp2: Decimal
    issued_at_utc: datetime
    expires_at_utc: datetime
    data_source: str
    notes: str
    mode: str
    setup_closed_at_utc: datetime
    recorded_at: datetime
    tp3: Decimal | None = None

    def __post_init__(self) -> None:
        prices = (self.sl, self.entry, self.tp1, self.tp2)
        if any(not price.is_finite() or price <= 0 for price in prices):
            raise ValueError("Signal prices must be finite and positive")
        sl, entry, tp1, tp2 = prices
        if not (
            (self.direction == "BUY" and sl < entry < tp1 < tp2)
            or (self.direction == "SELL" and sl > entry > tp1 > tp2)
        ):
            raise ValueError("Signal levels must be strictly ordered for BUY or SELL")
        if self.tp3 is not None and (
            not self.tp3.is_finite() or self.tp3 <= 0
            or not (self.tp3 > tp2 if self.direction == "BUY" else self.tp3 < tp2)
        ):
            raise ValueError("TP3 must be a positive target beyond TP2")
        for value in (self.setup_closed_at_utc, self.issued_at_utc, self.expires_at_utc, self.recorded_at):
            utc(value)
        if not self.setup_closed_at_utc <= self.issued_at_utc < self.expires_at_utc:
            raise ValueError("Invalid setup, issue, or expiry times")
        if self.mode not in ("LIVE", "REPLAY", "BACKTEST"):
            raise ValueError("Unsupported signal mode")
        if self.recorded_at < self.issued_at_utc or (
            self.mode == "LIVE" and self.recorded_at != self.issued_at_utc
        ):
            raise ValueError("A LIVE signal must be recorded at issue time, never backdated")


@dataclass(frozen=True)
class Outcome:
    status: Status = Status.PENDING
    triggered_at: datetime | None = None
    tp1_at: datetime | None = None
    closed_at: datetime | None = None
    result_r: Decimal | None = None
    checked_until: datetime | None = None
    tp2_at: datetime | None = None
