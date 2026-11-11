import { ChevronRight } from 'lucide-react';
import { AlertSnapshot } from '../../../components/alerts/AlertPresentation.jsx';

const severityStyles = {
  WARNING: { accent: 'border-l-[#F59E0B]', badge: 'bg-[#FFF3C4] text-[#8F5000]', dot: 'bg-[#D97706]', value: 'text-[#B45309]' },
  HIGH: { accent: 'border-l-red-600', badge: 'bg-red-100 text-red-800', dot: 'bg-red-600', value: 'text-red-700' },
  CRITICAL: { accent: 'border-l-red-600', badge: 'bg-red-100 text-red-800', dot: 'bg-red-600', value: 'text-red-700' },
  INFO: { accent: 'border-l-sky-500', badge: 'bg-sky-100 text-sky-800', dot: 'bg-sky-500', value: 'text-sky-700' },
};
const highlightValues = (description, className) => description.split(/(\b\d+(?:\.\d+)?\s*(?:seconds?|secs?|minutes?|people|persons?|s)\b)/gi)
  .map((part, index) => index % 2 ? <strong key={index} className={`font-bold ${className}`}>{part}</strong> : part);

/** Compact presentation only: the existing panel owns persisted data and selection. */
export default function GrillGateAlertCard({ alert, selected, onSelect }) {
  const style = severityStyles[alert.severity] || { accent: 'border-l-slate-400', badge: 'bg-slate-100 text-slate-700', dot: 'bg-slate-500', value: 'text-slate-700' };
  const description = alert.summary || alert.title || alert.sourceEventType || 'Monitoring alert';
  return <article className="@container min-w-0">
    <button type="button" onClick={() => onSelect(alert.id)} aria-pressed={selected}
      aria-label={`${alert.severity}, ${alert.status}. ${description}. Open alert details`}
      className={`grid min-h-[112px] w-full items-center gap-3 overflow-hidden rounded-[20px] border-l-[5px] bg-white py-4 pl-4 pr-3 text-left shadow-[0_6px_24px_rgba(15,27,61,0.08)] transition-shadow hover:shadow-[0_8px_28px_rgba(15,27,61,0.13)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#34479B] ${style.accent} ${selected ? 'ring-2 ring-[#34479B]' : ''}`}
      style={{ gridTemplateColumns: 'clamp(3.5rem, 17cqw, 5.5rem) minmax(0, 1fr) clamp(2rem, 9cqw, 2.75rem)' }}>
      <AlertSnapshot alert={alert} compact />
      <span className="min-w-0">
        <span className={`mb-2 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-bold leading-none tracking-wide ${style.badge}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${style.dot}`} aria-hidden="true" />{alert.severity || 'ALERT'}
        </span>
        <span className="block break-words text-sm leading-[1.55] text-[#202530]">{highlightValues(description, style.value)}</span>
      </span>
      <span className="flex aspect-square w-full items-center justify-center rounded-full bg-[#EEF0FC] text-[#34479B]" aria-hidden="true"><ChevronRight size={19} strokeWidth={2} /></span>
    </button>
  </article>;
}
