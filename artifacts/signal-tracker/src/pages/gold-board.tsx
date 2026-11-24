import { useEffect, useState } from "react";
import { ArrowDownRight, ArrowRight, ArrowUpRight, Bell, Check, ChevronDown, Eye, EyeOff, LayoutGrid, RefreshCw, RotateCcw, Sheet, SlidersHorizontal, X } from "lucide-react";
import { Link } from "wouter";
import { DeskHeader } from "@/components/desk-header";
import { GoldOpenSignals } from "@/components/gold-open-signals";
import { EMPTY_DISTANCE, StyleSelect, TargetDistanceInputs } from "@/components/gold-signal-filters";
import { GoldSignalSheet } from "@/components/gold-signal-sheet";
import { PARALLEL_NOTE, ParallelTargetResult } from "@/components/parallel-target-result";
import { SiteTestBadge } from "@/components/site-test-badge";
import { SnapshotGate } from "@/components/snapshot-gate";
import { StrategyToggle } from "@/components/strategy-toggle";
import { useSnapshot } from "@/hooks/use-snapshot";
import { useTickingNow } from "@/hooks/use-ticking-now";
import { fmtAge, fmtDate, fmtR, fmtScalar, hitLevels, rTone, STYLE_NAMES } from "@/lib/format";
import { cambodiaDateTime } from "@/lib/history-results";
import { compareGoldDays, filterGoldCards, getGoldDashboard, getGoldOpenSignals, goldTargetMetrics, type GoldCardFilters, type GoldStrategyCard } from "@/lib/gold-board";
import { goldSignalStatus, publishedSignalState, STATE_LABEL, STATUS, TP3_LABEL, TP3_NOTE, TP3_WATCH_LABEL } from "@/lib/gold-labels";
import { parseTargetRange } from "@/lib/gold-targets";
import type { PublicSignal, Snapshot, Style } from "@/lib/public-snapshot";
import { cn } from "@/lib/utils";

const STATE_NOTE: Record<GoldStrategyCard["state"], string> = {
  signal: "",
  waiting: "No current setup. A signal appears only when one qualifies.",
  warming: "Collecting enough price history before it can scan.",
  unconfirmed: "Data issue. Current state cannot be confirmed.",
  paused: "Scanner paused. No new signals.",
  offline: "Scanner not connected.",
};
const FILLED = { target: "bg-[hsl(var(--gain))] text-white", stop: "bg-[hsl(var(--loss))] text-white" };
const pipsFmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const HIDDEN_KEY = "gold-dashboard-hidden";
type Direction = "all" | "BUY" | "SELL";

function readHidden(): string[] {
  try { const v = JSON.parse(localStorage.getItem(HIDDEN_KEY) ?? "[]"); return Array.isArray(v) ? v.filter((x) => typeof x === "string") : []; }
  catch { return []; }
}

