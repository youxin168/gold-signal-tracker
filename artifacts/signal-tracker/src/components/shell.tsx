import { type ReactNode, useRef } from "react";
import { Link, useLocation } from "wouter";
import { Activity, ChevronDown } from "lucide-react";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

const MORE = [
  { href: "/telegram", label: "Telegram alerts" },
  { href: "/signals", label: "All signals" },
  { href: "/strategies", label: "Strategies" },
  { href: "/scoreboard", label: "Scoreboard" },
  { href: "/compare", label: "Compare" },
  { href: "/about", label: "Method & risk" },
];

export function Shell({ children }: { children: ReactNode }) {
  const [location] = useLocation();
  const main = useRef<HTMLElement>(null);
  const isActive = (h: string) => location === h || (h !== "/" && location.startsWith(`${h}/`));
  const moreActive = MORE.some(({ href }) => isActive(href));
  const linkClass = "inline-flex min-h-9 items-center nav-link rounded-md px-2 text-xs whitespace-nowrap font-medium transition-colors hover:bg-white/10 hover:text-white focus-visible:outline-2 focus-visible:outline-ring sm:px-3 sm:text-sm";
  return (
    <div className="flex min-h-[100dvh] flex-col">
      <button type="button" onClick={() => main.current?.focus()} data-testid="button-skip-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-card focus:px-3 focus:py-2">Skip to content</button>
      <header className="sticky top-0 z-40 border-b-2 border-[hsl(var(--gold))] bg-[hsl(var(--ink))] text-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-x-2 gap-y-0.5 px-4 py-1.5 sm:px-6 sm:py-2">
          <Link href="/" className="inline-flex min-h-10 items-center gap-2 whitespace-nowrap text-[15px] font-semibold tracking-tight sm:gap-2.5 sm:text-lg" data-testid="link-home">
            <span aria-hidden="true" className="grid size-8 shrink-0 place-items-center rounded-md bg-[hsl(var(--gold))] text-[hsl(var(--ink))] sm:size-8"><Activity size={18} strokeWidth={2.2} /></span>
            <span>Signal Tracker<span className="ml-2 hidden align-middle font-mono text-[10px] font-medium tracking-[0.18em] text-[hsl(var(--gold))] md:inline">XAUUSD</span></span>
          </Link>
          <nav aria-label="Main" className="flex items-center gap-0.5 sm:gap-1">
            <Link href="/" aria-current={isActive("/") ? "page" : undefined} data-testid="link-nav-gold"
              className={cn(linkClass, isActive("/") ? "text-white" : "text-[#b9c9cf]")}>Signals</Link>
            <Link href="/history" aria-current={isActive("/history") ? "page" : undefined} data-testid="link-nav-history"
              className={cn(linkClass, isActive("/history") ? "text-white" : "text-[#b9c9cf]")}>History</Link>
            <DropdownMenu modal={false}>
              <DropdownMenuTrigger data-testid="button-more" className={cn(linkClass, "gap-1", moreActive ? "text-white" : "text-[#b9c9cf]")}>
                More <ChevronDown aria-hidden="true" className="h-3.5 w-3.5" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-44">
                {MORE.map(({ href, label }) => (
                  <DropdownMenuItem key={href} asChild>
                    <Link href={href} aria-current={isActive(href) ? "page" : undefined} data-testid={`link-nav-${href.slice(1)}`} className="min-h-10 cursor-pointer">
                      {label}
                    </Link>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </nav>
        </div>
      </header>
      <main id="main" ref={main} tabIndex={-1}
        className="mx-auto w-full max-w-7xl flex-1 px-4 py-5 outline-none sm:px-6 sm:py-7"
        key={location}>{children}</main>
      <footer className="border-t border-border bg-muted/50">
        <div className="mx-auto max-w-7xl px-4 py-5 text-xs leading-relaxed text-muted-foreground sm:px-6" data-testid="text-disclosure">
          Testing only. Signals can be delayed. No trades are placed. Not financial advice.
        </div>
      </footer>
    </div>
  );
}
