"""Point-in-time filter evidence for historical runs."""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd

from .candles import DataError, timestamp_utc
from .config import load_object
from .research_data import parse_export_times
from .trend_pullback import SpreadQuote


@dataclass(frozen=True)
class CalendarSnapshot:
    captured: datetime
    start: datetime
    end: datetime
    relevant_events: tuple[datetime, ...]


class HistoricalCalendar:
    def __init__(self, snapshots: list[CalendarSnapshot]):
        self.snapshots = sorted(snapshots, key=lambda s: s.captured)
        self.times = [snapshot.captured for snapshot in self.snapshots]
        if len(set(self.times)) != len(self.times):
            raise DataError("Calendar snapshots must have unique capture times")

    @classmethod
    def read(cls, path: Path, rule: dict[str, Any]) -> "HistoricalCalendar":
        data = load_object(path)
        provenance = data.get("provenance")
        if not isinstance(data["snapshots"], list) or not isinstance(provenance, str) or not provenance.strip():
            raise DataError("Supply a calendar provenance note and a list of historical snapshots")
        snapshots = []
        for item in data["snapshots"]:
            captured, start, end = (
                timestamp_utc(item[key])
                for key in ("captured_at_utc", "coverage_start_utc", "coverage_end_utc")
            )
            if start >= end or not isinstance(item["events"], list):
                raise DataError("Invalid calendar coverage or event list")
            events = []
            for event in item["events"]:
                when = timestamp_utc(event["at_utc"])
                currency, impact = event["currency"], event["impact"]
                if (not start <= when < end or impact not in ("HIGH", "MEDIUM", "LOW")
                        or not isinstance(currency, str) or len(currency) != 3
                        or not currency.isalpha() or not currency.isupper()):
                    raise DataError("Each calendar event must have valid fields within snapshot coverage")
                if impact in rule["impact"] and currency in rule["currencies"]:
                    events.append(when)
            snapshots.append(CalendarSnapshot(captured, start, end, tuple(sorted(events))))
        return cls(snapshots)

    def status(self, at: datetime, rule: dict[str, Any]) -> str:
        index = bisect_right(self.times, at) - 1
        if index < 0:
            return "unknown"
        snapshot = self.snapshots[index]
        low = at - timedelta(minutes=rule["minutes_after"])
        high = at + timedelta(minutes=rule["minutes_before"])
        if not snapshot.start <= low <= high < snapshot.end:
            return "unknown"
        pos = bisect_left(snapshot.relevant_events, low)
        if pos < len(snapshot.relevant_events) and snapshot.relevant_events[pos] <= high:
            return "blocked"
        return "ok"


class HistoricalQuotes:
    def __init__(self, observations: list[SpreadQuote]):
        self.quotes = sorted(observations, key=lambda q: q.observed_at)
        self.times = [quote.observed_at for quote in self.quotes]
        if len(set(self.times)) != len(self.times):
            raise DataError("Spread observation times must be unique")

    @classmethod
    def read(cls, path: Path, feed: str) -> "HistoricalQuotes":
        data = pd.read_csv(path, dtype=str)
        if not {"observed_at_utc", "pair", "data_source", "bid", "ask"}.issubset(data):
            raise DataError("Spread CSV needs observed_at_utc, pair, data_source, bid and ask")
        if not data["pair"].eq("XAUUSD").all() or not data["data_source"].eq(feed).all():
            raise DataError("Spread observations must use XAUUSD and the same feed as the candles")
        quotes = []
        for at, bid, ask in zip(parse_export_times(data["observed_at_utc"]), data["bid"], data["ask"]):
            try:
                bid, ask = Decimal(bid), Decimal(ask)
                if not bid.is_finite() or not ask.is_finite() or not 0 < bid <= ask:
                    raise DataError("Invalid bid/ask observation")
            except (InvalidOperation, TypeError) as error:
                raise DataError("Invalid bid/ask observation") from error
            # Keep the full provider timestamp precision at the decision boundary.
            quotes.append(SpreadQuote(ask - bid, at))
        return cls(quotes)

    def as_of(self, at: datetime) -> SpreadQuote | None:
        pos = bisect_right(self.times, at) - 1
        return self.quotes[pos] if pos >= 0 else None
