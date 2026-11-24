"""Read free historical spot-price candles. The adapters never place orders."""

import json
import logging
import os
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile

import pandas as pd

from .candles import OHLC, CandleWindow, DataError, closed_frame, timestamp_utc, validate_ohlc

LOG = logging.getLogger(__name__)
OANDA_PRACTICE = "https://api-fxpractice.oanda.com/v3"
HISTDATA_SOURCE = "HISTDATA_ASCII_M1_BID"
OANDA_SOURCE = "OANDA_PRACTICE_BID"


def _practice_get(path: str, token: str, params: dict[str, str], context: str) -> dict:
    request = Request(
        f"{OANDA_PRACTICE}/{path}?{urlencode(params)}",
        headers={"Authorization": f"Bearer {token}", "Accept-Datetime-Format": "RFC3339"},
    )
    for attempt in range(3):
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.load(response)
            if not isinstance(payload, dict):
                raise DataError("OANDA returned an invalid response")
            return payload
        except HTTPError as error:
            if error.code in (401, 403):
                raise DataError("OANDA refused access; check the practice token and instrument availability") from error
            if error.code == 429:
                raise DataError("OANDA rate-limited the request; retry later") from error
            if error.code < 500 or attempt == 2:
                raise DataError(f"OANDA returned HTTP {error.code} for {context}") from error
        except (URLError, TimeoutError) as error:
            if attempt == 2:
                raise DataError(f"Unable to reach OANDA practice for {context}") from error
        except (ValueError, UnicodeDecodeError) as error:
            raise DataError("Unable to decode the OANDA JSON response") from error
        sleep(2**attempt)
    raise AssertionError("OANDA retry loop did not finish")


def _download_oanda(instrument: str, token: str, params: dict[str, str]) -> dict:
    return _practice_get(f"instruments/{instrument}/candles", token, params, instrument)


def fetch_practice_spread(instrument: str, account: str, token: str) -> tuple[Decimal, pd.Timestamp]:
    """Use a timestamped tradeable top-of-book bid and ask, never the model spread."""
    if not re.fullmatch(r"[A-Z0-9]+_[A-Z0-9]+", instrument) or not re.fullmatch(r"\d+-\d+-\d+-\d+", account):
        raise DataError("Invalid OANDA practice account or instrument format")
    payload = _practice_get(f"accounts/{account}/pricing", token, {"instruments": instrument}, "practice quote")
    try:
        price, = [price for price in payload["prices"] if price["instrument"] == instrument]
        if price["tradeable"] is not True:
            raise ValueError("Quote is not tradeable")
        bid, ask = (Decimal(price[key][0]["price"]) for key in ("bids", "asks"))
        if not bid.is_finite() or not ask.is_finite() or bid <= 0 or ask < bid:
            raise ValueError("Invalid quote levels")
        return ask - bid, timestamp_utc(price["time"])
    except (TypeError, KeyError, IndexError, ValueError, InvalidOperation) as error:
        raise DataError("No valid tradeable bid/ask quote from OANDA practice") from error


def fetch_oanda(pair: str, instrument: str, window: CandleWindow) -> pd.DataFrame:
    """Fetch completed bid candles with bounded request sizes and UTC alignment."""
    if not re.fullmatch(r"[A-Z0-9]+_[A-Z0-9]+", instrument):
        raise DataError("Invalid OANDA instrument mapping")
    token = os.environ.get("OANDA_API_TOKEN", "").strip()
    if not token:
        raise DataError("Set OANDA_API_TOKEN with a practice API token, or use a HistData download")
    rows: list[dict] = []
    cursor = window.start
    while cursor < window.end:
        page_end = min(cursor + window.duration * 4500, window.end)
        params = {
            "from": cursor.isoformat(),
            "to": page_end.isoformat(),
            "granularity": window.timeframe,
            "price": "B",
            "smooth": "false",
            "alignmentTimezone": "UTC",
            "dailyAlignment": "0",
        }
        LOG.info("Fetching %s %s: %s to %s", pair, window.timeframe, cursor, page_end)
        payload = _download_oanda(instrument, token, params)
        page = payload.get("candles")
        if not isinstance(page, list):
            raise DataError("OANDA response is missing its candle list")
        try:
            for candle in page:
                if not isinstance(candle["complete"], bool):
                    raise ValueError("Invalid completion flag")
                if not candle["complete"]:
                    continue
                opened = timestamp_utc(candle["time"])
                if not cursor <= opened < page_end:
                    continue
                bid = candle["bid"]
                rows.append({
                    "opened_at_utc": opened,
                    "open": float(bid["o"]),
                    "high": float(bid["h"]),
                    "low": float(bid["l"]),
                    "close": float(bid["c"]),
                    "volume": int(candle["volume"]),
                })
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise DataError(f"Invalid OANDA candle near {cursor}") from error
        cursor = page_end

    if not rows:
        raise DataError("OANDA did not return any usable closed candles")
    frame = pd.DataFrame(rows).set_index("opened_at_utc")
    return closed_frame(frame, window, pair=pair, data_source=OANDA_SOURCE)


