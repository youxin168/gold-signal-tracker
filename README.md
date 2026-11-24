# Signal Tracker — XAUUSD testing journal

Testing and research only. This project does not place trades, connect to live
broker accounts, or give financial advice. No return or win rate is promised.
The tracker runs six frozen Claude strategies for XAUUSD, accepts registered
external rules and operator CSV signals, and publishes a testing-only journal,
scoreboard, and evidence-scoped comparison site. The GitHub Actions runner
and Telegram alerts are implemented but off until you configure them.

### No-account gold scanner

The Replit preview can use **biquote** without an account, API key or deposit.
While the workspace and its `Gold scanner (preview)` workflow are running, the
scanner runs about every five minutes and refreshes the preview's published
file. Preview is not a 24/7 deployment. Run an immediate update with
`uv run --locked signal-tracker preview-scanner --once` (not while the
background workflow is already running). Select versions for the preview
workflow with repeatable `--strategy CLD-SCA-01-v2` arguments; if omitted,
the runner evaluates all active versions in their eligible sessions. The website's
expand/collapse toggles only change which rules are visible.

The Biquote versions use indicative XAUUSD midpoint candles, report their own
results, and leave all original v1 gold rules and backtests untouched.
The entry filter uses observed bid/ask spreads and the provider's high-impact
US schedule. It pauses when that schedule is missing, looks incomplete, or
has nearby events with uncertain times. The calendar is not independently
reviewed. Simulated fills use an assumed $0.30 spread around the midpoint
and $0.05 slippage, not tick-by-tick execution. Retention is limited; a missed
minute can leave a result unresolved. Trend Pullback and Session Breakout
now use **H1 EMA150** for Biquote in v3, so they can warm up within the
provider's roughly 168-bar window. They still look for entries on M15 during
their original sessions. The EMA200 versions are retained separately and no
longer scan Biquote. The preview continues to cache closed H1 candles
privately; neither the raw feed nor that file is published. These are
experimental tests only.

For public GitHub Pages hosting, use the existing GitHub setup below with
`TRACKER_ENABLE_LIVE=true` and `TRACKER_LIVE_FEED=biquote`. No OANDA secrets
or manual reviewed calendar are needed in that mode. The GitHub runner
does not store raw hourly data on its public state branch. The two
Intraday v3 strategies can use the current closed H1 window when it has at
least 150 bars. Pages and the Replit preview keep separate testing journals.

## Get started

1. Use Python 3.13 and run the commands below from the project root.
2. Install the Python package: `python -m pip install -e .` on your own machine,
   or run the examples with `uv run signal-tracker` instead of `signal-tracker`
   if you use `uv`. Pandas is the only direct Python dependency.
3. List the strategy versions (all six Claude rules are frozen):

   ```sh
   signal-tracker strategies
   ```

4. Use one of the two data sources below. Record which source you used; these
   feeds are not interchangeable.

### Historical files: HistData (no signup or API token)

