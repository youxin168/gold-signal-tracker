import { useMemo, useState } from "react";
import { Link } from "wouter";
import type { Snapshot } from "@/lib/public-snapshot";
import { PageHeader, EmptyState, FilterSelect, SignalTable } from "@/components/bits";
import { SnapshotGate } from "@/components/snapshot-gate";
import { useTickingNow } from "@/hooks/use-ticking-now";
import { sortSignals, STATUSES, uniq } from "@/lib/format";
import { publishedSignalState } from "@/lib/gold-labels";

function LiveBody({ snap }: { snap: Snapshot }) {
  const now = useTickingNow();
  const live = useMemo(() => {
    const retired = new Set(snap.strategies.filter((s) => s.retired_live).map((s) => s.strategy_code));
    return sortSignals(snap.cohorts.filter((c) => c.mode === "LIVE").flatMap((c) => c.signals)
      .filter((s) => !retired.has(s.strategy_code)));
  }, [snap]);
  const [f, setF] = useState({ style: "", source: "", pair: "", status: "" });
  const rows = live.filter((s) => (!f.style || s.style === f.style) && (!f.source || s.source === f.source) && (!f.pair || s.pair === f.pair)
    && (!f.status || (publishedSignalState(s, now).unconfirmed ? "Unconfirmed" : s.status) === f.status));
  const set = (k: keyof typeof f) => (v: string) => setF((p) => ({ ...p, [k]: v }));
  const hasLiveCohort = snap.cohorts.some((c) => c.mode === "LIVE");
  return (
    <>
      <section aria-label="Published signal filters" className="desk-panel mb-4 rounded-lg border border-border bg-card p-4">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold">Filter the journal</h2>
          <p className="font-mono text-xs text-muted-foreground">{rows.length} of {live.length} records</p>
        </div>
        <div className="grid items-end gap-3 min-[390px]:grid-cols-2 lg:grid-cols-4 [&_select]:min-w-0">
        <FilterSelect id="style" label="Style" value={f.style} onChange={set("style")} options={uniq(snap.strategies.map((s) => s.style))} />
        <FilterSelect id="source" label="Source" value={f.source} onChange={set("source")} options={uniq(snap.strategies.map((s) => s.source))} />
        <FilterSelect id="pair" label="Pair" value={f.pair} onChange={set("pair")} options={uniq(live.map((s) => s.pair))} />
        <FilterSelect id="status" label="Status" value={f.status} onChange={set("status")} options={[...STATUSES, "Unconfirmed"]} />
        </div>
      </section>
      {live.length === 0 ? (
        <EmptyState title="No live signals published yet">
          {hasLiveCohort ? "The live cohort exists but holds zero records." : "No live cohort is present in this snapshot."} That is expected while the scheduled runner is {snap.runner.state.replace("_", " ")}. Historical evidence is in{" "}
          <Link href="/history" className="text-primary underline underline-offset-2">History</Link> and{" "}
          <Link href="/scoreboard" className="text-primary underline underline-offset-2">Scoreboard</Link>.
        </EmptyState>
      ) : rows.length === 0 ? (
        <EmptyState title="Nothing matches these filters">Clear one or more filters to see the {live.length} published live records.</EmptyState>
      ) : (
        <SignalTable signals={rows} relativeAge />
      )}
    </>
  );
}

export default function LivePage() {
  return (
    <>
      <PageHeader kicker="Live journal · all statuses" title="Published signals">
        Published signals from active strategies. Retired versions are in History. These are journal entries, not instructions, and the file can lag the market.
      </PageHeader>
      <SnapshotGate>{(s) => <LiveBody snap={s} />}</SnapshotGate>
    </>
  );
}
