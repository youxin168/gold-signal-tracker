import io
import json
import sqlite3
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from signal_tracker.cli import main
from signal_tracker.config import load_strategies
from signal_tracker.signal import Status
from signal_tracker.sources import HISTDATA_SOURCE, OANDA_SOURCE
from signal_tracker.store import freeze, from_record, open_records, publish, transaction
from signal_tracker.trend_pullback import CODE, SpreadQuote, evaluate
from test_checker import START, sample

SPEC = next(spec for spec in load_strategies()["strategies"] if spec["strategy_code"] == CODE)
CALENDAR = {"coverage_start_utc": "2024-07-03T00:00:00Z",
            "coverage_end_utc": "2024-07-04T00:00:00Z", "events": []}


def frame(closes, minutes, ending=START):
    ends = pd.date_range(end=ending, periods=len(closes), freq=f"{minutes}min")
    opens = ends - pd.Timedelta(minutes=minutes)
    result = pd.DataFrame({"close": closes, "closed_at_utc": ends}, index=opens)
    result["open"] = result["close"]
    result["high"] = result["close"] + 3
    result["low"] = result["close"] - 3
    result["pair"] = "XAUUSD"
    result["data_source"] = HISTDATA_SOURCE
    result["timeframe"] = {1: "M1", 15: "M15", 60: "H1"}[minutes]
    result.index.name = "opened_at_utc"
    return result


