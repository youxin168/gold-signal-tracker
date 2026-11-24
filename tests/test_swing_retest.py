"""Closed-candle confirmation and the prospective scanner for the in-house Swing test."""
import unittest
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from signal_tracker.automation import tick
from signal_tracker.biquote import SOURCE
from signal_tracker.config import CONFIG_DIR
from signal_tracker.public_snapshot import make_snapshot
from signal_tracker.strategy_engine import decide, prepare
from signal_tracker.trend_pullback import SpreadQuote
from test_phase2 import CALENDAR, START
from test_strategy_engine import CODE, candles

SPEC = CODE["OWN-SWG-01-v1"]


def setup():
    # Prior high is 2003; break, touch and confirm on separate consecutive H1 bars.
    hourly = candles([2000.0] * 17 + [2008.0, 2005.0, 2009.0], 60)
    hourly.loc[hourly.index[-3:], ["open", "high", "low", "close"]] = [
        [2002.0, 2009.0, 2001.0, 2008.0],
        [2007.0, 2008.0, 2002.0, 2005.0],
        [2005.0, 2009.5, 2004.0, 2009.0],
    ]
    context = candles([1940.0 + i for i in range(65)], 240)
    return hourly, context


class SwingRetestTests(unittest.TestCase):
    def test_only_a_separate_closed_confirmation_can_publish(self):
        hourly, context = setup()
        rule = prepare(hourly, context, SPEC)
        self.assertNotEqual(rule.at(START - timedelta(hours=2), "UTC weekday").kind, "SIGNAL")
        self.assertEqual(rule.at(START - timedelta(hours=1), "UTC weekday").kind, "PREPARE")
        self.assertEqual(rule.at(START - timedelta(seconds=1), "UTC weekday").kind, "PREPARE")
        result = rule.at(START, "UTC weekday")
        self.assertEqual((result.kind, result.direction, result.setup_at), ("SIGNAL", "BUY", START))
        entry, stop, tp1, tp2 = result.levels
        self.assertLess(stop, D("2002"))  # beyond the first retest wick
        self.assertEqual((tp1 - entry, tp2 - entry), (2 * (entry - stop), 3 * (entry - stop)))
        future = pd.concat([hourly, candles([1000.0], 60, START + timedelta(hours=1))])
        future_context = pd.concat([context, candles([1000.0], 240, START + timedelta(hours=4))])
        self.assertEqual(prepare(future, future_context, SPEC).at(START, "UTC weekday"), result)

    def test_wick_only_breakout_close_back_inside_failed_confirmation_and_gaps(self):
        hourly, context = setup()
        for index, column, value in [
            (-3, "close", 2003),  # breakout touched the range but did not close outside
            (-2, "close", 2002.5),  # first retest closes inside the broken range
            (-1, "close", 2008),  # confirmation does not clear the retest wick
            (-1, "low", 2002.5),  # confirmation fails to hold the breakout level
        ]:
            changed = hourly.copy()
            changed.loc[changed.index[index], column] = value
            self.assertNotEqual(prepare(changed, context, SPEC).at(START, "UTC weekday").kind, "SIGNAL")
        for index in (-2, -4, -9):
            changed = hourly.drop(hourly.index[index])
            self.assertNotEqual(prepare(changed, context, SPEC).at(START, "UTC weekday").kind, "SIGNAL")
        self.assertNotEqual(prepare(hourly, context.iloc[:-1], SPEC).at(START, "UTC weekday").kind, "SIGNAL")

    def test_mirror_sell_confirmation_and_gates(self):
        hourly, context = setup()
        for frame in (hourly, context):
            old_high, old_low = frame["high"].copy(), frame["low"].copy()
            frame["high"], frame["low"] = 4000 - old_low, 4000 - old_high
            for name in ("open", "close"):
                frame[name] = 4000 - frame[name]
        quote = SpreadQuote(D("0.30"), START)
        sell = decide(hourly, context, SPEC, START, calendar=CALENDAR, quote=quote)
        self.assertEqual((sell.kind, sell.direction), ("SIGNAL", "SELL"))
        entry, stop, tp1, tp2 = sell.levels
        self.assertGreater(stop, D("1998"))
        self.assertEqual((entry - tp1, entry - tp2), (2 * (stop - entry), 3 * (stop - entry)))
        for missing_calendar, spread in [(None, quote), (CALENDAR, SpreadQuote(D("0.60"), START))]:
            self.assertEqual(decide(hourly, context, SPEC, START, calendar=missing_calendar, quote=spread).kind, "SKIP")

    def test_failed_confirmation_is_not_reused_next_hour(self):
        hourly, context = setup()
        hourly.loc[hourly.index[-1], "close"] = 2007.0
        later = candles([2009.0], 60, START + timedelta(hours=1))
        later.loc[later.index[-1], ["open", "high", "low"]] = [2007.0, 2010.0, 2006.0]
        prepared = prepare(pd.concat([hourly, later]), context, SPEC)
        self.assertNotEqual(prepared.at(START + timedelta(hours=1), "UTC weekday").kind, "SIGNAL")

    def test_prospective_tick_records_only_one_and_exports_the_in_house_badge(self):
        hourly, context = setup()
        hourly["data_source"] = SOURCE
        calendar = CALENDAR | {"verified_at_utc": START.isoformat()}
        clock = START + timedelta(seconds=2)
        with TemporaryDirectory() as folder:
            db = Path(folder) / "preview.db"
            with patch("signal_tracker.automation.now_utc", return_value=clock), \
                    patch("signal_tracker.automation._window", side_effect=lambda _p, _s, _e, tf: {"H1": hourly, "H4": context}[tf]), \
                    patch("signal_tracker.automation.biquote.calendar", return_value=calendar), \
                    patch("signal_tracker.automation.biquote.spread", return_value=(D("0.30"), pd.Timestamp(START))):
                status = tick(CONFIG_DIR, db, None, [SPEC["strategy_code"]], feed=SOURCE)
                self.assertIn("Recorded one new prospective signal", status["message"])
                self.assertIn("Already recorded", tick(CONFIG_DIR, db, None, [SPEC["strategy_code"]], feed=SOURCE)["message"])
            published = make_snapshot(CONFIG_DIR, db, [], None)
            badges = [spec for spec in published["strategies"] if spec.get("site_test")]
            self.assertEqual([spec["strategy_code"] for spec in badges], [SPEC["strategy_code"]])
            records = published["cohorts"][0]["signals"]
            self.assertEqual(len(records), 1)
            self.assertEqual((records[0]["source"], records[0]["style"], records[0]["status"]), ("OWN", "SWG", "PENDING"))
            self.assertEqual(records[0]["issued_at_utc"], clock)
