import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from signal_tracker.indicators import adx, atr, donchian, ema, rsi, true_range, with_indicators


class IndicatorTests(unittest.TestCase):
    def test_ema_uses_sma_seed(self):
        result = ema(pd.Series([1, 3, 6, 5]), 2)
        self.assertTrue(pd.isna(result.iloc[0]))
        self.assertEqual(result.iloc[1], 2)
        self.assertAlmostEqual(result.iloc[2], 14 / 3)

    def test_ema_restarts_after_missing_value(self):
        result = ema(pd.Series([1, 3, None, 5, 7]), 2)
        self.assertTrue(result.iloc[2:4].isna().all())
        self.assertEqual(result.iloc[4], 6)

    def test_rsi_extremes_and_warmup(self):
        for prices, expected in [([1, 2, 3], 100), ([3, 2, 1], 0), ([3, 3, 3], 50)]:
            result = rsi(pd.Series(prices), 2)
            self.assertTrue(result.iloc[:2].isna().all())
            self.assertEqual(result.iloc[2], expected)

    def test_true_range_counts_gap_and_atr_uses_wilder_smoothing(self):
        bars = pd.DataFrame({"high": [11, 16, 17], "low": [9, 15, 15], "close": [10, 15, 16]})
        self.assertEqual(true_range(bars).tolist(), [2, 6, 2])
        self.assertEqual(atr(bars, 2).iloc[1:].tolist(), [4, 3])

    def test_adx_for_flat_and_rising_prices(self):
        for prices, expected in [([3] * 5, 0), (list(range(5)), 100)]:
            result = adx(pd.DataFrame({"high": prices, "low": prices}), 2)
            self.assertTrue(result.iloc[:3].isna().all())
            self.assertEqual(result.iloc[3:].tolist(), [expected, expected])

    def test_donchian_excludes_candidate_bar(self):
        bars = pd.DataFrame({"high": [4, 6, 9], "low": [2, 1, 0]})
        band = donchian(bars, 2)
        self.assertEqual(band.iloc[-1].tolist(), [6, 1])

    def test_later_data_cannot_change_past_indicators(self):
        close = pd.Series([100 + (i % 9) - (i % 3) / 2 for i in range(240)])
        bars = pd.DataFrame({"high": close + 1, "low": close - 1, "close": close})
        assert_frame_equal(with_indicators(bars).iloc[:210], with_indicators(bars.iloc[:210]))
