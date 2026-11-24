import type { Snapshot, Strategy } from "@/lib/public-snapshot";
import { PageHeader, EmptyState } from "@/components/bits";
import { SnapshotGate } from "@/components/snapshot-gate";
import { StrategyToggle } from "@/components/strategy-toggle";

function StrategyList({ rows }: { rows: Strategy[] }) {
  return (
    <ul className="divide-y divide-border overflow-hidden rounded-lg border border-card-border bg-card">
      {rows.map((strategy) => <li key={strategy.strategy_code}><StrategyToggle strategy={strategy} /></li>)}
    </ul>
  );
}

function List({ snap }: { snap: Snapshot }) {
  if (snap.strategies.length === 0) return <EmptyState title="No strategies published">The snapshot lists no frozen strategies.</EmptyState>;
  const currentFeed = snap.runner.data_source ?? "OANDA_PRACTICE_BID";
  const available = snap.strategies.filter((s) => !s.retired_live);
  const selected = available.filter((s) => (s.live_feed ?? "OANDA_PRACTICE_BID") === currentFeed);
  const other = available.filter((s) => !selected.includes(s));
  return (
    <div className="max-w-3xl space-y-5">
      {selected.length > 0 && <StrategyList rows={selected} />}
      {other.length > 0 && (
        <details className="rounded-lg border border-border p-3">
          <summary className="cursor-pointer px-1 py-2 text-sm text-muted-foreground" data-testid="toggle-other-versions">Other feed versions ({other.length})</summary>
          <div className="mt-2"><StrategyList rows={other} /></div>
        </details>
      )}
    </div>
  );
}

export default function StrategiesPage() {
  return (
    <>
      <PageHeader kicker="XAUUSD testing" title="Strategies">
        Tap a strategy to open or close its rules. This doesn’t turn the scanner on or off.
      </PageHeader>
      <SnapshotGate>{(s) => <List snap={s} />}</SnapshotGate>
    </>
  );
}
