import unittest
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory

from signal_tracker.parallel_targets import TargetPlan, advance_plan, create, public_plans, save
from signal_tracker.store import publish, transaction
from test_checker import MODEL, START, bar, sample
from test_strategy_engine import CODE


class ParallelTargetsTests(unittest.TestCase):
    def test_three_orders_retain_original_stop_after_two_targets(self):
        signal = replace(sample("LIVE"), entry=D("3616.02"), sl=D("3609.99"), tp1=D("3622.05"), tp2=D("3625.07"))
        plan = TargetPlan((signal.tp1, signal.tp2, D("3626.94")), ("OPEN",) * 3)
        candles = [bar(0, "3615.5", "3614", "3630"), bar(1, "3620", "3612", "3625.07"),
                   bar(2, "3610", "3609.99", "3627")]
        lookup = {candle.opened: candle for candle in candles}
        filled, _ = advance_plan(signal, plan, MODEL, candles[0].closed, lookup.get)
        self.assertEqual(filled.statuses, ("OPEN",) * 3)
        partial, _ = advance_plan(signal, filled, MODEL, candles[1].closed, lookup.get)
        self.assertEqual(partial.statuses, ("TP", "TP", "OPEN"))
        complete, _ = advance_plan(signal, partial, MODEL, candles[2].closed, lookup.get)
        self.assertEqual(complete.statuses, ("TP", "TP", "SL"))
        with TemporaryDirectory() as tmp, transaction(Path(tmp) / "signals.db") as conn:
            publish(conn, signal, CODE[signal.strategy_code])
            create(conn, signal, plan.targets[-1])
            save(conn, signal.signal_id, complete, None)
            result = public_plans(conn)[signal.signal_id]
        self.assertEqual(round(result["realized_r"], 2), D("1.50"))
        self.assertEqual(round(result["per_total_risk_r"], 2), D("0.50"))

    def test_sell_two_targets_and_missing_minute(self):
        signal = replace(sample(), direction="SELL", sl=D("2002"), tp1=D("1998"), tp2=D("1996"))
        plan = TargetPlan((signal.tp1, signal.tp2), ("OPEN",) * 2)
        candles = [bar(0, "2000", "1999.50", "2001"), bar(2, "1999", "1995.60", "2001")]
        lookup = {candle.opened: candle for candle in candles}
        unresolved, missing = advance_plan(signal, plan, MODEL, candles[-1].closed, lookup.get)
        self.assertEqual((unresolved.statuses, missing), (("OPEN", "OPEN"), START + timedelta(minutes=1)))
        middle = bar(1, "1999", "1998.5", "2001")
        lookup[middle.opened] = middle
        closed, gap = advance_plan(signal, unresolved, MODEL, candles[-1].closed, lookup.get)
        self.assertEqual((closed.statuses, closed.phase, gap), (("TP", "TP"), "CLOSED", None))

    def test_unfilled_orders_expire_with_no_r(self):
        signal = sample()
        plan = TargetPlan((signal.tp1, signal.tp2), ("OPEN",) * 2)
        candles = [bar(index, "2001", "2000.9", "2002") for index in range(4)]
        lookup = {candle.opened: candle for candle in candles}
        expired, gap = advance_plan(signal, plan, MODEL, signal.expires_at_utc, lookup.get)
        self.assertEqual((expired.phase, expired.statuses, gap), ("EXPIRED", ("EXPIRED", "EXPIRED"), None))

    def test_tp3_can_hit_after_price_returns_to_entry_without_hitting_original_sl(self):
        signal = sample()
        plan = TargetPlan((signal.tp1, signal.tp2, D("2006")), ("OPEN",) * 3)
        candles = [bar(0, "1999.70", "1999.50", "2000"), bar(1, "2001", "2000.50", "2004"),
                   bar(2, "2001", "1999.50", "2006")]
        lookup = {candle.opened: candle for candle in candles}
        result, gap = advance_plan(signal, plan, MODEL, candles[-1].closed, lookup.get)
        self.assertEqual((result.phase, result.statuses, gap), ("CLOSED", ("TP", "TP", "TP"), None))
