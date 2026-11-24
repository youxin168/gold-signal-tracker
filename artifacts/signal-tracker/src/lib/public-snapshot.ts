/** Public, read-only JSON file exported by the same Python engine as the CLI. */
export type Mode = "LIVE" | "REPLAY" | "BACKTEST";
export type Style = "SCA" | "INT" | "SWG";
export type SignalStatus = "PENDING" | "ACTIVE" | "TP1" | "TP2" | "TP2_OPEN" | "TP3" | "SL" | "BE" | "EXPIRED";
export type Tp3WatchState = "WATCHING" | "HIT" | "STOPPED" | "EXPIRED" | "UNRESOLVED";
export type ParallelTargets = {
  phase: "PENDING" | "ACTIVE" | "CLOSED" | "EXPIRED";
  legs: { target: number; status: "OPEN" | "TP" | "SL" | "EXPIRED"; result_r: string | null }[];
  realized_r: string | null;
  per_total_risk_r: string | null;
  unresolved_reason: string | null;
};
export type PublicSignal = {
  signal_id: string; strategy_code: string; source: string; style: Style;
  pair: string; direction: "BUY" | "SELL"; entry: string; sl: string; tp1: string; tp2: string;
  tp3?: string | null; tp2_at?: string | null;
  tp3_watch?: { price: string; state: Tp3WatchState; hit_at: string | null; unresolved_reason: string | null };
  parallel_targets?: ParallelTargets;
  issued_at_utc: string; expires_at_utc: string; triggered_at: string | null;
  closed_at: string | null; status: SignalStatus; result_r: string | null; data_source: string;
  unresolved_reason?: string | null;
};
export type Strategy = {
  strategy_code: string; source: string; style: Style; name: string; version_state: string;
  experimental: boolean; entry_timeframe: string; trend_timeframe: string;
  rules: string[]; expiry_minutes: number; max_signals_per_day: number;
  target_multiples: string[]; notes: string[]; live_feed?: string;
  site_test?: boolean;
  retired_live?: boolean;
};
export type Scalar = number | string | null;
export type Metrics = {
  signals: number; filled: number; expired: number; fill_rate: Scalar; completed: number;
  entry_unresolved: number; filled_open: number; sample_size_badge: string;
  win_rate: Scalar; average_r: Scalar; expectancy_r: Scalar; profit_factor: Scalar;
  total_r: Scalar; max_drawdown_r: Scalar; longest_losing_streak: Scalar;
  profit_factor_status: string; win_rate_ci_95: [number, number] | null;
  expectancy_r_ci_95: [number, number] | null;
  equity_curve_r: { closed_at_utc: string; equity_r: string }[];
};
export type Score = { style: Style; metrics: Metrics; breakdowns: Record<string, Record<string, Metrics>> };
export type StrategyScore = Score & {
  strategy_code: string; name: string; version_state: string; rank: number | null;
  rank_reason: string | null; coverage: Record<string, number> | null;
  analyst: {
    summary: string; strengths: string[]; weaknesses: string[]; warnings: string[];
    best_session: { sessions: string[]; expectancy_r: Scalar } | null;
    worst_session: { sessions: string[]; expectancy_r: Scalar } | null;
  };
};
export type HeadToHead = {
  style: Style; claude_code: string; external_code: string;
  start_utc: string | null; end_utc_exclusive: string | null;
  claude_metrics: Metrics | null; external_metrics: Metrics | null;
  leader: string | null; explanation: string;
};
export type Cohort = {
  id: string; mode: Mode; label: string; data_source: string | null; fold: string | null;
  start_utc: string | null; end_utc_exclusive: string | null; note: string | null;
  signals: PublicSignal[]; strategies: StrategyScore[]; styles: Score[];
  comparisons?: HeadToHead[];
};
export type Snapshot = {
  schema_version: 1; generated_at_utc: string; pair: string; strategies: Strategy[]; cohorts: Cohort[];
  runner: {
    state: "not_configured" | "disabled" | "ready" | "waiting" | "error";
    updated_at_utc: string | null;
    message: string;
    data_source?: string;
    enabled_strategy_codes?: string[];
    strategy_warmup?: Record<string, { have: number; need: number }>;
  };
};

export async function getSnapshot(signal?: AbortSignal): Promise<Snapshot> {
  const response = await fetch(`${import.meta.env.BASE_URL}data/snapshot.json`, { signal, cache: "no-cache" });
  if (!response.ok) throw new Error("Could not load the published data snapshot.");
  const snapshot: Snapshot = await response.json();
  if (snapshot.schema_version !== 1 || !Array.isArray(snapshot.cohorts) || !Array.isArray(snapshot.strategies)) {
    throw new Error("The published data snapshot has an unsupported format.");
  }
  return snapshot;
}
