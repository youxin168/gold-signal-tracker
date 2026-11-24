import { useState } from "react";
import { Link } from "wouter";
import type { Snapshot, Style } from "@/lib/public-snapshot";
import { PageHeader, EmptyState, MetricsGrid, EquityCurve, BreakdownTables, ModeTag } from "@/components/bits";
import { SnapshotGate } from "@/components/snapshot-gate";
import { CohortPicker } from "@/components/cohort-picker";
import { fmtPct, fmtR, rTone, STYLE_NAMES } from "@/lib/format";
import { cn } from "@/lib/utils";

function ScoreBody({ snap }: { snap: Snapshot }) {
  const [id, setId] = useState(snap.cohorts.find((c) => c.signals.length)?.id ??
    snap.cohorts.find((c) => c.mode === "BACKTEST")?.id ?? snap.cohorts[0]?.id ?? "");
  const cohort = snap.cohorts.find((c) => c.id === id) ?? snap.cohorts[0];
  const [sel, setSel] = useState<string | null>(null);
  const [style, setStyle] = useState<Style>("INT");
  if (!cohort) return <EmptyState title="No cohorts in this snapshot">Nothing has been scored yet.</EmptyState>;
  const strat = cohort.strategies.find((s) => s.strategy_code === sel) ?? null;
  const focus = strat ?? cohort.styles.find((row) => row.style === style) ?? cohort.styles[0] ?? null;
  const firstIssue = cohort.signals.reduce<string | undefined>((earliest, signal) => {
    const inScope = strat ? signal.strategy_code === strat.strategy_code : signal.style === focus?.style;
    return inScope && (!earliest || signal.issued_at_utc < earliest) ? signal.issued_at_utc : earliest;
  }, undefined);
  return (
    <div className="space-y-10">
      <div className="flex flex-wrap items-end gap-4">
        <CohortPicker cohorts={snap.cohorts} value={cohort.id} onChange={(v) => { setId(v); setSel(null); }} />
        <ModeTag mode={cohort.mode} />
      </div>
      {cohort.mode === "BACKTEST" && !cohort.signals.length &&
        <p className="rounded-md border border-border bg-card p-4 text-sm">
          No qualifying trades in this fold. See the strategy’s analyst notes for missing filter evidence; returns are not estimable.
        </p>}

      <section key={`styles-${cohort.id}`} className="rise">
        <h2 className="font-display mb-3 text-2xl">By style</h2>
        {cohort.styles.length === 0 ? <EmptyState title="No style scores">This cohort has no scored styles.</EmptyState> : (
          <div className="space-y-6">
            {cohort.styles.map((s) => (
              <div key={s.style}>
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">{s.style} · {STYLE_NAMES[s.style]}</p>
                  <button type="button" aria-pressed={!sel && s.style === style}
                    onClick={() => { setSel(null); setStyle(s.style); }}
                    className="rounded border border-border px-2 py-1 text-xs text-primary hover:bg-card">
                    {s.style} equity and breakdowns
                  </button>
                </div>
                <MetricsGrid m={s.metrics} />
              </div>
            ))}
          </div>
        )}
      </section>

      <section key={`strats-${cohort.id}`} className="rise">
        <h2 className="font-display mb-1 text-2xl">By strategy</h2>
        <p className="mb-3 text-sm text-muted-foreground">Ranks require at least two comparable strategies within a style and 100 completed trades each. Select a strategy for its curve and breakdowns.</p>
        {cohort.strategies.length === 0 ? <EmptyState title="No strategy scores">This cohort scored no strategies.</EmptyState> : (
          <div className="overflow-x-auto rounded-md border border-card-border bg-card">
            <table className="w-full min-w-[760px] font-mono text-[13px]">
              <thead className="border-b border-border bg-muted/60 text-left text-[11px] uppercase tracking-wider text-muted-foreground">
                <tr><th className="px-3 py-2">Rank</th><th className="px-3 py-2">Strategy</th><th className="px-3 py-2">Style</th><th className="px-3 py-2 text-right">Completed</th><th className="px-3 py-2 text-right">Expectancy</th><th className="px-3 py-2 text-right">Total</th><th className="px-3 py-2">Sample</th><th className="px-3 py-2 text-right">Win rate</th></tr>
              </thead>
              <tbody className="divide-y divide-border">
                {cohort.strategies.map((s) => (
                  <tr key={s.strategy_code} onClick={() => setSel(s.strategy_code)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && setSel(s.strategy_code)}
                    aria-selected={sel === s.strategy_code} data-testid={`row-strategy-${s.strategy_code}`}
                    className={cn("cursor-pointer transition-colors hover:bg-muted/40 focus:outline-none focus-visible:bg-muted", sel === s.strategy_code && "bg-accent/40")}>
                    <td className="px-3 py-2.5">{s.rank ?? <span className="text-muted-foreground" title={s.rank_reason ?? undefined}>unranked</span>}{s.rank === null && s.rank_reason && <span className="block max-w-[14rem] font-sans text-[11px] text-muted-foreground">{s.rank_reason}</span>}</td>
                    <td className="px-3 py-2.5"><span>{s.strategy_code}</span><span className="block font-sans text-xs text-muted-foreground">{s.name} · {s.version_state}</span></td>
                    <td className="px-3 py-2.5">{s.style}</td>
                    <td className="px-3 py-2.5 text-right">{s.metrics.completed}</td>
                    <td className={cn("px-3 py-2.5 text-right", rTone(s.metrics.expectancy_r))}>{fmtR(s.metrics.expectancy_r)}</td>
                    <td className={cn("px-3 py-2.5 text-right", rTone(s.metrics.total_r))}>{fmtR(s.metrics.total_r)}</td>
                    <td className="px-3 py-2.5 text-muted-foreground">{s.metrics.sample_size_badge}</td>
                    <td className="px-3 py-2.5 text-right">{fmtPct(s.metrics.win_rate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {focus && (
        <section key={`focus-${cohort.id}-${sel ?? style}`} className="rise space-y-5" aria-label="Selected equity and breakdowns">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="font-display text-2xl">{strat ? `${strat.strategy_code} in detail` : `${focus.style} style in detail`}</h2>
            {strat && <Link href={`/strategies/${encodeURIComponent(strat.strategy_code)}`} className="text-sm text-primary underline underline-offset-2" data-testid="link-strategy-detail">Frozen rules and notes</Link>}
          </div>
          {strat && <MetricsGrid m={strat.metrics} />}
          <EquityCurve points={focus.metrics.equity_curve_r} startedAt={firstIssue} />
          <BreakdownTables breakdowns={focus.breakdowns} />
        </section>
      )}
    </div>
  );
}

export default function ScoreboardPage() {
  return (
    <>
      <PageHeader kicker="Scores · one evidence source at a time" title="Scoreboard">
        Fill rate is filled ÷ (filled + expired). Win rate counts positive net results among completed trades only. Intervals are descriptive, not forecasts.
      </PageHeader>
      <SnapshotGate>{(s) => <ScoreBody snap={s} />}</SnapshotGate>
    </>
  );
}
