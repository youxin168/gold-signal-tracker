"""Three-target execution, backward-compatible storage, and public evidence."""
import sqlite3
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory

from signal_tracker.checker import Execution, advance, on_bar
from signal_tracker.config import CONFIG_DIR, load_strategies
from signal_tracker.phase2 import signal_for
from signal_tracker.public_snapshot import make_snapshot
from signal_tracker.signal import Outcome, Status
from signal_tracker.store import SCHEMA, from_record, open_records, publish, save_outcome, transaction
from signal_tracker.trend_pullback import Decision
from test_checker import START, bar, sample


SPECS = {spec["strategy_code"]: spec for spec in load_strategies()["strategies"]}
FEED = "BIQUOTE_XAUUSD_MID"
PILOT = SPECS["CLD-SCA-02-v3"]
MID = Execution.from_config(PILOT["execution"])


class Tp3Tests(unittest.TestCase):
    def test_long_hits_tp2_then_tp3_with_partial_size_and_costs(self):
        sig = replace(sample(), tp3=D("2006"))
        filled = on_bar(sig, Outcome(), bar(0, "1999.85", "1999.50", "2006.50"), MID)
        self.assertEqual(filled.status, Status.ACTIVE)  # no target credited on the entry bar
        second = on_bar(sig, filled, bar(1, "2001", "2000.45", "2004.20"), MID)
        self.assertEqual(second.status, Status.TP2_OPEN)
        self.assertIsNone(second.result_r)
        self.assertEqual(second.tp1_at, second.tp2_at)
        done = on_bar(sig, second, bar(2, "2002", "2000.50", "2006.15"), MID)
        self.assertEqual((done.status, done.result_r), (Status.TP3, D("1.70")))
        self.assertEqual(done.tp2_at, second.tp2_at)
        same, missing = advance(sig, second, MID, START + timedelta(minutes=4), lambda _: None)
        self.assertEqual((same, missing), (second, START + timedelta(minutes=2)))

    def test_breakeven_wins_over_same_bar_tp3_and_retains_tp2(self):
        sig = replace(sample(), tp3=D("2006"))
        filled = on_bar(sig, Outcome(), bar(0, "1999.85", "1999.50", "2001"), MID)
        second = on_bar(sig, filled, bar(1, "2001", "2000.45", "2004.20"), MID)
        stopped = on_bar(sig, second, bar(2, "2001", "2000.15", "2006.50"), MID)
        self.assertEqual((stopped.status, stopped.result_r), (Status.BE, D("0.95")))
        self.assertEqual(stopped.tp2_at, second.tp2_at)

    def test_short_targets_use_executable_ask(self):
        sig = replace(sample(), direction="SELL", sl=D("2002"), tp1=D("1998"), tp2=D("1996"), tp3=D("1994"))
        filled = on_bar(sig, Outcome(), bar(0, "2000.15", "1999.9", "2000.30"), MID)
        second = on_bar(sig, filled, bar(1, "1998", "1994", "1999.80"), MID)
        self.assertEqual(second.status, Status.TP2_OPEN)
        result = on_bar(sig, second, bar(2, "1996", "1993.85", "1997"), MID)
        self.assertEqual((result.status, result.result_r), (Status.TP3, D("1.70")))

    def test_upgrade_preserves_original_record_and_exports_new_open_and_closed_targets(self):
        parent = SPECS["CLD-SCA-02-v2"]
        setup = Decision("SIGNAL", "London", "BUY", START, tuple(map(D, ("2000", "1998", "2002", "2004"))))
        original = signal_for(setup, parent, FEED, "LIVE", START, START)
        previous_result = Outcome(Status.TP2, START, START, START, D("1.45"), START)
        with TemporaryDirectory() as folder:
            db = Path(folder) / "old.db"
            with transaction(db) as con:
                publish(con, original, parent)
                save_outcome(con, original.signal_id, previous_result)
            with closing(sqlite3.connect(db)) as con, con:
                # Put the stored rows in the pre-TP3 schema shape.
                con.execute("DROP VIEW signal_records")
                con.execute("ALTER TABLE signals DROP COLUMN tp3")
                con.execute("ALTER TABLE outcomes RENAME TO new_outcomes")
                con.execute("""CREATE TABLE outcomes (
                    signal_id TEXT PRIMARY KEY REFERENCES signals(signal_id),
                    status TEXT NOT NULL CHECK (status IN ('PENDING','ACTIVE','TP1','TP2','SL','BE','EXPIRED')),
                    triggered_at TEXT, tp1_at TEXT, closed_at TEXT, result_r TEXT, checked_until TEXT)""")
                con.execute("INSERT INTO outcomes SELECT signal_id,status,triggered_at,tp1_at,closed_at,result_r,checked_until FROM new_outcomes")
                con.execute("DROP TABLE new_outcomes")
                con.execute("""CREATE VIEW signal_records AS
                    SELECT signals.*, status, triggered_at, tp1_at, closed_at, result_r, checked_until
                    FROM signals JOIN outcomes USING (signal_id)""")
            old_snapshot = make_snapshot(CONFIG_DIR, db, [], None)
            self.assertIsNone(old_snapshot["cohorts"][0]["signals"][0]["tp3"])
            signal = signal_for(replace(setup, levels=(*setup.levels, D("2006"))), PILOT, FEED, "LIVE", START, START)
            with transaction(db) as con:
                self.assertEqual(from_record(con.execute("SELECT * FROM signal_records").fetchone()), (original, previous_result))
                self.assertEqual(publish(con, signal, PILOT), "Published")
                second = Outcome(Status.TP2_OPEN, START, START, checked_until=START, tp2_at=START)
                save_outcome(con, signal.signal_id, second)
                self.assertEqual(len(open_records(con, "LIVE", START)), 1)
                with self.assertRaisesRegex(sqlite3.IntegrityError, "cannot be changed"):
                    con.execute("UPDATE signals SET tp3 = '2007' WHERE signal_id = ?", (signal.signal_id,))
            snapshot = make_snapshot(CONFIG_DIR, db, [], None)
            new = next(row for row in snapshot["cohorts"][0]["signals"] if row["signal_id"] == signal.signal_id)
            self.assertEqual((new["tp3"], new["status"], new["result_r"]), (D("2006"), Status.TP2_OPEN, None))
            with transaction(db) as con:
                final = replace(second, status=Status.TP3, closed_at=START, result_r=D("1.70"))
                save_outcome(con, signal.signal_id, final)
                self.assertFalse(open_records(con, "LIVE", START))
            snapshot = make_snapshot(CONFIG_DIR, db, [], None)
            new = next(row for row in snapshot["cohorts"][0]["signals"] if row["signal_id"] == signal.signal_id)
            self.assertEqual((new["status"], new["result_r"]), (Status.TP3, D("1.70")))
