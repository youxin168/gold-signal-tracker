"""Telegram HTML for newly published gold signals."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html import escape

from .parallel_targets import TargetPlan, target_order_r
from .signal import Outcome, Signal, Status, TERMINAL

ICT = timezone(timedelta(hours=7), "ICT")
PIP = Decimal("0.01")
STYLES = {"SCA": "SCALPING", "INT": "INTRADAY", "SWG": "SWING"}


def _price_code(price: Decimal) -> str:
    return f"<code>{price:f}</code>"


def _time_ict(value: datetime) -> str:
    return f"{value.astimezone(ICT):%d %b %H:%M} ICT"


def _title(signal: Signal, label: str) -> str:
    return f"<b>{escape(signal.pair)} {escape(signal.direction)} · {label}</b>"


def format_new_signal(signal: Signal, strategy_name: str, suggested_tp3: Decimal | None = None) -> str:
    """Wrap each raw price separately so readers can copy just that price."""
    risk = abs(signal.entry - signal.sl)
    target3 = signal.tp3 if signal.tp3 is not None else suggested_tp3
    style = STYLES.get(signal.style, signal.style)

    lines = [
        _title(signal, escape(style)),
        f"{escape(strategy_name)} · New signal (entry unconfirmed at issue)",
        "",
        f"Side: <b>{escape(signal.direction)}</b>",
        f"Entry: {_price_code(signal.entry)}",
        f"SL: {_price_code(signal.sl)} · {risk / PIP:,.0f} pips risk",
    ]
    for number, target in enumerate((signal.tp1, signal.tp2, target3), 1):
        if target is None:
            lines.append(f"TP{number}: None")
            continue
        distance = abs(target - signal.entry)
        lines.append(f"TP{number}: {_price_code(target)} · {distance / PIP:,.0f} pips · {distance / risk:.2f}R")
    lines += [
        "",
        f"Issued: {_time_ict(signal.issued_at_utc)}",
        f"Entry expires: {_time_ict(signal.expires_at_utc)}",
        "Planned distances before costs · Signal Tracker · Testing only",
    ]
    return "\n".join(lines)


def format_trade_result(signal: Signal, strategy_name: str, outcome: Outcome) -> str | None:
    """Return only a confirmed final result, never a partial or fabricated trade."""
    result = outcome.result_r
    if outcome.closed_at is None or outcome.status not in TERMINAL | {Status.EXPIRED}:
        return None
    if outcome.status is Status.EXPIRED:
        label = "EXPIRED"
        detail = f"Entry {_price_code(signal.entry)} was not reached before expiry."
        summary = "<b>Not filled · No R result</b>"
    else:
        if result is None:
            return None
        summary = f"<b>Trade result: {result:+.2f}R</b> · with modeled costs"
        if outcome.status is Status.TP2:
            label, detail = "CLOSED AT TP2", f"TP2 {_price_code(signal.tp2)} hit."
        elif outcome.status is Status.TP3 and signal.tp3 is not None:
            label, detail = "CLOSED AT TP3", f"TP3 {_price_code(signal.tp3)} hit."
        elif outcome.status is Status.SL:
            label, detail = "STOP-LOSS HIT", f"Original SL {_price_code(signal.sl)} hit."
        elif outcome.status is Status.BE:
            label = "CLOSED AFTER TP1"
            detail = f"TP1 hit; the remainder stopped at breakeven {_price_code(signal.entry)}."
        else:
            return None
    return "\n".join([
        _title(signal, label), escape(strategy_name), "", detail, summary, "",
        f"Closed: {_time_ict(outcome.closed_at)}", "Signal Tracker · Testing only",
    ])


def format_data_gap(signal: Signal, strategy_name: str, checkpoint: datetime, scope: str) -> str:
    return "\n".join([
        _title(signal, "RESULT UNCONFIRMED"),
        escape(strategy_name), "",
        f"{scope}: price history is missing or incomplete.",
        f"Last covered through: {_time_ict(checkpoint)}",
        "TP / SL and the current position cannot be confirmed beyond that time.",
        "No win or loss is recorded for the unconfirmed result.",
        "A final result will follow only if complete price coverage is recovered.",
        "", "Signal Tracker · Testing only",
    ])


def format_fixed_result(signal: Signal, strategy_name: str, plan: TargetPlan) -> str | None:
    if plan.phase != "CLOSED" or plan.checked_until is None or not plan.targets:
        return None
    lines = [
        _title(signal, "FIXED-SL FINAL RESULT"),
        f"{escape(strategy_name)} · Original SL {_price_code(signal.sl)}",
        "",
    ]
    total = Decimal(0)
    for index, (target, status) in enumerate(zip(plan.targets, plan.statuses, strict=True), 1):
        value = target_order_r(signal.entry, signal.sl, target, status)
        if value is None:
            return None
        total += value
        detail = f"{_price_code(target)} hit" if status == "TP" else f"stopped at {_price_code(signal.sl)}"
        lines.append(f"TP{index} order: {detail} · <b>{value:+.2f}R</b>")
    lines += [
        "",
        f"<b>Combined: {total:+.2f}R</b> · {total / len(plan.targets):+.2f}R vs. total starting risk",
        f"Closed: {_time_ict(plan.checked_until)}",
        "Before costs · Separate simulation · Signal Tracker · Testing only",
    ]
    return "\n".join(lines)
