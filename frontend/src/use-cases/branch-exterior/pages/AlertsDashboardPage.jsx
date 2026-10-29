import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api, bxApiUrl, bxStorageUrl, fmtTime } from '../api/index.js';
import { useNewEvents } from '../feed.js';
import { BarChart, DonutChart } from '../components/Charts.jsx';
import Modal from '../components/Modal.jsx';
import { Empty } from '../components/ui.jsx';

const SEV_COLORS = { info: '#6b7788', low: '#3fbf6f', medium: '#e0a930', high: '#e2793a', critical: '#e2574a' };
const SCEN_LABELS = ['loitering', 'gathering', 'movement', 'intrusion', 'anomaly', 'simulated'];
const qstr = (o) => Object.entries(o).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&');

function EventDetail({ id, onClose, onReviewed }) {
  const [e, setE] = useState(null);
  const [remarks, setRemarks] = useState('');
  const [err, setErr] = useState('');
  useEffect(() => {
    api.get(`/events/${id}`).then((x) => { setE(x); setRemarks(x.reviewer_remarks || ''); }).catch((x) => setErr(x.message));
  }, [id]);
  if (err) return <Modal title="Event" onClose={onClose}><div className="bx-diag">{err}</div></Modal>;
  if (!e) return <Modal title="Event" onClose={onClose}><div className="bx-row bx-gap-8 bx-muted"><span className="bx-spinner" /> Loading…</div></Modal>;

  const review = async (status) => {
    try { await api.post(`/events/${e.id}/review`, { status, reviewer_remarks: remarks }); } catch (x) { alert(x.message); return; }
    onReviewed();
  };
  const hasSnap = !!e.snapshot_path; const hasClip = !!e.clip_path;
  return (
    <Modal
      title={`${e.camera_name} - ${e.scenario}`}
      onClose={onClose}
      footer={(
        <>
          <a className="bx-btn" href={bxApiUrl(`/events/${e.id}/report`)} target="_blank" rel="noreferrer" title="Printable one-page report (Save as PDF)">📄 Incident report</a>
          <button type="button" className="bx-btn" onClick={() => review('false_positive')}>Mark false positive</button>
          <button type="button" className="bx-btn bx-btn-danger" onClick={() => review('confirmed')}>Confirm - follow procedure</button>
          <button type="button" className="bx-btn bx-btn-primary" onClick={() => review('closed')}>Close event</button>
        </>
      )}
    >
      <div className="bx-row bx-gap-8 bx-wrap" style={{ marginBottom: 10 }}>
        <span className={`bx-badge sev-${e.severity}`}>{e.severity}</span>
        <span className={`bx-badge status-${e.status}`}>{e.status.replace('_', ' ')}</span>
        <span className="bx-tag">{fmtTime(e.created_at)}</span>
        <span className="bx-tag">confidence {Math.round((e.confidence || 0) * 100)}%</span>
      </div>
      <p>{e.message}</p>
      <p className="bx-muted" style={{ fontSize: 12 }}>Zone: {e.zone_name || '-'} · Track ID(s): {(e.track_ids || []).join(', ') || '-'}</p>
      {hasSnap && <img src={bxStorageUrl(e.snapshot_path)} alt="snapshot" style={{ width: '100%', borderRadius: 8, border: '1px solid var(--bx-border-soft)', margin: '8px 0' }} />}
      {hasClip && <video src={bxStorageUrl(e.clip_path)} controls style={{ width: '100%', borderRadius: 8, border: '1px solid var(--bx-border-soft)' }} />}
      {!hasSnap && !hasClip && <p className="bx-muted" style={{ fontSize: 12 }}>No snapshot/clip stored - only suspicious events (high/critical severity, weapon, fighting) keep media, to save disk space. {e.meta && e.meta.evidence ? `(${String(e.meta.evidence)})` : ''}</p>}
      {hasSnap && !hasClip && <p className="bx-muted" style={{ fontSize: 12 }}>Clip is still being written (about 5 s after the event) - reopen this event shortly.</p>}
      {Object.keys(e.meta || {}).length > 0 && (
        <pre className="bx-mono" style={{ fontSize: 11, background: 'var(--bx-inset)', padding: 8, borderRadius: 6, overflowX: 'auto', border: '1px solid var(--bx-border-soft)' }}>{JSON.stringify(e.meta, null, 2)}</pre>
      )}
      <label className="bx-field" style={{ marginTop: 10 }}>Reviewer remarks
        <textarea className="bx-input" rows={2} value={remarks} onChange={(x) => setRemarks(x.target.value)} placeholder="e.g. Confirmed guard on night patrol" />
      </label>
    </Modal>
  );
}