def _read_histdata(path: Path, symbol: str) -> pd.DataFrame:
    csv_name = re.compile(rf"DAT_ASCII_{re.escape(symbol)}_M1_\d{{4}}(?:\d{{2}})?\.csv", re.I)
    columns = ["timestamp", *OHLC, "volume"]
    try:
        if path.suffix.lower() == ".zip":
            with ZipFile(path) as archive:
                members = [member for member in archive.namelist() if csv_name.fullmatch(Path(member).name)]
                if len(members) != 1:
                    raise DataError(f"{path.name}: expected one HistData {symbol} Generic ASCII M1 CSV")
                with archive.open(members[0]) as stream:
                    frame = pd.read_csv(stream, sep=";", header=None, dtype={0: "str"})
        elif csv_name.fullmatch(path.name):
            frame = pd.read_csv(path, sep=";", header=None, dtype={0: "str"})
        else:
            raise DataError(f"{path.name}: use the original HistData {symbol} Generic ASCII M1 ZIP or CSV")
        if frame.shape[1] != len(columns):
            raise DataError(f"{path.name}: expected {len(columns)} semicolon-separated columns")
        frame.columns = columns
        if not frame["timestamp"].str.fullmatch(r"\d{8} \d{6}", na=False).all():
            raise DataError(f"{path.name}: expected timestamps formatted as YYYYMMDD HHMMSS")
        parsed = pd.to_datetime(frame.pop("timestamp"), format="%Y%m%d %H%M%S")
        # HistData documents fixed EST (UTC-5), not America/New_York with DST.
        frame.index = pd.DatetimeIndex(parsed).tz_localize("Etc/GMT+5").tz_convert("UTC")
        if ((frame.index.second != 0) | (frame.index.microsecond != 0)).any():
            raise DataError(f"{path.name}: source bars are not on minute boundaries")
        for field in [*OHLC, "volume"]:
            frame[field] = pd.to_numeric(frame[field], errors="raise")
        validate_ohlc(frame)
        if frame.index.has_duplicates:
            # Some annual exports repeat identical records. Drop them only
            # inside one input and only when every field agrees.
            repeated = frame.loc[frame.index.duplicated(keep=False)]
            if repeated.reset_index().drop_duplicates().shape[0] != repeated.index.nunique():
                raise DataError(f"{path.name}: conflicting records share a timestamp")
            duplicate = frame.index.duplicated(keep="first")
            LOG.warning("%s: discarded %d identical repeated minutes", path.name, int(duplicate.sum()))
            frame = frame.loc[~duplicate]
        return frame
    except (BadZipFile, OSError, ValueError) as error:
        raise DataError(f"Could not read {path}: {error}") from error


def load_histdata(
    pair: str, symbol: str, paths: list[Path], window: CandleWindow
) -> pd.DataFrame:
    """Aggregate file exports in UTC and expose coverage instead of filling minutes."""
    if not paths:
        raise DataError("Supply one or more HistData ZIP/CSV files with --file")
    minute = pd.concat([_read_histdata(path, symbol) for path in paths]).sort_index()
    if minute.index.has_duplicates:
        raise DataError("Duplicate HistData minutes; do not mix overlapping annual and monthly archives")
    minute = minute.loc[(minute.index >= window.start) & (minute.index < window.end)]
    frequency = f"{int(window.duration / pd.Timedelta(minutes=1))}min"
    grouped = minute.resample(frequency, origin="epoch", label="left", closed="left")
    frame = grouped.agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    frame["source_bars"] = grouped.size()
    frame["expected_source_bars"] = int(window.duration / pd.Timedelta(minutes=1))
    frame = frame.loc[frame["source_bars"] > 0].copy()
    partial = frame["source_bars"] < frame["expected_source_bars"]
    if partial.any():
        LOG.warning("%d %s bars have fewer than their expected source minutes", int(partial.sum()), window.timeframe)
    if window.timeframe in ("M5", "M15", "H1"):
        # A minute gap can hide a level touch. Never pass these short bars off as complete.
        frame = frame.loc[~partial].copy()
    return closed_frame(frame, window, pair=pair, data_source=HISTDATA_SOURCE)
