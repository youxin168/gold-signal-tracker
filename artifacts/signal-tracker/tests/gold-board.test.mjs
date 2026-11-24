import { strict as assert } from "node:assert";
import { test } from "node:test";
import { getGoldBoard, goldTargetMetrics } from "../src/lib/gold-board.ts";

const now = Date.parse("2024-07-03T12:10:00Z");
const sample = (signal_id, fields = {}) => ({
  signal_id,
  source: "CLD",
  pair: "XAUUSD",
  issued_at_utc: "2024-07-03T12:00:00Z",
  expires_at_utc: "2024-07-03T12:15:00Z",
  status: "PENDING",
  ...fields,
});
const data = (signals, state = "ready", updated_at_utc = "2024-07-03T12:08:00Z") => ({
  runner: { state, updated_at_utc },
  strategies: [],
  cohorts: [
    { mode: "BACKTEST", signals: [sample("historical")] },
    { mode: "REPLAY", signals: [sample("replay")] },
    { mode: "LIVE", signals },
  ],
});

test("only built-in XAUUSD live records can appear on the board", () => {
  const result = getGoldBoard(data([sample("external", { source: "EXT1" }), sample("other-pair", { pair: "EURUSD" })]), now);
  assert.equal(result.signal, undefined);
});

test("the newest ongoing signal takes priority over a newer closed record", () => {
  const active = sample("active", { status: "TP1" });
  const closed = sample("closed", { status: "SL", issued_at_utc: "2024-07-03T12:05:00Z" });
  const previous = sample("previous", { status: "ACTIVE", issued_at_utc: "2024-07-03T11:55:00Z" });
  const result = getGoldBoard(data([previous, closed, active]), now);
  assert.equal(result.signal, active);
  assert.equal(result.isCurrent, true);
});

test("a stale or disconnected scanner cannot claim an old signal is current", () => {
  for (const [state, stamp] of [["ready", "2024-07-03T11:00:00Z"], ["error", "2024-07-03T12:08:00Z"],
    ["disabled", null], ["not_configured", null]]) {
    const active = sample("last", { status: "ACTIVE" });
    const result = getGoldBoard(data([active], state, stamp), now);
    assert.equal(result.signal, active);
    assert.equal(result.isCurrent, false);
    assert.equal(result.fresh, false);
  }
});

test("a missed entry deadline is not shown as a confirmed expiry", () => {
  const pending = sample("unconfirmed", { expires_at_utc: "2024-07-03T12:10:00Z" });
  const result = getGoldBoard(data([pending]), now);
  assert.equal(result.entryWindowPassed, true);
  assert.equal(result.isCurrent, false);
  assert.equal(result.signal.status, "PENDING");
});

test("missing candles never present a recorded fill as confirmed current", () => {
  const active = sample("last", { status: "ACTIVE", unresolved_reason: "Missing candle" });
  const result = getGoldBoard(data([active]), now);
  assert.equal(result.signal, active);
  assert.equal(result.isCurrent, false);
});

test("gold target metrics give planned reward, USD per ounce and pips in the trade direction", () => {
  const result = { rewardRatio: 2, moveUsd: 100, pips: 10_000 };
  assert.deepEqual(goldTargetMetrics("BUY", "3000", "2950", "3100"), result);
  assert.deepEqual(goldTargetMetrics("SELL", "3000", "3050", "2900"), result);
  assert.deepEqual(goldTargetMetrics("BUY", "3000.02", "3000.01", "3000.03"), { rewardRatio: 1, moveUsd: 0.01, pips: 1 });
});

test("target metrics reject a missing price, zero risk, or reversed stop or target", () => {
  assert.equal(goldTargetMetrics("BUY", "", "2950", "3100"), null);
  assert.equal(goldTargetMetrics("BUY", "3000", "3000", "3100"), null);
  assert.equal(goldTargetMetrics("BUY", "3000", "3050", "3100"), null);
  assert.equal(goldTargetMetrics("SELL", "3000", "3050", "3100"), null);
});
