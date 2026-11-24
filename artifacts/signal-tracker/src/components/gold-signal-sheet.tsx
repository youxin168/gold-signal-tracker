import { useState } from "react";
import { Check, EyeOff, Sheet, X } from "lucide-react";
import { SiteTestBadge } from "@/components/site-test-badge";
import { PARALLEL_NOTE, ParallelTargetResult } from "@/components/parallel-target-result";
import { fmtAge, fmtDate, fmtR, fmtScalar, hitLevels, rTone, STYLE_NAMES } from "@/lib/format";
import { getGoldSheetRows, goldTargetMetrics, type GoldStrategyCard } from "@/lib/gold-board";
import { publishedSignalState, STATE_LABEL, TP3_LABEL, TP3_NOTE, TP3_WATCH_LABEL } from "@/lib/gold-labels";
import { cambodiaDateTime } from "@/lib/history-results";
import type { PublicSignal } from "@/lib/public-snapshot";
import { cn } from "@/lib/utils";

const HEADERS = ["Strategy", "Side", "Status", "Entry", "Initial SL", "TP1", "TP2", "TP3", "Published (ICT)", "Fixed-SL orders"] as const;
const EMPTY = "—";
const GRID = "border-b border-r border-[#dbe4de]";
const CELL = `${GRID} px-2.5 py-2.5 align-middle`;
const LEVEL = `${CELL} text-right font-mono tabular-nums whitespace-nowrap`;
const ROW_NUMBER = `${GRID} w-8 min-w-8 bg-[#f0f4f0] text-center font-mono text-[11px] text-[#516459]`;
const pips = new Intl.NumberFormat("en-US");

export function TargetCell({ signal, target, hit, rowKey, showMetrics = true }: {
  signal?: PublicSignal; target: "tp1" | "tp2" | "tp3"; hit?: boolean; rowKey: string; showMetrics?: boolean;
}) {
  const price = signal?.[target];
  const metrics = showMetrics && signal && price ? goldTargetMetrics(signal.direction, signal.entry, signal.sl, price) : null;
  const missing = target === "tp3" && signal ? TP3_LABEL : EMPTY;
  const watch = target === "tp3" ? signal?.tp3_watch : undefined;
  return (
    <td className={cn(LEVEL, hit ? "bg-[hsl(var(--gain))] text-white" : !price && "text-muted-foreground")}
        data-testid={`sheet-${target}-${rowKey}`} data-hit={hit || undefined}
        title={watch?.unresolved_reason ?? (watch?.hit_at ? `TP3 confirmed ${fmtDate(watch.hit_at)}` : target === "tp3" ? TP3_NOTE : undefined)}>
      <span className="inline-flex items-center gap-1">
        {hit && <Check size={12} aria-label="Hit" />}{price ? fmtScalar(price) : missing}
      </span>
      {watch && !hit && <p className="mt-0.5 font-sans text-[10px] text-muted-foreground">{TP3_WATCH_LABEL[watch.state]}</p>}
      {metrics && <div className={cn("mt-1 space-y-0.5 font-sans text-[10px] leading-tight", hit ? "text-white" : "text-muted-foreground")}>
        <p>R:R 1:{fmtScalar(metrics.rewardRatio)}</p>
        <p>+${fmtScalar(metrics.moveUsd)}/oz</p>
        <p>+{pips.format(metrics.pips)} pips</p>
      </div>}
    </td>
  );
}

