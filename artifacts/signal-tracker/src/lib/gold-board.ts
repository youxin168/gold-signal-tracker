import type { PublicSignal, Snapshot, Strategy, Style } from "@/lib/public-snapshot";
import { matchesGoldTargetRange, type TargetRange } from "./gold-targets.ts";

export { goldTargetMetrics } from "./gold-targets.ts";

// Pages publishes about every 15 minutes. Allow for delays, but don't present
// an old journal entry as current when the scheduler has stopped updating it.
const MAX_CHECK_AGE_MS = 45 * 60 * 1000;
const isCuratedStrategy = (strategy: Strategy) => strategy.source === "CLD" || (strategy.source === "OWN" && strategy.site_test === true);

function hasFreshScan(snapshot: Snapshot, nowMs: number) {
  const lastCheck = snapshot.runner.updated_at_utc;
  const age = lastCheck ? nowMs - Date.parse(lastCheck) : Infinity;
  const state = snapshot.runner.state;
  return (state === "ready" || state === "waiting") && age >= 0 && age <= MAX_CHECK_AGE_MS;
}

function journalSignals(snapshot: Snapshot, feed = snapshot.runner.data_source) {
  const retired = new Set(snapshot.strategies.filter((strategy) => strategy.retired_live).map((strategy) => strategy.strategy_code));
  const ownTests = new Set(snapshot.strategies.filter((strategy) => strategy.source === "OWN" && strategy.site_test === true)
    .map((strategy) => strategy.strategy_code));
  return snapshot.cohorts
    .filter((cohort) => cohort.mode === "LIVE")
    .flatMap((cohort) => cohort.signals)
    .filter((signal) => !retired.has(signal.strategy_code) && signal.pair === "XAUUSD" && (!feed || signal.data_source === feed)
      && (signal.source === "CLD" || (signal.source === "OWN" && ownTests.has(signal.strategy_code))))
    .sort((a, b) => Date.parse(b.issued_at_utc) - Date.parse(a.issued_at_utc));
}

function isOngoing(signal: PublicSignal, nowMs: number) {
  return !signal.unresolved_reason && (signal.status === "ACTIVE" || signal.status === "TP1" || signal.status === "TP2_OPEN"
    || (signal.status === "PENDING" && Date.parse(signal.expires_at_utc) > nowMs));
}

export function getGoldBoard(snapshot: Snapshot, nowMs: number) {
  const fresh = hasFreshScan(snapshot, nowMs);
  const signals = journalSignals(snapshot);
  const ongoing = fresh ? signals.find((signal) => isOngoing(signal, nowMs)) : undefined;
  const signal = ongoing ?? signals[0];
  const entryWindowPassed = signal?.status === "PENDING" && Date.parse(signal.expires_at_utc) <= nowMs;
  return { signal, isCurrent: ongoing !== undefined, entryWindowPassed, fresh };
}

const DEFAULT_FEED = "OANDA_PRACTICE_BID";
const STYLE_ORDER = { SCA: 0, INT: 1, SWG: 2 };
const UNSETTLED = new Set(["PENDING", "ACTIVE", "TP1", "TP2_OPEN"]);
const COMPLETED = new Set(["TP2", "TP3", "SL", "BE"]);

export type GoldStrategyCard = {
  strategy: Strategy;
  state: "signal" | "waiting" | "warming" | "unconfirmed" | "paused" | "offline";
  signals: PublicSignal[];
  latest?: PublicSignal;
  warmup?: { have: number; need: number };
};

export type GoldOpenSignal = {
  strategy: Strategy;
  signal: PublicSignal;
  state: "pending" | "active" | "unconfirmed";
  statusLabel: string;
};

