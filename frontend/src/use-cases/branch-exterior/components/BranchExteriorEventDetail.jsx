import { useEffect, useRef, useState } from 'react';
import { api, bxApiUrl, bxStorageUrl, fmtTime } from '../api/index.js';
import Modal from './Modal.jsx';

const missing = '—';

function evidenceNotice(meta = {}) {
  const state = String(meta.evidence || '');
  if (state === 'not_saved:not_suspicious') return 'No snapshot was captured because this incident did not meet the evidence severity policy.';
  if (state.startsWith('not_saved:cooldown')) return 'No snapshot was captured because the evidence cooldown is active.';
  if (state.startsWith('not_saved:daily_cap_reached')) return 'No snapshot was captured because the daily evidence limit was reached.';
  if (state.startsWith('not_saved:storage_cap_reached')) return 'No snapshot was captured because the evidence storage limit was reached.';
  if (state.startsWith('failed:')) return 'Evidence capture failed; the incident was saved.';
  return 'No snapshot or clip is attached to this incident.';
}

export default function BranchExteriorEventDetail({ id, incident, initialEvent, onClose, onReviewed }) {
  const [event, setEvent] = useState(initialEvent?.id === id ? initialEvent : null);
  const [remarks, setRemarks] = useState(initialEvent?.id === id ? initialEvent.reviewer_remarks || '' : '');
  const [error, setError] = useState('');
  const [snapshotFailed, setSnapshotFailed] = useState(false);
  const [clipFailed, setClipFailed] = useState(false);
  const [snapshotReady, setSnapshotReady] = useState(false);
  const [clipReady, setClipReady] = useState(false);
  const [evidenceTab, setEvidenceTab] = useState(() => initialEvent?.id === id && !initialEvent.snapshot_path && initialEvent.clip_path ? 'clip' : 'snapshot');
  const mediaRef = useRef(null);

  useEffect(() => {
    let active = true;
    setEvent(initialEvent?.id === id ? initialEvent : null);
    setRemarks(initialEvent?.id === id ? initialEvent.reviewer_remarks || '' : '');
    setError(''); setSnapshotFailed(false); setClipFailed(false); setSnapshotReady(false); setClipReady(false);
    setEvidenceTab(initialEvent?.id === id && !initialEvent.snapshot_path && initialEvent.clip_path ? 'clip' : 'snapshot');
    api.get(`/events/${encodeURIComponent(id)}`).then((row) => {
      if (active) {
        setEvent(row); setRemarks(row.reviewer_remarks || '');
        if (!row.snapshot_path && row.clip_path) setEvidenceTab('clip');
      }
    }).catch((cause) => { if (active) setError(cause.message); });
    return () => { active = false; };
  }, [id, initialEvent]);

  if (error) return <Modal title="Event" onClose={onClose}><div className="bx-diag" role="alert">{error}</div></Modal>;
  if (!event) return <Modal title="Event" onClose={onClose}><div className="bx-row bx-gap-8 bx-muted"><span className="bx-spinner" /> Loading…</div></Modal>;

  const review = async (status) => {
    try { await api.post(`/events/${event.id}/review`, { status, reviewer_remarks: remarks }); }
    catch (cause) { alert(cause.message); return; }
    onReviewed?.();
  };
  const meta = event.meta || {};
  const hasSnapshot = Boolean(event.snapshot_path) && !snapshotFailed;
  const hasClip = Boolean(event.clip_path) && !clipFailed;
  const severity = String(event.severity || 'info').toLowerCase();
  const evidencePath = evidenceTab === 'clip' ? event.clip_path : event.snapshot_path;
  const evidenceFailed = evidenceTab === 'clip' ? clipFailed : snapshotFailed;
  const evidenceReady = evidenceTab === 'clip' ? clipReady : snapshotReady;
  const hasEvidence = evidenceTab === 'clip' ? hasClip : hasSnapshot;
  const onEvidenceTabKeyDown = (change) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(change.key)) return;
    change.preventDefault();
    const tabs = [...(change.currentTarget.parentElement?.querySelectorAll('[role="tab"]') || [])];
    const activeIndex = tabs.indexOf(change.currentTarget);
    const nextIndex = change.key === 'Home' ? 0 : change.key === 'End' ? tabs.length - 1
      : (activeIndex + (change.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length;
    tabs[nextIndex]?.focus();
    tabs[nextIndex]?.click();
  };
  const detailFields = [
    ['Camera name', event.camera_name || meta.camera_name], ['Camera ID', event.camera_id || meta.camera_id],
    ['Branch', meta.branch_name], ['Branch code', meta.branch_code], ['Place', meta.place_name],
    ['Region', meta.region_name], ['Branch manager', meta.branch_manager], ['Detection zone', event.zone_name],
    ['Alert type', event.scenario], ['Severity', event.severity],
    ['Confidence', Number.isFinite(event.confidence) ? `${(event.confidence * 100).toFixed(1)}%` : null],
    ['Track ID', (event.track_ids || (event.track_id != null ? [event.track_id] : [])).join(', ') || null], ['Detection time', event.created_at ? fmtTime(event.created_at) : null],
    ['Trigger', event.message], ['Source event ID', event.id], ['Incident ID', incident?.id], ['Incident status', incident?.status || 'Not published to Common Alerts'],
    ['Review status', event.status],
  ];

  return <Modal title={event.scenario || 'Monitoring alert'} onClose={onClose} maxWidth={900}
    footer={<>
      <a className="bx-btn" href={bxApiUrl(`/events/${event.id}/report`)} target="_blank" rel="noreferrer">Incident report</a>
      <button type="button" className="bx-btn" onClick={() => review('under_review')}>Acknowledge</button>
      <button type="button" className="bx-btn bx-btn-primary" onClick={() => review('closed')}>Resolve</button>
      <button type="button" className="bx-btn bx-btn-danger" onClick={() => review('false_positive')}>Discard</button>
    </>}>
    <div className="bx-detail-heading">
      <div><h2>{event.message || event.scenario || 'Monitoring alert'}</h2><p>{event.camera_name || meta.camera_name || 'Camera'}{event.created_at ? ` · ${fmtTime(event.created_at)}` : ''}</p></div>
      <div className="bx-row bx-gap-8 bx-wrap"><span className={`bx-badge sev-${severity}`}>{severity.toUpperCase()}</span><span className="bx-tag">Incident: {incident?.status || 'Not published'}</span></div>
    </div>
    <section className="bx-detail-evidence" aria-label="Alert evidence">
      <div className="bx-detail-tabs" role="tablist" aria-label="Evidence type">
        <button type="button" role="tab" tabIndex={evidenceTab === 'snapshot' ? 0 : -1} aria-selected={evidenceTab === 'snapshot'} onKeyDown={onEvidenceTabKeyDown} onClick={() => setEvidenceTab('snapshot')}>Snapshot</button>
        {event.clip_path && <button type="button" role="tab" tabIndex={evidenceTab === 'clip' ? 0 : -1} aria-selected={evidenceTab === 'clip'} onKeyDown={onEvidenceTabKeyDown} onClick={() => setEvidenceTab('clip')}>Video clip</button>}
        <button type="button" className="bx-btn bx-btn-sm" disabled={!hasEvidence || !evidenceReady} onClick={() => mediaRef.current?.requestFullscreen?.()}>Fullscreen</button>
      </div>
      <div ref={mediaRef} className="bx-detail-media">
        {hasEvidence && evidenceTab === 'snapshot' && <img src={bxStorageUrl(evidencePath)} alt="Captured incident snapshot" onLoad={() => setSnapshotReady(true)} onError={() => setSnapshotFailed(true)} />}
        {hasEvidence && evidenceTab === 'clip' && <video src={bxStorageUrl(evidencePath)} controls={clipReady} preload="metadata" onLoadedMetadata={() => setClipReady(true)} onError={() => setClipFailed(true)} />}
        {evidenceFailed && <p role="status">{evidenceTab === 'clip' ? 'Video clip is unavailable.' : 'Snapshot is unavailable.'}</p>}
        {hasEvidence && !evidenceReady && <p role="status">Checking {evidenceTab === 'clip' ? 'video clip' : 'snapshot'}…</p>}
        {!hasEvidence && !evidenceFailed && <p role="status">{evidencePath ? 'Checking evidence…' : evidenceNotice(meta)}</p>}
      </div>
      <div className="bx-row bx-gap-8 bx-wrap bx-detail-downloads">
        {hasSnapshot && snapshotReady ? <a className="bx-btn" href={bxStorageUrl(event.snapshot_path)} download>Download snapshot</a> : <button type="button" className="bx-btn" disabled>Download snapshot</button>}
        {hasClip && clipReady ? <a className="bx-btn" href={bxStorageUrl(event.clip_path)} download>Download clip</a> : <button type="button" className="bx-btn" disabled>Download clip</button>}
      </div>
    </section>
    <h3 className="bx-detail-section-title">Alert details</h3>
    <dl className="bx-event-details">{detailFields.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || missing}</dd></div>)}</dl>
    <label className="bx-field" style={{ marginTop: 12 }}>Reviewer remarks
      <textarea className="bx-input" rows={2} value={remarks} onChange={(change) => setRemarks(change.target.value)} placeholder="Add review remarks" />
    </label>
  </Modal>;
}
