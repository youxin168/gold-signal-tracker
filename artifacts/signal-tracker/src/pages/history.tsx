import { useMemo, useState } from "react";
import { SlidersHorizontal } from "lucide-react";
import { EmptyState, ModeTag, Segmented } from "@/components/bits";
import { DeskHeader } from "@/components/desk-header";
import { GoldHistorySheet } from "@/components/gold-history-sheet";
import { EMPTY_DISTANCE, StyleSelect, TargetDistanceInputs } from "@/components/gold-signal-filters";
import { HistoryResultSummary } from "@/components/history-result-summary";
import { SnapshotGate } from "@/components/snapshot-gate";
import { cohortSubtitle, fmtDate, sortSignals, UNRESOLVED } from "@/lib/format";
import { parseTargetRange } from "@/lib/gold-targets";
import { cambodiaDate, DAY_MS, filterHistory, summarizeHistory } from "@/lib/history-results";
import type { Cohort, Snapshot, Style } from "@/lib/public-snapshot";

type View = "resolved" | "unresolved" | "all";
const selectClass = "h-9 w-full min-w-0 rounded-md border border-border bg-card px-2 text-sm text-foreground";
const quickClass = "rounded-md border border-border bg-card px-2.5 py-1.5 text-xs hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring";

function scopeLabel(cohort: Cohort) {
  if (cohort.mode === "BACKTEST") return `${cohort.mode} · ${cohort.label}`;
  const feed = cohort.data_source === "BIQUOTE_XAUUSD_MID" ? "Biquote"
    : cohort.data_source === "OANDA_PRACTICE_BID" ? "OANDA practice" : cohort.data_source;
  return `${cohort.mode === "LIVE" ? "Live tests" : "Replay"}${feed ? ` · ${feed}` : ""}`;
}

