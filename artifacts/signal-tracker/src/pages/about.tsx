import { PageHeader } from "@/components/bits";

const SECTIONS: { h: string; p: string[] }[] = [
  { h: "What this is", p: ["A public journal of XAUUSD spot-gold signals produced by fixed, versioned rule sets. It exists to test whether simple systematic rules hold up, written for someone learning to evaluate strategies honestly.", "It is not a broker, does not place trades, does not predict prices and is not advice."] },
  { h: "Evidence sources stay separate", p: ["LIVE records were recorded prospectively in the research journal; the public snapshot may arrive later. REPLAY reruns the engine over recorded data. BACKTEST scores each historical fold separately. The site never pools these modes or price feeds.", "The 2023–2024 audit found technical setups but had no eligible trades because fresh bid/ask and then-known news evidence was unavailable. This does not establish that the rules fail or that they never trigger."] },
  { h: "How the numbers are counted", p: ["Fill rate = filled ÷ (filled + expired). Unresolved entries do not count against the fill rate. Expiry without an entry is not a loss.", "Win rate = positive net results ÷ completed trades, including flat results in the denominator. Open trades and TP1 partials are not completed results.", "Results are in R, where 1R is the distance from entry to the original stop. Realized equity adds the net R at each close time.", "Only closed candles are used; if a stop and target are both touched in a candle, the stop takes priority. After TP1 the remaining stop moves to breakeven under the frozen partial-exit rule."] },
  { h: "Ranks and uncertainty", p: ["Ranking requires at least two comparable same-style strategies with 100 or more completed trades each. Total R, expectancy, lower drawdown and profit factor determine rank. Win rate does not.", "The 95% intervals for win rate and expectancy are descriptive, not forecasts. A large sample does not guarantee that results will persist."] },
  { h: "Comparing external strategies", p: ["The comparison uses only the same style, price feed, and BACKTEST fold, or the overlap of recorded UTC issue dates in LIVE or REPLAY. A shared date window does not prove both strategies ran continuously.", "Manually supplied signals can show their own realized results, but never earn a leader against an automated strategy whose eligibility rules can be checked. Imports with historic dates are REPLAY only."] },
  { h: "Known data limits", p: ["HistData archives contain bid-only candles. The frozen result model estimates ask-side fills using explicit spread and slippage assumptions. These assumptions cannot substitute for an observed spread when deciding whether to issue a signal.", "Historical candles and news coverage can contain gaps. Missing entry or outcome data is left unresolved, not counted as a fill, loss, or expiry.", "The site reflects periodic snapshots, not a live price stream. GitHub Actions may delay, skip, or stop scheduled runs, and instrument access depends on the availability of an OANDA practice account in your region."] },
];

export default function AboutPage() {
  return (
    <>
      <PageHeader kicker="Methodology and risk" title="How to read this journal">
        Trading gold carries real risk of loss. Past results, especially from small or simulated samples, do not predict future ones.
      </PageHeader>
      <div className="max-w-3xl space-y-10">
        {SECTIONS.map((s, i) => (
          <section key={s.h} className="rise grid gap-3 md:grid-cols-[180px_1fr]" style={{ animationDelay: `${i * 60}ms` }}>
            <h2 className="font-display text-xl">{s.h}</h2>
            <div className="space-y-3 text-[15px] leading-relaxed text-muted-foreground">{s.p.map((t, j) => <p key={j}>{t}</p>)}</div>
          </section>
        ))}
      </div>
    </>
  );
}
