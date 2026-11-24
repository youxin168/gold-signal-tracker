import { Link } from 'wouter';

export default function NotFound() {
  return (
    <div className="rise max-w-xl py-10">
      <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-accent-foreground">404</p>
      <h1 className="font-display mt-2 text-4xl">No page at this address</h1>
      <p className="mt-3 text-muted-foreground">The link may be from an older layout of the journal.</p>
      <Link href="/" className="mt-5 inline-block text-primary underline underline-offset-2" data-testid="link-home-404">Back to published signals</Link>
    </div>
  );
}
