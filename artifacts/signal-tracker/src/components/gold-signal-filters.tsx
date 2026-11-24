import type { Style } from "@/lib/public-snapshot";

const control = "h-9 w-full min-w-0 rounded-md border border-border bg-card px-2 text-sm font-normal text-foreground";
const label = "grid min-w-0 gap-1 text-xs font-medium text-muted-foreground";

export const EMPTY_DISTANCE = { min: "", max: "" };
export type DistanceInputs = typeof EMPTY_DISTANCE;

export function StyleSelect({ scope, value, onChange }: {
  scope: "home" | "history"; value: Style | ""; onChange: (value: Style | "") => void;
}) {
  return (
    <label className={label}>
      Trading style
      <select className={control} value={value} onChange={(event) => onChange(event.target.value as Style | "")}
        data-testid={`select-${scope}-style`}>
        <option value="">All styles</option>
        <option value="SCA">Scalping</option>
        <option value="INT">Intraday</option>
        <option value="SWG">Swing</option>
      </select>
    </label>
  );
}

export function TargetDistanceInputs({ scope, value, onChange, invalid }: {
  scope: "home" | "history"; value: DistanceInputs; onChange: (value: DistanceInputs) => void; invalid: boolean;
}) {
  const helpId = `${scope}-target-distance-help`;
  const errorId = `${scope}-target-distance-error`;
  return (
    <fieldset className="min-w-0">
      <legend className="mb-1 text-xs font-medium text-muted-foreground">Target distance (pips)</legend>
      <div className="flex max-w-xs items-center gap-2">
        {(["min", "max"] as const).map((bound) => (
          <input key={bound} className={control} type="number" inputMode="numeric" min={0} step={1}
            aria-label={bound === "min" ? "Minimum target distance in pips" : "Maximum target distance in pips"}
            placeholder={bound === "min" ? "Min" : "Max"} value={value[bound]}
            aria-describedby={invalid ? `${helpId} ${errorId}` : helpId} aria-invalid={invalid || undefined}
            onChange={(event) => onChange({ ...value, [bound]: event.target.value })}
            data-testid={`input-${scope}-target-${bound}`} />
        ))}
      </div>
      <p id={helpId} className="mt-1 text-[11px] text-muted-foreground">
        Entry to farthest listed TP · 100 gold pips = $1/oz
      </p>
      {invalid && <p id={errorId} role="alert" className="mt-1 text-xs text-destructive">
        Use whole pips and keep the maximum at or above the minimum.
      </p>}
    </fieldset>
  );
}
