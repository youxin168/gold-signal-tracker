import { useState } from "react";
import { Link } from "wouter";
import { ArrowUpRight, FileSpreadsheet, Scale } from "lucide-react";
import { PageHeader, EmptyState, Segmented, ModeTag } from "@/components/bits";
import { SnapshotGate } from "@/components/snapshot-gate";
import { CohortPicker } from "@/components/cohort-picker";
import type { Cohort, HeadToHead, Metrics, Snapshot, Strategy, Style } from "@/lib/public-snapshot";
import { fmtDate, fmtPct, fmtR, fmtScalar, rTone, STYLE_NAMES } from "@/lib/format";
import { cn } from "@/lib/utils";

const STYLES: Style[] = ["SCA", "INT", "SWG"];
const METHOD = "/about";
const matchupId = (h: HeadToHead) => `${h.claude_code}/${h.external_code}`;

const ci = (c: [number, number] | null, pct = false) => (c ? (pct ? `${fmtPct(c[0])} to ${fmtPct(c[1])}` : `${fmtR(c[0])} to ${fmtR(c[1])}`) : "CI not available");

function Row({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border py-2 last:border-0">
      <dt className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">{label}</dt>
      <dd className="text-right">
        <span className={cn("font-mono text-[15px]", tone)}>{value}</span>
        {hint && <span className="block text-[11px] text-muted-foreground">{hint}</span>}
      </dd>
    </div>
  );
}

function Side({ role, code, m, strategy, coverage, isLeader }: { role: string; code: string; m: Metrics | null; strategy?: Strategy; coverage?: Record<string, number> | null; isLeader: boolean }) {
  return (
    <section className={cn("rise rounded-md border bg-card p-4", isLeader ? "border-primary/50" : "border-card-border")} data-testid={`card-side-${code}`}>
      <header className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-accent-foreground">{role}</p>
          <p className="font-display text-2xl">{code}</p>
          {strategy && <p className="text-xs text-muted-foreground">{strategy.name} · {strategy.version_state}{strategy.experimental ? " · experimental" : ""}</p>}
        </div>
        <Link href={`/strategies/${encodeURIComponent(code)}`} className="inline-flex items-center gap-1 text-sm text-primary underline underline-offset-2" data-testid={`link-strategy-${code}`}>
          Rules <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
        </Link>
      </header>
      {!m ? (
        <p className="rounded border border-dashed border-input px-3 py-4 text-sm text-muted-foreground" data-testid={`text-no-metrics-${code}`}>
          No comparable metrics in the overlap window. This is missing evidence, not a poor result.
        </p>
      ) : (
        <>
          <div className="mb-2 flex items-baseline justify-between rounded bg-muted/60 px-3 py-2">
            <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">Comparable sample</span>
            <span className="font-mono text-sm" data-testid={`text-sample-${code}`}>{m.completed} completed · {m.sample_size_badge}</span>
          </div>
          <dl>
            <Row label="Expectancy" value={fmtR(m.expectancy_r)} tone={rTone(m.expectancy_r)} hint={`95% ${ci(m.expectancy_r_ci_95)}`} />
            <Row label="Win rate" value={fmtPct(m.win_rate)} hint={`95% ${ci(m.win_rate_ci_95, true)}`} />
            <Row label="Total" value={fmtR(m.total_r)} tone={rTone(m.total_r)} hint={`avg ${fmtR(m.average_r)}`} />
            <Row label="Profit factor" value={fmtScalar(m.profit_factor)} hint={m.profit_factor_status} />
            <Row label="Max drawdown" value={fmtR(m.max_drawdown_r)} />
            <Row label="Losing streak" value={fmtScalar(m.longest_losing_streak, 0)} />
            <Row label="Fill rate" value={fmtPct(m.fill_rate)} hint={`${m.filled} filled · ${m.expired} expired · ${m.entry_unresolved} unresolved`} />
            {coverage && <Row label="Full-fold coverage"
              value={`${coverage.technical_candidates_before_filters ?? 0} technical candidates`}
              hint={`${coverage.both_filters_pass ?? 0} decision slots passed both evidence gates`} />}
          </dl>
        </>
      )}
    </section>
  );
}

function NotConfigured({ cohort }: { cohort: Cohort }) {
  return (
    <EmptyState title="No external strategy is configured for this evidence">
      <p>Comparisons appear only when the engine has CLD and an external or own strategy on {cohort.label}. Nothing is compared here, so no side is judged.</p>
      <div className="mt-4 rounded border border-border bg-card px-4 py-3">
        <p className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider text-accent-foreground"><FileSpreadsheet className="h-4 w-4" aria-hidden />To add one</p>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm">
          <li>Register an EXT1, EXT2, or OWN strategy with <code>register-external</code>.</li>
          <li>Run its backtest or record its signals with <code>import-signals</code>.</li>
          <li>Re-export the snapshot. The README has the files and commands.</li>
        </ol>
      </div>
      <Link href={METHOD} className="mt-3 inline-block text-primary underline underline-offset-2" data-testid="link-method-config">Read Method &amp; risk</Link>
    </EmptyState>
  );
}

