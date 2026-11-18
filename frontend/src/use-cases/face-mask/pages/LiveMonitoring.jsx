import FaceMaskConcealmentCard from '../components/FaceMaskConcealmentCard.jsx';
import useCommonIncidentStates from '../../../hooks/useCommonIncidentStates.js';
import { sourceMediaUrl } from '../../../api/sourceThumbnail.js';
import { FACE_MASK_BASE_URL } from '../../../config/services.js';
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, coveringLabel, fmApiUrl, timeAgo } from '../api/index.js';
import AddCameraModal from '../components/AddCameraModal.jsx';
import { useFmStatus } from '../components/FmStatus.jsx';
import { EventStatusBadge, PageState, ServiceDown, StateDot, StreamBadge, Empty } from '../components/ui.jsx';
import usePolling from '../hooks/usePolling.js';
import FaceMaskEventModal from '../components/FaceMaskEventModal.jsx';
import { normalizeLiveEvents } from './liveEventsModel.js';
import SourcePicker from '../../../components/video/SourcePicker.jsx';
import { PlaybackBadge, PlaybackProgress, StartStopControls } from '../../../components/video/PlaybackControls.jsx';
import { playbackPlaceholder, playbackStatus } from '../../../components/video/playbackState.js';
import { useOptionalActiveBranch } from '../../../features/branches/ActiveBranch.jsx';

const STAGE = { height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: '#cbd5e1', textAlign: 'center', padding: 16 };
const LIVE_STATES = ['ONLINE', 'PROCESSING', 'RECONNECTING', 'DONE', 'STOPPED', 'STOPPING'];
const browseFaceMaskVideos = () => api.get('/uploads/browse');

