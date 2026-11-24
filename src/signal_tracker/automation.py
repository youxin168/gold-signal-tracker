"""One bounded, prospective XAUUSD tick. Evidence gaps stop publication, not the website."""

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from . import biquote, parallel_targets, third_target
from .candles import CandleWindow, DataError, timestamp_utc
from .checker import Execution, advance, first_full_minute
from .config import TIMEFRAMES, load_object, load_strategies, market_for
from .phase2 import signal_for
from .research_data import MinuteLookup
from .scoreboard import Regimes
from .scoreboard_stats import ScoredSignal
from .signal import Outcome, now_utc, utc
from .sources import OANDA_SOURCE, fetch_oanda, fetch_practice_spread
from .store import from_record, open_records, publish, save_outcome, transaction
from .telegram import enqueue
from .strategy_engine import ARCHETYPES, decide
from .trend_pullback import SpreadQuote, _session

LOG = logging.getLogger(__name__)
REGIME_SQL = "CREATE TABLE IF NOT EXISTS signal_regimes (signal_id TEXT PRIMARY KEY REFERENCES signals, regime TEXT NOT NULL)"
EVIDENCE_SQL = """CREATE TABLE IF NOT EXISTS signal_evidence (
    signal_id TEXT PRIMARY KEY REFERENCES signals, quote_at TEXT NOT NULL,
    observed_spread TEXT NOT NULL, news_verified_at TEXT NOT NULL
)"""
GAPS_SQL = """CREATE TABLE IF NOT EXISTS signal_gaps (
    signal_id TEXT PRIMARY KEY REFERENCES signals, reason TEXT NOT NULL
)"""


def _reviewed_calendar(path: Path | None, at: datetime, rule: dict) -> dict | None:
    if path is None:
        return None
    document = load_object(path)
    reviewed = timestamp_utc(document["verified_at_utc"])
    first = timestamp_utc(document["coverage_start_utc"])
    last = timestamp_utc(document["coverage_end_utc"])
    if not timedelta(0) <= at - reviewed <= timedelta(hours=24):
        return None
    if not first <= at - timedelta(minutes=rule["minutes_after"]) or not at + timedelta(minutes=rule["minutes_before"]) < last:
        return None
    if not isinstance(document["source"], str) or not document["source"].strip():
        raise ValueError("Calendar needs a named source")
    return document


def _fetch(pair: str, instrument: str, start: datetime, end: datetime, frame: str):
    return fetch_oanda(pair, instrument, CandleWindow.create(utc(start), utc(end), frame))


