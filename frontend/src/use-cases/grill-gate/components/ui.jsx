/** Shared Grill Gate UI primitives using the Vault Access light palette. */

export const TONES = {
  ok: 'bg-emerald-50 text-emerald-800 ring-emerald-200',
  warn: 'bg-amber-50 text-amber-800 ring-amber-200',
  bad: 'bg-rose-50 text-rose-800 ring-rose-200',
  info: 'bg-sky-50 text-sky-800 ring-sky-200',
  idle: 'bg-slate-100 text-slate-700 ring-slate-200',
  purple: 'bg-violet-50 text-violet-800 ring-violet-200',
};
const DOTS = { ok: 'bg-emerald-400', warn: 'bg-amber-400', bad: 'bg-rose-400', info: 'bg-sky-400', idle: 'bg-slate-400', purple: 'bg-violet-400' };

export const btn = 'inline-flex min-h-9 items-center justify-center gap-1.5 rounded-lg px-3 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-40';
export const btnPrimary = `${btn} bg-[#34479B] text-white hover:bg-[#293B86]`;
export const btnDanger = `${btn} bg-rose-50 text-rose-800 ring-1 ring-rose-200 hover:bg-rose-100`;
export const btnGhost = `${btn} bg-white text-[#34479B] ring-1 ring-[#E3E7F0] hover:bg-[#F4F6FB]`;

export function Card({ title, aside, className = '', children }) {
  return (
    <section className={`rounded-xl border border-[#E3E7F0] bg-white p-4 sm:p-5 ${className}`}>
      {(title || aside) && (
        <header className="mb-3 flex items-center justify-between gap-3">
          {title && <h2 className="text-[15px] font-semibold text-[#0F1B3D]">{title}</h2>}
          {aside && <div className="flex shrink-0 items-center gap-2 text-xs text-[#55607A]">{aside}</div>}
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

export function StatCard({ label, value, valueClass = 'text-slate-500', sub, badge }) {
  return (
    <div className="rounded-xl border border-[#E3E7F0] bg-white p-4">
      <p className="text-xs text-[#55607A]">{label}</p>
      <p className={`mt-1 text-[28px] font-bold leading-tight ${valueClass}`}>{value}</p>
      {badge && <div className="mt-1">{badge}</div>}
      {sub && <p className="mt-1 text-xs leading-5 text-[#55607A]">{sub}</p>}
    </div>
  );
}

export function ErrorNote({ children }) {
  if (!children) return null;
  return <p role="alert" className="rounded-lg bg-rose-50 p-3 text-sm text-rose-800 ring-1 ring-rose-200">{children}</p>;
}
