import { useCallback, useEffect, useRef, useState } from 'react';
import { api, bxApiUrl, bxUrl } from '../api.js';
import AddCameraModal, { rescanVideosFolder } from '../components/AddCameraModal.jsx';
import Modal from '../components/Modal.jsx';
import { Empty } from '../components/ui.jsx';

const PAGE_BUILD = 10; // must match BUILD in backend/app/api/routes/health.py

const ZONE_COLORS = {
  entrance: '#4a90e2', atm: '#2fb894', side_lane: '#e0a930',
  forecourt: '#9d7fe0', rear: '#e0a930', restricted: '#e2574a', other: '#8b98a9',
};
const ALERT_TEXT = {
  off: 'no zone alert (background rules only)',
  suspicious: 'alerts on SUSPICIOUS activity in / at this zone',
  enter: 'RESTRICTED: alerts on touch / entry + suspicious activity',
  near: 'RESTRICTED: alerts on approach / touch / entry + suspicious activity',
};
// Being in a zone is normal, so most zones only alert on SUSPICIOUS activity. Only truly restricted areas alert on touch / entry.
const TYPE_DEFAULT_ALERT = { atm: 'suspicious', entrance: 'suspicious', forecourt: 'suspicious', side_lane: 'suspicious', other: 'suspicious', rear: 'enter', restricted: 'enter' };
const HINT_PLAY = 'The video is playing. Press Pause (or click "Draw new zone") on a frame where the area is visible, then click at least 3 points around it.';
const HINT_IDLE = 'The video plays here. Press Pause (or just click "Draw new zone") when the area you want is visible, then click at least 3 points around it.';

const fmtClock = (sec) => {
  if (!Number.isFinite(sec)) return '0:00';
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};

function drawPolygon(ctx, pts, color, label, dashed) {
  if (pts.length < 2) {
    if (pts.length === 1) { ctx.fillStyle = color; ctx.beginPath(); ctx.arc(pts[0].x, pts[0].y, 4, 0, 7); ctx.fill(); }
    return;
  }
  ctx.beginPath();
  ctx.moveTo(pts[0].x, pts[0].y);
  pts.slice(1).forEach((p) => ctx.lineTo(p.x, p.y));
  ctx.closePath();
  ctx.fillStyle = `${color}33`; ctx.fill();
  ctx.strokeStyle = color; ctx.lineWidth = 2;
  ctx.setLineDash(dashed ? [6, 4] : []); ctx.stroke(); ctx.setLineDash([]);
  pts.forEach((p) => { ctx.fillStyle = color; ctx.beginPath(); ctx.arc(p.x, p.y, 3.5, 0, 7); ctx.fill(); });
  if (label) {
    ctx.fillStyle = '#fff'; ctx.font = 'bold 12px sans-serif';
    ctx.shadowColor = '#000'; ctx.shadowBlur = 3;
    ctx.fillText(label, pts[0].x + 6, pts[0].y - 6);
    ctx.shadowBlur = 0;
  }
}

function nearestEdge(pts, p) {
  let best = { i: -1, d: 1e9, pt: null };
  const n = pts.length;
  for (let i = 0; i < n; i++) {
    const a = pts[i]; const b = pts[(i + 1) % n];
    const dx = b.x - a.x; const dy = b.y - a.y; const len2 = dx * dx + dy * dy || 1;
    const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2));
    const q = { x: a.x + t * dx, y: a.y + t * dy };
    const d = Math.hypot(p.x - q.x, p.y - q.y);
    if (d < best.d) best = { i, d, pt: q };
  }
  return best;
}

// Turn the outline (canvas pixels) into 0..1 fractions; refuse anything that is not a clean number so the server never gets NaN / null.
function cleanPolygon(pts, w, h) {
  if (!(w > 0 && h > 0)) return null;
  const out = pts.map((p) => ({ x: Math.min(1, Math.max(0, p.x / w)), y: Math.min(1, Math.max(0, p.y / h)) }));
  return out.every((p) => Number.isFinite(p.x) && Number.isFinite(p.y)) && out.length >= 3 ? out : null;
}

