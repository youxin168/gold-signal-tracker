"""Comparable head-to-head results without pooling incompatible evidence."""

from collections import defaultdict
from datetime import UTC, timedelta
from itertools import product
from typing import Any

from .scoreboard import MIN_RANK_SAMPLE, Cohort, _rank_key
from .scoreboard_stats import ScoredSignal, summarize
from .signal import utc


def eligibility(spec: dict[str, Any]) -> tuple:
    return spec.get("execution"), spec.get("news_filter"), spec.get("spread_filter")


def _window(records: list[ScoredSignal]):
    days = [row.signal.issued_at_utc.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            for row in records]
    return (min(days), max(days) + timedelta(days=1)) if days else None


def compare(cohort: Cohort) -> list[dict[str, Any]]:
    buckets: dict[str, list[ScoredSignal]] = defaultdict(list)
    for record in cohort.records:
        buckets[record.signal.strategy_code].append(record)
    strategies = cohort.strategies
    claude = sorted(code for code, spec in strategies.items() if spec["source"] == "CLD")
    external = sorted(code for code, spec in strategies.items() if spec["source"] in {"EXT1", "EXT2", "OWN"})
    results = []
    for left, right in product(claude, external):
        a, b = strategies[left], strategies[right]
        if a["style"] != b["style"] or a["version_state"] != "FROZEN" or b["version_state"] != "FROZEN":
            continue
        records_a, records_b = buckets[left], buckets[right]
        start, end = cohort.start_utc, cohort.end_utc_exclusive
        metrics_a = metrics_b = None
        leader = None
        reason = ""
        if cohort.mode != "BACKTEST":
            span_a, span_b = _window(records_a), _window(records_b)
            if span_a and span_b and max(span_a[0], span_b[0]) < min(span_a[1], span_b[1]):
                first, last = max(span_a[0], span_b[0]), min(span_a[1], span_b[1])
                start, end = utc(first), utc(last)
                records_a = [r for r in records_a if first <= r.signal.issued_at_utc < last]
                records_b = [r for r in records_b if first <= r.signal.issued_at_utc < last]
            else:
                start = end = None
                reason = "There is no shared UTC issue-date window with recorded signals on both sides."
        if not reason:
            metrics_a, metrics_b = summarize(records_a, equity=False), summarize(records_b, equity=False)
            if "manual_v1" in (a.get("implementation"), b.get("implementation")):
                reason = "Descriptive only: the review cannot verify a manual entry used the same automated filters."
            elif eligibility(a) != eligibility(b):
                reason = "The execution assumptions or entry evidence gates differ; no comparison rank is valid."
            elif min(metrics_a["completed"], metrics_b["completed"]) < MIN_RANK_SAMPLE:
                reason = f"Both strategies need at least {MIN_RANK_SAMPLE} completed trades in this window. No leader is declared."
            else:
                key_a, key_b = _rank_key(metrics_a), _rank_key(metrics_b)
                leader = left if key_a < key_b else right if key_b < key_a else None
                reason = ("Observed leader uses total R, expectancy, lower drawdown, then profit factor; "
                          "this ranking does not establish a persistent edge." if leader else
                          "The two strategies tie on the ranking metrics; no leader is declared.")
            if cohort.mode != "BACKTEST":
                reason += " The shared span uses recorded UTC issue dates; it does not prove continuous scan coverage."
        results.append({"style": a["style"], "claude_code": left, "external_code": right,
                        "start_utc": start, "end_utc_exclusive": end, "claude_metrics": metrics_a,
                        "external_metrics": metrics_b, "leader": leader, "explanation": reason})
    return results
