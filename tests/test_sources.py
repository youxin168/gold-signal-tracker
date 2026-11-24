import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

import pandas as pd

from signal_tracker.candles import CandleWindow, DataError
from signal_tracker.config import load_strategies, market_for
from signal_tracker.sources import fetch_oanda, load_histdata


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.window = CandleWindow.create("2024-07-03T00:00:00Z", "2024-07-03T00:10:00Z", "M5")

    def test_histdata_uses_fixed_est_and_drops_gap_buckets(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "histdata.zip"
            # 19:00 fixed EST => 00:00 UTC even in July. Missing 19:07.
            minutes = [0, 1, 2, 3, 4, 5, 6, 8, 9, 10]
            text = "\n".join(f"20240702 19{m:02}00;2000;{2001+m};1999;2001;0" for m in minutes)
            with ZipFile(path, "w") as archive:
                archive.writestr("DAT_ASCII_XAUUSD_M1_202407.csv", text)
            result = load_histdata("XAUUSD", "XAUUSD", [path], self.window)
        self.assertEqual(result.index.tolist(), [pd.Timestamp("2024-07-03T00:00:00Z")])
        self.assertEqual(result.iloc[0]["closed_at_utc"], pd.Timestamp("2024-07-03T00:05:00Z"))
        self.assertEqual(result.iloc[0]["source_bars"], 5)
        self.assertEqual(result.iloc[0]["high"], 2005)

    def test_histdata_rejects_overlapping_archives(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "DAT_ASCII_XAUUSD_M1_202407.csv"
            path.write_text("20240702 190000;2000;2001;1999;2000;0\n")
            with self.assertRaisesRegex(DataError, "Duplicate"):
                load_histdata("XAUUSD", "XAUUSD", [path, path], self.window)

    def test_histdata_removes_exact_duplicates_but_rejects_conflicting_prices(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "DAT_ASCII_XAUUSD_M1_202407.csv"
            row = "20240702 190000;2000;2001;1999;2000;0\n"
            minute = CandleWindow.create("2024-07-03T00:00:00Z", "2024-07-03T00:01:00Z", "M1")
            path.write_text(row * 2)
            self.assertEqual(len(load_histdata("XAUUSD", "XAUUSD", [path], minute)), 1)
            path.write_text(row + row.replace(";1999;", ";1998;"))
            with self.assertRaisesRegex(DataError, "conflicting"):
                load_histdata("XAUUSD", "XAUUSD", [path], minute)

    def test_window_rejects_naive_and_misaligned_times(self):
        with self.assertRaisesRegex(DataError, "timezone"):
            CandleWindow.create("2024-07-03T00:00:00", "2024-07-03T00:10:00Z", "M5")
        with self.assertRaisesRegex(DataError, "aligned"):
            CandleWindow.create("2024-07-03T00:01:00Z", "2024-07-03T00:10:00Z", "M5")

    def test_oanda_uses_only_completed_candles_in_window(self):
        def candle(minute, complete):
            return {"time": f"2024-07-03T00:{minute:02}:00.000000000Z", "complete": complete,
                    "bid": {"o": "2000", "h": "2002", "l": "1998", "c": "2001"}, "volume": 3}

        payload = {"candles": [candle(0, False), candle(5, True), candle(10, True)]}
        with patch.dict("os.environ", {"OANDA_API_TOKEN": "unit-test-only"}):
            with patch("signal_tracker.sources._download_oanda", return_value=payload) as download:
                result = fetch_oanda("XAUUSD", "XAU_USD", self.window)
        self.assertEqual(result.index.tolist(), [pd.Timestamp("2024-07-03T00:05:00Z")])
        self.assertEqual(result.iloc[0]["closed_at_utc"], self.window.end)
        self.assertEqual(download.call_args.args[2]["price"], "B")
        self.assertEqual(download.call_args.args[2]["alignmentTimezone"], "UTC")

    def test_config_preserves_original_versions_alongside_the_new_intraday_versions(self):
        registry = load_strategies()
        self.assertEqual(len(registry["strategies"]), 16)
        self.assertEqual(sum(spec["experimental"] for spec in registry["strategies"]), 12)
        self.assertEqual(sum(spec.get("live_feed") == "BIQUOTE_XAUUSD_MID" for spec in registry["strategies"]), 10)
        specs = {spec["strategy_code"]: spec for spec in registry["strategies"]}
        baseline, experiment = specs["CLD-SCA-02-v2"], specs["CLD-SCA-02-v3"]
        self.assertEqual(baseline["take_profit_r"], [1, 2])
        self.assertNotIn("tp2_fraction", baseline["execution"])
        self.assertEqual(experiment["take_profit_r"], [1, 2, 3])
        self.assertEqual(experiment["setup"], baseline["setup"])
        for code in ("CLD-INT-01", "CLD-INT-02"):
            original, faster = specs[code + "-v2"], specs[code + "-v3"]
            self.assertEqual(original["trend"]["ema_period"], 200)
            self.assertEqual(faster["trend"], original["trend"] | {"ema_period": 150})
            self.assertNotIn("EMA200", " ".join(faster["public_rules"]))
            changed = {"strategy_code", "trend", "public_rules"}
            self.assertEqual({k: v for k, v in original.items() if k not in changed},
                             {k: v for k, v in faster.items() if k not in changed})
            self.assertIn(code + "-v2", registry["retired_live_strategy_codes"])
            self.assertNotIn(code + "-v3", registry["retired_live_strategy_codes"])
        self.assertTrue(specs["OWN-SWG-01-v1"]["site_test"])
        self.assertTrue(all(spec["version_state"] == "FROZEN" for spec in registry["strategies"]))
        self.assertEqual(market_for(None)[0], "XAUUSD")
        with self.assertRaisesRegex(ValueError, "not enabled"):
            market_for("EURUSD")