class RuleTests(unittest.TestCase):
    def setUp(self):
        self.m15 = frame([2000 + 2 * (i % 2) for i in range(60)] + [2001, 1999, 2002], 15)
        self.h1 = frame([1800 + i for i in range(205)], 60)
        self.quote = SpreadQuote(D("0.30"), START)

    def decide(self, at=START, calendar=CALENDAR, quote=None):
        return evaluate(self.m15, self.h1, SPEC, at, calendar=calendar,
                        quote=self.quote if quote is None else quote)

    def test_closed_buy_sell_and_targets(self):
        buy = self.decide()
        self.assertEqual((buy.kind, buy.direction, buy.setup_at), ("SIGNAL", "BUY", START))
        entry, sl, tp1, tp2 = buy.levels
        self.assertEqual((entry, tp1 - entry, tp2 - entry), (D("2002"), entry - sl, 2 * (entry - sl)))
        self.h1["close"] = 4000 - self.h1["close"]
        self.m15.loc[:, ["open", "close"]] = 4000 - self.m15[["open", "close"]]
        self.m15["high"], self.m15["low"] = 4000 - self.m15["low"], 4000 - self.m15["high"]
        sell = self.decide()
        self.assertEqual((sell.kind, sell.direction), ("SIGNAL", "SELL"))
        self.assertEqual(sell.levels, tuple(4000 - price for price in buy.levels))

    def test_prepare_has_no_levels_and_future_bars_do_not_affect_signals(self):
        pivot_at = START - timedelta(minutes=15)
        self.assertEqual(self.decide(pivot_at, quote=SpreadQuote(D("0.30"), pivot_at)).kind, "PREPARE")
        before = self.decide()
        self.h1 = pd.concat([self.h1, frame([10], 60, ending=START + timedelta(minutes=60))])
        self.m15 = pd.concat([self.m15, frame([10], 15, ending=START + timedelta(minutes=15))])
        self.assertEqual(self.decide(), before)

    def test_news_spread_session_and_recent_candle_gates(self):
        event = {"at_utc": "2024-07-03T12:30:00Z", "impact": "HIGH", "currency": "USD"}
        for calendar in (None, CALENDAR | {"events": [event]},
                         CALENDAR | {"coverage_end_utc": "2024-07-03T12:10:00Z"}):
            self.assertIn("news", self.decide(calendar=calendar).reason)
        for quote in (SpreadQuote(D("0.51"), START),
                      SpreadQuote(D("0.30"), START - timedelta(seconds=301)),
                      SpreadQuote(D("0.30"), START + timedelta(seconds=1))):
            self.assertIn("Spread", self.decide(quote=quote).reason)
        self.assertIn("session", self.decide(START - timedelta(hours=8)).reason)
        self.m15 = self.m15.drop(self.m15.index[-2])
        self.assertIn("missing candle", self.decide().reason)

    def test_real_indicators_and_cli_record_check_workflow(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "phase2.db"
            (root / "calendar.json").write_text(json.dumps(CALENDAR))
            self.m15.to_csv(root / "m15.csv")
            self.h1.to_csv(root / "h1.csv")
            m1 = frame([2002, 1990], 1, ending=START + timedelta(minutes=2))
            m1.to_csv(root / "m1.csv")
            scan = ["scan", "--db", str(db), "--m15", str(root / "m15.csv"), "--h1", str(root / "h1.csv"),
                    "--calendar", str(root / "calendar.json"), "--spread", "0.30", "--spread-at", START.isoformat()]
            run = lambda *args: main_from_args(list(args))
            self.assertEqual(run(*scan)[0], 1)  # Archive data cannot be recorded LIVE.
            self.assertIn("REPLAY PENDING", run(*scan, "--replay-as-of", START.isoformat())[1])
            self.assertIn("Already recorded", run(*scan, "--replay-as-of", START.isoformat())[1])
            self.assertEqual(run("signals", "--db", str(db))[1], "")
            check = ["check", "--db", str(db), "--m1", str(root / "m1.csv"), "--replay-as-of"]
            first = run(*check, (START + timedelta(minutes=1)).isoformat())[1]
            self.assertIn("REPLAY ACTIVE", first)
            second = run(*check, (START + timedelta(minutes=2)).isoformat())[1]
            self.assertIn("REPLAY SL", second)
            record = json.loads(run("signals", "--db", str(db), "--mode", "REPLAY")[1])
            self.assertEqual(record["status"], "SL")
            self.assertGreater(record["recorded_at"], record["issued_at_utc"])
            self.assertIn("no unresolved", run(*check, (START + timedelta(minutes=2)).isoformat())[1])

    def test_prospective_issue_and_missing_minute_checkpoint(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "phase2.db"
            (root / "calendar.json").write_text(json.dumps(CALENDAR))
            decision_at = START + timedelta(seconds=7)
            self.m15.assign(data_source=OANDA_SOURCE).to_csv(root / "m15.csv")
            self.h1.assign(data_source=OANDA_SOURCE).to_csv(root / "h1.csv")
            m1 = frame([2002, 2002, 1990], 1, ending=START + timedelta(minutes=3))
            m1 = m1.assign(data_source=OANDA_SOURCE)
            m1.drop(m1.index[1]).to_csv(root / "m1.csv")
            with patch("signal_tracker.phase2.now_utc", return_value=decision_at):
                status, message = main_from_args([
                    "scan", "--db", str(db), "--m15", str(root / "m15.csv"), "--h1", str(root / "h1.csv"),
                    "--calendar", str(root / "calendar.json"), "--spread", "0.30", "--spread-at", START.isoformat(),
                ])
            self.assertEqual(status, 0)
            self.assertIn("LIVE PENDING", message)
            check = ["check", "--db", str(db), "--m1", str(root / "m1.csv")]
            with patch("signal_tracker.phase2.now_utc", return_value=START + timedelta(minutes=3)):
                self.assertIn("LIVE PENDING", main_from_args(check)[1])
                m1.to_csv(root / "m1.csv")
                self.assertIn("LIVE SL", main_from_args(check)[1])
            record = json.loads(main_from_args(["signals", "--db", str(db)])[1])
            self.assertEqual(record["issued_at_utc"], decision_at.isoformat(timespec="microseconds"))
            self.assertEqual(record["recorded_at"], record["issued_at_utc"])
            self.assertEqual(record["triggered_at"], (START + timedelta(minutes=2)).isoformat(timespec="microseconds"))


def main_from_args(args):
    with patch("sys.argv", ["signal-tracker", *args]), redirect_stdout(io.StringIO()) as output:
        status = main()
    return status, output.getvalue()


class StoreTests(unittest.TestCase):
    def test_terms_frozen_duplicates_daily_cap_and_mode_separation(self):
        with TemporaryDirectory() as directory, transaction(Path(directory) / "test.db") as database:
            signal = sample()
            self.assertEqual(publish(database, signal, SPEC), "Published")
            self.assertIn("Already recorded", publish(database, replace(signal, signal_id="duplicate"), SPEC))

            def later(hours, mode="REPLAY"):
                delta = timedelta(hours=hours)
                return replace(signal, signal_id=f"{mode}-{hours}", mode=mode,
                               issued_at_utc=START + delta, expires_at_utc=signal.expires_at_utc + delta,
                               recorded_at=START + delta, setup_closed_at_utc=START + delta)

            self.assertEqual(publish(database, later(1), SPEC), "Published")
            self.assertIn("Daily UTC", publish(database, later(2), SPEC))
            self.assertEqual(publish(database, later(12), SPEC), "Published")
            self.assertEqual(publish(database, later(1, "LIVE"), SPEC), "Published")
            self.assertEqual(len(open_records(database, "LIVE", START + timedelta(days=1))), 1)
            self.assertEqual(from_record(open_records(database, "REPLAY", START)[0])[1].status, Status.PENDING)
            with self.assertRaisesRegex(ValueError, "create a new version"):
                freeze(database, SPEC | {"expiry_minutes": 10})
            with self.assertRaises(sqlite3.IntegrityError):
                database.execute("UPDATE signals SET entry = '1234'")
            with self.assertRaises(sqlite3.IntegrityError):
                database.execute("DELETE FROM signals")
            with self.assertRaisesRegex(ValueError, "never backdated"):
                replace(later(1, "LIVE"), recorded_at=START + timedelta(hours=2))
