import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, coveringLabel, fmApiUrl, timeAgo } from '../api/index.js';
import AddCameraModal from '../components/AddCameraModal.jsx';
import { useFmStatus } from '../components/FmStatus.jsx';
import { EventStatusBadge, PageState, ServiceDown, StateDot, StreamBadge, Empty } from '../components/ui.jsx';
import usePolling from '../hooks/usePolling.js';

// A sensible default entrance for a quick video test: the lower part of the frame, people walking "up" into the building.
// Real cameras get their own ROI on the Entry ROI page.
const DEFAULT_ROI = {
  name: 'Default entrance (lower frame)',
  polygon: [{ x: 0.05, y: 0.4 }, { x: 0.95, y: 0.4 }, { x: 0.95, y: 0.98 }, { x: 0.05, y: 0.98 }],
  inward_vector: { x: 0, y: -1 },
};
const STAGE = { height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: '#cbd5e1', textAlign: 'center', padding: 16 };
const LIVE_STATES = ['ONLINE', 'PROCESSING', 'RECONNECTING', 'DONE'];

function VideoPanel({ onCreated }) {
  const [files, setFiles] = useState([]);
  const [picked, setPicked] = useState('');
  const [upload, setUpload] = useState(null);
  const [useDefaultRoi, setUseDefaultRoi] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const loadFiles = useCallback(() => api.get('/uploads/browse').then(setFiles).catch(() => setFiles([])), []);
  useEffect(() => { loadFiles(); }, [loadFiles]);

  const run = async (path, name) => {
    const created = await api.post('/videos/process', { path, name, roi: useDefaultRoi ? DEFAULT_ROI : null });
    await onCreated(created);
  };
  const submit = async () => {
    setError(''); setBusy(true);
    try {
      if (upload) {
        const fd = new FormData(); fd.append('file', upload);
        const up = await api.postForm('/uploads/video', fd);
        await run(up.path, upload.name.replace(/\.[^.]+$/, ''));
        setUpload(null); await loadFiles();
      } else if (picked) {
        await run(picked, files.find((f) => f.path === picked)?.name.replace(/\.[^.]+$/, '') || '');
      } else { throw new Error('Choose a video file to upload, or pick one that is already on the server.'); }
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  return (
    <div className="bx-card bx-mb-16">
      <div className="bx-card-title">Analyse a video</div>
      {error && <div className="bx-diag" role="alert">{error}</div>}
      <div className="bx-field-row">
        <label className="bx-field">Upload a video
          <input className="bx-input" type="file" accept="video/*" onChange={(e) => { setUpload(e.target.files[0] || null); setPicked(''); }} />
        </label>
        <label className="bx-field">…or pick one already on the server
          <select className="bx-input" value={picked} onChange={(e) => { setPicked(e.target.value); setUpload(null); }}>
            <option value="">{files.length ? 'Select a video…' : 'No videos found'}</option>
            {files.map((f) => <option key={f.path} value={f.path}>{f.name} ({f.folder}, {f.size_mb} MB)</option>)}
          </select>
        </label>
      </div>
      <label className="bx-row bx-gap-8" style={{ fontSize: 13, marginBottom: 10 }}>
        <input type="checkbox" checked={useDefaultRoi} onChange={(e) => setUseDefaultRoi(e.target.checked)} />
        Use a default entrance (lower part of the frame, walking up). Untick to set the entry area yourself on the Entry ROI page first.
      </label>
      <button type="button" className="bx-btn bx-btn-primary" disabled={busy} onClick={submit}>{busy ? 'Starting…' : 'Analyse video'}</button>
    </div>
  );
}

function Progress({ st }) {
  if (!st.frames_total) return null;
  return (
    <div style={{ padding: '4px 16px 10px' }}>
      <div className="bx-bar-track" role="progressbar" aria-valuenow={st.percent} aria-valuemin={0} aria-valuemax={100}>
        <div className="bx-bar-fill" style={{ width: `${st.percent}%` }} />
      </div>
      <div className="bx-muted" style={{ fontSize: 12, marginTop: 4 }}>
        {st.percent}% · {st.frames_read} / {st.frames_total} frames · {st.events_found} concealment event{st.events_found === 1 ? '' : 's'} so far
      </div>
    </div>
  );
}

export default function LiveMonitoring() {
  const { state: serviceState } = useFmStatus();
  const [selectedId, setSelectedId] = useState(() => { try { return localStorage.getItem('fmCameraId') || ''; } catch { return ''; } });
  const [addOpen, setAddOpen] = useState(false);
  const [actionError, setActionError] = useState('');
  const [nonce, setNonce] = useState(0);
  const [imgFailed, setImgFailed] = useState(false);

  const cams = usePolling(() => api.get('/cameras'), 1500);
  const events = usePolling(() => api.get('/events?limit=10'), 3000);
  const cameras = cams.data || [];
  const cam = cameras.find((c) => c.id === selectedId) || null;
  const st = cam?.stream || {};
  const hasFrame = !!cam && LIVE_STATES.includes(st.status) && (st.frames_read > 0 || st.status === 'DONE');
  const running = !!(cam && st.running);

  useEffect(() => { setImgFailed(false); }, [selectedId, st.status === 'DONE', nonce]);  // eslint-disable-line react-hooks/exhaustive-deps
  const select = (id) => {
    setSelectedId(id); setNonce((n) => n + 1);
    try { if (id) localStorage.setItem('fmCameraId', id); else localStorage.removeItem('fmCameraId'); } catch { /* ignore */ }
  };
  const streamSrc = useMemo(() => (hasFrame ? fmApiUrl(`/streams/${cam.id}/processed?t=${Date.now()}`) : ''),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [hasFrame, cam?.id, nonce]);

  const act = async (fn) => {
    setActionError('');
    try { await fn(); setNonce((n) => n + 1); await cams.reload(); } catch (e) { setActionError(e.message); }
  };
  const toggleRun = () => act(() => api.post(`/cameras/${cam.id}/${running ? 'stop' : 'start'}`));
  const remove = () => {
    if (!window.confirm(`Delete camera "${cam.name}"? Its entry ROIs are removed too; recorded events and evidence are kept.`)) return;
    act(async () => { await api.del(`/cameras/${cam.id}`); select(''); });
  };

  const trackRows = Object.entries(st.track_states || {});
  const down = serviceState === 'offline';

  return (
    <>
      <div className="bx-section-title">
        <div className="bx-row bx-gap-12 bx-wrap">
          <span className="bx-tag">{cameras.length} camera{cameras.length === 1 ? '' : 's'} / video{cameras.length === 1 ? '' : 's'}</span>
        </div>
        <button type="button" className="bx-btn bx-btn-primary" disabled={down} onClick={() => setAddOpen(true)}>+ Add camera</button>
      </div>

      {cams.error && !cams.data && <ServiceDown error={cams.error} onRetry={cams.reload} />}
      {actionError && <div className="bx-diag" role="alert">{actionError}</div>}

      {!down && <VideoPanel onCreated={async (created) => { select(created.id); await cams.reload(); }} />}

      <div className="bx-card bx-mb-16">
        <label className="bx-field" style={{ margin: 0 }}>
          <span>Camera or video</span>
          <select className="bx-input" value={selectedId} onChange={(e) => select(e.target.value)} disabled={!cameras.length}>
            <option value="">{cameras.length ? '— Select a camera or video —' : 'No cameras yet - add one or analyse a video above'}</option>
            {cameras.map((c) => <option key={c.id} value={c.id}>{c.stream.running ? '▶ ' : ''}{c.name} ({c.stream.status})</option>)}
          </select>
        </label>
      </div>

      <PageState loading={cams.loading} error={null} data={cams.data} isEmpty={() => false}>
        <div className="bx-two-col">
          <div className="bx-tile">
            <div className="bx-video-wrap" style={{ aspectRatio: '4/3', maxHeight: '70vh' }}>
              <div style={{ width: '100%', height: '100%' }}>
                {hasFrame && !imgFailed && <img src={streamSrc} alt={cam.name} onError={() => setImgFailed(true)} style={{ width: '100%', height: '100%', objectFit: 'contain' }} />}
                {(!hasFrame || imgFailed) && (
                  <div style={STAGE}>
                    {!cam && <><div style={{ fontSize: 28 }}>🎬</div>Select a camera or video above</>}
                    {cam && st.status === 'RECONNECTING' && <><div style={{ fontSize: 28 }}>🔄</div>Reconnecting to the camera… {st.last_error}</>}
                    {cam && st.status === 'OFFLINE' && <><div style={{ fontSize: 28 }}>📴</div>Camera is OFFLINE. It keeps retrying automatically. {st.last_error}</>}
                    {cam && st.status === 'ERROR' && <><div style={{ fontSize: 28 }}>⚠</div>{st.last_error || 'The stream could not start.'}</>}
                    {cam && ['STOPPED', 'ONLINE', 'PROCESSING'].includes(st.status) && !running && <><div style={{ fontSize: 28 }}>⏸</div>Stopped. Press Start to analyse.</>}
                    {cam && running && !hasFrame && <><div style={{ fontSize: 28 }}>⏳</div>Starting (the first start loads the AI models)…</>}
                  </div>
                )}
              </div>
              {cam && <div className="bx-live-badge"><span className={running ? 'bx-dot-live' : 'bx-dot-off'} /> {st.status}</div>}
            </div>
            <div className="bx-tile-meta">
              <div>
                <div className="name">{cam ? cam.name : 'No camera selected'} {cam && <StreamBadge status={st.status} />}</div>
                <div className="loc">{cam ? (cam.location || cam.source) : 'Pick a camera or video from the list above.'}</div>
              </div>
              {cam && (
                <div className="bx-row bx-gap-8 bx-wrap">
                  <button type="button" className={`bx-btn bx-btn-sm${running ? '' : ' bx-btn-primary'}`} onClick={toggleRun}>{running ? 'Stop' : 'Start'}</button>
                  <Link className="bx-btn bx-btn-sm" to={`/face-mask/roi?camera=${cam.id}`}>Entry ROI</Link>
                  <button type="button" className="bx-btn bx-btn-sm bx-btn-ghost" onClick={remove}>Delete</button>
                </div>
              )}
            </div>
            {cam && <Progress st={st} />}
            {cam && st.status === 'DONE' && (
              <div className="bx-hint" style={{ margin: '0 16px 10px' }}>
                <b>Finished.</b> {st.frames_read} frames analysed, <b>{st.events_found}</b> concealment event{st.events_found === 1 ? '' : 's'} found.
                {st.events_found > 0 && <> <Link to="/face-mask/events">Review them</Link>.</>}
              </div>
            )}
            {cam && st.notice && <div className="bx-diag" role="status" style={{ margin: '0 16px 10px' }}>{st.notice}. <Link to={`/face-mask/roi?camera=${cam.id}`}>Set it now</Link>.</div>}
            {cam && st.last_error && ['RECONNECTING', 'OFFLINE'].includes(st.status) === false && st.status !== 'ERROR' && (
              <div style={{ padding: '0 16px 6px', fontSize: 12, color: 'var(--bx-red)' }}>{st.last_error}</div>
            )}
            {cam && (
              <div className="bx-stat-grid">
                {[['People tracked', st.active_tracks || 0], ['FPS', (st.fps || 0).toFixed(1)], ['Frames', st.frames_read || 0], ['Events', st.events_found || 0]]
                  .map(([k, v]) => <div key={k} className="bx-stat"><div className="k">{k}</div><div className="v">{v}</div></div>)}
              </div>
            )}
            {cam && trackRows.length > 0 && (
              <div style={{ padding: '0 16px 14px', fontSize: 13 }}>
                <b>Current tracks</b>
                <div className="bx-row bx-gap-8 bx-wrap" style={{ marginTop: 6 }}>
                  {trackRows.map(([id, s]) => <span key={id} className="bx-tag"><StateDot state={s} />#{id} {s.replace('_', ' ').toLowerCase()}</span>)}
                </div>
              </div>
            )}
          </div>

          <div className="bx-card">
            <div className="bx-card-title">Concealment events <Link to="/face-mask/events" style={{ fontWeight: 400, fontSize: 12 }}>(all)</Link></div>
            <div className="bx-ticker">
              {events.error && !events.data && <ServiceDown error={events.error} onRetry={events.reload} />}
              {events.data && events.data.items.length === 0 && <Empty icon="🕑" bare>No concealment events yet.</Empty>}
              {(events.data?.items || []).map((e) => (
                <Link key={e.id} to={`/face-mask/events/${e.id}`} className="bx-ticker-item sev-high" style={{ display: 'block', textDecoration: 'none', color: 'inherit' }}>
                  <div className="top"><span className="cam">{coveringLabel(e.covering_type)}</span><span className="time">{timeAgo(e.first_seen)}</span></div>
                  <div className="msg">Track #{e.track_id} · score {e.score.toFixed(2)} · {e.frame_count} frames</div>
                  <div style={{ marginTop: 5 }}><EventStatusBadge status={e.status} /></div>
                </Link>
              ))}
            </div>
          </div>
        </div>
      </PageState>

      {addOpen && <AddCameraModal onClose={() => setAddOpen(false)} onCreated={(created) => { select(created.id); cams.reload(); }} />}
    </>
  );
}
