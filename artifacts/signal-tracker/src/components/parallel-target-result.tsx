import { fmtR, rTone } from "@/lib/format";
import type { ParallelTargets } from "@/lib/public-snapshot";
import { cn } from "@/lib/utils";

export const PARALLEL_NOTE = "Equal-size test orders, one per available target. Original SL stays fixed. Gross R before costs; independent of Trade result.";

export function ParallelTargetResult({ plan }: { plan?: ParallelTargets }) {
  if (!plan) return <span className="text-muted-foreground" title="Not tracked for this record">—</span>;
  const status = plan.unresolved_reason ? "Unconfirmed data" : plan.phase === "EXPIRED" ? "Not filled"
    : plan.phase === "PENDING" ? "Waiting for entry" : plan.phase === "ACTIVE" ? "Partial · orders open" : "All orders closed";
  return (
    <div className="space-y-1 text-xs" title={plan.unresolved_reason ?? PARALLEL_NOTE}>
      <div className="flex flex-wrap gap-x-2 gap-y-0.5">
        <span className={cn("font-semibold tabular-nums", rTone(plan.realized_r))}>
          {plan.realized_r === null ? "—" : `${fmtR(plan.realized_r)} combined`}
        </span>
        <span className="text-muted-foreground">{status}</span>
      </div>
      <div className="flex flex-wrap gap-x-2 gap-y-0.5 font-mono text-[11px]">
        {plan.legs.map((leg) => (
          <span key={leg.target} className={cn("whitespace-nowrap", rTone(leg.result_r))}>
            TP{leg.target}: {leg.status === "OPEN" ? plan.phase === "PENDING" ? "Pending" : "Open" : leg.status === "EXPIRED" ? "Unfilled"
              : `${fmtR(leg.result_r)}${leg.status === "SL" ? " (SL)" : ""}`}
          </span>
        ))}
      </div>
      {plan.per_total_risk_r !== null && <p className="text-[11px] text-muted-foreground">
        {fmtR(plan.per_total_risk_r)} vs. total starting risk
      </p>}
    </div>
  );
}
