import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, bxApiUrl, timeAgo } from '../api/index.js';
import { useNewEvents } from '../feed.js';
import { beep, setSound, soundOn } from '../sound.js';
import AddCameraModal, { rescanVideosFolder } from '../components/AddCameraModal.jsx';
import { Empty } from '../components/ui.jsx';

// Every detection the system can make, in plain words, with how many incidents of each were seen in this video.
const RULES = [
  ['weapon', 'Weapon-like object', 'knife / bat-like object held by a person'],
  ['fighting', 'Fighting', 'two people in close contact with violent arm movement (needs body pose)'],
  ['violent_action', 'Violent action', 'sustained swinging / striking by one person, e.g. a hammer at an ATM'],
  ['snatch_flee', 'Snatch and flee', 'close contact, then one person runs away'],
  ['vehicle_escape', 'Escape on a bike', 'gets onto a motorbike after a snatch / weapon / fight / run'],
  ['vehicle_takeoff', 'Parked bike taken', 'a bike that sat parked is boarded by someone who came on foot and rides off'],
  ['climbing', 'Climbing', 'feet rise while the body stays the same size, arms up (wall / fence / gate)'],
  ['drop_from_height', 'Jump down from height', 'a fast one-way drop of the feet at constant size'],
  ['fallen', 'Person down', 'lying posture held for a moment'],
  ['running', 'Running', 'moving faster than about 1.1 body-heights per second'],
  ['jumping', 'Jumping', 'feet leave the ground and come back'],
  ['scanning', 'Lookout behaviour', 'repeatedly looking left / right while standing still (needs body pose)'],
  ['gate_tampering', 'Gate tampering', 'lingering at an entrance / restricted zone while scanning or working with the hands'],
  ['unattended_bag', 'Unattended bag', 'a bag left alone with nobody near it for 20 s'],
  ['atm_group', 'Group at ATM', '3+ people inside an ATM zone'],
  ['group', 'Group together', '3+ people staying together (when no zones are drawn)'],
  ['zone_group', 'Group at a zone', '3+ people gathered at an armed zone for 15+ s'],
  ['zone_watching', 'Staring at a zone', 'repeatedly looking toward an armed zone while standing about (needs body pose)'],
  ['zone_rush', 'Running toward a zone', 'running toward an armed zone'],
  ['zone_tamper', 'Hands working on a zone', 'hands on the zone with vigorous arm movement - prying / hammering (needs body pose)'],
  ['zone_touch', 'Restricted zone breach', 'someone touches / enters a zone set to Restricted'],
  ['zone_near', 'Near a restricted zone', 'someone comes close to a zone set to Restricted - near'],
];

const THREAT = { NORMAL: ['#16a34a', 'NORMAL'], ELEVATED: ['#ca8a04', 'ELEVATED'], HIGH: ['#ea580c', 'HIGH'], CRITICAL: ['#dc2626', 'CRITICAL'] };
const stageMsg = { height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: '#cbd5e1', textAlign: 'center', padding: 16 };

