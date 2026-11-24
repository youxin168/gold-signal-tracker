import type { GoldStrategyCard } from "@/lib/gold-board";
import type { PublicSignal, SignalStatus, Tp3WatchState } from "@/lib/public-snapshot";

export const STATUS: Record<SignalStatus, string> = {
  PENDING: "Waiting for entry", ACTIVE: "Active", TP1: "Target 1 hit", TP2: "Target 2 hit",
  TP2_OPEN: "Target 2 hit · still open", TP3: "Target 3 hit",
  SL: "Stop-loss hit", BE: "Breakeven stop hit", EXPIRED: "Expired",
};

export const STATE_LABEL: Record<GoldStrategyCard["state"], string> = {
  signal: "Signal", waiting: "Waiting", warming: "Warming up", unconfirmed: "Unconfirmed", paused: "Paused", offline: "Offline",
};

export const TP3_LABEL = "None";
export const TP3_NOTE = "None means no TP3 was suggested for that signal. New TP3 watches don’t change the TP1/TP2 result.";
export const TP3_WATCH_LABEL: Record<Tp3WatchState, string> = {
  WATCHING: "Watching", HIT: "Hit", STOPPED: "Not hit · stopped", EXPIRED: "Not filled", UNRESOLVED: "Unconfirmed",
};

export function goldSignalStatus(signal: PublicSignal) {
  return signal.status === "TP2" && signal.tp3_watch?.state === "WATCHING"
    ? "TP2 hit · watching TP3" : STATUS[signal.status];
}

/** Preserve known checkpoints without presenting a missing outcome as current. */
export function publishedSignalState(signal: PublicSignal, nowMs?: number) {
  const entryWindowEnded = signal.status === "PENDING" && nowMs !== undefined
    && Date.parse(signal.expires_at_utc) <= nowMs;
  const reason = signal.unresolved_reason === "MISSING_M1" ? "Missing M1 candles"
    : signal.unresolved_reason === "FOLD_CUTOFF" ? "Unresolved at fold cutoff" : signal.unresolved_reason;
  if (reason || entryWindowEnded) return {
    label: "Unconfirmed",
    detail: [STATUS[signal.status], reason || "Entry window ended; no outcome confirmed"].join(" · "),
    unconfirmed: true,
  };
  return { label: goldSignalStatus(signal), detail: null, unconfirmed: false };
}
