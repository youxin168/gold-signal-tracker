"""Render the backtest without turning unavailable metrics into zeroes."""

from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Any

from .backtest import Fold

COUNTS = (
    ("session_decision_slots", "London/New York decision slots (including holidays)"),
    ("observed_session_decisions", "Slots with a closed entry candle"),
    ("news_ok", "News filter passed"),
    ("news_blocked", "Excluded by high-impact news"),
    ("news_unknown", "Missing usable calendar snapshot"),
    ("spread_ok", "Spread filter passed"),
    ("spread_wide", "Excluded by wide spread"),
    ("spread_unknown", "Missing fresh bid/ask quote"),
    ("both_filters_pass", "Both evidence filters passed"),
    ("technical_candidates_before_filters", "Technical candidates before filters (not signals)"),
    ("technical_candidates_rejected_by_filters", "Technical candidates not eligible after filters"),
    ("daily_cap_rejections", "Excluded by daily signal limit"),
)
RESULTS = (
    ("signals", "Eligible signals"), ("filled", "Filled (including unresolved)"),
    ("expired", "Expired unfilled"), ("unresolved", "Unresolved"),
    ("missing_m1", "Unresolved: missing M1"), ("fold_cutoff", "Unresolved: fold ended"),
    ("closed", "Completed trades with a result"), ("wins", "Positive net results"),
    ("losses", "Negative net results"), ("flat", "Zero net results"),
    ("win_rate_closed", "Win rate (completed trades only)"),
    ("average_r_closed", "Average R (completed trades only)"),
    ("total_r_closed", "Total R (completed trades only)"),
)


def _display(key: str, value: Any) -> str:
    if value is None:
        return "Not estimable"
    if key == "win_rate_closed":
        return f"{value:.1%}"
    if isinstance(value, Decimal):
        return f"{value:.3f}"
    return f"{value:,}"


def markdown(
    folds: tuple[Fold, Fold], spec: dict[str, Any], feed: str, inputs: dict[str, str],
) -> str:
    one, two = folds
    period = f"{one.start.date()} to {two.end.date()} (UTC; end exclusive)"
    metrics = [fold.metrics() for fold in folds]
    text = [
        f"# BACKTEST — {spec['pair']} · {spec['strategy_code']}", "",
        f"Requested window: **{period}**  ",
        f"Price feed: `{feed}`  ",
        f"Split: first {one.start.date()}–{one.end.date()}, then {two.start.date()}–{two.end.date()}; both end-exclusive.",
        "", "**Research and testing only. Not financial advice or evidence of live execution.**", "",
    ]
    if any(not metric["closed"] for metric in metrics):
        text.extend([
            "**Performance is not estimable for at least one fold.** "
            "A missing input or a zero eligible sample is not a 0% win rate, a flat result, or a failed strategy.", "",
        ])
    if (two.end - one.start).days < 730:
        text.extend(["**Short run:** the requested date range contains fewer than 730 days.", ""])
    for fold, metric in zip(folds, metrics):
        if metric["closed"] < 30:
            text.append(f"- **{fold.label}: too early** — fewer than 30 completed trades.")
        if fold.coverage["news_unknown"] or fold.coverage["spread_unknown"] or metric["unresolved"]:
            text.append(f"- **{fold.label}: incomplete evidence.** Any observed results describe only the covered subset.")
    text.extend(["", "## Price coverage", "",
                 "| UTC time slots | In-sample observed / possible | Out-of-sample observed / possible |",
                 "|---|---:|---:|"])
    entry_tf, trend_tf = spec["entry_timeframe"], spec["trend_timeframe"]
    for tf in ("m1", entry_tf.lower(), trend_tf.lower()):
        cells = [f"{f.coverage[f'{tf}_observed']:,} / {f.coverage[f'{tf}_slots']:,}" for f in folds]
        text.append(f"| {tf.upper()} | {' | '.join(cells)} |")
    text.extend(["", "Possible slots include normal closures and holidays. This is not an estimate of in-session data loss.",
                 "", "## Decision coverage", "", "| Item | In-sample | Out-of-sample |", "|---|---:|---:|"])
    for key, label in (*COUNTS, (f"missing_{entry_tf.lower()}_decisions", f"Session slots missing {entry_tf}")):
        text.append(f"| {label} | {one.coverage[key]:,} | {two.coverage[key]:,} |")
    text.extend(["", "## Outcome summary", "", "| Item | In-sample | Out-of-sample |", "|---|---:|---:|"])
    for key, label in RESULTS:
        text.append(f"| {label} | {_display(key, metrics[0][key])} | {_display(key, metrics[1][key])} |")
    text.extend([
        "", "## Method and limits", "",
        "- Frozen strategy and execution rules; no fitting, optimization, or choice of settings based on results.",
        "- The calendar range is split chronologically at roughly 70/30, rounded down to a UTC date. Earlier candles can warm indicators; future candles cannot change earlier indicator values.",
        f"- Decisions use only closed {entry_tf} and {trend_tf} candles, the last bid/ask observation at or before that decision, and a calendar snapshot captured by then that covers the full news window.",
        "- Missing required price, news, or quote inputs are not replaced by assumptions. Pre-filter technical candidates are counted only to show where evidence was missing.",
        "- Orders first use the next minute's interval, never the confirmation candle. Outcomes stop at each fold boundary or the first missing M1 bar; open signals are not transferred between folds or assigned artificial closing returns.",
        f"- Execution is a bid-OHLC simulation with {spec['execution']['spread_price']} USD/oz fixed spread, "
        f"{spec['execution']['slippage_price_per_fill']} USD/oz adverse slippage per fill, and "
        f"{Decimal(spec['execution']['tp1_fraction']):.0%} sized at TP1. The measured spread filter is separate from this execution assumption.",
        "- Win rate and R use only completed trades with a finite result; expiry and unresolved records are not losses.",
        "", "## Inputs", "",
    ])
    if spec["experimental"]:
        text.insert(text.index("## Price coverage"), "**EXPERIMENTAL:** M5 is reconstructed from observed M1 bid bars. "
                    "The archive cannot establish tick order, true tradeable spread, or execution timing.\n")
    if entry_tf == "H4" or trend_tf == "D1":
        text.insert(text.index("## Price coverage"), "For HistData, H4/D1 need at least 180/1,320 source minutes; "
                    "shorter buckets were excluded. Such aggregates are not an independent guarantee against missing minutes.\n")
    text.extend(f"- {label}: `{description}`" for label, description in inputs.items())
    return "\n".join(text) + "\n"


def machine_report(
    folds: tuple[Fold, Fold], spec: dict[str, Any], feed: str, inputs: dict[str, str],
) -> dict[str, Any]:
    return {
        "mode": "BACKTEST", "strategy": spec, "data_source": feed, "inputs": inputs,
        "folds": [
            {"label": f.label, "start_utc": f.start, "end_utc_exclusive": f.end,
             "coverage": dict(f.coverage), "metrics": f.metrics(), "records": [
                 {**asdict(signal), **asdict(outcome), "unresolved_reason": reason}
                 for signal, outcome, reason in f.records
             ]}
            for f in folds
        ],
    }


def json_value(value: datetime | Decimal) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Unexpected report value: {type(value).__name__}")
