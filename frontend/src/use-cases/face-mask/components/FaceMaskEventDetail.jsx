import { useState } from 'react';
import { api, coveringLabel, fmApiUrl, fmtTime } from '../api/index.js';
import { EventStatusBadge, PageState } from './ui.jsx';
import usePolling from '../hooks/usePolling.js';

// Which review actions the workflow allows from each status (the server enforces the same table).
const NEXT = { OPEN: ['UNDER_REVIEW'], UNDER_REVIEW: ['CONFIRMED', 'FALSE_POSITIVE'], CONFIRMED: ['CLOSED'], FALSE_POSITIVE: ['CLOSED'], CLOSED: [] };
const ACTION_LABEL = { UNDER_REVIEW: 'Mark under review', CONFIRMED: 'Confirm', FALSE_POSITIVE: 'False positive', CLOSED: 'Close' };
const NEEDS_REASON = { FALSE_POSITIVE: 'Reason (why is this a false positive?)', CLOSED: 'Closing remarks' };

/** 409 from an invalid transition arrives as the server's sentence; make a missing one readable. */
function readableReviewError(e) {
  if (e?.status === 409) return `That change is not allowed from the event's current status. ${e.message || ''}`.trim();
  return e?.message || 'The review action failed.';
}

export default function FaceMaskEventDetail({ eventId, cameras, onClose, onChanged }) {
  const ev = usePolling(async () => {
    const [event, evidence, actions] = await Promise.all([
      api.get(`/events/${eventId}`), api.get(`/events/${eventId}/evidence`), api.get(`/events/${eventId}/actions`)]);
    return { event, evidence, actions };
  }, 4000, [eventId]);
  const [pending, setPending] = useState(null);       // review action waiting for its reason
  const [reason, setReason] = useState('');
  const [reviewer, setReviewer] = useState(() => { try { return localStorage.getItem('fmReviewer') || ''; } catch { return ''; } });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const act = async (status, remarks) => {
    setBusy(true); setError('');
    try {
      try { localStorage.setItem('fmReviewer', reviewer); } catch { /* ignore */ }
      await api.post(`/events/${eventId}/review`, { to_status: status, remarks: remarks || '', reviewer });
      setPending(null); setReason('');
      await ev.reload(); onChanged();
    } catch (e) { setError(readableReviewError(e)); } finally { setBusy(false); }
  };

  const data = ev.data;
  const e = data?.event;
  const evidence = data?.evidence;
  const cameraName = cameras.find((c) => c.id === e?.camera_id)?.name || evidence?.camera_name || e?.camera_id;

  return (
    <aside className="bx-card" aria-label={`Concealment event ${eventId.slice(0, 8)}`}>
      <div className="bx-row" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
        <div className="bx-card-title" style={{ margin: 0 }}>Concealment event {eventId.slice(0, 8)}</div>
        <button type="button" className="bx-btn bx-btn-sm" onClick={onClose} aria-label="Close details">Close</button>
      </div>
      <PageState loading={ev.loading} error={ev.error} data={data} onRetry={ev.reload}>
        {e && (
          <div className="bx-two-col" style={{ gridTemplateColumns: '1fr' }}>
            <div>
              <div className="bx-card-title">Evidence</div>
              {evidence.snapshot_url
                ? <img src={fmApiUrl(evidence.snapshot_url.replace(/^\/api/, ''))} alt="Best head frame with the head box" style={{ width: '100%', borderRadius: 6, background: '#000' }} />
                : <div className="bx-hint">The snapshot is not available (yet).</div>}
              <div style={{ marginTop: 10 }}>
                {evidence.clip_url ? (
                  // eslint-disable-next-line jsx-a11y/media-has-caption
                  <video controls preload="metadata" style={{ width: '100%', borderRadius: 6, background: '#000' }} src={fmApiUrl(evidence.clip_url.replace(/^\/api/, ''))} />
                ) : (
                  <div className="bx-hint" role="status">
                    Clip: <b>{evidence.clip_status}</b>
                    {evidence.clip_status === 'pending' && ' - it is still being recorded (a few seconds after the event).'}
                    {evidence.clip_status === 'failed' && ` - ${evidence.clip_error || 'it could not be written'}. The snapshot is kept.`}
                  </div>
                )}
              </div>
            </div>
            <div>
              <div className="bx-card-title">Details</div>
              <table className="bx-table">
                <tbody>
                  {[
                    ['Status', <EventStatusBadge key="s" status={e.status} />],
                    ['Camera', cameraName], ['Entry ROI', evidence.roi_name || '-'], ['Track ID', `#${e.track_id}`],
                    ['First seen', fmtTime(e.first_seen)], ['Last seen', fmtTime(e.last_seen)],
                    ['Score', e.score.toFixed(2)], ['Covering', coveringLabel(e.covering_type)], ['Frames evaluated', e.frame_count],
                    ['Reviewer', e.reviewer || '-'], ['Remarks', e.remarks || '-'],
                  ].map(([k, v]) => <tr key={k}><td className="bx-muted">{k}</td><td>{v}</td></tr>)}
                </tbody>
              </table>

              <div className="bx-card-title" style={{ marginTop: 14 }}>Review</div>
              {error && <div className="bx-diag" role="alert">{error}</div>}
              <label className="bx-field">Your name (for the audit trail)
                <input className="bx-input" value={reviewer} onChange={(x) => setReviewer(x.target.value)} maxLength={120} autoComplete="off" />
              </label>
              {NEXT[e.status].length === 0 && <div className="bx-hint">This event is closed.</div>}
              {!pending && (
                <div className="bx-row bx-gap-8 bx-wrap">
                  {NEXT[e.status].map((s) => (
                    <button key={s} type="button" className={`bx-btn bx-btn-sm${s === 'CONFIRMED' ? ' bx-btn-primary' : ''}`} disabled={busy}
                      onClick={() => (NEEDS_REASON[s] ? setPending(s) : act(s))}>{ACTION_LABEL[s]}</button>
                  ))}
                </div>
              )}
              {pending && (
                <div>
                  <label className="bx-field">{NEEDS_REASON[pending]}
                    <textarea className="bx-input" rows={3} value={reason} onChange={(x) => setReason(x.target.value)} />
                  </label>
                  <div className="bx-row bx-gap-8">
                    <button type="button" className="bx-btn bx-btn-sm bx-btn-primary" disabled={busy || !reason.trim()} onClick={() => act(pending, reason)}>{ACTION_LABEL[pending]}</button>
                    <button type="button" className="bx-btn bx-btn-sm" onClick={() => { setPending(null); setReason(''); }}>Cancel</button>
                  </div>
                </div>
              )}

              <div className="bx-card-title" style={{ marginTop: 14 }}>History</div>
              {data.actions.length === 0 && <div className="bx-muted" style={{ fontSize: 13 }}>No review actions yet.</div>}
              {data.actions.map((a) => (
                <div key={a.id} style={{ fontSize: 12, padding: '4px 0', borderBottom: '1px solid var(--bx-hair)' }}>
                  {fmtTime(a.created_at)} · {a.from_status.replace('_', ' ')} → <b>{a.to_status.replace('_', ' ')}</b>{a.actor ? ` · ${a.actor}` : ''}{a.remarks ? ` · “${a.remarks}”` : ''}
                </div>
              ))}
            </div>
          </div>
        )}
      </PageState>
    </aside>
  );
}

