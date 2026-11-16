import { useEffect, useState } from 'react';
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

  useEffect(() => {
    let active = true;
    setEvent(initialEvent?.id === id ? initialEvent : null);
    setRemarks(initialEvent?.id === id ? initialEvent.reviewer_remarks || '' : '');
    setError(''); setSnapshotFailed(false); setClipFailed(false); setSnapshotReady(false); setClipReady(false);
    api.get(`/events/${encodeURIComponent(id)}`).then((row) => {
      if (active) { setEvent(row); setRemarks(row.reviewer_remarks || ''); }
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
  const detailFields = [
    ['Camera name', event.camera_name || meta.camera_name], ['Camera ID', event.camera_id || meta.camera_id],
    ['Branch', meta.branch_name], ['Branch code', meta.branch_code], ['Place', meta.place_name],
    ['Region', meta.region_name], ['Branch manager', meta.branch_manager], ['Detection zone', event.zone_name],
    ['Alert type', event.scenario], ['Severity', event.severity],
    ['Confidence', Number.isFinite(event.confidence) ? `${(event.confidence * 100).toFixed(1)}%` : null],
    ['Track ID', (event.track_ids || []).join(', ') || null], ['Detection time', event.created_at ? fmtTime(event.created_at) : null],
    ['Trigger', event.message], ['Incident status', incident?.status || 'Not published to Common Alerts'],
    ['Review status', event.status],
  ];

  return <Modal title={`${event.camera_name || 'Camera'} — ${event.scenario || 'Incident'}`} onClose={onClose}
    footer={<>
      <a className="bx-btn" href={bxApiUrl(`/events/${event.id}/report`)} target="_blank" rel="noreferrer">Incident report</a>
      <button type="button" className="bx-btn" onClick={() => review('false_positive')}>Mark false positive</button>
      <button type="button" className="bx-btn bx-btn-danger" onClick={() => review('confirmed')}>Confirm incident</button>
      <button type="button" className="bx-btn bx-btn-primary" onClick={() => review('closed')}>Close event</button>
    </>}>
    <div className="bx-row bx-gap-8 bx-wrap" style={{ marginBottom: 10 }}>
      <span className={`bx-badge sev-${event.severity}`}>{event.severity}</span>
      <span className="bx-tag">Incident: {incident?.status || 'Not published'}</span>
      <span className={`bx-badge status-${event.status}`}>Review: {event.status?.replace('_', ' ')}</span>
      {event.created_at && <span className="bx-tag">{fmtTime(event.created_at)}</span>}
    </div>
    {hasSnapshot && <img src={bxStorageUrl(event.snapshot_path)} alt="Captured incident snapshot" onLoad={() => setSnapshotReady(true)} onError={() => setSnapshotFailed(true)} style={{ width: '100%', borderRadius: 8, border: '1px solid var(--bx-border-soft)', margin: '8px 0' }} />}
    {snapshotFailed && <p className="bx-muted" role="status">Snapshot is unavailable.</p>}
    {hasClip && <video src={bxStorageUrl(event.clip_path)} controls={clipReady} preload="metadata" onLoadedMetadata={() => setClipReady(true)} onError={() => setClipFailed(true)} style={{ width: '100%', borderRadius: 8, border: '1px solid var(--bx-border-soft)' }} />}
    {hasClip && !clipReady && !clipFailed && <p className="bx-muted" role="status">Checking video clip…</p>}
    {clipFailed && <p className="bx-muted" role="status">Video clip is unavailable.</p>}
    {!hasSnapshot && !hasClip && <p className="bx-muted" style={{ fontSize: 12 }}>{evidenceNotice(meta)}</p>}
    <div className="bx-row bx-gap-8 bx-wrap" style={{ margin: '10px 0' }}>
      {hasSnapshot && snapshotReady ? <a className="bx-btn" href={bxStorageUrl(event.snapshot_path)} download>Download snapshot</a> : <button type="button" className="bx-btn" disabled>Download snapshot</button>}
      {hasClip && clipReady ? <a className="bx-btn" href={bxStorageUrl(event.clip_path)} download>Download clip</a> : <button type="button" className="bx-btn" disabled>Download clip</button>}
    </div>
    <dl className="bx-event-details">{detailFields.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || missing}</dd></div>)}</dl>
    <label className="bx-field" style={{ marginTop: 10 }}>Reviewer remarks
      <textarea className="bx-input" rows={2} value={remarks} onChange={(change) => setRemarks(change.target.value)} placeholder="Add review remarks" />
    </label>
  </Modal>;
}