def _check_existing(db: Path, pair: str, instrument: str, cutoff: datetime,
                    feed: str = OANDA_SOURCE) -> tuple[int, bool]:
    if not db.exists():
        return 0, False

    def eligible(connection):
        for kind, records in (("official", open_records(connection, "LIVE", cutoff)),
                              ("watch", third_target.open_watches(connection, cutoff)),
                              ("parallel", parallel_targets.records(connection, cutoff))):
            for raw in records:
                signal, official = from_record(raw)
                if signal.data_source == feed and signal.pair == pair:
                    state = (third_target.watch_outcome(raw) if kind == "watch" else
                             parallel_targets.read_plan(raw) if kind == "parallel" else official)
                    yield kind, raw, signal, state

    with transaction(db) as connection:
        connection.execute(third_target.SCHEMA)
        connection.execute(parallel_targets.SCHEMA)
        records = list(eligible(connection))
    end = cutoff.replace(second=0, microsecond=0)
    lookups: dict[datetime, MinuteLookup | None] = {}
    for _, _, signal, state in records:
        start = state.checked_until or first_full_minute(signal.issued_at_utc)
        if start >= end:
            continue
        bucket = end - timedelta(hours=6) if feed == biquote.SOURCE else start.replace(minute=0, second=0, microsecond=0)
        if bucket not in lookups:
            try:
                # An old unresolved gap must not prevent checking more recent records.
                minutes = (_window(pair, bucket, end, "M1") if feed == biquote.SOURCE else
                           _fetch(pair, instrument, bucket, min(end, bucket + timedelta(days=3)), "M1"))
                lookups[bucket] = MinuteLookup(minutes)
            except DataError as error:
                LOG.warning("Outcome check skipped an unavailable practice candle window: %s", error)
                lookups[bucket] = None
    changed, missing_bars = 0, False
    with transaction(db) as connection:
        connection.execute(GAPS_SQL)
        for kind, raw, signal, before in eligible(connection):
            start = before.checked_until or first_full_minute(signal.issued_at_utc)
            bucket = end - timedelta(hours=6) if feed == biquote.SOURCE else start.replace(minute=0, second=0, microsecond=0)
            lookup = lookups.get(bucket)
            actual_cutoff = min(cutoff, bucket + timedelta(days=3))
            if kind in {"watch", "parallel"}:
                parallel = kind == "parallel"
                gap_key = "plan_gap" if parallel else "watch_unresolved"
                result, reason = before, None
                if lookup is None and start < end:
                    reason = "No complete minute-candle check was available."
                else:
                    model = Execution.from_config(json.loads(raw["specification"])["execution"])
                    get_bar = lookup or (lambda _: None)
                    if parallel:
                        result, missing = parallel_targets.advance_plan(signal, before, model, actual_cutoff, get_bar)
                        ongoing = result.phase in {"PENDING", "ACTIVE"}
                    else:
                        result, missing = third_target.advance_watch(signal, before, Decimal(raw["target"]), model,
                                                                     actual_cutoff, get_bar)
                        ongoing = result.status in third_target.WATCHING
                    if missing is not None:
                        reason = f"Missing candle at {utc(missing)}."
                    elif actual_cutoff < cutoff and ongoing:
                        reason = "Recent minute candles have not been checked yet."
                missing_bars |= reason is not None
                if result != before or reason != raw[gap_key]:
                    if parallel:
                        parallel_targets.save(connection, signal.signal_id, result, reason)
                    else:
                        connection.execute(
                            """UPDATE tp3_watch SET state = ?, checked_until = ?, hit_at = ?, unresolved = ?
                               WHERE signal_id = ?""",
                            (result.status, utc(result.checked_until) if result.checked_until else None,
                             utc(result.closed_at) if result.status == "TP2" and result.closed_at else None,
                             reason, signal.signal_id),
                        )
                    changed += 1
                continue
            if lookup is None and start < end:
                missing_bars = True
                connection.execute("INSERT OR REPLACE INTO signal_gaps VALUES (?, ?)",
                                   (signal.signal_id, "No complete minute-candle check was available."))
                continue
            if actual_cutoff < cutoff:
                missing_bars = True
            result, missing = advance(signal, before, Execution.from_config(json.loads(raw["specification"])["execution"]),
                                      actual_cutoff, lookup or (lambda _: None))
            if missing is not None:
                missing_bars = True
                connection.execute("INSERT OR REPLACE INTO signal_gaps VALUES (?, ?)",
                                   (signal.signal_id, f"Missing candle at {utc(missing)}."))
                LOG.warning("Missing M1 coverage at %s; %s kept unresolved", utc(missing), signal.signal_id)
            elif actual_cutoff < cutoff and result.status in {"PENDING", "ACTIVE", "TP1", "TP2_OPEN"}:
                connection.execute("INSERT OR REPLACE INTO signal_gaps VALUES (?, ?)",
                                   (signal.signal_id, "Recent minute candles have not been checked yet."))
            else:
                connection.execute("DELETE FROM signal_gaps WHERE signal_id = ?", (signal.signal_id,))
            if result == before:
                continue
            save_outcome(connection, signal.signal_id, result)
            changed += 1
            if result.status != before.status:
                outcome = f" · {result.result_r:+.2f}R" if result.result_r is not None else ""
                enqueue(connection, f"{signal.signal_id}:{result.status}", signal.source, signal.style, result.status,
                        f"{signal.strategy_code} · {signal.direction}{outcome}\nID: {signal.signal_id}", cutoff)
    return changed, missing_bars


WARMUP_DAYS = {"M5": 4, "M15": 4, "H1": 28, "H4": 60, "D1": 450}


