import { memo, useState } from 'react';
import { AlertTriangle, Bell, Camera, CircleAlert, Info, ShieldAlert } from 'lucide-react';

export const ALERT_TYPES = {
  COUNT_MISMATCH: { label: 'Count mismatch', icon: AlertTriangle },
  EXCESS_PERSON: { label: 'Excess person', icon: ShieldAlert },
  UNAUTHORIZED_ENTRY: { label: 'Unauthorized entry', icon: ShieldAlert },
  NO_ENTRY: { label: 'No entry', icon: Info },
  SESSION_EXPIRED: { label: 'Session expired', icon: AlertTriangle },
  CAMERA_FEED_STALE: { label: 'Camera feed stale', icon: Camera },
  CAMERA_FEED_LOST: { label: 'Camera feed lost', icon: Camera },
};

export const ACTION_LABELS = { acknowledge: 'Acknowledge', resolve: 'Resolve', dismiss: 'Discard' };
const tone = {
  CRITICAL: 'border-l-red-600 bg-red-50 text-red-800', HIGH: 'border-l-red-400 bg-rose-50 text-rose-900',
  WARNING: 'border-l-amber-500 bg-amber-50 text-amber-900', INFO: 'border-l-blue-500 bg-blue-50 text-blue-900',
  RESOLVED: 'border-l-emerald-500 bg-emerald-50 text-emerald-900', DISMISSED: 'border-l-slate-400 bg-slate-50 text-slate-700',
};

export function relativeTime(value) {
  if (!value) return 'Time unavailable';
  const seconds = Math.max(0, Math.floor((Date.now() - Date.parse(value)) / 1000));
  if (seconds < 60) return `${seconds} sec ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} hr ago`;
  return `${Math.floor(seconds / 86400)} days ago`;
}

