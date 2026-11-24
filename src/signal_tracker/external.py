"""Operator-only registration and immutable publication for external signals."""

import argparse
import csv
import math
import re
from collections import Counter
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .candles import timestamp_utc
from .config import STRATEGY_CODE, load_object, load_strategies
from .phase2 import DEFAULT_DB
from .public_snapshot import atomic_json
from .signal import Signal, now_utc
from .sources import HISTDATA_SOURCE, OANDA_SOURCE
from .store import publish, transaction
from .telegram import enqueue

EXTERNAL_SOURCES = {"EXT1", "EXT2", "OWN"}
DEFAULT_FRAMES = {"SCA": ("M5", "M15"), "INT": ("M15", "H1"), "SWG": ("H4", "D1")}
CSV_FIELDS = {"external_id", "strategy_code", "direction", "entry", "sl", "tp1", "tp2", "issued_at_utc"}
EXTERNAL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
IMPORT_SQL = """CREATE TABLE IF NOT EXISTS external_signal_ids (
    strategy_code TEXT NOT NULL, mode TEXT NOT NULL, external_id TEXT NOT NULL,
    signal_id TEXT NOT NULL REFERENCES signals, PRIMARY KEY(strategy_code, mode, external_id)
)"""


def _positive_int(value: Any, limit: int, field: str) -> int:
    if type(value) is not int or not 1 <= value <= limit:
        raise ValueError(f"{field} must be an integer from 1 to {limit}")
    return value


