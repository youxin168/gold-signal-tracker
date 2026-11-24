import { type ReactNode, useMemo, useState } from "react";
import { AlertTriangle, Inbox, RotateCw } from "lucide-react";
import { Line, LineChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, ReferenceLine } from "recharts";
import type { Metrics, PublicSignal, SignalStatus, Mode } from "@/lib/public-snapshot";
import { fmtAge, fmtDate, fmtPct, fmtR, fmtScalar, hitLevels, rTone, STYLE_NAMES } from "@/lib/format";
import { publishedSignalState, TP3_LABEL, TP3_WATCH_LABEL } from "@/lib/gold-labels";
import { cambodiaDateTime } from "@/lib/history-results";
import { useTickingNow } from "@/hooks/use-ticking-now";
import { cn } from "@/lib/utils";

export function PageHeader({ kicker, title, children }: { kicker: string; title: string; children?: ReactNode }) {
  return (
    <header className="desk-header rise mb-6 rounded-lg px-5 py-5 sm:px-7">
      <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-[hsl(var(--gold))]">{kicker}</p>
      <h1 className="mt-1.5 text-2xl font-semibold tracking-tight text-white sm:text-[1.85rem]" data-testid="text-page-title">{title}</h1>
      {children && <div className="mt-2 max-w-3xl text-sm leading-relaxed text-white/85 [&_a]:text-[hsl(var(--gold))]">{children}</div>}
    </header>
  );
}

const STATUS_TONE: Record<SignalStatus, string> = {
  PENDING: "border-border bg-muted text-muted-foreground",
  ACTIVE: "border-primary/40 bg-primary/10 text-primary",
  TP1: "border-transparent bg-[hsl(var(--gain))] text-white",
  TP2: "border-transparent bg-[hsl(var(--gain))] text-white",
  TP2_OPEN: "border-transparent bg-[hsl(var(--gain))] text-white",
  TP3: "border-transparent bg-[hsl(var(--gain))] text-white",
  SL: "border-transparent bg-[hsl(var(--loss))] text-white",
  BE: "border-border bg-secondary text-foreground",
  EXPIRED: "border-dashed border-border bg-transparent text-muted-foreground",
};

export function StatusBadge({ status }: { status: SignalStatus }) {
  return <span className={cn("inline-flex rounded-sm border px-1.5 py-0.5 font-mono text-[11px] font-medium", STATUS_TONE[status])}>{status === "TP2_OPEN" ? "TP2 · open" : status}</span>;
}

const MODE_TONE: Record<Mode, string> = {
  LIVE: "bg-primary text-primary-foreground",
  REPLAY: "bg-accent text-accent-foreground",
  BACKTEST: "bg-secondary text-foreground border border-border",
};
export function ModeTag({ mode }: { mode: Mode }) {
  return <span className={cn("rounded-sm px-1.5 py-0.5 font-mono text-[10px] font-medium tracking-wider", MODE_TONE[mode])}>{mode}</span>;
}

export function StyleTag({ style }: { style: keyof typeof STYLE_NAMES }) {
  return <span className="font-mono text-xs text-muted-foreground" title={STYLE_NAMES[style]}>{style}</span>;
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rise flex flex-col items-start gap-2 rounded-md border border-dashed border-input bg-card/60 px-6 py-10" data-testid="state-empty">
      <Inbox className="h-5 w-5 text-accent-foreground" aria-hidden />
      <p className="font-display text-xl">{title}</p>
      {children && <div className="max-w-xl text-sm leading-relaxed text-muted-foreground">{children}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <div role="alert" className="rise rounded-md border border-[hsl(var(--loss)/.35)] bg-card px-6 py-8" data-testid="state-error">
      <div className="flex items-center gap-2 text-[hsl(var(--loss))]"><AlertTriangle className="h-5 w-5" aria-hidden /><p className="font-display text-xl">The published snapshot could not be read</p></div>
      <p className="mt-2 max-w-xl text-sm text-muted-foreground">{error instanceof Error ? error.message : "Unknown error."} Nothing is shown rather than guessed.</p>
      <button onClick={onRetry} className="mt-4 inline-flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground hover:opacity-90" data-testid="button-retry">
        <RotateCw className="h-4 w-4" aria-hidden /> Try again
      </button>
    </div>
  );
}

