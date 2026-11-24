"""Run the backtest from validated historical inputs and export standalone reports."""

import argparse
import hashlib
import json
from pathlib import Path

from .backtest import run
from .backtest_inputs import HistoricalCalendar, HistoricalQuotes
from .backtest_report import json_value, machine_report, markdown
from .candles import timestamp_utc
from .config import TIMEFRAMES, load_strategies
from .research_data import read_bars
from .signal import now_utc
from .trend_pullback import CODE


def add_backtest(commands: argparse._SubParsersAction) -> None:
    cmd = commands.add_parser("backtest", help="Backtest an implemented XAUUSD strategy using a chronological 70/30 split")
    cmd.add_argument("--strategy", default=CODE, help="Frozen rules-based strategy version")
    for timeframe in TIMEFRAMES:
        cmd.add_argument(f"--{timeframe.lower()}", required=timeframe == "M1", type=Path,
                         help=f"{timeframe} closed bid candle export (as required by the strategy)")
    cmd.add_argument("--start", required=True, help="Inclusive UTC midnight (ISO 8601)")
    cmd.add_argument("--end", required=True, help="Exclusive UTC midnight (ISO 8601)")
    cmd.add_argument("--calendar", type=Path, help="Timestamped calendar snapshot JSON; omit to report missing coverage")
    cmd.add_argument("--quotes", type=Path, help="Historical bid/ask observation CSV; omit to report missing coverage")
    cmd.add_argument("--output", required=True, type=Path, help="New Markdown report path")
    cmd.add_argument("--json-output", type=Path, help="Optional new JSON report path with individual outcomes")


def _fingerprint(path: Path | None) -> str:
    if path is None:
        return "Not supplied"
    with path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    return f"{path.name} (SHA-256: {sha})"


def run_backtest(args: argparse.Namespace) -> None:
    if args.json_output is not None and args.output.resolve() == args.json_output.resolve():
        raise ValueError("Markdown and JSON outputs must be different paths")
    destinations = [path for path in (args.output, args.json_output) if path is not None]
    for path in destinations:
        if path.exists():
            raise ValueError(f"Output already exists: {path}")
    spec = next((entry for entry in load_strategies(args.config_dir)["strategies"]
                 if entry["strategy_code"] == args.strategy), None)
    if (spec is None or spec["version_state"] != "FROZEN" or spec["pair"] != "XAUUSD"
            or spec.get("implementation") == "manual_v1"):
        raise ValueError("Choose a frozen XAUUSD rules-based strategy")
    if spec["execution"]["method"] == "mid_ohlc_v1":
        raise ValueError("The bid archives cannot backtest the Biquote midpoint versions")
    dates = [timestamp_utc(value) for value in (args.start, args.end)]
    if any(stamp != stamp.normalize() for stamp in dates):
        raise ValueError("Backtest dates must begin at midnight UTC")
    start, end = (stamp.to_pydatetime() for stamp in dates)
    setup_frames = (spec["entry_timeframe"], spec["trend_timeframe"])
    paths = [getattr(args, tf.lower()) for tf in setup_frames]
    if any(path is None for path in paths):
        raise ValueError(f"{args.strategy} requires --{setup_frames[0].lower()} and --{setup_frames[1].lower()}")
    entry, trend = (read_bars(path, tf) for path, tf in zip(paths, setup_frames))
    m1 = read_bars(args.m1, "M1")
    feed = m1["data_source"].iloc[0]
    calendar = HistoricalCalendar.read(args.calendar, spec["news_filter"]) if args.calendar else HistoricalCalendar([])
    quotes = HistoricalQuotes.read(args.quotes, feed) if args.quotes else HistoricalQuotes([])
    folds = run(m1, entry, trend, spec, start, end, now_utc(), calendar, quotes)
    inputs = {f"{tf} candles": _fingerprint(path) for tf, path in zip(("M1", *setup_frames), (args.m1, *paths))}
    if args.h1 is not None and "H1 candles" not in inputs:
        h1 = read_bars(args.h1, "H1")
        if h1["data_source"].iloc[0] != feed:
            raise ValueError("The optional regime H1 export must use the same price feed")
        inputs["H1 candles"] = _fingerprint(args.h1)
    inputs.update({"News snapshots": _fingerprint(args.calendar), "Bid/ask observations": _fingerprint(args.quotes)})
    inputs["Frozen strategy"] = _fingerprint(args.config_dir / "strategies.json")
    results = [markdown(folds, spec, feed, inputs)]
    if args.json_output is not None:
        results.append(json.dumps(machine_report(folds, spec, feed, inputs), default=json_value, indent=2) + "\n")
    for destination, result in zip(destinations, results):
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("x", encoding="utf-8") as stream:
            stream.write(result)
    print(f"BACKTEST report: {args.output}")
    for fold in folds:
        metrics = fold.metrics()
        print(f"{fold.label}: {metrics['signals']} eligible signals, {metrics['closed']} completed, "
              f"{metrics['unresolved']} unresolved")
