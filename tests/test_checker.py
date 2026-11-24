import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from signal_tracker.checker import Bar, Execution, expire_if_due, first_full_minute, on_bar
from signal_tracker.signal import Outcome, Signal, Status

START = datetime(2024, 7, 3, 12, tzinfo=UTC)
MODEL = Execution(D("0.30"), D("0.05"), D("0.5"))


def sample(mode="REPLAY"):
    return Signal("one", "CLD-INT-01-v1", "CLD", "INT", "XAUUSD", "BUY",
                  D("2000"), D("1998"), D("2002"), D("2004"), START,
                  START + timedelta(minutes=4), "HISTDATA_ASCII_M1_BID", "", mode, START, START)


def bar(minute, opening, low, high):
    return Bar(START + timedelta(minutes=minute), D(opening), D(high), D(low))


class CheckerTests(unittest.TestCase):
    def setUp(self):
        self.signal = sample()
        self.filled = on_bar(self.signal, Outcome(), bar(0, "1999.70", "1999.50", "2002.10"), MODEL)

    def test_activation_uses_ask_for_buy_and_ignores_targets_on_its_bar(self):
        self.assertEqual(self.filled.status, Status.ACTIVE)
        self.assertEqual(self.filled.triggered_at, START + timedelta(minutes=1))
        missed = on_bar(self.signal, Outcome(), bar(0, "2000", "1999.90", "2001"), MODEL)
        self.assertEqual(missed.status, Status.PENDING)

    def test_stop_wins_even_if_tp2_also_touched(self):
        result = on_bar(self.signal, self.filled, bar(1, "2000", "1998", "2004"), MODEL)
        self.assertEqual((result.status, result.result_r), (Status.SL, D("-1.05")))
        same = on_bar(self.signal, Outcome(), bar(0, "1999.70", "1998", "2004"), MODEL)
        self.assertEqual(same.status, Status.SL)

    def test_tp1_then_breakeven_wins_over_tp2(self):
        first = on_bar(self.signal, self.filled, bar(1, "2000", "1999", "2002"), MODEL)
        self.assertEqual(first.status, Status.TP1)
        self.assertIsNone(first.result_r)
        end = on_bar(self.signal, first, bar(2, "2001", "2000", "2004"), MODEL)
        self.assertEqual((end.status, end.result_r), (Status.BE, D("0.45")))

    def test_both_targets_and_stop_gap(self):
        result = on_bar(self.signal, self.filled, bar(1, "2001", "2000", "2004"), MODEL)
        self.assertEqual((result.status, result.result_r), (Status.TP2, D("1.45")))
        self.assertEqual(result.tp1_at, result.closed_at)
        gap = on_bar(self.signal, self.filled, bar(1, "1997", "1996", "2000"), MODEL)
        self.assertEqual(gap.result_r, D("-1.55"))

    def test_short_exit_uses_ask_with_spread(self):
        short = replace(self.signal, direction="SELL", sl=D("2002"), tp1=D("1998"), tp2=D("1996"))
        state = on_bar(short, Outcome(), bar(0, "2000", "1999.9", "2000.2"), MODEL)
        result = on_bar(short, state, bar(1, "2001", "1999", "2001.70"), MODEL)
        self.assertEqual((result.status, result.result_r), (Status.SL, D("-1.05")))

    def test_expiry_needs_full_coverage_and_has_no_r_result(self):
        state = Outcome()
        for minute in range(4):
            state = on_bar(self.signal, state, bar(minute, "2001", "2000.5", "2002"), MODEL)
        expired = expire_if_due(self.signal, state, self.signal.expires_at_utc)
        self.assertEqual(expired.status, Status.EXPIRED)
        self.assertIsNone(expired.result_r)
        self.assertEqual(expire_if_due(self.signal, Outcome(), self.signal.expires_at_utc).status, Status.PENDING)
        self.assertEqual(expire_if_due(self.signal, self.filled, self.signal.expires_at_utc).status, Status.ACTIVE)
        with self.assertRaisesRegex(ValueError, "cannot skip a gap"):
            on_bar(self.signal, Outcome(), bar(1, "2001", "2000.5", "2002"), MODEL)

    def test_issue_minute_is_not_reused_for_a_partial_bar(self):
        later = replace(self.signal, issued_at_utc=START + timedelta(seconds=1),
                        recorded_at=START + timedelta(seconds=1))
        self.assertEqual(first_full_minute(later.issued_at_utc), START + timedelta(minutes=1))
        with self.assertRaisesRegex(ValueError, "Expected M1 bar"):
            on_bar(later, Outcome(), bar(0, "2000", "1999", "2001"), MODEL)
