import assert from "node:assert/strict";
import { test } from "node:test";
import { cambodiaDate, cambodiaDateTime, filterHistory, summarizeHistory } from "../src/lib/history-results.ts";
import { parseTargetRange } from "../src/lib/gold-targets.ts";

const closed = (strategy_code, result_r, fields = {}) => ({
  strategy_code, result_r, status: "TP2", issued_at_utc: "2026-11-19T16:45:00Z",
  closed_at: "2026-11-19T17:00:00Z", ...fields,
});
const allBetween = (day) => ({ code: "", from: day, to: day });

test("date ranges are inclusive by Cambodia close date, falling back to issue date for open signals", () => {
  const nextDay = closed("one", "1");
  const priorDay = closed("one", "-1", { closed_at: "2026-11-19T16:59:59Z" });
  const open = closed("two", null, { status: "ACTIVE", closed_at: null });
  const signals = [nextDay, priorDay, open];
  assert.equal(cambodiaDate(Date.parse(nextDay.closed_at)), "2026-11-20");
  assert.equal(cambodiaDateTime(nextDay.closed_at), "2026-11-20 00:00");
  assert.deepEqual(filterHistory(signals, allBetween("2026-11-20")), [nextDay]);
  assert.deepEqual(filterHistory(signals, { ...allBetween("2026-11-19"), code: "two" }), [open]);
  assert.deepEqual(filterHistory(signals, { ...allBetween("2026-11-19"), from: "" }), [priorDay, open]);
  assert.deepEqual(filterHistory(signals, { ...allBetween("2026-11-20"), to: "" }), [nextDay]);
  assert.deepEqual(filterHistory(signals, { ...allBetween("2026-11-19"), from: "2026-11-20" }), []);
});

test("net R uses only confirmed closed results and skips the archived TP3 pilot in mixed totals", () => {
  const retired = closed("archived", "1.65", { status: "TP3" });
  const signals = [
    closed("sweep", "1.4"), closed("scalp", "-1.02", { status: "SL" }),
    closed("sweep", "0", { status: "BE" }), retired,
    closed("scalp", "5", { closed_at: null, status: "TP1" }),
    closed("scalp", "0", { status: "EXPIRED" }),
    closed("scalp", "-1", { unresolved_reason: "Missing candle" }),
    closed("scalp", "NaN"), closed("scalp", "  "),
  ];
  assert.deepEqual(summarizeHistory(signals, new Set(["archived"])), {
    netR: 0.38, gains: 1.4, losses: -1.02, closed: 3, wins: 1, losingTrades: 1, flat: 1, archived: 1,
  });
  const selected = filterHistory(signals, { ...allBetween("2026-11-20"), code: "archived" });
  assert.equal(summarizeHistory(selected, new Set()).netR, 1.65);
  assert.equal(summarizeHistory(filterHistory(signals, { ...allBetween("2026-11-20"), code: "scalp" }), new Set()).netR, -1.02);
  assert.equal(summarizeHistory(signals.slice(4), new Set()).netR, null);
});

test("a real flat result is zero, not the same as an empty selection", () => {
  const result = summarizeHistory([closed("one", "0.1"), closed("two", "-0.1")], new Set());
  assert.equal(result.netR, 0);
  assert.equal(result.closed, 2);
  assert.equal(summarizeHistory([], new Set()).netR, null);
});

test("style, target distance and date narrow the same records used by the result summary", () => {
  const fields = { pair: "XAUUSD", direction: "BUY", entry: "3000", sl: "2990", tp1: "3010", tp2: "3020" };
  const swing = closed("swing", "1.5", { ...fields, style: "SWG", tp3: "3040" });
  const nearbySwing = closed("swing", "-1", { ...fields, style: "SWG" });
  const scalp = closed("scalp", "2", { ...fields, style: "SCA", tp3: "3040" });
  const earlier = closed("swing", "2", { ...fields, style: "SWG", tp3: "3040", closed_at: "2026-11-19T16:55:00Z" });
  const matched = filterHistory([swing, nearbySwing, scalp, earlier], {
    ...allBetween("2026-11-20"), style: "SWG", range: parseTargetRange("3000", ""),
  });
  assert.deepEqual(matched, [swing]);
  assert.equal(summarizeHistory(matched, new Set()).netR, 1.5);
});
