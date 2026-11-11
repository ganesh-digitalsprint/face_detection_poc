import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Camera } from 'lucide-react';
import { alertSourceLink, alertSourceLabel, evidenceLabel, grillAlertMetadata, grillSnapshotRefs, useCaseLabel } from '../../api/alertServiceModel.js';
import { getGrillGateSnapshot } from '../../use-cases/grill-gate/api/grillGate.js';
import { loadSnapshot } from './snapshotResource.js';

export const alertDate = (value) => value ? new Date(value).toLocaleString() : 'Time unavailable';
const tone = { CRITICAL: 'bg-red-100 text-red-800', HIGH: 'bg-red-100 text-red-800', WARNING: 'bg-amber-100 text-amber-800', INFO: 'bg-sky-100 text-sky-800' };
export function AlertBadge({ children }) {
  return <span className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold ${tone[children] || 'bg-slate-100 text-slate-700'}`}>{children}</span>;
}

export function AlertSnapshot({ alert, large = false, evidenceIndex = 0, compact = false }) {
  const ref = grillSnapshotRefs(alert)[evidenceIndex];
  const [retry, setRetry] = useState(0);
  const key = JSON.stringify([alert.sourceEventId || alert.id, ref?.retrieval_path, alert.evidenceStatus, retry]);
  const [image, setImage] = useState({ key: '', loading: false, url: '', error: '' });
  const dialog = useRef(null);
  useEffect(() => {
    if (alert.useCase !== 'grill_gate' || !ref) return undefined;
    return loadSnapshot({ ref, fetchBlob: getGrillGateSnapshot, onChange: (next) => setImage({ ...next, key }) });
  }, [key]); // The key includes source, evidence, and capture state.
  const current = image.key === key ? image : { loading: alert.useCase === 'grill_gate' && Boolean(ref), url: '', error: '' };
  const fallback = current.loading ? 'Loading snapshot\u2026' : current.error || (alert.evidenceStatus === 'PENDING' ? 'Snapshot capture pending' : alert.evidenceStatus === 'CAPTURED' ? 'Captured snapshot reference is missing.' : 'No captured snapshot is attached to this incident.');
  // The right-side card owns the single details button; no nested image button.
  if (compact) return <span className="flex aspect-square w-full items-center justify-center overflow-hidden rounded-2xl bg-[#202530] text-[#B7BED0]">
    {current.url ? <img src={current.url} alt="Captured alert snapshot" className="h-full w-full object-cover" onError={() => setImage((old) => ({ ...old, url: '', error: 'Snapshot could not be displayed.' }))} />
      : <><Camera className="h-7 w-7" strokeWidth={1.7} aria-hidden="true" /><span className="sr-only">{fallback}</span></>}
  </span>;
  return <div className={`overflow-hidden rounded-xl ${large ? 'bg-[#18223c]' : 'bg-slate-100'}`}>
    {current.url ? <>
      <button type="button" onClick={() => dialog.current?.showModal()} className="block w-full" aria-label="Expand captured snapshot">
        <img src={current.url} onError={() => setImage((old) => ({ ...old, url: '', error: 'Snapshot could not be displayed.' }))} alt="Captured alert snapshot" className={`w-full ${large ? 'max-h-[440px] object-contain' : 'h-24 object-cover'}`} />
      </button>
      {large && <p className="px-3 py-2 text-xs text-white">Captured evidence{ref.width && ref.height ? ` - ${ref.width} x ${ref.height}` : ''} &middot; Select image to expand</p>}
      <dialog ref={dialog} className="m-auto max-h-[95vh] max-w-[95vw] rounded-xl bg-white p-3 backdrop:bg-black/70" onClick={(e) => { if (e.target === e.currentTarget) dialog.current.close(); }}>
        <button type="button" onClick={() => dialog.current.close()} className="mb-2 rounded border px-3 py-1">Close snapshot</button>
        <img src={current.url} alt="Expanded captured alert snapshot" className="max-h-[80vh] max-w-full object-contain" />
        <a download={`alert-${alert.sourceEventId || alert.id}.jpg`} href={current.url} className="mt-2 block text-sm text-indigo-700 underline">Download snapshot</a>
      </dialog>
    </> : <div role="status" className={`flex flex-col items-center justify-center gap-2 px-3 text-center text-xs ${large ? 'min-h-56 text-slate-200' : 'h-24 text-slate-500'}`}>{fallback}{current.error && <button type="button" onClick={() => setRetry((n) => n + 1)} className="underline">Retry snapshot</button>}</div>}
  </div>;
}

export function AlertCard({ alert, selected, onSelect, compact = false }) {
  return <article className={`rounded-2xl border border-l-4 bg-white p-3 ${['HIGH','CRITICAL'].includes(alert.severity) ? 'border-l-red-600' : 'border-l-amber-500'} ${selected ? 'ring-2 ring-[#34479B]' : 'border-[#E3E7F0]'}`}>
    <div className={`flex gap-3 ${compact ? '' : 'sm:gap-4'}`}>
      <div className={`shrink-0 ${compact ? 'w-[72px]' : 'w-28 sm:w-36'}`}><AlertSnapshot alert={alert} /></div>
      <button type="button" onClick={() => onSelect(alert.id)} aria-pressed={selected} className="min-w-0 flex-1 text-left">
        <div className="flex flex-wrap items-center gap-2"><AlertBadge>{alert.severity}</AlertBadge><span className="text-[11px] text-slate-500">{alert.status}</span></div>
        <h3 className="mt-1 text-sm font-bold leading-snug text-[#0F1B3D]">{alert.title || alert.sourceEventType}</h3>
        <p className="mt-1 text-xs text-[#55607A]">{useCaseLabel(alert.useCase)} &middot; {alertSourceLabel(alert)}</p>
        <p className="mt-1 text-xs text-[#55607A]">{alertDate(alert.occurredAt)}{alert.domainData?.video_time_seconds != null ? ` - Video ${alert.domainData.video_time_seconds} s` : ''}</p>
        {!compact && <p className="mt-1 text-xs text-[#69758F]">{alert.sourceEventType}{alert.zoneName ? ` - ${alert.zoneName}` : ''}{alert.sessionRef ? ` - session ${alert.sessionRef.slice(0,8)}` : ''}</p>}
        <p className="mt-1 line-clamp-2 text-xs text-[#55607A]">{alert.summary}</p>
        <span className={`mt-2 inline-block rounded px-2 py-0.5 text-[11px] ${alert.evidenceStatus === 'CAPTURED' ? 'bg-emerald-50 text-emerald-800' : 'bg-slate-100 text-slate-600'}`}>{evidenceLabel(alert)}</span>
        <span className="ml-2 text-xs font-semibold text-[#34479B]">View details &rsaquo;</span>
      </button>
    </div>
  </article>;
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
    {children}
    <Link to={`/alerts/all?use_case=grill_gate&source_event_id=${encodeURIComponent(alert.sourceEventId || '')}`} className="block text-sm font-semibold text-[#34479B]">Open Alert Center &rsaquo;</Link>
    <Link to={alertSourceLink(alert)} className="block text-sm text-[#34479B]">Open source monitoring &rsaquo;</Link>
  </section>;
}
