import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, coveringLabel, fmApiUrl, fmtTime } from '../api/index.js';
import Modal from '../../branch-exterior/components/Modal.jsx';
import { Badge, PageState } from './ui.jsx';
import usePolling from '../hooks/usePolling.js';
import { faceMaskAlertCenterLocation, faceMaskIncidentLocation } from './faceMaskAlertNavigation.js';
import { coverageLabel, coverageSeverity, coverageTitle } from '../coverageModel.js';

const NEXT = { OPEN: ['UNDER_REVIEW'], UNDER_REVIEW: ['CONFIRMED', 'FALSE_POSITIVE'], CONFIRMED: ['CLOSED'], FALSE_POSITIVE: ['CLOSED'], CLOSED: [] };
const ACTION_LABEL = { UNDER_REVIEW: 'Mark under review', CONFIRMED: 'Confirm', FALSE_POSITIVE: 'False positive', CLOSED: 'Close' };
const NEEDS_REASON = { FALSE_POSITIVE: 'Reason (why is this a false positive?)', CLOSED: 'Closing remarks' };
const missing = '—';
const sourceStatus = (status) => String(status || '').toUpperCase();

function readableReviewError(error) {
  if (error?.status === 409) return `That change is not allowed from the event's current status. ${error.message || ''}`.trim();
  return error?.message || 'The review action failed.';
}

