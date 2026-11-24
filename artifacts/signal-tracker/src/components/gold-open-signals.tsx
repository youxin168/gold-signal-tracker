import { useState } from "react";
import { Activity, ArrowDownRight, ArrowUpRight, Check, CircleAlert, ListFilter } from "lucide-react";
import type { GoldOpenSignal } from "@/lib/gold-board";
import { fmtAge, fmtScalar, hitLevels, STYLE_NAMES } from "@/lib/format";
import { TP3_LABEL } from "@/lib/gold-labels";
import { cambodiaDateTime } from "@/lib/history-results";
import { cn } from "@/lib/utils";

type OpenView = "all" | GoldOpenSignal["state"];

function OpenSignalRow({ row, now }: { row: GoldOpenSignal; now: number }) {
  const { signal, strategy, state, statusLabel } = row;
  const buy = signal.direction === "BUY";
  const hits = hitLevels(signal.status, signal.tp2_at, signal.tp3_watch?.state);
  const age = fmtAge(signal.issued_at_utc, now);
  return (
    <li className="grid items-center gap-x-5 gap-y-2.5 px-3.5 py-3.5 sm:px-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]"
      data-testid={`open-signal-${signal.signal_id}`}>
      <div className="flex items-start gap-2.5">
        <span className={cn("inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs font-semibold",
          buy ? "bg-[hsl(var(--gain)/0.12)] text-[hsl(var(--gain))]" : "bg-[hsl(var(--loss)/0.12)] text-[hsl(var(--loss))]")}>
          {buy ? <ArrowUpRight size={14} aria-hidden="true" /> : <ArrowDownRight size={14} aria-hidden="true" />}{signal.direction}
        </span>
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">{strategy.name} <span className="font-normal text-muted-foreground">· {STYLE_NAMES[strategy.style]}</span></h3>
          <p className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-xs">
            <span className={cn("font-semibold", state === "active" ? "text-primary" : "text-accent-foreground")}>{statusLabel}</span>
            <time dateTime={signal.issued_at_utc} title={`${cambodiaDateTime(signal.issued_at_utc)} ICT`} className="text-muted-foreground">
              {age ?? `${cambodiaDateTime(signal.issued_at_utc)} ICT`}
            </time>
          </p>
          {state === "pending" && <p className="mt-0.5 text-[11px] text-muted-foreground">
            Entry expires <time dateTime={signal.expires_at_utc}>{cambodiaDateTime(signal.expires_at_utc)} ICT</time>
          </p>}
          {state === "active" && (signal.status === "TP1" || signal.status === "TP2_OPEN") && (
            <p className="mt-0.5 text-[11px] text-muted-foreground">Breakeven stop at {fmtScalar(signal.entry)}</p>
          )}
        </div>
      </div>
      <dl className="grid grid-cols-[repeat(auto-fit,minmax(3.5rem,1fr))] overflow-hidden rounded-lg border border-border bg-border gap-px" aria-label="Published price levels">
        {([
          ["Entry", signal.entry, false], ["Initial SL", signal.sl, hits.sl],
          ["TP1", signal.tp1, hits.tp1], ["TP2", signal.tp2, hits.tp2], ["TP3", signal.tp3, hits.tp3],
        ] as const).map(([label, price, hit]) => (
          <div key={label} className={cn("min-w-0 px-1.5 py-1.5 sm:px-2", !hit ? "bg-background" :
            label === "Initial SL" ? "bg-[hsl(var(--loss))] text-white" : "bg-[hsl(var(--gain))] text-white")}>
            <dt className={cn("flex items-center gap-0.5 text-[10px] font-medium", !hit && "text-muted-foreground")}>
              {label}{hit && <Check size={11} aria-label="Hit" />}
            </dt>
            <dd className="font-mono text-[11px] font-medium tabular-nums sm:text-xs">{label === "TP3" && !price ? TP3_LABEL : fmtScalar(price ?? null)}</dd>
          </div>
        ))}
      </dl>
    </li>
  );
}

export function GoldOpenSignals({ rows, now, dataIssue }: { rows: GoldOpenSignal[]; now: number; dataIssue: boolean }) {
  const [view, setView] = useState<OpenView>("all");
  const pending = rows.filter((row) => row.state === "pending").length;
  const active = rows.filter((row) => row.state === "active").length;
  const unconfirmed = rows.filter((row) => row.state === "unconfirmed").length;
  const options = [
    { key: "all", title: "All open", count: pending + active },
    { key: "pending", title: "Pending", count: pending },
    { key: "active", title: "Active", count: active },
    ...(unconfirmed || view === "unconfirmed" ? [{ key: "unconfirmed" as const, title: "Unconfirmed", count: unconfirmed }] : []),
  ] as const;
  const shown = rows.filter((row) => view === "all" ? row.state !== "unconfirmed" : row.state === view);
  return (
    <section aria-labelledby="open-signals-title" className="desk-panel mb-5 overflow-hidden rounded-lg border border-border bg-card" data-testid="section-open-signals">
      <div className="flex flex-wrap items-center justify-between gap-x-5 gap-y-3 border-b border-border bg-card px-3.5 py-3.5 sm:px-4">
        <div className="flex items-center gap-3">
          <span className="grid size-9 shrink-0 place-items-center rounded-md bg-[hsl(var(--ink))] text-[hsl(var(--gold))]">
            <ListFilter size={16} aria-hidden="true" />
          </span>
          <div>
            <p className="font-mono text-[10px] font-medium uppercase tracking-[0.15em] text-muted-foreground">Open signal desk</p>
            <h2 id="open-signals-title" className="text-base font-semibold tracking-tight">Pending &amp; active signals</h2>
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Open signal status">
          {options.map(({ key, title, count }) => (
            <button type="button" key={key} aria-pressed={view === key} onClick={() => setView(key)}
              data-testid={`button-open-${key}`}
              className={cn("inline-flex min-h-8 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-medium focus-visible:outline-2 focus-visible:outline-ring",
                view === key ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card text-foreground hover:bg-muted")}>
              {title} <span className="rounded bg-current/10 px-1 font-mono text-[10px] tabular-nums">{count}</span>
            </button>
          ))}
        </div>
      </div>
      {shown.length ? (
        <ul className="divide-y divide-border">
          {shown.map((row) => <OpenSignalRow key={row.signal.signal_id} row={row} now={now} />)}
        </ul>
      ) : (
        <p className="flex items-center gap-2.5 px-3.5 py-4 text-sm text-muted-foreground sm:px-4" data-testid="text-open-signals-empty">
          {dataIssue ? <CircleAlert size={16} aria-hidden="true" className="shrink-0 text-accent-foreground" /> : <Activity size={16} aria-hidden="true" className="shrink-0 text-primary" />}
          {view === "unconfirmed" ? "No unconfirmed signals."
            : dataIssue ? "Scanner data is unavailable or out of date. Current signals cannot be verified."
              : view === "pending" ? "No published signals are waiting for entry."
                : view === "active" ? "No filled signals are currently being tracked."
                  : "No signals currently waiting for entry or active."}
        </p>
      )}
      {!dataIssue && view === "all" && unconfirmed > 0 && (
        <p className="border-t border-border bg-muted/35 px-3.5 py-2 text-xs text-muted-foreground sm:px-4">
          {unconfirmed} unconfirmed {unconfirmed === 1 ? "signal is" : "signals are"} listed separately and not counted as open.
        </p>
      )}
    </section>
  );
}
