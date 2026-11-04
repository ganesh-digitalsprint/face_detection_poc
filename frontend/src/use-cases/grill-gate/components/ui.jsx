/** Dark surface primitives matching the Grill Gate reference design. */

export const TONES = {
  ok: 'bg-emerald-500/15 text-emerald-300 ring-emerald-400/30',
  warn: 'bg-amber-500/15 text-amber-300 ring-amber-400/30',
  bad: 'bg-rose-500/15 text-rose-300 ring-rose-400/30',
  info: 'bg-sky-500/15 text-sky-300 ring-sky-400/30',
  idle: 'bg-slate-500/20 text-slate-300 ring-slate-400/20',
  purple: 'bg-violet-500/20 text-violet-300 ring-violet-400/30',
};
const DOTS = { ok: 'bg-emerald-400', warn: 'bg-amber-400', bad: 'bg-rose-400', info: 'bg-sky-400', idle: 'bg-slate-400', purple: 'bg-violet-400' };

export const btn = 'inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg px-3 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-40';
export const btnPrimary = `${btn} bg-[#3c5ba4] text-white hover:bg-[#4a6bbb]`;
export const btnDanger = `${btn} bg-rose-500/15 text-rose-200 ring-1 ring-rose-400/30 hover:bg-rose-500/25`;
export const btnGhost = `${btn} bg-white/5 text-slate-200 ring-1 ring-white/10 hover:bg-white/10`;

export function Card({ title, aside, className = '', children }) {
  return (
    <section className={`rounded-xl border border-[#22304d] bg-[#121b2f] p-4 sm:p-5 ${className}`}>
      {(title || aside) && (
        <header className="mb-3 flex items-center justify-between gap-3">
          {title && <h2 className="text-[15px] font-semibold text-slate-100">{title}</h2>}
          {aside && <div className="flex shrink-0 items-center gap-2 text-xs text-slate-400">{aside}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Pill({ tone = 'idle', dot = false, children, className = '' }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide ring-1 ${TONES[tone] ?? TONES.idle} ${className}`}>
      {dot && <span className={`h-1.5 w-1.5 rounded-full ${DOTS[tone] ?? DOTS.idle}`} aria-hidden />}
      {children}
    </span>
  );
}

/** Honest placeholder for monitoring data the backend does not produce yet. */
export function Pending({ title, children }) {
  return (
    <div className="rounded-lg border border-dashed border-[#2c3b5c] bg-[#0f1729] p-4 text-sm">
      <p className="flex items-center gap-2 font-semibold text-slate-200"><Pill tone="idle">Pending backend</Pill>{title}</p>
      {children && <p className="mt-2 text-xs leading-5 text-slate-400">{children}</p>}
    </div>
  );
}

export function StatCard({ label, value, valueClass = 'text-slate-500', sub, badge }) {
  return (
    <div className="rounded-xl border border-[#22304d] bg-[#121b2f] p-4">
      <p className="text-xs text-slate-400">{label}</p>
      <p className={`mt-1 text-[28px] font-bold leading-tight ${valueClass}`}>{value}</p>
      {badge && <div className="mt-1">{badge}</div>}
      {sub && <p className="mt-1 text-xs leading-5 text-slate-400">{sub}</p>}
    </div>
  );
}

export function ErrorNote({ children }) {
  if (!children) return null;
  return <p role="alert" className="rounded-lg bg-rose-500/10 p-3 text-sm text-rose-200 ring-1 ring-rose-400/30">{children}</p>;
}
