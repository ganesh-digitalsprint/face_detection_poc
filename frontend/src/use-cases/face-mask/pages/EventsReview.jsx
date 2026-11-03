import { useEffect, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { api, coveringLabel, fmApiUrl, fmtTime, qs } from '../api/index.js';
import { EventStatusBadge, PageState } from '../components/ui.jsx';
import Modal from '../../branch-exterior/components/Modal.jsx';
import usePolling from '../hooks/usePolling.js';

const STATUSES = ['OPEN', 'UNDER_REVIEW', 'CONFIRMED', 'FALSE_POSITIVE', 'CLOSED'];
const PAGE_SIZE = 15;
// Which review actions the workflow allows from each status (the server enforces the same table).
const NEXT = { OPEN: ['UNDER_REVIEW'], UNDER_REVIEW: ['CONFIRMED', 'FALSE_POSITIVE'], CONFIRMED: ['CLOSED'], FALSE_POSITIVE: ['CLOSED'], CLOSED: [] };
const ACTION_LABEL = { UNDER_REVIEW: 'Mark under review', CONFIRMED: 'Confirm', FALSE_POSITIVE: 'False positive', CLOSED: 'Close' };
const NEEDS_REASON = { FALSE_POSITIVE: 'Reason (why is this a false positive?)', CLOSED: 'Closing remarks' };

function toIso(local) { return local ? new Date(local).toISOString() : ''; }

function Detail({ eventId, cameras, onClose, onChanged }) {
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
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  const data = ev.data;
  const e = data?.event;
  const evidence = data?.evidence;
  const cameraName = cameras.find((c) => c.id === e?.camera_id)?.name || evidence?.camera_name || e?.camera_id;

  return (
    <Modal title={`Concealment event ${eventId.slice(0, 8)}`} onClose={onClose} maxWidth={920}>
      <PageState loading={ev.loading} error={ev.error} data={data} onRetry={ev.reload}>
        {e && (
          <div className="bx-two-col" style={{ gridTemplateColumns: '1.3fr 1fr' }}>
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
    </Modal>
  );
}

export default function EventsReview() {
  const { eventId } = useParams();
  const navigate = useNavigate();
  const [search] = useSearchParams();
  const [filters, setFilters] = useState({ from: '', to: '', camera_id: '', status: STATUSES.includes(search.get('status')) ? search.get('status') : '', covering_type: '' });
  const [page, setPage] = useState(0);
  const set = (k) => (ev) => { setFilters((f) => ({ ...f, [k]: ev.target.value })); setPage(0); };

  const cams = usePolling(() => api.get('/cameras'), 15000);
  const list = usePolling(() => api.get(`/events${qs({
    date_from: toIso(filters.from), date_to: toIso(filters.to), camera_id: filters.camera_id, status: filters.status,
    covering_type: filters.covering_type, limit: PAGE_SIZE, offset: page * PAGE_SIZE })}`), 5000, [filters, page]);
  const cameras = cams.data || [];
  const nameOf = (id) => cameras.find((c) => c.id === id)?.name || id.slice(0, 8);
  const total = list.data?.total || 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  useEffect(() => { if (page > pages - 1) setPage(0); }, [pages, page]);

  return (
    <>
      <div className="bx-card bx-mb-16">
        <div className="bx-field-row" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))' }}>
          <label className="bx-field">From <input className="bx-input" type="datetime-local" value={filters.from} onChange={set('from')} /></label>
          <label className="bx-field">To <input className="bx-input" type="datetime-local" value={filters.to} onChange={set('to')} /></label>
          <label className="bx-field">Camera
            <select className="bx-input" value={filters.camera_id} onChange={set('camera_id')}>
              <option value="">All cameras</option>{cameras.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
          <label className="bx-field">Status
            <select className="bx-input" value={filters.status} onChange={set('status')}>
              <option value="">All statuses</option>{STATUSES.map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
            </select>
          </label>
          <label className="bx-field">Covering
            <select className="bx-input" value={filters.covering_type} onChange={set('covering_type')}>
              <option value="">Any</option>
              {['lower_face_covering', 'full_face_covering', 'head_covering', 'surgical_mask', 'scarf', 'cap_concealing', 'helmet', 'other_mask']
                .map((c) => <option key={c} value={c}>{coveringLabel(c)}</option>)}
            </select>
          </label>
        </div>
        <button type="button" className="bx-btn bx-btn-sm" onClick={() => { setFilters({ from: '', to: '', camera_id: '', status: '', covering_type: '' }); setPage(0); }}>Clear filters</button>
      </div>

      <div className="bx-card">
        <PageState loading={list.loading} error={list.error} data={list.data} onRetry={list.reload}
          isEmpty={(d) => d.total === 0} emptyIcon="🛡" emptyText="No concealment events match these filters.">
          <div className="bx-scroll-x">
            <table className="bx-table">
              <thead><tr><th>Time</th><th>Camera</th><th>Track</th><th>Covering</th><th>Score</th><th>Status</th><th>Clip</th></tr></thead>
              <tbody>
                {(list.data?.items || []).map((e) => (
                  <tr key={e.id} className="clickable" tabIndex={0} onClick={() => navigate(`/face-mask/events/${e.id}`)}
                    onKeyDown={(k) => { if (k.key === 'Enter') navigate(`/face-mask/events/${e.id}`); }}>
                    <td>{fmtTime(e.first_seen)}</td><td>{nameOf(e.camera_id)}</td><td>#{e.track_id}</td>
                    <td>{coveringLabel(e.covering_type)}</td><td>{e.score.toFixed(2)}</td>
                    <td><EventStatusBadge status={e.status} /></td><td>{e.clip_status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="bx-row bx-gap-8" style={{ justifyContent: 'space-between', marginTop: 12 }}>
            <span className="bx-muted" style={{ fontSize: 13 }}>{total} event{total === 1 ? '' : 's'} · page {page + 1} of {pages}</span>
            <span className="bx-row bx-gap-8">
              <button type="button" className="bx-btn bx-btn-sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Previous</button>
              <button type="button" className="bx-btn bx-btn-sm" disabled={page >= pages - 1} onClick={() => setPage((p) => p + 1)}>Next</button>
            </span>
          </div>
        </PageState>
      </div>

      {eventId && <Detail eventId={eventId} cameras={cameras} onClose={() => navigate('/face-mask/events')} onChanged={list.reload} />}
    </>
  );
}