export default function AlertsDashboardPage() {
  const [params, setParams] = useSearchParams();
  const [summary, setSummary] = useState(null);
  const [events, setEvents] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [severity, setSeverity] = useState('');
  const [scenario, setScenario] = useState('');
  const [status, setStatus] = useState('');
  const [detailId, setDetailId] = useState(params.get('event'));

  const filters = { ...(severity && { severity }), ...(scenario && { scenario }), ...(status && { status }) };
  const qs = qstr({ ...filters, limit: 300 });

  const loadSummary = useCallback(async () => {
    try { setSummary(await api.get('/dashboard/summary')); } catch { /* backend busy */ }
  }, []);
  const loadEvents = useCallback(async () => {
    try { setEvents(await api.get(`/events?${qs}`)); } catch { setEvents([]); }
    setLoaded(true);
  }, [qs]);

  useEffect(() => { loadSummary(); const id = setInterval(loadSummary, 15000); return () => clearInterval(id); }, [loadSummary]);
  useEffect(() => { loadEvents(); }, [loadEvents]);
  useNewEvents(() => { loadEvents(); loadSummary(); });

  const closeDetail = () => {
    setDetailId(null);
    if (params.get('event')) { params.delete('event'); setParams(params, { replace: true }); }
  };

  const clearEvents = async () => {
    const typed = prompt('This permanently deletes ALL events (every camera, every status) from the database. Cameras, zones and guards are not affected. This is meant to recover from an alert flood - type OK to confirm.');
    if (typed !== 'OK' && typed !== 'ok') return;
    try {
      const r = await api.del('/events');
      alert(`Deleted ${r.deleted} event(s).`);
    } catch (e) { alert(e.message); }
    loadEvents(); loadSummary();
  };

  const s = summary;
  const sevMap = s ? Object.fromEntries(s.by_severity.map((x) => [x.severity, x.count])) : {};
  const scenMap = s ? Object.fromEntries(s.by_scenario.map((x) => [x.scenario, x.count])) : {};

  return (
    <>
      <div className="bx-grid bx-grid-4 bx-mb-16">
        <div className="bx-card bx-kpi"><span className="lbl">Open alerts</span><span className="num">{s ? s.open_events : '-'}</span><span className="delta">{s ? `${s.critical_open} critical` : '-'}</span></div>
        <div className="bx-card bx-kpi"><span className="lbl">Events today</span><span className="num">{s ? s.events_today : '-'}</span><span className="delta">since 00:00</span></div>
        <div className="bx-card bx-kpi"><span className="lbl">Cameras online</span><span className="num">{s ? `${s.cameras_online} / ${s.cameras_total}` : '-'}</span><span className="delta">of total configured</span></div>
        <div className="bx-card bx-kpi"><span className="lbl">Guards enrolled</span><span className="num">{s ? s.guards_enrolled : '-'}</span><span className="delta">for on-site recognition</span></div>
      </div>

      <div className="bx-grid bx-grid-3 bx-mb-16">
        <div className="bx-card">
          <div className="bx-card-title">By severity</div>
          <DonutChart segments={Object.keys(SEV_COLORS).map((k) => ({ label: k, value: sevMap[k] || 0, color: SEV_COLORS[k] }))} />
          <div style={{ marginTop: 8, fontSize: 11 }}>
            {Object.keys(SEV_COLORS).map((k) => (
              <span key={k} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, marginRight: 10 }}>
                <span className="bx-swatch" style={{ background: SEV_COLORS[k], marginRight: 0 }} />{k} ({sevMap[k] || 0})
              </span>
            ))}
          </div>
        </div>
        <div className="bx-card">
          <div className="bx-card-title">By scenario (Tasks 1-5)</div>
          <BarChart labels={SCEN_LABELS} values={SCEN_LABELS.map((l) => scenMap[l] || 0)} color="#4a90e2" />
        </div>
        <div className="bx-card">
          <div className="bx-card-title">Last 24 hours, by hour</div>
          <BarChart labels={s ? s.by_hour.map((h) => h.hour.slice(0, 2)) : []} values={s ? s.by_hour.map((h) => h.count) : []} color="#2fb894" />
        </div>
      </div>

      <div className="bx-card">
        <div className="bx-section-title">
          <h2>Events</h2>
          <div className="bx-row bx-gap-8 bx-wrap">
            <select className="bx-input bx-input-auto" value={severity} onChange={(e) => setSeverity(e.target.value)}>
              <option value="">All severities</option><option>info</option><option>low</option><option>medium</option><option>high</option><option>critical</option>
            </select>
            <select className="bx-input bx-input-auto" value={scenario} onChange={(e) => setScenario(e.target.value)}>
              <option value="">All scenarios</option><option value="loitering">Loitering</option><option value="gathering">Gathering</option><option value="movement">Movement</option><option value="intrusion">Intrusion</option><option value="anomaly">Anomaly</option>
            </select>
            <select className="bx-input bx-input-auto" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All statuses</option><option value="open">Open</option><option value="under_review">Under review</option><option value="confirmed">Confirmed</option><option value="false_positive">False positive</option><option value="closed">Closed</option>
            </select>
            <a className="bx-btn bx-btn-sm" href={bxApiUrl(`/events/export/csv?${qs}`)}>⬇ Export CSV</a>
            <button type="button" className="bx-btn bx-btn-sm bx-btn-danger" onClick={clearEvents}>🗑 Clear events</button>
          </div>
        </div>
        <div className="bx-scroll-x">
          <table className="bx-table">
            <thead><tr><th>Time</th><th>Camera</th><th>Zone</th><th>Scenario</th><th>Severity</th><th>Status</th><th>Confidence</th></tr></thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.id} className="clickable" onClick={() => setDetailId(e.id)}>
                  <td className="bx-mono bx-faint">{fmtTime(e.created_at)}</td>
                  <td>{e.camera_name}</td>
                  <td>{e.zone_name || <span className="bx-faint">-</span>}</td>
                  <td>
                    <span className="bx-tag">{e.scenario}</span>
                    {e.meta && e.meta.kind && e.meta.kind !== e.scenario && <> <span className="bx-tag bx-tag-blue">{String(e.meta.kind).replace(/_/g, ' ')}</span></>}
                  </td>
                  <td><span className={`bx-badge sev-${e.severity}`}>{e.severity}</span></td>
                  <td><span className={`bx-badge status-${e.status}`}>{e.status.replace('_', ' ')}</span></td>
                  <td>{Math.round((e.confidence || 0) * 100)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {loaded && events.length === 0 && <Empty icon="✅" bare>No events match these filters.</Empty>}
      </div>

      {detailId && <EventDetail id={detailId} onClose={closeDetail} onReviewed={() => { closeDetail(); loadEvents(); loadSummary(); }} />}
    </>
  );
}
