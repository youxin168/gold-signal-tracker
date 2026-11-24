"""Build strategy/style scorecards and same-style rankings for a single cohort."""

import json
from dataclasses import dataclass, field
from datetime import UTC, timedelta
from decimal import Decimal
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd

from .analyst import analyze
from .indicators import adx
from .scoreboard_stats import ScoredSignal, summarize

STYLES = ("SCA", "INT", "SWG")
MIN_RANK_SAMPLE = 100
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
SESSION_LABELS = ("Asia", "London", "New York", "Other")
LONDON, NEW_YORK = ZoneInfo("Europe/London"), ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Cohort:
    mode: str
    pair: str
    data_source: str | None
    strategies: dict[str, dict[str, Any]]
    records: list[ScoredSignal]
    fold: str | None = None
    start_utc: str | None = None
    end_utc_exclusive: str | None = None
    coverage: dict[str, dict[str, int]] = field(default_factory=dict)
    note: str | None = None
    regime_input: str | None = None


class Regimes:
    """Research labels from the most recent already-closed H1 ADX(14)."""

    def __init__(self, candles: pd.DataFrame):
        self.feed = candles["data_source"].iloc[0]
        self.closed = pd.DatetimeIndex(candles["closed_at_utc"])
        self.values = adx(candles).to_numpy()

    def label(self, row: ScoredSignal) -> str:
        at = row.signal.issued_at_utc
        i = self.closed.searchsorted(at, side="right") - 1
        if (self.feed != row.signal.data_source or i < 0 or at - self.closed[i] >= timedelta(hours=1)
                or pd.isna(self.values[i])):
            return "Unknown"
        return "Trending" if self.values[i] >= 25 else "Ranging"


def session(row: ScoredSignal) -> str:
    at = row.signal.issued_at_utc
    utc = at.astimezone(UTC)
    for name, zone in (("London", LONDON), ("New York", NEW_YORK)):
        local = at.astimezone(zone)
        if local.weekday() < 5 and 8 <= local.hour < 17:
            return name
    if utc.weekday() < 5 and utc.hour < 7:
        return "Asia"
    return "Other"


def _breakdowns(rows: list[ScoredSignal]) -> dict[str, dict]:
    buckets = {
        "session": {label: [] for label in SESSION_LABELS},
        "weekday_utc": {label: [] for label in WEEKDAYS},
        "direction": {label: [] for label in ("BUY", "SELL")},
        "market_regime": {label: [] for label in ("Trending", "Ranging", "Unknown")},
    }
    for row in rows:
        buckets["session"][session(row)].append(row)
        buckets["weekday_utc"][WEEKDAYS[row.signal.issued_at_utc.astimezone(UTC).weekday()]].append(row)
        buckets["direction"][row.signal.direction].append(row)
        buckets["market_regime"][row.regime].append(row)
    return {key: {label: summarize(group, equity=False) for label, group in values.items()}
            for key, values in buckets.items()}


def _rank_key(metrics: dict[str, Any]) -> tuple:
    # Win rate is displayed last, never used to break ties. A factor without
    # losses is unbounded only when there are positive returns.
    factor_order = {"not_estimable": 0, "finite": 1, "no_losses": 2}
    return (-metrics["total_r"], -metrics["expectancy_r"], metrics["max_drawdown_r"],
            -factor_order[metrics["profit_factor_status"]], -(metrics["profit_factor"] or Decimal(0)))


def _rank(cards: Iterable[dict[str, Any]], specifications: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    cards = list(cards)
    manual = {card["strategy_code"] for card in cards
              if specifications[card["strategy_code"]].get("implementation") == "manual_v1"}
    for card in cards:
        if card["strategy_code"] in manual:
            card["rank_reason"] = "Manual signal eligibility is not verified against automatic rules"
    eligible = sorted((card for card in cards if card["metrics"]["completed"] >= MIN_RANK_SAMPLE
                       and card["strategy_code"] not in manual),
                      key=lambda card: (_rank_key(card["metrics"]), card["strategy_code"]))
    shared_fields = ("execution", "news_filter", "spread_filter")
    comparable = len({json.dumps([specifications[card["strategy_code"]].get(field) for field in shared_fields],
                                 sort_keys=True) for card in eligible}) <= 1
    if not comparable:
        for card in eligible:
            card["rank_reason"] = "Execution assumptions differ across usable strategies"
        return sorted(cards, key=lambda card: card["strategy_code"])
    previous_key = None
    position = None
    for i, card in enumerate(eligible, 1):
        key = _rank_key(card["metrics"])
        if key != previous_key:
            position = i
        previous_key = key
        if len(eligible) > 1:
            card["rank"] = position
            card["rank_reason"] = None
        else:
            card["rank_reason"] = "No other usable strategy in the same style and evidence scope"
    ineligible = sorted((card for card in cards if card["metrics"]["completed"] < MIN_RANK_SAMPLE
                         or card["strategy_code"] in manual),
                        key=lambda card: card["strategy_code"])
    return eligible + ineligible


def build(cohort: Cohort) -> dict[str, Any]:
    grouped: dict[str, list[ScoredSignal]] = {code: [] for code in cohort.strategies}
    seen = set()
    for row in cohort.records:
        signal = row.signal
        if signal.signal_id in seen:
            raise ValueError(f"Duplicate signal in scoreboard scope: {signal.signal_id}")
        seen.add(signal.signal_id)
        if (signal.mode != cohort.mode or signal.pair != cohort.pair or signal.data_source != cohort.data_source
                or signal.strategy_code not in grouped):
            raise ValueError(f"Signal is incompatible with scoreboard scope: {signal.signal_id}")
        grouped[signal.strategy_code].append(row)
    cards = []
    for code, spec in cohort.strategies.items():
        rows = grouped[code]
        metrics, breakdowns = summarize(rows), _breakdowns(rows)
        coverage = cohort.coverage.get(code)
        cards.append({
            "strategy_code": code, "name": spec["name"], "source": spec["source"], "style": spec["style"],
            "version_state": spec["version_state"], "metrics": metrics, "breakdowns": breakdowns,
            "coverage": coverage,
            "analyst": analyze(rows, metrics, breakdowns["session"], coverage),
            "rank": None, "rank_reason": f"Fewer than {MIN_RANK_SAMPLE} completed trades",
        })
    styles, ordered = [], []
    for style in STYLES:
        ranked = _rank((card for card in cards if card["style"] == style), cohort.strategies)
        style_rows = [row for card in ranked for row in grouped[card["strategy_code"]]]
        ordered.extend(ranked)
        styles.append({"style": style, "strategies": [card["strategy_code"] for card in ranked],
                       "metrics": summarize(style_rows), "breakdowns": _breakdowns(style_rows)})
    return {
        "mode": cohort.mode, "pair": cohort.pair, "fold": cohort.fold, "data_source": cohort.data_source,
        "start_utc": cohort.start_utc, "end_utc_exclusive": cohort.end_utc_exclusive,
        "note": cohort.note, "regime_input": cohort.regime_input, "minimum_rank_sample": MIN_RANK_SAMPLE,
        "ranking_policy": ["total_r_desc", "expectancy_r_desc", "max_drawdown_r_asc", "profit_factor_desc"],
        "strategies": ordered, "styles": styles,
    }
