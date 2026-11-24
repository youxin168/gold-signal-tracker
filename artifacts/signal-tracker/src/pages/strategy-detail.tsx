import { useState } from "react";
import { Link, useParams } from "wouter";
import { ArrowLeft } from "lucide-react";
import type { Snapshot } from "@/lib/public-snapshot";
import { PageHeader, EmptyState, MetricsGrid, ModeTag } from "@/components/bits";
import { SnapshotGate } from "@/components/snapshot-gate";
import { CohortPicker } from "@/components/cohort-picker";
import { fmtR, STYLE_NAMES } from "@/lib/format";

function NoteList({ title, items, tone }: { title: string; items: string[]; tone?: string }) {
  if (items.length === 0) return null;
  return (
    <div>
      <h4 className={`mb-1 font-mono text-[11px] uppercase tracking-wider ${tone ?? "text-muted-foreground"}`}>{title}</h4>
      <ul className="list-disc space-y-1 pl-5 text-sm">{items.map((x, i) => <li key={i}>{x}</li>)}</ul>
    </div>
  );
}

function Detail({ snap, code }: { snap: Snapshot; code: string }) {
  const s = snap.strategies.find((x) => x.strategy_code === code);
  const withScore = snap.cohorts.filter((c) => c.strategies.some((x) => x.strategy_code === code));
  const [cid, setCid] = useState(withScore.find((c) => c.signals.some((signal) => signal.strategy_code === code))?.id ??
    withScore.find((c) => c.mode === "BACKTEST")?.id ?? withScore[0]?.id ?? "");
  if (!s) return <EmptyState title={`No strategy named ${code}`}><Link href="/strategies" className="text-primary underline">Back to all strategies</Link></EmptyState>;
  const cohort = withScore.find((c) => c.id === cid) ?? withScore[0];
  const score = cohort?.strategies.find((x) => x.strategy_code === code);
  return (
    <>
      <PageHeader kicker={`${s.strategy_code} · ${STYLE_NAMES[s.style]} · ${s.version_state}${s.experimental ? " · experimental" : ""}`} title={s.name}>
        Source {s.source}. Entries on {s.entry_timeframe}, trend read on {s.trend_timeframe}.
        {s.retired_live && " Retired: no new signals. Prior results are in History."}
      </PageHeader>
      <div className="grid gap-10 lg:grid-cols-[1fr_320px]">
        <section className="rise">
          <h2 className="font-display mb-3 text-2xl">Rules</h2>
          <ol className="space-y-2">
            {s.rules.map((r, i) => (
              <li key={i} className="flex gap-3 rounded-md border border-card-border bg-card px-4 py-3 text-sm leading-relaxed">
                <span className="font-mono text-xs text-accent-foreground">{String(i + 1).padStart(2, "0")}</span><span>{r}</span>
              </li>
            ))}
          </ol>
          {s.notes.length > 0 && <div className="mt-6"><NoteList title="Design notes" items={s.notes} /></div>}
        </section>
        <aside className="rise">
          <dl className="divide-y divide-border rounded-md border border-card-border bg-card font-mono text-sm">
            {[["Expiry", `${s.expiry_minutes} min`], ["Max signals / day", String(s.max_signals_per_day)], ["Targets", s.target_multiples.map((t) => `${t}R`).join(" / ") || "Publisher supplied"], ["Version", s.version_state]].map(([k, v]) => (
              <div key={k} className="flex justify-between gap-3 px-4 py-2.5"><dt className="text-muted-foreground">{k}</dt><dd>{v}</dd></div>
            ))}
          </dl>
        </aside>
      </div>
      <section className="mt-12 border-t border-border pt-8">
        <h2 className="font-display mb-1 text-2xl">Analyst notes</h2>
        <p className="mb-4 text-sm text-muted-foreground">Notes are written per evidence source and apply only to the one selected.</p>
        {withScore.length === 0 || !cohort || !score ? (
          <EmptyState title="Not yet scored">No cohort in this snapshot has scored this strategy.</EmptyState>
        ) : (
          <div key={cohort.id} className="rise space-y-5">
            <div className="flex flex-wrap items-end gap-3"><CohortPicker cohorts={withScore} value={cohort.id} onChange={setCid} /><ModeTag mode={cohort.mode} />
              <span className="font-mono text-xs text-muted-foreground">{score.rank !== null ? `rank ${score.rank} in ${score.style}` : `unranked${score.rank_reason ? `: ${score.rank_reason}` : ""}`}</span></div>
            <p className="font-display max-w-3xl text-xl leading-snug">{score.analyst.summary}</p>
            <div className="grid gap-5 md:grid-cols-3">
              <NoteList title="Strengths" items={score.analyst.strengths} tone="text-[hsl(var(--gain))]" />
              <NoteList title="Weaknesses" items={score.analyst.weaknesses} tone="text-[hsl(var(--loss))]" />
              <NoteList title="Warnings" items={score.analyst.warnings} tone="text-accent-foreground" />
            </div>
            <div className="flex flex-wrap gap-6 font-mono text-xs">
              {score.analyst.best_session && <span>Best session: {score.analyst.best_session.sessions.join(", ")} ({fmtR(score.analyst.best_session.expectancy_r)})</span>}
              {score.analyst.worst_session && <span>Worst session: {score.analyst.worst_session.sessions.join(", ")} ({fmtR(score.analyst.worst_session.expectancy_r)})</span>}
              {score.coverage && <span className="text-muted-foreground">Coverage: {Object.entries(score.coverage).map(([k, v]) => `${k} ${v}`).join(" · ")}</span>}
            </div>
            <MetricsGrid m={score.metrics} />
          </div>
        )}
      </section>
    </>
  );
}

export default function StrategyDetailPage() {
  const params = useParams<{ code: string }>();
  const code = decodeURIComponent(params.code ?? "");
  return (
    <>
      <Link href="/strategies" className="mb-6 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground" data-testid="link-back"><ArrowLeft className="h-4 w-4" /> All strategies</Link>
      <SnapshotGate>{(s) => <Detail snap={s} code={code} />}</SnapshotGate>
    </>
  );
}