function Body({ snap }: { snap: Snapshot }) {
  const first = snap.cohorts.find((item) => item.comparisons?.length) ?? snap.cohorts[0];
  const [cohortId, setCohortId] = useState(first?.id ?? "");
  const [style, setStyle] = useState<Style>(first?.comparisons?.[0]?.style ?? "INT");
  const [pick, setPick] = useState("");
  const cohort = snap.cohorts.find((c) => c.id === cohortId) ?? snap.cohorts[0];
  const forStyle = (cohort?.comparisons ?? []).filter((h) => h.style === style);

  if (!cohort) return <EmptyState title="No evidence cohorts published">The snapshot has no cohorts yet. <Link href={METHOD} className="text-primary underline">Method &amp; risk</Link> explains how evidence is produced.</EmptyState>;

  const h = forStyle.find((x) => matchupId(x) === pick) ?? forStyle[0];
  const scoreOf = (code: string) => cohort.strategies.find((s) => s.strategy_code === code);
  const stratOf = (code: string) => snap.strategies.find((s) => s.strategy_code === code);
  const noOverlap = h && (!h.start_utc || !h.end_utc_exclusive);
  const anyComparisons = (cohort.comparisons ?? []).length > 0;

  return (
    <div className="space-y-6">
      <div className="rise flex flex-col gap-4 rounded-md border border-border bg-card/60 p-4 md:flex-row md:items-end md:justify-between">
        <div className="w-full md:max-w-md">
          <CohortPicker cohorts={snap.cohorts} value={cohort.id} onChange={(id) => {
            setCohortId(id); setPick("");
            const comparisons = snap.cohorts.find((c) => c.id === id)?.comparisons;
            if (comparisons?.length && !comparisons.some((match) => match.style === style)) setStyle(comparisons[0].style);
          }} />
          <p className="mt-1.5 flex items-center gap-2 text-xs text-muted-foreground"><ModeTag mode={cohort.mode} />{cohort.data_source ?? "no data source"}</p>
        </div>
        <div className="flex flex-col gap-1">
          <span className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">Style</span>
          <Segmented label="Style" value={style} onChange={(v) => { setStyle(v); setPick(""); }} options={STYLES.map((s) => ({ value: s, label: STYLE_NAMES[s] }))} />
        </div>
        {h && (
          <label className="flex min-w-0 flex-col gap-1 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
            Matchup
            <select value={matchupId(h)} onChange={(event) => setPick(event.target.value)}
              className="h-10 w-full rounded-md border border-input bg-card px-2 text-xs normal-case tracking-normal text-foreground">
              {forStyle.map((match) => <option key={matchupId(match)} value={matchupId(match)}>
                {match.claude_code} vs {match.external_code}
              </option>)}
            </select>
          </label>
        )}
      </div>

      {!anyComparisons ? (
        <NotConfigured cohort={cohort} />
      ) : !h ? (
        <EmptyState title={`No ${STYLE_NAMES[style]} matchup in this cohort`}>
          The engine published comparisons for other styles only. A strategy is compared solely against one of the same style. Try another style, or read <Link href={METHOD} className="text-primary underline">Method &amp; risk</Link>.
        </EmptyState>
      ) : (
        <>
          <div className="rise rounded-md border border-border bg-card px-5 py-4" data-testid="panel-verdict">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-xs text-muted-foreground">
              <span className="flex items-center gap-1.5 text-accent-foreground"><Scale className="h-4 w-4" aria-hidden />{h.claude_code} vs {h.external_code}</span>
              <span data-testid="text-overlap">{noOverlap ? "No overlapping window (UTC)" : `Overlap ${fmtDate(h.start_utc)} to ${fmtDate(h.end_utc_exclusive)} UTC, end exclusive`}</span>
            </div>
            <p className="font-display mt-2 text-2xl" data-testid="text-leader">
              {h.leader ? <>Observed leader: <span className="text-primary">{h.leader}</span></> : "No leader declared"}
            </p>
            <p className="mt-1 max-w-2xl text-sm leading-relaxed text-muted-foreground" data-testid="text-explanation">{h.explanation}</p>
            {h.leader ? (
              <p className="mt-2 text-xs text-muted-foreground">Observed in this testing sample only, as computed by the engine. Not a forecast.</p>
            ) : (
              <p className="mt-2 text-xs text-muted-foreground">The engine withholds a leader when evidence is inadequate. Insufficient evidence is not a loss for either side. <Link href={METHOD} className="text-primary underline" data-testid="link-method-leader">Why</Link></p>
            )}
          </div>
          {noOverlap && (
            <EmptyState title="No shared period can be established">
              Without a shared UTC window their numbers cannot be read side by side. See <Link href={METHOD} className="text-primary underline" data-testid="link-method-overlap">Method &amp; risk</Link> on overlap rules.
            </EmptyState>
          )}
          <div className="grid gap-4 md:grid-cols-2">
            <Side role="CLD" code={h.claude_code} m={h.claude_metrics} strategy={stratOf(h.claude_code)} coverage={scoreOf(h.claude_code)?.coverage} isLeader={h.leader === h.claude_code} />
            <Side role={stratOf(h.external_code)?.source ?? "External"} code={h.external_code} m={h.external_metrics} strategy={stratOf(h.external_code)} coverage={scoreOf(h.external_code)?.coverage} isLeader={h.leader === h.external_code} />
          </div>
        </>
      )}
    </div>
  );
}

export default function ComparePage() {
  return (
    <>
      <PageHeader kicker="Head to head · testing only" title="Compare">
        Same style, same evidence, same UTC window. The engine decides whether a leader can be named; this page only shows its result.
      </PageHeader>
      <SnapshotGate>{(s) => <Body snap={s} />}</SnapshotGate>
    </>
  );
}
