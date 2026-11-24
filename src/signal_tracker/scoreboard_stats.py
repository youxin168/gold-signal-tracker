"""Descriptive performance and uncertainty from individual scored signals."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from math import sqrt
from typing import Any

from .config import STRATEGY_CODE
from .signal import Outcome, Signal, Status

CLOSED = {Status.SL, Status.TP2, Status.TP3, Status.BE}
ZERO = Decimal(0)


@dataclass(frozen=True)
class ScoredSignal:
    signal: Signal
    outcome: Outcome
    regime: str = "Unknown"
    unresolved_reason: str | None = None

    def __post_init__(self) -> None:
        signal, state = self.signal, self.outcome
        match = STRATEGY_CODE.fullmatch(signal.strategy_code)
        if not match or match.groups() != (signal.source, signal.style):
            raise ValueError(f"Strategy code, source and style disagree: {signal.signal_id}")
        finished = state.status in CLOSED
        filled = finished or state.status in (Status.ACTIVE, Status.TP1, Status.TP2_OPEN)
        ended = finished or state.status == Status.EXPIRED
        if (filled != (state.triggered_at is not None) or ended != (state.closed_at is not None)
                or finished != (state.result_r is not None)
                or (state.result_r is not None and not state.result_r.is_finite())):
            raise ValueError(f"Invalid status, times or result: {signal.signal_id}")
        for stamp in (state.triggered_at, state.closed_at):
            if stamp is not None and (stamp.utcoffset() is None or stamp < signal.issued_at_utc):
                raise ValueError(f"Invalid outcome timestamp: {signal.signal_id}")
        if finished and state.closed_at < state.triggered_at:
            raise ValueError(f"Outcome closes before the signal fills: {signal.signal_id}")
        if self.unresolved_reason is not None and ended:
            raise ValueError(f"Closed signal cannot have an unresolved reason: {signal.signal_id}")


def sample_badge(n: int) -> str:
    if n < 30:
        return "Too early"
    return "Weak evidence" if n < 100 else "Usable"


def wilson_interval(wins: int, n: int) -> tuple[float, float] | None:
    """Nominal 95% Wilson score interval; association can narrow it too much."""
    if not n:
        return None
    z = 1.959963984540054
    p = wins / n
    denom = 1 + z * z / n
    midpoint = (p + z * z / (2 * n)) / denom
    radius = z / denom * sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, midpoint - radius), min(1.0, midpoint + radius)


# Two-sided 95% Student t critical values. Between tabulated degrees of
# freedom use the lower df (wider interval), not interpolation toward normality.
T95 = (
    (1, 12.706), (2, 4.303), (3, 3.183), (4, 2.776), (5, 2.571), (6, 2.447),
    (7, 2.365), (8, 2.306), (9, 2.262), (10, 2.228), (12, 2.179), (15, 2.131),
    (20, 2.086), (30, 2.042), (60, 2.000), (120, 1.980),
)


def expectancy_interval(
    results: list[tuple[datetime, Decimal]], mean: Decimal,
) -> tuple[float, float] | None:
    """95% t interval for mean R with same-UTC-close-day clustered errors."""
    day_scores: dict[date, Decimal] = defaultdict(Decimal)
    for closed_at, result in results:
        day_scores[closed_at.astimezone(UTC).date()] += result - mean
    groups = len(day_scores)
    if groups < 2:
        return None
    critical = next(value for df, value in reversed(T95) if df < groups)
    residual_sum = sum((score**2 for score in day_scores.values()), ZERO)
    se = sqrt(float(residual_sum) * groups / (groups - 1)) / len(results)
    return float(mean) - critical * se, float(mean) + critical * se


def summarize(
    records: list[ScoredSignal], *, equity: bool = True, intervals: bool = True,
) -> dict[str, Any]:
    counts = Counter(record.outcome.status for record in records)
    filled = sum(record.outcome.triggered_at is not None for record in records)
    expired = counts[Status.EXPIRED]
    closed = sorted(
        ((row.outcome.closed_at, row.signal.signal_id, row.outcome.result_r)
         for row in records if row.outcome.status in CLOSED),
        key=lambda item: (item[0], item[1]),
    )
    values = [item[2] for item in closed]
    n = len(values)
    total = sum(values, ZERO)
    wins, losses = sum(value > 0 for value in values), sum(value < 0 for value in values)
    gross_profit = sum((value for value in values if value > 0), ZERO)
    gross_loss = -sum((value for value in values if value < 0), ZERO)
    factor = gross_profit / gross_loss if gross_loss else None
    factor_status = ("finite" if gross_loss else "no_losses" if gross_profit else "not_estimable")
    average = total / n if n else None
    streak = max_streak = 0
    by_time: dict[datetime, Decimal] = defaultdict(Decimal)
    for stamp, _, value in closed:
        streak = streak + 1 if value < 0 else 0
        max_streak = max(max_streak, streak)
        by_time[stamp.astimezone(UTC)] += value
    peak = running = max_drawdown = ZERO
    points = []
    for stamp, amount in by_time.items():
        running += amount
        peak = max(peak, running)
        max_drawdown = max(max_drawdown, peak - running)
        if equity:
            points.append({"closed_at_utc": stamp.isoformat(), "equity_r": running})
    return {
        "signals": len(records), "filled": filled, "expired": expired,
        "entry_unresolved": len(records) - filled - expired, "filled_open": filled - n,
        "unresolved_missing_m1": sum(row.unresolved_reason == "MISSING_M1" for row in records),
        "unresolved_fold_cutoff": sum(row.unresolved_reason == "FOLD_CUTOFF" for row in records),
        "fill_rate": Decimal(filled) / (filled + expired) if filled + expired else None,
        "observed_fill_rate_lower_bound": Decimal(filled) / len(records) if records else None,
        "completed": n, "wins": wins, "losses": losses, "flat": n - wins - losses,
        "win_rate": Decimal(wins) / n if n else None,
        "average_r": average, "expectancy_r": average,
        "profit_factor": factor, "profit_factor_status": factor_status,
        "total_r": total if n else None,
        "max_drawdown_r": max_drawdown if n else None,
        "longest_losing_streak": max_streak if n else None,
        "equity_curve_r": points,
        "sample_size_badge": sample_badge(n),
        "win_rate_ci_95": wilson_interval(wins, n) if intervals else None,
        "expectancy_r_ci_95": expectancy_interval([(stamp, value) for stamp, _, value in closed], average)
        if n and intervals else None,
        "completed_utc_days": len({stamp.astimezone(UTC).date() for stamp, _, _ in closed}),
    }
