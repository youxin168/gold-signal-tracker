import type { PublicSignal, Style } from "@/lib/public-snapshot";
import { matchesGoldTargetRange, type TargetRange } from "./gold-targets.ts";

const CAMBODIA_OFFSET = 7 * 60 * 60 * 1000;
export const DAY_MS = 24 * 60 * 60 * 1000;
const FINISHED = new Set(["TP2", "TP3", "SL", "BE"]);

function localIso(value: string | number | null): string {
  const time = typeof value === "number" ? value : value ? Date.parse(value) : NaN;
  return Number.isFinite(time) ? new Date(time + CAMBODIA_OFFSET).toISOString() : "";
}

export function cambodiaDate(value: string | number | null) {
  return localIso(value).slice(0, 10);
}

export function cambodiaDateTime(value: string | null) {
  return localIso(value).slice(0, 16).replace("T", " ") || "—";
}

export function filterHistory(
  signals: readonly PublicSignal[],
  { code, from, to, style, range }: { code: string; from: string; to: string; style?: Style | ""; range?: TargetRange },
) {
  if (from && to && from > to) return [];
  return signals.filter((signal) => {
    if (code && signal.strategy_code !== code) return false;
    if (style && signal.style !== style) return false;
    if (!matchesGoldTargetRange(signal, range)) return false;
    if (!from && !to) return true;
    const day = cambodiaDate(signal.closed_at ?? signal.issued_at_utc);
    return !!day && (!from || day >= from) && (!to || day <= to);
  });
}

export function summarizeHistory(signals: readonly PublicSignal[], excludedCodes: ReadonlySet<string>) {
  let gains = 0, losses = 0, wins = 0, losingTrades = 0, flat = 0, archived = 0;
  for (const signal of signals) {
    if (!signal.closed_at || !FINISHED.has(signal.status) || signal.unresolved_reason || !signal.result_r?.trim()) continue;
    const r = Number(signal.result_r);
    if (!Number.isFinite(r)) continue;
    if (excludedCodes.has(signal.strategy_code)) {
      archived++;
    } else if (r > 0) {
      gains += r;
      wins++;
    } else if (r < 0) {
      losses += r;
      losingTrades++;
    } else {
      flat++;
    }
  }
  const closed = wins + losingTrades + flat;
  // Match the worksheet's two decimal places and avoid a signed zero.
  const total = Number((gains + losses).toFixed(2)) || 0;
  return { netR: closed ? total : null, gains, losses, closed, wins, losingTrades, flat, archived };
}