function SignalLevels({ signal, now, id }: { signal: PublicSignal; now: number; id: string }) {
  const hits = hitLevels(signal.status, signal.tp2_at, signal.tp3_watch?.state);
  const display = publishedSignalState(signal, now);
  const windowPassed = signal.status === "PENDING" && Date.parse(signal.expires_at_utc) <= now;
  const tone = hits.sl ? "stop" : hits.tp1 ? "target" : null;
  const t1 = goldTargetMetrics(signal.direction, signal.entry, signal.sl, signal.tp1);
  const t2 = goldTargetMetrics(signal.direction, signal.entry, signal.sl, signal.tp2);
  const t3 = signal.tp3 ? goldTargetMetrics(signal.direction, signal.entry, signal.sl, signal.tp3) : null;
  const buy = signal.direction === "BUY";
  const age = fmtAge(signal.issued_at_utc, now);
  return (
    <div className="rounded-lg border border-border bg-background/50" data-testid={`signal-${id}`}>
      <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-xs">
        <span className={cn("font-semibold", buy ? "text-[hsl(var(--gain))]" : "text-[hsl(var(--loss))]")} data-testid={`text-direction-${id}`}>{signal.direction}</span>
        <span className={cn("rounded-full px-2 py-0.5 font-medium", display.unconfirmed ? "bg-accent text-accent-foreground" : tone ? FILLED[tone] : "bg-muted")} data-testid={`text-status-${id}`}>
          {display.label}
        </span>
      </div>
      <dl className="grid grid-cols-2 gap-px border-y border-border bg-border">
        {[
          { label: "Entry", value: signal.entry, k: "entry", hit: false, m: null },
          { label: hits.tp1 ? "Initial SL" : "Stop-loss", value: signal.sl, k: "sl", hit: hits.sl, m: null },
          { label: "TP 1", value: signal.tp1, k: "tp1", hit: hits.tp1, m: t1 },
          { label: "TP 2", value: signal.tp2, k: "tp2", hit: hits.tp2, m: t2 },
          { label: "TP 3", value: signal.tp3, k: "tp3", hit: hits.tp3, m: t3 },
        ].map(({ label, value, k, hit, m }) => (
          <div key={k} className={cn("min-w-0 px-3 py-2", hit ? FILLED[k === "sl" ? "stop" : "target"] : k === "entry" ? "bg-primary/10" : "bg-card")} data-hit={hit || undefined}>
            <dt className={cn("flex items-center justify-between text-[11px] font-medium", !hit && "text-muted-foreground")}>
              {label}{hit && (k === "sl" ? <X aria-label="hit" className="h-3 w-3" /> : <Check aria-label="hit" className="h-3 w-3" />)}
            </dt>
            <dd className="font-mono text-sm tabular-nums" data-testid={`text-${k}-${id}`}
              title={k === "tp3" ? signal.tp3_watch?.unresolved_reason ?? TP3_NOTE : undefined}>
              {k === "tp3" && !value ? TP3_LABEL : fmtScalar(value ?? null)}
            </dd>
            {k === "tp3" && signal.tp3_watch && !hit && (
              <dd className="text-[11px] text-muted-foreground">{TP3_WATCH_LABEL[signal.tp3_watch.state]}</dd>
            )}
            {m && <dd className={cn("mt-0.5 text-[11px] leading-tight tabular-nums", hit ? "text-white" : "text-muted-foreground")} data-testid={`text-metrics-${k}-${id}`}>
              <span className="block font-semibold">R:R 1:{fmtScalar(m.rewardRatio)}</span>
              <span className="block">+${fmtScalar(m.moveUsd)}/oz · +{pipsFmt.format(m.pips)} pips</span>
            </dd>}
          </div>
        ))}
      </dl>
      <div className="space-y-0.5 px-3 py-2 text-xs text-muted-foreground">
        <p data-testid={`text-time-${id}`}>Published <time dateTime={signal.issued_at_utc} className="font-medium text-foreground">{age ?? `${cambodiaDateTime(signal.issued_at_utc)} ICT`}</time>{age && ` · ${cambodiaDateTime(signal.issued_at_utc)} ICT`}</p>
        {signal.status === "PENDING" && <p>{windowPassed ? "Entry window ended" : "Entry expires"} {cambodiaDateTime(signal.expires_at_utc)} ICT</p>}
        {(signal.status === "TP1" || signal.status === "TP2_OPEN") && <p>Remaining position uses a breakeven stop at {fmtScalar(signal.entry)}.</p>}
        {signal.result_r !== null && <p data-testid={`text-result-${id}`}>Test result: <strong className="text-foreground">{fmtR(signal.result_r)}</strong></p>}
        {display.detail && <p>{display.detail}</p>}
        {signal.parallel_targets && <section className="mt-2 border-t border-border pt-2" aria-label="Fixed-SL test orders">
          <p className="mb-1 font-semibold text-foreground" title={PARALLEL_NOTE}>Fixed-SL orders · before costs</p>
          <ParallelTargetResult plan={signal.parallel_targets} />
        </section>}
      </div>
    </div>
  );
}