export function GoldSignalSheet({ cards, now, dataIssue, onHide }: {
  cards: GoldStrategyCard[];
  now: number;
  dataIssue: boolean;
  onHide: (code: string) => void;
}) {
  const [showPrevious, setShowPrevious] = useState(false);
  const rows = getGoldSheetRows(cards, showPrevious);
  return (
    <section className="desk-panel overflow-hidden rounded-xl border border-[#b9cbc0] bg-white text-[#182e23]"
      aria-label="Gold signal spreadsheet" data-testid="gold-signal-sheet">
      <div className="flex items-center justify-between gap-2 bg-[hsl(var(--ink))] px-3 py-3 text-white sm:px-4">
        <h2 className="flex items-center gap-2 text-sm font-semibold"><Sheet size={16} aria-hidden="true" /> XAUUSD worksheet</h2>
        <span className="font-mono text-[10px] tracking-wider text-emerald-100">READ ONLY</span>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-[#dbe4de] bg-[#f6f9f6] px-3 py-2 text-xs sm:px-4">
        <label className="inline-flex min-h-6 cursor-pointer items-center gap-2 font-medium">
          <input type="checkbox" checked={showPrevious} onChange={(event) => setShowPrevious(event.target.checked)}
            className="size-4 accent-[#175339]" data-testid="checkbox-sheet-last-signal" />
          Show last closed signal
        </label>
        <span className="text-[#516459]"><span className="sm:hidden">Swipe for more columns · </span>{rows.length} {rows.length === 1 ? "row" : "rows"}</span>
      </div>
      <div className="overflow-x-auto focus-visible:outline-2 focus-visible:outline-inset focus-visible:outline-[#175339]" role="region"
        aria-label="Scrollable signals table" tabIndex={0} data-testid="region-gold-sheet">
        <table className="w-full min-w-[990px] border-separate border-spacing-0 text-xs">
          <caption className="sr-only">XAUUSD test signals by strategy. Green target cells and red stop cells mark confirmed hits.</caption>
          <thead>
            <tr aria-hidden="true" className="bg-[#f0f4f0] text-center font-mono text-[10px] text-[#516459]">
              <td className={cn(ROW_NUMBER, "py-1")} />
              {HEADERS.map((name, index) => <td key={name} className={cn(GRID, "py-1 last:border-r-0")}>{String.fromCharCode(65 + index)}</td>)}
            </tr>
            <tr className="whitespace-nowrap bg-[#e2efe7] text-left text-[11px] font-semibold text-[#264536]">
              <th scope="col" className={ROW_NUMBER}><span className="sr-only">Row</span>#</th>
              {HEADERS.map((name, index) => (
                <th scope="col" key={name} className={cn(GRID, "px-2.5 py-2 last:border-r-0",
                  index === 0 && "sticky left-0 z-10 min-w-33 bg-[#e2efe7] sm:min-w-40",
                  index === 2 && "min-w-32", index >= 3 && index <= 7 && "text-right")}>{name}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(({ card, signal, previous, firstForStrategy }, index) => {
              const { strategy } = card;
              const hits = signal && hitLevels(signal.status, signal.tp2_at, signal.tp3_watch?.state);
              const rowKey = signal?.signal_id ?? strategy.strategy_code;
              const age = signal && fmtAge(signal.issued_at_utc, now);
              const state = card.state === "signal" && dataIssue ? "unconfirmed" : card.state;
              const display = signal && (previous || !dataIssue) ? publishedSignalState(signal, now) : null;
              const status = display?.label ?? STATE_LABEL[state];
              const result = signal?.closed_at && !signal.unresolved_reason
                ? signal : !signal && card.latest?.closed_at && !card.latest.unresolved_reason ? card.latest : undefined;
              const bg = index % 2 ? "bg-[#f8faf8]" : "bg-white";
              return (
                <tr key={rowKey} className={bg} data-testid={`row-sheet-${rowKey}`}>
                  <td className={ROW_NUMBER}>{index + 1}</td>
                  <th scope="row" className={cn(CELL, "sticky left-0 z-10 w-33 text-left font-normal sm:w-40", bg)}>
                    <div className="flex items-center justify-between gap-1">
                      <span className="font-semibold">{strategy.name}</span>
                      {firstForStrategy && <button type="button" onClick={() => onHide(strategy.strategy_code)}
                        aria-label={`Hide ${strategy.name}`} title="Hide strategy"
                        className="shrink-0 rounded p-1.5 text-[#516459] hover:bg-[#e2efe7] focus-visible:outline-2 focus-visible:outline-[#175339]"
                        data-testid={`button-sheet-hide-${strategy.strategy_code}`}><EyeOff size={13} /></button>}
                    </div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[10px] text-[#516459]">
                      {STYLE_NAMES[strategy.style]}{strategy.site_test && <SiteTestBadge />}
                    </div>
                  </th>
                  <td className={CELL}>
                    {signal ? <span className={cn("rounded px-1.5 py-0.5 font-semibold", signal.direction === "BUY"
                      ? "bg-[#e0f1e6] text-[#175339]" : "bg-[#fae9e6] text-[#942f26]")}>{signal.direction}</span>
                      : <span className="text-muted-foreground">{EMPTY}</span>}
                  </td>
                  <td className={CELL} data-testid={`sheet-status-${rowKey}`}>
                    {previous && <span className="mb-0.5 block text-[10px] font-medium text-[#516459]">Previous · not open</span>}
                    <span className={cn("font-medium", state === "warming" && !previous && "text-[#795006]")}>
                      {status}{!signal && card.warmup && ` · ${card.warmup.have}/${card.warmup.need}`}
                    </span>
                    {display?.detail && <span className="mt-0.5 block text-[11px] text-muted-foreground">{display.detail}</span>}
                    {result?.result_r != null && <span className={cn("mt-0.5 block whitespace-nowrap text-[11px]", rTone(result.result_r))}>
                      {!previous && "Last: "}{fmtR(result.result_r)}
                    </span>}
                    {(signal?.status === "TP1" || signal?.status === "TP2_OPEN") && !dataIssue && <span className="mt-0.5 block text-[10px] text-[#516459]">Stop at breakeven</span>}
                  </td>
                  <td className={cn(LEVEL, !signal && "text-muted-foreground")}>{signal ? fmtScalar(signal.entry) : EMPTY}</td>
                  <td className={cn(LEVEL, hits && hits.sl ? "bg-[hsl(var(--loss))] text-white" : !signal && "text-muted-foreground")}
                    data-hit={hits && hits.sl || undefined}>
                    {hits && hits.sl && <X size={12} className="mr-1 inline-block" aria-label="Hit" />}
                    {signal ? fmtScalar(signal.sl) : EMPTY}
                  </td>
                  <TargetCell signal={signal} target="tp1" hit={hits?.tp1} rowKey={rowKey} />
                  <TargetCell signal={signal} target="tp2" hit={hits?.tp2} rowKey={rowKey} />
                  <TargetCell signal={signal} target="tp3" hit={hits?.tp3} rowKey={rowKey} />
                  <td className={cn(CELL, "whitespace-nowrap text-muted-foreground")}>
                    {signal ? <time dateTime={signal.issued_at_utc} title={`${cambodiaDateTime(signal.issued_at_utc)} ICT`}>{age ?? `${cambodiaDateTime(signal.issued_at_utc)} ICT`}</time> : EMPTY}
                  </td>
                  <td className={cn(CELL, "min-w-40 border-r-0")}><ParallelTargetResult plan={signal?.parallel_targets} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 bg-[#f6f9f6] px-3 py-2 text-[11px] text-[#43554a] sm:px-4">
        <p><strong className="font-semibold text-[#175339]">TP3:</strong> {TP3_NOTE}</p>
        <p>{PARALLEL_NOTE}</p>
        <p>Target distances before costs · 1 tracker pip = $0.01/oz</p>
      </div>
    </section>
  );
}
