"""A readable Phase 4 report. Graph rendering belongs to the website phase."""

from decimal import Decimal
from typing import Any

COLUMNS = (
    ("signals", "Signals"), ("filled", "Filled"), ("expired", "Expired"),
    ("entry_unresolved", "Entry unresolved"), ("filled_open", "Filled open"),
    ("fill_rate", "Fill rate"), ("completed", "Completed"), ("sample_size_badge", "Evidence"),
    ("average_r", "Average R"), ("expectancy_r", "Expectancy R"), ("profit_factor", "Profit factor"),
    ("total_r", "Total R"), ("max_drawdown_r", "Max DD R"), ("longest_losing_streak", "Losing streak"),
    ("win_rate", "Win rate"),
)
BREAKDOWN_LABELS = {"session": "Session at issue", "weekday_utc": "UTC weekday at issue",
                    "direction": "Direction", "market_regime": "Market regime at issue"}


def _text(value: str) -> str:
    return value.replace("|", r"\|").replace("\r", " ").replace("\n", " ")


def _metric(metrics: dict[str, Any], key: str) -> str:
    value = metrics[key]
    if key == "profit_factor" and metrics["profit_factor_status"] == "no_losses":
        return "No losses"
    if value is None:
        return "Not estimable"
    if key in ("win_rate", "fill_rate"):
        return f"{value:.1%}"
    if isinstance(value, Decimal):
        return f"{value:.3f}"
    return _text(str(value))


def _table(first: str, rows: list[tuple[str, dict[str, Any]]], columns=COLUMNS) -> list[str]:
    headers = [first, *(label for _, label in columns)]
    output = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    output.extend("| " + " | ".join([_text(name), *(_metric(values, key) for key, _ in columns)]) + " |"
                  for name, values in rows)
    return output


def _interval(value: tuple[float, float] | None, fmt: str) -> str:
    return f"{value[0]:{fmt}} to {value[1]:{fmt}}" if value is not None else "Not estimable"


def _breakdowns(card: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if not card["metrics"]["signals"]:
        return lines
    for key, values in card["breakdowns"].items():
        lines.extend(["", f"**{BREAKDOWN_LABELS[key]}**", ""])
        lines.extend(_table("Group", list(values.items()), (
            ("signals", "Signals"), ("filled", "Filled"), ("expired", "Expired"), ("fill_rate", "Fill rate"),
            ("completed", "Completed"), ("expectancy_r", "Expectancy R"), ("total_r", "Total R"),
            ("win_rate", "Win rate"),
        )))
    return lines


def markdown(scorecard: dict[str, Any], *, detailed: bool = True) -> str:
    title = f"{scorecard['mode']} scoreboard — {scorecard['pair']}"
    if scorecard["fold"]:
        title += f" · {scorecard['fold']}"
    lines = [f"# {title}", "", "Testing and research only; not financial advice.", "",
             f"Price feed: {scorecard['data_source'] or 'No records'}"]
    if scorecard["start_utc"]:
        lines.append(f"Window: {scorecard['start_utc']} to {scorecard['end_utc_exclusive']} (end exclusive)")
    if scorecard["note"]:
        lines.append(scorecard["note"])
    if scorecard["regime_input"] is None:
        lines.append("Market regime is unknown unless a matching H1 export is supplied.")
    lines.extend(["", "## Style totals", ""])
    lines.extend(_table("Style", [(card["style"], card["metrics"]) for card in scorecard["styles"]]))
    for style in scorecard["styles"]:
        cards = [card for card in scorecard["strategies"] if card["style"] == style["style"]]
        if not cards:
            continue
        lines.extend(["", f"## {style['style']} strategies", ""])
        lines.extend(_table("Rank and strategy", [
            (f"{card['rank'] or 'Unranked'} · {card['strategy_code']} · {card['version_state']}", card["metrics"])
            for card in cards
        ]))
        if detailed:
            lines.extend(_breakdowns(style))
        for card in cards:
            analyst = card["analyst"]
            lines.extend(["", f"### {_text(card['strategy_code'])} — {_text(card['name'])}", "", analyst["summary"]])
            if card["rank_reason"]:
                lines.append(f"- Rank withheld: {card['rank_reason']}.")
            for heading, key in (("Strength", "strengths"), ("Weakness", "weaknesses"), ("Warning", "warnings")):
                lines.extend(f"- **{heading}:** {note}" for note in analyst[key])
            metrics = card["metrics"]
            exp_range = metrics["expectancy_r_ci_95"]
            unit = " R" if exp_range is not None else ""
            lines.append(f"- **95% expectancy interval:** {_interval(exp_range, '.2f')}{unit}.")
            lines.append(f"- **95% win-rate interval:** {_interval(metrics['win_rate_ci_95'], '.1%')}.")
            for role in ("best", "worst"):
                result = analyst[f"{role}_session"]
                if result:
                    lines.append(f"- **{role.title()} observed session:** {', '.join(result['sessions'])} "
                                 f"({result['expectancy_r']:+.2f}R per completed trade).")
            if detailed:
                lines.extend(_breakdowns(card))
    lines.extend([
        "", "## How to read this", "",
        "- Fill rate is filled ÷ (filled + expired). Pending entries are not failures; filled open trades are not completed trades.",
        "- A win is a strictly positive net result. A flat result stays in the win-rate denominator. Average R and expectancy are the same realized sample mean.",
        "- Ranking stays within a style, with at least two strategies on the same basis and at least 100 completed trades each. It uses total R, expectancy, lower drawdown and profit factor, in that order. Win rate is not a ranking criterion.",
        "- Equity starts at zero and adds realized net R by UTC close timestamp. Simultaneous closes are combined for equity and drawdown. Style totals describe pooled signals, not a portfolio simulation.",
        "- Losing streak uses close time and stable signal ID order for tied times; a flat result resets it.",
        "- Win-rate intervals use Wilson’s method. Expectancy intervals use UTC close-day clusters and a t reference. These intervals are descriptive; trade dependence, incomplete coverage and regime changes can make uncertainty larger.",
    ])
    return "\n".join(lines) + "\n"
