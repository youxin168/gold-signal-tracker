import assert from "node:assert/strict";
import { test } from "node:test";
import { compareGoldDays, filterGoldCards, getGoldDashboard, getGoldOpenSignals, getGoldSheetRows } from "../src/lib/gold-board.ts";
import { matchesGoldTargetRange, parseTargetRange } from "../src/lib/gold-targets.ts";

const FEED = "BIQUOTE_XAUUSD_MID";
const codes = ["CLD-SCA-01-v2", "CLD-SCA-02-v2", "CLD-INT-01-v2", "CLD-INT-02-v2", "CLD-SWG-01-v2", "CLD-SWG-02-v2"];
const NOW = Date.parse("2026-11-19T09:15:00Z");
const strategies = codes.map((strategy_code) => ({ strategy_code, source: "CLD", style: strategy_code.split("-")[1], live_feed: FEED }));
const row = (strategy_code, fields = {}) => ({
  signal_id: fields.signal_id ?? `${strategy_code}-${fields.direction ?? "BUY"}`, strategy_code,
  source: "CLD", pair: "XAUUSD", data_source: FEED, direction: "BUY",
  status: "PENDING", issued_at_utc: "2026-11-19T09:05:00Z", expires_at_utc: "2026-11-19T09:35:00Z",
  closed_at: null, result_r: null, ...fields,
});
const makeSnapshot = (signals = [], runner = {}) => ({
  runner: { state: "ready", data_source: FEED, updated_at_utc: "2026-11-19T09:12:00Z", ...runner },
  strategies: [...strategies,
    { ...strategies[0], strategy_code: "CLD-SCA-01-v1", live_feed: "OANDA_PRACTICE_BID" },
    { ...strategies[0], strategy_code: "OWN-SCA-01-v1", source: "OWN" },
  ],
  cohorts: [
    { mode: "LIVE", signals },
    { mode: "REPLAY", signals: [row(codes[3], { status: "ACTIVE" })] },
    { mode: "BACKTEST", signals: [row(codes[3], { status: "TP2", closed_at: "2026-11-19T09:08:00Z", result_r: "2" })] },
  ],
});

test("the open list shows every published pending or filled gold signal, with recent entries first", () => {
  const pending = row(codes[0], { signal_id: "pending" });
  const active = row(codes[0], { signal_id: "filled", direction: "SELL", status: "ACTIVE", issued_at_utc: "2026-11-19T09:10:00Z" });
  const partial = row(codes[1], { signal_id: "partial", status: "TP1" });
  const snapshot = makeSnapshot([
    pending, active, partial, active,
    row(codes[2], { status: "SL", closed_at: "2026-11-19T09:12:00Z" }),
    row(codes[2], { signal_id: "future", issued_at_utc: "2026-11-19T09:16:00Z" }),
    row(codes[3], { status: "EXPIRED" }),
    row(codes[4], { status: "ACTIVE", data_source: "OANDA_PRACTICE_BID" }),
    row(codes[5], { status: "ACTIVE", pair: "EURUSD" }),
  ]);
  assert.deepEqual(getGoldOpenSignals(snapshot, NOW).map(({ signal, state, statusLabel }) => [signal.signal_id, state, statusLabel]), [
    ["filled", "active", "Entry filled"],
    ["pending", "pending", "Waiting for entry"],
    ["partial", "active", "TP1 hit · still open"],
  ]);
});

test("missing data or a passed entry window cannot count as currently pending or active", () => {
  const snapshot = makeSnapshot([
    row(codes[0], { signal_id: "past-due", expires_at_utc: "2026-11-19T09:15:00Z" }),
    row(codes[1], { signal_id: "missing", status: "ACTIVE", unresolved_reason: "MISSING_M1" }),
    row(codes[2], { signal_id: "fresh", status: "TP2_OPEN" }),
  ]);
  assert.deepEqual(getGoldOpenSignals(snapshot, NOW).map(({ state }) => state), ["unconfirmed", "unconfirmed", "active"]);
  assert.equal(getGoldOpenSignals(snapshot, NOW)[0].statusLabel, "Entry window ended · result unconfirmed");
  assert.ok(getGoldOpenSignals(snapshot, NOW, true).every(({ state }) => state === "unconfirmed"));
  assert.ok(getGoldOpenSignals(snapshot, NOW + 60 * 60_000).every(({ state }) => state === "unconfirmed"));
});

test("follow-on tracking stays active only while a TP3 watch or fixed-SL test is open", () => {
  const closed_at = "2026-11-19T09:08:00Z";
  const snapshot = makeSnapshot([
    row(codes[0], { signal_id: "watching", status: "TP2", closed_at, tp3_watch: { state: "WATCHING" } }),
    row(codes[1], { signal_id: "fixed-open", status: "BE", closed_at, parallel_targets: { phase: "ACTIVE" } }),
    row(codes[2], { signal_id: "fixed-gap", status: "BE", closed_at, parallel_targets: { phase: "ACTIVE", unresolved_reason: "MISSING_M1" } }),
    row(codes[3], { signal_id: "done", status: "TP2", closed_at, tp3_watch: { state: "STOPPED" }, parallel_targets: { phase: "CLOSED" } }),
  ]);
  assert.deepEqual(getGoldOpenSignals(snapshot, NOW).map(({ signal, state, statusLabel }) => [signal.signal_id, state, statusLabel]), [
    ["watching", "active", "TP2 hit · watching TP3"],
    ["fixed-open", "active", "Fixed-SL test orders still open"],
  ]);
});

