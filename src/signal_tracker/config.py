"""Read local research settings, and reject unknown or disabled instruments."""

import json
import re
from pathlib import Path
from typing import Any

CONFIG_DIR = Path("config")
TIMEFRAMES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440}
STRATEGY_CODE = re.compile(r"(CLD|EXT1|EXT2|OWN)-(SCA|INT|SWG)-\d{2}-v[1-9]\d*")


def load_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def load_strategies(config_dir: Path = CONFIG_DIR) -> dict[str, Any]:
    registry = load_object(config_dir / "strategies.json")
    raw = registry["strategies"]
    by_code = {row["strategy_code"]: row for row in raw}
    pilot = registry.get("biquote_pilot_versions", {})
    new_versions = []
    for code, parent in pilot.items():
        base = by_code[parent]
        if base["version_state"] != "FROZEN" or code != parent.removesuffix("-v1") + "-v2":
            raise ValueError("Biquote versions must inherit the corresponding frozen v1 rules")
        rules = base.get("public_rules") or [
            "Use H1 price versus EMA200 and an M15 EMA21/50 RSI(14) pullback with confirmation.",
            "London or New York weekdays. Stop at 1.5× ATR(14); keep the original entry and target rules.",
        ]
        new_versions.append(base | {
            "strategy_code": code,
            "live_feed": "BIQUOTE_XAUUSD_MID",
            "news_provider": "biquote_us_high_impact_v1",
            "experimental": True,
            "execution": base["execution"] | {"method": "mid_ohlc_v1"},
            "public_rules": [*rules, "Test-only midpoint candles from biquote; observed bid/ask spread and the provider's US high-impact calendar gate entries.",
                             "Outcomes use a fixed $0.30 spread around the midpoint, $0.05 slippage per fill and the shared conservative checker."],
        })
    insert_at = max((i + 1 for i, row in enumerate(raw) if row["strategy_code"] in pilot.values()), default=len(raw))
    if experiment := registry.get("tp3_pilot"):
        parent = next(row for row in new_versions if row["strategy_code"] == experiment["parent"])
        new_versions.append(parent | {
            "strategy_code": experiment["strategy_code"],
            "name": f"{parent['name']} · TP3 test",
            "take_profit_r": [*parent["take_profit_r"], experiment["target_r"]],
            "execution": parent["execution"] | {"tp2_fraction": experiment["tp2_fraction"]},
            "public_rules": [*parent["public_rules"],
                             "TP3 experiment: exit 50% at 1R, 25% at 2R and 25% at 3R. "
                             "The stop moves to entry after TP1 and stays there after TP2. "
                             "This is a separate test, not a safety or performance claim."],
        })
    for code, change in registry.get("biquote_hourly_ema_versions", {}).items():
        parent = next((row for row in new_versions if row["strategy_code"] == change["parent"]), None)
        period = change["ema_period"]
        if (parent is None or parent["style"] != "INT" or parent["trend_timeframe"] != "H1"
                or parent["trend"]["type"] != "price_vs_ema"
                or code != parent["strategy_code"].removesuffix("-v2") + "-v3"
                or type(period) is not int or not 1 < period < parent["trend"]["ema_period"]):
            raise ValueError("A Biquote H1 variant must reduce its corresponding Intraday v2 EMA period")
        previous = parent["trend"]["ema_period"]
        new_versions.append(parent | {
            "strategy_code": code,
            "trend": parent["trend"] | {"ema_period": period},
            "public_rules": [
                *(rule.replace(f"EMA{previous}", f"EMA{period}") for rule in parent["public_rules"]),
                f"Wait for {period} closed H1 candles. This version uses a shorter trend filter to fit the free feed; its results are separate from v2.",
            ],
        })
    registry["strategies"] = [*raw[:insert_at], *new_versions, *raw[insert_at:]]
    seen: set[str] = set()
    for strategy in registry["strategies"]:
        code = strategy["strategy_code"]
        match = STRATEGY_CODE.fullmatch(code)
        if not match or match.groups() != (strategy["source"], strategy["style"]):
            raise ValueError(f"Strategy code disagrees with source or style: {code}")
        if code in seen:
            raise ValueError(f"Duplicate strategy code: {code}")
        if strategy["style"] == "SCA" and not strategy["experimental"]:
            raise ValueError(f"Scalping strategy must be experimental: {code}")
        if any(strategy[key] not in TIMEFRAMES for key in ("entry_timeframe", "trend_timeframe")):
            raise ValueError(f"Unsupported strategy timeframe: {code}")
        seen.add(code)
    retired = registry.get("retired_live_strategy_codes", [])
    if not isinstance(retired, list) or any(code not in seen for code in retired):
        raise ValueError("Retired live strategies must be registered versions")
    return registry


def market_for(pair: str | None, config_dir: Path = CONFIG_DIR) -> tuple[str, dict[str, Any]]:
    registry = load_object(config_dir / "markets.json")
    symbol = pair.upper() if pair else registry["default_pair"]
    market = registry["pairs"].get(symbol)
    if not market or not market["enabled"]:
        raise ValueError(f"{symbol} is not enabled in {config_dir / 'markets.json'}")
    return symbol, market
