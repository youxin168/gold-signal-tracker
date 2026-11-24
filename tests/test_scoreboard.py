import json
import unittest
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory

from signal_tracker.analyst import analyze
from signal_tracker.backtest import Fold
from signal_tracker.backtest_report import json_value, machine_report
from signal_tracker.scoreboard import Cohort, Regimes, _rank_key, build, session
from signal_tracker.scoreboard_inputs import from_backtests, from_database
from signal_tracker.scoreboard_stats import ScoredSignal, sample_badge, summarize, wilson_interval
from signal_tracker.signal import Outcome, Status
from signal_tracker.sources import HISTDATA_SOURCE, OANDA_SOURCE
from signal_tracker.store import publish, save_outcome, transaction
from test_checker import START, sample
from test_phase2 import SPEC, frame, main_from_args

DAY = timedelta(days=1)
MINUTE = timedelta(minutes=1)
BASE = SPEC["strategy_code"]


def spec(code):
    source, style, _, _ = code.split("-")
    return SPEC | {"strategy_code": code, "source": source, "style": style}


def row(key, value=None, *, at=START, status=None, code=BASE, mode="REPLAY", feed=HISTDATA_SOURCE):
    config = spec(code)
    signal = replace(sample(mode), signal_id=f"{code}-{key}", strategy_code=code,
                     source=config["source"], style=config["style"], issued_at_utc=at,
                     setup_closed_at_utc=at, recorded_at=at, expires_at_utc=at + 4 * MINUTE,
                     data_source=feed)
    result = D(value) if value is not None else None
    if status is None:
        status = (Status.PENDING if result is None else Status.TP2 if result > 0 else
                  Status.SL if result < 0 else Status.BE)
    filled = status not in (Status.PENDING, Status.EXPIRED)
    ended = at + 4 * MINUTE if status == Status.EXPIRED else at + 2 * MINUTE if result is not None else None
    return ScoredSignal(signal, Outcome(status, at + MINUTE if filled else None, None, ended, result))


def cohort(records, codes):
    return Cohort("REPLAY", "XAUUSD", HISTDATA_SOURCE, {code: spec(code) for code in codes}, records)


class StatsTests(unittest.TestCase):
    def test_fill_result_counts_expectancy_streak_and_drawdown(self):
        closed = [row(i, result, at=START + DAY * i) for i, result in enumerate(["2", "-1", "-2", "0", "2"])]
        rows = closed + [row("pending"), row("expiry", status=Status.EXPIRED),
                         row("partial", status=Status.TP1), row("active", status=Status.ACTIVE)]
        metrics = summarize(rows)
        self.assertEqual((metrics["signals"], metrics["filled"], metrics["expired"]), (9, 7, 1))
        self.assertEqual((metrics["entry_unresolved"], metrics["filled_open"], metrics["completed"]), (1, 2, 5))
        self.assertEqual((metrics["fill_rate"], metrics["win_rate"]), (D("0.875"), D("0.4")))
        self.assertEqual((metrics["wins"], metrics["losses"], metrics["flat"]), (2, 2, 1))
        self.assertEqual(metrics["expectancy_r"], D("0.2"))
        self.assertEqual(metrics["average_r"], metrics["expectancy_r"])
        self.assertEqual(metrics["profit_factor"], D(4) / 3)
        self.assertEqual(metrics["max_drawdown_r"], 3)
        self.assertEqual(metrics["longest_losing_streak"], 2)
        self.assertEqual([p["equity_r"] for p in metrics["equity_curve_r"]], [2, 1, -1, -1, 1])

    def test_empty_all_win_all_loss_and_same_timestamp(self):
        empty = summarize([])
        self.assertIsNone(empty["total_r"])
        self.assertIsNone(empty["fill_rate"])
        self.assertIsNone(empty["win_rate_ci_95"])
        self.assertEqual(summarize([row("win", "1")])["profit_factor_status"], "no_losses")
        self.assertEqual(summarize([row("loss", "-1")])["profit_factor"], 0)
        self.assertEqual(summarize([row("flat", "0")])["profit_factor_status"], "not_estimable")
        simultaneous = summarize([row("a", "2"), row("b", "-3")])
        self.assertEqual(len(simultaneous["equity_curve_r"]), 1)
        self.assertEqual(simultaneous["max_drawdown_r"], 1)
        self.assertIsNone(simultaneous["expectancy_r_ci_95"])

    def test_wilson_and_day_cluster_intervals_and_sample_boundaries(self):
        interval = wilson_interval(5, 10)
        self.assertAlmostEqual(interval[0], 0.236593, places=5)
        self.assertAlmostEqual(interval[1], 0.763407, places=5)
        result = summarize([row("loss", "-1"), row("win", "1", at=START + DAY)])
        self.assertEqual(result["completed_utc_days"], 2)
        self.assertAlmostEqual(result["expectancy_r_ci_95"][0], -12.706)
        self.assertAlmostEqual(result["expectancy_r_ci_95"][1], 12.706)
        self.assertEqual([sample_badge(n) for n in (29, 30, 99, 100)],
                         ["Too early", "Weak evidence", "Weak evidence", "Usable"])


