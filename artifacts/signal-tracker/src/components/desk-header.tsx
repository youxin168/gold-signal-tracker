import type { ReactNode } from "react";

export function DeskHeader({ label, title, description, children }: {
  label: string; title: string; description: string; children?: ReactNode;
}) {
  return (
    <header className="desk-header relative isolate mb-4 overflow-hidden rounded-lg px-4 py-4 sm:px-6 sm:py-5">
      <svg aria-hidden="true" viewBox="0 0 380 120" preserveAspectRatio="xMaxYMid slice"
        className="pointer-events-none absolute inset-y-0 right-0 -z-10 h-full w-[45%] text-[hsl(var(--gold))] opacity-40 max-sm:opacity-15">
        <g stroke="currentColor" strokeWidth="1" fill="currentColor">
          <path d="M96 82v28M130 76v30M164 60v30M198 50v32M232 54v30M266 36v30M300 24v34M334 32v30M368 12v38" />
          <path fillOpacity=".4" d="M90 88h12v14H90zM124 82h12v14h-12zM158 66h12v16h-12zM192 58h12v14h-12zM226 60h12v16h-12zM260 42h12v14h-12zM294 30h12v18h-12zM328 40h12v14h-12zM362 22h12v18h-12z" />
        </g>
      </svg>
      <div className="relative flex flex-wrap items-end justify-between gap-x-5 gap-y-3">
        <div className="min-w-0">
          <p className="mb-1.5 flex items-center gap-2 font-mono text-[10px] font-medium tracking-[0.2em] text-[hsl(var(--gold))]">
            <span aria-hidden="true" className="h-1.5 w-1.5 rotate-45 bg-current" />{label}
          </p>
          <h1 className="text-2xl leading-tight font-semibold tracking-[-0.025em] text-white sm:text-[1.85rem]">{title}</h1>
          <p className="mt-1 max-w-xl text-[13px] text-[#bccbd0]">{description}</p>
        </div>
        {children}
      </div>
    </header>
  );
}