function GoldCard({ card, now, unconfirmedAll, onHide }: { card: GoldStrategyCard; now: number; unconfirmedAll: boolean; onHide: () => void }) {
  const [open, setOpen] = useState(false);
  const code = card.strategy.strategy_code;
  const state = unconfirmedAll && card.state === "signal" ? "unconfirmed" : card.state;
  const top = card.signals[0];
  const age = top ? fmtAge(top.issued_at_utc, now) : null;
  const showSignal = top && (state === "signal" || state === "unconfirmed");
  const buy = top?.direction === "BUY";
  const lastResult = card.latest?.closed_at && card.latest.result_r !== null ? card.latest : null;
  return (
    <article className="desk-card rise flex min-w-0 flex-col overflow-hidden rounded-lg border border-border bg-card"
      data-side={showSignal && state === "signal" ? top.direction : undefined} data-testid={`card-strategy-${code}`}>
      <div className="flex items-start justify-between gap-1 px-4 pt-3.5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="rounded-md bg-muted px-1.5 py-0.5 text-[10px] font-semibold text-primary">{STYLE_NAMES[card.strategy.style]}</span>
            {card.strategy.site_test && <SiteTestBadge />}
          </div>
          <h3 className="mt-1.5 text-base leading-snug font-semibold tracking-tight" data-testid={`text-name-${code}`}>{card.strategy.name}</h3>
          <p className="mt-0.5 font-mono text-[10px] tracking-wide text-muted-foreground">{code}</p>
        </div>
        <button type="button" onClick={onHide} title="Hide this card" aria-label={`Hide ${card.strategy.name}`}
          className="rounded p-2 text-muted-foreground hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring" data-testid={`button-hide-${code}`}>
          <EyeOff className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="flex flex-1 items-center gap-3 px-4 py-3">
        {showSignal ? (
          <>
            <span className={cn("inline-flex shrink-0 items-center gap-1 rounded-lg px-2.5 py-1.5 text-sm font-semibold",
              buy ? "bg-[hsl(var(--gain)/0.12)] text-[hsl(var(--gain))]" : "bg-[hsl(var(--loss)/0.1)] text-[hsl(var(--loss))]")} data-testid={`text-overview-direction-${code}`}>
              {top.direction}{buy ? <ArrowUpRight size={15} /> : <ArrowDownRight size={15} />}
            </span>
            <div className="min-w-0 text-xs">
              <p className="flex flex-wrap items-baseline gap-x-1.5">
                <span className="font-mono tabular-nums">@ {fmtScalar(top.entry)}</span>
                {age && <time dateTime={top.issued_at_utc} title={fmtDate(top.issued_at_utc)}
                  className="text-muted-foreground" data-testid={`text-overview-age-${code}`}>{age}</time>}
              </p>
              <p className="text-muted-foreground" data-testid={`text-overview-status-${code}`}>
                {state === "unconfirmed" ? "Unconfirmed" : goldSignalStatus(top)}
                {card.signals.length > 1 && <span className="ml-1 rounded bg-accent px-1.5 font-medium text-accent-foreground" data-testid={`text-count-${code}`}>{card.signals.length} signals</span>}
              </p>
            </div>
          </>
        ) : (
          <div className="text-xs">
            <span className={cn("inline-block rounded-full px-2 py-0.5 font-medium", state === "unconfirmed" || state === "offline" ? "bg-accent text-accent-foreground" : "bg-muted")} data-testid={`status-${code}`}>
              {STATE_LABEL[state]}{state === "warming" && card.warmup && ` · ${card.warmup.have}/${card.warmup.need}`}
            </span>
            {lastResult && state === "waiting"
              ? <p className="mt-1 text-muted-foreground" data-testid={`text-last-result-${code}`}>
                Last result: {STATUS[lastResult.status]} <span className={cn("font-medium", rTone(lastResult.result_r))}>{fmtR(lastResult.result_r)}</span>
              </p>
              : <p className="mt-1 text-muted-foreground">{STATE_NOTE[state]}</p>}
          </div>
        )}
      </div>
      {showSignal && state === "signal" && (
        <dl className="mx-4 mb-3 grid grid-cols-[repeat(auto-fit,minmax(58px,1fr))] gap-px overflow-hidden rounded-lg border border-border bg-border"
          aria-label="Signal price levels">
          {([
            ["Entry", top.entry], ["SL", top.sl], ["TP1", top.tp1], ["TP2", top.tp2], ["TP3", top.tp3],
          ] as const).map(([label, price]) => (
            <div key={label} className="min-w-0 bg-background px-1.5 py-1.5">
              <dt className="text-[10px] font-medium text-muted-foreground">{label}</dt>
              <dd className="font-mono text-[11px] leading-relaxed font-medium tabular-nums">{price ? fmtScalar(price) : "None"}</dd>
            </div>
          ))}
        </dl>
      )}
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-controls={`strategy-details-${code}`}
        className="flex min-h-10 items-center justify-between border-t border-border bg-muted/35 px-4 py-2 text-xs font-semibold text-primary hover:bg-muted" data-testid={`button-details-${code}`}>
        {open ? "Hide details" : "Details"}
        <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div id={`strategy-details-${code}`} className="rise space-y-2 border-t border-border px-3 py-3" data-testid={`details-${code}`}>
          {card.signals.length > 0 ? card.signals.map((s) => <SignalLevels key={s.signal_id} signal={s} now={now} id={s.signal_id} />)
            : <p className="text-xs text-muted-foreground">No current signal.</p>}
          {card.signals.length === 0 && card.latest && (
            <div className="space-y-1" data-testid={`text-latest-${code}`}>
              <p className="text-xs font-medium text-muted-foreground">Last published signal · not current</p>
              <SignalLevels signal={card.latest} now={now} id={card.latest.signal_id} />
            </div>
          )}
          {(card.signals.length > 0 || card.latest) && <p className="text-[11px] text-muted-foreground">Planned move before costs. R:R uses the original stop-loss. 1 tracker pip = $0.01/oz.</p>}
          <div className="rounded-lg border border-border"><StrategyToggle strategy={card.strategy} featured /></div>
        </div>
      )}
    </article>
  );
}

