"""Keyless XAUUSD midpoint candles, observed quotes and US news evidence."""

import json
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from .candles import OHLC, CandleWindow, DataError, closed_frame, timestamp_utc
from .signal import utc

SOURCE = "BIQUOTE_XAUUSD_MID"
INTERVALS = {"M1": "1m", "M5": "5m", "M15": "15m", "H1": "1h", "H4": "4h", "D1": "1d"}
CALENDAR_LIMIT = 200


def _get(path: str, **params):
    url = f"https://biquote.io/api/{path}?{urlencode(params)}"
    try:
        with urlopen(Request(url, headers={"User-Agent": "XAUUSD testing signal tracker", "Accept": "application/json"}),
                     timeout=8) as response:
            body = response.read(1_500_001)
        if len(body) > 1_500_000:
            raise DataError("Biquote payload exceeded the size limit")
        return json.loads(body, parse_float=Decimal)
    except (OSError, URLError, UnicodeError, json.JSONDecodeError) as error:
        raise DataError("Biquote request failed or was unavailable") from error


def candles(pair: str, window: CandleWindow) -> pd.DataFrame:
    if pair != "XAUUSD":
        raise DataError("The Biquote pilot supports XAUUSD only")
    interval = INTERVALS[window.timeframe]
    data = _get("XAUUSD/ohlc", interval=interval, limit=500, to=utc(window.end))
    if not isinstance(data, dict) or data.get("symbol") != pair or data.get("interval") != interval:
        raise DataError("Biquote returned the wrong market or interval")
    try:
        rows = []
        for bar in data["bars"]:
            if type(bar["isOpen"]) is not bool:
                raise DataError("Biquote did not confirm whether a candle was closed")
            if not bar["isOpen"]:
                rows.append((timestamp_utc(bar["openTime"]), [float(bar[key]) for key in OHLC]))
        frame = pd.DataFrame([values for _, values in rows], columns=OHLC,
                             index=pd.DatetimeIndex([stamp for stamp, _ in rows], tz="UTC"))
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise DataError("Invalid Biquote candle data") from error
    return closed_frame(frame, window, pair=pair, data_source=SOURCE)


def spread() -> tuple[Decimal, pd.Timestamp]:
    try:
        quote = _get("XAUUSD", allowStale="false")
        if quote["symbol"] != "XAUUSD":
            raise DataError("The quote was not for XAUUSD")
        stamp = timestamp_utc(quote["timestamp"])
        bid, ask = (Decimal(str(quote[name])) for name in ("bid", "ask"))
        if not bid.is_finite() or not ask.is_finite() or not 0 < bid <= ask:
            raise DataError("Biquote returned invalid bid/ask prices")
        return ask - bid, stamp
    except (KeyError, TypeError, ValueError, InvalidOperation) as error:
        raise DataError("No usable Biquote bid/ask quote") from error


def calendar(at: datetime, clock) -> dict | None:
    """Use the provider's live US high-impact schedule, not a historical backfill."""
    start, end = at - timedelta(days=7), at + timedelta(days=7)
    data = _get("calendar", **{"from": utc(start), "to": utc(end), "countries": "US",
                              "importance": "high", "limit": CALENDAR_LIMIT})
    if not isinstance(data, list) or not 0 < len(data) < CALENDAR_LIMIT:
        return None
    try:
        dates, events = [], []
        for row in data:
            time = timestamp_utc(row["time"]).to_pydatetime()
            if not start <= time < end or row["countryCode"] != "US" or row["currency"] != "USD" or row["importance"] != "high":
                return None
            mode = row["timeMode"]
            if mode not in {"exact", "tentative", "date", "notime"}:
                return None
            events.append({"at_utc": utc(time), "currency": "USD", "impact": "HIGH"})
            if mode != "exact":
                dates.append(time.date())
        # A quiet day is valid, but do not trust an empty or one-sided calendar
        # response as evidence that there is no news.
        times = [timestamp_utc(row["at_utc"]) for row in events]
        if not min(times) < at < max(times):
            return None
        if any(at.date() + timedelta(days=offset) in dates for offset in (-1, 0, 1)):
            return None
    except (TypeError, ValueError, KeyError):
        return None
    return {"source": "biquote US high-impact economic calendar (provider response, not independently reviewed)",
            "verified_at_utc": utc(clock()), "coverage_start_utc": utc(start),
            "coverage_end_utc": utc(end), "events": events}