export function LoadingBlock() {
  return (
    <div className="space-y-3" aria-busy="true" aria-label="Loading snapshot">
      <div className="h-10 w-2/3 animate-pulse rounded bg-muted" />
      {Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-11 animate-pulse rounded bg-muted/70" style={{ animationDelay: `${i * 80}ms` }} />)}
    </div>
  );
}

export function FilterSelect({ label, value, options, onChange, id }: { label: string; value: string; options: string[]; onChange: (v: string) => void; id: string }) {
  return (
    <label className="flex flex-col gap-1 text-[11px] font-mono uppercase tracking-wider text-muted-foreground">
      {label}
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} data-testid={`select-${id}`}
        className="h-9 min-w-[8rem] rounded-md border border-input bg-card px-2 font-sans text-sm normal-case tracking-normal text-foreground focus:outline-none focus:ring-2 focus:ring-ring">
        <option value="">All</option>
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </label>
  );
}

export function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: { value: T; label: ReactNode }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex flex-wrap gap-1 rounded-md border border-border bg-card p-1">
      {options.map((o) => (
        <button key={o.value} role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)} data-testid={`toggle-${o.value}`}
          className={cn("rounded px-3 py-1.5 text-sm transition-colors", value === o.value ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground")}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

function OutcomePrice({ value, hit, target }: { value: string; hit: boolean; target: boolean }) {
  if (!hit) return <span>{value}</span>;
  return (
    <span className={cn("rounded px-1.5 py-0.5 text-white", target ? "bg-[hsl(var(--gain))]" : "bg-[hsl(var(--loss))]")}>
      {value}<span className="sr-only"> hit</span>
    </span>
  );
}

export function SignalTable({ signals, showClose = true, relativeAge = false }: { signals: PublicSignal[]; showClose?: boolean; relativeAge?: boolean }) {
  const [limit, setLimit] = useState(100);
  const now = useTickingNow(relativeAge);
  const rows = signals.slice(0, limit);
  return (
    <div className="rise">
      <div className="desk-panel overflow-hidden rounded-lg border border-border bg-card">
        <div className="flex items-center justify-between gap-3 bg-[hsl(var(--ink))] px-4 py-3 text-white">
          <h2 className="text-sm font-semibold">Published signal ledger</h2>
          <span className="text-xs text-white/80 sm:hidden">Swipe for more columns</span>
        </div>
        <div className="overflow-x-auto focus-visible:outline-2 focus-visible:outline-inset focus-visible:outline-ring"
          role="region" aria-label="Scrollable published signals" tabIndex={0}>
        <table className="w-full min-w-[980px] text-sm">
          <thead className="border-b border-border bg-muted/60 text-left font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
            <tr>
              <th scope="col" className="px-3 py-2.5 font-medium">Issued (ICT)</th><th scope="col" className="px-3 py-2.5 font-medium">Strategy</th><th scope="col" className="px-3 py-2.5 font-medium">Style</th>
              <th scope="col" className="px-3 py-2.5 font-medium">Side</th>
              {["Entry", "Initial SL", "TP1", "TP2", "TP3"].map((label) => <th scope="col" key={label} className="whitespace-nowrap px-3 py-2.5 text-right font-medium">{label}</th>)}
              <th scope="col" className="px-3 py-2.5 font-medium">Status</th>
              {showClose && <th scope="col" className="px-3 py-2.5 font-medium">Closed (ICT)</th>}
              <th scope="col" className="whitespace-nowrap px-3 py-2.5 text-right font-medium">Trade R</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border font-mono text-[13px]">
            {rows.map((s) => {
              const age = relativeAge ? fmtAge(s.issued_at_utc, now) : null;
              const hit = hitLevels(s.status, s.tp2_at, s.tp3_watch?.state);
              const state = publishedSignalState(s, relativeAge ? now : undefined);
              const price = (value: string) => s.pair === "XAUUSD" ? fmtScalar(value) : value;
              return (
              <tr key={s.signal_id} className="transition-colors hover:bg-muted/40" data-testid={`row-signal-${s.signal_id}`}>
                <td className="whitespace-nowrap px-3 py-2.5 text-muted-foreground" title={`Entry window ends ${cambodiaDateTime(s.expires_at_utc)} ICT`}>
                  <time dateTime={s.issued_at_utc}>
                    {age && <span className="block font-medium text-foreground" data-testid={`text-signal-age-${s.signal_id}`}>{age}</span>}
                    {cambodiaDateTime(s.issued_at_utc)}
                  </time>
                </td>
                <td className="px-3 py-2.5"><span className="text-foreground">{s.strategy_code}</span><span className="block text-[11px] text-muted-foreground">{s.source} · {s.pair}</span></td>
                <td className="px-3 py-2.5"><StyleTag style={s.style} /></td>
                <td className="px-3 py-2.5"><span className={cn("rounded px-1.5 py-0.5 font-semibold",
                  s.direction === "BUY" ? "bg-[hsl(var(--gain)/0.1)] text-[hsl(var(--gain))]" : "bg-[hsl(var(--loss)/0.1)] text-[hsl(var(--loss))]")}>{s.direction}</span></td>
                <td className="px-3 py-2.5 text-right font-semibold">{price(s.entry)}</td>
                <td className="whitespace-nowrap px-3 py-2.5 text-right"><OutcomePrice value={price(s.sl)} hit={hit.sl} target={false} /></td>
                <td className="whitespace-nowrap px-3 py-2.5 text-right"><OutcomePrice value={price(s.tp1)} hit={hit.tp1} target /></td>
                <td className="whitespace-nowrap px-3 py-2.5 text-right"><OutcomePrice value={price(s.tp2)} hit={hit.tp2} target /></td>
                <td className="whitespace-nowrap px-3 py-2.5 text-right" title={s.tp3_watch && TP3_WATCH_LABEL[s.tp3_watch.state]}><OutcomePrice value={s.tp3 ? price(s.tp3) : TP3_LABEL} hit={hit.tp3 && Boolean(s.tp3)} target /></td>
                <td className="min-w-36 px-3 py-2.5 font-sans">
                  <span className={cn("inline-block rounded-md px-2 py-0.5 text-xs font-semibold", state.unconfirmed ? "bg-accent text-accent-foreground" : STATUS_TONE[s.status])}>{state.label}</span>
                  {state.detail && <span className="mt-1 block text-[11px] leading-snug text-muted-foreground">{state.detail}</span>}
                </td>
                {showClose && <td className="whitespace-nowrap px-3 py-2.5 text-muted-foreground">{s.closed_at ? <time dateTime={s.closed_at}>{cambodiaDateTime(s.closed_at)}</time> : "—"}</td>}
                <td className={cn("px-3 py-2.5 text-right font-medium", rTone(s.result_r))}>{fmtR(s.result_r)}</td>
              </tr>
              );
            })}
          </tbody>
        </table>
        </div>
      </div>
      <div className="mt-2 flex items-center justify-between font-mono text-xs text-muted-foreground">
        <span data-testid="text-row-count">{rows.length} of {signals.length} records</span>
        {signals.length > limit && <button onClick={() => setLimit((l) => l + 200)} className="rounded border border-border px-2 py-1 hover:bg-muted" data-testid="button-show-more">Show more</button>}
      </div>
    </div>
  );
}

function Stat({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: string }) {
  return (
    <div className="bg-card px-4 py-3">
      <dt className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">{label}</dt>
      <dd className={cn("mt-1 font-mono text-lg", tone)}>{value}</dd>
      {hint && <p className="mt-0.5 text-[11px] leading-snug text-muted-foreground">{hint}</p>}
    </div>
  );
}

const ci = (c: [number, number] | null, pct = false) => (c ? (pct ? `${fmtPct(c[0])} to ${fmtPct(c[1])}` : `${fmtR(c[0])} to ${fmtR(c[1])}`) : "not available");

export function MetricsGrid({ m }: { m: Metrics }) {
  return (
    <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-card-border bg-border sm:grid-cols-3 lg:grid-cols-6">
      <Stat label="Signals" value={String(m.signals)} hint={`${m.expired} expired unfilled`} />
      <Stat label="Fill rate" value={fmtPct(m.fill_rate)} hint={`${m.filled} filled of ${m.filled + m.expired} resolved entries`} />
      <Stat label="Completed" value={String(m.completed)} hint={`${m.filled_open} open · ${m.entry_unresolved} entry unresolved`} />
      <Stat label="Expectancy" value={fmtR(m.expectancy_r)} tone={rTone(m.expectancy_r)} hint={`95% ${ci(m.expectancy_r_ci_95)}`} />
      <Stat label="Total" value={fmtR(m.total_r)} tone={rTone(m.total_r)} hint={`avg ${fmtR(m.average_r)}`} />
      <Stat label="Profit factor" value={fmtScalar(m.profit_factor)} hint={m.profit_factor_status} />
      <Stat label="Max drawdown" value={fmtR(m.max_drawdown_r)} />
      <Stat label="Losing streak" value={fmtScalar(m.longest_losing_streak, 0)} />
      <Stat label="Sample" value={m.sample_size_badge} />
      <Stat label="Win rate" value={fmtPct(m.win_rate)} hint={`of ${m.completed} completed · 95% ${ci(m.win_rate_ci_95, true)}`} />
    </dl>
  );
}

export function EquityCurve({ points, startedAt }: { points: Metrics["equity_curve_r"]; startedAt?: string }) {
  const data = useMemo(() => points.map((p) => ({ t: Date.parse(p.closed_at_utc), r: Number(p.equity_r) })).filter((p) => Number.isFinite(p.t) && Number.isFinite(p.r)), [points]);
  if (data.length === 0) {
    return <EmptyState title="No realized equity yet">The curve is drawn only from closed trades. This selection has none, so no line is plotted.</EmptyState>;
  }
  const start = startedAt ? Date.parse(startedAt) : NaN;
  const series = Number.isFinite(start) && start < data[0].t ? [{ t: start, r: 0 }, ...data] : data;
  return (
    <figure className="rise rounded-md border border-card-border bg-card p-4" data-testid="chart-equity">
      <figcaption className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-display text-lg">Realized equity, in R</span>
        <span className="font-mono text-xs text-muted-foreground">{data.length} close {data.length === 1 ? "timestamp" : "timestamps"} · UTC</span>
      </figcaption>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={series} margin={{ top: 6, right: 12, bottom: 0, left: -8 }}>
            <CartesianGrid stroke="hsl(var(--border))" vertical={false} />
            <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]} tickFormatter={(t: number) => new Date(t).toISOString().slice(0, 10)} tick={{ fontSize: 11, fontFamily: "IBM Plex Mono", fill: "hsl(var(--muted-foreground))" }} stroke="hsl(var(--border))" minTickGap={40} />
            <YAxis domain={[(v: number) => Math.min(v, 0), (v: number) => Math.max(v, 0)]} tickFormatter={(v: number) => `${v}R`} tick={{ fontSize: 11, fontFamily: "IBM Plex Mono", fill: "hsl(var(--muted-foreground))" }} stroke="hsl(var(--border))" width={52} />
            <ReferenceLine y={0} stroke="hsl(var(--muted-foreground))" strokeDasharray="3 3" />
            <Tooltip contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 6, fontFamily: "IBM Plex Mono", fontSize: 12 }}
              labelFormatter={(t: number) => fmtDate(new Date(t).toISOString())} formatter={(v: number) => [fmtR(v), "Equity"]} />
            <Line type="stepAfter" dataKey="r" stroke="hsl(var(--primary))" strokeWidth={2} dot={data.length < 20} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

export function BreakdownTables({ breakdowns }: { breakdowns: Record<string, Record<string, Metrics>> }) {
  const dims = Object.keys(breakdowns);
  const [dim, setDim] = useState(dims[0] ?? "");
  const active = breakdowns[dim] ? dim : dims[0];
  if (!active) return <EmptyState title="No breakdowns published">The engine did not export any metric breakdowns for this selection.</EmptyState>;
  const rows = Object.entries(breakdowns[active]);
  return (
    <div className="rise">
      <Segmented label="Breakdown dimension" value={active} onChange={setDim} options={dims.map((d) => ({ value: d, label: d.replace(/_/g, " ") }))} />
      <div className="mt-3 overflow-x-auto rounded-md border border-card-border bg-card">
        <table className="w-full min-w-[640px] font-mono text-[13px]">
          <thead className="border-b border-border bg-muted/60 text-left text-[11px] uppercase tracking-wider text-muted-foreground">
            <tr><th className="px-3 py-2">{active.replace(/_/g, " ")}</th><th className="px-3 py-2 text-right">Signals</th><th className="px-3 py-2 text-right">Filled</th><th className="px-3 py-2 text-right">Completed</th><th className="px-3 py-2 text-right">Win rate</th><th className="px-3 py-2 text-right">Expectancy</th><th className="px-3 py-2 text-right">Total</th><th className="px-3 py-2">Sample</th></tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map(([k, m]) => (
              <tr key={k} data-testid={`row-breakdown-${k}`}>
                <td className="px-3 py-2">{k}</td><td className="px-3 py-2 text-right">{m.signals}</td><td className="px-3 py-2 text-right">{m.filled}</td><td className="px-3 py-2 text-right">{m.completed}</td>
                <td className="px-3 py-2 text-right">{fmtPct(m.win_rate)}</td><td className={cn("px-3 py-2 text-right", rTone(m.expectancy_r))}>{fmtR(m.expectancy_r)}</td>
                <td className={cn("px-3 py-2 text-right", rTone(m.total_r))}>{fmtR(m.total_r)}</td><td className="px-3 py-2 text-muted-foreground">{m.sample_size_badge}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
