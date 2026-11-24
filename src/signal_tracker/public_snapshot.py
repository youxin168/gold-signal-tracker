"""Export an allowlisted, read-only payload for the Replit preview and GitHub Pages."""

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, replace
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from . import parallel_targets, third_target
from .backtest_report import json_value
from .config import load_strategies, market_for
from .head_to_head import compare
from .scoreboard import Cohort, build
from .scoreboard_inputs import FOLDS, from_backtests, from_database
from .signal import now_utc, utc

GOLD_AUDIT = Path("reports/xauusd-cld-int-01-2023-2024.json")
PUBLIC_FIELDS = ("signal_id", "strategy_code", "source", "style", "pair", "direction", "entry", "sl", "tp1", "tp2", "tp3", "tp2_at",
                 "issued_at_utc", "expires_at_utc", "triggered_at", "closed_at", "status", "result_r", "data_source")
STRATEGY_FIELDS = ("strategy_code", "source", "style", "name", "version_state", "experimental",
                   "entry_timeframe", "trend_timeframe", "expiry_minutes")
RULES = {
    "CLD-SCA-01-v1": ["Use M15 price versus EMA50 for direction.",
                      "On M5, look for an EMA20 pullback, RSI(7) turn, and confirming close.",
                      "Stop at 1.2× ATR(14) from entry."],
    "CLD-SCA-02-v1": ["On M5, sweep the prior 20 closed candles’ high or low and close back inside the range.",
                      "London and New York only; stop beyond the sweep wick."],
    "CLD-INT-01-v1": ["Use the closed H1 price versus EMA200 to set direction.",
                      "On M15, the RSI(14) pivot candle crosses the prior EMA21 or EMA50. "
                      "Require a confirming close that reclaims the EMA; RSI pivot range 40–50 for buys or 50–60 for sells.",
                      "Enter at the confirmation close; stop distance is 1.5× ATR(14).",
                      "London or New York, 08:00–17:00 local weekdays. Skip high-impact USD/XAU news "
                      "within 30 minutes and require observed spread ≤ $0.50 no more than five minutes old.",
                      "Outcome model: M1 bid OHLC, $0.30 assumed spread, $0.05 slippage per fill, "
                      "50% closes at TP1 before the remainder moves to breakeven."],
    "CLD-INT-02-v1": ["At London open, require a closed M15 break outside 00:00–07:00 UTC Asian range that agrees with H1 trend.",
                      "Stop on the other side of the range, or at 1.5× ATR(14) if the range is wider."],
    "CLD-SWG-01-v1": ["D1 EMA50 versus EMA200 sets the trend. Look for an H4 EMA21/50 pullback and RSI turn.",
                      "Stop distance is 2× ATR(14)."],
    "CLD-SWG-02-v1": ["Require an H4 close outside the prior 20-candle Donchian channel that agrees with D1 trend.",
                      "Stop distance is 2× ATR(14)."],
}