1. Open [HistData's free download page](https://www.histdata.com/download-free-forex-data/)
   and select **Generic ASCII → 1 Minute Bar Quotes → XAU/USD**, then a year or
   month. For the example below use [January 2024](https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/xauusd/2024/1).
2. Save the original ZIP under `generated-artifacts/`. The command also accepts an
   original extracted `DAT_ASCII_XAUUSD_M1_*.csv` with the provider's filename.
3. Export closed UTC candles with indicators:

   ```sh
   signal-tracker candles --provider histdata --pair XAUUSD --timeframe M15 \
     --start 2024-01-03T00:00:00Z --end 2024-01-04T00:00:00Z \
     --file generated-artifacts/HISTDATA_COM_ASCII_XAUUSD_M1_202401.zip \
     --indicators --output generated-artifacts/xauusd-histdata-m15.csv
   ```

   Repeat `--file` for non-overlapping downloads. Request a longer window for
   indicator warm-up: one day of M15 cannot warm up EMA200. An output path must
   not already exist.

### Automated fetch: OANDA practice candles (optional)

1. If a free **v20 practice** account and XAU/USD are offered in your region,
   create the practice account and generate a personal token using
   [OANDA's authentication instructions](https://developer.oanda.com/rest-live-v20/authentication/).
   A live account or deposit is not needed for this adapter. Do not create or
   deposit into one if the free practice option is unavailable.
2. Set `OANDA_API_TOKEN` in your process environment or secret manager. Do not
   paste it into code, chat, logs, or a repository. The adapter only sends candle
   read requests to the practice host.
3. Run:

   ```sh
   signal-tracker candles --provider oanda --pair XAUUSD --timeframe M15 \
     --start 2024-01-03T00:00:00Z --end 2024-01-04T00:00:00Z \
     --indicators --output generated-artifacts/xauusd-oanda-m15.csv
   ```

   The provider allows up to 5,000 candles per request. The fetcher uses smaller
   windows, fetches them sequentially, and reports rate limits or permission
   errors instead of swapping feeds. Availability and delay were not verified
   with an authenticated practice account. This integration is not needed to
   use historical replay offline.

## Data contract and limits

- The default instrument is **XAUUSD spot**. There is no gold-futures fallback.
  Enable EURUSD or GBPUSD in `config/markets.json`; the provider mappings are
  already there. Available timeframes: M1, M5, M15, H1, H4, and D1.
- Bar open and close times are explicit and in UTC. Windows must be aligned to
  the selected timeframe and cannot end in the future. A candle is not exposed
  until its close time is at or before the requested cutoff. The OANDA adapter
  also rejects candles the provider marks incomplete. The backtest joins
  higher timeframes by **close time**, not open time, and never uses the
  price range of the signal candle to simulate a later fill.
- [HistData documents](https://www.histdata.com/f-a-q/) that M1 candles are bid
  prices in fixed Eastern Standard Time (UTC−5, no daylight-saving adjustment).
  The importer converts to UTC before aggregation. It drops M5, M15, and H1
  buckets with missing source minutes. It retains H4 and D1 buckets with
  observed data and exposes minute counts because normal rollover and
  weekend/holiday closures can shorten these buckets. Treat reduced coverage
  as a quality flag, not proof that a bucket is safe for outcome tracking. Missing
  slots are reported, never filled. Exactly repeated rows within one archive
  are logged and discarded; conflicting prices or overlapping input files
  fail validation. `volume` may be zero in files and is an activity count
  in OANDA candles, not consolidated market volume.
- HistData is a batch archive, not a live feed. Multi-year M1 downloads can
  support historical M5/M15 research if coverage checks pass. Neither a
  continuous two-year window nor current-year completeness has been verified.
  Periods with gaps can bias both which setups are observed and how trades
  appear to finish. M5 is especially sensitive to gaps, spread, slippage, and
  unknown price order inside each candle, so both scalping strategies are
  experimental. OANDA practice access, available lookback, data delay, and
  coverage may differ by region and instrument. Treat this as indicative
  broker-source pricing, not a consolidated quote or execution record.
- Bid OHLC has no observed spread or ask-side fill data. Neither a bid touch nor
  a candle crossing a level proves execution. Phase 2's shared checker uses a
  documented approximation. Check provider terms before redistributing raw data.
- EMA is seeded with a simple average. ATR, RSI, and ADX use Wilder smoothing.
  Flat RSI is 50; flat ADX is 0 after warm-up. Donchian highs/lows exclude the
  candidate candle. Unknown warm-up values stay blank; no indicators use a
  future observation. Indicators advance on observed rows, not elapsed time.

## Phase 2: scan and check XAUUSD signals

Use `candles` above to export **M15, H1, and M1 from the same provider**. Include
at least 200 closed H1 bars for EMA warm-up and at least 23 closed M15 bars for
the pullback indicators. A `scan` checks one decision time. A `check` can
advance every eligible unresolved record in the selected mode; invoke it again
with newer M1 candles to continue tracking. Neither command runs on a schedule
in this phase.

Before scanning, supply a JSON file with `coverage_start_utc`,
`coverage_end_utc` (exclusive), and an `events` list. Each event has `at_utc`,
`currency` (e.g. `USD`), and `impact` (e.g. `HIGH`). An empty list asserts there
are **no events** in the covered period, not that you haven't checked. Supply
coverage and events from a calendar you have verified. Phase 2 does not fetch
news. Supply the observed ask minus bid and its timestamp with `--spread` and
`--spread-at`. The scan skips when a required observation is missing or stale.

```sh
# Example historical decision time; use corresponding verified data files.
signal-tracker scan --m15 xauusd-m15.csv --h1 xauusd-h1.csv \
  --calendar news.json --spread 0.30 --spread-at 2024-01-03T12:00:00Z \
  --replay-as-of 2024-01-03T12:00:00Z

signal-tracker check --m1 xauusd-m1.csv --replay-as-of 2024-01-04T00:00:00Z
signal-tracker signals --mode REPLAY
```

For a prospective `LIVE` scan, omit `--replay-as-of`, use current OANDA practice
candles, verified news coverage, and a fresh spread observation. `LIVE` means
recorded prospectively against a practice feed, **not** a real trade or
guaranteed real-time quote. `REPLAY` is for single-time historical checks; it
never appears in `LIVE` results and is not a Phase 3 backtest. The commands
default to `generated-artifacts/signals.db`; pass `--db` to choose another
SQLite file. Keep this file if you need the research record. Publication and
the initial outcome are saved atomically. Later checks advance only the
outcome, not the original signal. Re-scanning a recorded candle cannot create
a duplicate in the same mode.

### Frozen CLD-INT-01-v1 decision rules

- Direction is the latest eligible H1 close above/below EMA200; equality
  skips. Only H1 candles closed by the M15 setup close are eligible. The most
  recent three M15 closes must be consecutive and the scan must run less than
  one M15 interval after its last close.
- The middle M15 candle must touch EMA21 or EMA50 as known **before** it
  opened, and its RSI(14) must be a strict local low in 40–50 for BUY or local
  high in 50–60 for SELL. The third close must reclaim the touched EMA in the
  trend direction. `PREPARE` means the latest candle shows the pullback and
  RSI moving into the band, but no turn is confirmed; it has no levels, is
  never a stored signal, and is not sent externally.
- Entry is the confirmation close; SL is 1.5× M15 ATR(14) from entry, rounded
  to the nearest gold cent. TP1 and TP2 are 1R and 2R based on the rounded
  entry-to-SL distance. Entry expires after four hours. The cap is two
  published signals per UTC day per mode.
- Scan only on weekdays during 08:00–17:00 local London or New York time
  (daylight saving applies). In an overlap, label it London. Skip within 30
  minutes either side of high-impact USD/XAU news, or if coverage is unknown;
  skip spreads above $0.50/oz or measurements older than five minutes.
  These gates apply to issuing setups, not to managing their outcomes.

### Shared result-checking assumptions

- The checker uses closed M1 candles starting at the first full minute after
  publication (an exact minute boundary is eligible). Buy entries and sell
  exits use estimated ask (bid + $0.30/oz); sell entries and buy exits use bid.
  Entry requires the resulting candle range to contain the level. A gap over
  the price alone is not a fill. Timestamps represent the confirming bar close,
  not the exact price-touch time. Partial issue or expiry minutes are excluded
  because OHLC cannot locate touches inside them.
- Stop wins any same-candle stop/target conflict. On the fill candle only the
  stop is eligible, since a target could have touched before entry. An adverse
  gap through an existing stop fills at the worse opening quote. When both
  targets are touched later and no stop is hit, take both.
- Close half at TP1 and move the remaining stop to entry starting with the
  next M1 candle. `TP1` stays open; the final result is either `TP2` or `BE`
  for the remaining half. If that stop and TP2 both touch, `BE` takes
  precedence. `BE` describes the planned stop level, not a zero net result.
  Include $0.05/oz adverse slippage on entry and each exit (applied per unit
  to its weighted share). Divide net P&L by the original entry-to-SL distance
  to get R. An unfilled entry that expires has no R result. Once filled, the
  entry deadline does not close the position.
- Missing M1 bars, including gaps across market closures, halt the checker at
  the first missing minute. It does not infer an outcome or an expiry across
  that gap, and resumes from the same checkpoint if coverage is supplied.
  This is intentionally strict; there is no holiday/closure-aware skip yet.
  The assumed spread, slippage and sizing are in the frozen configuration
  and are not measured transaction costs.

## Phase 3: chronological XAUUSD backtest

The [2023–2024 BACKTEST report](reports/xauusd-cld-int-01-2023-2024.md) covers two
years of real HistData bid prices, with late 2022 candles for warm-up. It reports
decision coverage and pre-filter technical candidates, but **cannot estimate
performance**: the run had no verified point-in-time news snapshots or
observed historical spreads. It does not count these candidates as signals.

### Reproduce the audit or run with complete data

1. Download HistData's annual XAUUSD Generic ASCII M1 archives for
   [2022](https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/xauusd/2022),
   [2023](https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/xauusd/2023),
   and [2024](https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/xauusd/2024)
   and put them in `generated-artifacts/phase3/`. Do not add raw source data to the repo.
2. Export the same price window in all three timeframes:

   ```sh
   d=generated-artifacts/phase3
   for tf in M1 M15 H1; do
     signal-tracker candles --provider histdata --timeframe "$tf" \
       --start 2022-12-01T00:00:00Z --end 2025-01-01T00:00:00Z \
       --file "$d/HISTDATA_COM_ASCII_XAUUSD_M1_2022.zip" \
       --file "$d/HISTDATA_COM_ASCII_XAUUSD_M1_2023.zip" \
       --file "$d/HISTDATA_COM_ASCII_XAUUSD_M1_2024.zip" \
       --output "$d/xauusd-$tf.csv"
   done
   ```

3. Run the audit. To try to estimate performance, add
   `--calendar path/to/snapshots.json --quotes path/to/quotes.csv` with verified
   historical data as described below. Leave them out to reproduce the
   supplied report. Use new output paths on each run.

   ```sh
   signal-tracker backtest --m1 "$d/xauusd-M1.csv" --m15 "$d/xauusd-M15.csv" \
     --h1 "$d/xauusd-H1.csv" --start 2023-01-01T00:00:00Z \
     --end 2025-01-01T00:00:00Z --output "$d/report.md" --json-output "$d/report.json"
   ```

4. Read both folds separately. The report shows coverage, fills, expiries,
   unresolved records, and net R metrics when outcomes are available. Missing
   values are shown as **Not estimable**, and tiny or partially observed
   samples are flagged. Individual simulated records only appear in the
   optional JSON report, never in the LIVE/REPLAY database.

**Historical spread CSV:** Use `observed_at_utc,pair,data_source,bid,ask`. The
feed label must match the three candle CSVs. Use synchronous quotes from that
source, not a difference between two aggregated bar highs/lows. HistData's
Generic ASCII **tick** archive includes ask prices, but its M1 archive does
not. Tick downloads, completeness checks, and conversion to this smaller
quote CSV are not automated. If sampling ticks for import, keep the original
timestamp of the last available tick at or before each decision. The filter
uses only an observation at most five minutes old and never uses the fixed
execution spread as filter evidence.

**Point-in-time news JSON:** Use a top-level `provenance` string and `snapshots`
array. Each snapshot has `captured_at_utc`, `coverage_start_utc`,
`coverage_end_utc` (exclusive), and `events`. Event fields are `at_utc`,
`currency` (uppercase), and `impact` (`HIGH`, `MEDIUM` or `LOW`). The runner
uses the latest snapshot captured **by** each decision, only if it covers both
sides of the news window. Capture timestamps and coverage must come from
verified archives. A calendar downloaded today must not be relabeled as
known two years ago. No needed event data is assumed absent just because
the calendar is missing.

**No look-ahead or tuning:** The 70/30 split is chronological, rounded down
to midnight UTC; the same frozen parameters apply in both folds. Historical
indicators carry earlier state into the out-of-sample fold but never use
later bars. Each order can first use a minute opening at or after the issue
time, and its outcome is evaluated only within its own fold. The engine does
not use later candles to settle open positions from the earlier fold, and
does not mark unresolved trades as wins or losses.

## Phase 4: scoreboard and analyst

The [in-sample scoreboard](reports/xauusd-scoreboard-in-sample.md) and
[out-of-sample scoreboard](reports/xauusd-scoreboard-out-of-sample.md) are based
on the real 2023–2024 price audit. Both are **unranked and not estimable**:
no signal had enough evidence to pass the required filters. Technical
setups are not signals and do not enter any performance denominator.

```sh
# Read the local database without editing it or creating it if it doesn't exist.
signal-tracker scoreboard --mode LIVE

# Only report on replay records; optional exports include the detailed tables
# and the points for equity curves.
signal-tracker scoreboard --mode REPLAY --output generated-artifacts/replay-scores.md \
  --json-output generated-artifacts/replay-scores.json

# Choose exactly one fold. Optional --h1 takes the original matching H1 CSV.
signal-tracker scoreboard --mode BACKTEST --fold out-of-sample \
  --backtest-report reports/xauusd-cld-int-01-2023-2024.json \
  --output generated-artifacts/gold-out-of-sample-scores.md
```

### How scores are calculated

- **Counts and denominators:** Each stored signal counts once. Fill rate =
  `filled / (filled + expired)`; pending/unresolved entries are not failures.
  The JSON also exposes filled divided by all issued signals as an observed
  lower bound. Filled but open and TP1 partials are not completed trades.
  Win rate is positive net R divided by completed trades, including flat
  outcomes in the denominator. Expectancy and average R are both the sample
  mean of completed net R. Profit factor is gross gains ÷ absolute gross
  losses; positive gains with no losses are flagged instead of returning an
  infinite JSON number. With neither, it is not estimable.
- **Risk:** Equity starts from zero and adds completed net R by close time.
  Same-time closes are combined for equity and maximum drawdown; the losing
  streak uses close time and stable signal ID for ties and resets at a flat
  or win. Drawdown is realized-only, not maximum intratrade or portfolio heat.
  A style total pools all its signals, including overlapping strategies; it
  is not an independent or capital-constrained portfolio.
- **Breakdowns:** Use issue-time Asia (00:00–07:00 UTC), London or New York
  (08:00–17:00 local weekdays, DST aware; London takes overlap), or Other.
  Additional groups use UTC weekday, BUY/SELL, and regime. A matching H1
  export classifies the last candle closed by issue time using ADX(14)
  (trending ≥25, ranging <25). Missing, stale, or not-warmed-up ADX is
  **Unknown**. A backtest will accept only the H1 input with the original
  report fingerprint.
- **Evidence:** Badges refer to **completed trades**: 0–29 Too early,
  30–99 Weak evidence, and 100+ Usable. Reports include a nominal 95% Wilson
  interval for win rate and a 95% t interval for expectancy using UTC
  close-day clustered errors, with at least two close days required.
  These are descriptive, not forecasts; Wilson assumes independence, and
  clustering does not account for dependence across days or data selection.
- **Ranking and analyst notes:** Rank only within the same style and scope,
  when at least two strategies each have 100 completed trades and comparable
  execution assumptions. Rank lexicographically on higher total R, higher
  expectancy, lower drawdown, then higher profit factor. Exact ties share a
  rank; win rate is displayed last and never breaks ties. Analyst notes flag
  missing inputs, unresolved results, weak samples, and profit dependent on
  the best one to three trades. Best/worst sessions are descriptive and
  require two populated sessions with at least 10 completed trades each.
- **Keep cohorts separate:** A LIVE or REPLAY report reads only that mode.
  If multiple price feeds are present, specify `--data-source`. To compare
  backtests, repeat `--backtest-report` with different strategies from the
  same fold dates, feed, M1 file, filter inputs and execution assumptions.
  No past reports are overwritten and no mixed live/backtest standings are
  produced.

## Phase 5: website, GitHub Actions, and Telegram

### Use the website now

Open **Preview** to see the six built-in XAUUSD strategies and the separate
Swing Retest experiment on the Biquote preview. Expand any card
to see its active test signals or the last published one. **BUY**, **SELL**,
**Hide waiting**, and individual hide buttons change the view, not the
scanner. **Today vs yesterday** compares equal elapsed time in Cambodia and
includes hidden strategies. It counts signals by issue time and completed R
by close time; it is not a ranking. The page checks for a new published file
about once a minute while open; **Refresh** also reads that file, not live
market prices. Switch between **Cards** and **Sheet** on the home page.
**History** uses a worksheet with separate live, replay, and backtest views
and a strategy-version filter. **All signals** opens the full log.
**Scoreboard** and **Compare** sit under **More**.

**Optional TP3 on existing strategies:** For new signals published by the
scheduled scanner, it looks at up to 20 already-closed trend-timeframe
candles for the nearest confirmed swing high (BUY) or swing low (SELL).
It must have a consecutive closed candle on both sides. The price is set
one tick inside that level, at least 0.25R beyond TP2 and no more than 5R
from entry. Otherwise the site shows **None**. An optional TP3 uses the
same fill, stop and breakeven rules, and can remain under watch after TP2
closes the original result. It doesn't change TP1/TP2 allocations, realized
R or the scoreboard. Missing minute candles leave the watch unconfirmed;
targets are not credited in the entry minute or when they share a minute
with the stop in force. A suggestion is not a safety or profit claim.
Earlier records are not backfilled. Sweep Reversal `CLD-SCA-02-v3` is
retired; its existing outcomes remain in History, not the active scoreboard.

**Fixed-SL orders:** For new scanner signals, simulate one equal-size
order per available TP, all with the same entry and original SL. These
stops do not move after another order hits its target. The worksheet
shows each order's gross R, the sum of closed orders (R uses one order's
initial risk), and that sum divided by the number of orders (relative to
total starting risk). Open orders contribute no result. A stop is modeled
at −1R before costs; this is not a claim that a stop would fill at its
level. Spread affects which prices count as touches. Gaps in coverage stop
the simulation until the missing minute is available. On the same minute,
SL wins over a target, and a target is not credited on the entry minute.
This separate experiment does not change Trade result, the scoreboard, or
older records.

**Swing Retest · Signal Tracker (`OWN-SWG-01-v1`, ST TEST):** The XAUUSD
preview scanner looks for a closed H1 breakout of the previous 12 consecutive
H1 bars in the direction of the closed H4 EMA50 bias. The first retest must
hold the level on a close within three bars. Only the following bar can
confirm, by staying on the breakout side and closing beyond the retest wick.
An unconfirmed, interrupted, or failed setup cannot publish. Common news
and spread gates still apply. The stop is beyond the retest wick and
ATR-based, with targets at 2R and 3R. The eight-hour expiry is for unfilled
entries only, not a forced exit. No dollar-distance filter is used. Existing
strategies and their results are unchanged. This midpoint variant is
forward-tested: the bid-only archives cannot provide a comparable backtest.

To rebuild the published file locally:

```sh
uv run --locked signal-tracker export-site
```

Only export records you intend to share publicly. The exporter omits private
signal notes, credentials, calendar contents, and chat IDs. Do not copy a
personal SQLite database into the public directory.

### Publish a free GitHub Pages snapshot

1. Push the project to a **public GitHub repository** you control. Review what
   will be public before pushing; use repository **Secrets** for all credentials.
2. In GitHub **Settings → Pages**, set **Source** to **GitHub Actions**.
3. In **Settings → Secrets and variables → Actions → Variables**, add
   `TRACKER_ENABLE_PAGES` with value `true`. Leave the live and Telegram flags
   unset if you only want the historical reports.
4. In **Actions → Gold signal tracker**, choose **Run workflow** on the
   default branch. When deployment succeeds, open the link from the job.
   The Replit preview is separate; GitHub does not update its local snapshot.

### Enable prospective scans and outcome checks (optional)

1. If a free OANDA **practice** account with XAU/USD is available to you, add
   `OANDA_API_TOKEN` and `OANDA_PRACTICE_ACCOUNT_ID` under GitHub Actions
   **Secrets**. The code makes candle and quote GET requests to the practice
   host only. Do not use a live account.
2. Supply `SIGNAL_CALENDAR_JSON` as a repository secret. Use a calendar you
   actually reviewed from a trusted source, with true UTC coverage for high-impact
   USD/XAU events. Record the real verification time. Adapt
   [the calendar format](config/calendar.example.json); do not upload the
   example as current evidence, reuse a stale review, or assume an empty
   `events` list means no news. Review again as schedules change and at least
   every 24 hours. No free verified calendar provider is bundled.
3. Set repository variable `TRACKER_ENABLE_LIVE=true` and run the workflow
   once manually. Unset the flag to pause. Removing only the calendar
   pauses *new* signals, but a practice token can still check existing outcomes.
4. Understand persistence before enabling: the runner keeps a dedicated
   `signal-tracker-state` branch (no force pushes) holding the automation
   SQLite journal and status so a new runner can resume. **This branch is
   public in a public repository.** It contains testing records and delivery
   acknowledgements, not the bot token, recipient details or news JSON.
   Never connect it to a private journal. Keep the branch as long as you need
   signal history and duplicate detection.

The schedule requests a run approximately 2 minutes after each M5 close on
UTC weekdays. Pages builds are requested every 15 minutes and when you run the
workflow manually. M15 and H4 rules scan only in the first five minutes after
their eligible close. Actual start times and Pages rollout can lag or be skipped; stale
setup bars and unavailable inputs do not create backdated results. Missing
M1 can leave outcomes unresolved, including across closures. Only the latest
checkpoint status from each run is queued for alerts; intermediate changes
inside a batch may not send separately. GitHub can disable inactive scheduled
workflows; check Actions and the timestamp on the site. This is a best-effort,
free testing setup, subject to public GitHub Pages and Actions limits and
practice data availability. It is not intended for real orders, timing-sensitive
scalping, or continuous market coverage.

### Send new Preview signals to a public Telegram channel

1. Create a bot using `/newbot` in [@BotFather](https://t.me/BotFather).
   Add the bot to your public channel as an admin with **Post Messages**
   permission. No extra admin permissions are needed.
2. In Replit Secrets add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
   Use the channel's `@username` or public `t.me` link for `TELEGRAM_CHAT_ID`.
   A numeric channel ID is also accepted if the channel is public. Don't paste
   the token into a chat, log, command, screenshot, or code file.
3. To verify the channel and posting permission without sending a message:
   `uv run --locked signal-tracker check-telegram-channel`.
4. Only when ready for public posts, set the Replit environment variable
   `TRACKER_PREVIEW_TELEGRAM=true` and restart **Gold scanner (preview)**.
   This is off by default. Remove the flag and restart to pause delivery.

Preview posts newly published test signals, then replies to that same post
with the confirmed original result and the separate Fixed-SL final result.
It does not post PREPARE, entry or individual target updates, older signals
without a recorded post, or results that rely on missing prices. Missing
price coverage lasting 15 minutes triggers one **RESULT UNCONFIRMED** reply
per posted signal, rather than silence or a guessed win/loss. If the missing
history is recovered, confirmed final replies can still follow. An unfilled
expiry has no R and does not produce a Fixed-SL result. A reply is never
sent as a standalone message if the original post is unavailable.
Each price uses separate Telegram inline code for copying;
the displayed target pips and R are planned distances before costs.
Issued and entry-expiry times use Cambodia time (ICT).
By default it includes all three styles from CLD and Signal
Tracker's OWN strategies. Adjust `config/telegram-preview.json` to opt out
of styles, sources, or either final result. New-signal alerts can retry while that runner is
running and the alert is less than 15 minutes old. Alerts from before
the current runner started are not sent as new signals. Confirmed replies
to existing posts can resume after a restart from the private preview journal.
A failed Telegram request
doesn't stop the scanner or the website from updating. Telegram can
still duplicate a message if delivery succeeds but its acknowledgement
is lost. Preview runs only while its scanner and workspace are active;
this is not a 24/7 alert setup. Do not run another sender against the
same feed and channel unless you want messages from both journals.

### Let visitors connect their own Telegram channel or group

Open **Telegram alerts** on the website and select **Connect in Telegram**.
Add the shared Signal Tracker bot as an administrator in your channel or
group first; a channel must grant **Post Messages**. In your private chat
with the bot, select **Choose channel** or **Choose group**. Telegram verifies
the account and the bot checks both parties' posting rights. The bot never
asks for your password, token, or manually pasted chat ID.

One destination per Telegram account, with 25 connections for this free
testing setup. Use **Manage in Telegram** to see the current destination,
`/connectalerts` to replace it, or `/stopalerts` to disconnect. Switching
does not affect the main channel. It sends only new signals to the new
destination; it does not replay posts or results from a previous connection.

The website is the starting point; confirmation and settings changes take
place inside Telegram. No republish is needed for those changes. The
subscriber list stays in the private preview SQLite journal, not in the public
snapshot or GitHub. The site can be published separately, but the Replit
**Gold scanner (preview)** workflow must stay running for subscription
commands and alerts. Enable the worker with `TRACKER_TELEGRAM_SELF_SERVICE=true`
alongside `TRACKER_PREVIEW_TELEGRAM=true`, then restart the scanner. Only one
process may poll this bot. If a webhook is configured, the subscription worker
won't take over. Keep `BOT` in the website Telegram page in sync if you replace
the shared bot itself, rather than just changing a destination.

### Enable Telegram on GitHub Actions (optional)

1. In Telegram, message the official [@BotFather](https://t.me/BotFather),
   send `/newbot`, and choose a name and username. Put its token in Actions
   **Secrets** as `TELEGRAM_BOT_TOKEN`. Never share it in chat, source files,
   screenshots, or logs.
2. Choose one chat. For a test channel, add the bot as an admin with permission
   to post. For a public channel, use `@channelname`. For a private chat, first
   open the bot and tap **Start**; use the [Bot API `getUpdates`](https://core.telegram.org/bots/api#getupdates)
   from a trusted local client and read `message.chat.id` without logging or
   sharing the request URL. For a private channel, read `channel_post.chat.id`.
   Store the ID or handle as Actions secret `TELEGRAM_CHAT_ID`.
3. Edit [`config/telegram.json`](config/telegram.json). `styles`, `sources`,
   and `events` are allowlists; an empty list sends nothing. The default sends
   CLD intraday alerts only. PREPARE means a forming setup and contains no
   entry, stops or targets. It is never counted as a signal or trade.
4. Set repository variable `TRACKER_ENABLE_TELEGRAM=true` when ready. The
   runner sends only recent, prospective events and does not broadcast
   BACKTEST or REPLAY. One destination is supported in this version. A crash
   after Telegram accepts a message but before checkpointing can still produce
   a duplicate; signal alerts include a stable ID.

## Phase 6: six gold rules, six separate historical audits

All six use the shared conservative result checker. No parameters were
selected on the basis of these audits. Historical tests split the 2023–2024
window at 2024-05-26 UTC (about 70/30). The numbers below are **technical
candidates before the evidence filters, not trades**.

| Rule | Timeframes | In-sample candidates | Out-of-sample candidates |
| --- | --- | ---: | ---: |
| [Micro Pullback](reports/xauusd-cld-sca-01-2023-2024.md) *(experimental)* | M5 / M15 | 2,498 | 1,246 |
| [Sweep Reversal](reports/xauusd-cld-sca-02-2023-2024.md) *(experimental)* | M5 / M15 | 5,134 | 3,119 |
| [Trend Pullback](reports/xauusd-cld-int-01-2023-2024.md) | M15 / H1 | 500 | 261 |
| [Session Breakout](reports/xauusd-cld-int-02-2023-2024.md) | M15 / H1 | 110 | 54 |
| [Daily Trend Pullback](reports/xauusd-cld-swg-01-2023-2024.md) | H4 / D1 | 53 | 35 |
| [Channel Breakout](reports/xauusd-cld-swg-02-2023-2024.md) | H4 / D1 | 79 | 61 |

Both folds for every strategy had **zero qualifying trades**: the required
timestamped spread and news inputs were not available. No strategy can be
ranked on these files. M5 is reconstructed from complete M1 bid aggregates,
not verified bid/ask ticks or forward execution. H4 and D1 use UTC archive
buckets with at least 180 and 1,320 observed minutes respectively, so normal
market breaks can be represented without accepting nearly empty bars. Very
short holiday sessions can be dropped; the counts do not establish tick
coverage within a retained bar.

Use `backtest --strategy CODE` with the matching closed candle files (`--m1`
plus `--m5 --m15`, `--m15 --h1`, or `--h4 --d1`), the same dates, and a new
`--output`/`--json-output` path. Download 2022 as warm-up before the 2023–2024
window for D1 EMA200. Supply `--h1` when creating any report that should
support an optional fingerprint-verified ADX regime breakdown. `scan
--strategy CODE` takes the same setup timeframes;
the optional scheduled flag `scheduled-tick --strategy CODE` restricts which
automated versions are evaluated for a local run. A prospective scan is not
a signal until its rule and spread/news gates pass.

## Phase 7: external strategies and comparisons

### Register new rules or a manual journal

1. Copy the [rules example](config/external-rules.example.json) or
   [manual example](config/external-manual.example.json). Use a unique
   `EXT1`, `EXT2`, or `OWN` code, in the same `SOURCE-STYLE-NUMBER-VERSION`
   format. Do not publish descriptions containing private information.
2. For a rules-based entry, choose the CLD template of the same style that
   actually matches the source's written rules. Supported settings are
   `expiry_minutes`, `max_signals_per_utc_day`, `take_profit_r`, and—where
   applicable—`atr_multiple` or `lookback_closed_candles`. `public_rules` is
   descriptive, not executable. If a source needs a different setup, add a
   tested rule implementation rather than misrepresenting the template.
3. Run `uv run --locked signal-tracker register-external --file your-rules.json`.
   This adds a frozen definition to `config/strategies.json`. Changing rules
   requires a new version. Commit the definition if the GitHub runner should
   use it. Automated variants use the same prospective evidence gates.

### Record manual signals

Copy [the header-only CSV](config/external-signals.example.csv) and enter the
new signal levels. Use a stable, public `external_id`, not a private user ID.
Only one freshly published row per strategy is allowed per LIVE import.

```sh
# Prospective testing publication. Leave issued_at_utc blank.
uv run --locked signal-tracker import-signals --file my-new-signals.csv \
  --mode LIVE --data-source OANDA_PRACTICE_BID --confirm-new-publication

# Historical evidence. Enter the original timezone-aware issued_at_utc.
uv run --locked signal-tracker import-signals --file my-past-signals.csv \
  --mode REPLAY --data-source HISTDATA_ASCII_M1_BID

# Update the local preview from the journal.
uv run --locked signal-tracker export-site
```

LIVE records use the tracker’s current UTC time for both issue and recording.
Only use that mode when first publishing the signal now. The tracker does
not verify an outside publication date; if it was posted earlier, use
REPLAY. LIVE rejects supplied dates and IDs already seen in REPLAY. A
repeated ID with identical terms is ignored; an attempt to change its
entry, stop, targets or other immutable terms is rejected.

For the GitHub journal, use **Actions → Gold signal tracker → Run workflow**:
enter one CSV row without its header or timestamp in `manual_signal`, tick
the first-publication confirmation, and run it. The row will be public; do
not enter credentials or private information. The configured runner and
shared checker track the outcome under the OANDA practice feed. Local REPLAY
uses `check --replay-as-of` with M1 candles from the chosen feed.

### Compare versions

Use **Compare** to choose the evidence cohort and two strategies of the same
style. For a rules-based historical comparison, run the external backtest
on the bundled audit basis and add it with `export-site --backtest-report PATH`.
Comparable reports must share date boundaries, price feed, M1 file
fingerprint, timestamped spread/news inputs, and execution assumptions.
LIVE and REPLAY compare only the overlap of recorded UTC issue dates; this
does not prove continuous coverage. A leader is withheld for manual entries,
incompatible assumptions, ties, or fewer than 100 completed trades on either
side. The site never treats an observed leader as a forecast.

## Structure and versioning

| Location | Purpose |
| --- | --- |
| `config/strategies.json` | Six strategy versions, shared filters, PREPARE definition |
| `config/markets.json` | Enabled pairs and feed-specific symbols |
| `src/signal_tracker/` | Python data, indicators, strategy, checker, SQLite, backtest, scoreboard and CLI |
| `tests/` | Python unit tests; no token or internet access required |
| `reports/` | Historical backtest and scoreboard reports, explicitly separate from LIVE |
| `artifacts/signal-tracker/` | Static gold journal, history, dashboard and method |
| `.github/workflows/gold-tracker.yml` | Opt-in GitHub Actions schedule and Pages publishing |

All six built-in rule versions are frozen, not validated for profitability.
A rule or assumption change requires a new strategy code
(e.g. `CLD-INT-01-v2`) with an explicitly supported
implementation and a fresh performance record. The database snapshots the
rules and rejects edits under an existing code.

Run unit tests from the project root:

```sh
python -m unittest discover -s tests -v
# Or: uv run python -m unittest discover -s tests -v
```