function classifyOpenSignal(signal: PublicSignal, nowMs: number, fresh: boolean): Pick<GoldOpenSignal, "state" | "statusLabel"> | undefined {
  const pending = signal.status === "PENDING";
  const active = !signal.closed_at && (signal.status === "ACTIVE" || signal.status === "TP1" || signal.status === "TP2_OPEN");
  const watchingTp3 = signal.status === "TP2" && signal.tp3_watch?.state === "WATCHING" && !signal.tp3_watch.unresolved_reason;
  const fixedOpen = signal.status !== "EXPIRED" && signal.parallel_targets?.phase === "ACTIVE" && !signal.parallel_targets.unresolved_reason;
  if (!pending && !active && !watchingTp3 && !fixedOpen) return;
  if (pending && !(Date.parse(signal.expires_at_utc) > nowMs)) {
    return { state: "unconfirmed", statusLabel: "Entry window ended · result unconfirmed" };
  }
  if (!fresh || signal.unresolved_reason) {
    return { state: "unconfirmed", statusLabel: pending ? "Entry status unconfirmed" : "Current status unconfirmed" };
  }
  if (pending) return { state: "pending", statusLabel: "Waiting for entry" };
  const statusLabel = signal.status === "TP1" && active ? "TP1 hit · still open"
    : signal.status === "TP2_OPEN" && active ? "TP2 hit · still open"
      : active ? "Entry filled"
        : watchingTp3 ? "TP2 hit · watching TP3" : "Fixed-SL test orders still open";
  return { state: "active", statusLabel };
}

/** One row per published signal, independent of watchlist display filters. */
export function getGoldOpenSignals(snapshot: Snapshot, nowMs: number, refreshFailed = false): GoldOpenSignal[] {
  const feed = snapshot.runner.data_source ?? DEFAULT_FEED;
  const fresh = !refreshFailed && hasFreshScan(snapshot, nowMs);
  const strategies = new Map(snapshot.strategies.filter((strategy) =>
    !strategy.retired_live && isCuratedStrategy(strategy) && (strategy.live_feed ?? DEFAULT_FEED) === feed,
  ).map((strategy) => [strategy.strategy_code, strategy]));
  const seen = new Set<string>();
  return journalSignals(snapshot, feed).flatMap((signal) => {
    const strategy = strategies.get(signal.strategy_code);
    const publishedAt = Date.parse(signal.issued_at_utc);
    if (!strategy || seen.has(signal.signal_id) || !(publishedAt <= nowMs)) return [];
    seen.add(signal.signal_id);
    const status = classifyOpenSignal(signal, nowMs, fresh);
    return status ? [{ strategy, signal, ...status }] : [];
  });
}

export function getGoldDashboard(snapshot: Snapshot, nowMs: number) {
  const feed = snapshot.runner.data_source ?? DEFAULT_FEED;
  const fresh = hasFreshScan(snapshot, nowMs);
  const groups = new Map<string, PublicSignal[]>();
  for (const signal of journalSignals(snapshot, feed)) {
    const group = groups.get(signal.strategy_code);
    if (group) group.push(signal);
    else groups.set(signal.strategy_code, [signal]);
  }
  const strategies = snapshot.strategies
    .filter((strategy) => !strategy.retired_live && isCuratedStrategy(strategy) && (strategy.live_feed ?? DEFAULT_FEED) === feed)
    .sort((a, b) => STYLE_ORDER[a.style] - STYLE_ORDER[b.style] || a.strategy_code.localeCompare(b.strategy_code));
  const cards = strategies.map((strategy): GoldStrategyCard => {
    const code = strategy.strategy_code;
    const records = groups.get(code) ?? [];
    const latest = records[0];
    const signals = fresh ? records.filter((signal) => isOngoing(signal, nowMs)
      || (signal.status === "TP2" && signal.tp3_watch?.state === "WATCHING")
      || (signal.parallel_targets?.phase === "ACTIVE" && !signal.parallel_targets.unresolved_reason)) : [];
    const warmup = snapshot.runner.strategy_warmup?.[code];
    const paused = snapshot.runner.state === "disabled"
      || snapshot.runner.enabled_strategy_codes?.includes(code) === false;
    if (signals.length) return { strategy, state: "signal", signals, latest };
    if (paused) return { strategy, state: "paused", signals, latest };
    // An unconfirmed entry or exit is not the same as no setup.
    if (records.some((signal) => UNSETTLED.has(signal.status))) {
      return { strategy, state: "unconfirmed", signals, latest: records.find((signal) => UNSETTLED.has(signal.status)) };
    }
    if (!fresh) return { strategy, state: "offline", signals, latest };
    if (warmup && warmup.have < warmup.need) return { strategy, state: "warming", signals, latest, warmup };
    return { strategy, state: "waiting", signals, latest };
  });
  return { cards, fresh };
}

