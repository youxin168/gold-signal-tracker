import type { Cohort, PublicSignal, Scalar, SignalStatus, Tp3WatchState } from "@/lib/public-snapshot";

export const STATUSES: SignalStatus[] = ["PENDING", "ACTIVE", "TP1", "TP2_OPEN", "TP2", "TP3", "SL", "BE", "EXPIRED"];
export const UNRESOLVED: SignalStatus[] = ["PENDING", "ACTIVE", "TP1", "TP2_OPEN"];
export const STYLE_NAMES = { SCA: "Scalp", INT: "Intraday", SWG: "Swing" } as const;

export function fmtDate(iso: string | null | undefined, withTime = true): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const date = d.toISOString().slice(0, 10);
  return withTime ? `${date} ${d.toISOString().slice(11, 16)} UTC` : date;
}

/** Age is based on issue time and rounds down so a new signal isn't shown older than it is. */
export function fmtAge(iso: string, nowMs: number): string | null {
  const elapsed = nowMs - Date.parse(iso);
  if (!Number.isFinite(elapsed) || elapsed < 0) return null;
  const minutes = Math.floor(elapsed / 60_000);
  if (minutes === 0) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    const rest = minutes % 60;
    return `${hours} hr${rest ? ` ${rest} min` : ""} ago`;
  }
  const days = Math.floor(hours / 24);
  return `${days} ${days === 1 ? "day" : "days"} ago`;
}

export function hitLevels(status: SignalStatus, tp2At?: string | null, watch?: Tp3WatchState) {
  const tp3 = status === "TP3" || watch === "HIT";
  const tp2 = status === "TP3" || status === "TP2" || status === "TP2_OPEN" || (status === "BE" && Boolean(tp2At));
  return { sl: status === "SL", tp1: tp2 || status === "TP1" || status === "BE", tp2, tp3 };
}

/** Scalars arrive from Python as number, decimal string, or null. Never invent a value. */
export function fmtScalar(v: Scalar, digits = 2, suffix = ""): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return String(v);
  return `${n.toFixed(digits)}${suffix}`;
}

/** Ratios (0..1) shown as percent. */
export function fmtPct(v: Scalar): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return String(v);
  return `${(n * 100).toFixed(1)}%`;
}

export function fmtR(v: Scalar | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  return `${n > 0 ? "+" : ""}${n.toFixed(2)}R`;
}

export function rTone(v: Scalar | undefined): string {
  const n = Number(v);
  if (v === null || v === undefined || !Number.isFinite(n) || n === 0) return "text-foreground";
  return n > 0 ? "text-[hsl(var(--gain))]" : "text-[hsl(var(--loss))]";
}

export function cohortSubtitle(c: Cohort): string {
  return [c.data_source, c.fold ? `fold ${c.fold}` : null].filter(Boolean).join(" · ");
}

export function uniq<T>(xs: T[]): T[] {
  return Array.from(new Set(xs)).sort() as T[];
}

export function sortSignals(xs: PublicSignal[]): PublicSignal[] {
  return [...xs].sort((a, b) => b.issued_at_utc.localeCompare(a.issued_at_utc));
}
