"""The common, UTC, closed-candle contract used by both data adapters."""

from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite

import pandas as pd

from .config import TIMEFRAMES

OHLC = ["open", "high", "low", "close"]


class DataError(ValueError):
    """Market data is unavailable, malformed, or not safe to use."""


def timestamp_utc(value: str | datetime | pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp) or timestamp.tzinfo is None:
        raise DataError("Timestamps must include a timezone, e.g. 2024-01-03T00:00:00Z")
    return timestamp.tz_convert("UTC")


@dataclass(frozen=True)
class CandleWindow:
    """A half-open UTC time range. A candle ending exactly at end is included."""

    start: pd.Timestamp
    end: pd.Timestamp
    timeframe: str
    duration: pd.Timedelta

    @classmethod
    def create(cls, start: str, end: str, timeframe: str) -> "CandleWindow":
        if timeframe not in TIMEFRAMES:
            raise DataError(f"Unknown timeframe: {timeframe}")
        first, last = timestamp_utc(start), timestamp_utc(end)
        duration = pd.Timedelta(minutes=TIMEFRAMES[timeframe])
        if first >= last or last > datetime.now(UTC):
            raise DataError("Require start < end and end no later than the current UTC time")
        if first.value % duration.value or last.value % duration.value:
            raise DataError(f"Start and end must be aligned to {timeframe} UTC boundaries")
        return cls(first, last, timeframe, duration)


def validate_ohlc(frame: pd.DataFrame) -> None:
    prices = frame[OHLC]
    invalid = (
        (~prices.map(isfinite)).any(axis=1)
        | (prices <= 0).any(axis=1)
        | (frame["low"] > frame[["open", "close"]].min(axis=1))
        | (frame["high"] < frame[["open", "close"]].max(axis=1))
    )
    if invalid.any():
        raise DataError(f"Invalid OHLC values at {frame.index[invalid][0]}")


def closed_frame(
    frame: pd.DataFrame, window: CandleWindow, *, pair: str, data_source: str
) -> pd.DataFrame:
    """Sort and label bars. Missing bars are never interpolated or forward-filled."""
    frame = frame.sort_index()
    if frame.index.has_duplicates:
        raise DataError("Duplicate candle timestamps; check for overlapping inputs")
    frame = frame.loc[
        (frame.index >= window.start) & (frame.index + window.duration <= window.end)
    ].copy()
    if frame.empty:
        raise DataError("No usable closed candles in the requested window")
    # timedelta modulo works across pandas timestamp resolutions.
    if ((frame.index - window.start) % window.duration != pd.Timedelta(0)).any():
        raise DataError(f"Source returned candles not aligned to {window.timeframe} UTC boundaries")
    validate_ohlc(frame)
    frame.index.name = "opened_at_utc"
    frame.insert(0, "closed_at_utc", frame.index + window.duration)
    frame.insert(1, "pair", pair)
    frame.insert(2, "timeframe", window.timeframe)
    frame.insert(3, "data_source", data_source)
    return frame
