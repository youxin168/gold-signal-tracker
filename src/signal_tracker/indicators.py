"""Causal indicators. Input rows must be sorted, already-closed candles."""

import pandas as pd


def _check_period(period: int) -> None:
    if period < 1:
        raise ValueError("Indicator period must be at least one")


def _smooth(values: pd.Series, period: int, alpha: float) -> pd.Series:
    """Seed with a simple average; restart warm-up after an explicit missing value."""
    _check_period(period)
    result: list[float] = []
    count = 0
    running_sum = 0.0
    average = float("nan")
    for value in values:
        if pd.isna(value):
            count, running_sum, average = 0, 0.0, float("nan")
        elif count < period:
            count += 1
            running_sum += value
            if count == period:
                average = running_sum / period
        else:
            average += alpha * (value - average)
        result.append(average)
    return pd.Series(result, index=values.index, dtype="float64")


def ema(values: pd.Series, period: int) -> pd.Series:
    """Exponential moving average, seeded with the first `period` observations."""
    _check_period(period)
    return _smooth(values, period, 2 / (period + 1)).rename(f"ema_{period}")


def _wilder(values: pd.Series, period: int) -> pd.Series:
    _check_period(period)
    return _smooth(values, period, 1 / period)


def true_range(candles: pd.DataFrame) -> pd.Series:
    """Greatest of the high/low range and the distances to the previous close."""
    previous_close = candles["close"].shift(1)
    return pd.concat(
        [candles["high"] - candles["low"], (candles["high"] - previous_close).abs(),
         (candles["low"] - previous_close).abs()], axis=1,
    ).max(axis=1, skipna=True).rename("true_range")


def atr(candles: pd.DataFrame, period: int = 14) -> pd.Series:
    return _wilder(true_range(candles), period).rename(f"atr_{period}")


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    changes = close.diff()
    gain = _wilder(changes.clip(lower=0), period)
    loss = _wilder((-changes).clip(lower=0), period)
    total = gain + loss
    result = (100 * gain / total).mask(total == 0, 50.0)
    return result.rename(f"rsi_{period}")


def adx(candles: pd.DataFrame, period: int = 14) -> pd.Series:
    up = candles["high"].diff()
    down = -candles["low"].diff()
    valid = up.notna() & down.notna()
    plus = _wilder(up.where((up > down) & (up > 0), 0).where(valid), period)
    minus = _wilder(down.where((down > up) & (down > 0), 0).where(valid), period)
    # The common smoothed true range denominator in +DI/-DI cancels in DX.
    total = plus + minus
    dx = (100 * (plus - minus).abs() / total).mask(total == 0, 0.0)
    return _wilder(dx, period).rename(f"adx_{period}")


def donchian(candles: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Previous highs/lows only; the candidate candle cannot move the threshold."""
    _check_period(period)
    return pd.DataFrame({
        f"donchian_high_{period}": candles["high"].shift(1).rolling(period).max(),
        f"donchian_low_{period}": candles["low"].shift(1).rolling(period).min(),
    })


def with_indicators(candles: pd.DataFrame) -> pd.DataFrame:
    """Attach research columns; not a strategy decision or a signal."""
    result = candles.copy()
    for period in (20, 21, 50, 200):
        result[f"ema_{period}"] = ema(candles["close"], period)
    for period in (7, 14):
        result[f"rsi_{period}"] = rsi(candles["close"], period)
    result["atr_14"] = atr(candles)
    result["adx_14"] = adx(candles)
    return result.join(donchian(candles))
