import { strict as assert } from "node:assert";
import { test } from "node:test";
import { fmtAge, hitLevels } from "../src/lib/format.ts";
import { publishedSignalState } from "../src/lib/gold-labels.ts";

const issued = "2026-11-19T08:50:05.679387+00:00";
const start = Date.parse(issued);

test("published views distinguish missing evidence from the recorded checkpoint", () => {
  assert.deepEqual(publishedSignalState({ status: "ACTIVE", unresolved_reason: "MISSING_M1" }), {
    label: "Unconfirmed", detail: "Active · Missing M1 candles", unconfirmed: true,
  });
  assert.equal(publishedSignalState({ status: "TP1", unresolved_reason: "FOLD_CUTOFF" }).detail, "Target 1 hit · Unresolved at fold cutoff");
  assert.equal(publishedSignalState({ status: "TP2", tp3_watch: { state: "WATCHING" } }).label, "TP2 hit · watching TP3");
});

test("a pending record after its entry deadline is not a confirmed expiry", () => {
  const pending = { status: "PENDING", expires_at_utc: issued };
  assert.equal(publishedSignalState(pending, start - 1).label, "Waiting for entry");
  assert.equal(publishedSignalState(pending, start).label, "Unconfirmed");
  assert.equal(publishedSignalState({ ...pending, status: "EXPIRED" }, start).label, "Expired");
});

test("signal age changes only after elapsed minutes from publication", () => {
  assert.equal(fmtAge(issued, start), "just now");
  assert.equal(fmtAge(issued, start + 59_999), "just now");
  assert.equal(fmtAge(issued, start + 60_000), "1 min ago");
  assert.equal(fmtAge(issued, start + 7 * 60_000), "7 min ago");
  assert.equal(fmtAge(issued, start + 65 * 60_000), "1 hr 5 min ago");
  assert.equal(fmtAge(issued, start + 48 * 60 * 60_000), "2 days ago");
  assert.equal(fmtAge(issued, start - 200), null);
  assert.equal(fmtAge("not a timestamp", start), null);
});

test("an optional TP3 colors only a confirmed watch without replacing the official result", () => {
  for (const state of ["WATCHING", "STOPPED", "EXPIRED", "UNRESOLVED"]) {
    assert.deepEqual(hitLevels("TP2", null, state), { sl: false, tp1: true, tp2: true, tp3: false });
  }
  assert.deepEqual(hitLevels("TP2", null, "HIT"), { sl: false, tp1: true, tp2: true, tp3: true });
});

test("fills reflect confirmed target and stop states only", () => {
  assert.deepEqual(hitLevels("TP1"), { sl: false, tp1: true, tp2: false, tp3: false });
  assert.deepEqual(hitLevels("TP2"), { sl: false, tp1: true, tp2: true, tp3: false });
  assert.deepEqual(hitLevels("TP2_OPEN"), hitLevels("TP2"));
  assert.deepEqual(hitLevels("TP3"), { sl: false, tp1: true, tp2: true, tp3: true });
  assert.deepEqual(hitLevels("SL"), { sl: true, tp1: false, tp2: false, tp3: false });
  assert.deepEqual(hitLevels("BE"), { sl: false, tp1: true, tp2: false, tp3: false });
  assert.deepEqual(hitLevels("BE", issued), hitLevels("TP2"));
  for (const status of ["PENDING", "ACTIVE", "EXPIRED"]) {
    assert.deepEqual(hitLevels(status), { sl: false, tp1: false, tp2: false, tp3: false });
  }
});