function DayCompare({ snapshot, now, cards, filters }: {
  snapshot: Snapshot; now: number; cards: GoldStrategyCard[]; filters: Pick<GoldCardFilters, "direction" | "range">;
}) {
  const [open, setOpen] = useState(false);
  const cmp = open ? compareGoldDays(snapshot, now, cards, filters) : null;
  return (
    <section className="mt-6 rounded-lg border border-border bg-card" data-testid="section-day-compare">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}
        className="flex w-full items-center justify-between px-4 py-3 text-left text-sm font-medium hover:bg-muted/60" data-testid="button-toggle-compare">
        <span>Today vs yesterday <span className="font-normal text-muted-foreground">· Cambodia time</span></span>
        <ChevronDown className={cn("h-4 w-4 transition-transform", open && "rotate-180")} />
      </button>
      {cmp && (
        <div className="rise border-t border-border px-4 py-3 text-sm">
          <p className="mb-2 text-xs text-muted-foreground" data-testid="text-compare-labels">
            Today so far vs yesterday up to the same time. Uses the style, side and distance filters above, including hidden strategies. These small samples aren’t a ranking.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs tabular-nums">
              <thead className="text-muted-foreground"><tr className="text-left">
                <th scope="col" className="py-1 pr-2 font-medium">Strategy</th>
                <th scope="col" className="pr-2 font-medium">Today <span className="block">{cmp.todayLabel}</span></th>
                <th scope="col" className="font-medium">Yesterday <span className="block">{cmp.yesterdayLabel}</span></th>
              </tr></thead>
              <tbody>{cmp.rows.map((row) => (
                <tr key={row.strategy.strategy_code} className="border-t border-border" data-testid={`row-compare-${row.strategy.strategy_code}`}>
                  <th scope="row" className="py-2 pr-3 text-left font-medium">{row.strategy.name}</th>
                  {[row.today, row.yesterday].map((day, index) => (
                    <td key={index} className="py-2 pr-2">
                      <span className="block whitespace-nowrap text-muted-foreground">{day.issued} issued / {day.closed} closed</span>
                      <span className={cn("block font-medium", rTone(day.totalR))}>{fmtR(day.totalR)}</span>
                    </td>
                  ))}
                </tr>
              ))}</tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">1R is the original risk on a test. Results count on the day they close; — means no completed result.</p>
        </div>
      )}
    </section>
  );
}

