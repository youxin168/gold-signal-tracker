"""Load comparable signal cohorts without writing to the signal database."""

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import STRATEGY_CODE, load_object
from .research_data import read_bars
from .scoreboard import Cohort, Regimes
from .scoreboard_stats import ScoredSignal
from .sources import OANDA_SOURCE
from .store import from_record

FOLDS = {"in-sample": "In-sample", "out-of-sample": "Out-of-sample"}
INPUT_SHA = re.compile(r"\(SHA-256: ([0-9a-f]{64})\)$")


def _input_id(description: str) -> str:
    match = INPUT_SHA.search(description)
    if match:
        return match[1]
    if description == "Not supplied":
        return description
    raise ValueError("Backtest report is missing a valid input fingerprint")


def _spec(spec: dict[str, Any]) -> str:
    code = spec["strategy_code"]
    match = STRATEGY_CODE.fullmatch(code)
    if not match or match.groups() != (spec["source"], spec["style"]):
        raise ValueError(f"Invalid strategy in scoreboard input: {code}")
    return code


def from_database(
    path: Path, mode: str, pair: str, registry: list[dict[str, Any]],
    *, feed: str | None, allow_missing: bool = False,
) -> Cohort:
    if mode not in ("LIVE", "REPLAY"):
        raise ValueError("SQLite only contains LIVE or REPLAY records")
    def applicable(feed_name: str | None):
        strategy_feed = (feed_name if mode == "LIVE" else None) or OANDA_SOURCE
        return {_spec(spec): spec for spec in registry if spec.get("pair", pair) == pair
                and spec.get("live_feed", OANDA_SOURCE) == strategy_feed}

    strategies = applicable(feed)
    if not path.exists():
        if not allow_missing:
            raise ValueError(f"Signal database not found: {path}")
        return Cohort(mode, pair, feed, strategies, [], note="No signal database exists yet.")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        stored_regimes = {}
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='signal_regimes'").fetchone():
            stored_regimes = dict(conn.execute("SELECT signal_id, regime FROM signal_regimes"))
        gaps = {}
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='signal_gaps'").fetchone():
            gaps = dict(conn.execute("SELECT signal_id, reason FROM signal_gaps"))
        records = conn.execute(
            """SELECT signal_records.*, versions.specification FROM signal_records
               JOIN versions USING (strategy_code) WHERE mode = ? AND pair = ?""", (mode, pair),
        ).fetchall()
    if feed is None:
        sources = {row["data_source"] for row in records}
        if len(sources) > 1:
            raise ValueError("This scope contains multiple feeds; choose one with --data-source")
        feed = next(iter(sources), None)
        strategies = applicable(feed)
    rows = []
    for row in records:
        if row["data_source"] != feed:
            continue
        spec = json.loads(row["specification"])
        strategies[_spec(spec)] = spec
        rows.append(ScoredSignal(*from_record(row), regime=stored_regimes.get(row["signal_id"], "Unknown"),
                                 unresolved_reason=gaps.get(row["signal_id"])))
    return Cohort(mode, pair, feed, strategies, rows, note=None if rows else "No signals in this scope.")


def from_backtests(
    paths: list[Path], fold_key: str, pair: str, h1_sha: str | None = None,
) -> Cohort:
    if not paths or fold_key not in FOLDS:
        raise ValueError("Choose a backtest fold and provide at least one backtest JSON report")
    label = FOLDS[fold_key]
    strategies: dict[str, dict[str, Any]] = {}
    coverage: dict[str, dict[str, int]] = {}
    records: list[ScoredSignal] = []
    scope = None
    for path in paths:
        report = load_object(path)
        spec = report["strategy"]
        code = _spec(spec)
        if report["mode"] != "BACKTEST" or spec["pair"] != pair or spec["version_state"] != "FROZEN":
            raise ValueError(f"{path}: expected a frozen {pair} BACKTEST report")
        if code in strategies:
            raise ValueError(f"Duplicate strategy report for this fold: {code}")
        selected = [fold for fold in report["folds"] if fold["label"] == label]
        if len(selected) != 1:
            raise ValueError(f"{path}: expected exactly one {label} fold")
        fold = selected[0]
        start, end = [datetime.fromisoformat(fold[key]) for key in ("start_utc", "end_utc_exclusive")]
        if start.utcoffset() is None or end.utcoffset() is None or start >= end:
            raise ValueError(f"{path}: invalid backtest fold period")
        feed = report["data_source"]
        descriptions = report["inputs"]
        evidence = tuple(_input_id(descriptions[key])
                         for key in ("M1 candles", "News snapshots", "Bid/ask observations"))
        current = (feed, start, end, evidence, spec["execution"])
        if scope is not None and current != scope:
            raise ValueError("Compare only reports with the same feed, fold dates, evidence inputs and execution assumptions")
        if h1_sha is not None:
            h1_input = descriptions.get("H1 candles")
            if h1_input is None or _input_id(h1_input) != h1_sha:
                raise ValueError(f"{path}: H1 candles must match a recorded fingerprint; "
                                 "provide --h1 when running the backtest to register these candles")
        scope = current
        strategies[code] = spec
        coverage[code] = fold["coverage"]
        for raw in fold["records"]:
            signal, outcome = from_record(raw)
            if (signal.strategy_code != code or not start <= signal.issued_at_utc < end
                    or any(stamp is not None and stamp > end
                           for stamp in (outcome.closed_at, outcome.triggered_at, outcome.checked_until))):
                raise ValueError(f"{path}: signal lies outside its strategy or fold")
            records.append(ScoredSignal(signal, outcome, unresolved_reason=raw.get("unresolved_reason")))
    return Cohort("BACKTEST", pair, scope[0], strategies, records, label,
                  scope[1].isoformat(), scope[2].isoformat(), coverage)


def fingerprint(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def with_regimes(cohort: Cohort, path: Path, sha: str) -> Cohort:
    classifier = Regimes(read_bars(path, "H1"))
    if cohort.data_source is not None and classifier.feed != cohort.data_source:
        raise ValueError("H1 candles must use the same feed as the scorecard")
    rows = [replace(row, regime=classifier.label(row)) for row in cohort.records]
    return replace(cohort, records=rows, regime_input=f"{path.name} (SHA-256: {sha})")
