"""Research commands for the testing-only Signal Tracker."""

import argparse
import logging
import sqlite3
from pathlib import Path

from .candles import CandleWindow
from .config import CONFIG_DIR, TIMEFRAMES, load_strategies, market_for
from .external import add_external, run_external
from .indicators import with_indicators
from .phase2 import add_commands, run_phase2
from .phase3 import add_backtest, run_backtest
from .phase4 import add_scoreboard, run_scoreboard
from .phase5 import add_phase5, run_phase5
from .sources import fetch_oanda, load_histdata

LOG = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, default=CONFIG_DIR)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("strategies", help="List configured strategy versions")
    candles = commands.add_parser("candles", help="Read closed spot candles and export a CSV")
    candles.add_argument("--provider", required=True, choices=("histdata", "oanda"))
    candles.add_argument("--pair", help="Pair from config/markets.json; default XAUUSD")
    candles.add_argument("--timeframe", required=True, choices=TIMEFRAMES)
    candles.add_argument("--start", required=True, help="Timezone-aware start on a candle boundary")
    candles.add_argument("--end", required=True, help="Timezone-aware end on a candle boundary")
    candles.add_argument("--file", action="append", type=Path, default=[], help="HistData input, repeatable")
    candles.add_argument("--indicators", action="store_true", help="Append research indicator columns")
    candles.add_argument("--output", required=True, type=Path, help="A new CSV path; never overwritten")
    add_commands(commands)
    add_backtest(commands)
    add_scoreboard(commands)
    add_phase5(commands)
    add_external(commands)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        if args.command == "strategies":
            for spec in load_strategies(args.config_dir)["strategies"]:
                warning = " | EXPERIMENTAL" if spec["experimental"] else ""
                print(f'{spec["strategy_code"]} | {spec["name"]} | {spec["version_state"]}{warning}')
            return 0

        if args.command == "backtest":
            run_backtest(args)
            return 0

        if args.command == "scoreboard":
            run_scoreboard(args)
            return 0

        if args.command in ("export-site", "scheduled-tick", "send-alerts", "check-telegram-channel", "preview-scanner"):
            run_phase5(args)
            return 0

        if args.command in ("register-external", "import-signals"):
            run_external(args)
            return 0

        if args.command != "candles":
            run_phase2(args)
            return 0

        pair, market = market_for(args.pair, args.config_dir)
        window = CandleWindow.create(args.start, args.end, args.timeframe)
        if args.output.exists():
            raise ValueError(f"Output already exists: {args.output}")
        if args.provider == "histdata":
            frame = load_histdata(pair, market["histdata_symbol"], args.file, window)
        else:
            if args.file:
                raise ValueError("--file is only supported by --provider histdata")
            frame = fetch_oanda(pair, market["oanda_instrument"], window)
        slots = int((window.end - window.start) / window.duration)
        if len(frame) < slots:
            LOG.warning("%d of %d UTC candle slots are absent, including market closures; no gaps were filled",
                        slots - len(frame), slots)
        if args.indicators:
            frame = with_indicators(frame)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="") as stream:
            frame.to_csv(stream)
        LOG.info("Wrote %d %s %s candles to %s", len(frame), pair, args.timeframe, args.output)
    except (KeyError, OSError, ValueError, sqlite3.Error) as error:
        LOG.error("%s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