// ---------------------------------------------------------------- zone dialog --
function ZoneModal({ editing, onBack, onSave }) {
  const z = editing || {};
  const [name, setName] = useState(z.name || '');
  const [type, setType] = useState(z.zone_type || 'atm');
  const [alertMode, setAlertMode] = useState(editing ? (z.alert_mode || 'off') : (TYPE_DEFAULT_ALERT[z.zone_type || 'atm'] || 'suspicious'));
  const [sev, setSev] = useState(z.alert_severity || 'high');
  const [restricted, setRestricted] = useState(!!z.restricted);
  const [busy, setBusy] = useState(false);

  const changeType = (t) => { setType(t); if (!editing) setAlertMode(TYPE_DEFAULT_ALERT[t] || 'suspicious'); };
  const save = async () => {
    setBusy(true);
    await onSave({
      name: name.trim() || (editing ? editing.name : 'Unnamed zone'),
      zone_type: type,
      restricted: restricted || type === 'restricted',
      alert_mode: alertMode,
      alert_severity: sev,
    });
    setBusy(false);
  };

  return (
    <Modal
      title={editing ? 'Edit zone' : 'New zone'}
      onClose={onBack}
      footer={(
        <>
          <button type="button" className="bx-btn" onClick={onBack}>← Back to the outline</button>
          <button type="button" className="bx-btn bx-btn-primary" disabled={busy} onClick={save}>{editing ? 'Save changes' : 'Save zone'}</button>
        </>
      )}
    >
      <label className="bx-field">Zone name
        <input className="bx-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. ATM front" autoComplete="off" autoFocus />
      </label>
      <label className="bx-field">Zone type
        <select className="bx-input" value={type} onChange={(e) => changeType(e.target.value)}>
          <option value="entrance">Entrance / gate</option>
          <option value="atm">ATM area</option>
          <option value="side_lane">Side lane</option>
          <option value="forecourt">Forecourt / parking</option>
          <option value="rear">Rear access</option>
          <option value="restricted">Restricted (after-hours intrusion applies)</option>
          <option value="other">Other</option>
        </select>
      </label>
      <label className="bx-field">When should this zone raise an alert?
        <select className="bx-input" value={alertMode} onChange={(e) => setAlertMode(e.target.value)}>
          <option value="suspicious">Suspicious activity only (recommended)</option>
          <option value="enter">Restricted area - also the moment anyone touches or enters it</option>
          <option value="near">Restricted area - also when anyone comes near it</option>
          <option value="off">Off - background rules only, no zone alert</option>
        </select>
      </label>
      <label className="bx-field">Alert severity
        <select className="bx-input" value={sev} onChange={(e) => setSev(e.target.value)}>
          <option value="low">Low</option><option value="medium">Medium</option>
          <option value="high">High (a snapshot + clip are saved)</option><option value="critical">Critical (a snapshot + clip are saved)</option>
        </select>
      </label>
      <div className="bx-hint">
        <b>Suspicious activity</b> = a weapon, a fight, 3+ people gathering at the zone for 15+ seconds, repeatedly looking toward it, running toward it, jumping, climbing, hands working on it, or any behaviour rule firing for someone there.
        Just walking in or standing there does <b>not</b> alert, which keeps false alarms down. When it fires: the zone flashes red, a red ZONE ALERT bar and a beep appear on Live Monitoring, and the event is saved with its evidence.
        Use the restricted options only for areas nobody should enter.
      </div>
      <label className="bx-check" style={{ marginTop: 12 }}>
        <input type="checkbox" checked={restricted} onChange={(e) => setRestricted(e.target.checked)} />
        Treat as a restricted area (after-hours intrusion, stricter loitering threshold)
      </label>
    </Modal>
  );
}

