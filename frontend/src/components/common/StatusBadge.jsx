import { AlertCircle, CheckCircle2, Circle, HelpCircle, Loader2, XCircle } from 'lucide-react';

// Status is conveyed by icon + text + color (never color alone).
const STATUS = {
  LIVE: { cls: 'bg-red-50 text-red-700 border-red-200', icon: Circle, fill: true },
  CONNECTED: { cls: 'bg-emerald-50 text-emerald-700 border-emerald-200', icon: Circle, fill: true },
  DEGRADED: { cls: 'bg-amber-50 text-amber-700 border-amber-200', icon: AlertCircle },
  OFFLINE: { cls: 'bg-slate-100 text-slate-600 border-slate-300', icon: XCircle },
  DETECTED: { cls: 'bg-sky-50 text-sky-700 border-sky-200', icon: CheckCircle2 },
  MATCH: { cls: 'bg-emerald-50 text-emerald-700 border-emerald-200', icon: CheckCircle2 },
  UNKNOWN: { cls: 'bg-amber-50 text-amber-700 border-amber-200', icon: HelpCircle },
  VERIFIED: { cls: 'bg-emerald-50 text-emerald-700 border-emerald-200', icon: CheckCircle2 },
  'NOT VERIFIED': { cls: 'bg-red-50 text-red-700 border-red-200', icon: XCircle },
  ERROR: { cls: 'bg-red-50 text-red-700 border-red-200', icon: XCircle },
  PROCESSING: { cls: 'bg-blue-50 text-blue-700 border-blue-200', icon: Loader2, spin: true },
  CHECKING: { cls: 'bg-slate-100 text-slate-600 border-slate-300', icon: Loader2, spin: true },
  STOPPED: { cls: 'bg-slate-100 text-slate-600 border-slate-300', icon: Circle },
};

export default function StatusBadge({ status }) {
  const cfg = STATUS[status] ?? STATUS.UNKNOWN;
  const Icon = cfg.icon;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${cfg.cls}`}>
      <Icon className={`h-3 w-3 ${cfg.spin ? 'animate-spin' : ''} ${cfg.fill ? 'fill-current' : ''}`} aria-hidden />
      {status}
    </span>
  );
}
