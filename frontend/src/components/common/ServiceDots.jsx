import { SERVICES } from '../../config/serviceRegistry.js';

const DOT = { ok: 'bg-emerald-500', degraded: 'bg-amber-500', offline: 'bg-slate-400', checking: 'bg-slate-300' };
const WORD = { ok: 'online', degraded: 'degraded', offline: 'offline', checking: 'checking' };

/** One dot per backend service; the tooltip and screen-reader text carry the name and state (never colour alone). */
export default function ServiceDots({ services }) {
  const summary = SERVICES.map((s) => `${s.label}: ${WORD[services[s.id]] ?? 'checking'}`).join(', ');
  return (
    <span className="inline-flex items-center gap-1" title={summary} role="img" aria-label={summary}>
      {SERVICES.map((s) => (
        <span key={s.id} className={`h-2 w-2 rounded-full ${DOT[services[s.id]] ?? DOT.checking}`} title={`${s.label}: ${WORD[services[s.id]] ?? 'checking'}`} />
      ))}
    </span>
  );
}
