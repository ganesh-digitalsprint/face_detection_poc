import CompactAlertCard from './CompactAlertCard.jsx';
import AlertSnapshot from './AlertSnapshot.jsx';
export { default as AlertSnapshot } from './AlertSnapshot.jsx';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { alertSourceLink, alertSourceLabel, evidenceLabel, grillAlertMetadata, grillSnapshotRefs, useCaseLabel } from '../../api/alertServiceModel.js';

export const alertDate = (value) => value ? new Date(value).toLocaleString() : 'Time unavailable';
const tone = { CRITICAL: 'bg-red-100 text-red-800', HIGH: 'bg-red-100 text-red-800', WARNING: 'bg-amber-100 text-amber-800', INFO: 'bg-sky-100 text-sky-800' };
export function AlertBadge({ children }) {
  return <span className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold ${tone[children] || 'bg-slate-100 text-slate-700'}`}>{children}</span>;
}

export function AlertCard({ alert, selected, onSelect }) {
  return <CompactAlertCard alert={alert} selected={selected} onSelect={onSelect} />;
}

export function AlertEvidenceDetails({ alert }) {
  const [index, setIndex] = useState(0);
  useEffect(() => setIndex(0), [alert.id, alert.evidenceRefs?.length]);
  const metadata = grillAlertMetadata(alert);
  const snapshots = grillSnapshotRefs(alert);
  return <>
    <AlertSnapshot alert={alert} large evidenceIndex={index} />
    {snapshots.length > 1 && <div className="flex flex-wrap gap-2">{snapshots.map((ref, i) => <button type="button" key={ref.id || i} onClick={() => setIndex(i)} aria-pressed={index === i} className="rounded border px-3 py-2 text-xs">Snapshot {i + 1}</button>)}</div>}
    {snapshots[index]?.captured_at && <p className="text-xs text-[#55607A]">Snapshot captured at {alertDate(snapshots[index].captured_at)}</p>}
    {metadata.length > 0 && <dl className="grid grid-cols-2 gap-3 border-t border-[#E3E7F0] pt-3 text-xs sm:grid-cols-3">{metadata.map(([label,value]) => <div key={label}><dt className="text-[#69758F]">{label}</dt><dd className="mt-1 font-bold text-[#0F1B3D]">{String(value)}{['Observed duration','Threshold'].includes(label) ? ' s' : ''}</dd></div>)}</dl>}
  </>;
}

export function SourceAlertDetail({ alert, onClose, children }) {
  return <section className="vault-card space-y-4 p-4 sm:p-5" aria-label="Alert details">
    <div className="flex items-start justify-between gap-2"><div><AlertBadge>{alert.severity}</AlertBadge><h2 className="mt-1 text-lg font-bold text-[#0F1B3D]">{alert.title || alert.sourceEventType}</h2></div><button onClick={onClose} type="button" className="text-sm text-[#55607A]">Close</button></div>
    <p className="text-sm text-[#55607A]">{useCaseLabel(alert.useCase)} &middot; {alertSourceLabel(alert)} &middot; {alert.status}</p>
    <p className="text-sm text-[#55607A]">{alert.summary}</p>
    <AlertEvidenceDetails alert={alert} />
    <dl className="grid grid-cols-2 gap-3 text-xs"><div><dt>Occurred</dt><dd>{alertDate(alert.occurredAt)}</dd></div><div><dt>Alert type</dt><dd>{alert.sourceEventType}</dd></div><div><dt>Alert ID</dt><dd className="break-all">{alert.id}</dd></div><div><dt>Source event ID</dt><dd className="break-all">{alert.sourceEventId}</dd></div></dl>
    {alert.acknowledgementComment && <p className="text-sm text-slate-700">Acknowledgement comment: {alert.acknowledgementComment}</p>}
    {alert.acknowledgedAt && <p className="text-xs text-slate-500">Acknowledged: {alertDate(alert.acknowledgedAt)} ? {alert.acknowledgedBy}</p>}
    {alert.resolvedAt && <p className="text-xs text-slate-500">Resolved: {alertDate(alert.resolvedAt)} ? {alert.resolvedBy}</p>}
    {alert.dismissedAt && <p className="text-xs text-slate-500">Discarded: {alertDate(alert.dismissedAt)} ? {alert.dismissedBy}</p>}
    {alert.resolutionNote && <p className="text-sm text-slate-700">Reason: {alert.resolutionNote}</p>}
    {children}
    <Link to={`/alerts/all?use_case=grill_gate&source_event_id=${encodeURIComponent(alert.sourceEventId || '')}`} className="block text-sm font-semibold text-[#34479B]">Open Alert Center &rsaquo;</Link>
    <Link to={alertSourceLink(alert)} className="block text-sm text-[#34479B]">Open source monitoring &rsaquo;</Link>
  </section>;
}