def _number(value: Any, field: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 20:
        raise ValueError(f"{field} must be a finite number in (0, 20]")
    return value


def register(config_dir: Path, input_path: Path) -> str:
    path = config_dir / "strategies.json"
    raw, data = load_object(path), load_object(input_path)
    if set(data) - {"strategy_code", "name", "template", "parameters", "public_rules"}:
        raise ValueError("Unknown external strategy fields; see the README format")
    code = data.get("strategy_code", "")
    match = STRATEGY_CODE.fullmatch(code) if isinstance(code, str) else None
    if not match or match[1] not in EXTERNAL_SOURCES:
        raise ValueError("Use an EXT1, EXT2, or OWN strategy code with style and version")
    source, style = match.groups()
    registry = {spec["strategy_code"]: spec for spec in load_strategies(config_dir)["strategies"]}
    if code in registry:
        raise ValueError("This strategy version already exists; register a new version for rule changes")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 80:
        raise ValueError("Provide a strategy name of 1–80 characters")
    overrides = data.get("parameters", {})
    if not isinstance(overrides, dict):
        raise ValueError("Strategy parameters must be a JSON object")
    template = data.get("template")
    if not isinstance(template, str):
        raise ValueError("Set template to 'manual' or a supported CLD code")
    if template == "manual":
        if set(overrides) - {"expiry_minutes", "max_signals_per_utc_day"}:
            raise ValueError("Manual strategy parameters only accept expiry and daily cap")
        entry, trend = DEFAULT_FRAMES[style]
        defaults = raw["xauusd_defaults"]
        spec = {"implementation": "manual_v1", "entry_timeframe": entry, "trend_timeframe": trend,
                "expiry_minutes": 240, "max_signals_per_utc_day": 2, "take_profit_r": [],
                "execution": defaults["execution"], "price_tick": defaults["price_tick"]}
        description = ["Entries, stops, and targets are supplied by the publisher, not computed by the tracker.",
                       "The tracker records first publication time and applies the shared XAUUSD outcome model.",
                       "Manual setup eligibility is not verified like an automated rule and is not ranked against it."]
    else:
        base = registry.get(template)
        if not base or base["source"] != "CLD" or base["style"] != style:
            raise ValueError("Choose an implemented CLD template for the same style")
        spec = base.copy()
        supported = {"expiry_minutes", "max_signals_per_utc_day", "take_profit_r"}
        if "atr_multiple" in spec["stop"]:
            supported.add("atr_multiple")
        if "lookback_closed_candles" in spec["setup"]:
            supported.add("lookback_closed_candles")
        if set(overrides) - supported:
            raise ValueError("Parameters not supported by this template: " + ", ".join(sorted(set(overrides) - supported)))
        description = [f"Uses the {base['name']} rule template ({template}).",
                       "Same setup, sessions, news/spread gates and execution model except for the explicit parameters below."]
        if "atr_multiple" in overrides:
            value = _number(overrides["atr_multiple"], "atr_multiple")
            spec["stop"] = spec["stop"] | {"atr_multiple": value}
            description.append(f"Stop ATR multiplier: {value:g}.")
        if "lookback_closed_candles" in overrides:
            value = _positive_int(overrides["lookback_closed_candles"], 120, "lookback_closed_candles")
            spec["setup"] = spec["setup"] | {"lookback_closed_candles": value}
            description.append(f"Closed-candle lookback: {value}.")
        if "take_profit_r" in overrides:
            targets = overrides["take_profit_r"]
            if not isinstance(targets, list) or len(targets) != 2:
                raise ValueError("take_profit_r needs two increasing positive R multiples")
            low, high = (_number(n, "take_profit_r") for n in targets)
            if low >= high:
                raise ValueError("take_profit_r needs increasing targets")
            spec["take_profit_r"] = [low, high]
    for key, cap in (("expiry_minutes", 10080), ("max_signals_per_utc_day", 24)):
        if key in overrides:
            spec[key] = _positive_int(overrides[key], cap, key)
    extra = data.get("public_rules", [])
    if not isinstance(extra, list) or len(extra) > 12 or any(
        not isinstance(line, str) or not line.strip() or len(line) > 320 for line in extra
    ):
        raise ValueError("public_rules must be a list of up to 12 short descriptive strings")
    spec.update({"strategy_code": code, "source": source, "style": style, "name": name.strip(),
                 "pair": "XAUUSD", "version_state": "FROZEN", "experimental": style == "SCA",
                 "public_rules": description + extra})
    raw["strategies"].append(spec)
    # Update a dedicated config file, never rewrite or reinterpret an existing version.
    atomic_json(path, raw, public=True, pretty=True)
    return code


def import_csv(config_dir: Path, db: Path, file: Path, mode: str, feed: str, confirm: bool) -> tuple[int, int]:
    if mode == "LIVE" and (feed != OANDA_SOURCE or not confirm):
        raise ValueError("LIVE requires the OANDA practice feed and --confirm-new-publication")
    specs = {spec["strategy_code"]: spec for spec in load_strategies(config_dir)["strategies"]}
    with file.open(encoding="utf-8-sig", newline="") as reader:
        rows = csv.DictReader(reader)
        if not rows.fieldnames or set(rows.fieldnames) != CSV_FIELDS or len(rows.fieldnames) != len(CSV_FIELDS):
            raise ValueError("Use the exact header from config/external-signals.example.csv")
        records = list(rows)
    if not records:
        raise ValueError("No publication rows in the CSV")
    if len(records) > 1000:
        raise ValueError("At most 1000 rows per import")
    if mode == "LIVE" and len({row["strategy_code"] for row in records}) != len(records):
        raise ValueError("LIVE imports allow one newly published row per strategy per batch")
    with transaction(db) as connection:
        connection.execute(IMPORT_SQL)
        recorded = now_utc()
        imported, duplicates = 0, 0
        for line, row in enumerate(records, 2):
            try:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError("Every row must match the CSV header")
                code, external_id = row["strategy_code"].strip(), row["external_id"].strip()
                spec = specs.get(code)
                if not spec or spec["source"] not in EXTERNAL_SOURCES or spec["implementation"] != "manual_v1":
                    raise ValueError("Register a matching external manual strategy first")
                if not EXTERNAL_ID.fullmatch(external_id):
                    raise ValueError("external_id must be a stable identifier using letters, numbers, dots, hyphens, or colons")
                supplied_at = row["issued_at_utc"].strip()
                if mode == "LIVE" and supplied_at:
                    raise ValueError("Backdating is never allowed in LIVE. Leave issued_at_utc blank or use REPLAY.")
                if mode == "LIVE" and connection.execute(
                    "SELECT 1 FROM external_signal_ids WHERE strategy_code=? AND mode='REPLAY' AND external_id=?",
                    (code, external_id),
                ).fetchone():
                    raise ValueError("This external ID is already recorded as historical and cannot be imported as LIVE")
                issued = recorded if mode == "LIVE" else timestamp_utc(supplied_at).to_pydatetime()
                if issued > recorded:
                    raise ValueError("A REPLAY issue time cannot be in the future")
                levels = tuple(Decimal(row[key].strip()) for key in ("entry", "sl", "tp1", "tp2"))
                tick = Decimal(spec["price_tick"])
                if any(not n.is_finite() or n <= 0 or n > 1_000_000 or n % tick != 0 for n in levels):
                    raise ValueError("Supply positive finite gold prices aligned to the $0.01 tick")
                signal_id = str(uuid5(NAMESPACE_URL, f"signal-tracker/external/{code}/{mode}/{external_id}"))
                stable = connection.execute(
                    "SELECT direction,entry,sl,tp1,tp2,issued_at_utc,data_source FROM signals WHERE signal_id=?", (signal_id,)
                ).fetchone()
                if stable:
                    actual_levels = tuple(Decimal(stable[key]) for key in ("entry", "sl", "tp1", "tp2"))
                    if (actual_levels != levels or stable["direction"] != row["direction"].strip().upper()
                            or stable["data_source"] != feed or (mode == "REPLAY"
                                and timestamp_utc(stable["issued_at_utc"]) != issued)):
                        raise ValueError("Existing external ID has different immutable terms")
                    duplicates += 1
                    continue
                signal = Signal(signal_id, code, spec["source"], spec["style"], "XAUUSD", row["direction"].strip().upper(),
                                *levels, issued, issued + timedelta(minutes=spec["expiry_minutes"]), feed,
                                "Operator-supplied testing signal; automated entry eligibility not assessed.",
                                mode, issued, recorded)
                reason = publish(connection, signal, spec)
                if reason != "Published":
                    raise ValueError(reason)
                connection.execute("INSERT INTO external_signal_ids VALUES (?, ?, ?, ?)", (code, mode, external_id, signal_id))
                if mode == "LIVE":
                    enqueue(connection, f"{signal_id}:PENDING", spec["source"], spec["style"], "PENDING",
                            f"{code} · {signal.direction}\nEntry {signal.entry} · SL {signal.sl}\n"
                            f"TP1 {signal.tp1} · TP2 {signal.tp2}\nID: {signal_id}", recorded)
                imported += 1
            except (ValueError, InvalidOperation) as error:
                raise ValueError(f"CSV row {line}: {error}") from None
    return imported, duplicates


def add_external(commands: argparse._SubParsersAction) -> None:
    reg = commands.add_parser("register-external", help="Register a new frozen external rules or manual strategy")
    reg.add_argument("--file", type=Path, required=True)
    cmd = commands.add_parser("import-signals", help="Publish operator-supplied signals from CSV or import as REPLAY")
    cmd.add_argument("--file", type=Path, required=True)
    cmd.add_argument("--mode", choices=("LIVE", "REPLAY"), required=True)
    cmd.add_argument("--data-source", choices=(HISTDATA_SOURCE, OANDA_SOURCE), required=True)
    cmd.add_argument("--confirm-new-publication", action="store_true",
                     help="Attest LIVE entries are first published right now, not copied from earlier posts")
    cmd.add_argument("--db", type=Path, default=DEFAULT_DB)


def run_external(args: argparse.Namespace) -> None:
    if args.command == "register-external":
        print(f"Registered {register(args.config_dir, args.file)}. Existing versions were not changed.")
    else:
        imported, duplicates = import_csv(args.config_dir, args.db, args.file, args.mode, args.data_source,
                                          args.confirm_new_publication)
        print(f"{args.mode}: {imported} published; {duplicates} identical IDs already recorded.")
