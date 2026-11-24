"""Scoreboard command line entry point."""

import argparse
import json
from pathlib import Path

from .backtest_report import json_value
from .config import load_strategies, market_for
from .phase2 import DEFAULT_DB
from .scoreboard import build
from .scoreboard_inputs import FOLDS, fingerprint, from_backtests, from_database, with_regimes
from .scoreboard_report import markdown


def add_scoreboard(commands: argparse._SubParsersAction) -> None:
    command = commands.add_parser("scoreboard", help="Score strategies and styles, with no mixing of evidence modes")
    command.add_argument("--mode", required=True, choices=("LIVE", "REPLAY", "BACKTEST"))
    command.add_argument("--pair", help="Enabled pair (defaults to XAUUSD)")
    command.add_argument("--db", type=Path, help=f"LIVE/REPLAY signal database (default: {DEFAULT_DB})")
    command.add_argument("--data-source", help="Restrict a LIVE/REPLAY scorecard to one data feed")
    command.add_argument("--backtest-report", type=Path, action="append", default=[],
                         help="Phase 3 JSON report; repeat for comparable strategies")
    command.add_argument("--fold", choices=FOLDS, help="Required for BACKTEST; one fold per scorecard")
    command.add_argument("--h1", type=Path, help="Matching H1 export to label ADX market regimes")
    command.add_argument("--output", type=Path, help="Optional new detailed Markdown path")
    command.add_argument("--json-output", type=Path, help="Optional new JSON path, including equity and breakdowns")


def run_scoreboard(args: argparse.Namespace) -> None:
    pair, _ = market_for(args.pair, args.config_dir)
    destinations = [path for path in (args.output, args.json_output) if path is not None]
    if len({path.resolve() for path in destinations}) != len(destinations):
        raise ValueError("Markdown and JSON outputs must be different paths")
    for path in destinations:
        if path.exists():
            raise ValueError(f"Output already exists: {path}")
    if args.mode == "BACKTEST":
        if args.db is not None or args.data_source is not None:
            raise ValueError("BACKTEST does not use a live database or an override feed")
        if not args.backtest_report or args.fold is None:
            raise ValueError("BACKTEST requires --backtest-report and --fold")
    elif args.backtest_report or args.fold is not None:
        raise ValueError("A backtest report or fold cannot be used in LIVE or REPLAY")
    sha = fingerprint(args.h1) if args.h1 else None
    if args.mode == "BACKTEST":
        cohort = from_backtests(args.backtest_report, args.fold, pair, sha)
    else:
        registry = load_strategies(args.config_dir)["strategies"]
        cohort = from_database(args.db or DEFAULT_DB, args.mode, pair, registry,
                               feed=args.data_source, allow_missing=args.db is None)
    if args.h1 is not None:
        cohort = with_regimes(cohort, args.h1, sha)
    report = build(cohort)
    for path in destinations:
        content = (markdown(report) if path == args.output else
                   json.dumps(report, indent=2, default=json_value, allow_nan=False) + "\n")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as stream:
            stream.write(content)
    print(markdown(report, detailed=False), end="")