def atomic_json(path: Path, value: Any, *, public: bool = False, pretty: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        staged = Path(stream.name)
        try:
            json.dump(value, stream, default=json_value, allow_nan=False,
                      indent=2 if pretty else None, separators=None if pretty else (",", ":"), ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            if public:
                staged.chmod(0o644)
            staged.replace(path)
        finally:
            staged.unlink(missing_ok=True)


def _public_scorecard(cohort: Cohort, label: str, watches: dict | None = None,
                      retired: set[str] | None = None, plans: dict | None = None) -> dict[str, Any]:
    signals = []
    for row in sorted(cohort.records, key=lambda row: (row.signal.issued_at_utc, row.signal.signal_id), reverse=True):
        record = asdict(row.signal) | asdict(row.outcome)
        watch = (watches or {}).get(row.signal.signal_id)
        plan = (plans or {}).get(row.signal.signal_id)
        signals.append({key: record[key] for key in PUBLIC_FIELDS}
                       | {"unresolved_reason": row.unresolved_reason}
                       | ({"tp3": watch["price"], "tp3_watch": watch} if watch else {})
                       | ({"parallel_targets": plan} if plan is not None else {}))
    scored = replace(cohort, strategies={code: spec for code, spec in cohort.strategies.items() if code not in retired},
                     records=[row for row in cohort.records if row.signal.strategy_code not in retired]) if retired else cohort
    score = build(scored)
    return score | {"id": f"{cohort.mode}:{cohort.data_source or 'none'}:{cohort.fold or '-'}",
                    "label": label, "signals": signals, "comparisons": compare(scored)}


def make_snapshot(config_dir: Path, db: Path, reports: list[Path], status_path: Path | None) -> dict[str, Any]:
    pair, _ = market_for("XAUUSD", config_dir)
    settings = load_strategies(config_dir)
    registry = settings["strategies"]
    retired = set(settings.get("retired_live_strategy_codes", []))
    feeds: dict[str, list[str]] = {"LIVE": [], "REPLAY": []}
    watches: dict = {}
    plans: dict = {}
    if db.exists():
        with closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            watches = third_target.public_watches(conn)
            plans = parallel_targets.public_plans(conn)
            for mode, feed in conn.execute(
                "SELECT DISTINCT mode, data_source FROM signals WHERE pair = ? ORDER BY mode, data_source", (pair,)
            ):
                feeds[mode].append(feed)
    cohorts = []
    specs = {spec["strategy_code"]: spec for spec in registry}
    frozen = {}
    for mode, sources in feeds.items():
        for feed in sources or [None]:
            cohort = from_database(db, mode, pair, registry, feed=feed, allow_missing=True)
            for code in {row.signal.strategy_code for row in cohort.records}:
                if code in frozen and frozen[code] != cohort.strategies[code]:
                    raise ValueError(f"Conflicting frozen definitions for {code}")
                frozen[code] = cohort.strategies[code]
            cohorts.append(_public_scorecard(cohort, mode + (f" · {feed}" if feed else ""),
                                              watches if mode == "LIVE" else None, retired if mode == "LIVE" else None,
                                              plans if mode == "LIVE" else None))
    for key, label in FOLDS.items():
        if reports:
            cohort = from_backtests(reports, key, pair)
            cohorts.append(_public_scorecard(cohort, f"BACKTEST · {label}"))
            for code, spec in cohort.strategies.items():
                if code in frozen and frozen[code] != spec:
                    raise ValueError(f"Conflicting frozen definitions for {code}")
                frozen[code] = spec
    status = {"state": "not_configured", "updated_at_utc": None,
              "message": "No scheduled live run has been recorded. No price stream is connected to this website."}
    if status_path is not None and status_path.exists():
        raw = json.loads(status_path.read_text(encoding="utf-8"))
        status = {key: raw[key] for key in status}
        if raw.get("data_source") == "BIQUOTE_XAUUSD_MID":
            status["data_source"] = raw["data_source"]
        # Allowlist only recognized codes and integer progress, never the cached prices.
        enabled = raw.get("enabled_strategy_codes")
        if isinstance(enabled, list):
            status["enabled_strategy_codes"] = [code for code in enabled
                                                if isinstance(code, str) and code in specs and code not in retired]
        warmups = raw.get("strategy_warmup")
        if isinstance(warmups, dict):
            status["strategy_warmup"] = {
                code: {"have": counts["have"], "need": counts["need"]}
                for code, counts in warmups.items()
                if code in specs and code not in retired and isinstance(counts, dict) and type(counts.get("have")) is int
                and type(counts.get("need")) is int and 0 <= counts["have"] < counts["need"]
            }
    strategies = []
    for code, spec in sorted((specs | frozen).items()):
        strategies.append({key: spec[key] for key in STRATEGY_FIELDS} | {
            "live_feed": spec.get("live_feed", "OANDA_PRACTICE_BID"),
            "rules": spec.get("public_rules") or RULES.get(code, []),
            "target_multiples": [str(value) for value in spec["take_profit_r"]],
            "max_signals_per_day": spec["max_signals_per_utc_day"],
            "notes": spec.get("needs_definition") or [],
            **({"site_test": True} if spec.get("site_test") is True else {}),
            **({"retired_live": True} if code in retired else {}),
        })
    return {"schema_version": 1, "generated_at_utc": utc(now_utc()), "pair": pair, "runner": status,
            "strategies": strategies, "cohorts": cohorts}
