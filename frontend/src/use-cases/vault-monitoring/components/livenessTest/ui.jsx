import { AlertTriangle, CheckCircle2, Circle, XCircle } from 'lucide-react';

const BADGE_TONES = {
  success: { cls: 'bg-[#E6F6EE] text-[#0B6B43]', icon: CheckCircle2 },
  warning: { cls: 'bg-[#FFF4DC] text-[#6B4500]', icon: AlertTriangle },
  danger: { cls: 'bg-[#FDECEA] text-[#B3261E]', icon: XCircle },
  neutral: { cls: 'bg-[#F4F6FB] text-[#55607A]', icon: Circle },
};

/** Status pill: always text plus an icon, never colour alone. */
export function Badge({ tone = 'neutral', children, title }) {
  const { cls, icon: Icon } = BADGE_TONES[tone];
  return (
    <span title={title} className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-bold tracking-wide ${cls}`}>
      <Icon className="h-3.5 w-3.5" aria-hidden />
      {children}
    </span>
  );
}

export function LabCard({ title, badge, aside, tone, children, labelledBy }) {
  const toneCls = tone === 'warning' ? 'border-[#F2D58F] bg-[#FFF9EC]' : '';
  return (
    <section aria-labelledby={labelledBy} className={`vault-card p-5 ${toneCls}`}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 id={labelledBy} className="vault-heading text-base">{title}</h2>
        {(badge || aside) && (
          <div className="flex items-center gap-2">
            {aside && <span className="text-xs text-[#55607A]">{aside}</span>}
            {badge}
          </div>
        )}
      </div>
      {children}
    </section>
  );
}

export function Row({ label, children, highlight }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-[#EEF1F7] py-2 text-sm last:border-b-0">
      <dt className="text-[#55607A]">{label}</dt>
      <dd className={`font-mono tabular-nums ${highlight ? 'font-semibold text-[#6B4500]' : 'text-[#0F1B3D]'}`}>{children}</dd>
    </div>
  );
}

export function DetectorError({ detector, error }) {
  return (
    <p role="alert" className="flex items-start gap-2 rounded-lg bg-[#FDECEA] p-3 text-sm text-[#B3261E]">
      <XCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <span><span className="font-semibold">{detector} error:</span> {error}</span>
    </p>
  );
}