class ScoreboardTests(unittest.TestCase):
    def test_ranking_uses_documented_tiebreaks_not_win_rate(self):
        metrics = {"total_r": D(20), "expectancy_r": D("0.20"), "max_drawdown_r": D(5),
                   "profit_factor": D(2), "profit_factor_status": "finite", "win_rate": D("0.45")}
        for change in ({"total_r": D(21)}, {"expectancy_r": D("0.21")},
                       {"max_drawdown_r": D(4)}, {"profit_factor": D("2.1")},
                       {"profit_factor": None, "profit_factor_status": "no_losses"}):
            self.assertLess(_rank_key(metrics | change), _rank_key(metrics))
        self.assertEqual(_rank_key(metrics), _rank_key(metrics | {"win_rate": D("0.99")}))

    def test_ranking_scoped_by_style_and_gated_by_sample_with_ties(self):
        codes = [BASE, "EXT1-INT-01-v1", "EXT2-INT-01-v1", "CLD-INT-02-v1", "OWN-SWG-01-v1"]
        sizes = [100, 100, 100, 99, 100]
        values = ["1", "1", "0.5", "100", "200"]
        rows = [row(i, value, at=START + DAY * i, code=code)
                for code, n, value in zip(codes, sizes, values) for i in range(n)]
        score = build(cohort(rows, codes))
        ranks = {card["strategy_code"]: card["rank"] for card in score["strategies"]}
        self.assertEqual(ranks, {BASE: 1, codes[1]: 1, codes[2]: 3, codes[3]: None, codes[4]: None})
        style = next(card for card in score["styles"] if card["style"] == "INT")
        self.assertEqual(style["metrics"]["completed"], 399)
        incompatible = spec(codes[1]) | {"execution": SPEC["execution"] | {"spread_price": "0.40"}}
        changed = replace(cohort(rows, codes), strategies=cohort(rows, codes).strategies | {codes[1]: incompatible})
        self.assertTrue(all(card["rank"] is None for card in build(changed)["strategies"]))

    def test_breakdowns_use_issue_time_dst_and_closed_adx(self):
        london = row("london", "1", at=START.replace(hour=7))
        new_york = row("new-york", "-1", at=START.replace(hour=17))
        asia = row("asia", "0", at=START.replace(hour=5))
        self.assertEqual([session(v) for v in (asia, london, new_york)], ["Asia", "London", "New York"])
        rising = frame([1800 + n for n in range(55)], 60)
        flat = frame([2000] * 55, 60)
        self.assertEqual(Regimes(rising).label(london), "Trending")
        self.assertEqual(Regimes(flat).label(london), "Ranging")
        self.assertEqual(Regimes(rising).label(row("stale", at=START + 2 * MINUTE * 60)), "Unknown")
        self.assertEqual(Regimes(rising).label(row("other-feed", feed=OANDA_SOURCE)), "Unknown")
        reverse = replace(new_york.signal, direction="SELL", sl=D("2002"), tp1=D("1998"), tp2=D("1996"))
        data = [replace(london, regime="Trending"), replace(new_york, signal=reverse, regime="Ranging"), asia]
        breakdowns = build(cohort(data, [BASE]))["strategies"][0]["breakdowns"]
        self.assertEqual(breakdowns["session"]["London"]["total_r"], 1)
        self.assertEqual(breakdowns["weekday_utc"]["Wednesday"]["completed"], 3)
        self.assertEqual(breakdowns["direction"]["SELL"]["losses"], 1)
        self.assertEqual(breakdowns["market_regime"]["Unknown"]["flat"], 1)

    def test_analyst_detects_concentration_and_withholds_sparse_sessions(self):
        london = [row(f"L{i}", "2" if i < 3 else "-0.25", at=START + DAY * (i + i // 5 * 2))
                  for i in range(10)]
        new_york = [row(f"N{i}", "-0.25", at=START.replace(hour=17) + DAY * (i + i // 5 * 2))
                    for i in range(10)]
        notes = analyze(london + new_york, summarize(london + new_york),
                        {"London": summarize(london), "New York": summarize(new_york)}, {"news_unknown": 1})
        self.assertEqual(notes["best_session"]["sessions"], ["London"])
        self.assertEqual(notes["worst_session"]["sessions"], ["New York"])
        self.assertTrue(any("top 3" in note for note in notes["warnings"]))
        self.assertTrue(any("Sample too small" in note for note in notes["warnings"]))
        self.assertTrue(any("evidence is missing" in note for note in notes["warnings"]))
        self.assertIsNone(analyze(london, summarize(london), {"London": summarize(london)}, None)["best_session"])

    def test_duplicate_or_mixed_records_fail(self):
        r = row("unique", "1")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            build(cohort([r, r], [BASE]))
        with self.assertRaisesRegex(ValueError, "incompatible"):
            build(cohort([replace(r, signal=replace(r.signal, mode="BACKTEST"))], [BASE]))
        with self.assertRaisesRegex(ValueError, "Invalid status"):
            ScoredSignal(r.signal, Outcome(Status.EXPIRED, result_r=D(9)))


class ScoreboardInputTests(unittest.TestCase):
    def test_scoreboard_reads_live_and_replay_without_pooling(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "signals.db"
            replay = row("replay", "1")
            live = row("live", "-1", mode="LIVE", feed=OANDA_SOURCE)
            with transaction(path) as conn:
                for scored in (replay, live):
                    self.assertEqual(publish(conn, scored.signal, SPEC), "Published")
                    save_outcome(conn, scored.signal.signal_id, scored.outcome)
            self.assertEqual(build(from_database(path, "LIVE", "XAUUSD", [SPEC], feed=None))
                             ["strategies"][0]["metrics"]["total_r"], -1)
            export = Path(directory) / "replay.json"
            result, stdout = main_from_args(["scoreboard", "--mode", "REPLAY", "--db", str(path),
                                            "--json-output", str(export)])
            self.assertEqual(result, 0)
            self.assertIn("REPLAY scoreboard", stdout)
            trend = next(card for card in json.loads(export.read_text())["strategies"]
                         if card["strategy_code"] == BASE)
            self.assertEqual(D(trend["metrics"]["total_r"]), 1)
            result, _ = main_from_args(["scoreboard", "--mode", "LIVE", "--fold", "out-of-sample"])
            self.assertEqual(result, 1)

    def test_backtest_requires_explicit_fold_comparable_inputs_and_disjoint_strategies(self):
        with TemporaryDirectory() as directory:
            in_start = START.replace(hour=0)
            one = Fold("In-sample", in_start, in_start + DAY)
            two = Fold("Out-of-sample", one.end, one.end + DAY)
            r = row("historical", "2", mode="BACKTEST")
            one.records = [(r.signal, r.outcome, None)]
            ids = {"M1 candles": f"m1.csv (SHA-256: {'a' * 64})", "H1 candles": f"h1.csv (SHA-256: {'b' * 64})",
                   "News snapshots": "Not supplied", "Bid/ask observations": "Not supplied"}
            path = Path(directory) / "a.json"
            report = machine_report((one, two), SPEC, HISTDATA_SOURCE, ids)
            path.write_text(json.dumps(report, default=json_value))
            self.assertEqual(len(from_backtests([path], "in-sample", "XAUUSD", "b" * 64).records), 1)
            self.assertFalse(from_backtests([path], "out-of-sample", "XAUUSD").records)
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                from_backtests([path], "in-sample", "XAUUSD", "a" * 64)
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                from_backtests([path, path], "in-sample", "XAUUSD")
            path_b = Path(directory) / "b.json"
            changed = machine_report(
                (replace(one, records=[]), two), spec("OWN-INT-01-v1"), HISTDATA_SOURCE,
                ids | {"M1 candles": f"different.csv (SHA-256: {'c' * 64})"},
            )
            path_b.write_text(json.dumps(changed, default=json_value))
            with self.assertRaisesRegex(ValueError, "same feed"):
                from_backtests([path, path_b], "in-sample", "XAUUSD")