export default function LiveMonitoringPage() {
  const navigate = useNavigate();
  const [cameras, setCameras] = useState([]);
  const [statuses, setStatuses] = useState({});
  const [selectedId, setSelectedId] = useState(() => localStorage.getItem('liveCameraId') || '');
  const [showProcessed, setShowProcessed] = useState(true);
  const [starting, setStarting] = useState(false);
  const [ticker, setTicker] = useState([]);
  const [soundState, setSoundState] = useState(soundOn());
  const [addOpen, setAddOpen] = useState(false);
  const [rescanBusy, setRescanBusy] = useState(false);
  const [streamNonce, setStreamNonce] = useState(0);
  const [, setTick] = useState(0);
  const selectedRef = useRef(selectedId);
  selectedRef.current = selectedId;
  const zoneAlertOn = useRef(false);
  const initDone = useRef(false);

  const loadCameras = useCallback(async () => {
    let cams = [];
    try { cams = await api.get('/cameras'); } catch { return; }
    let st = {};
    try { st = await api.get('/cameras/status/all'); } catch { st = {}; }
    setCameras(cams); setStatuses(st);
    if (selectedRef.current && !cams.some((c) => c.id === selectedRef.current)) {
      setSelectedId(''); selectedRef.current = ''; localStorage.removeItem('liveCameraId');
    }
    return cams;
  }, []);

  const selectCamera = useCallback(async (id) => {
    setSelectedId(id); selectedRef.current = id;
    setStreamNonce((n) => n + 1);
    if (id) localStorage.setItem('liveCameraId', id); else localStorage.removeItem('liveCameraId');
    try {
      if (id) { setStarting(true); await api.post(`/cameras/${id}/activate`); } // stops every other video, starts this one
      else await api.post('/cameras/stop-all');
    } catch (e) { alert(`Could not switch video: ${e.message}`); }
    await loadCameras();
    setStarting(false);
  }, [loadCameras]);

  // Initial load + polling. Re-activate the video chosen last time (the server starts with every video idle).
  useEffect(() => {
    let alive = true;
    (async () => {
      const cams = await loadCameras();
      if (!alive || initDone.current) return;
      initDone.current = true;
      const cam = cams?.find((c) => c.id === selectedRef.current);
      if (cam) {
        let st = {};
        try { st = await api.get('/cameras/status/all'); } catch { /* ignore */ }
        if (!(st[cam.id] && st[cam.id].running)) selectCamera(cam.id);
      }
    })();
    const id = setInterval(loadCameras, 1500);
    api.get('/events?limit=15').then((ev) => alive && setTicker(ev)).catch(() => {});
    return () => { alive = false; clearInterval(id); };
  }, [loadCameras, selectCamera]);

  useNewEvents((event) => { setTicker((t) => [event, ...t].slice(0, 25)); loadCameras(); });

  const cam = cameras.find((c) => c.id === selectedId) || null;
  const st = cam ? (statuses[cam.id] || {}) : {};
  const running = !!(cam && st.running);

  const streamSrc = useMemo(
    () => (running ? bxApiUrl(`/streams/${cam.id}/${showProcessed ? 'processed' : 'raw'}?t=${Date.now()}`) : ''),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [running, cam?.id, showProcessed, streamNonce],
  );

  // Zone alert beep, only on the moment an alert starts.
  const za = running && st.zone_alerts ? st.zone_alerts : [];
  useEffect(() => {
    if (za.length > 0 && !zoneAlertOn.current) beep();
    zoneAlertOn.current = za.length > 0;
  }, [za.length]);

  const toggleRun = async () => {
    if (!cam) return;
    try { if (running) await api.post(`/cameras/${cam.id}/stop`); else await api.post(`/cameras/${cam.id}/activate`); } catch (e) { alert(e.message); }
    setStreamNonce((n) => n + 1); await loadCameras();
  };
  const toggleOverlay = async (endpoint, current) => {
    if (!cam) return;
    try { await api.post(`/cameras/${cam.id}/${endpoint}?on=${!current}`); } catch (e) { alert(e.message); }
    await loadCameras();
  };
  const deleteCamera = async () => {
    if (!cam) return;
    if (!confirm(`Delete camera "${cam.name}"? This also removes its zones, events and saved clips/snapshots.\n(The video file itself is not deleted - while it stays in sample_videos it will reappear as a new camera.)`)) return;
    try { await api.del(`/cameras/${cam.id}`); } catch (e) { alert(e.message); }
    setSelectedId(''); selectedRef.current = ''; localStorage.removeItem('liveCameraId');
    await loadCameras();
  };

  const groups = (st.groups && st.groups.length) ? st.groups.join(' + ') : 'none';
  const stats = [
    ['People in view', st.people_now || 0], ['Alone', st.individuals || 0], ['Groups', groups],
    ['Largest group', st.largest_group || 0],
    ['Weapons detected', st.weapons_now || 0, true], ['Armed people', st.armed_people || 0, true],
    ['Armed people seen', st.weapons_seen || 0, true], ['Fighting', st.fighting_now || 0, true],
    ['Fallen', st.fallen_now || 0, true], ['Running', st.running_now || 0], ['Jumping', st.jumping_now || 0],
    ['Unique people seen', st.unique_people || 0], ['Peak at once', st.peak_people || 0],
    ['Vehicles', st.vehicle_count || 0], ['FPS', (st.fps || 0).toFixed(1)],
  ];
  const counts = (running && st.behavior_counts) || {};
  const [tc, tn] = THREAT[st.threat_level] || THREAT.NORMAL;
  const people = st.people_now || 0;

  return (
    <>
      <div className="bx-section-title">
        <div className="bx-row bx-gap-12 bx-wrap">
          <span className="bx-tag">{cameras.length} video{cameras.length === 1 ? '' : 's'} available</span>
          <span className="bx-tag">{running ? `${people} ${people === 1 ? 'person' : 'people'} in view` : 'nothing playing'}</span>
        </div>
        <div className="bx-row bx-gap-8 bx-wrap">
          <button type="button" className="bx-btn" disabled={rescanBusy} title="Scan storage/sample_videos for new files now (also automatic every 15s)"
            onClick={() => rescanVideosFolder(setRescanBusy, loadCameras)}>
            {rescanBusy ? 'Scanning...' : '↻ Rescan videos folder'}
          </button>
          <button type="button" className="bx-btn bx-btn-primary" onClick={() => setAddOpen(true)}>+ Add camera</button>
        </div>
      </div>

      <div className="bx-card bx-mb-16">
        <label className="bx-field" style={{ margin: 0 }}>
          <span>Video (from <span className="bx-mono">backend/storage/sample_videos</span> - new files appear here automatically)</span>
          <select className="bx-input" value={selectedId} onChange={(e) => selectCamera(e.target.value)}>
            <option value="">— Select a video to play (all others stay stopped) —</option>
            {cameras.map((c) => (
              <option key={c.id} value={c.id}>{statuses[c.id] && statuses[c.id].running ? '▶ ' : ''}{c.name}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="bx-two-col">
        <div className="bx-tile">
          {za.length > 0 && <div className="bx-zone-bar">⚠ ZONE ALERT — {za.join('  |  ')}</div>}
          <div className="bx-video-wrap" style={{ aspectRatio: '16/9', maxHeight: '72vh' }}>
            <div style={{ width: '100%', height: '100%' }}>
              {running && <img src={streamSrc} alt={cam.name} style={{ width: '100%', height: '100%', objectFit: 'contain' }} />}
              {!running && starting && <div style={stageMsg}><div style={{ fontSize: 28 }}>⏳</div>Starting analysis (the first start loads the AI models and can take a minute)...</div>}
              {!running && !starting && cam && <div style={stageMsg}><div style={{ fontSize: 28 }}>⏸</div>Stopped — press Start to analyse this video</div>}
              {!running && !starting && !cam && <div style={stageMsg}><div style={{ fontSize: 28 }}>🎬</div>Select a video from the dropdown above</div>}
            </div>
            <div className="bx-live-badge">
              <span className={running ? 'bx-dot-live' : 'bx-dot-off'} /> {running ? 'LIVE' : 'STOPPED'}
            </div>
          </div>

          <div className="bx-tile-meta">
            <div>
              <div className="name">{cam ? cam.name : 'No video selected'}</div>
              <div className="loc">{cam ? (cam.location || cam.source) : 'Pick a video from the list above - only that video is analysed, so CPU use stays low.'}</div>
            </div>
            <div className="bx-row bx-gap-8 bx-wrap">
              {running && <button type="button" className={`bx-btn bx-btn-sm${st.heatmap_overlay ? ' bx-btn-primary' : ''}`} title="Show where people spend time (hot = most time)" onClick={() => toggleOverlay('heatmap', st.heatmap_overlay)}>Heatmap</button>}
              <button type="button" className="bx-btn bx-btn-sm" title="Turn the alert beep on or off"
                onClick={() => { setSound(!soundOn()); setSoundState(soundOn()); if (soundOn()) beep(); }}>
                {soundState ? '🔔 Sound on' : '🔕 Sound off'}
              </button>
              {running && <button type="button" className={`bx-btn bx-btn-sm${st.debug_overlay ? ' bx-btn-primary' : ''}`} title="Draw every raw AI detection with its class and confidence - shows what the model really sees" onClick={() => toggleOverlay('debug-overlay', st.debug_overlay)}>AI detections</button>}
              {running && <button type="button" className="bx-btn bx-btn-sm" onClick={() => setShowProcessed((v) => !v)}>{showProcessed ? 'Show original' : 'Show processed'}</button>}
              {cam && <button type="button" className={`bx-btn bx-btn-sm${running ? '' : ' bx-btn-primary'}`} onClick={toggleRun}>{running ? 'Stop' : 'Start'}</button>}
              {cam && <button type="button" className="bx-btn bx-btn-sm" onClick={() => navigate(`/branch-exterior/regions?camera=${cam.id}`)}>Regions</button>}
              {cam && <button type="button" className="bx-btn bx-btn-sm bx-btn-ghost" onClick={deleteCamera}>Delete</button>}
            </div>
          </div>

          {running && (
            <div style={{ margin: '6px 16px 2px' }}>
              <span style={{ display: 'inline-block', background: tc, color: '#fff', fontWeight: 700, padding: '5px 14px', borderRadius: 99, animation: st.threat_level === 'CRITICAL' ? 'bx-pulse 1s infinite' : undefined }}>THREAT LEVEL: {tn}</span>
              <span style={{ fontSize: 13, marginLeft: 8 }}>{st.threat_reasons && st.threat_reasons.length ? `— ${st.threat_reasons.join(', ')}` : ''}</span>
              {st.prep_info && <span className="bx-muted" style={{ fontSize: 11, marginLeft: 10 }}>(picture: {st.prep_info})</span>}
            </div>
          )}
          {running && (
            <div className="bx-muted" style={{ padding: '4px 16px 6px', fontSize: 12 }}>
              Engine: <b>{st.detector || 'starting...'}</b>{st.pose_active ? ' + RTMPose' : ''}<br />
              Weapons: <b>{st.weapon_engine || '...'}</b>
              {st.weapon_labels && st.weapon_labels.length > 0 && <> — <b style={{ color: '#ef4444' }}>{st.weapon_labels.join(', ').toUpperCase()}</b></>}
            </div>
          )}
          {running && st.features && st.features.length > 0 && (
            <div style={{ padding: '0 16px 6px', display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {st.features.map((f) => <span key={f} className="bx-tag" style={{ fontSize: 11, whiteSpace: 'normal' }}>{f}</span>)}
            </div>
          )}
          {st.last_error && <div style={{ padding: '0 16px 6px', fontSize: 12, color: 'var(--bx-red)' }}>{st.last_error}</div>}
          <div className="bx-stat-grid">
            {stats.map(([k, v, threat]) => (
              <div key={k} className={`bx-stat${threat && Number(v) > 0 ? ' hot' : ''}`}>
                <div className="k">{k}</div><div className="v">{v}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="bx-card">
          <div className="bx-card-title">Live alert ticker</div>
          <div className="bx-ticker">
            {ticker.length === 0 && <Empty icon="🕑" bare>Waiting for events...</Empty>}
            {ticker.map((e) => (
              <div key={e.id} className={`bx-ticker-item sev-${e.severity}`}>
                <div className="top"><span className="cam">{e.camera_name}</span><span className="time">{timeAgo(e.created_at)}</span></div>
                <div className="msg">{e.message}</div>
                <div style={{ marginTop: 5 }}><span className={`bx-badge sev-${e.severity}`}>{e.severity}</span> <span className="bx-tag">{e.scenario}</span></div>
              </div>
            ))}
          </div>
          <div className="bx-card-title" style={{ marginTop: 18 }}>What the AI watches for <span className="bx-muted" style={{ fontWeight: 400 }}>(incidents this video)</span></div>
          <div>
            {RULES.map(([k, name, desc]) => {
              const n = counts[k] || 0;
              return (
                <div key={k} className="bx-rule" title={desc}>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: n ? 700 : 500, color: n ? '#ef4444' : undefined }}>{name}</div>
                    <div className="bx-muted" style={{ fontSize: 11 }}>{desc}</div>
                  </div>
                  <span className={`bx-tag${n ? ' bx-tag-hot' : ''}`} style={{ alignSelf: 'center' }}>{n}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {addOpen && <AddCameraModal onClose={() => setAddOpen(false)} onCreated={(created) => selectCamera(created.id)} />}
    </>
  );
}
