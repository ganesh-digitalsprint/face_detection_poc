import { useNavigate } from 'react-router-dom';
import AlertSnapshot from '../../../../components/alerts/AlertSnapshot.jsx';
import LifecycleConfirmation from '../../../../components/alerts/LifecycleConfirmation.jsx';
import CompactAlertCard from '../../../../components/alerts/CompactAlertCard.jsx';
import { memo, useState } from 'react';
import { AlertTriangle, Camera, Info, ShieldAlert } from 'lucide-react';

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
export function relativeTime(value) {
  if (!value) return 'Time unavailable';
  const seconds = Math.max(0, Math.floor((Date.now() - Date.parse(value)) / 1000));
  if (seconds < 60) return `${seconds} sec ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} hr ago`;
  return `${Math.floor(seconds / 86400)} days ago`;
}

function AlertCard({ alert, variant = 'row', onSelect, onAction, pending = false, thumbnailUrl }) {
  const navigate = useNavigate();
  const [confirmAction, setConfirmAction] = useState(null);
  const shared = { ...alert, useCase: 'vault_monitoring', summary: alert.message || alert.title,
    sourceEventId: alert.id, sourceEventType: alert.type, occurredAt: alert.createdAt };
  const openDetail = () => onSelect ? onSelect(alert) : navigate(`/alerts/vault?scope=${['RESOLVED','DISMISSED'].includes(alert.status) ? 'history' : 'active'}&alert=${encodeURIComponent(alert.id)}`);
  if (variant !== 'drawer') return <CompactAlertCard alert={shared} thumbnailUrl={thumbnailUrl} onSelect={openDetail} />;
  const permitted = { OPEN:['acknowledge','resolve','dismiss'], ACKNOWLEDGED:['resolve','dismiss'] }[alert.status] || [];
  const actions = (alert.allowedActions || []).filter((action) => permitted.includes(action));
  return <div className="space-y-4">
    <div className="flex gap-2"><span className="rounded-full bg-amber-50 px-2 py-1 text-xs font-bold">{alert.severity}</span><span className="text-sm font-semibold">{alert.status}</span></div>
    <AlertSnapshot alert={shared} large />
    <p className="text-sm leading-relaxed">{alert.message || alert.title}</p>
    <dl className="grid grid-cols-2 gap-3 text-xs">
      <div><dt>Camera / source</dt><dd>{alert.cameraId || alert.source || 'Unavailable'}</dd></div>
      <div><dt>Created</dt><dd>{alert.createdAt ? new Date(alert.createdAt).toLocaleString() : 'Unavailable'}</dd></div>
      <div><dt>Type</dt><dd>{ALERT_TYPES[alert.type]?.label || alert.type}</dd></div>
      <div><dt>Occurrences</dt><dd>{alert.occurrenceCount || 1}</dd></div>
    </dl>
    {alert.evidenceStatus === 'PENDING' && <p role="status" className="text-xs text-slate-500">Capturing evidence...</p>}
    {alert.evidenceStatus === 'FAILED' && <p role="status" className="text-xs text-red-700">Evidence capture failed</p>}
    {onAction && <div className="flex flex-wrap gap-2">{actions.map((action) => <button key={action} type="button" disabled={pending} onClick={() => action === 'acknowledge' ? onAction(alert, action) : setConfirmAction(action)} className="min-h-10 rounded-lg border border-slate-200 px-3 text-sm font-semibold text-[#34479B] disabled:opacity-50">{ACTION_LABELS[action]}</button>)}</div>}
    {onAction && ['OPEN','ACKNOWLEDGED'].includes(alert.status) && !actions.includes('dismiss') && <p className="text-xs text-slate-500">The source policy requires High and Critical alerts to be resolved with a note.</p>}
    {confirmAction && <LifecycleConfirmation target={confirmAction === 'dismiss' ? 'DISMISSED' : 'RESOLVED'} pending={pending} onClose={() => setConfirmAction(null)} onConfirm={(reason) => { onAction(alert, confirmAction, reason); setConfirmAction(null); }} />}
  </div>;
}

export default memo(AlertCard);