function GoldDashboard({ snapshot }: { snapshot: Snapshot }) {
  const { isFetching, refetch, isRefetchError } = useSnapshot();
  const now = useTickingNow();
  const { cards, fresh } = getGoldDashboard(snapshot, now);
  const [direction, setDirection] = useState<Direction>("all");
  const [style, setStyle] = useState<Style | "">("");
  const [distance, setDistance] = useState(EMPTY_DISTANCE);
  const [hideWaiting, setHideWaiting] = useState(false);
  const [hidden, setHidden] = useState<string[]>(readHidden);
  const [view, setView] = useState<"cards" | "sheet">(
    () => new URLSearchParams(window.location.search).get("view") === "sheet" ? "sheet" : "cards",
  );
  useEffect(() => { try { localStorage.setItem(HIDDEN_KEY, JSON.stringify(hidden)); } catch { /* storage unavailable */ } }, [hidden]);
  const range = parseTargetRange(distance.min, distance.max);
  const styleCards = style ? cards.filter((card) => card.strategy.style === style) : cards;
  const shown = filterGoldCards(cards, { direction, style, range, hideWaiting, hidden });
  const runner = snapshot.runner;
  const biquote = runner.data_source === "BIQUOTE_XAUUSD_MID";
  const dataIssue = isRefetchError || !fresh || runner.state === "error";
  const connection = isRefetchError ? "Could not refresh" :
    runner.state === "not_configured" ? "Scanner not connected" :
    runner.state === "disabled" ? "Scanner paused" :
    runner.state === "error" ? "Scanner needs attention" :
    !fresh ? "Waiting for an update" :
    runner.state === "waiting" ? "Scanner waiting" : biquote ? "Scanner connected" : "Scanner ready";
  const hiddenCards = styleCards.filter((c) => hidden.includes(c.strategy.strategy_code));
  const filtered = direction !== "all" || !!style || range.active || hideWaiting || hidden.length > 0;
  const reset = () => { setDirection("all"); setStyle(""); setDistance(EMPTY_DISTANCE); setHideWaiting(false); setHidden([]); };
  const hide = (code: string) => setHidden((current) => current.includes(code) ? current : [...current, code]);
  const chip = (on: boolean) => cn("min-h-8 rounded-full border px-3 py-1 text-xs font-medium transition-colors", on ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card hover:bg-muted");

  return (
    <div>
      <div className="desk-panel mb-4 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-card p-2.5 pl-3 sm:px-4 sm:py-2.5">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs" data-testid="status-runner">
          <span className={cn("flex items-center gap-1.5 rounded-full px-2.5 py-1 font-semibold", !dataIssue && runner.state === "ready"
            ? "bg-[hsl(var(--gain)/0.12)] text-[hsl(var(--gain))]" : "bg-accent text-accent-foreground")}>
          <span aria-hidden="true" className="size-1.5 rounded-full bg-current" />
          {connection}
          </span>
          <span className="text-muted-foreground" data-testid="text-last-check">
            {runner.updated_at_utc ? (
              <>Last scan <time className="font-mono text-[11px]" dateTime={runner.updated_at_utc} title="Cambodia time (UTC+7)">{cambodiaDateTime(runner.updated_at_utc)} ICT</time></>
            ) : "No scan yet"}
          </span>
        </div>
        <button type="button" onClick={() => void refetch()} disabled={isFetching} data-testid="button-refresh"
          className="inline-flex min-h-8 items-center gap-1.5 rounded-lg border border-border px-2.5 text-xs font-semibold text-primary hover:bg-muted disabled:opacity-60">
          <RefreshCw className={cn("h-3.5 w-3.5", isFetching && "animate-spin")} />{isFetching ? "Checking…" : "Refresh"}
        </button>
      </div>

      <GoldOpenSignals rows={getGoldOpenSignals(snapshot, now, isRefetchError)} now={now} dataIssue={dataIssue} />

      <div className="mb-3 mt-6 flex items-end justify-between gap-3">
        <div>
          <p className="font-mono text-[10px] font-medium uppercase tracking-[0.15em] text-muted-foreground">Strategy monitor</p>
          <h2 className="text-xl font-semibold tracking-tight">Strategy watchlist</h2>
        </div>
        <p className="text-xs whitespace-nowrap text-muted-foreground" data-testid="text-visible-strategies">{shown.length} of {cards.length} shown</p>
      </div>
      <div className={cn("grid min-w-0 items-start gap-3.5", view === "cards" && "xl:grid-cols-[15.5rem_minmax(0,1fr)]")}>
      <section className="desk-panel overflow-hidden rounded-lg border border-border bg-card px-3.5 pt-3.5 sm:px-4" aria-label="Signal display controls">
      <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold"><SlidersHorizontal size={15} className="text-primary" aria-hidden="true" /> Watchlist filters</h3>
      <div className={cn("mb-3 grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] items-start gap-3 sm:max-w-lg sm:grid-cols-[minmax(0,10rem)_1fr]", view === "cards" && "xl:grid-cols-1")}>
        <StyleSelect scope="home" value={style} onChange={setStyle} />
        <TargetDistanceInputs scope="home" value={distance} onChange={setDistance} invalid={range.invalid} />
      </div>
      <div className="-mx-3.5 flex flex-wrap items-center justify-between gap-2 border-t border-border bg-muted/35 px-3.5 py-2.5 sm:-mx-4 sm:px-4">
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Signal filters">
        {(["all", "BUY", "SELL"] as const).map((d) => (
          <button key={d} type="button" aria-pressed={direction === d} onClick={() => setDirection(d)} className={chip(direction === d)} data-testid={`button-direction-${d.toLowerCase()}`}>
            {d === "all" ? "All" : d}
          </button>
        ))}
        <button type="button" aria-pressed={hideWaiting} onClick={() => setHideWaiting((v) => !v)} className={chip(hideWaiting)} data-testid="button-hide-waiting">Hide waiting</button>
        {hiddenCards.map((c) => (
          <button key={c.strategy.strategy_code} type="button" aria-label={`Show ${c.strategy.name}`} onClick={() => setHidden((h) => h.filter((x) => x !== c.strategy.strategy_code))}
            className="inline-flex items-center gap-1 rounded-full border border-dashed border-border px-2.5 py-1 text-xs text-muted-foreground hover:bg-muted" data-testid={`button-show-${c.strategy.strategy_code}`}>
            <Eye className="h-3 w-3" />{c.strategy.name}
          </button>
        ))}
        {filtered && <button type="button" onClick={reset} className="inline-flex items-center gap-1 px-2 py-1 text-xs text-primary hover:underline" data-testid="button-reset-filters"><RotateCcw className="h-3 w-3" />Reset</button>}
        </div>
        <div className="inline-flex items-center gap-0.5 rounded-lg border border-border bg-muted/70 p-0.5" role="group" aria-label="Display style">
          {([{ key: "cards", label: "Cards", Icon: LayoutGrid }, { key: "sheet", label: "Sheet", Icon: Sheet }] as const).map(({ key, label, Icon }) => (
            <button key={key} type="button" aria-pressed={view === key} onClick={() => setView(key)}
              className={cn("inline-flex min-h-8 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors",
                view === key ? "bg-card text-primary shadow-sm" : "text-muted-foreground hover:text-foreground")}
              data-testid={`button-view-${key}`}><Icon size={14} aria-hidden="true" />{label}</button>
          ))}
        </div>
      </div>
      </section>

      <div className="min-w-0">
      {shown.length > 0 ? view === "sheet" ? (
        <GoldSignalSheet cards={shown} now={now} dataIssue={dataIssue} onHide={hide} />
      ) : (
        <div className="grid grid-cols-1 items-start gap-3 sm:grid-cols-2 lg:grid-cols-3" data-testid="grid-strategies">
          {shown.map((card) => (
            <GoldCard key={card.strategy.strategy_code} card={card} now={now} unconfirmedAll={dataIssue}
              onHide={() => hide(card.strategy.strategy_code)} />
          ))}
        </div>
      ) : (
        <section className="rounded-lg border border-dashed border-border bg-card px-6 py-10 text-center" data-testid="card-empty">
          <h2 className="font-display text-2xl">Nothing matches these filters</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {cards.length === 0 ? "No strategies are published yet." :
              direction !== "all" || range.active ? "No current signals match the selected style, side or target distance. For closed signals, see History." :
              "No strategies are visible with the current filters."}
          </p>
          {filtered && <button type="button" onClick={reset} className="mt-4 rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground" data-testid="button-empty-reset">Show all strategies</button>}
        </section>
      )}
      </div>
      </div>

      {!range.invalid && <DayCompare snapshot={snapshot} now={now} cards={styleCards} filters={{ direction, range }} />}

      <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <p>
          {biquote ? <>Indicative data by <a href="https://biquote.io/" rel="noreferrer" target="_blank" className="underline" data-testid="link-biquote">biquote</a>.</> : "Published snapshot data."}
          {runner.message.includes("warming up H1 history") && " Intraday strategies are still gathering hourly data."}
        </p>
        <Link href="/signals" className="font-medium text-primary underline-offset-4 hover:underline" data-testid="link-full-signal-list">All signals →</Link>
      </div>
    </div>
  );
}

export default function GoldBoardPage() {
  return (
    <>
      <DeskHeader label="XAUUSD / TEST SIGNALS" title="Gold signals" description="Track gold signals across Scalping, Intraday and Swing. Testing only.">
        <div className="flex flex-wrap gap-2">
        <Link href="/telegram" className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-[hsl(var(--gold)/0.5)] bg-white/5 px-3 text-xs font-semibold text-white hover:bg-[hsl(var(--gold))] hover:text-[hsl(var(--ink))] focus-visible:outline-2 focus-visible:outline-white"
          data-testid="link-desk-telegram"><Bell size={14} aria-hidden="true" /> Telegram alerts</Link>
        <Link href="/history" className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-[hsl(var(--gold)/0.5)] bg-white/5 px-3 text-xs font-semibold text-white hover:bg-[hsl(var(--gold))] hover:text-[hsl(var(--ink))] focus-visible:outline-2 focus-visible:outline-white"
          data-testid="link-desk-history">View history <ArrowRight size={14} aria-hidden="true" /></Link>
        </div>
      </DeskHeader>
      <SnapshotGate>{(snapshot) => <GoldDashboard snapshot={snapshot} />}</SnapshotGate>
    </>
  );
}