def _boundary(at: datetime, timeframe: str) -> datetime:
    midnight = at.replace(hour=0, minute=0, second=0, microsecond=0)
    step = TIMEFRAMES[timeframe]
    return midnight + timedelta(minutes=int((at - midnight).total_seconds() // 60) // step * step)


def _window(pair: str, start: datetime, end: datetime, timeframe: str):
    return biquote.candles(pair, CandleWindow.create(utc(start), utc(end), timeframe))


def _remember_h1(cache: Path, bars: pd.DataFrame) -> pd.DataFrame:
    from .public_snapshot import atomic_json

    if cache.exists():
        prior = pd.DataFrame(load_object(cache)["rows"])
        if not prior.empty:
            prior.index = pd.DatetimeIndex(pd.to_datetime(prior.pop("opened_at_utc"), utc=True))
            prior["closed_at_utc"] = pd.to_datetime(prior["closed_at_utc"], utc=True)
            bars = pd.concat([prior, bars])
            bars = bars.loc[~bars.index.duplicated(keep="last")].sort_index().tail(650)
    rows = bars.rename_axis("opened_at_utc").reset_index().to_dict("records")
    atomic_json(cache, {"rows": rows})
    return bars


def tick(config_dir: Path, db: Path, calendar_path: Path | None, codes: list[str] | None = None, *,
         feed: str = OANDA_SOURCE, cache: Path | None = None) -> dict[str, Any]:
    enabled: list[str] | None = None
    warmup: dict[str, dict[str, int]] = {}

    def status(state: str, message: str) -> dict:
        status = {"state": state, "message": message, "updated_at_utc": utc(now_utc())}
        if enabled is not None:
            status["enabled_strategy_codes"] = enabled
        if feed == biquote.SOURCE:
            status.update(data_source=feed, strategy_warmup=warmup)
        return status

    initial = now_utc().astimezone(UTC)
    token = os.environ.get("OANDA_API_TOKEN", "").strip()
    account = os.environ.get("OANDA_PRACTICE_ACCOUNT_ID", "").strip()
    public_feed = feed == biquote.SOURCE
    if not public_feed and not token:
        return status("not_configured", "OANDA practice is not configured. No live scan or outcome check ran.")
    pair, market = market_for("XAUUSD", config_dir)
    instrument = market["oanda_instrument"]
    registry = load_strategies(config_dir)
    retired = set(registry.get("retired_live_strategy_codes", []))
    specs = {row["strategy_code"]: row for row in registry["strategies"]
             if row.get("pair") == pair and row["version_state"] == "FROZEN" and row.get("implementation") in ARCHETYPES
             and row["strategy_code"] not in retired and row.get("live_feed", OANDA_SOURCE) == feed}
    if codes and set(codes) - set(specs):
        raise ValueError("The requested strategy does not have frozen automated rules")
    selected = [spec for code, spec in specs.items() if codes is None or code in codes]
    enabled = [spec["strategy_code"] for spec in selected]

    def record_hourly_warmup(have: int) -> None:
        for spec in selected:
            if spec["trend_timeframe"] != "H1":
                continue
            need = (spec.get("trend") or {}).get("ema_period", 0)
            if have < need:
                warmup[spec["strategy_code"]] = {"have": have, "need": need}
            else:
                warmup.pop(spec["strategy_code"], None)

    changed, gaps = (_check_existing(db, pair, instrument, initial, feed) if public_feed
                     else _check_existing(db, pair, instrument, initial))
    outcome_note = (f" {changed} outcome checkpoints updated." +
                    (" Some outcomes remain unresolved due to missing M1 coverage." if gaps else ""))
    if not public_feed and not account:
        return status("not_configured", "No practice account ID for observed spread. New publication is paused." + outcome_note)
    due = [spec for spec in selected
           if _session(initial, spec["session_filter"]) is not None
           and initial - _boundary(initial, spec["entry_timeframe"]) < timedelta(minutes=5)]
    try:
        # Retain closed H1 bars privately, even outside a strategy's session,
        # so a short upstream window does not require starting over.
        candles = {}
        if public_feed and cache is not None:
            try:
                if initial.weekday() < 5:
                    hour = _boundary(initial, "H1")
                    candles["H1"] = _remember_h1(cache, _window(pair, hour - timedelta(days=28), hour, "H1"))
                    record_hourly_warmup(len(candles["H1"]))
                elif cache.exists():
                    record_hourly_warmup(len(load_object(cache)["rows"]))
            except (ValueError, OSError, KeyError) as error:
                LOG.warning("Biquote H1 warm-up could not be saved: %s", error)
        if not due:
            return status("waiting", "No strategy has a session and fresh close due at this tick." + outcome_note)
        calendar = (biquote.calendar(initial, now_utc) if public_feed else
                    _reviewed_calendar(calendar_path, initial, due[0]["news_filter"]))
        if calendar is None:
            message = ("The Biquote news calendar could not be verified. No signals issued." if public_feed else
                       "No recent reviewed news calendar covers this decision. No signals issued.")
            return status("waiting", message + outcome_note)
        frames = {spec[key] for spec in due for key in ("entry_timeframe", "trend_timeframe")} | {"H1"}
        for tf in sorted(frames - candles.keys()):
            end = _boundary(initial, tf)
            try:
                start = end - timedelta(days=WARMUP_DAYS[tf])
                candles[tf] = _window(pair, start, end, tf) if public_feed else _fetch(pair, instrument, start, end, tf)
                if public_feed and tf == "H1":
                    record_hourly_warmup(len(candles[tf]))
            except DataError as error:
                LOG.warning("%s source candles unavailable: %s", tf, error)
        price, quote_time = biquote.spread() if public_feed else fetch_practice_spread(instrument, account, token)
        regimes = Regimes(candles["H1"]) if "H1" in candles else None
        messages, errors, published, prepared = [], 0, 0, 0
        for spec in due:
            code = spec["strategy_code"]
            entry, trend = spec["entry_timeframe"], spec["trend_timeframe"]
            if entry not in candles or trend not in candles:
                errors += 1
                messages.append(f"{code}: missing closed candles")
                continue
            with transaction(db) as connection:
                at = now_utc()
                checked_calendar = calendar if public_feed else _reviewed_calendar(calendar_path, at, spec["news_filter"])
                if checked_calendar != calendar:
                    messages.append(f"{code}: calendar changed or no longer covers the scan")
                    continue
                Execution.from_config(spec["execution"])
                if public_feed and code in warmup:
                    progress = warmup[code]
                    messages.append(f"{code}: warming up H1 history ({progress['have']}/{progress['need']} candles)")
                    continue
                decision = decide(candles[entry], candles[trend], spec, at, calendar=checked_calendar,
                                  quote=SpreadQuote(price, quote_time.to_pydatetime()))
                if decision.kind == "PREPARE":
                    enqueue(connection, f"{code}:{decision.setup_at}:PREPARE", spec["source"], spec["style"], "PREPARE",
                            f"{code} · {decision.direction}\nSetup forming; not an entry or a published signal.", at)
                    prepared += 1
                    continue
                if decision.levels is None:
                    messages.append(f"{code}: {decision.reason}")
                    continue
                signal = signal_for(decision, spec, feed, "LIVE", at, at)
                regime = regimes.label(ScoredSignal(signal, Outcome())) if regimes is not None else "Unknown"
                message = publish(connection, signal, spec)
                if message == "Published":
                    target = third_target.suggest(signal, candles[trend], trend, Decimal(spec["price_tick"]))
                    tp3 = signal.tp3 if signal.tp3 is not None else target
                    parallel_targets.create(connection, signal, tp3)
                    if target is not None:
                        connection.execute(third_target.SCHEMA)
                        connection.execute("INSERT INTO tp3_watch (signal_id, target) VALUES (?, ?)",
                                           (signal.signal_id, str(target)))
                    connection.execute(REGIME_SQL)
                    connection.execute("INSERT INTO signal_regimes VALUES (?, ?)", (signal.signal_id, regime))
                    connection.execute(EVIDENCE_SQL)
                    connection.execute("INSERT INTO signal_evidence VALUES (?, ?, ?, ?)",
                                       (signal.signal_id, quote_time.isoformat(), str(price),
                                        timestamp_utc(calendar["verified_at_utc"]).isoformat()))
                    enqueue(connection, f"{signal.signal_id}:PENDING", signal.source, signal.style, "PENDING",
                            f"{code} · {signal.direction}\nEntry {signal.entry} · SL {signal.sl}\n"
                            f"TP1 {signal.tp1} · TP2 {signal.tp2} · TP3 {tp3 if tp3 is not None else 'None'}\n"
                            f"Expires {utc(signal.expires_at_utc)} · ID: {signal.signal_id}", at)
                    published += 1
                else:
                    messages.append(f"{code}: {message}")
        summary = ("Recorded one new prospective signal." if published == 1 else
                   f"Recorded {published} new prospective signals." if published else "No new signal.")
        if prepared:
            summary += f" {prepared} PREPARE setup(s)."
        if messages:
            summary += " " + "; ".join(messages) + "."
        return status("error" if errors else "ready", summary + outcome_note)
    except (KeyError, ValueError, OSError) as error:
        LOG.warning("Prospective scan skipped (%s); no signal fabricated.", type(error).__name__)
        return status("error", "Market data, strategy config or the news calendar interrupted the scan. "
                      "Already recorded signals were retained." + outcome_note)
