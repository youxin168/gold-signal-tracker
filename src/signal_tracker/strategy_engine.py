"""Closed-candle rules shared by prospective scans and chronological backtests."""

from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import pandas as pd

from .config import TIMEFRAMES
from .indicators import atr, donchian, ema, rsi
from .trend_pullback import Decision, PreparedTrend, SpreadQuote, _news_blocked, _session, spread_status

ARCHETYPES = frozenset({"trend_pullback_v1", "micro_pullback_v1", "sweep_reversal_v1",
                        "session_breakout_v1", "daily_pullback_v1", "channel_breakout_v1", "swing_retest_v1"})


class PreparedRule:
    """Compute causal series once; every decision is indexed by candle close."""

    def __init__(self, entry: pd.DataFrame, trend: pd.DataFrame, spec: dict[str, Any]):
        self.spec, self.kind = spec, spec["implementation"]
        self.entry = entry
        self.mtime, self.htime = (pd.DatetimeIndex(frame["closed_at_utc"]) for frame in (entry, trend))
        self.step = timedelta(minutes=TIMEFRAMES[spec["entry_timeframe"]])
        self.context_step = timedelta(minutes=TIMEFRAMES[spec["trend_timeframe"]])
        self.high, self.low, self.open, self.close = (entry[key].to_numpy() for key in ("high", "low", "open", "close"))
        self.context = None
        t = spec["trend"]
        if t and t["type"] == "price_vs_ema":
            self.context = (trend["close"] - ema(trend["close"], t["ema_period"])).to_numpy()
        elif t and t["type"] == "ema_vs_ema":
            self.context = (ema(trend["close"], t["fast_period"]) - ema(trend["close"], t["slow_period"])).to_numpy()
        setup, stop = spec["setup"], spec["stop"]
        self.distances = atr(entry, stop["atr_period"]).to_numpy() if "atr_period" in stop else None
        self.turn = rsi(entry["close"], setup["rsi_period"]).to_numpy() if "rsi_period" in setup else None
        self.bands = [ema(entry["close"], n).shift(1).to_numpy() for n in setup.get("ema_periods", [])]
        if "lookback_closed_candles" in setup:
            self.lookback = setup["lookback_closed_candles"]
            envelope = donchian(entry, self.lookback)
            self.range_high, self.range_low = (envelope.iloc[:, k].to_numpy() for k in (0, 1))
        if self.kind == "session_breakout_v1":
            self.asian = self._asian_ranges()

    def _asian_ranges(self) -> dict:
        window = self.spec["setup"]["asian_range_utc"]
        start, end = [int(window[key].split(":")[0]) for key in ("start", "end_exclusive")]
        hours = self.entry.index.hour
        data = self.entry.loc[(hours >= start) & (hours < end)]
        return {day: (group["high"].max(), group["low"].min())
                for day, group in data.groupby(data.index.date)
                if len(group) == (end - start) * 60 // int(self.step.total_seconds() / 60)}

    def _contiguous(self, i: int, n: int) -> bool:
        # Unique, regularly aligned bars make an exact end-to-end span sufficient.
        return i >= n and self.mtime[i] - self.mtime[i - n] == self.step * n

    def _levels(self, i: int, sign: int, session: str, stop: float | None = None) -> Decision:
        spec, at = self.spec, self.mtime[i].to_pydatetime()
        side = "BUY" if sign == 1 else "SELL"
        tick = Decimal(spec["price_tick"])
        price = self.close[i]
        if stop is None:
            distance = self.distances[i] * spec["stop"]["atr_multiple"]
            if pd.isna(distance) or distance <= 0:
                return Decision("SKIP", "ATR is not warmed up or is zero")
            stop = price - sign * distance
        def snapped(value: float | Decimal) -> Decimal:
            return (Decimal(str(value)) / tick).quantize(Decimal(1), rounding=ROUND_HALF_UP) * tick
        entry, sl = snapped(price), snapped(stop)
        risk = sign * (entry - sl)
        if risk <= 0:
            return Decision("SKIP", "Stop is on the wrong side or rounds to entry")
        targets = tuple(snapped(entry + sign * risk * Decimal(str(multiple))) for multiple in spec["take_profit_r"])
        if len(targets) not in (2, 3):
            raise ValueError("A strategy must define two or three targets")
        if min(entry, sl, *targets) <= 0 or not all(
            sign * (target - prior) > 0 for prior, target in zip((entry, *targets), targets)
        ):
            return Decision("SKIP", "Rounded levels are not positive and ordered")
        return Decision("SIGNAL", session, side, at, (entry, sl, *targets))

    def _prepare(self, i: int, sign: int, session: str) -> Decision:
        return Decision("PREPARE", f"{session}: setup forming, no confirmed entry",
                        "BUY" if sign == 1 else "SELL", self.mtime[i].to_pydatetime())

    def _pullback(self, i: int, sign: int, session: str) -> Decision:
        if not self._contiguous(i, 2):
            return Decision("SKIP", "Pullback crosses a missing entry candle")
        left, pivot, right = self.turn[i - 2:i + 1]
        def touch(k: int, confirmed: bool) -> bool:
            return any(self.low[k] <= band[k] <= self.high[k] and
                       (not confirmed or sign * (self.close[i] - band[k]) > 0) for band in self.bands)
        if (sign * (left - pivot) > 0 and sign * (right - pivot) > 0 and touch(i - 1, True)
                and sign * (self.close[i] - self.open[i]) > 0 and sign * (self.close[i] - self.close[i - 1]) > 0):
            return self._levels(i, sign, session)
        if sign * (pivot - right) > 0 and touch(i, False):
            return self._prepare(i, sign, session)
        return Decision("NONE", "No confirmed pullback")

    def _sweep(self, i: int, session: str) -> Decision:
        if not self._contiguous(i, self.lookback):
            return Decision("SKIP", "Sweep range crosses a missing entry candle")
        top, bottom = self.range_high[i], self.range_low[i]
        swept_high, swept_low = self.high[i] > top, self.low[i] < bottom
        if swept_high == swept_low:
            return Decision("NONE", "No unambiguous range sweep")
        sign = 1 if swept_low else -1
        if bottom < self.close[i] < top:
            wick = self.low[i] if swept_low else self.high[i]
            return self._levels(i, sign, session, wick - sign * float(self.spec["stop"]["buffer_price"]))
        if (swept_low and self.close[i] <= bottom) or (swept_high and self.close[i] >= top):
            return self._prepare(i, sign, session)
        return Decision("NONE", "Sweep did not close inside its range")

    def _session_breakout(self, i: int, sign: int, session: str) -> Decision:
        at = self.mtime[i]
        asia_end = int(self.spec["setup"]["asian_range_utc"]["end_exclusive"].split(":")[0])
        # The final Asian bar belongs to the range; it cannot be a breakout.
        if at <= at.normalize() + timedelta(hours=asia_end):
            return Decision("SKIP", "Asian range has not finished before this bar")
        limits = self.asian.get(at.date())
        if limits is None or not self._contiguous(i, 1):
            return Decision("SKIP", "Asian range or prior entry bar is incomplete")
        top, bottom = limits
        if not bottom <= self.close[i - 1] <= top:
            return Decision("NONE", "Prior close was not inside the Asian range")
        threshold = top if sign == 1 else bottom
        if sign * (self.close[i] - threshold) > 0:
            distance = self.distances[i] * self.spec["stop"]["atr_multiple"]
            if pd.isna(distance) or distance <= 0:
                return Decision("SKIP", "ATR is not warmed up or is zero")
            opposite = bottom if sign == 1 else top
            stop = self.close[i] - sign * min(abs(self.close[i] - opposite), distance)
            return self._levels(i, sign, session, stop)
        if sign * ((self.high[i] if sign == 1 else self.low[i]) - threshold) > 0:
            return self._prepare(i, sign, session)
        return Decision("NONE", "No session breakout")

    def _channel(self, i: int, sign: int, session: str) -> Decision:
        threshold = self.range_high[i] if sign == 1 else self.range_low[i]
        if pd.isna(threshold):
            return Decision("SKIP", "Channel is not warmed up")
        if sign * (self.close[i] - threshold) > 0:
            return self._levels(i, sign, session)
        if sign * ((self.high[i] if sign == 1 else self.low[i]) - threshold) > 0:
            return self._prepare(i, sign, session)
        return Decision("NONE", "No channel breakout")

    def _first_retest(self, retest: int, sign: int) -> float | None:
        """Return the frozen breakout level only if this is its first valid retest."""
        if retest <= 0:
            return None
        level_series = self.range_high if sign == 1 else self.range_low
        near_wick = self.low if sign == 1 else self.high
        far_wick = self.high if sign == 1 else self.low
        window = self.spec["setup"]["max_retest_bars"]
        for gap in range(1, window + 1):
            breakout = retest - gap
            if not self._contiguous(breakout, self.lookback) or not self._contiguous(retest, gap):
                continue
            threshold = level_series[breakout]
            if pd.isna(threshold) or sign * (self.close[breakout] - threshold) <= 0:
                continue
            context_at = self.mtime[breakout]
            h4 = self.htime.searchsorted(context_at, side="right") - 1
            if h4 < 0 or context_at - self.htime[h4] >= self.context_step or not sign * self.context[h4] > 0:
                continue
            # Any earlier touch consumes this setup, including a close back inside.
            if any(not sign * (near_wick[k] - threshold) > 0 for k in range(breakout + 1, retest)):
                continue
            if (sign * (near_wick[retest] - threshold) <= 0 <= sign * (far_wick[retest] - threshold)
                    and sign * (self.close[retest] - threshold) >= 0):
                return float(threshold)
        return None

    def _swing_retest(self, i: int, sign: int, session: str) -> Decision:
        # Confirmation is never the breakout or retest candle itself. Signals
        # use only the first closing confirmation immediately after a valid retest.
        if i < self.lookback or not self._contiguous(i, 1):
            return Decision("SKIP", "Swing Retest lacks fresh consecutive H1 candles")
        threshold = self._first_retest(i - 1, sign)
        if threshold is not None:
            edge = self.high[i - 1] if sign == 1 else self.low[i - 1]
            near = self.low[i] if sign == 1 else self.high[i]
            if (sign * (near - threshold) >= 0 and sign * (self.close[i] - edge) > 0
                    and sign * (self.close[i] - self.open[i]) > 0):
                rule = self.spec["stop"]
                distance = self.distances[i]
                if (not self._contiguous(i, rule["atr_period"]) or pd.isna(distance) or distance <= 0):
                    return Decision("SKIP", "Swing Retest lacks sufficient H1 risk data")
                wick = self.low[i - 1] if sign == 1 else self.high[i - 1]
                wick_risk = sign * (self.close[i] - wick) + rule["buffer_atr_fraction"] * distance
                risk = max(wick_risk, rule["min_atr_multiple"] * distance)
                return self._levels(i, sign, f"{session}: confirmed H1 break and first retest",
                                    self.close[i] - sign * risk)
            return Decision("NONE", "Swing Retest rejected: next close did not confirm the retest")
        if self._first_retest(i, sign) is not None:
            return self._prepare(i, sign, session)
        return Decision("NONE", "Swing Retest awaiting an H1 breakout, first retest and confirming close")

    def at(self, at: datetime, session: str) -> Decision:
        i = self.mtime.searchsorted(at, side="right") - 1
        if i < 0 or at - self.mtime[i] >= self.step:
            return Decision("SKIP", "No fresh closed entry candle")
        closed = self.mtime[i]
        j = self.htime.searchsorted(closed, side="right") - 1
        if j < 0 or closed - self.htime[j] >= self.context_step:
            return Decision("SKIP", "No fresh higher-timeframe context")
        if self.kind == "sweep_reversal_v1":
            return self._sweep(i, session)
        trend = self.context[j]
        if pd.isna(trend) or trend == 0:
            return Decision("SKIP", "Trend is not warmed up or is flat")
        sign = 1 if trend > 0 else -1
        if self.kind in ("micro_pullback_v1", "daily_pullback_v1"):
            return self._pullback(i, sign, session)
        if self.kind == "session_breakout_v1":
            return self._session_breakout(i, sign, session)
        if self.kind == "swing_retest_v1":
            return self._swing_retest(i, sign, session)
        return self._channel(i, sign, session)


def prepare(entry, trend, spec):
    if spec["implementation"] == "trend_pullback_v1":
        return PreparedTrend(entry, trend, spec)
    if spec["implementation"] not in ARCHETYPES:
        raise ValueError("No automated rule engine for this strategy")
    return PreparedRule(entry, trend, spec)


def decide(entry, trend, spec, at, *, calendar: dict | None, quote: SpreadQuote | None) -> Decision:
    if spec["implementation"] == "trend_pullback_v1":
        from .trend_pullback import evaluate
        return evaluate(entry, trend, spec, at, calendar=calendar, quote=quote)
    session = _session(at, spec["session_filter"])
    if session is None:
        return Decision("SKIP", "Outside the frozen session")
    if _news_blocked(calendar, at, spec["news_filter"]):
        return Decision("SKIP", "High-impact news window or missing calendar coverage")
    if spread_status(quote, at, spec["spread_filter"]) != "ok":
        return Decision("SKIP", "Spread is too wide, missing, stale or future-dated")
    # Computing on a truncated slice also avoids accidental use of future
    # rows by a future rule; historical setup arrays are separately tested.
    after_gates = prepare(entry.loc[entry["closed_at_utc"] <= at], trend.loc[trend["closed_at_utc"] <= at], spec)
    return after_gates.at(at, session)
