import json
import shutil
import unittest
from dataclasses import replace
from datetime import UTC, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from signal_tracker.config import CONFIG_DIR, load_strategies
from signal_tracker.external import import_csv, register
from signal_tracker.head_to_head import compare
from signal_tracker.scoreboard import build
from signal_tracker.sources import HISTDATA_SOURCE, OANDA_SOURCE
from signal_tracker.store import from_record, transaction
from test_checker import START
from test_phase2 import frame, main_from_args
from test_scoreboard import BASE, cohort, row

HEADER = "external_id,strategy_code,direction,entry,sl,tp1,tp2,issued_at_utc\n"
MANUAL = "EXT1-INT-01-v1"


class ExternalTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.config = self.root / "config"
        shutil.copytree(CONFIG_DIR, self.config)
        self.csv, self.db = self.root / "import.csv", self.root / "signals.db"

    def test_register_manual_and_finite_rule_overrides_without_editing_frozen_terms(self):
        before = load_strategies(self.config)["strategies"]
        code = register(self.config, self.config / "external-rules.example.json")
        after = load_strategies(self.config)["strategies"]
        self.assertEqual(after[:-1], before)
        spec = after[-1]
        self.assertEqual((code, spec["implementation"], spec["stop"]["atr_multiple"]),
                         ("OWN-INT-01-v1", "trend_pullback_v1", 1.8))
        self.assertEqual(spec["news_filter"], before[2]["news_filter"])
        with self.assertRaisesRegex(ValueError, "exists"):
            register(self.config, self.config / "external-rules.example.json")
        bad = (json.loads((self.config / "external-rules.example.json").read_text()) |
               {"strategy_code": "EXT2-INT-01-v1", "parameters": {"python": "unknown"}})
        candidate = self.root / "candidate.json"
        candidate.write_text(json.dumps(bad))
        with self.assertRaisesRegex(ValueError, "not supported"):
            register(self.config, candidate)
        self.assertEqual(register(self.config, self.config / "external-manual.example.json"), MANUAL)

    def test_live_requires_attestation_and_never_accepts_a_supplied_timestamp(self):
        register(self.config, self.config / "external-manual.example.json")
        line = f"sample,{MANUAL},BUY,2000,1998,2002,2004,"
        self.csv.write_text(HEADER + line + START.isoformat() + "\n")
        with self.assertRaisesRegex(ValueError, "Backdating"):
            import_csv(self.config, self.db, self.csv, "LIVE", OANDA_SOURCE, True)
        self.csv.write_text(HEADER + line + "\n")
        with self.assertRaisesRegex(ValueError, "confirm-new"):
            import_csv(self.config, self.db, self.csv, "LIVE", OANDA_SOURCE, False)
        with patch("signal_tracker.external.now_utc", return_value=START):
            self.assertEqual(import_csv(self.config, self.db, self.csv, "LIVE", OANDA_SOURCE, True), (1, 0))
        with patch("signal_tracker.external.now_utc", return_value=START + timedelta(minutes=2)):
            self.assertEqual(import_csv(self.config, self.db, self.csv, "LIVE", OANDA_SOURCE, True), (0, 1))
        with transaction(self.db) as conn:
            signal, outcome = from_record(conn.execute("SELECT * FROM signal_records").fetchone())
            self.assertEqual(signal.issued_at_utc, signal.recorded_at)
            self.assertEqual(signal.issued_at_utc, START)
            self.assertEqual((signal.mode, outcome.status), ("LIVE", "PENDING"))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM telegram_events").fetchone()[0], 1)
        self.csv.write_text(HEADER + line.replace("2000", "1999") + "\n")
        with self.assertRaisesRegex(ValueError, "immutable terms"):
            import_csv(self.config, self.db, self.csv, "LIVE", OANDA_SOURCE, True)

    def test_replay_uses_shared_checker_and_batch_rolls_back_on_bad_levels(self):
        register(self.config, self.config / "external-manual.example.json")
        first = f"s1,{MANUAL},BUY,2000,1998,2002,2004,{START.isoformat()}\n"
        bad = f"s2,{MANUAL},BUY,2000,2001,2002,2004,{(START + timedelta(minutes=1)).isoformat()}\n"
        self.csv.write_text(HEADER + first + bad)
        with self.assertRaisesRegex(ValueError, "strictly ordered"):
            import_csv(self.config, self.db, self.csv, "REPLAY", HISTDATA_SOURCE, False)
        self.csv.write_text(HEADER + first)
        self.assertEqual(import_csv(self.config, self.db, self.csv, "REPLAY", HISTDATA_SOURCE, False), (1, 0))
        self.csv.write_text(HEADER + f"s1,{MANUAL},BUY,2000,1998,2002,2004,\n")
        with self.assertRaisesRegex(ValueError, "already recorded as historical"):
            import_csv(self.config, self.db, self.csv, "LIVE", OANDA_SOURCE, True)
        path = self.root / "m1.csv"
        frame([1999, 1980], 1, ending=START + timedelta(minutes=2)).to_csv(path)
        result, output = main_from_args(["--config-dir", str(self.config), "check", "--m1", str(path),
                                         "--db", str(self.db), "--replay-as-of", (START + timedelta(minutes=2)).isoformat()])
        self.assertEqual(result, 0)
        self.assertIn("REPLAY SL", output)
        with transaction(self.db) as conn:
            self.assertEqual(conn.execute("SELECT DISTINCT mode FROM signals").fetchone()[0], "REPLAY")
            self.assertIsNone(conn.execute("SELECT 1 FROM sqlite_master WHERE name='telegram_events'").fetchone())

    def test_comparison_gates_styles_modes_evidence_and_completed_samples(self):
        ext = "OWN-INT-01-v1"
        other = "EXT2-SWG-01-v1"
        left = [row(i, "1", at=START + timedelta(days=i), code=BASE) for i in range(100)]
        right = [row(i, "0.6", at=START + timedelta(days=i), code=ext) for i in range(100)]
        scoped = cohort(left + right, [BASE, ext, other])
        enough, = compare(scoped)
        self.assertEqual(enough["leader"], BASE)
        self.assertEqual(enough["external_metrics"]["completed"], 100)
        self.assertEqual(enough["start_utc"], START.replace(hour=0, tzinfo=UTC).isoformat(timespec="microseconds"))
        thin, = compare(replace(scoped, records=left + right[1:]))
        self.assertIsNone(thin["leader"])
        self.assertEqual(thin["claude_metrics"]["completed"], 99)
        manual_scope = replace(scoped, strategies=scoped.strategies |
                               {ext: scoped.strategies[ext] | {"implementation": "manual_v1"}})
        manual, = compare(manual_scope)
        self.assertIsNone(manual["leader"])
        self.assertIn("Descriptive only", manual["explanation"])
        self.assertTrue(all(card["rank"] is None for card in build(manual_scope)["strategies"]))
        no_shared, = compare(replace(scoped, records=left + [row("late", "1", at=START + timedelta(days=500), code=ext)]))
        self.assertIsNone(no_shared["claude_metrics"])
