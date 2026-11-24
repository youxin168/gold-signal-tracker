import json
import unittest
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd

from signal_tracker.backtest import run
from signal_tracker.backtest_inputs import CalendarSnapshot, HistoricalCalendar, HistoricalQuotes
from signal_tracker.backtest_report import markdown
from signal_tracker.signal import Status
from signal_tracker.store import publish, transaction
from signal_tracker.trend_pullback import Decision, PreparedTrend, SpreadQuote
from test_checker import START, sample
from test_phase2 import SPEC, frame, main_from_args

ONE_DAY = timedelta(days=1)
START_DATE = START.replace(hour=0)
END_DATE = START_DATE + 2 * ONE_DAY
COMPLETE_CALENDAR = HistoricalCalendar(
    [CalendarSnapshot(START_DATE - ONE_DAY, START_DATE - ONE_DAY, END_DATE + ONE_DAY, ())]
)


class BacktestTests(unittest.TestCase):
    def setUp(self):
        closes = [2000 + 2 * (i % 2) for i in range(60)] + [2001, 1999, 2002]
        self.m15 = pd.concat([frame(closes, 15, START), frame(closes, 15, START + ONE_DAY)])
        self.h1 = frame([1800 + i for i in range(245)], 60, START + ONE_DAY)
        self.m1 = pd.concat([
            frame([2002, 1980], 1, START + timedelta(minutes=2)),
            frame([2002, 2050], 1, START + ONE_DAY + timedelta(minutes=2)),
        ])

    def test_measured_inputs_produce_separate_real_rule_results(self):
        quotes = HistoricalQuotes([
            SpreadQuote(D("0.30"), START), SpreadQuote(D("0.30"), START + ONE_DAY),
        ])
        one, two = run(self.m1, self.m15, self.h1, SPEC, START_DATE, END_DATE,
                       END_DATE, COMPLETE_CALENDAR, quotes)
        self.assertEqual(one.end, two.start)
        self.assertEqual([one.metrics()["closed"], two.metrics()["closed"]], [1, 1])
        self.assertEqual((one.records[0][1].status, two.records[0][1].status), (Status.SL, Status.TP2))
        self.assertEqual(one.records[0][0].mode, "BACKTEST")
        self.assertLess(one.metrics()["total_r_closed"], 0)
        self.assertGreater(two.metrics()["total_r_closed"], 0)

    def test_missing_evidence_has_no_outcomes_or_performance_in_either_fold(self):
        folds = run(self.m1, self.m15, self.h1, SPEC, START_DATE, END_DATE, END_DATE,
                    HistoricalCalendar([]), HistoricalQuotes([]))
        for fold in folds:
            self.assertGreater(fold.coverage["technical_candidates_before_filters"], 0)
            self.assertGreater(fold.coverage["news_unknown"], 0)
            self.assertGreater(fold.coverage["spread_unknown"], 0)
            self.assertEqual(fold.metrics()["signals"], 0)
            self.assertIsNone(fold.metrics()["win_rate_closed"])
        report = markdown(folds, SPEC, "feed", {})
        self.assertIn("Performance is not estimable", report)
        self.assertIn("Not estimable | Not estimable", report)

    def test_oldest_folds_cannot_see_future_snapshots_or_quotes(self):
        after = START + timedelta(seconds=1)
        quotes = HistoricalQuotes([SpreadQuote(D("0.30"), after)])
        news = HistoricalCalendar([CalendarSnapshot(after, START_DATE, END_DATE, ())])
        self.assertIsNone(quotes.as_of(START))
        self.assertEqual(news.status(START, SPEC["news_filter"]), "unknown")
        self.assertEqual(news.status(after, SPEC["news_filter"]), "ok")
        event_at = START + timedelta(minutes=30)
        news = HistoricalCalendar([CalendarSnapshot(START_DATE, START_DATE, END_DATE, (event_at,))])
        self.assertEqual(news.status(START, SPEC["news_filter"]), "blocked")

    def test_appending_future_price_bars_does_not_change_cached_decision(self):
        truncated_m15 = self.m15.loc[self.m15["closed_at_utc"] <= START]
        truncated_h1 = self.h1.loc[self.h1["closed_at_utc"] <= START]
        expected = PreparedTrend(truncated_m15, truncated_h1, SPEC).at(START, "London")
        self.assertEqual(expected.kind, "SIGNAL")
        self.assertEqual(PreparedTrend(self.m15, self.h1, SPEC).at(START, "London"), expected)

    def test_active_trade_at_fold_cutoff_cannot_see_later_stop(self):
        boundary = START_DATE + ONE_DAY
        at = boundary - timedelta(hours=3, minutes=15)
        previous = self.m15.loc[self.m15["closed_at_utc"] != at]
        m15 = pd.concat([previous, frame([2000], 15, at)]).sort_index()
        minute = frame([2000] * 195 + [1980], 1, boundary + timedelta(minutes=1))
        quote = HistoricalQuotes([SpreadQuote(D("0.30"), at)])
        decision = Decision("SIGNAL", "New York", "BUY", at, (D("2000"), D("1995"), D("2005"), D("2010")))
        with patch("signal_tracker.trend_pullback.PreparedTrend.at", return_value=decision):
            one, _ = run(minute, m15, self.h1, SPEC, START_DATE, END_DATE, END_DATE, COMPLETE_CALENDAR, quote)
        self.assertEqual(len(one.records), 1)
        _, state, reason = one.records[0]
        self.assertEqual((state.status, state.checked_until, reason), (Status.ACTIVE, boundary, "FOLD_CUTOFF"))

    def test_backtest_records_cannot_be_published_to_live_database(self):
        with TemporaryDirectory() as directory, transaction(Path(directory) / "signals.db") as db:
            with self.assertRaisesRegex(ValueError, "Backtests belong in separate"):
                publish(db, replace(sample(), mode="BACKTEST"), SPEC)

    def test_cli_loads_snapshots_quotes_and_reports_mode(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("m1", "m15", "h1"):
                getattr(self, name).to_csv(root / f"{name}.csv")
            quote = root / "quotes.csv"
            quote.write_text("observed_at_utc,pair,data_source,bid,ask\n"
                             "2024-07-03T12:00:00Z,XAUUSD,HISTDATA_ASCII_M1_BID,2000,2000.30\n")
            news = root / "calendar.json"
            news.write_text(json.dumps({
                "provenance": "Synthetic test fixture",
                "snapshots": [{"captured_at_utc": "2024-07-03T00:00:00Z", "events": [],
                               "coverage_start_utc": "2024-07-03T00:00:00Z",
                               "coverage_end_utc": "2024-07-05T00:00:00Z"}],
            }))
            args = ["backtest", "--m1", str(root / "m1.csv"), "--m15", str(root / "m15.csv"),
                    "--h1", str(root / "h1.csv"), "--calendar", str(news), "--quotes", str(quote),
                    "--start", START_DATE.isoformat(), "--end", END_DATE.isoformat(),
                    "--output", str(root / "report.md"), "--json-output", str(root / "report.json")]
            status, text = main_from_args(args)
            self.assertEqual(status, 0)
            self.assertIn("1 eligible signals, 1 completed", text)
            payload = json.loads((root / "report.json").read_text())
            self.assertEqual(payload["mode"], "BACKTEST")
            self.assertEqual(payload["folds"][0]["records"][0]["status"], "SL")
            self.assertIsNone(payload["folds"][1]["metrics"]["average_r_closed"])
            self.assertEqual(main_from_args(args)[0], 1)  # Existing report is never overwritten.