function CohortHistory({ cohort, strategies }: { cohort: Cohort; strategies: Snapshot["strategies"] }) {
  const [view, setView] = useState<View>("resolved");
  const [code, setCode] = useState("");
  const [style, setStyle] = useState<Style | "">("");
  const [distance, setDistance] = useState(EMPTY_DISTANCE);
  const [dates, setDates] = useState({ from: "", to: "" });
  const badDates = Boolean(dates.from && dates.to && dates.from > dates.to);
  const range = useMemo(() => parseTargetRange(distance.min, distance.max), [distance]);
  const archivedCodes = useMemo(() => new Set(strategies.filter((s) => s.retired_live).map((s) => s.strategy_code)), [strategies]);
  const options = useMemo(() => [...new Set(cohort.signals
    .filter((signal) => !style || signal.style === style).map((signal) => signal.strategy_code))].sort(), [cohort.signals, style]);
  const split = useMemo(() => {
    const all = sortSignals(filterHistory(cohort.signals, { code, style, range, ...dates }));
    const isUnresolved = (s: (typeof all)[number]) => Boolean(s.unresolved_reason) || UNRESOLVED.includes(s.status);
    return {
      all,
      unresolved: all.filter(isUnresolved),
      resolved: all.filter((s) => !isUnresolved(s)),
    };
  }, [cohort.signals, code, dates, style, range]);
  const summary = summarizeHistory(split.resolved, code ? new Set() : archivedCodes);
  const selectDay = (daysAgo: number) => {
    const day = cambodiaDate(Date.now() - daysAgo * DAY_MS);
    setDates({ from: day, to: day });
  };

  return (
    <>
      <fieldset className="desk-panel mb-4 rounded-lg border border-border bg-card p-3.5 sm:p-4" aria-label="History filters">
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <p className="flex items-center gap-2 text-sm font-semibold"><SlidersHorizontal size={15} className="text-primary" aria-hidden="true" /> Filter results</p>
          <p id="history-date-help" className="text-[11px] text-muted-foreground">
            Cambodia time (UTC+7) · closed date, or issued date if still open
          </p>
        </div>
        <div className="grid grid-cols-2 items-start gap-2.5 md:grid-cols-[minmax(0,1fr)_minmax(0,1.7fr)_minmax(0,1fr)_minmax(0,1fr)]">
          <StyleSelect scope="history" value={style} onChange={(next) => {
            setStyle(next);
            if (code && next && !cohort.signals.some((signal) => signal.strategy_code === code && signal.style === next)) setCode("");
          }} />
          <label className="grid min-w-0 gap-1 text-xs font-medium text-muted-foreground">
            Strategy version
            <select className={selectClass} value={code} onChange={(event) => setCode(event.target.value)} data-testid="select-history-strategy">
              <option value="">All strategies</option>
              {options.map((option) => {
                const strategy = strategies.find((s) => s.strategy_code === option);
                return <option key={option} value={option}>{strategy ? `${strategy.name} (${option})${strategy.retired_live ? " · Archived" : ""}` : option}</option>;
              })}
            </select>
          </label>
          {(["from", "to"] as const).map((key) => (
            <label className="grid min-w-0 gap-1 text-xs font-medium text-muted-foreground" key={key}>
              {key === "from" ? "From date" : "To date"}
              <input type="date" className={selectClass} value={dates[key]} aria-describedby="history-date-help"
                aria-invalid={badDates || undefined} data-testid={`input-history-${key}`}
                onChange={(event) => {
                  const value = event.target.value;
                  setDates((previous) => ({ ...previous, [key]: value }));
                }} />
            </label>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <div className="w-full max-w-xs">
            <TargetDistanceInputs scope="history" value={distance} onChange={setDistance} invalid={range.invalid} />
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" className={quickClass} onClick={() => selectDay(0)}>Today</button>
            <button type="button" className={quickClass} onClick={() => selectDay(1)}>Yesterday</button>
            {(dates.from || dates.to) && <button type="button" className={quickClass} onClick={() => setDates({ from: "", to: "" })}>Clear dates</button>}
            {(style || range.active || code) && <button type="button" className={quickClass} data-testid="button-clear-history-signal-filters"
              onClick={() => { setStyle(""); setCode(""); setDistance(EMPTY_DISTANCE); }}>Clear signal filters</button>}
          </div>
        </div>
        {badDates && <p role="alert" className="mt-2 text-xs text-destructive">The end date must be on or after the start date.</p>}
      </fieldset>
      <HistoryResultSummary summary={summary} />
      <div className="mb-3">
        <Segmented label="History records" value={view} onChange={(value: View) => setView(value)} options={[
          { value: "resolved", label: `Outcomes (${split.resolved.length})` },
          { value: "unresolved", label: `Open / unresolved (${split.unresolved.length})` },
          { value: "all", label: `All (${split.all.length})` },
        ]} />
      </div>
      {badDates || range.invalid ? null : !cohort.signals.length ? (
        <EmptyState title="No records in this group">{cohort.mode === "BACKTEST"
          ? "No signals qualified in this period. Missing filter data can prevent a signal and does not prove the strategy never triggers."
          : "No signals have been recorded for this mode and feed."}</EmptyState>
      ) : split[view].length === 0 ? (
        <EmptyState title={view === "unresolved" ? "No open or unresolved signals" : "No records match"}>Try a different date range, style, target distance, or record view.</EmptyState>
      ) : <GoldHistorySheet signals={split[view]} strategies={strategies} />}
    </>
  );
}

function HistoryBody({ snap }: { snap: Snapshot }) {
  const [id, setId] = useState("");
  const cohort = snap.cohorts.find((c) => c.id === id)
    ?? snap.cohorts.find((c) => c.mode === "LIVE" && c.data_source === snap.runner.data_source)
    ?? snap.cohorts.find((c) => c.signals.length) ?? snap.cohorts[0];
  if (!cohort) return <EmptyState title="No signal history yet">No live, replay, or backtest groups have been published.</EmptyState>;
  return (
    <div className="min-w-0">
      <section className="desk-panel mb-4 rounded-lg border border-border bg-card p-3.5 sm:p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <label className="grid w-full max-w-sm gap-1 text-xs font-medium text-muted-foreground">
            Records to show
            <select className={selectClass} value={cohort.id} onChange={(event) => setId(event.target.value)} data-testid="select-history-scope">
              {snap.cohorts.map((c) => <option key={c.id} value={c.id}>{scopeLabel(c)} ({c.signals.length})</option>)}
            </select>
          </label>
          <span className="inline-flex items-center gap-2 text-xs text-muted-foreground"><ModeTag mode={cohort.mode} /> {cohortSubtitle(cohort)}</span>
        </div>
        <details className="mt-2 text-xs text-muted-foreground" data-testid="details-history-scope">
          <summary className="cursor-pointer">About this record group</summary>
          <p className="mt-2">Feed: {cohort.data_source ?? "—"} · Period: {fmtDate(cohort.start_utc, false)} to {fmtDate(cohort.end_utc_exclusive, false)} (end excluded)</p>
          {cohort.note && <p className="mt-1">{cohort.note}</p>}
        </details>
      </section>
      <CohortHistory key={cohort.id} cohort={cohort} strategies={snap.strategies} />
    </div>
  );
}

export default function HistoryPage() {
  return (
    <>
      <DeskHeader label="XAUUSD / TEST RESULTS" title="Signal history"
        description="Review outcomes by strategy and date. Live tests, replay and backtest results stay separate." />
      <SnapshotGate>{(snap) => <HistoryBody snap={snap} />}</SnapshotGate>
    </>
  );
}