test("shows all six on the current feed, including waiting, warming, paused, and unresolved", () => {
  const snapshot = makeSnapshot([
    row(codes[0]), row(codes[0], { direction: "SELL", status: "TP1" }),
    row(codes[1], { status: "ACTIVE", unresolved_reason: "Missing candles" }),
    row(codes[4], { data_source: "OANDA_PRACTICE_BID" }),
  ], {
    enabled_strategy_codes: codes.slice(0, 5),
    strategy_warmup: { [codes[2]]: { have: 170, need: 200 } },
  });
  const { cards } = getGoldDashboard(snapshot, NOW);
  assert.equal(cards.length, 6);
  assert.deepEqual(cards.map((card) => card.state), ["signal", "unconfirmed", "warming", "waiting", "waiting", "paused"]);
  assert.equal(cards[0].signals.length, 2);
  assert.equal(cards[1].signals.length, 0);
  assert.deepEqual(cards[2].warmup, { have: 170, need: 200 });
  assert.equal(getGoldDashboard(snapshot, NOW + 90 * 60_000).cards.filter((card) => card.signals.length).length, 0);
});

test("individual and side filters affect visibility, not another direction or original records", () => {
  const snapshot = makeSnapshot([row(codes[0]), row(codes[0], { direction: "SELL" }), row(codes[1], { direction: "SELL" })]);
  const { cards } = getGoldDashboard(snapshot, NOW);
  const visible = filterGoldCards(cards, { direction: "SELL", hideWaiting: false, hidden: [codes[1]] });
  assert.equal(visible.length, 1);
  assert.equal(visible[0].strategy.strategy_code, codes[0]);
  assert.deepEqual(visible[0].signals.map((row) => row.direction), ["SELL"]);
  assert.equal(cards[0].signals.length, 2);
  assert.equal(filterGoldCards(cards, { direction: "all", hidden: [], hideWaiting: true }).length, 2);
});

test("style preserves waiting rows, while distance and side select individual live signals", () => {
  const smaller = row(codes[4], { entry: "3000", sl: "2997", tp1: "3003", tp2: "3009" });
  const larger = row(codes[4], { direction: "SELL", entry: "3000", sl: "3008", tp1: "2992", tp2: "2984", tp3: "2970" });
  const scalp = row(codes[0], { entry: "3000", sl: "2990", tp1: "3010", tp2: "3030" });
  const snap = makeSnapshot([smaller, larger, scalp]);
  const { cards } = getGoldDashboard(snap, NOW);
  const filters = { style: "SWG", hidden: [], hideWaiting: false, direction: "all" };
  assert.deepEqual(filterGoldCards(cards, filters).map((c) => c.strategy.strategy_code), codes.slice(4));
  assert.deepEqual(filterGoldCards(cards, { ...filters, range: parseTargetRange("", "900") }).flatMap((c) => c.signals), [smaller]);
  const range = parseTargetRange("3000", "");
  assert.deepEqual(filterGoldCards(cards, { ...filters, direction: "SELL", range }).flatMap((c) => c.signals), [larger]);
  assert.deepEqual(filterGoldCards(cards, { ...filters, direction: "BUY", range }), []);
  assert.equal(compareGoldDays(snap, NOW, cards.slice(4), { direction: "SELL", range }).rows[0].today.issued, 1);
});

test("target distance has inclusive bounds and rejects invalid values or non-gold signals", () => {
  const signal = row(codes[0], { entry: "3000", sl: "2997", tp1: "3003", tp2: "3009", tp3: null });
  assert.equal(matchesGoldTargetRange(signal, parseTargetRange("900", "900")), true);
  assert.equal(matchesGoldTargetRange({ ...signal, pair: "EURUSD" }, parseTargetRange("1", "")), false);
  assert.equal(matchesGoldTargetRange({ ...signal, tp2: "2980" }, parseTargetRange("900", "")), false);
  for (const [min, max] of [["15", "10"], ["-1", ""], ["", "0.5"], ["", "Infinity"]]) {
    assert.equal(parseTargetRange(min, max).invalid, true);
    assert.equal(matchesGoldTargetRange(signal, parseTargetRange(min, max)), false);
  }
});

