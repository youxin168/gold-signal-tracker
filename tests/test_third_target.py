"""Third targets are prospective observations, not rewritten trade results."""

import unittest
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from signal_tracker import third_target
from signal_tracker.automation import _check_existing, tick
from signal_tracker.biquote import SOURCE
from signal_tracker.config import CONFIG_DIR
from signal_tracker.public_snapshot import make_snapshot
from signal_tracker.signal import Outcome, Status
from signal_tracker.store import from_record, publish, transaction
from signal_tracker.strategy_engine import Decision
from test_checker import MODEL, START, bar, sample
from test_phase2 import CALENDAR
from test_strategy_engine import CODE, candles


def context(minutes=60):
    out = candles([2000.0] * 7, minutes)
    out["high"] = [2003, 2020, 2003, 2008, 2004, 2006, 2003]
    return out


class ThirdTargetTests(unittest.TestCase):
    def test_nearest_closed_pivot_and_mirrored_sell(self):
        buy = sample()
        high = context()
        self.assertEqual(third_target.suggest(buy, high, "H1", D("0.01")), D("2005.99"))
        sell = replace(buy, direction="SELL", sl=D("2002"), tp1=D("1998"), tp2=D("1996"))
        low = high.assign(low=4000 - high["high"])
        self.assertEqual(third_target.suggest(sell, low, "H1", D("0.01")), D("1994.01"))

    def test_no_suggestion_if_plain_range_gap_too_close_or_future_confirmation(self):
        buy = sample()
        no_pivot = context().assign(high=2003)
        self.assertIsNone(third_target.suggest(buy, no_pivot, "H1", D("0.01")))
        barely = context().assign(high=[2003] * 5 + [2004.4, 2003])
        self.assertIsNone(third_target.suggest(buy, barely, "H1", D("0.01")))
        before_confirmation = replace(buy, setup_closed_at_utc=START - timedelta(hours=1))
        level = context().assign(high=[2003] * 5 + [2006, 2003])
        self.assertIsNone(third_target.suggest(before_confirmation, level, "H1", D("0.01")))
        self.assertIsNone(third_target.suggest(buy, level.iloc[:-3:-1], "H1", D("0.01")))
        self.assertIsNone(third_target.suggest(buy, level.drop(level.index[-3]), "H1", D("0.01")))

    def test_stop_wins_over_tp3_and_missing_minute_never_becomes_hit(self):
        plan = sample()
        bars = [bar(0, "1999.70", "1999.50", "2010"), bar(1, "2001", "2000", "2004.25"),
                bar(2, "2002", "1999.99", "2006")]
        lookup = {candle.opened: candle for candle in bars}
        just_filled, _ = third_target.advance_watch(plan, Outcome(), D("2005.99"), MODEL,
                                                   bars[0].closed, lookup.get)
        self.assertEqual(just_filled.status, Status.ACTIVE)
        stopped, _ = third_target.advance_watch(plan, just_filled, D("2005.99"), MODEL, bars[-1].closed, lookup.get)
        self.assertEqual(stopped.status, Status.BE)
        del lookup[bars[1].opened]
        unresolved, missing = third_target.advance_watch(plan, just_filled, D("2005.99"), MODEL, bars[-1].closed, lookup.get)
        self.assertEqual((unresolved, missing), (just_filled, bars[1].opened))

    def test_scanner_records_suggestion_without_retiring_history_or_rewriting_r(self):
        entry = candles([2000.0] * 15, 5)
        by_frame = {"M5": entry, "M15": context(15), "H1": context()}
        by_frame["H1"]["data_source"] = SOURCE
        quote = (D("0.30"), pd.Timestamp(START))
        calendar = CALENDAR | {"verified_at_utc": START.isoformat()}
        base = CODE["CLD-SCA-02-v2"]
        pilot = CODE["CLD-SCA-02-v3"]
        retired = replace(sample("LIVE"), signal_id="archived", data_source=SOURCE,
                          strategy_code=pilot["strategy_code"], style="SCA", tp3=D("2006"))
        levels = tuple(map(D, ("2000", "1998", "2002", "2004")))
        steps = pd.DataFrame({"open": [1999.85, 2001.0, 2004.0],
                              "low": [1999.4, 2000.5, 2003.8], "high": [2000, 2004.2, 2006.2]},
                             index=pd.date_range(START, periods=3, freq="min"))
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "signals.db"
            with patch("signal_tracker.automation.now_utc", return_value=START), \
                    patch("signal_tracker.automation.biquote.calendar", return_value=calendar), \
                    patch("signal_tracker.automation.biquote.spread", return_value=quote), \
                    patch("signal_tracker.automation._window", side_effect=lambda _p, _s, _e, tf: by_frame[tf]), \
                    patch("signal_tracker.automation.decide", return_value=Decision("SIGNAL", "fixture", "BUY", START, levels)):
                out = tick(CONFIG_DIR, db, None, [base["strategy_code"]], feed=SOURCE)
                self.assertIn("Recorded one", out["message"])
                with self.assertRaisesRegex(ValueError, "frozen automated rules"):
                    tick(CONFIG_DIR, db, None, [pilot["strategy_code"]], feed=SOURCE)
            with transaction(db) as conn:
                self.assertIsNone(from_record(conn.execute("SELECT * FROM signal_records").fetchone())[0].tp3)
                alert = conn.execute("SELECT message FROM telegram_events WHERE event = 'PENDING'").fetchone()[0]
                self.assertIn("TP3 2005.99", alert)
            with patch("signal_tracker.automation._window", return_value=steps.iloc[:2]) as window:
                _check_existing(db, "XAUUSD", "XAU_USD", START + timedelta(minutes=2), SOURCE)
                window.assert_called_once()

            def public():
                snapshot = make_snapshot(CONFIG_DIR, db, [], None)
                self.assertTrue(next(s for s in snapshot["strategies"] if s["strategy_code"] == pilot["strategy_code"])["retired_live"])
                return next(c for c in snapshot["cohorts"] if c["mode"] == "LIVE" and c["data_source"] == SOURCE)

            cohort = public()
            closed = cohort["signals"][0]
            self.assertEqual((closed["status"], closed["tp3"], closed["tp3_watch"]["state"]), ("TP2", "2005.99", "WATCHING"))
            self.assertEqual([leg["status"] for leg in closed["parallel_targets"]["legs"]], ["TP", "TP", "OPEN"])
            self.assertEqual(closed["parallel_targets"]["realized_r"], D("3"))
            original_r = closed["result_r"]
            with patch("signal_tracker.automation._window", return_value=steps):
                _check_existing(db, "XAUUSD", "XAU_USD", START + timedelta(minutes=3), SOURCE)
            with transaction(db) as conn:
                self.assertEqual(publish(conn, retired, pilot), "Published")
            after = public()
            archived = next(row for row in after["signals"] if row["signal_id"] == "archived")
            watched = next(row for row in after["signals"] if row["signal_id"] == closed["signal_id"])
            self.assertEqual(archived["tp3"], D("2006"))
            self.assertNotIn("tp3_watch", archived)
            self.assertNotIn("parallel_targets", archived)
            self.assertNotIn(pilot["strategy_code"], {s["strategy_code"] for s in after["strategies"]})
            self.assertEqual((watched["status"], watched["result_r"], watched["tp3_watch"]["state"]),
                             ("TP2", original_r, "HIT"))
            self.assertEqual([leg["status"] for leg in watched["parallel_targets"]["legs"]], ["TP", "TP", "TP"])
            self.assertEqual(watched["parallel_targets"]["realized_r"], D("5.995"))
