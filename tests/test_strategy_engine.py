import unittest
from datetime import timedelta
from decimal import Decimal as D

import pandas as pd

from signal_tracker.config import load_strategies
from signal_tracker.strategy_engine import decide, prepare
from signal_tracker.trend_pullback import SpreadQuote
from test_phase2 import CALENDAR, START

CODE = {spec["strategy_code"]: spec for spec in load_strategies()["strategies"]}


def candles(values, minutes, end=START):
    """Small synthetic, aligned price examples; not public strategy evidence."""
    ends = pd.date_range(end=end, periods=len(values), freq=f"{minutes}min")
    out = pd.DataFrame({"closed_at_utc": ends, "close": values}, index=ends - pd.Timedelta(minutes=minutes))
    out["open"] = out.close
    out["high"], out["low"] = out.close + 3, out.close - 3
    return out


class StrategyEngineTests(unittest.TestCase):
    def test_intraday_ema150_needs_150_closed_hourly_candles_not_200(self):
        pullback = candles([2000 + 2 * (i % 2) for i in range(60)] + [2001, 1999, 2002], 15)
        pullback.loc[pullback.index[-1], "open"] = 2001
        breakout_at = START.replace(hour=7, minute=15)
        breakout = candles([2000] * 29, 15, breakout_at)
        breakout.loc[breakout.index[-1], ["open", "close", "high"]] = [2000, 2009, 2011]
        for code, bars, at in (("CLD-INT-01", pullback, START), ("CLD-INT-02", breakout, breakout_at)):
            h1 = candles([1800 + i for i in range(150)], 60, at.replace(minute=0))
            with self.subTest(code=code):
                def scan(spec, trend):
                    return decide(bars, trend, spec, at, calendar=CALENDAR, quote=SpreadQuote(D("0.30"), at))

                self.assertEqual(scan(CODE[code + "-v2"], h1).kind, "SKIP")
                self.assertEqual(scan(CODE[code + "-v3"], h1.iloc[1:]).kind, "SKIP")
                result = scan(CODE[code + "-v3"], h1)
                self.assertEqual((result.kind, result.direction), ("SIGNAL", "BUY"))

    def test_micro_pullback_and_prepare_on_m5_without_future_context(self):
        spec = CODE["CLD-SCA-01-v1"]
        bars = candles([2000 + (i % 2) * 2 for i in range(60)] + [2001, 1999, 2002], 5)
        h = candles([1800 + i for i in range(60)], 15)
        bars.loc[bars.index[-1], "open"] = 2001
        evaluation = prepare(bars, h, spec)
        self.assertEqual(evaluation.at(START - timedelta(minutes=5), "London").kind, "PREPARE")
        buy = decide(bars, h, spec, START, calendar=CALENDAR, quote=SpreadQuote(D("0.30"), START))
        self.assertEqual((buy.kind, buy.direction), ("SIGNAL", "BUY"))
        self.assertEqual(buy.levels[2] - buy.levels[0], buy.levels[0] - buy.levels[1])
        for quote in (None, SpreadQuote(D("0.60"), START), SpreadQuote(D("0.30"), START + timedelta(seconds=1))):
            self.assertEqual(decide(bars, h, spec, START, calendar=CALENDAR, quote=quote).kind, "SKIP")
        appended = pd.concat((bars, candles([9999], 5, end=START + timedelta(minutes=5))))
        self.assertEqual(prepare(appended, h, spec).at(START, "London"), buy)
        self.assertEqual(prepare(bars.drop(bars.index[-2]), h, spec).at(START, "London").kind, "SKIP")

    def test_sweep_reclaim_stop_buffer_double_sweep_and_gap(self):
        spec = CODE["CLD-SCA-02-v1"]
        bars = candles([2000] * 21, 5)
        h = candles([1975], 15)
        bars.loc[bars.index[-1], ["low", "high"]] = [1990, 2002]
        buy = prepare(bars, h, spec).at(START, "New York")
        self.assertEqual((buy.kind, buy.direction, buy.levels[1]), ("SIGNAL", "BUY", D("1989.99")))
        older = pd.concat((bars, candles([1000], 5, end=START + timedelta(minutes=5))))
        self.assertEqual(prepare(older, h, spec).at(START, "New York"), buy)
        self.assertEqual(prepare(bars.drop(bars.index[3]), h, spec).at(START, "New York").kind, "SKIP")
        bars.loc[bars.index[-1], "high"] = 2004
        self.assertNotEqual(prepare(bars, h, spec).at(START, "New York").kind, "SIGNAL")

    def test_london_breakout_uses_completed_asian_range_and_prior_inside_close(self):
        spec = CODE["CLD-INT-02-v1"]
        at = START.replace(hour=7, minute=15)
        bars = candles([2000] * 29, 15, at)
        bars.loc[bars.index[-1], ["open", "close", "high"]] = [2000, 2009, 2011]
        h = candles([1800 + i for i in range(205)], 60, at.replace(minute=0))
        buy = decide(bars, h, spec, at, calendar=CALENDAR, quote=SpreadQuote(D("0.30"), at))
        self.assertEqual((buy.kind, buy.direction, buy.levels[0]), ("SIGNAL", "BUY", D("2009")))
        self.assertGreater(buy.levels[1], D("1997"))
        self.assertEqual(prepare(bars.drop(bars.index[3]), h, spec).at(at, "London").kind, "SKIP")
        self.assertEqual(prepare(bars, h, spec).at(at.replace(minute=0), "London").kind, "SKIP")
        self.assertEqual(decide(bars, h, spec, at.replace(hour=11), calendar=CALENDAR, quote=None).kind, "SKIP")

    def test_daily_pullback_targets_and_safe_context_join(self):
        spec = CODE["CLD-SWG-01-v1"]
        bars = candles([2000 + (i % 2) * 2 for i in range(60)] + [2001, 1999, 2002], 240)
        h = candles([1700 + i for i in range(220)], 1440, START.replace(hour=0))
        bars.loc[bars.index[-1], "open"] = 2001
        now = prepare(bars, h, spec).at(START, "UTC weekday")
        self.assertEqual((now.kind, now.direction), ("SIGNAL", "BUY"))
        entry, sl, tp1, tp2 = now.levels
        self.assertEqual((tp1 - entry, tp2 - entry), (2 * (entry - sl), 3 * (entry - sl)))
        future = pd.concat((h, candles([1], 1440, START.replace(hour=0) + timedelta(days=1))))
        self.assertEqual(prepare(bars, future, spec).at(START, "UTC weekday"), now)
        self.assertEqual(prepare(bars, h.iloc[:-1], spec).at(START, "UTC weekday").kind, "SKIP")

    def test_channel_threshold_excludes_the_breakout_candle(self):
        spec = CODE["CLD-SWG-02-v1"]
        bars = candles([2000] * 20 + [2005], 240)
        h = candles([1700 + i for i in range(220)], 1440, START.replace(hour=0))
        proposal = prepare(bars, h, spec).at(START, "UTC weekday")
        self.assertEqual((proposal.kind, proposal.direction), ("SIGNAL", "BUY"))
        bars.loc[bars.index[-1], "close"] = 2002
        self.assertEqual(prepare(bars, h, spec).at(START, "UTC weekday").kind, "PREPARE")