test("the curated Signal Tracker experiment appears under Swing without exposing unmarked OWN signals", () => {
  const code = "OWN-SWG-01-v1";
  const snapshot = makeSnapshot([
    row(code, { source: "OWN", status: "ACTIVE" }),
    row("OWN-SCA-01-v1", { source: "OWN", status: "ACTIVE" }),
    row(code, { source: "OWN", status: "ACTIVE", data_source: "OANDA_PRACTICE_BID" }),
  ]);
  snapshot.strategies.push({ strategy_code: code, source: "OWN", style: "SWG", live_feed: FEED, site_test: true });
  const { cards } = getGoldDashboard(snapshot, NOW);
  assert.equal(cards.length, 7);
  assert.equal(cards.at(-1).strategy.strategy_code, code);
  assert.equal(cards.at(-1).signals.length, 1);
  assert.equal(cards.at(-1).signals[0].data_source, FEED);
  assert.equal(compareGoldDays(snapshot, NOW, cards).rows.at(-1).today.issued, 1);
});

test("the old TP3 pilot stays out of the board while TP3 follows the regular strategy after TP2", () => {
  const retired = "CLD-SCA-02-v3";
  const signal = row(codes[1], { status: "TP2", result_r: "1.4", closed_at: "2026-11-19T09:06:00Z",
    tp3: "3775", tp3_watch: { price: "3775", state: "WATCHING" } });
  const archived = row(retired, { status: "ACTIVE" });
  const snapshot = makeSnapshot([signal, archived]);
  snapshot.strategies.push({ ...strategies[1], strategy_code: retired, retired_live: true });
  const { cards } = getGoldDashboard(snapshot, NOW);
  assert.equal(cards.length, 6);
  assert.deepEqual(cards.find((c) => c.strategy.strategy_code === codes[1]).signals, [signal]);
  assert.equal(compareGoldDays(snapshot, NOW, cards).rows[1].today.totalR, 1.4);
  assert.equal(snapshot.cohorts[0].signals.includes(archived), true);
});

test("sheet shows each open signal and one waiting row per remaining strategy", () => {
  const snapshot = makeSnapshot([
    row(codes[0]), row(codes[0], { direction: "SELL", status: "ACTIVE" }),
    row(codes[1], { status: "TP2", closed_at: "2026-11-19T09:10:00Z", result_r: "1.5" }),
    row(codes[2], { status: "ACTIVE", unresolved_reason: "Missing data" }),
  ]);
  const { cards } = getGoldDashboard(snapshot, NOW);
  const current = getGoldSheetRows(cards, false);
  assert.equal(current.length, 7);
  assert.deepEqual(current.slice(0, 2).map((row) => row.signal.direction), ["BUY", "SELL"]);
  assert.equal(current[1].firstForStrategy, false);
  assert.equal(current[2].signal, undefined);
  const withPrevious = getGoldSheetRows(cards, true);
  assert.equal(withPrevious[2].previous, true);
  assert.equal(withPrevious[2].signal.status, "TP2");
  assert.equal(withPrevious[3].signal, undefined);
});

test("a partial TP2 remains current and a confirmed TP3 counts as a completed result", () => {
  const snapshot = makeSnapshot([
    row(codes[0], { status: "TP2_OPEN", tp3: "2006" }),
    row(codes[1], { status: "TP3", tp3: "2006", closed_at: "2026-11-19T09:13:00Z", result_r: "1.70" }),
  ]);
  const { cards } = getGoldDashboard(snapshot, NOW);
  assert.equal(cards[0].signals[0].status, "TP2_OPEN");
  assert.equal(cards[1].signals.length, 0);
  assert.equal(getGoldSheetRows(cards, true)[1].signal.status, "TP3");
  assert.equal(compareGoldDays(snapshot, NOW, cards).rows[1].today.totalR, 1.7);
});

test("Cambodia day comparison uses equal elapsed time and counts R by closure, not issue date", () => {
  const snapshot = makeSnapshot([
    row(codes[0], { status: "SL", issued_at_utc: "2026-11-17T17:00:00Z", closed_at: "2026-11-18T08:00:00Z", result_r: "-1.20" }),
    row(codes[0], { status: "TP2", issued_at_utc: "2026-11-18T11:00:00Z", closed_at: "2026-11-18T17:00:00Z", result_r: "2.50" }),
    row(codes[0], { status: "TP1", issued_at_utc: "2026-11-19T09:00:00Z" }),
    row(codes[0], { status: "EXPIRED", issued_at_utc: "2026-11-18T08:00:00Z", closed_at: "2026-11-18T09:15:00Z" }),
    row(codes[0], { status: "SL", issued_at_utc: "2026-11-19T09:20:00Z", closed_at: "2026-11-19T09:25:00Z", result_r: "-2" }),
  ]);
  const { cards } = getGoldDashboard(snapshot, NOW);
  const comparison = compareGoldDays(snapshot, NOW, cards);
  assert.equal(comparison.todayLabel, "19 Nov");
  assert.equal(comparison.yesterdayLabel, "18 Nov");
  assert.deepEqual(comparison.rows[0].today, { issued: 1, closed: 1, totalR: 2.5 });
  assert.deepEqual(comparison.rows[0].yesterday, { issued: 2, closed: 1, totalR: -1.2 });
  assert.equal(comparison.rows.length, 6);
  assert.deepEqual(comparison.rows[1].yesterday, { issued: 0, closed: 0, totalR: null });
});
