"""Command line workflows for prospective scans and separately labeled replays."""

import argparse
import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from .candles import timestamp_utc
from .checker import Execution, advance
from .config import load_object, load_strategies
from .research_data import MinuteLookup, read_bars
from .signal import Signal, now_utc
from .sources import OANDA_SOURCE
from .store import freeze, from_record, open_records, publish, save_outcome, transaction
from .strategy_engine import decide
from .trend_pullback import CODE, Decision, SpreadQuote

LOG = logging.getLogger(__name__)
DEFAULT_DB = Path("generated-artifacts/signals.db")


def signal_for(decision: Decision, spec: dict, feed: str, mode: str,
               decision_at: datetime, recorded: datetime) -> Signal:
    if decision.levels is None or decision.direction is None or decision.setup_at is None:
        raise ValueError("Only confirmed entries are signals")
    code, pair = spec["strategy_code"], spec["pair"]
    signal_id = str(uuid5(NAMESPACE_URL, f"signal-tracker/{code}/{pair}/{mode}/{decision.setup_at.isoformat()}"))
    entry, sl, tp1, tp2, *extra = decision.levels
    return Signal(signal_id, code, spec["source"], spec["style"], pair, decision.direction,
                  entry, sl, tp1, tp2, decision_at, decision_at + timedelta(minutes=spec["expiry_minutes"]),
                  feed, f"{decision.reason}; testing only; closed {spec['entry_timeframe']}/{spec['trend_timeframe']} setup",
                  mode, decision.setup_at, recorded, tp3=extra[0] if extra else None)


def add_commands(commands: argparse._SubParsersAction) -> None:
    scan = commands.add_parser("scan", help="Evaluate one frozen XAUUSD rules-based strategy")
    scan.add_argument("--strategy", default=CODE)
    for tf in ("m5", "m15", "h1", "h4", "d1"):
        scan.add_argument(f"--{tf}", type=Path, help=f"Closed {tf.upper()} candle export")
    scan.add_argument("--calendar", type=Path, help="JSON calendar with explicit time coverage")
    scan.add_argument("--spread", help="Observed ask minus bid in USD per troy ounce")
    scan.add_argument("--spread-at", help="UTC timestamp of the spread observation")
    scan.add_argument("--replay-as-of", help="Historical decision time; never recorded as LIVE")
    check = commands.add_parser("check", help="Advance stored outcomes using closed XAUUSD M1 bars")
    check.add_argument("--m1", required=True, type=Path, help="Phase 1 M1 candle CSV")
    check.add_argument("--replay-as-of", help="Only check REPLAY signals up to this historical instant")
    listing = commands.add_parser("signals", help="List stored signals and outcomes as JSON lines")
    listing.add_argument("--mode", choices=("LIVE", "REPLAY"), default="LIVE")
    for command in (scan, check, listing):
        command.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"Default: {DEFAULT_DB}")


def _scan(args: argparse.Namespace) -> None:
    spec = next((spec for spec in load_strategies(args.config_dir)["strategies"] if spec["strategy_code"] == args.strategy), None)
    if spec is None or spec["version_state"] != "FROZEN" or spec.get("implementation") == "manual_v1":
        raise ValueError("Choose a frozen rules-based strategy")
    if spec["execution"]["method"] == "mid_ohlc_v1":
        raise ValueError("Run Biquote versions with scheduled-tick --feed biquote; bid CSVs do not match their execution model")
    Execution.from_config(spec["execution"])
    frames = [spec["entry_timeframe"], spec["trend_timeframe"]]
    paths = [getattr(args, tf.lower(), None) for tf in frames]
    if not all(paths):
        raise ValueError(f"Supply the {frames[0]} and {frames[1]} candle exports")
    entry, trend = (read_bars(path, tf) for path, tf in zip(paths, frames))
    feed = entry["data_source"].iloc[0]
    if trend["data_source"].iloc[0] != feed:
        raise ValueError("Entry and trend inputs must use the same data source")
    mode = "REPLAY" if args.replay_as_of else "LIVE"
    if mode == "LIVE" and feed != OANDA_SOURCE:
        raise ValueError("LIVE scans require OANDA practice data; use --replay-as-of for archive files")
    if (args.spread is None) != (args.spread_at is None):
        raise ValueError("Provide both --spread and --spread-at")
    spread = (
        SpreadQuote(Decimal(args.spread), timestamp_utc(args.spread_at).to_pydatetime())
        if args.spread_at is not None else None
    )
    calendar = load_object(args.calendar) if args.calendar else None
    with transaction(args.db) as connection:
        freeze(connection, spec)
        recorded = now_utc()
        decision_at = timestamp_utc(args.replay_as_of).to_pydatetime() if args.replay_as_of else recorded
        if decision_at > recorded:
            raise ValueError("Replay decision time cannot be in the future")
        decision = decide(entry, trend, spec, decision_at, calendar=calendar, quote=spread)
        if decision.levels is None or decision.direction is None or decision.setup_at is None:
            print(f"{mode} {decision.kind}: {decision.reason}")
            return
        signal = signal_for(decision, spec, feed, mode, decision_at, recorded)
        message = publish(connection, signal, spec)
        if message == "Published":
            print(f"{mode} PENDING {signal.signal_id} {signal.direction} entry={signal.entry} "
                  f"SL={signal.sl} TP1={signal.tp1} TP2={signal.tp2}")
        else:
            print(f"{mode} SKIP: {message}")


def _check(args: argparse.Namespace) -> None:
    bars = read_bars(args.m1, "M1")
    feed = bars["data_source"].iloc[0]
    mode = "REPLAY" if args.replay_as_of else "LIVE"
    now = now_utc()
    as_of = timestamp_utc(args.replay_as_of).to_pydatetime() if args.replay_as_of else now
    if as_of > now:
        raise ValueError("Outcome cutoff cannot be in the future")
    lookup = MinuteLookup(bars)
    with transaction(args.db) as connection:
        records = open_records(connection, mode, as_of)
        for record in records:
            signal, before = from_record(record)
            if signal.data_source != feed:
                LOG.warning("%s: skipping different feed (%s)", signal.signal_id, signal.data_source)
                continue
            policy = Execution.from_config(json.loads(record["specification"])["execution"])
            state, missing = advance(signal, before, policy, as_of, lookup)
            if missing is not None:
                LOG.warning("%s: missing M1 candle at %s; kept unresolved", signal.signal_id, missing.isoformat())
            if state != before:
                save_outcome(connection, signal.signal_id, state)
            result = f" result_r={state.result_r}" if state.result_r is not None else ""
            print(f"{mode} {state.status} {signal.signal_id}{result}")
        if not records:
            print(f"{mode}: no unresolved eligible signals")


def run_phase2(args: argparse.Namespace) -> None:
    if args.command == "scan":
        try:
            _scan(args)
        except InvalidOperation as error:
            raise ValueError("Invalid decimal in strategy or spread inputs") from error
    elif args.command == "check":
        _check(args)
    else:
        with transaction(args.db) as connection:
            rows = connection.execute(
                "SELECT * FROM signal_records WHERE mode = ? ORDER BY issued_at_utc, signal_id", (args.mode,)
            )
            for row in rows:
                print(json.dumps(dict(row)))
