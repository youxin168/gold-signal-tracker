import { ArrowUpRight, Bell, Settings2, ShieldCheck } from "lucide-react";
import { DeskHeader } from "@/components/desk-header";

// The bot handle is public. The bot token and subscriber details never enter the website.
const BOT = "https://t.me/Youxin_Opsok_bot";

const steps = [
  { title: "Add the bot in Telegram", detail: "Make @Youxin_Opsok_bot an admin of your own channel or group. For a channel, grant Post Messages." },
  { title: "Choose your destination", detail: "Open Connect in Telegram, tap Start if prompted, then choose the channel or group you manage." },
  { title: "Receive new test alerts", detail: "The bot confirms your connection privately. New gold signals go to that destination; older signals are not resent." },
];

export default function TelegramPage() {
  return (
    <>
      <DeskHeader label="XAUUSD / TELEGRAM" title="Telegram alerts" description="Send Signal Tracker’s gold test alerts to a channel or group you manage." />
      <div className="grid gap-4 md:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <section className="desk-panel rounded-lg border border-border bg-card p-5 sm:p-6" aria-labelledby="connect-telegram">
          <div className="mb-4 flex items-center gap-3">
            <span className="grid size-9 place-items-center rounded-lg bg-muted text-primary"><Bell size={17} aria-hidden="true" /></span>
            <h2 id="connect-telegram" className="text-lg font-semibold tracking-tight">Connect your Telegram</h2>
          </div>
          <ol className="mb-5 space-y-3.5">
            {steps.map(({ title, detail }, index) => (
              <li key={title} className="flex items-start gap-3">
                <span aria-hidden="true" className="grid size-6 shrink-0 place-items-center rounded-full bg-[hsl(var(--gold))] font-mono text-xs text-[hsl(var(--ink))]">{index + 1}</span>
                <div><p className="text-sm font-semibold">{title}</p><p className="mt-0.5 text-sm text-muted-foreground">{detail}</p></div>
              </li>
            ))}
          </ol>
          <a href={`${BOT}?start=connect_alerts`} target="_blank" rel="noopener noreferrer" data-testid="link-connect-telegram"
            className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-primary px-3.5 text-sm font-semibold text-primary-foreground hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">
            Connect in Telegram <ArrowUpRight size={16} aria-hidden="true" />
          </a>
        </section>
        <section className="desk-panel rounded-lg border border-border bg-card p-5 sm:p-6" aria-labelledby="manage-telegram">
          <div className="mb-4 flex items-center gap-3">
            <span className="grid size-9 place-items-center rounded-lg bg-muted text-primary"><Settings2 size={17} aria-hidden="true" /></span>
            <h2 id="manage-telegram" className="text-lg font-semibold tracking-tight">Manage your alerts</h2>
          </div>
          <p className="text-sm text-muted-foreground">One destination per Telegram account. Change or disconnect it in the bot without republishing this website.</p>
          <a href={`${BOT}?start=manage_alerts`} target="_blank" rel="noopener noreferrer" data-testid="link-manage-telegram"
            className="mt-4 inline-flex min-h-10 items-center gap-2 rounded-lg border border-border px-3.5 text-sm font-semibold text-primary hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring">
            Manage in Telegram <ArrowUpRight size={16} aria-hidden="true" />
          </a>
          <p className="mt-5 flex gap-2 border-t border-border pt-4 text-xs text-muted-foreground"><ShieldCheck size={16} className="shrink-0 text-primary" aria-hidden="true" />No website login, Telegram password or bot token needed. Alerts are testing-only and depend on the scanner being online.</p>
        </section>
      </div>
    </>
  );
}
