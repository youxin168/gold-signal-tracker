import type { Cohort } from "@/lib/public-snapshot";
import { cohortSubtitle } from "@/lib/format";

export function CohortPicker({ cohorts, value, onChange }: { cohorts: Cohort[]; value: string; onChange: (id: string) => void }) {
  return (
    <label className="flex flex-col gap-1 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
      Evidence
      <select value={value} onChange={(e) => onChange(e.target.value)} data-testid="select-cohort"
        className="h-10 w-full max-w-md rounded-md border border-input bg-card px-2 font-sans text-sm normal-case tracking-normal text-foreground focus:outline-none focus:ring-2 focus:ring-ring">
        {cohorts.map((c) => <option key={c.id} value={c.id}>{c.label}{cohortSubtitle(c) ? ` (${cohortSubtitle(c)})` : ""}</option>)}
      </select>
    </label>
  );
}
