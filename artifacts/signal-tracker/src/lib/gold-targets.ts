import type { PublicSignal } from "@/lib/public-snapshot";

// One tracker pip is $0.01/oz. Broker definitions may differ.
const PIPS_PER_DOLLAR = 100;

export function goldTargetMetrics(direction: PublicSignal["direction"], entry: string, stop: string, target: string) {
  const [entryPips, stopPips, targetPips] = [entry, stop, target].map((value) =>
    value.trim() ? Math.round(Number(value) * PIPS_PER_DOLLAR) : NaN);
  if (![entryPips, stopPips, targetPips].every((value) => Number.isSafeInteger(value) && value > 0)) return null;
  const sign = direction === "BUY" ? 1 : -1;
  const risk = sign * (entryPips - stopPips);
  const pips = sign * (targetPips - entryPips);
  if (risk <= 0 || pips <= 0) return null;
  return { rewardRatio: pips / risk, moveUsd: pips / PIPS_PER_DOLLAR, pips };
}

export function parseTargetRange(minInput: string, maxInput: string) {
  const bound = (raw: string, fallback: number) => raw === "" ? fallback : /^\d+$/.test(raw) ? Number(raw) : NaN;
  const min = bound(minInput, 0);
  const max = bound(maxInput, Infinity);
  const active = minInput !== "" || maxInput !== "";
  const invalid = !Number.isSafeInteger(min) || (maxInput !== "" && !Number.isSafeInteger(max)) || min > max;
  return { min, max, active, invalid };
}

export type TargetRange = ReturnType<typeof parseTargetRange>;

export function matchesGoldTargetRange(signal: PublicSignal, range?: TargetRange) {
  if (!range?.active) return true;
  if (range.invalid || signal.pair !== "XAUUSD") return false;
  // The target distance is planned upside/downside, never realized pips.
  const farthest = Math.max(0, ...[signal.tp1, signal.tp2, signal.tp3].map((target) =>
    target ? goldTargetMetrics(signal.direction, signal.entry, signal.sl, target)?.pips ?? 0 : 0));
  return farthest > 0 && farthest >= range.min && farthest <= range.max;
}
