"""Deterministic, plain-language notes; observations are not advice."""

from decimal import Decimal
from typing import Any

from .scoreboard_stats import ScoredSignal, ZERO

MIN_SESSION_SAMPLE = 10


def analyze(
    records: list[ScoredSignal], metrics: dict[str, Any],
    sessions: dict[str, dict[str, Any]], coverage: dict[str, int] | None,
) -> dict[str, Any]:
    n = metrics["completed"]
    strengths: list[str] = []
    weaknesses: list[str] = []
    warnings: list[str] = []
    if not n:
        summary = "No completed trades. Win rate, expectancy and drawdown are not estimable."
    else:
        summary = (f"{n} completed trades averaged {metrics['expectancy_r']:+.2f}R, "
                   f"with {metrics['max_drawdown_r']:.2f}R of realized drawdown.")
        if metrics["expectancy_r"] > 0:
            strengths.append("Completed trades had positive net expectancy in this sample.")
        elif metrics["expectancy_r"] < 0:
            weaknesses.append("Completed trades had negative net expectancy in this sample.")
        else:
            weaknesses.append("Completed trades had no net gain in this sample.")
        interval = metrics["expectancy_r_ci_95"]
        if interval and interval[0] <= 0 <= interval[1]:
            warnings.append("The expectancy interval includes zero; the sign of the edge is uncertain.")
        if interval is None:
            warnings.append("Too few distinct UTC close days to estimate an expectancy interval.")
        elif interval[0] == interval[1]:
            warnings.append("The observed day clusters gave no estimated variation; this is not certainty.")
        if metrics["max_drawdown_r"] > 0:
            weaknesses.append(f"Realized equity fell by as much as {metrics['max_drawdown_r']:.2f}R from a peak.")
    if n < 30:
        warnings.append("Sample too small: fewer than 30 completed trades. Do not draw a performance conclusion.")
    elif n < 100:
        warnings.append("Only weak evidence: fewer than 100 completed trades. Not eligible for ranking.")
    else:
        warnings.append("Usable sample size is not proof that future returns will be similar.")
    delayed = metrics["entry_unresolved"] + metrics["filled_open"]
    if delayed:
        warnings.append(f"{delayed} signals are unresolved and excluded from win rate and R metrics.")
    if metrics["unresolved_missing_m1"]:
        warnings.append(f"{metrics['unresolved_missing_m1']} signals could not be resolved across missing M1 candles.")
    if metrics["unresolved_fold_cutoff"]:
        warnings.append(f"{metrics['unresolved_fold_cutoff']} signals were still unresolved at the fold cutoff.")
    if coverage is not None:
        if coverage.get("news_unknown", 0) or coverage.get("spread_unknown", 0):
            warnings.append("Historical news or spread evidence is missing. Results only describe the covered subset.")
        rejected = coverage.get("technical_candidates_rejected_by_filters", 0)
        if rejected:
            warnings.append(f"{rejected} technical setups did not pass the required filters and are not trades.")
    wins: list[Decimal] = sorted(
        (row.outcome.result_r for row in records
         if row.outcome.result_r is not None and row.outcome.result_r > 0), reverse=True,
    )
    top = wins[:3]
    if top and metrics["total_r"] and metrics["total_r"] > 0 and metrics["total_r"] - sum(top, ZERO) <= 0:
        noun = "trade" if len(top) == 1 else "trades"
        warnings.append(f"Net profit depends on the top {len(top)} winning {noun}; without them total R is not positive.")
    comparable = {name: stats for name, stats in sessions.items()
                  if name in ("Asia", "London", "New York") and stats["completed"] >= MIN_SESSION_SAMPLE}
    best = worst = None
    if len(comparable) >= 2:
        expectancy = {name: stats["expectancy_r"] for name, stats in comparable.items()}
        high, low = max(expectancy.values()), min(expectancy.values())
        if high != low:
            def describe(value: Decimal) -> dict[str, Any]:
                return {"sessions": [name for name, mean in expectancy.items() if mean == value],
                        "expectancy_r": value}
            best, worst = describe(high), describe(low)
        else:
            warnings.append("Comparable sessions tied on average R.")
    else:
        warnings.append(f"Best/worst session not estimable: need {MIN_SESSION_SAMPLE} completed trades in at least two sessions.")
    return {"summary": summary, "strengths": strengths, "weaknesses": weaknesses,
            "best_session": best, "worst_session": worst, "warnings": warnings}