export default function LiveMonitoring() {
  const activeScope = useOptionalActiveBranch()?.scope;
  const branchId = activeScope?.type === 'branch' ? activeScope.id : null;
  const incidentStates=useCommonIncidentStates('face_mask');
  const { state: serviceState } = useFmStatus();
  const [selectedId, setSelectedId] = useState(() => { try { return localStorage.getItem('fmCameraId') || ''; } catch { return ''; } });
  const [addOpen, setAddOpen] = useState(false);
  const [actionError, setActionError] = useState('');
  const [nonce, setNonce] = useState(0);
  const [imgFailed, setImgFailed] = useState(false);
  const [debugOverlay, setDebugOverlay] = useState(false);
  const [useSavedRoi, setUseSavedRoi] = useState(true);
  const [stopping, setStopping] = useState(false);
  const [starting, setStarting] = useState(false);
  const [selectedEventId, setSelectedEventId] = useState('');

  const cams = usePolling(() => api.get('/cameras'), 1500);
  const events = usePolling(() => api.get('/events?limit=10'), 3000);
  const cameras = cams.data || [];
  const cam = cameras.find((c) => c.id === selectedId) || null;
  const roiMode = usePolling(() => cam ? api.get(`/cameras/${cam.id}/roi-mode`) : null, 3000, [cam?.id]);
  const st = cam?.stream || {};
  const hasFrame = !!cam && LIVE_STATES.includes(st.status) && (st.frames_read > 0 || st.status === 'DONE');
  const running = !!(cam && st.running);
  const displayStatus = playbackStatus(st.status, running);

  useEffect(() => {
    if (cam && roiMode.data?.camera_id === cam.id) setUseSavedRoi(roiMode.data.use_saved_roi);
  }, [cam?.id, roiMode.data]);

  const changeRoiMode = async (enabled) => {
    setUseSavedRoi(enabled);
    if (!cam) return;
    try {
      await api.put(`/cameras/${cam.id}/roi-mode`, { use_saved_roi: enabled });
      await roiMode.reload();
      setActionError('');
    } catch (error) {
      setUseSavedRoi(!enabled);
      setActionError(error.message);
    }
  };

  useEffect(() => { setImgFailed(false); }, [selectedId, st.status, nonce]);  // eslint-disable-line react-hooks/exhaustive-deps
  const select = (id) => {
    setSelectedId(id); setNonce((n) => n + 1);
    try { if (id) localStorage.setItem('fmCameraId', id); else localStorage.removeItem('fmCameraId'); } catch { /* ignore */ }
  };
  const streamSrc = useMemo(() => (hasFrame ? fmApiUrl(running
    ? `/streams/${cam.id}/processed?debug=${debugOverlay}&t=${Date.now()}`
    : `/streams/${cam.id}/last?t=${Date.now()}`) : ''),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [hasFrame, cam?.id, nonce, debugOverlay, running]);

  const act = async (fn) => {
    setActionError('');
    try { await fn(); setNonce((n) => n + 1); await cams.reload(); } catch (e) { setActionError(e.message); }
  };
  const stop = async () => {
    if (!cam || !running || stopping) return;
    setStopping(true);
    try { await act(() => api.post(`/cameras/${cam.id}/stop`)); } finally { setStopping(false); }
  };
  const start = async () => {
    if (!cam || running || starting) return;
    setStarting(true);
    try { await act(() => api.post(`/cameras/${cam.id}/start`)); } finally { setStarting(false); }
  };
  const remove = () => {
    if (!window.confirm(`Delete camera "${cam.name}"? Its entry ROIs are removed too; recorded events and evidence are kept.`)) return;
    act(async () => { if (running) await api.post(`/cameras/${cam.id}/stop`); await api.del(`/cameras/${cam.id}`); select(''); });
  };
  const assignCurrentBranch = () => {
    if (!cam || !branchId || cam.branch_id || running) return;
    act(() => api.patch(`/cameras/${cam.id}`, { branch_id: branchId }));
  };

  const trackRows = Object.entries(st.track_states || {});
  const liveEvents = normalizeLiveEvents(events.data?.items || []);
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

      {!down && <SourcePicker useCase="face_mask" cameras={cameras} browseVideos={browseFaceMaskVideos}
        isRunning={running} activeCameraId={cam?.id} activeSourcePath={cam?.source}
        onProcess={async (source) => {
          if (running && cam) await api.post(`/cameras/${cam.id}/stop`);
          if (source.kind === 'camera') {
            await api.post(`/cameras/${source.cameraId}/start?restart=true&use_saved_roi=${useSavedRoi}`);
            select(source.cameraId); await cams.reload();
          } else {
            const created = await api.post('/videos/process', { path: source.processPath, camera_id: source.cameraId || null,
              name: source.name.replace(/\.[^.]+$/, ''), use_saved_roi: useSavedRoi, branch_id: branchId });
            select(created.id); await cams.reload();
          }
        }}>
        <label className="bx-row bx-gap-8" style={{ fontSize: 13, marginTop: 12 }}>
          <input type="checkbox" checked={useSavedRoi} onChange={(e) => changeRoiMode(e.target.checked)} />
          Restrict evaluation to a saved entry area. If unchecked, Face Mask evaluates and plots the whole video frame; configure a reusable zone on <Link to="/regions?use_case=face_mask">Regions &amp; Zones</Link>.
        </label>
      </SourcePicker>}

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
                    {cam && !running && !['RECONNECTING', 'OFFLINE', 'ERROR'].includes(st.status) && <><div style={{ fontSize: 28 }}>⏸</div>{playbackPlaceholder(true, displayStatus, st.position_seconds)}</>}
                    {cam && running && !hasFrame && <><div style={{ fontSize: 28 }}>⏳</div>Starting (the first start loads the AI models)…</>}
                  </div>
                )}
              </div>
              {cam && <PlaybackBadge status={st.status} running={running} />}
            </div>
            <div className="bx-tile-meta">
              <label className="bx-row bx-gap-8" style={{ fontSize: 12 }}><input type="checkbox" checked={debugOverlay} onChange={(event) => setDebugOverlay(event.target.checked)} /> Debug overlay</label>
              <div>
                <div className="name">{cam ? cam.name : 'No camera selected'} {cam && <StreamBadge status={displayStatus} />}</div>
                <div className="loc">{cam ? (cam.location || cam.source) : 'Pick a camera or video from the list above.'}</div>
                {cam && !cam.branch_id && branchId && !running && <button type="button" className="bx-btn bx-btn-sm" onClick={assignCurrentBranch}>
                  Assign selected branch: {activeScope.name || branchId}
                </button>}
                {cam && !cam.branch_id && running && <div className="bx-hint">Branch is unassigned. Stop this camera before assigning a branch.</div>}
                {cam && !cam.branch_id && !branchId && !running && <div className="bx-hint">Branch is unassigned. Select a branch in the header to assign it explicitly.</div>}
              </div>
              {<div className="bx-row bx-gap-8 bx-wrap">
                  <StartStopControls selected={!!cam} status={st.status} running={running} starting={starting}
                    stopping={stopping} canResume={st.can_resume}
                    canRestartCamera={!!cam && !['upload', 'folder'].includes(cam.cam_type) && st.frames_read > 0}
                    positionSeconds={st.position_seconds}
                    onStart={start} onStop={stop} />
                  {cam && <>
                  <Link className="bx-btn bx-btn-sm" to={`/regions?use_case=face_mask&camera=${cam.id}`}>Entry ROI</Link>
                  <button type="button" className="bx-btn bx-btn-sm bx-btn-ghost" onClick={remove}>Delete</button>
                  </>}
                </div>
              }
            </div>
            {cam && <div className="bx-hint" style={{ margin: '0 16px 10px' }}>
              <label className="bx-row bx-gap-8"><input type="checkbox" checked={useSavedRoi}
                onChange={(event) => changeRoiMode(event.target.checked)} /> Use and show saved Entry ROI</label>
              {roiMode.error && <span role="alert">Entry ROI mode is unavailable. Restart the Face Mask service to apply live changes. </span>}
              <span>{roiMode.error ? 'Saved zone status could not be verified.' : useSavedRoi
                ? (roiMode.data?.camera_id === cam.id && roiMode.data.saved_rois?.length
                  ? `Active: ${roiMode.data.saved_rois.map((roi) => roi.name).join(', ')}`
                  : 'No saved Entry ROI for this camera; using the full frame.')
                : 'Entry ROI off; analysing the full frame.'} Camera ID: {cam.id.slice(0, 8)}.</span>
            </div>}
            {cam && <PlaybackProgress status={st} />}
            {cam && !running && st.frames_read > 0 && <div className="bx-hint" style={{ margin: '0 16px 10px' }}>{playbackPlaceholder(true, displayStatus, st.position_seconds)}</div>}
            {cam && st.status === 'DONE' && (
              <div className="bx-hint" style={{ margin: '0 16px 10px' }}>
                <b>Finished.</b> {st.frames_read} frames analysed, <b>{st.events_found}</b> concealment event{st.events_found === 1 ? '' : 's'} found.
                {st.events_found > 0 && <> <Link to="/alerts?use_case=face_mask">Review them</Link>.</>}
              </div>
            )}
            {cam && st.notice && <div className="bx-diag" role="status" style={{ margin: '0 16px 10px' }}>{st.notice}{st.notice.includes('ROI') && <>. <Link to={`/regions?use_case=face_mask&camera=${cam.id}`}>Set it now</Link>.</>}</div>}
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
            <div className="bx-card-title">Concealment events <Link to="/alerts?use_case=face_mask" style={{ fontWeight: 400, fontSize: 12 }}>(all)</Link></div>
            <div className="bx-ticker" style={{ maxHeight: 480, overflowY: 'auto' }}>
              {events.error && events.data && <div className="bx-diag" role="status">Connection warning: showing the last loaded concealment events. {events.error.message}</div>}
              {events.error && !events.data && <ServiceDown error={events.error} onRetry={events.reload} />}
              {!events.data && !events.error && <div className="bx-hint" role="status" style={{ padding: 12 }}>Loading concealment events…</div>}
              {events.data && liveEvents.length === 0 && !events.error && <Empty icon="◷" bare>No concealment events yet.</Empty>}
              {liveEvents.map((event) => <FaceMaskConcealmentCard key={event.id} event={event} common={incidentStates.bySource[event.id]}
                thumbnailUrl={event.snapshot_path ? sourceMediaUrl(FACE_MASK_BASE_URL, event.snapshot_path, 'face_mask') : undefined}
                onSelect={setSelectedEventId} />)}
            </div>
            {selectedEventId && <FaceMaskEventModal eventId={selectedEventId} cameras={cameras}
              severity={incidentStates.bySource[selectedEventId]?.severity} incidentStatus={incidentStates.bySource[selectedEventId]?.status}
              incidentId={incidentStates.bySource[selectedEventId]?.id} incidentLookupError={incidentStates.error}
              onClose={() => setSelectedEventId('')} onChanged={events.reload} />}
          </div>
        </div>
      </PageState>

      {addOpen && <AddCameraModal onClose={() => setAddOpen(false)} onCreated={(created) => { select(created.id); cams.reload(); }} />}
    </>
  );
}
