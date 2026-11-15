import { useEffect, useRef, useState } from 'react';
import { Download, Maximize } from 'lucide-react';
import { AlertEvidenceDetails, AlertSnapshot } from './AlertPresentation.jsx';
import LifecycleConfirmation from './LifecycleConfirmation.jsx';
import { alertDetailLocationFields, availableActions, snapshotRefs, useCaseLabel } from '../../api/alertServiceModel.js';
import '../../pages/CommonAlertDetail.css';

const missing = '—';
const formatTime = (value) => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString() : missing;
const actionLabels = { ACKNOWLEDGED: 'Acknowledge', RESOLVED: 'Resolve', DISMISSED: 'Discard' };

export default function CommonAlertDetail({ alert, audit, actionsEnabled, pending, notice, onAction, onClose }) {
  const [note, setNote] = useState('');
  const [confirmTarget, setConfirmTarget] = useState(null);
  const [snapshotIndex, setSnapshotIndex] = useState(0);
  const viewer = useRef(null);
  useEffect(() => { setNote(''); setConfirmTarget(null); setSnapshotIndex(0); }, [alert.id]);
  const actions = availableActions(alert, actionsEnabled);
  const refs = alert.resourceRefs || {};
  const domain = alert.domainData || {};
  const snapshots = snapshotRefs(alert);
  const identifier = domain.alert_number || domain.incident_number || alert.id;
  const comments = (audit.rows || []).filter((row) => typeof row.details?.note === 'string' && row.details.note.trim());
  const extraComment = alert.acknowledgementComment && !comments.some((row) => row.details.note === alert.acknowledgementComment);
  const videoTime = domain.video_time_seconds ?? domain.video_timestamp_seconds;
  const duration = domain.gate_open_duration_seconds ?? domain.observed_duration_seconds;
  const threshold = domain.configured_threshold_seconds ?? domain.threshold_seconds;
  const fields = [
    ...alertDetailLocationFields(alert),
    ['Use case', useCaseLabel(alert.useCase)],
    ['Detected time', formatTime(alert.occurredAt)],
    ['Video time', Number.isFinite(videoTime) ? `${videoTime.toFixed(1)} s` : null],
    ['Trigger', Number.isFinite(duration) ? `Open ${duration} s${Number.isFinite(threshold) ? ` / threshold ${threshold} s` : ''}` : alert.summary],
    ['Alert ID', identifier],
  ];
  const connection = domain.camera_connection_status || refs.camera_connection_status;
  return <div className="common-detail-page">
    <header className="common-detail-header">
      <div className="common-detail-badges">
        <span className={`detail-severity severity-${alert.severity?.toLowerCase()}`}>{alert.severity}</span>
        <span className="detail-status">{alert.status}</span>
      </div>
      <h1>{alert.title || alert.sourceEventType}</h1>
      <p>Detected {formatTime(alert.occurredAt)} · {alert.branchName || missing} · {alert.cameraName || missing}</p>
      {connection && <span className="detail-connection">{String(connection)}</span>}
    </header>
    <div className="common-detail-columns">
      <div className="common-detail-left">
        <section className="detail-card detail-evidence" aria-label="Alert evidence">
          <div className="detail-card-heading"><h2>Evidence</h2><div className="detail-evidence-tabs" role="tablist" aria-label="Evidence format">
            <button type="button" role="tab" aria-selected="false" disabled title="Video playback is planned for a later stage">Video clip</button>
            <button type="button" role="tab" aria-selected="true">Snapshots</button>
          </div></div>
          <div ref={viewer} className="detail-viewer"><AlertEvidenceDetails alert={alert} evidenceIndex={snapshotIndex} onEvidenceIndexChange={setSnapshotIndex} /></div>
          {snapshots.length > 0 && <><p className="detail-small">Snapshots</p><div className="detail-thumbnail-strip">{snapshots.map((ref, index) => <button type="button" key={ref.id || index} onClick={() => setSnapshotIndex(index)} aria-label={`View snapshot ${index + 1}`} aria-pressed={snapshotIndex === index}>
            <AlertSnapshot alert={alert} compact evidenceIndex={index} /><span>Snapshot {index + 1}</span>
          </button>)}</div></>}
          <div className="detail-evidence-tools">
            <button type="button" disabled title="Clip downloads are planned for a later stage"><Download size={14} />Download clip</button>
            <button type="button" disabled title="Snapshot downloads are planned for a later stage"><Download size={14} />Download snapshots</button>
            <button type="button" disabled={!snapshots.length || typeof document === 'undefined' || !document.fullscreenEnabled} onClick={() => viewer.current?.requestFullscreen?.().catch(() => {})}><Maximize size={14} />Fullscreen</button>
          </div>
        </section>
        <section className="detail-card detail-comments" aria-label="Alert comments">
          <h2>Comments <span>{comments.length + (extraComment ? 1 : 0)}</span></h2>
          <textarea aria-label="Add a comment" placeholder="Add a comment…" rows={3} disabled />
          <div className="detail-comment-submit"><p>Comment posting is not available yet.</p><button type="button" disabled>Post comment</button></div>
          {audit.loading && <p role="status">Loading comments…</p>}
          {audit.error && <p role="alert">{audit.error}</p>}
          {!audit.loading && !audit.error && !comments.length && !extraComment && <p className="detail-small">No comments yet.</p>}
          {comments.map((row) => <article className="detail-comment" key={row.id}><span className="detail-avatar" aria-hidden>{(row.actor_id || '?').slice(0, 2).toUpperCase()}</span><div><p><strong>{row.actor_id || missing}</strong><time>{formatTime(row.created_at)}</time></p><p>{row.details.note}</p></div></article>)}
          {extraComment && <article className="detail-comment"><div><strong>{alert.acknowledgedBy || missing}</strong><time>{formatTime(alert.acknowledgedAt)}</time><p>{alert.acknowledgementComment}</p></div></article>}
          <details className="detail-audit"><summary>Audit history</summary>{(audit.rows || []).map((row) => <p key={row.id}>{row.action} · {row.actor_id || missing} · {formatTime(row.created_at)}</p>)}</details>
        </section>
      </div>
      <div className="common-detail-right">
        <section className="detail-card" aria-label="Alert details"><h2>Alert details</h2><dl className="detail-fields">{fields.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || missing}</dd></div>)}</dl>
          <details className="detail-audit"><summary>Source references</summary><p>Source event {alert.sourceEventId || missing}</p><p>Camera ID {alert.cameraId || missing}</p><p>Session {alert.sessionRef || missing}</p><p>Video job {alert.videoJobId || missing}</p><p>Occurred {formatTime(alert.occurredAt)}</p></details>
        </section>
        <section className="detail-card detail-actions" aria-label="Alert actions"><h2>Actions</h2>
          {Object.entries(actionLabels).map(([target, label]) => {
            const enabled = actions.some((action) => action.target === target) && typeof onAction === 'function';
            return <button key={target} type="button" data-action={target} disabled={!enabled || pending} title={!enabled ? 'Unavailable for this alert or current permissions' : undefined} onClick={() => target === 'ACKNOWLEDGED' && alert.useCase !== 'grill_gate' ? onAction(alert, target, note) : setConfirmTarget(target)}>{label}</button>;
          })}
          {actions.length > 0 && alert.useCase !== 'grill_gate' && <textarea aria-label="Action comment" value={note} onChange={(event) => setNote(event.target.value)} placeholder="Comment for the alert action" maxLength={500} rows={2} />}
          <p className="detail-small">Resolve and Discard require a comment. Discard keeps the alert in History as a false alarm.</p>
          {!actions.length && <p className="detail-small">Actions are unavailable for this alert or current permissions.</p>}
          {alert.resolutionNote && <p>Resolution comment · {alert.resolutionNote}</p>}
          {notice && <p role="status">{notice}</p>}
        </section>
      </div>
    </div>
    {confirmTarget && <LifecycleConfirmation target={confirmTarget} initialReason={note} pending={pending} onClose={() => setConfirmTarget(null)} onConfirm={(reason) => { onAction(alert, confirmTarget, reason); setConfirmTarget(null); }} />}
  </div>;
}
