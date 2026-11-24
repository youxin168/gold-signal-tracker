"""Shared conservative evaluator; independent of strategy, style, and source."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Callable

from .signal import TERMINAL, Outcome, Signal, Status

MINUTE = timedelta(minutes=1)


@dataclass(frozen=True)
class Execution:
    spread: Decimal
    slippage: Decimal
    tp1_fraction: Decimal
    midpoint: bool = False
    tp2_fraction: Decimal | None = None

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "Execution":
        if config["method"] not in {"bid_ohlc_v1", "mid_ohlc_v1"} or config["timeframe"] != "M1":
            raise ValueError("Unsupported execution model")
        model = cls(*(Decimal(config[key]) for key in
                      ("spread_price", "slippage_price_per_fill", "tp1_fraction")),
                    midpoint=config["method"] == "mid_ohlc_v1",
                    tp2_fraction=Decimal(config["tp2_fraction"]) if "tp2_fraction" in config else None)
        if (not all(value.is_finite() for value in (model.spread, model.slippage, model.tp1_fraction))
                or min(model.spread, model.slippage) < 0 or not 0 < model.tp1_fraction < 1):
            raise ValueError("Invalid spread, slippage or TP1 sizing")
        if model.tp2_fraction is not None and (not model.tp2_fraction.is_finite()
                or not 0 < model.tp2_fraction < 1 - model.tp1_fraction):
            raise ValueError("TP2 sizing must leave a positive portion for TP3")
        return model


@dataclass(frozen=True)
class Bar:
    opened: datetime
    open: Decimal
    high: Decimal
    low: Decimal

    @property
    def closed(self) -> datetime:
        return self.opened + MINUTE


def first_full_minute(issued: datetime) -> datetime:
    floor = issued.replace(second=0, microsecond=0)
    return floor if issued == floor else floor + MINUTE


def quote_offsets(direction: str, model: Execution) -> tuple[Decimal, Decimal]:
    """Offsets from the source candle to the entry and exit quote sides."""
    buy = direction == "BUY"
    if model.midpoint:
        half = model.spread / 2
        return (half, -half) if buy else (-half, half)
    return (model.spread, Decimal(0)) if buy else (Decimal(0), model.spread)


def expire_if_due(signal: Signal, state: Outcome, as_of: datetime) -> Outcome:
    """Expire only after all fully eligible minutes have been checked."""
    if state.status != Status.PENDING or as_of < signal.expires_at_utc:
        return state
    deadline = signal.expires_at_utc.replace(second=0, microsecond=0)
    if (state.checked_until or first_full_minute(signal.issued_at_utc)) >= deadline:
        return replace(state, status=Status.EXPIRED, closed_at=signal.expires_at_utc)
    return state


def advance(
    signal: Signal, state: Outcome, model: Execution, as_of: datetime,
    get_bar: Callable[[datetime], Bar | None],
) -> tuple[Outcome, datetime | None]:
    """Advance up to a cutoff or stop at the first unobserved eligible minute."""
    expected = state.checked_until or first_full_minute(signal.issued_at_utc)
    missing = None
    while state.status not in TERMINAL and expected + MINUTE <= as_of:
        if state.status == Status.PENDING and expected + MINUTE > signal.expires_at_utc:
            break
        candle = get_bar(expected)
        if candle is None:
            missing = expected
            break
        state = on_bar(signal, state, candle, model)
        expected += MINUTE
    return expire_if_due(signal, state, as_of), missing


def on_bar(signal: Signal, state: Outcome, bar: Bar, model: Execution) -> Outcome:
    """Apply exactly one fully closed, consecutive M1 bar."""
    if state.status in TERMINAL:
        return state
    expected = state.checked_until or first_full_minute(signal.issued_at_utc)
    if bar.opened != expected:
        raise ValueError(f"Expected M1 bar at {expected.isoformat()}; cannot skip a gap")
    if state.status == Status.PENDING and bar.closed > signal.expires_at_utc:
        return expire_if_due(signal, state, bar.closed)
    state = replace(state, checked_until=bar.closed)
    buy = signal.direction == "BUY"
    entry_offset, exit_offset = quote_offsets(signal.direction, model)
    just_filled = False
    if state.status == Status.PENDING:
        if not bar.low + entry_offset <= signal.entry <= bar.high + entry_offset:
            return state
        state = replace(state, status=Status.ACTIVE, triggered_at=bar.closed)
        just_filled = True

    low, high, opening = (value + exit_offset for value in (bar.low, bar.high, bar.open))
    # SL and targets are executable-side quotes. Apply adverse slippage at each
    # entry and exit; a gap through a stop can cost more than one planned R.
    sign = 1 if buy else -1
    risk = abs(signal.entry - signal.sl)

    def leg(price: Decimal) -> Decimal:
        return (sign * (price - signal.entry) - 2 * model.slippage) / risk

    def close(status: Status, result: Decimal) -> Outcome:
        return replace(state, status=status, closed_at=bar.closed, result_r=result)

    fraction = model.tp1_fraction
    taken_tp2 = state.status == Status.TP2_OPEN
    taken_tp1 = state.status in (Status.TP1, Status.TP2_OPEN)
    second = model.tp2_fraction
    if (signal.tp3 is None) != (second is None):
        raise ValueError("A TP3 signal requires its frozen three-target execution model")
    stop = signal.entry if taken_tp1 else signal.sl
    if (low <= stop if buy else high >= stop):
        exit_price = stop if just_filled else (min(stop, opening) if buy else max(stop, opening))
        if taken_tp1:
            second_paid = second if taken_tp2 and second is not None else Decimal(0)
            return close(Status.BE, fraction * leg(signal.tp1) + second_paid * leg(signal.tp2)
                         + (1 - fraction - second_paid) * leg(exit_price))
        return close(Status.SL, leg(exit_price))
    if just_filled:  # A target touch could have happened before the entry.
        return state
    def reached(target: Decimal) -> bool:
        return high >= target if buy else low <= target

    if signal.tp3 is not None and second is not None and reached(signal.tp3):
        state = replace(state, tp1_at=state.tp1_at or bar.closed, tp2_at=state.tp2_at or bar.closed)
        return close(Status.TP3, fraction * leg(signal.tp1) + second * leg(signal.tp2)
                     + (1 - fraction - second) * leg(signal.tp3))
    if reached(signal.tp2):
        if second is not None:
            return replace(state, status=Status.TP2_OPEN, tp1_at=state.tp1_at or bar.closed,
                           tp2_at=state.tp2_at or bar.closed)
        state = replace(state, tp1_at=state.tp1_at or bar.closed)
        return close(Status.TP2, fraction * leg(signal.tp1) + (1 - fraction) * leg(signal.tp2))
    if not taken_tp1 and reached(signal.tp1):
        return replace(state, status=Status.TP1, tp1_at=bar.closed)
    return state