export default function FaceMaskEventModal({ eventId, cameras = [], severity, incidentId, incidentStatus, incidentLookupError = false, onClose, onChanged }) {
  const detail = usePolling(async () => {
    const [event, evidence, actions] = await Promise.all([
      api.get(`/events/${encodeURIComponent(eventId)}`),
      api.get(`/events/${encodeURIComponent(eventId)}/evidence`),
      api.get(`/events/${encodeURIComponent(eventId)}/actions`),
    ]);
    return { event, evidence, actions };
  }, 4000, [eventId]);
  const [pending, setPending] = useState(null);
  const [reason, setReason] = useState('');
  const [reviewer, setReviewer] = useState(() => { try { return localStorage.getItem('fmReviewer') || ''; } catch { return ''; } });
  const [actionError, setActionError] = useState('');
  const [busy, setBusy] = useState(false);
  const [snapshotFailed, setSnapshotFailed] = useState(false);
  const mediaRef = useRef(null);
  useEffect(() => { setSnapshotFailed(false); }, [eventId]);

  const act = async (status, remarks = '') => {
    setBusy(true); setActionError('');
    try {
      try { localStorage.setItem('fmReviewer', reviewer); } catch { /* optional preference */ }
      await api.post(`/events/${encodeURIComponent(eventId)}/review`, { to_status: status, remarks, reviewer });
      setPending(null); setReason('');
      await detail.reload();
      onChanged?.();
    } catch (error) { setActionError(readableReviewError(error)); }
    finally { setBusy(false); }
  };

  const event = detail.data?.event;
  const evidence = detail.data?.evidence;
  const cameraName = event?.camera_name || cameras.find((camera) => camera.id === event?.camera_id)?.name || event?.camera_id;
  const snapshotUrl = evidence?.snapshot_url ? fmApiUrl(evidence.snapshot_url.replace(/^\/api/, '')) : '';
  const cropUrl = evidence?.crop_url ? fmApiUrl(evidence.crop_url.replace(/^\/api/, '')) : '';
  const clipUrl = evidence?.clip_url ? fmApiUrl(evidence.clip_url.replace(/^\/api/, '')) : '';
  const reviewStatus = sourceStatus(event?.status);
  const displaySeverity = coverageSeverity(event, severity);
  const incidentLocation = faceMaskIncidentLocation(incidentId);
  const displayIncidentStatus = incidentLocation ? incidentStatus : null;
  const fields = event ? [
    ['Camera name', cameraName], ['Camera ID', event.camera_id],
    ['Branch', event.branch_name], ['Branch code', event.branch_code],
    ['Place', event.place_name], ['Region', event.region_name],
    ['Branch manager', event.branch_manager], ['Covering type', coveringLabel(event.covering_type)],
    ['Alert type', 'FACE_CONCEALMENT'], ['Coverage', coverageLabel(event.coverage_state)], ['Severity', displaySeverity],
    ['Confidence / score', `${(event.score * 100).toFixed(1)}% / ${event.score.toFixed(2)}`], ['Track ID', event.track_id],
    ['Detection time', fmtTime(event.first_seen)], ['Trigger', null],
    ['Source event ID', event.id], ['Incident ID', incidentLocation ? incidentId : 'Not yet available in Alert Center'],
    ['Incident status', displayIncidentStatus], ['Review status', reviewStatus],
    ['Detection zone', evidence?.roi_name], ['Frames evaluated', event.frame_count],
    ['Evidence frame', evidence?.frame_id], ['Video time (seconds)', evidence?.video_timestamp_seconds],
    ['Box match IoU', evidence?.verification_iou],
  ] : [];

  return <Modal title={`Concealment event ${eventId.slice(0, 8)}`} onClose={onClose} maxWidth="min(90vw, 1120px)"
    footer={<div className="bx-row bx-gap-8 bx-wrap" style={{ justifyContent: 'space-between', width: '100%' }}>
      <div className="bx-row bx-gap-8 bx-wrap">
        {snapshotUrl && !snapshotFailed
          ? <a className="bx-btn" href={snapshotUrl} download={`face-mask-${eventId}.jpg`}>Download snapshot</a>
          : <button type="button" className="bx-btn" disabled>Download snapshot</button>}
        {incidentLocation
          ? <Link className="bx-btn bx-btn-primary" to={incidentLocation}>View in Alert Center</Link>
          : <Link className="bx-btn bx-btn-primary" to={faceMaskAlertCenterLocation}>Open Alert Center</Link>}
      </div>
      <button type="button" className="bx-btn" onClick={onClose}>Close details</button>
    </div>}>
    <PageState loading={detail.loading} error={detail.error} data={detail.data} onRetry={detail.reload}>
      {event && <>
        <div className="bx-detail-heading">
          <div><h2>{coverageTitle(event.coverage_state)}</h2><p>{cameraName || missing} · {fmtTime(event.first_seen)}</p></div>
          <div className="bx-row bx-gap-8"><span className="bx-tag">{coverageLabel(event.coverage_state)}</span><Badge kind="sev" value={(displaySeverity || 'info').toLowerCase()} text={displaySeverity || '—'} /><span className="bx-tag">Incident: {displayIncidentStatus || '—'}</span></div>
        </div>
        <section className="bx-detail-evidence" aria-label="Alert evidence">
          <div className="bx-detail-tabs"><span className="bx-tag">Snapshot</span>
            <button type="button" className="bx-btn bx-btn-sm" disabled={!snapshotUrl || snapshotFailed}
              onClick={() => mediaRef.current?.requestFullscreen?.().catch(() => {})}>Expand</button>
          </div>
          <div ref={mediaRef} className="bx-detail-media">
            {snapshotUrl && !snapshotFailed
              ? <img src={snapshotUrl} alt="Captured concealment event snapshot" onError={() => setSnapshotFailed(true)} />
              : <p role="status">{snapshotFailed ? 'Snapshot is unavailable.' : 'No snapshot is available for this event.'}</p>}
          </div>
          {cropUrl && <div className="bx-detail-media" style={{ marginTop: 12, maxWidth: 400 }}>
            <img src={cropUrl} alt="Head and shoulders crop from the evidence frame" />
          </div>}
          {evidence?.verification === 'unverified' && <div className="bx-hint" role="alert">
            Evidence unverified: the saved box did not match a fresh person detection. Review this snapshot carefully.
          </div>}
          <div className="bx-row bx-gap-8 bx-wrap bx-detail-downloads">
            {clipUrl && <a className="bx-btn" href={clipUrl} download={`face-mask-${event.id}.${evidence?.clip_format || 'mp4'}`}>Download clip</a>}
          </div>
          {clipUrl ? <video controls preload="metadata" className="mt-3 max-h-[420px] w-full rounded-lg bg-black" src={clipUrl}>
            Video evidence is unavailable in this browser.
          </video> : <div className="bx-hint" role="status">Clip: <b>{evidence.clip_status}</b>
            {evidence.clip_status === 'pending' && ' — it is still being recorded.'}
            {evidence.clip_status === 'failed' && ` — ${evidence.clip_error || 'clip is unavailable'}. The snapshot is kept.`}
            {!['pending', 'failed'].includes(evidence.clip_status) && ' — no clip is available.'}
          </div>}
        </section>

        <h3 className="bx-detail-section-title">Alert details</h3>
        <dl className="bx-event-details">{fields.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value ?? missing}</dd></div>)}</dl>

        <div className="bx-hint" role="status" style={{ marginTop: 12 }}>
          {incidentLocation ? 'Published in Alert Center.' : 'Not yet available in Alert Center.'}
          {!incidentLocation && incidentLookupError && ' Publication status could not be checked.'}
        </div>

        <section className="bx-card" style={{ marginTop: 16 }} aria-label="Review actions">
          <div className="bx-card-title">Review</div>
          {actionError && <div className="bx-diag" role="alert">{actionError}</div>}
          <label className="bx-field">Your name (for the audit trail)
            <input className="bx-input" value={reviewer} onChange={(change) => setReviewer(change.target.value)} maxLength={120} autoComplete="off" />
          </label>
          {NEXT[reviewStatus]?.length === 0 && <div className="bx-hint">This event is closed.</div>}
          {!pending && <div className="bx-row bx-gap-8 bx-wrap">{(NEXT[reviewStatus] || []).map((status) => <button key={status} type="button"
            className={`bx-btn bx-btn-sm${status === 'CONFIRMED' ? ' bx-btn-primary' : ''}`} disabled={busy}
            onClick={() => NEEDS_REASON[status] ? setPending(status) : act(status)}>{ACTION_LABEL[status]}</button>)}</div>}
          {pending && <>
            <label className="bx-field">{NEEDS_REASON[pending]}<textarea className="bx-input" rows={3} value={reason} onChange={(change) => setReason(change.target.value)} /></label>
            <div className="bx-row bx-gap-8"><button type="button" className="bx-btn bx-btn-sm bx-btn-primary" disabled={busy || !reason.trim()}
              onClick={() => act(pending, reason)}>{ACTION_LABEL[pending]}</button>
              <button type="button" className="bx-btn bx-btn-sm" onClick={() => { setPending(null); setReason(''); }}>Cancel</button></div>
          </>}
          <div className="bx-card-title" style={{ marginTop: 14 }}>History</div>
          {detail.data.actions.length === 0 && <div className="bx-muted" style={{ fontSize: 13 }}>No review actions yet.</div>}
          {detail.data.actions.map((action) => <div key={action.id} style={{ fontSize: 12, padding: '4px 0', borderBottom: '1px solid var(--bx-hair)'}}>
            {fmtTime(action.created_at)} · {action.from_status.replace('_', ' ')} → <b>{action.to_status.replace('_', ' ')}</b>{action.actor ? ` · ${action.actor}` : ''}{action.remarks ? ` · “${action.remarks}”` : ''}
          </div>)}
        </section>
      </>}
    </PageState>
  </Modal>;
}
