import { useEffect, useState } from "react";
import { Check, Sheet, X } from "lucide-react";
import { TargetCell } from "@/components/gold-signal-sheet";
import { SiteTestBadge } from "@/components/site-test-badge";
import { PARALLEL_NOTE, ParallelTargetResult } from "@/components/parallel-target-result";
import { fmtR, fmtScalar, hitLevels, rTone } from "@/lib/format";
import { publishedSignalState, TP3_NOTE } from "@/lib/gold-labels";
import { cambodiaDateTime } from "@/lib/history-results";
import type { PublicSignal, Strategy } from "@/lib/public-snapshot";
import { cn } from "@/lib/utils";

const HEADERS = ["Strategy", "Side", "Status", "Entry", "Initial SL", "TP1", "TP2", "TP3", "Issued (ICT)", "Closed (ICT)", "Trade R", "Fixed-SL orders"];
const GRID = "border-b border-r border-[#dbe4de]";
const CELL = `${GRID} px-2.5 py-2 align-middle`;
const LEVEL = `${CELL} whitespace-nowrap text-right font-mono tabular-nums`;
const NUMBER = `${GRID} min-w-8 bg-[#f0f4f0] text-center font-mono text-[11px] text-[#516459]`;
const STEP = 200;

export function GoldHistorySheet({ signals, strategies }: { signals: PublicSignal[]; strategies: Strategy[] }) {
  const [limit, setLimit] = useState(STEP);
  useEffect(() => { setLimit(STEP); }, [signals]);
  const registry = new Map(strategies.map((s) => [s.strategy_code, s]));
  const rows = signals.slice(0, limit);
  return (
    <section className="desk-panel overflow-hidden rounded-xl border border-[#b9cbc0] bg-white text-[#182e23]" aria-label="Signal history worksheet">
      <div className="flex items-center justify-between gap-2 bg-[hsl(var(--ink))] px-3.5 py-3 text-white">
        <h2 className="flex items-center gap-2 text-sm font-semibold"><Sheet size={16} className="text-[hsl(var(--gold))]" aria-hidden="true" /> Signal history worksheet</h2>
        <span className="text-[11px] text-white/80" data-testid="text-history-worksheet-count">{rows.length} of {signals.length} records</span>
      </div>
      <div className="bg-[#f6f9f6] px-3.5 py-2 text-[11px] text-[#43554a] sm:hidden">Swipe to see prices, dates, and results.</div>
      <div className="overflow-x-auto focus-visible:outline-2 focus-visible:outline-inset focus-visible:outline-[#175339]"
        role="region" aria-label="Scrollable history table" tabIndex={0} data-testid="region-history-worksheet">
        <table className="w-full min-w-[1220px] border-separate border-spacing-0 text-xs">
          <caption className="sr-only">Signal history for the selected evidence scope, with take-profit and stop-loss hits.</caption>
          <thead>
            <tr aria-hidden="true" className="bg-[#f0f4f0] text-center font-mono text-[10px] text-[#516459]">
              <td className={cn(NUMBER, "py-1")} />
              {HEADERS.map((name, index) => <td key={name} className={cn(GRID, "py-1 last:border-r-0")}>{String.fromCharCode(65 + index)}</td>)}
            </tr>
            <tr className="whitespace-nowrap bg-[#e2efe7] text-left text-[11px] text-[#264536]">
              <th scope="col" className={NUMBER}><span className="sr-only">Row</span>#</th>
              {HEADERS.map((name, index) => <th scope="col" key={name} className={cn(GRID, "px-2.5 py-2 last:border-r-0",
                index === 0 && "sticky left-0 z-10 bg-[#e2efe7]", ((index >= 3 && index <= 7) || index === 10) && "text-right")}>{name}</th>)}
            </tr>
          </thead>
          <tbody>{rows.map((s, i) => {
            const hit = hitLevels(s.status, s.tp2_at, s.tp3_watch?.state);
            const bg = i % 2 ? "bg-[#f8faf8]" : "bg-white";
            const display = publishedSignalState(s);
            return (
              <tr key={s.signal_id} className={bg} data-testid={`row-history-${s.signal_id}`}>
                <td className={NUMBER}>{i + 1}</td>
                <th scope="row" className={cn(CELL, "sticky left-0 z-10 min-w-35 text-left font-semibold", bg)}>
                  {registry.get(s.strategy_code)?.name ?? s.strategy_code}
                  <span className="block whitespace-nowrap font-mono text-[10px] font-normal text-[#516459]">{s.strategy_code}</span>
                  {registry.get(s.strategy_code)?.site_test && <SiteTestBadge />}
                </th>
                <td className={CELL}>
                  <span className={cn("rounded-md px-1.5 py-0.5 text-[11px] font-semibold",
                    s.direction === "BUY" ? "bg-[#e6f3e9] text-[#205838]" : "bg-[#f8e9e5] text-[#8b392b]")}>{s.direction}</span>
                </td>
                <td className={CELL}>
                  <span className={cn("font-medium", display.unconfirmed && "rounded bg-accent px-1.5 py-0.5 text-accent-foreground")}>{display.label}</span>
                  {display.detail && <span className="mt-1 block text-[11px] text-[#516459]">{display.detail}</span>}
                </td>
                <td className={LEVEL}>{fmtScalar(s.entry)}</td>
                <td className={cn(LEVEL, hit.sl && "bg-[hsl(var(--loss))] text-white")}>
                  {hit.sl && <X size={12} className="mr-1 inline-block" aria-label="Hit" />}{fmtScalar(s.sl)}
                </td>
                <TargetCell signal={s} target="tp1" rowKey={s.signal_id} hit={hit.tp1} showMetrics={false} />
                <TargetCell signal={s} target="tp2" rowKey={s.signal_id} hit={hit.tp2} showMetrics={false} />
                <TargetCell signal={s} target="tp3" rowKey={s.signal_id} hit={hit.tp3} showMetrics={false} />
                {[s.issued_at_utc, s.closed_at].map((date, index) => (
                  <td className={cn(CELL, "whitespace-nowrap text-[#516459]")} key={index}>
                    {date ? <time dateTime={date}>{cambodiaDateTime(date)}</time> : "—"}
                  </td>
                ))}
                <td className={cn(LEVEL, "font-medium", rTone(s.result_r))}>{fmtR(s.result_r)}</td>
                <td className={cn(CELL, "min-w-44 border-r-0")}><ParallelTargetResult plan={s.parallel_targets} /></td>
              </tr>
            );
          })}</tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 bg-[#f6f9f6] px-3.5 py-2 text-[11px] text-[#43554a]">
        <p className="flex items-center gap-1"><Check size={12} aria-hidden="true" /> Colored price cells mark confirmed hits. {TP3_NOTE}</p>
        <p>{PARALLEL_NOTE} Older records were not recalculated.</p>
        {limit < signals.length && <button type="button" onClick={() => setLimit((n) => n + STEP)}
          className="rounded border border-[#b9cbc0] px-2 py-1 font-medium text-[#175339] hover:bg-[#e2efe7]" data-testid="button-history-show-more">Show more</button>}
      </div>
    </section>
  );
}
