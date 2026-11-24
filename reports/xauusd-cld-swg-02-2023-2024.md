# BACKTEST — XAUUSD · CLD-SWG-02-v1

Requested window: **2023-01-01 to 2025-01-01 (UTC; end exclusive)**  
Price feed: `HISTDATA_ASCII_M1_BID`  
Split: first 2023-01-01–2024-05-26, then 2024-05-26–2025-01-01; both end-exclusive.

**Research and testing only. Not financial advice or evidence of live execution.**

**Performance is not estimable for at least one fold.** A missing input or a zero eligible sample is not a 0% win rate, a flat result, or a failed strategy.

- **In-sample: too early** — fewer than 30 completed trades.
- **In-sample: incomplete evidence.** Any observed results describe only the covered subset.
- **Out-of-sample: too early** — fewer than 30 completed trades.
- **Out-of-sample: incomplete evidence.** Any observed results describe only the covered subset.

For HistData, H4/D1 need at least 180/1,320 source minutes; shorter buckets were excluded. Such aggregates are not an independent guarantee against missing minutes.

## Price coverage

| UTC time slots | In-sample observed / possible | Out-of-sample observed / possible |
|---|---:|---:|
| M1 | 450,250 / 735,840 | 214,094 / 316,800 |
| H4 | 1,731 / 3,066 | 888 / 1,320 |
| D1 | 219 / 511 | 146 / 220 |

Possible slots include normal closures and holidays. This is not an estimate of in-session data loss.

## Decision coverage

| Item | In-sample | Out-of-sample |
|---|---:|---:|
| London/New York decision slots (including holidays) | 2,190 | 942 |
| Slots with a closed entry candle | 1,731 | 888 |
| News filter passed | 0 | 0 |
| Excluded by high-impact news | 0 | 0 |
| Missing usable calendar snapshot | 1,731 | 888 |
| Spread filter passed | 0 | 0 |
| Excluded by wide spread | 0 | 0 |
| Missing fresh bid/ask quote | 1,731 | 888 |
| Both evidence filters passed | 0 | 0 |
| Technical candidates before filters (not signals) | 79 | 61 |
| Technical candidates not eligible after filters | 79 | 61 |
| Excluded by daily signal limit | 0 | 0 |
| Session slots missing H4 | 459 | 54 |

## Outcome summary

| Item | In-sample | Out-of-sample |
|---|---:|---:|
| Eligible signals | 0 | 0 |
| Filled (including unresolved) | 0 | 0 |
| Expired unfilled | 0 | 0 |
| Unresolved | 0 | 0 |
| Unresolved: missing M1 | 0 | 0 |
| Unresolved: fold ended | 0 | 0 |
| Completed trades with a result | 0 | 0 |
| Positive net results | 0 | 0 |
| Negative net results | 0 | 0 |
| Zero net results | 0 | 0 |
| Win rate (completed trades only) | Not estimable | Not estimable |
| Average R (completed trades only) | Not estimable | Not estimable |
| Total R (completed trades only) | Not estimable | Not estimable |

## Method and limits

- Frozen strategy and execution rules; no fitting, optimization, or choice of settings based on results.
- The calendar range is split chronologically at roughly 70/30, rounded down to a UTC date. Earlier candles can warm indicators; future candles cannot change earlier indicator values.
- Decisions use only closed H4 and D1 candles, the last bid/ask observation at or before that decision, and a calendar snapshot captured by then that covers the full news window.
- Missing required price, news, or quote inputs are not replaced by assumptions. Pre-filter technical candidates are counted only to show where evidence was missing.
- Orders first use the next minute's interval, never the confirmation candle. Outcomes stop at each fold boundary or the first missing M1 bar; open signals are not transferred between folds or assigned artificial closing returns.
- Execution is a bid-OHLC simulation with 0.30 USD/oz fixed spread, 0.05 USD/oz adverse slippage per fill, and 50% sized at TP1. The measured spread filter is separate from this execution assumption.
- Win rate and R use only completed trades with a finite result; expiry and unresolved records are not losses.

## Inputs

- M1 candles: `xauusd-M1.csv (SHA-256: 190d1b6c3dd025ec0b480dc62f37574b875f646de8715bb3bc4b3b6023e7c32a)`
- H4 candles: `xauusd-H4.csv (SHA-256: d52cb45856725d5a011f794824f15cdbd2c87f57a1bc389fbbdebd857c44bdda)`
- D1 candles: `xauusd-D1.csv (SHA-256: 235ab3a8c715b07ed252d75730553e77a92d4379d92b67e923c398b8d77bc1a8)`
- H1 candles: `xauusd-H1.csv (SHA-256: 1bd11eb97d17edddbc39111d5879190a6f84b5253c1e87d45f5d067d95bdc770)`
- News snapshots: `Not supplied`
- Bid/ask observations: `Not supplied`
- Frozen strategy: `strategies.json (SHA-256: 957a41c6a6e8c244d5b35b8e9548ca408a4ee41049786e98410c82f204109874)`