export type GoldCardFilters = {
  direction: "all" | "BUY" | "SELL";
  style?: Style | "";
  range?: TargetRange;
  hideWaiting: boolean;
  hidden: string[];
};

function matchesGoldSignal(signal: PublicSignal, filters?: Pick<GoldCardFilters, "direction" | "range">) {
  return (!filters || filters.direction === "all" || signal.direction === filters.direction)
    && matchesGoldTargetRange(signal, filters?.range);
}

export function filterGoldCards(cards: GoldStrategyCard[], filters: GoldCardFilters): GoldStrategyCard[] {
  const hidden = new Set(filters.hidden);
  return cards.flatMap((card) => {
    if (hidden.has(card.strategy.strategy_code) || (filters.style && card.strategy.style !== filters.style)) return [];
    if (filters.direction !== "all" || filters.range?.active) {
      const signals = card.signals.filter((signal) => matchesGoldSignal(signal, filters));
      return signals.length ? [{ ...card, signals }] : [];
    }
    if (filters.hideWaiting && card.signals.length === 0) return [];
    return [card];
  });
}

export type GoldSheetRow = {
  card: GoldStrategyCard;
  signal?: PublicSignal;
  previous: boolean;
  firstForStrategy: boolean;
};

export function getGoldSheetRows(cards: GoldStrategyCard[], showPrevious: boolean): GoldSheetRow[] {
  return cards.flatMap<GoldSheetRow>((card) => {
    if (card.signals.length) {
      return card.signals.map((signal, index) => ({ card, signal, previous: false, firstForStrategy: index === 0 }));
    }
    const previous = showPrevious && card.latest?.closed_at && !card.latest.unresolved_reason
      && COMPLETED.has(card.latest.status) ? card.latest : undefined;
    return [{ card, signal: previous, previous: Boolean(previous), firstForStrategy: true }];
  });
}

export type GoldDayStats = { issued: number; closed: number; totalR: number | null };
const DAY_MS = 24 * 60 * 60 * 1000;
// Phnom Penh is UTC+7 year-round; translate local midnight to its UTC instant.
const CAMBODIA_OFFSET = 7 * 60 * 60 * 1000;
const dayLabel = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "Asia/Phnom_Penh" });

export function compareGoldDays(snapshot: Snapshot, nowMs: number, cards: GoldStrategyCard[],
  filters?: Pick<GoldCardFilters, "direction" | "range">) {
  const todayStart = Math.floor((nowMs + CAMBODIA_OFFSET) / DAY_MS) * DAY_MS - CAMBODIA_OFFSET;
  const yesterdayStart = todayStart - DAY_MS;
  const groups = new Map<string, PublicSignal[]>();
  for (const signal of journalSignals(snapshot, snapshot.runner.data_source ?? DEFAULT_FEED)) {
    if (!matchesGoldSignal(signal, filters)) continue;
    const group = groups.get(signal.strategy_code);
    if (group) group.push(signal);
    else groups.set(signal.strategy_code, [signal]);
  }
  function count(records: PublicSignal[], start: number, end: number): GoldDayStats {
    const inRange = (stamp: string | null): boolean => {
      const time = stamp ? Date.parse(stamp) : NaN;
      return time >= start && time < end;
    };
    let issued = 0;
    let closed = 0;
    let total = 0;
    for (const signal of records) {
      if (inRange(signal.issued_at_utc)) issued++;
      if (!COMPLETED.has(signal.status) || signal.unresolved_reason || !inRange(signal.closed_at)) continue;
      if (signal.result_r === null || !signal.result_r.trim()) continue;
      const value = Number(signal.result_r);
      if (!Number.isFinite(value)) continue;
      total += value;
      closed++;
    }
    return { issued, closed, totalR: closed ? total : null };
  }
  return {
    todayLabel: dayLabel.format(todayStart),
    yesterdayLabel: dayLabel.format(yesterdayStart),
    rows: cards.map(({ strategy }) => {
      const records = groups.get(strategy.strategy_code) ?? [];
      return { strategy, today: count(records, todayStart, nowMs), yesterday: count(records, yesterdayStart, nowMs - DAY_MS) };
    }),
  };
}
