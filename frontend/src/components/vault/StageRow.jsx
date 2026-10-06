import { CheckCircle2, Circle, Loader2, XCircle } from 'lucide-react';

const TONES = {
  pass: { icon: CheckCircle2, cls: 'text-emerald-700' },
  fail: { icon: XCircle, cls: 'text-red-700' },
  pending: { icon: Loader2, cls: 'text-brand', spin: true },
  idle: { icon: Circle, cls: 'text-slate-400' },
};

/** One line of the security checklist. Tone is conveyed by icon + text, never colour alone. */
export default function StageRow({ tone = 'idle', label, detail }) {
  const { icon: Icon, cls, spin } = TONES[tone];
  return (
    <li className={`flex items-start gap-3 text-sm transition-colors ${cls}`}>
      <Icon className={`mt-0.5 h-5 w-5 shrink-0 ${spin ? 'animate-spin' : ''}`} aria-hidden />
      <div>
        <p className="font-medium">{label}</p>
        {detail && <p className="text-xs text-slate-600">{detail}</p>}
      </div>
    </li>
  );
}
