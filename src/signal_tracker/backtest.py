"""A two-fold, chronological BACKTEST; it never writes signal database records."""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pandas as pd

from .backtest_inputs import HistoricalCalendar, HistoricalQuotes
from .checker import Execution, advance
from .research_data import MinuteLookup
from .signal import TERMINAL, Outcome, Signal, Status
from .config import TIMEFRAMES
from .strategy_engine import prepare
from .trend_pullback import _session, spread_status


@dataclass
class Fold:
    label: str
    start: datetime
    end: datetime
    coverage: Counter[str] = field(default_factory=Counter)
    records: list[tuple[Signal, Outcome, str | None]] = field(default_factory=list)

    def metrics(self) -> dict[str, Any]:
        outcomes = [item[1] for item in self.records]
        resolved = [outcome.result_r for outcome in outcomes if outcome.result_r is not None]
        wins = sum(result > 0 for result in resolved)
        return {
            "signals": len(outcomes),
            "filled": sum(state.triggered_at is not None for state in outcomes),
            "expired": sum(state.status == Status.EXPIRED for state in outcomes),
            "unresolved": sum(state.status not in TERMINAL for state in outcomes),
            "missing_m1": sum(item[2] == "MISSING_M1" for item in self.records),
            "fold_cutoff": sum(item[2] == "FOLD_CUTOFF" for item in self.records),
            "closed": len(resolved),
            "wins": wins,
            "losses": sum(result < 0 for result in resolved),
            "flat": sum(result == 0 for result in resolved),
            "win_rate_closed": Decimal(wins) / len(resolved) if resolved else None,
            "average_r_closed": sum(resolved) / len(resolved) if resolved else None,
            "total_r_closed": sum(resolved) if resolved else None,
        }


def split_at(start: datetime, end: datetime) -> datetime:
    if (start.hour or start.minute or start.second or start.microsecond
            or end.hour or end.minute or end.second or end.microsecond):
        raise ValueError("Backtest dates must begin at midnight UTC")
    days = (end - start).days
    if days < 2:
        raise ValueError("Backtest needs at least two calendar days for two nonempty folds")
    return start + timedelta(days=days * 7 // 10)


def run(
    m1: pd.DataFrame, entry: pd.DataFrame, trend: pd.DataFrame, spec: dict[str, Any],
    start: datetime, end: datetime, recorded: datetime,
    calendar: HistoricalCalendar, quotes: HistoricalQuotes,
) -> tuple[Fold, Fold]:
    split = split_at(start, end)
    if end > recorded:
        raise ValueError("Backtest end cannot be in the future")
    entry_tf, trend_tf = spec["entry_timeframe"], spec["trend_timeframe"]
    entry_step, trend_step = TIMEFRAMES[entry_tf], TIMEFRAMES[trend_tf]
    feeds = {value for frame in (m1, entry, trend) for value in frame["data_source"].unique()}
    if len(feeds) != 1:
        raise ValueError("Execution and setup inputs must come from a single price feed")
    feed = next(iter(feeds))
    prepared = prepare(entry, trend, spec)
    model = Execution.from_config(spec["execution"])
    minute = MinuteLookup(m1)
    folds = Fold("In-sample", start, split), Fold("Out-of-sample", split, end)
    for fold in folds:
        issued: Counter = Counter()
        for label, frame, step in (("m1", m1, 1), (entry_tf.lower(), entry, entry_step),
                                   (trend_tf.lower(), trend, trend_step)):
            slots = int((fold.end - fold.start).total_seconds() // (step * 60))
            observed = int(((frame.index >= fold.start) & (frame.index < fold.end)).sum())
            fold.coverage[f"{label}_observed"] = observed
            fold.coverage[f"{label}_slots"] = slots

        available = set(prepared.mtime[(prepared.mtime >= fold.start) & (prepared.mtime < fold.end)])
        for bar_at in pd.date_range(fold.start, fold.end, freq=f"{entry_step}min", inclusive="left"):
            at = bar_at.to_pydatetime()
            session = _session(at, spec["session_filter"])
            if session is None:
                continue
            fold.coverage["session_decision_slots"] += 1
            if bar_at not in available:
                fold.coverage[f"missing_{entry_tf.lower()}_decisions"] += 1
                continue
            fold.coverage["observed_session_decisions"] += 1
            news = calendar.status(at, spec["news_filter"])
            spread = spread_status(quotes.as_of(at), at, spec["spread_filter"])
            fold.coverage[f"news_{news}"] += 1
            fold.coverage[f"spread_{spread}"] += 1
            filters_pass = news == "ok" and spread == "ok"
            fold.coverage["both_filters_pass"] += filters_pass
            decision = prepared.at(at, session)
            if decision.kind == "SKIP":
                fold.coverage[f"technical_skip:{decision.reason}"] += 1
            elif decision.kind == "PREPARE":
                fold.coverage["technical_prepare_before_filters"] += 1
            if decision.kind != "SIGNAL":
                continue
            fold.coverage["technical_candidates_before_filters"] += 1
            if not filters_pass:
                fold.coverage["technical_candidates_rejected_by_filters"] += 1
                continue
            if issued[at.date()] >= spec["max_signals_per_utc_day"]:
                fold.coverage["daily_cap_rejections"] += 1
                continue
            issued[at.date()] += 1
            if decision.levels is None or decision.direction is None or decision.setup_at != at:
                raise RuntimeError("A backtest decision must be tied to its closed entry candle")
            code = spec["strategy_code"]
            signal = Signal(
                str(uuid5(NAMESPACE_URL, f"signal-tracker/BACKTEST/{code}/{feed}/{at.isoformat()}")),
                code, spec["source"], spec["style"], spec["pair"], decision.direction, *decision.levels,
                at, at + timedelta(minutes=spec["expiry_minutes"]), feed, decision.reason,
                "BACKTEST", at, recorded,
            )
            state, missing = advance(signal, Outcome(), model, fold.end, minute)
            unresolved = None
            if state.status not in TERMINAL:
                unresolved = "MISSING_M1" if missing is not None else "FOLD_CUTOFF"
            fold.records.append((signal, state, unresolved))
    return folds
