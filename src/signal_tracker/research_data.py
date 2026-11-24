"""Validate Phase 1 candle exports before any price is used for Phase 2."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

from .candles import OHLC, DataError, validate_ohlc
from .checker import Bar
from .config import TIMEFRAMES
from .sources import HISTDATA_SOURCE, OANDA_SOURCE


def parse_export_times(values: pd.Series) -> pd.Series:
    """Read aware ISO timestamps in bulk; never assume a timezone for naive data."""
    if not values.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", regex=True, na=False).all():
        raise DataError("Export timestamps must be ISO times with explicit timezone offsets")
    return pd.to_datetime(values, format="ISO8601", utc=True)


def read_bars(path: Path, timeframe: str) -> pd.DataFrame:
    bars = pd.read_csv(path, dtype=str)
    required = {"opened_at_utc", "closed_at_utc", "pair", "timeframe", "data_source", *OHLC}
    if bars.empty or not required.issubset(bars):
        raise DataError(f"{path}: expected a nonempty Phase 1 candle export")
    if not bars["pair"].eq("XAUUSD").all() or not bars["timeframe"].eq(timeframe).all():
        raise DataError(f"{path}: expected only XAUUSD {timeframe} candles")
    feeds = set(bars["data_source"])
    if len(feeds) != 1 or not feeds.issubset({HISTDATA_SOURCE, OANDA_SOURCE}):
        raise DataError(f"{path}: expected one recognized bid candle feed, not mixed data")
    for column in OHLC:
        bars[column] = pd.to_numeric(bars[column], errors="raise")
    for column in ("opened_at_utc", "closed_at_utc"):
        bars[column] = parse_export_times(bars[column])
    bars = bars.set_index("opened_at_utc").sort_index()
    minutes = TIMEFRAMES[timeframe]
    if (bars.index.has_duplicates or (bars.index != bars.index.floor(f"{minutes}min")).any()
            or not bars["closed_at_utc"].eq(bars.index + pd.Timedelta(minutes=minutes)).all()):
        raise DataError(f"{path}: invalid, unaligned or duplicate candle times")
    validate_ohlc(bars)
    # D1 and H4 aggregates can contain the normal daily gold halt. Allow
    # enough coverage for one planned break, not near-empty early-close bars.
    minimum = {"H4": 180, "D1": 1320}.get(timeframe)
    if minimum is not None and HISTDATA_SOURCE in feeds:
        if "source_bars" not in bars:
            raise DataError(f"{path}: higher-timeframe archives need source minute counts")
        counts = pd.to_numeric(bars["source_bars"], errors="raise")
        if (counts.isna() | (counts % 1 != 0) | (counts < 0) | (counts > minutes)).any():
            raise DataError(f"{path}: invalid source minute counts")
        bars = bars.loc[counts >= minimum].copy()
        if bars.empty:
            raise DataError(f"{path}: no {timeframe} candles meet the minimum archive coverage")
    return bars


class MinuteLookup:
    """Construct execution bars on demand rather than copying every price to Decimal."""

    def __init__(self, frame: pd.DataFrame):
        self.index = frame.index
        self.prices = frame[["open", "high", "low"]].to_numpy()

    def __call__(self, opened: datetime) -> Bar | None:
        try:
            pos = self.index.get_loc(opened)
        except KeyError:
            return None
        return Bar(opened, *(Decimal(str(value)) for value in self.prices[pos]))
