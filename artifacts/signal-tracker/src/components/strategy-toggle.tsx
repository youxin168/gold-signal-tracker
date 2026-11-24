import { ChevronDown } from "lucide-react";
import { Link } from "wouter";
import { SiteTestBadge } from "@/components/site-test-badge";
import type { Strategy } from "@/lib/public-snapshot";
import { STYLE_NAMES } from "@/lib/format";

export function StrategyToggle({ strategy, featured = false }: { strategy: Strategy; featured?: boolean }) {
  return (
    <details className="group" data-testid={`details-strategy-${strategy.strategy_code}`}>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded-md px-4 py-3 hover:bg-muted/60 focus-visible:outline-2 focus-visible:outline-ring [&::-webkit-details-marker]:hidden"
        data-testid={`toggle-strategy-${strategy.strategy_code}`}>
        <span>
          <span className={featured ? "font-medium text-primary" : "font-display text-lg"}>
            {featured ? `Strategy: ${strategy.name}` : strategy.name}
          </span>
          {strategy.site_test && <span className="ml-2"><SiteTestBadge /></span>}
          {!featured && <span className="block text-xs text-muted-foreground">{STYLE_NAMES[strategy.style]} · {strategy.entry_timeframe} / {strategy.trend_timeframe}{strategy.experimental ? " · Experimental" : ""}</span>}
        </span>
        <ChevronDown aria-hidden="true" className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
      </summary>
      <div className="space-y-3 border-t border-border px-4 py-4 text-sm">
        <p className="font-mono text-xs text-muted-foreground">{strategy.strategy_code}{featured && strategy.experimental ? " · Experimental" : ""}</p>
        {strategy.rules.length > 0 && <ul className="list-disc space-y-1 pl-4 text-muted-foreground">{strategy.rules.map((rule) => <li key={rule}>{rule}</li>)}</ul>}
        <Link href={`/strategies/${encodeURIComponent(strategy.strategy_code)}`} data-testid={`link-strategy-${strategy.strategy_code}`} className="inline-block font-medium text-primary underline underline-offset-4">View full strategy</Link>
      </div>
    </details>
  );
}
