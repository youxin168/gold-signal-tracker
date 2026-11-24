import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from signal_tracker import biquote
from signal_tracker.automation import _remember_h1, tick
from signal_tracker.candles import CandleWindow, DataError
from signal_tracker.checker import Execution, on_bar
from signal_tracker.config import CONFIG_DIR, load_strategies
from signal_tracker.signal import Outcome, Status, utc
from signal_tracker.strategy_engine import Decision
from test_checker import START, bar, sample
from test_phase2 import CALENDAR, frame


class BiquoteTests(unittest.TestCase):
    def test_ingestion_keeps_only_closed_in_range_candles(self):
        minute = timedelta(minutes=1)
        window = CandleWindow.create(utc(START - 2 * minute), utc(START), "M1")
        base = {"open": 2000, "low": 1999, "high": 2001, "close": 2000}
        data = {"symbol": "XAUUSD", "interval": "1m", "bars": [
            base | {"openTime": utc(START), "isOpen": True},
            base | {"openTime": utc(START - minute), "isOpen": False},
            base | {"openTime": utc(START - 3 * minute), "isOpen": False},
        ]}
        with patch("signal_tracker.biquote._get", return_value=data):
            bars = biquote.candles("XAUUSD", window)
            self.assertEqual(list(bars.index), [START - minute])
            self.assertEqual(list(bars["closed_at_utc"]), [START])
            self.assertEqual(bars.iloc[0].data_source, biquote.SOURCE)
        with patch("signal_tracker.biquote._get", return_value=data | {"symbol": "XAGUSD"}):
            with self.assertRaises(DataError):
                biquote.candles("XAUUSD", window)

    def test_fresh_spread_is_observed_and_malformed_quote_is_rejected(self):
        message = {"symbol": "XAUUSD", "timestamp": utc(START), "bid": "2000.05", "ask": "2000.31"}
        with patch("signal_tracker.biquote._get", return_value=message) as get:
            self.assertEqual(biquote.spread(), (Decimal("0.26"), START))
            get.assert_called_once_with("XAUUSD", allowStale="false")
        for wrong in ("NaN", "1999.00"):
            with patch("signal_tracker.biquote._get", return_value=message | {"ask": wrong}):
                with self.assertRaises(DataError):
                    biquote.spread()

    def test_calendar_requires_usable_coverage_and_explicit_time(self):
        template = {"countryCode": "US", "currency": "USD", "importance": "high", "timeMode": "exact"}
        past = template | {"time": utc(START - timedelta(days=2))}
        upcoming = template | {"time": utc(START + timedelta(hours=2))}
        with patch("signal_tracker.biquote._get", return_value=[past, upcoming]):
            result = biquote.calendar(START, lambda: START)
            self.assertEqual(result["verified_at_utc"], utc(START))
            self.assertEqual(len(result["events"]), 2)
        for rows in ([], [upcoming], [past, upcoming | {"timeMode": "tentative"}], [past, upcoming | {"currency": "CAD"}]):
            with patch("signal_tracker.biquote._get", return_value=rows):
                self.assertIsNone(biquote.calendar(START, lambda: START))

    def test_same_source_hourly_cache_prepends_older_closed_bars(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "h1.json"
            spans = [pd.date_range(end=START, periods=168, freq="h"), pd.date_range(end=START + timedelta(hours=32), periods=168, freq="h")]
            for stamps in spans:
                rows = pd.DataFrame(index=stamps, data={"closed_at_utc": stamps + pd.Timedelta(hours=1), "close": 2000})
                actual = _remember_h1(path, rows)
            self.assertEqual(len(actual), 200)
            self.assertTrue(actual.index.is_unique)

    def test_live_scanner_removes_intraday_warmup_at_150_and_selects_only_v3(self):
        now = START.replace(hour=7, minute=15)
        latest_hour = now.replace(minute=0)
        with TemporaryDirectory() as folder, \
                patch("signal_tracker.automation.now_utc", return_value=now), \
                patch("signal_tracker.automation.biquote.calendar", return_value=CALENDAR), \
                patch("signal_tracker.automation.biquote.spread", return_value=(Decimal("0.30"), pd.Timestamp(now))), \
                patch("signal_tracker.automation.decide", return_value=Decision("NONE", "No setup")) as decide:
            root = Path(folder)
            codes = ["CLD-INT-01-v3", "CLD-INT-02-v3"]
            hourly = frame([2000.0] * 150, 60, latest_hour).assign(data_source=biquote.SOURCE)
            m15 = frame([2001] * 30, 15, now).assign(data_source=biquote.SOURCE)
            for have in (149, 150):
                with patch("signal_tracker.automation._window",
                           side_effect=lambda _p, _s, _e, tf: hourly.tail(have) if tf == "H1" else m15):
                    status = tick(CONFIG_DIR, root / "signals.db", None, codes,
                                  feed=biquote.SOURCE, cache=root / "h1.json")
                self.assertEqual(status["state"], "ready")
                self.assertEqual(status["enabled_strategy_codes"], codes)
                self.assertEqual(status["strategy_warmup"], (
                    {code: {"have": 149, "need": 150} for code in codes} if have == 149 else {}))
                self.assertEqual(decide.call_count, 0 if have == 149 else 2)
            with self.assertRaisesRegex(ValueError, "frozen automated rules"):
                tick(CONFIG_DIR, root / "signals.db", None, ["CLD-INT-01-v2"], feed=biquote.SOURCE)

    def test_frozen_versions_use_different_execution_and_midpoint_sides(self):
        rows = {r["strategy_code"]: r for r in load_strategies()["strategies"]}
        bid = Execution.from_config(rows["CLD-INT-01-v1"]["execution"])
        mid = Execution.from_config(rows["CLD-INT-01-v2"]["execution"])
        entry_bar = bar(0, "1999.85", "1999.80", "2000")
        self.assertEqual(on_bar(sample(), Outcome(), entry_bar, bid).status, Status.PENDING)
        state = on_bar(sample(), Outcome(), entry_bar, mid)
        self.assertEqual(state.status, Status.ACTIVE)
        # Mid low alone is above the stop, but assumed bid is below it.
        self.assertEqual(on_bar(sample(), state, bar(1, "2001", "1998.10", "2004.50"), mid).status, Status.SL)
