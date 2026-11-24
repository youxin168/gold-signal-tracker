import { fmtR, rTone } from "@/lib/format";
import type { summarizeHistory } from "@/lib/history-results";
import { cn } from "@/lib/utils";

export function HistoryResultSummary({ summary }: { summary: ReturnType<typeof summarizeHistory> }) {
  const { netR, closed, gains, losses, wins, losingTrades, flat, archived } = summary;
  const direction = netR === null ? "No confirmed results" : netR > 0 ? "Net profit" : netR < 0 ? "Net loss" : "Flat";
  return (
    <section aria-label="Test result summary" aria-live="polite"
      className="desk-panel mb-4 rounded-xl border border-border bg-card px-3.5 py-3.5 sm:px-4">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 className="text-base font-semibold tracking-tight">Result summary</h2>
        <span className="text-xs text-muted-foreground">{closed} confirmed {closed === 1 ? "result" : "results"}</span>
      </div>
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-4">
        <div className="bg-muted px-3 py-2.5">
          <dt className="text-xs text-muted-foreground">{direction}</dt>
          <dd className={cn("mt-0.5 font-mono text-xl font-semibold tabular-nums", rTone(netR))}
            data-testid="text-history-net-r">{fmtR(netR)}</dd>
        </div>
        <div className="bg-card px-3 py-2">
          <dt className="text-xs text-muted-foreground">Winning results · {wins}</dt>
          <dd className={cn("font-mono text-base tabular-nums", rTone(gains))}>{fmtR(closed ? gains : null)}</dd>
        </div>
        <div className="bg-card px-3 py-2">
          <dt className="text-xs text-muted-foreground">Losing results · {losingTrades}</dt>
          <dd className={cn("font-mono text-base tabular-nums", rTone(losses))}>{fmtR(closed ? losses : null)}</dd>
        </div>
        <div className="bg-card px-3 py-2">
          <dt className="text-xs text-muted-foreground">Flat results</dt>
          <dd className="font-mono text-base tabular-nums">{closed ? flat : "—"}</dd>
        </div>
      </dl>
      <p className="mt-2 text-[11px] text-muted-foreground">
        Totals use the filters above. R is measured against each signal’s original risk, not cash profit.
        {archived > 0 && ` ${archived} retired test ${archived === 1 ? "result is" : "results are"} excluded to avoid counting the same setup twice. Select that version to see its own total.`}
      </p>
    </section>
  );
}