function AlertCard({ alert, variant = 'row', onSelect, onAction, pending = false, thumbnailUrl }) {
  const [noteOpen, setNoteOpen] = useState(false);
  const [noteAction, setNoteAction] = useState('dismiss');
  const [note, setNote] = useState('');
  const registry = ALERT_TYPES[alert.type] || { label: String(alert.type || 'Unknown alert').replaceAll('_', ' ').toLowerCase(), icon: Bell };
  const Icon = registry.icon;
  const severityTone = tone[alert.status] || tone[alert.severity] || tone.INFO;
  const humanTime = relativeTime(alert.lastSeenAt || alert.createdAt);
  const exactTime = (value) => value ? new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit', timeZoneName: 'short' }).format(new Date(value)) : 'Unavailable';
  const actions = alert.allowedActions;
  const compact = variant === 'compact';
  const drawer = variant === 'drawer';
  const actionButton = (action) => <button key={action} type="button" disabled={pending}
    onClick={(event) => { event.stopPropagation(); if (action === 'dismiss' || action === 'resolve') { setNoteAction(action); setNoteOpen(true); } else onAction?.(alert, action); }}
    className={`min-h-9 rounded-md px-3 text-xs font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand disabled:opacity-50 ${action === 'acknowledge' ? 'bg-[#34479B] text-white hover:bg-[#293a83]' : 'border border-slate-200 bg-white text-[#26365F] hover:bg-slate-50'}`}>
    {ACTION_LABELS[action]}
  </button>;
  const discardLocked = !actions.includes('dismiss') && alert.status !== 'RESOLVED' && alert.status !== 'DISMISSED';
  return <article role={onSelect ? 'group' : undefined} tabIndex={onSelect ? 0 : undefined}
    onClick={() => onSelect?.(alert)} onKeyDown={(event) => { if (event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); onSelect?.(alert); } }}
    className={`min-w-0 border-l-4 ${severityTone} ${compact ? 'rounded-xl border border-slate-200 border-l-4 bg-white p-3 text-[#152449]' : 'rounded-xl border border-slate-200 border-l-4 bg-white p-4 text-[#152449]'} ${onSelect ? 'cursor-pointer hover:border-[#aab7df]' : ''}`}>
    <div className="flex min-w-0 items-start justify-between gap-3">
      <div className="flex min-w-0 items-center gap-2">
        <span className={`shrink-0 rounded-md px-2 py-1 text-[10px] font-bold uppercase tracking-wide ${alert.severity === 'CRITICAL' || alert.severity === 'HIGH' ? 'bg-red-100 text-red-800' : alert.severity === 'WARNING' ? 'bg-amber-100 text-amber-900' : 'bg-blue-100 text-blue-800'}`}>{alert.severity || 'INFO'}</span>
        <span className="sr-only">{registry.label}</span>
      </div>
      <time className="shrink-0 text-xs text-slate-500" dateTime={alert.lastSeenAt || alert.createdAt} title={`Last seen ${exactTime(alert.lastSeenAt || alert.createdAt)} · First seen ${exactTime(alert.firstSeenAt)}`}>{humanTime}</time>
    </div>
    <h3 className="mt-2 flex items-start gap-2 break-words text-sm font-bold text-[#152449]"><Icon className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" aria-hidden/>{alert.title || registry.label}</h3>
    <p className={`mt-0.5 text-xs leading-5 text-slate-600 ${compact ? 'line-clamp-1' : ''}`}>{alert.message || 'No additional details.'}</p>
    <p className="mt-0.5 text-xs text-slate-500">{alert.observedCount != null && alert.requiredCount != null ? `${alert.observedCount} people present, ${alert.requiredCount} required` : null}{alert.cameraId ? `${alert.observedCount != null ? ' · ' : ''}${alert.cameraId}` : ''}{alert.incidentNumber ? ` · ${alert.incidentNumber}` : ''}</p>
    {thumbnailUrl && <img src={thumbnailUrl} alt={`Evidence thumbnail for ${registry.label}`} loading="lazy" className="mt-2 h-20 w-32 rounded-lg object-cover" />}
    {alert.primaryEvidenceId && !thumbnailUrl && <div role="status" aria-label="Evidence thumbnail unavailable" className="mt-2 flex h-16 w-32 items-center justify-center rounded-lg bg-slate-100 text-center text-[10px] text-slate-500">Evidence preview unavailable</div>}
    {alert.evidenceStatus === 'PENDING' && <p className="mt-2 text-xs text-slate-500" role="status">Capturing evidence…</p>}
    {alert.evidenceStatus === 'FAILED' && <p className="mt-2 text-xs font-medium text-red-700" role="status">Evidence capture failed</p>}
    {variant === 'row' && <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-3">
      <div className="flex flex-wrap gap-2 text-[11px] text-slate-500">{alert.useCase && <span className="rounded bg-slate-100 px-2 py-1">{alert.useCase}</span>}{alert.branchName && <span>{alert.branchName}</span>}{alert.cameraId && <span>{alert.cameraId}</span>}{alert.status && <span>{alert.status}</span>}{alert.occurrenceCount > 1 && <span>× {alert.occurrenceCount}</span>}</div>
      <div className="flex flex-wrap gap-2">{actions.map(actionButton)}{discardLocked && <button type="button" disabled title="High and Critical alerts must be resolved with a note." aria-label="Discard locked: high and critical alerts must be resolved with a note" className="min-h-9 cursor-not-allowed rounded-md border border-slate-200 bg-slate-50 px-3 text-xs text-slate-400">Discard locked</button>}</div>
    </div>}
    {compact && <div className="mt-2 flex flex-wrap gap-2">{actions.includes('acknowledge') && actionButton('acknowledge')}{actions.includes('dismiss') ? actionButton('dismiss') : discardLocked && <button type="button" disabled title="High and Critical alerts must be resolved with a note." aria-label="Discard locked: high and critical alerts must be resolved with a note" className="min-h-9 cursor-not-allowed rounded-md border border-slate-200 bg-slate-50 px-3 text-xs text-slate-400">Discard locked</button>}</div>}
    {drawer && <div className="mt-4 flex flex-wrap gap-2">{actions.map(actionButton)}{discardLocked && <span className="text-xs text-slate-500">Discard is locked for High and Critical alerts.</span>}</div>}
    {noteOpen && <form className="mt-3 space-y-2" onSubmit={(event) => { event.preventDefault(); onAction?.(alert, noteAction, note); setNoteOpen(false); }} onClick={(event) => event.stopPropagation()}>
      <label className="block text-xs font-medium text-slate-600">{noteAction === 'dismiss' ? 'Note (required to discard)' : 'Resolution note (required)'}
        <textarea autoFocus value={note} maxLength={500} required onChange={(event) => setNote(event.target.value)} className="mt-1 min-h-20 w-full resize-y rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-800 focus:border-[#34479B]" />
      </label><p className="text-right text-xs text-slate-500">{note.length}/500</p>
      <div className="flex gap-2"><button type="submit" disabled={pending || !note.trim()} className="min-h-9 flex-1 rounded-md border border-red-200 px-3 text-xs font-semibold text-red-700 disabled:opacity-50">Confirm {noteAction === 'dismiss' ? 'discard' : 'resolve'}</button><button type="button" onClick={() => setNoteOpen(false)} className="min-h-9 rounded-md border border-slate-200 px-3 text-xs">Cancel</button></div>
    </form>}
  </article>;
}

export default memo(AlertCard);
