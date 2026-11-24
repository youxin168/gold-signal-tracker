import json
import os
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from signal_tracker.automation import tick
from signal_tracker.config import CONFIG_DIR
from signal_tracker.public_snapshot import GOLD_AUDIT, atomic_json, make_snapshot
from signal_tracker.sources import OANDA_SOURCE, fetch_practice_spread
from signal_tracker.store import transaction
from signal_tracker.telegram import enqueue, flush_alerts
from signal_tracker.trend_pullback import CODE
from test_checker import START
from test_phase2 import CALENDAR, frame

PRACTICE = {"OANDA_API_TOKEN": "mock", "OANDA_PRACTICE_ACCOUNT_ID": "1-2-3-4"}
TELEGRAM = {"TELEGRAM_BOT_TOKEN": "123:mock-token", "TELEGRAM_CHAT_ID": "-567"}


class PhaseFiveTests(unittest.TestCase):
    def test_public_snapshot_includes_only_allowlisted_strategy_progress(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            status_path = root / "status.json"
            extra = {"have": 149, "need": 150, "private": ["do not export"]}
            atomic_json(status_path, {"state": "ready", "message": "Scanning", "updated_at_utc": START.isoformat(),
                                     "data_source": "BIQUOTE_XAUUSD_MID",
                                     "enabled_strategy_codes": ["CLD-SCA-01-v2", "CLD-INT-01-v2", "unregistered"],
                                     "strategy_warmup": {"CLD-INT-01-v3": extra, "CLD-INT-01-v2": extra, "unregistered": extra,
                                                         "CLD-INT-02-v3": {"have": 151, "need": 150}}})
            runner = make_snapshot(CONFIG_DIR, root / "signals.db", [], status_path)["runner"]
            self.assertEqual(runner["enabled_strategy_codes"], ["CLD-SCA-01-v2"])
            self.assertEqual(runner["strategy_warmup"], {"CLD-INT-01-v3": {"have": 149, "need": 150}})

    def test_public_snapshot_has_real_separate_empty_folds_and_no_secrets(self):
        with TemporaryDirectory() as folder:
            db = Path(folder) / "signals.db"
            snapshot = make_snapshot(CONFIG_DIR, db, [GOLD_AUDIT], None)
            self.assertFalse(db.exists())
            self.assertEqual([cohort["mode"] for cohort in snapshot["cohorts"]], ["LIVE", "REPLAY", "BACKTEST", "BACKTEST"])
            self.assertEqual([cohort["strategies"][0]["coverage"]["technical_candidates_before_filters"]
                              for cohort in snapshot["cohorts"][2:]], [500, 261])
            self.assertTrue(all(not cohort["signals"] for cohort in snapshot["cohorts"]))
            self.assertEqual(len(snapshot["strategies"]), 16)
            self.assertEqual(len([spec for spec in snapshot["strategies"] if spec["experimental"]]), 12)
            path = db.with_suffix(".json")
            atomic_json(path, snapshot, public=True)
            self.assertNotIn("TELEGRAM_CHAT_ID", path.read_text())

    def test_runner_refuses_missing_stale_or_future_calendar_without_fetching(self):
        with TemporaryDirectory() as folder, patch("signal_tracker.automation.now_utc", return_value=START), \
                patch("signal_tracker.automation.fetch_oanda") as fetch:
            db = Path(folder) / "signals.db"
            cal = Path(folder) / "news.json"
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(tick(CONFIG_DIR, db, None)["state"], "not_configured")
            with patch.dict(os.environ, PRACTICE, clear=True):
                self.assertEqual(tick(CONFIG_DIR, db, None)["state"], "waiting")
                for at in (START - timedelta(hours=25), START + timedelta(minutes=1)):
                    cal.write_text(json.dumps(CALENDAR | {"verified_at_utc": at.isoformat(), "source": "test"}))
                    self.assertIn("No recent reviewed news calendar", tick(CONFIG_DIR, db, cal)["message"])
            fetch.assert_not_called()
            self.assertFalse(db.exists())

    def test_prospective_tick_prepare_publish_and_advance_use_real_rules(self):
        with TemporaryDirectory() as folder, patch.dict(os.environ, PRACTICE, clear=True):
            db = Path(folder) / "signals.db"
            cal = Path(folder) / "news.json"
            cal.write_text(json.dumps(CALENDAR | {"verified_at_utc": (START - timedelta(hours=2)).isoformat(),
                                                  "source": "test calendar fixture"}))
            m15 = frame([2000 + 2 * (i % 2) for i in range(60)] + [2001, 1999, 2002], 15)
            h1 = frame([1800 + i for i in range(205)], 60)
            minutes = frame([2001, 1980], 1, ending=START + timedelta(minutes=2))
            data = {"M15": m15, "H1": h1, "M1": minutes}
            clock = [START - timedelta(minutes=15)]

            def fetch(_, __, window):
                return data[window.timeframe].loc[lambda rows: rows["closed_at_utc"] <= window.end].assign(
                    data_source=OANDA_SOURCE
                )

            with patch("signal_tracker.automation.now_utc", side_effect=lambda: clock[0]), \
                    patch("signal_tracker.automation.fetch_oanda", side_effect=fetch), \
                    patch("signal_tracker.automation.fetch_practice_spread",
                          side_effect=lambda *_: (Decimal("0.30"), pd.Timestamp(clock[0]))):
                self.assertIn("PREPARE", tick(CONFIG_DIR, db, cal, [CODE])["message"])
                with transaction(db) as db_conn:
                    self.assertEqual(db_conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0], 0)
                    prepare = db_conn.execute("SELECT message FROM telegram_events").fetchone()[0]
                    self.assertNotIn("TP1", prepare)
                clock[0] = START
                self.assertIn("Recorded one", tick(CONFIG_DIR, db, cal, [CODE])["message"])
                self.assertIn("Already recorded", tick(CONFIG_DIR, db, cal, [CODE])["message"])
                clock[0] = START + timedelta(minutes=2)
                self.assertIn("2 outcome checkpoints", tick(CONFIG_DIR, db, None, [CODE])["message"])
            with transaction(db) as db_conn:
                self.assertEqual([row[0] for row in db_conn.execute("SELECT status FROM outcomes")], ["SL"])
                self.assertEqual({r[0] for r in db_conn.execute("SELECT event FROM telegram_events")},
                                 {"PREPARE", "PENDING", "SL"})
            exported = make_snapshot(CONFIG_DIR, db, [GOLD_AUDIT], None)["cohorts"][0]
            self.assertEqual(exported["signals"][0]["status"], "SL")
            self.assertNotIn("notes", exported["signals"][0])
            trend = next(s for s in exported["strategies"] if s["strategy_code"] == "CLD-INT-01-v1")
            self.assertEqual(trend["breakdowns"]["market_regime"]["Trending"]["completed"], 1)

    def test_tick_scans_each_due_style_with_closed_inputs_and_one_quote(self):
        from signal_tracker.trend_pullback import Decision

        with TemporaryDirectory() as folder, patch.dict(os.environ, PRACTICE, clear=True):
            db, cal = Path(folder) / "signals.db", Path(folder) / "calendar.json"
            cal.write_text(json.dumps(CALENDAR | {"verified_at_utc": START.isoformat(), "source": "test"}))
            recent = frame([1800 + i for i in range(55)], 60).assign(data_source=OANDA_SOURCE)
            with patch("signal_tracker.automation.now_utc", return_value=START), \
                    patch("signal_tracker.automation.fetch_oanda", return_value=recent) as fetch, \
                    patch("signal_tracker.automation.fetch_practice_spread",
                          return_value=(Decimal("0.20"), pd.Timestamp(START))) as quote, \
                    patch("signal_tracker.automation.decide", return_value=Decision("NONE", "No setup")) as evaluate:
                self.assertEqual(tick(CONFIG_DIR, db, cal)["state"], "ready")
            self.assertEqual({call.args[2]["style"] for call in evaluate.call_args_list}, {"SCA", "INT", "SWG"})
            self.assertEqual({call.args[2].timeframe for call in fetch.call_args_list}, {"M5", "M15", "H1", "H4", "D1"})
            quote.assert_called_once()

    def test_telegram_filters_dedup_expiry_and_retry_after_failure(self):
        with TemporaryDirectory() as folder, patch.dict(os.environ, TELEGRAM, clear=True), \
                patch("signal_tracker.telegram.now_utc", return_value=START), \
                patch("signal_tracker.telegram.send_message") as sender:
            db = Path(folder) / "signals.db"
            with transaction(db) as conn:
                enqueue(conn, "one", "CLD", "INT", "PREPARE", "Forming", START)
                enqueue(conn, "one", "CLD", "INT", "PREPARE", "Forming", START)
                enqueue(conn, "filtered-source", "OWN", "INT", "PENDING", "Own", START)
                enqueue(conn, "filtered-style", "CLD", "SCA", "PENDING", "Scalp", START)
                enqueue(conn, "stale", "CLD", "INT", "PENDING", "Old", START - timedelta(minutes=30))
            sender.side_effect = ValueError("No acknowledgement")
            with self.assertRaises(ValueError):
                flush_alerts(db, CONFIG_DIR)
            sender.side_effect = None
            sender.reset_mock()
            flush_alerts(db, CONFIG_DIR)
            flush_alerts(db, CONFIG_DIR)
            sender.assert_called_once()
            self.assertIn("Forming", sender.call_args.args[-1])

    def test_timestamped_spread_uses_actual_ask_and_bid(self):
        quote = {"instrument": "XAU_USD", "tradeable": True, "time": START.isoformat(),
                 "bids": [{"price": "2700.20"}], "asks": [{"price": "2700.72"}]}
        with patch("signal_tracker.sources._practice_get", return_value={"prices": [quote]}):
            price, at = fetch_practice_spread("XAU_USD", "1-2-3-4", "mock")
            self.assertEqual(price, Decimal("0.52"))
            self.assertEqual(at, START)
            quote["tradeable"] = False
            with self.assertRaisesRegex(ValueError, "No valid tradeable"):
                fetch_practice_spread("XAU_USD", "1-2-3-4", "mock")