// ---------------------------------------------------------------- page --
export default function RegionsZonesPage() {
  const [cameras, setCameras] = useState([]);
  const [statuses, setStatuses] = useState({});
  const [cameraId, setCameraId] = useState(null);
  const [zones, setZones] = useState([]);
  const [mediaMode, setMediaModeState] = useState('none'); // video | still | live | none
  const [prepInfo, setPrepInfo] = useState(null);
  const [liveTest, setLiveTestState] = useState(false);
  const [liveBusy, setLiveBusy] = useState(false);
  const [hint, setHint] = useState('');
  const [mediaDiag, setMediaDiag] = useState(null);
  const [buildWarning, setBuildWarning] = useState(null);
  const [buildInfo, setBuildInfo] = useState('');
  const [paused, setPaused] = useState(false);
  const [clock, setClock] = useState({ pos: 0, label: '0:00 / 0:00' });
  const [framePos, setFramePos] = useState(15);
  const [ui, setUi] = useState({ drawing: false, n: 0, adjusting: false, editing: false });
  const [zoneModal, setZoneModal] = useState(null);
  const [addOpen, setAddOpen] = useState(false);
  const [rescanBusy, setRescanBusy] = useState(false);
  const [canvasTitle, setCanvasTitle] = useState('Camera view - click points to trace a zone boundary, then press "Finish zone"');

  // mutable drawing state (kept in refs so canvas handlers always see the latest values)
  const R = useRef({
    drawing: false, drawPoints: [], editingZoneId: null, editOriginal: null, redrawMode: false,
    dragIndex: -1, hoverIndex: -1, justDragged: false, canvasSize: { w: 0, h: 0 },
    zones: [], liveTest: false, mediaMode: 'none', cameraId: null, prepInfo: null, pending: null,
  });
  const videoRef = useRef(null);
  const frameRef = useRef(null);
  const stageRef = useRef(null);
  const canvasRef = useRef(null);
  const posTimer = useRef(null);
  const fn = useRef({});

  const setMediaMode = (m) => { R.current.mediaMode = m; setMediaModeState(m); };
  const setLiveTest = (v) => { R.current.liveTest = v; setLiveTestState(v); };
  const setZoneList = (z) => { R.current.zones = z; setZones(z); };
  const curCam = () => cameras.find((c) => c.id === R.current.cameraId) || null;
  const syncUi = () => {
    const r = R.current;
    setUi({ drawing: r.drawing, n: r.drawPoints.length, adjusting: !!r.editingZoneId && !r.redrawMode, editing: !!r.editingZoneId });
  };

  // ---- build check -----------------------------------------------------
  const checkBuild = useCallback(async () => {
    try {
      const h = await api.get('/health');
      setBuildInfo(`page build ${PAGE_BUILD} · server build ${h.build || 'old (before 6)'}`);
      if (h.zone_schema && (!h.zone_schema.ok || !(h.zone_schema.modes || []).includes('suspicious'))) {
        setBuildWarning(<><b>The server&apos;s zone settings are out of date</b> - it does not accept the new alert rules, so saving a zone will fail with &quot;422&quot;. Replace <code>backend/app/schemas/zone.py</code> with the latest one and restart the server.{h.zone_schema.error ? <span className="bx-muted"> ({h.zone_schema.error})</span> : null}</>);
      } else if (h.missing_routes && h.missing_routes.length) {
        setBuildWarning(<><b>The server is missing API routes this page needs:</b> {h.missing_routes.map((r) => <code key={r} style={{ marginRight: 6 }}>{r}</code>)}. Copy the latest <code>backend/app/main.py</code> (and the route files) over the project the server runs from and restart it.</>);
      } else if (!h.build || h.build < PAGE_BUILD) {
        setBuildWarning(<><b>The server is running OLDER backend files than this page needs.</b> Copy the <code>backend</code> files from the latest zip into the project the server runs from, then restart it.</>);
      } else setBuildWarning(null);
    } catch {
      setBuildInfo(`page build ${PAGE_BUILD} · server not reachable`);
      setBuildWarning(<><b>Cannot reach the server.</b> Is it running? (<code>python -m uvicorn app.main:app --port 8011</code> in backend/use_cases/branch_exterior)</>);
    }
  }, []);

  // ---- canvas ------------------------------------------------------------
  const redrawCanvas = () => {
    const canvas = canvasRef.current; if (!canvas) return;
    const r = R.current;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (r.liveTest) return; // the server draws the zones itself on the live picture
    r.zones.forEach((z) => {
      if (z.id === r.editingZoneId) return; // shown as the editable outline below
      drawPolygon(ctx, z.polygon.map((p) => ({ x: p.x * canvas.width, y: p.y * canvas.height })),
        ZONE_COLORS[z.zone_type] || '#888', z.name + (z.alert_mode !== 'off' ? '  \u26A0' : ''));
    });
    if (r.drawing && r.drawPoints.length) {
      const ez = r.editingZoneId ? r.zones.find((q) => q.id === r.editingZoneId) : null;
      drawPolygon(ctx, r.drawPoints, ez ? (ZONE_COLORS[ez.zone_type] || '#ffffff') : '#ffffff', ez ? `${ez.name} (editing)` : 'new zone', !ez);
      if (ez && !r.redrawMode) { // big white handles you can grab
        r.drawPoints.forEach((p, i) => {
          ctx.beginPath(); ctx.arc(p.x, p.y, i === r.hoverIndex || i === r.dragIndex ? 9 : 7, 0, 7);
          ctx.fillStyle = '#ffffff'; ctx.fill(); ctx.lineWidth = 2; ctx.strokeStyle = '#111'; ctx.stroke();
        });
      }
    } else if (r.pending) { // the zone dialog is open: keep the outline visible
      drawPolygon(ctx, r.pending.pts, '#ffffff', r.pending.label, true);
    }
  };

  const refreshCanvasSize = () => {
    const stage = stageRef.current; const canvas = canvasRef.current; if (!stage || !canvas) return;
    const r = R.current;
    const rect = stage.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) return;
    const nw = Math.round(rect.width); const nh = Math.round(rect.height);
    if (r.canvasSize.w && (nw !== r.canvasSize.w || nh !== r.canvasSize.h)) { // window resized while drawing / editing: keep the outline on the same spot
      const sc = (p) => ({ x: (p.x * nw) / r.canvasSize.w, y: (p.y * nh) / r.canvasSize.h });
      r.drawPoints = r.drawPoints.map(sc);
      if (r.editOriginal) r.editOriginal = r.editOriginal.map(sc);
      if (r.pending) r.pending = { ...r.pending, pts: r.pending.pts.map(sc) };
    }
    r.canvasSize = { w: nw, h: nh };
    canvas.width = nw; canvas.height = nh;
    canvas.style.width = `${rect.width}px`; canvas.style.height = `${rect.height}px`;
    redrawCanvas();
  };

  const setMode = (mode) => { setMediaMode(mode); setTimeout(refreshCanvasSize, 0); };

  // ---- drawing actions -----------------------------------------------------
  const cancelDrawing = (msg) => {
    const r = R.current;
    r.drawing = false; r.drawPoints = []; r.editingZoneId = null; r.editOriginal = null; r.redrawMode = false; r.dragIndex = -1; r.hoverIndex = -1; r.pending = null;
    syncUi();
    if (msg) setHint(msg);
    redrawCanvas();
  };

  const startDrawing = () => {
    const r = R.current;
    if (!r.cameraId) { alert('Choose a video or camera first.'); return; }
    if (r.liveTest) { alert("Stop the live test first (press 'Back to picture'), then draw."); return; }
    if (r.mediaMode === 'none') { alert('The picture is still loading (or could not load - see the red message above the picture).'); return; }
    if (r.mediaMode === 'video') { videoRef.current.pause(); setPaused(true); } // a moving picture is impossible to draw on
    refreshCanvasSize();
    r.editingZoneId = null; r.redrawMode = false; r.editOriginal = null; r.pending = null;
    r.drawing = true; r.drawPoints = [];
    setHint('Click at least 3 points around the area (e.g. the ATM, the gate), then press "Finish zone". Backspace removes the last point, Escape cancels.');
    syncUi(); redrawCanvas();
  };

  const finishDrawing = () => {
    const r = R.current; const canvas = canvasRef.current;
    const editId = r.editingZoneId;
    const editing = editId ? r.zones.find((q) => q.id === editId) : null;
    const pixelPts = r.drawPoints.map((p) => ({ ...p }));
    const normPoints = cleanPolygon(pixelPts, canvas.width, canvas.height);
    if (!normPoints) { alert('The zone outline could not be read (the picture may not be ready). Press Reload above the picture and try again.'); return; }
    const state = { editing, editId, normPoints, pixelPts, keepOriginal: r.editOriginal ? r.editOriginal.map((p) => ({ ...p })) : null, wasRedraw: r.redrawMode };
    // stop interactive drawing while the form is open, but keep the outline visible on the picture
    r.drawing = false; r.dragIndex = -1; r.hoverIndex = -1;
    r.pending = { pts: pixelPts, label: editing ? `${editing.name} (editing)` : 'new zone' };
    syncUi(); redrawCanvas();
    setZoneModal(state);
  };

  const backToOutline = () => {
    const r = R.current; const m = zoneModal; if (!m) return;
    setZoneModal(null);
    r.pending = null;
    r.drawing = true; r.drawPoints = m.pixelPts; r.editingZoneId = m.editId; r.editOriginal = m.keepOriginal; r.redrawMode = m.wasRedraw;
    setHint(m.editing ? `Editing "${m.editing.name}" - adjust the outline, then press "Finish zone" again.` : 'Add or undo points, then press "Finish zone" again.');
    syncUi(); redrawCanvas();
  };

  // Save a zone. If the server answers 422 (it rejected something), save in two steps so nothing is lost and the
  // message says exactly which part was refused. Returns "" when everything was saved, or a message when only part was.
  const saveZoneRequest = async (editing, body, polygon) => {
    const full = { ...body, polygon };
    try {
      if (editing) await api.patch(`/zones/${editing.id}`, full);
      else await api.post('/zones', { camera_id: R.current.cameraId, ...full });
      return '';
    } catch (e) {
      if (!/^422/.test(String(e.message))) throw e;
      const base = { name: body.name, zone_type: body.zone_type, restricted: body.restricted, polygon };
      const alerts = { alert_mode: body.alert_mode, alert_severity: body.alert_severity };
      let id = editing ? editing.id : null;
      if (editing) await api.patch(`/zones/${id}`, base);
      else id = (await api.post('/zones', { camera_id: R.current.cameraId, ...base })).id;
      try { await api.patch(`/zones/${id}`, alerts); return ''; } catch (e2) {
        return `The zone's outline, name and type were saved, but the server refused the alert rule:\n\n${e2.message}\n\nThis usually means backend/app/schemas/zone.py on the server is older than this page. Replace it with the latest one, restart the server, then use Edit zone to choose the alert rule again.`;
      }
    }
  };

  const saveZone = async (body) => {
    const m = zoneModal; if (!m) return;
    let partial = '';
    try { partial = await saveZoneRequest(m.editing, body, m.normPoints); } catch (e) {
      const missing = /^(404|405)/.test(String(e.message));
      alert(missing
        ? `Could not save the zone: the server has no zones API (${e.message}).\nCopy the latest backend/app/main.py over the project the server runs from, then restart it. The red box at the top of this page lists exactly what is missing.`
        : `Could not save the zone: ${e.message}`);
      return;
    }
    setZoneModal(null);
    cancelDrawing();
    setZoneList(await api.get(`/zones?camera_id=${R.current.cameraId}`));
    redrawCanvas();
    if (partial) { alert(partial); return; }
    setHint(m.editing ? "Zone updated. Press 'Live test' to see it react." : "Zone saved. Press 'Live test': the zone stays quiet for normal activity and flashes red when something suspicious happens at it.");
  };

  const editZone = (id) => {
    const r = R.current;
    const z = r.zones.find((q) => q.id === id); if (!z) return;
    if (r.drawing) { alert('Finish or cancel the zone you are working on first.'); return; }
    if (r.liveTest) { alert("Stop the live test first (press 'Back to picture'), then edit."); return; }
    if (r.mediaMode === 'none') { alert('The picture is still loading (or could not load - see the red message above the picture).'); return; }
    if (r.mediaMode === 'video') { videoRef.current.pause(); setPaused(true); }
    refreshCanvasSize();
    const c = canvasRef.current;
    r.editingZoneId = id; r.redrawMode = false; r.hoverIndex = -1; r.dragIndex = -1; r.pending = null;
    r.drawPoints = z.polygon.map((p) => ({ x: p.x * c.width, y: p.y * c.height }));
    r.editOriginal = r.drawPoints.map((p) => ({ ...p }));
    r.drawing = true;
    setHint(`Editing "${z.name}": drag a white dot to move it, click on an edge to add a dot, right-click a dot to remove it. Press "Finish zone" to change the name, type and alert rule. "Redraw from scratch" starts the outline again.`);
    syncUi(); redrawCanvas();
    if (c.scrollIntoView) c.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  const deleteZone = async (id) => {
    if (!confirm('Delete this zone?')) return;
    try { await api.del(`/zones/${id}`); } catch (e) { alert(e.message); }
    setZoneList(await api.get(`/zones?camera_id=${R.current.cameraId}`));
    redrawCanvas();
  };

  const armAllZones = async () => {
    for (const z of R.current.zones.filter((q) => (q.alert_mode || 'off') === 'off')) {
      try {
        await api.patch(`/zones/${z.id}`, { alert_mode: TYPE_DEFAULT_ALERT[z.zone_type] || 'suspicious', alert_severity: z.alert_severity || 'high' });
      } catch (e) { alert(`Could not update a zone: ${e.message}`); return; }
    }
    setZoneList(await api.get(`/zones?camera_id=${R.current.cameraId}`));
    redrawCanvas();
  };

  const undoOrReset = () => {
    const r = R.current;
    if (r.editingZoneId && !r.redrawMode && r.editOriginal) r.drawPoints = r.editOriginal.map((p) => ({ ...p })); // Reset shape
    else r.drawPoints.pop();
    syncUi(); redrawCanvas();
  };
  const redrawFromScratch = () => {
    const r = R.current;
    r.redrawMode = true; r.drawPoints = []; r.hoverIndex = -1;
    setHint('Click at least 3 points to trace the zone again, then press "Finish zone".');
    syncUi(); redrawCanvas();
  };

  // ---- media: playing video / still / live ------------------------------------
  const useStill = async (message) => {
    const r = R.current; if (!r.prepInfo) return;
    const img = frameRef.current;
    const pos = (parseInt(framePos, 10) || 0) / 100;
    img.onload = () => { setMode('still'); if (message) setHint(message); };
    img.onerror = () => { setMediaDiag(<b>Could not read a picture from this video / camera. Check that the file exists, or that the camera address and login are right.</b>); };
    img.src = bxApiUrl(`/cameras/${r.cameraId}/frame?pos=${pos}&t=${Date.now()}`);
  };
  fn.current.useStill = useStill;

  const loadMedia = async () => {
    const r = R.current;
    setMediaDiag(null);
    const v = videoRef.current;
    v.pause(); v.removeAttribute('src'); v.load();
    frameRef.current.removeAttribute('src');
    r.prepInfo = null; setPrepInfo(null);
    setMode('none');
    setHint('Loading the video...');
    let info = null;
    const cid = r.cameraId;
    try {
      info = await api.get(`/cameras/${cid}/prep`);
    } catch (e) {
      const notFound = String(e.message).startsWith('404') || String(e.message).startsWith('405');
      setMediaDiag(notFound
        ? <><b>The server has no <code>/cameras/&lt;id&gt;/prep</code> route</b> - it is running OLD backend files. Copy the latest <code>backend</code> files over the project the server runs from and restart it.</>
        : <><b>Could not prepare this video:</b> {e.message}</>);
      return;
    }
    if (cid !== r.cameraId) return; // another camera was picked meanwhile
    if (!info.ok) { setMediaDiag(<b>{info.error}</b>); setHint(info.error); return; }
    r.prepInfo = info; setPrepInfo(info);
    setPaused(false);
    if (info.video_url) {
      v.onloadeddata = () => {
        setMode('video');
        v.play().catch(() => setPaused(true));
        setHint(HINT_PLAY);
      };
      v.onerror = () => { useStill('This browser could not play the video file, so a still picture is shown instead - use the slider to pick a moment.'); };
      v.src = bxUrl(info.video_url);
      v.load();
      // if it has not started within 6 s, fall back to a still picture
      setTimeout(() => { if (R.current.mediaMode === 'none' && R.current.cameraId === cid) useStill('The video took too long to load - showing a still picture instead.'); }, 6000);
    } else {
      await useStill(info.kind === 'live' ? "Live cameras show a still picture; use 'Live test' to see the analysed stream." : '');
    }
  };

  const stopLiveTest = async (silent) => {
    setLiveTest(false);
    setCanvasTitle('Camera view - click points to trace a zone boundary, then press "Finish zone"');
    if (!silent) await loadMedia();
  };

  const loadCameraView = async (id) => {
    const r = R.current;
    if (r.liveTest) await stopLiveTest(true);
    r.cameraId = id; setCameraId(id);
    localStorage.setItem('regionsCameraId', id);
    r.drawing = false; r.drawPoints = []; r.editingZoneId = null; r.editOriginal = null; r.pending = null;
    syncUi();
    try {
      setZoneList(await api.get(`/zones?camera_id=${id}`));
    } catch (e) {
      setZoneList([]);
      setBuildWarning(<><b>Could not load zones ({e.message}).</b> The server does not have the zones API registered - copy the latest <code>backend/app/main.py</code> and restart it.</>);
    }
    await loadMedia();
  };

  const loadCameraList = async (keepSelection) => {
    const cams = await api.get('/cameras');
    let st = {};
    try { st = await api.get('/cameras/status/all'); } catch { st = {}; }
    setCameras(cams); setStatuses(st);
    if (cams.length === 0) { R.current.cameraId = null; setCameraId(null); return; }
    const want = (keepSelection && R.current.cameraId) || new URLSearchParams(window.location.search).get('camera')
      || localStorage.getItem('regionsCameraId') || localStorage.getItem('liveCameraId');
    const pick = cams.some((c) => c.id === want) ? want : cams[0].id;
    if (pick !== R.current.cameraId) await loadCameraView(pick);
    else setCameraId(pick);
  };

  // ---- live test ---------------------------------------------------------------------
  const startLiveTest = async () => {
    const cam = curCam();
    if (!cam) { alert('Choose a video or camera first.'); return; }
    if (!R.current.zones.length) { alert('Draw at least one zone first.'); return; }
    if (R.current.drawing) cancelDrawing();
    setLiveBusy(true);
    try {
      await api.post(`/cameras/${cam.id}/activate`); // starts this video; every other one is stopped
      setLiveTest(true);
      videoRef.current.pause();
      frameRef.current.src = bxApiUrl(`/streams/${cam.id}/processed?t=${Date.now()}`);
      setMode('live');
      setCanvasTitle('LIVE TEST - the analysed video; a zone flashes red when a person touches / enters / comes near it');
      setHint('The first start loads the AI models and can take a minute. Zones refresh within 5 seconds of saving.');
      await refreshCanvasSize();
    } catch (e) { alert(`Could not start the live test: ${e.message}`); } finally { setLiveBusy(false); }
  };

  // ---- effects ---------------------------------------------------------------------------
  useEffect(() => {
    checkBuild();
    loadCameraList(false).catch((e) => setMediaDiag(<b>Could not load the video list: {e.message}</b>));
    const id = setInterval(async () => { // keep the "ALERTING NOW" badges and the red bar fresh
      try { setStatuses(await api.get('/cameras/status/all')); } catch { /* ignore */ }
    }, 1500);
    return () => { clearInterval(id); clearTimeout(posTimer.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const stage = stageRef.current; if (!stage) return undefined;
    const ro = new ResizeObserver(() => refreshCanvasSize());
    ro.observe(stage);
    const onResize = () => { if (R.current.cameraId) refreshCanvasSize(); };
    window.addEventListener('resize', onResize);
    return () => { ro.disconnect(); window.removeEventListener('resize', onResize); };
  }, []);

  // video time label
  useEffect(() => {
    const v = videoRef.current; if (!v) return undefined;
    const onTime = () => {
      if (!v.duration) return;
      setClock({ pos: Math.round((v.currentTime / v.duration) * 1000), label: `${fmtClock(v.currentTime)} / ${fmtClock(v.duration)}` });
    };
    v.addEventListener('timeupdate', onTime);
    return () => v.removeEventListener('timeupdate', onTime);
  }, []);

  // mouse / keyboard drawing handlers
  useEffect(() => {
    const zc = canvasRef.current; if (!zc) return undefined;
    const r = R.current;
    const pos = (e) => {
      const b = zc.getBoundingClientRect();
      return { x: Math.max(0, Math.min(zc.width, e.clientX - b.left)), y: Math.max(0, Math.min(zc.height, e.clientY - b.top)) };
    };
    const hit = (p, rad) => {
      for (let i = r.drawPoints.length - 1; i >= 0; i--) if (Math.hypot(r.drawPoints[i].x - p.x, r.drawPoints[i].y - p.y) <= (rad || 11)) return i;
      return -1;
    };
    const adjusting = () => r.drawing && !!r.editingZoneId && !r.redrawMode;

    const onDown = (e) => { if (!adjusting()) return; const i = hit(pos(e)); if (i >= 0) { r.dragIndex = i; e.preventDefault(); } };
    const onMove = (e) => {
      if (!adjusting()) return;
      const p = pos(e);
      if (r.dragIndex >= 0) { r.drawPoints[r.dragIndex] = p; r.justDragged = true; redrawCanvas(); return; }
      const hv = hit(p);
      if (hv !== r.hoverIndex) { r.hoverIndex = hv; zc.style.cursor = hv >= 0 ? 'grab' : 'crosshair'; redrawCanvas(); }
    };
    const onUp = () => {
      if (r.dragIndex >= 0) { r.dragIndex = -1; syncUi(); redrawCanvas(); setTimeout(() => { r.justDragged = false; }, 0); }
    };
    const onClick = (e) => {
      if (!r.drawing) return;
      if (r.justDragged) { r.justDragged = false; return; } // the click that ends a drag must not add a point
      const p = pos(e);
      if (adjusting()) { // click on an edge = add a point there
        const ed = nearestEdge(r.drawPoints, p);
        if (hit(p) < 0 && ed.d <= 12) r.drawPoints.splice(ed.i + 1, 0, ed.pt);
      } else r.drawPoints.push(p);
      syncUi(); redrawCanvas();
    };
    const onCtx = (e) => { // right-click a dot = remove it
      if (!adjusting()) return;
      e.preventDefault();
      const i = hit(pos(e)); if (i < 0) return;
      if (r.drawPoints.length <= 3) { alert('A zone needs at least 3 points.'); return; }
      r.drawPoints.splice(i, 1); r.hoverIndex = -1;
      syncUi(); redrawCanvas();
    };
    const onKey = (e) => {
      if (!r.drawing) return;
      const tag = (e.target && e.target.tagName) || '';
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
      if (e.key === 'Escape') cancelDrawing('Cancelled.');
      if (e.key === 'Backspace') { e.preventDefault(); if (!adjusting()) { r.drawPoints.pop(); syncUi(); redrawCanvas(); } }
      if (e.key === 'Enter' && r.drawPoints.length >= 3) { e.preventDefault(); finishDrawing(); }
    };
    zc.addEventListener('mousedown', onDown); zc.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp); zc.addEventListener('click', onClick);
    zc.addEventListener('contextmenu', onCtx); document.addEventListener('keydown', onKey);
    return () => {
      zc.removeEventListener('mousedown', onDown); zc.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp); zc.removeEventListener('click', onClick);
      zc.removeEventListener('contextmenu', onCtx); document.removeEventListener('keydown', onKey);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // keep the canvas cursor right
  useEffect(() => { if (canvasRef.current) canvasRef.current.style.cursor = ui.drawing ? 'crosshair' : 'default'; }, [ui.drawing]);

  // ---- derived ---------------------------------------------------------------------------
  const st = statuses[cameraId] || {};
  const alerting = (st.zone_alerts || []).join(' | ');
  const za = st.running && st.zone_alerts ? st.zone_alerts : [];
  const offCount = zones.filter((z) => (z.alert_mode || 'off') === 'off').length;
  const playControls = mediaMode === 'video';
  const diags = [buildWarning, mediaDiag].filter(Boolean);

  let stageStyle = { position: 'relative', width: '100%', aspectRatio: '16/9', overflow: 'hidden', background: 'var(--bx-stage)' };
  let videoStyle = { position: 'absolute', objectFit: 'fill', maxWidth: 'none', display: mediaMode === 'video' ? 'block' : 'none' };
  if (prepInfo && prepInfo.crop) {
    // The stage has the aspect ratio of the CROPPED analysis picture; the playing <video> is scaled and shifted inside it so only the
    // cropped part shows. Zones are fractions of this stage = fractions of the analysed picture, so they line up with what the AI sees.
    const [x1, y1, x2, y2] = prepInfo.crop;
    const cw = x2 - x1; const ch = y2 - y1;
    stageStyle = { ...stageStyle, aspectRatio: `${cw} / ${ch}`, width: `min(100%, ${((76 * cw) / ch).toFixed(2)}vh)` };
    videoStyle = { ...videoStyle, width: `${(prepInfo.source_w / cw) * 100}%`, height: `${(prepInfo.source_h / ch) * 100}%`, left: `${(-x1 / cw) * 100}%`, top: `${(-y1 / ch) * 100}%` };
  }

  const counterText = ui.adjusting ? `${ui.n} points` : (ui.n < 3 ? `${ui.n} point${ui.n === 1 ? '' : 's'} (need at least 3)` : `${ui.n} points - ready`);

  return (
    <>
      <div className="bx-card bx-mb-16">
        <div className="bx-row bx-gap-12 bx-wrap" style={{ alignItems: 'flex-end' }}>
          <label className="bx-field" style={{ flex: 1, minWidth: 280, margin: 0 }}>Video / camera (same list as Live Monitoring)
            <select className="bx-input" value={cameraId || ''} onChange={(e) => e.target.value && loadCameraView(e.target.value)}>
              {cameras.length === 0 && <option value="">No videos or cameras yet - use &quot;Add camera&quot; or put a video in storage/sample_videos</option>}
              {cameras.map((c) => <option key={c.id} value={c.id}>{statuses[c.id] && statuses[c.id].running ? '▶ ' : ''}{c.name}</option>)}
            </select>
          </label>
          <button type="button" className="bx-btn" disabled={rescanBusy} title="Scan storage/sample_videos for new files now (also automatic every 15s)"
            onClick={() => rescanVideosFolder(setRescanBusy, () => loadCameraList(true))}>{rescanBusy ? 'Scanning...' : '↻ Rescan videos folder'}</button>
          <button type="button" className="bx-btn bx-btn-primary" onClick={() => setAddOpen(true)}>+ Add camera</button>
        </div>
      </div>

      {diags.length > 0 && <div className="bx-diag">{diags.map((d, i) => <div key={i}>{d}</div>)}</div>}

      <div className="bx-section-title">
        <div className="bx-row bx-gap-12 bx-wrap">
          {playControls && (
            <>
              <button type="button" className="bx-btn" style={{ minWidth: 96 }}
                onClick={() => { const v = videoRef.current; if (v.paused) { v.play(); setPaused(false); } else { v.pause(); setPaused(true); } }}>
                {paused ? '▶ Play' : '⏸ Pause'}
              </button>
              <label className="bx-row bx-gap-12" style={{ minWidth: 260 }}>
                <input type="range" min="0" max="1000" value={clock.pos} style={{ flex: 1 }}
                  onChange={(e) => { const v = videoRef.current; if (v.duration) v.currentTime = (e.target.value / 1000) * v.duration; setClock((c) => ({ ...c, pos: Number(e.target.value) })); }} />
                <span className="bx-muted" style={{ fontSize: 12, minWidth: 84, textAlign: 'right' }}>{clock.label}</span>
              </label>
            </>
          )}
          {mediaMode === 'still' && prepInfo && prepInfo.kind === 'file' && (
            <label className="bx-field" style={{ margin: 0, minWidth: 220 }}>Moment in the video
              <input type="range" min="0" max="99" value={framePos}
                onChange={(e) => { setFramePos(e.target.value); clearTimeout(posTimer.current); posTimer.current = setTimeout(() => R.current.cameraId && fn.current.useStill(''), 350); }} />
            </label>
          )}
          <button type="button" className="bx-btn" onClick={() => R.current.cameraId && loadMedia()}>↻ Reload</button>
        </div>
        <div className="bx-row bx-gap-8 bx-wrap">
          <button type="button" className="bx-btn" disabled={liveBusy} title="Run the AI analysis on this video and watch your zones react"
            onClick={() => (liveTest ? stopLiveTest(false) : startLiveTest())}>
            {liveBusy ? 'Starting analysis...' : liveTest ? '■ Back to picture' : '▶ Live test'}
          </button>
          {ui.drawing && <span className="bx-tag">{counterText}</span>}
          {ui.drawing && <button type="button" className="bx-btn" onClick={undoOrReset}>{ui.adjusting ? 'Reset shape' : 'Undo last point'}</button>}
          {ui.adjusting && <button type="button" className="bx-btn" title="Throw away this outline and trace the zone again from scratch" onClick={redrawFromScratch}>Redraw from scratch</button>}
          {ui.drawing && <button type="button" className="bx-btn" onClick={() => cancelDrawing('Cancelled.')}>Cancel</button>}
          {ui.drawing && <button type="button" className="bx-btn bx-btn-primary" disabled={ui.n < 3} onClick={() => { if (R.current.drawPoints.length < 3) { alert('Add at least 3 points before finishing.'); return; } finishDrawing(); }}>✓ Finish zone</button>}
          {!ui.drawing && <button type="button" className="bx-btn bx-btn-primary" onClick={startDrawing}>+ Draw new zone</button>}
        </div>
      </div>

      <div className="bx-two-col">
        <div className="bx-card">
          <div className="bx-card-title">{canvasTitle}</div>
          {liveTest && za.length > 0 && <div className="bx-zone-bar" style={{ fontSize: 14, padding: 8, borderRadius: '6px 6px 0 0' }}>⚠ ZONE ALERT — {za.join(' | ')}</div>}
          <div className="bx-canvas-wrap">
            <div ref={stageRef} style={stageStyle}>
              <video ref={videoRef} muted loop playsInline preload="auto" style={videoStyle} />
              <img ref={frameRef} alt="camera picture" style={{ position: 'absolute', left: 0, top: 0, width: '100%', height: '100%', objectFit: 'fill', display: mediaMode === 'still' || mediaMode === 'live' ? 'block' : 'none' }} />
              <canvas ref={canvasRef} />
            </div>
          </div>
          <div className="bx-hint">{hint || HINT_IDLE}</div>
          <div className="bx-hint" style={{ marginTop: 6 }}>{buildInfo}</div>
        </div>
        <div className="bx-card">
          <div className="bx-card-title">Configured zones</div>
          {zones.length === 0 && <Empty icon="🗺️" bare>No zones for this video / camera yet.<br />Click &quot;Draw new zone&quot;.</Empty>}
          {zones.length > 0 && offCount > 0 && (
            <div className="bx-hint" style={{ marginBottom: 10 }}>{offCount} zone(s) have no alerts turned on.{' '}
              <button type="button" className="bx-btn bx-btn-sm bx-btn-primary" onClick={armAllZones}>Turn on suspicious-activity alerts for all</button>
            </div>
          )}
          {zones.map((z) => {
            const hot = st.running && (alerting.includes(`${z.name}: `) || alerting.includes(`${z.name} (`));
            return (
              <div key={z.id} className={`bx-zone-item${hot ? ' hot' : ''}`}>
                <div>
                  <span className="bx-swatch" style={{ background: ZONE_COLORS[z.zone_type] || '#888' }} />
                  <b>{z.name}</b> <span className="bx-tag">{z.zone_type}</span>{' '}
                  {z.restricted && <span className="bx-badge sev-critical">restricted</span>}{' '}
                  {hot && <span className="bx-badge sev-critical">ALERTING NOW</span>}
                  <div className="bx-muted" style={{ fontSize: 12, margin: '3px 0 0 20px' }}>
                    {z.alert_mode !== 'off' ? '⚠ ' : ''}{ALERT_TEXT[z.alert_mode || 'off']}{z.alert_mode !== 'off' ? ` · ${z.alert_severity || 'high'} severity` : ''}
                  </div>
                </div>
                <div className="bx-row bx-gap-8">
                  <button type="button" className="bx-btn bx-btn-sm bx-btn-primary" onClick={() => editZone(z.id)}>Edit zone</button>
                  <button type="button" className="bx-btn bx-btn-sm bx-btn-ghost" onClick={() => deleteZone(z.id)}>Delete</button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {zoneModal && <ZoneModal editing={zoneModal.editing} onBack={backToOutline} onSave={saveZone} />}
      {addOpen && (
        <AddCameraModal
          start={false} // only needs a picture to draw on - don't start analysing yet
          onClose={() => setAddOpen(false)}
          onCreated={async (created) => { R.current.cameraId = created.id; await loadCameraList(true); await loadCameraView(created.id); }}
        />
      )}
    </>
  );
}
