"""CLD-INT-01: a deterministic proposal from already-closed H1 and M15 bars."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from .candles import timestamp_utc
from .indicators import atr, ema, rsi

CODE = "CLD-INT-01-v1"
M15 = timedelta(minutes=15)


@dataclass(frozen=True)
class Decision:
    kind: str
    reason: str
    direction: str | None = None
    setup_at: datetime | None = None
    levels: tuple[Decimal, ...] | None = None


@dataclass(frozen=True)
class SpreadQuote:
    price: Decimal
    observed_at: datetime


def _news_blocked(calendar: dict[str, Any] | None, at: datetime, rule: dict[str, Any]) -> bool:
    if calendar is None:
        return True
    before = timedelta(minutes=rule["minutes_before"])
    after = timedelta(minutes=rule["minutes_after"])
    # A future event within `before`, or a recent event within `after`, can block.
    if not (timestamp_utc(calendar["coverage_start_utc"]) <= at - after
            and timestamp_utc(calendar["coverage_end_utc"]) > at + before):
        return True
    if not isinstance(calendar["events"], list):
        raise ValueError("News calendar events must be a list")
    blocked = False
    for event in calendar["events"]:
        time = timestamp_utc(event["at_utc"])
        if event["impact"] not in ("HIGH", "MEDIUM", "LOW") or not (
            isinstance(event["currency"], str) and len(event["currency"]) == 3 and event["currency"].isupper()
        ):
            raise ValueError("News events require HIGH/MEDIUM/LOW impact and an uppercase currency code")
        if (event["impact"] in rule["impact"] and event["currency"] in rule["currencies"]
                and time - before <= at <= time + after):
            blocked = True
    return blocked


def _session(at: datetime, sessions: dict[str, Any]) -> str | None:
    for name, rule in sessions.items():
        local = at.astimezone(ZoneInfo(rule["timezone"]))
        if local.weekday() < 5 and rule["start_hour"] <= local.hour < rule["end_hour"]:
            return name
    return None


def spread_status(quote: SpreadQuote | None, as_of: datetime, rule: dict[str, Any]) -> str:
    """Separate unobservable spread from a valid observation that is too wide."""
    if (quote is None or not quote.price.is_finite() or quote.price < 0
            or not timedelta(0) <= as_of - quote.observed_at <= timedelta(seconds=rule["max_age_seconds"])):
        return "unknown"
    return "wide" if quote.price > Decimal(rule["max_spread_price"]) else "ok"


def evaluate(
    m15: pd.DataFrame, h1: pd.DataFrame, spec: dict[str, Any], as_of: datetime,
    *, calendar: dict[str, Any] | None, quote: SpreadQuote | None,
) -> Decision:
    """Calculate at a decision instant, never using bars that close later."""
    if spec["implementation"] != "trend_pullback_v1":
        raise ValueError("Unsupported strategy implementation")
    session = _session(as_of, spec["session_filter"])
    if session is None:
        return Decision("SKIP", "Outside London/New York session")
    if _news_blocked(calendar, as_of, spec["news_filter"]):
        return Decision("SKIP", "High-impact news window or missing calendar coverage")
    if spread_status(quote, as_of, spec["spread_filter"]) != "ok":
        return Decision("SKIP", "Spread is too wide, missing, stale or future-dated")

    return PreparedTrend(
        m15.loc[m15["closed_at_utc"] <= as_of],
        h1.loc[h1["closed_at_utc"] <= as_of], spec,
    ).at(as_of, session)


class PreparedTrend:
    """Cache causal indicators once instead of recomputing on each historical close."""

    def __init__(self, m15: pd.DataFrame, h1: pd.DataFrame, spec: dict[str, Any]):
        if spec["implementation"] != "trend_pullback_v1":
            raise ValueError("Unsupported strategy implementation")
        for bars in (m15, h1):
            times = bars["closed_at_utc"]
            if not times.is_monotonic_increasing or times.duplicated().any():
                raise ValueError("Strategy candles must be uniquely sorted by close time")
        self.spec = spec
        self.mtime = pd.DatetimeIndex(m15["closed_at_utc"])
        self.htime = pd.DatetimeIndex(h1["closed_at_utc"])
        self.trend = ema(h1["close"], spec["trend"]["ema_period"]).to_numpy()
        self.hclose = h1["close"].to_numpy()
        self.close = m15["close"].to_numpy()
        self.high, self.low = m15["high"].to_numpy(), m15["low"].to_numpy()
        self.rsi = rsi(m15["close"], spec["setup"]["rsi_period"]).to_numpy()
        self.ema = [ema(m15["close"], period).shift(1).to_numpy() for period in spec["setup"]["ema_periods"]]
        self.distance = atr(m15, spec["stop"]["atr_period"]).to_numpy() * spec["stop"]["atr_multiple"]

    def at(self, as_of: datetime, session: str) -> Decision:
        # Both timeframes are joined on close time, never on the opening timestamp.
        i = self.mtime.searchsorted(as_of, side="right") - 1
        if i < 2 or as_of - self.mtime[i] >= M15:
            return Decision("SKIP", "No fresh closed M15 candle")
        latest = self.mtime[i]
        if latest - self.mtime[i - 2] != 2 * M15 or latest - self.mtime[i - 1] != M15:
            return Decision("SKIP", "M15 setup crosses a missing candle")
        j = self.htime.searchsorted(latest, side="right") - 1
        if j < 0 or latest - self.htime[j] >= timedelta(hours=1):
            return Decision("SKIP", "No fresh H1 trend candle at setup close")
        trend_ema, trend_close = self.trend[j], self.hclose[j]
        if pd.isna(trend_ema) or trend_close == trend_ema:
            return Decision("SKIP", "H1 EMA not warmed up or trend is flat")
        direction = "BUY" if trend_close > trend_ema else "SELL"
        sign = 1 if direction == "BUY" else -1
        left, pivot, right = self.rsi[i - 2:i + 1]
        if pd.isna(left) or pd.isna(pivot) or pd.isna(right):
            return Decision("SKIP", "RSI not warmed up")
        lo, hi = self.spec["setup"][f"{direction.lower()}_rsi_range"]
        if all(pd.isna(band[i - 1]) or pd.isna(band[i]) for band in self.ema):
            return Decision("SKIP", "M15 EMA not warmed up")

        def touched(row: int, *, confirm: bool) -> bool:
            return any(
                self.low[row] <= level <= self.high[row]
                and (not confirm or sign * (self.close[i] - level) > 0)
                for level in (band[row] for band in self.ema)
            )

        at = latest.to_pydatetime()
        if lo <= pivot <= hi and sign * (left - pivot) > 0 and sign * (right - pivot) > 0 and touched(i - 1, confirm=True):
            distance = self.distance[i]
            tick = Decimal(self.spec["price_tick"])

            def quantize(value: Decimal) -> Decimal:
                return (value / tick).quantize(Decimal(1), rounding=ROUND_HALF_UP) * tick

            entry = quantize(Decimal(str(self.close[i])))
            if pd.isna(distance) or distance <= 0:
                return Decision("SKIP", "ATR not warmed up or zero")
            stop = quantize(entry - sign * Decimal(str(distance)))
            risk = abs(entry - stop)
            if risk == 0:
                return Decision("SKIP", "ATR risk rounded to zero")
            target1, target2 = (quantize(entry + sign * risk * Decimal(str(r))) for r in self.spec["take_profit_r"])
            if min(entry, stop, target1, target2) <= 0:
                return Decision("SKIP", "ATR levels are not positive")
            return Decision("SIGNAL", session, direction, at, (entry, stop, target1, target2))
        if lo <= right <= hi and sign * (pivot - right) > 0 and touched(i, confirm=False):
            return Decision("PREPARE", f"{session}: setup forming, no confirmed entry", direction, at)
        return Decision("SKIP", "No confirmed pullback")
