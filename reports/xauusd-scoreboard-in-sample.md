# BACKTEST scoreboard — XAUUSD · In-sample

Testing and research only; not financial advice.

Price feed: HISTDATA_ASCII_M1_BID
Window: 2023-01-01T00:00:00+00:00 to 2024-05-26T00:00:00+00:00 (end exclusive)
Market regime is unknown unless a matching H1 export is supplied.

## Style totals

| Style | Signals | Filled | Expired | Entry unresolved | Filled open | Fill rate | Completed | Evidence | Average R | Expectancy R | Profit factor | Total R | Max DD R | Losing streak | Win rate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SCA | 0 | 0 | 0 | 0 | 0 | Not estimable | 0 | Too early | Not estimable | Not estimable | Not estimable | Not estimable | Not estimable | Not estimable | Not estimable |
| INT | 0 | 0 | 0 | 0 | 0 | Not estimable | 0 | Too early | Not estimable | Not estimable | Not estimable | Not estimable | Not estimable | Not estimable | Not estimable |
| SWG | 0 | 0 | 0 | 0 | 0 | Not estimable | 0 | Too early | Not estimable | Not estimable | Not estimable | Not estimable | Not estimable | Not estimable | Not estimable |

## INT strategies

| Rank and strategy | Signals | Filled | Expired | Entry unresolved | Filled open | Fill rate | Completed | Evidence | Average R | Expectancy R | Profit factor | Total R | Max DD R | Losing streak | Win rate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Unranked · CLD-INT-01-v1 · FROZEN | 0 | 0 | 0 | 0 | 0 | Not estimable | 0 | Too early | Not estimable | Not estimable | Not estimable | Not estimable | Not estimable | Not estimable | Not estimable |

### CLD-INT-01-v1 — Trend Pullback

No completed trades. Win rate, expectancy and drawdown are not estimable.
- Rank withheld: Fewer than 100 completed trades.
- **Warning:** Sample too small: fewer than 30 completed trades. Do not draw a performance conclusion.
- **Warning:** Historical news or spread evidence is missing. Results only describe the covered subset.
- **Warning:** 500 technical setups did not pass the required filters and are not trades.
- **Warning:** Best/worst session not estimable: need 10 completed trades in at least two sessions.
- **95% expectancy interval:** Not estimable.
- **95% win-rate interval:** Not estimable.

## How to read this

- Fill rate is filled ÷ (filled + expired). Pending entries are not failures; filled open trades are not completed trades.
- A win is a strictly positive net result. A flat result stays in the win-rate denominator. Average R and expectancy are the same realized sample mean.
- Ranking stays within a style, with at least two strategies on the same basis and at least 100 completed trades each. It uses total R, expectancy, lower drawdown and profit factor, in that order. Win rate is not a ranking criterion.
- Equity starts at zero and adds realized net R by UTC close timestamp. Simultaneous closes are combined for equity and drawdown. Style totals describe pooled signals, not a portfolio simulation.
- Losing streak uses close time and stable signal ID order for tied times; a flat result resets it.
- Win-rate intervals use Wilson’s method. Expectancy intervals use UTC close-day clusters and a t reference. These intervals are descriptive; trade dependence, incomplete coverage and regime changes can make uncertainty larger.
