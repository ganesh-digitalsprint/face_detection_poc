import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Camera, Check, ImagePlus, Pencil, Plus, RefreshCw, Trash2, Undo2, Video, X } from 'lucide-react';
import { regionsRegistryApi } from '../../../api/regionsRegistry.js';
import { buildRegistryAdapter } from '../regionsAdapters.js';
const LegacyBranchRegionsZonesPage = lazy(() => import('./RegionsZonesPage.jsx'));
const BxLayout = lazy(() => import('../components/BxLayout.jsx'));

const btn = 'inline-flex items-center justify-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-50';
const input = 'mt-1 min-h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100';
const fieldLabel = 'block text-xs font-medium text-slate-600';
const slug = (value) => String(value || '').trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 39);

function browserTerminalId() {
  const key = 'fedbank-camera-terminal-id';
  try {
    let id = localStorage.getItem(key);
    if (!id) {
      id = `terminal-${globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`}`;
      localStorage.setItem(key, id);
    }
    return id;
  } catch {
    return `terminal-${globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`}`;
  }
}

function RegistrySetupDialog({ mode, location, useCase, onClose, onSaved }) {
  const [name, setName] = useState('');
  const [code, setCode] = useState('');
  const [sourceType, setSourceType] = useState('rtsp');
  const [connectionRef, setConnectionRef] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const save = async (event) => {
    event.preventDefault(); setError(''); setBusy(true);
    try {
      let createdLocation = null;
      if (mode === 'location') createdLocation = await regionsRegistryApi.post('/locations', { code: slug(code), name: name.trim() });
      else {
        const camera = await regionsRegistryApi.post('/cameras', { location_id: location.id, code: slug(code), name: name.trim() });
        const reference = sourceType === 'browser_webcam'
          ? `browser:${browserTerminalId()}:${slug(code) || 'camera'}`
          : connectionRef.trim();
        const source = await regionsRegistryApi.post('/sources', { camera_id: camera.id, source_type: sourceType, connection_ref: reference });
        await regionsRegistryApi.post('/assignments', { camera_id: camera.id, use_case: useCase.id, configuration: { source_id: source.id } });
      }
      await onSaved(createdLocation?.id || ''); onClose();
    } catch (exception) { setError(exception.response?.data?.detail || exception.message || 'Could not save this registry entry.'); }
    finally { setBusy(false); }
  };
  const isLocation = mode === 'location';
  return <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/40 p-4" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <form onSubmit={save} className="w-full max-w-lg rounded-2xl border border-slate-200 bg-white p-5 shadow-xl" role="dialog" aria-modal="true" aria-labelledby="registry-dialog-title">
      <div className="mb-4 flex items-center justify-between"><h2 id="registry-dialog-title" className="text-lg font-semibold text-slate-900">{isLocation ? 'Add location' : 'Add camera'}</h2><button type="button" className="rounded p-1 text-slate-500 hover:bg-slate-100" onClick={onClose} aria-label="Close"><X size={18}/></button></div>
      <label className={fieldLabel}>{isLocation ? 'Location name' : 'Camera name'}<input className={input} required maxLength={120} value={name} onChange={(event) => { setName(event.target.value); if (!code || code === slug(name)) setCode(slug(event.target.value)); }} placeholder={isLocation ? 'Vault Room 1' : 'Camera 01'}/></label>
      <label className={`${fieldLabel} mt-3`}>Code<input className={input} required maxLength={39} pattern="[a-z0-9_-]+" value={code} onChange={(event) => setCode(slug(event.target.value))} placeholder={isLocation ? 'vault-room-1' : 'camera-01'}/></label>
      {!isLocation && <>
        <label className={`${fieldLabel} mt-3`}>Source type<select className={input} value={sourceType} onChange={(event) => { setSourceType(event.target.value); setConnectionRef(event.target.value === 'server_webcam' ? 'device:0' : ''); }}><option value="rtsp">RTSP / RTSPS</option><option value="http_stream">HTTP stream</option><option value="video_file">Server video file</option><option value="browser_webcam">Browser webcam</option><option value="server_webcam">Server webcam</option></select></label>
        {sourceType === 'browser_webcam' ? <p className="mt-3 rounded-lg bg-slate-50 p-3 text-xs leading-5 text-slate-600">No source reference is needed. This browser creates a stable internal identity for its webcam automatically.</p> : <>
          <label className={`${fieldLabel} mt-3`}>{sourceType === 'server_webcam' ? 'Device index' : 'Source reference'}<input className={input} required value={connectionRef} onChange={(event) => setConnectionRef(event.target.value)} placeholder={sourceType === 'server_webcam' ? 'device:0' : 'env:VAULT_CAMERA_01_RTSP'}/></label>
          <p className="mt-2 text-xs leading-5 text-slate-500">{sourceType === 'server_webcam' ? 'Use the webcam index attached to the machine running the backend (usually device:0).' : <>Put the credential-bearing URL or file path in the backend environment and enter only its <code>env:NAME</code> reference here.</>}</p>
        </>}
      </>}
      {error && <p className="mt-3 rounded-lg bg-red-50 p-2 text-sm text-red-700" role="alert">{error}</p>}
      <div className="mt-5 flex justify-end gap-2"><button type="button" className={`${btn} bg-slate-100 text-slate-700`} onClick={onClose}>Cancel</button><button type="submit" className={`${btn} bg-emerald-100 text-emerald-800`} disabled={busy || !name.trim() || !code.trim() || (!isLocation && sourceType !== 'browser_webcam' && !connectionRef.trim())}>{busy ? 'Saving…' : isLocation ? 'Save location' : 'Save camera'}</button></div>
    </form>
  </div>;
}

function CommonUseCaseEditor({ useCase, useCases, onUseCaseChange, initialLocationId = '', initialCameraId = '' }) {
  const adapter = useMemo(() => buildRegistryAdapter(regionsRegistryApi, useCase.frontend_id), [useCase.frontend_id]);
  const [locations, setLocations] = useState([]); const [cameras, setCameras] = useState([]); const [assignments, setAssignments] = useState([]);
  const [locationId, setLocationId] = useState(''); const [cameraId, setCameraId] = useState(''); const [zones, setZones] = useState([]);
  const [tool, setTool] = useState('select'); const [points, setPoints] = useState([]); const [editing, setEditing] = useState(null);
  const [zoneName, setZoneName] = useState(''); const [zoneType, setZoneType] = useState(useCase.zone_types?.[0]?.key || '');
  const [reference, setReference] = useState('bottom_center'); const [dialog, setDialog] = useState(''); const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false); const [error, setError] = useState(''); const [frameUrl, setFrameUrl] = useState('');
  const [frameAspect, setFrameAspect] = useState(16 / 9);
  const [previewStatus, setPreviewStatus] = useState('idle'); const [previewMessage, setPreviewMessage] = useState(''); const [previewAttempt, setPreviewAttempt] = useState(0); const [previewEnabled, setPreviewEnabled] = useState(true);
  const canvasRef = useRef(null); const stageRef = useRef(null); const previewRef = useRef(null);
  const assignment = assignments.find((item) => item.camera_id === cameraId) || null;
  const camera = cameras.find((item) => item.id === cameraId) || null;
  const activeSource = camera?.sources?.find((source) => source.is_active) || camera?.sources?.[0] || null;
  const enabledCount = zones.filter((zone) => zone.enabled !== false).length;
  const isVault = useCase.id === 'vault_room';

  const refresh = useCallback(async (preferredLocation = '', preferredCamera = '') => {
    setLoading(true); setError('');
    try {
      const allLocations = await regionsRegistryApi.get('/locations'); setLocations(allLocations);
      const nextLocation = allLocations.some((item) => item.id === preferredLocation) ? preferredLocation : (allLocations[0]?.id || '');
      setLocationId(nextLocation);
      if (!nextLocation) { setCameras([]); setAssignments([]); setCameraId(''); setZones([]); return; }
      const [allCameras, allAssignments] = await Promise.all([
        regionsRegistryApi.get(`/cameras?location_id=${encodeURIComponent(nextLocation)}`),
        regionsRegistryApi.get(`/assignments?location_id=${encodeURIComponent(nextLocation)}&use_case=${encodeURIComponent(useCase.id)}`),
      ]);
      const assignedIds = new Set(allAssignments.map((item) => item.camera_id)); const available = allCameras.filter((item) => assignedIds.has(item.id));
      setCameras(available); setAssignments(allAssignments);
      const nextCamera = available.some((item) => item.id === preferredCamera) ? preferredCamera : (available[0]?.id || '');
      setCameraId(nextCamera);
      const selectedAssignment = allAssignments.find((item) => item.camera_id === nextCamera);
      setZones(selectedAssignment ? await adapter.loadZones(selectedAssignment.id) : []);
    } catch (exception) { setError(exception.response?.data?.detail || exception.message || 'Could not load Regions & Zones.'); }
    finally { setLoading(false); }
  }, [adapter, useCase.id]);
  // Deep links (e.g. from Grill Gate configuration) preselect a location/camera; unknown ids fall back to the first.
  const initialRef = useRef([initialLocationId, initialCameraId]);
  useEffect(() => { refresh(...initialRef.current); }, [refresh]);

  useEffect(() => {
    let disposed = false;
    let stream = null;
    setPreviewMessage('');
    if (frameUrl) { setPreviewStatus('paused'); return undefined; }
    if (!previewEnabled) { setPreviewStatus('stopped'); return undefined; }
    if (!cameraId) { setPreviewStatus('idle'); return undefined; }
    if (activeSource?.source_type !== 'browser_webcam') {
      setPreviewStatus('unavailable');
      setPreviewMessage('Live preview is available for Browser webcam sources. Load a reference image to draw zones for this source.');
      return undefined;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      setPreviewStatus('error');
      setPreviewMessage('This browser cannot access a camera. Use HTTPS or localhost, check camera permissions, or load a reference image.');
      return undefined;
    }
    setPreviewStatus('connecting');
    navigator.mediaDevices.getUserMedia({ video: true, audio: false }).then((nextStream) => {
      if (disposed) { nextStream.getTracks().forEach((track) => track.stop()); return; }
      stream = nextStream;
      const video = previewRef.current;
      if (!video) {
        stream.getTracks().forEach((track) => track.stop());
        stream = null;
        setPreviewStatus('error');
        setPreviewMessage('The camera preview element is unavailable. Retry preview.');
        return;
      }
      video.srcObject = stream;
      const play = video.play();
      if (play?.then) play.then(() => { if (!disposed) setPreviewStatus('live'); }).catch((exception) => {
        if (!disposed) {
          stream?.getTracks().forEach((track) => track.stop());
          if (video.srcObject === stream) video.srcObject = null;
          stream = null;
          setPreviewStatus('error');
          setPreviewMessage(exception.message || 'Camera preview could not start.');
        }
      });
      else setPreviewStatus('live');
      setPreviewMessage('');
    }).catch((exception) => {
      if (disposed) return;
      if (stream) stream.getTracks().forEach((track) => track.stop());
      stream = null;
      setPreviewStatus('error');
      setPreviewMessage(exception.name === 'NotAllowedError'
        ? 'Camera permission was denied. Allow camera access in the browser and retry.'
        : exception.name === 'NotFoundError'
          ? 'No webcam was found on this device. Load a reference image or connect a different source.'
          : exception.message || 'Could not start the browser camera preview.');
    });
    return () => {
      disposed = true;
      if (stream) stream.getTracks().forEach((track) => track.stop());
      if (previewRef.current) previewRef.current.srcObject = null;
    };
  }, [cameraId, activeSource?.source_type, previewAttempt, previewEnabled, frameUrl]);

  useEffect(() => {
    const canvas = canvasRef.current; if (!canvas) return;
    const ctx = canvas.getContext('2d'); ctx.clearRect(0, 0, canvas.width, canvas.height);
    const drawOverlays = () => {
      const all = [...zones, ...(points.length >= 2 ? [{ id: '__draft', name: zoneName || 'New zone', polygon: points.map((point) => ({ x: point.x / canvas.width, y: point.y / canvas.height })) }] : [])];
      all.forEach((zone) => {
        const polygon = (zone.polygon || []).map((point) => ({ x: (Array.isArray(point) ? point[0] : point.x) * canvas.width, y: (Array.isArray(point) ? point[1] : point.y) * canvas.height }));
        if (polygon.length < 2) return;
        ctx.beginPath(); ctx.moveTo(polygon[0].x, polygon[0].y); polygon.slice(1).forEach((point) => ctx.lineTo(point.x, point.y)); if (polygon.length > 2) ctx.closePath();
        const color = zone.id === '__draft' ? '#f8fafc' : (zone.enabled === false ? '#94a3b8' : '#34d399');
        ctx.fillStyle = `${color}30`; ctx.fill(); ctx.strokeStyle = color; ctx.lineWidth = 3; ctx.stroke();
        polygon.forEach((point) => { ctx.beginPath(); ctx.arc(point.x, point.y, 5, 0, Math.PI * 2); ctx.fillStyle = color; ctx.fill(); });
      });
    };
    if (frameUrl) { const image = new Image(); image.onload = () => { ctx.drawImage(image, 0, 0, canvas.width, canvas.height); drawOverlays(); }; image.src = frameUrl; }
    else drawOverlays();
  }, [frameUrl, points, zones, zoneName]);
  useEffect(() => () => { if (frameUrl) URL.revokeObjectURL(frameUrl); }, [frameUrl]);

  const selectCamera = async (id) => { setCameraId(id); setPoints([]); setEditing(null); setZoneName(''); setFrameUrl(''); setFrameAspect(16 / 9); const target = assignments.find((item) => item.camera_id === id); setZones(target ? await adapter.loadZones(target.id) : []); };
  const setReferenceImage = (event) => {
    const file = event.target.files?.[0]; if (!file) return;
    const url = URL.createObjectURL(file); const image = new Image();
    image.onload = () => { if (image.naturalWidth && image.naturalHeight) setFrameAspect(image.naturalWidth / image.naturalHeight); };
    image.src = url;
    setFrameUrl((old) => { if (old) URL.revokeObjectURL(old); return url; }); event.target.value = '';
  };
  const retryPreview = () => { setFrameUrl(''); setPreviewEnabled(true); setPreviewAttempt((attempt) => attempt + 1); };
  const stopPreview = () => setPreviewEnabled(false);
  const showLivePreview = () => { setFrameUrl(''); setPreviewEnabled(true); setPreviewAttempt((attempt) => attempt + 1); };
  const capturePreviewFrame = () => {
    const video = previewRef.current;
    if (!video || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || !video.videoWidth || !video.videoHeight) {
      setPreviewMessage('Wait for the live camera image to appear, then capture a frame.'); return;
    }
    const frame = document.createElement('canvas'); frame.width = video.videoWidth; frame.height = video.videoHeight;
    frame.getContext('2d').drawImage(video, 0, 0, frame.width, frame.height);
    frame.toBlob((blob) => {
      if (!blob) { setPreviewMessage('Could not capture a camera frame.'); return; }
      const url = URL.createObjectURL(blob);
      setFrameAspect(frame.width / frame.height);
      setFrameUrl((old) => { if (old) URL.revokeObjectURL(old); return url; });
    }, 'image/jpeg', 0.92);
  };
  const addPoint = (event) => {
    if (tool !== 'draw') return; const rect = stageRef.current.getBoundingClientRect();
    setPoints((current) => [...current, { x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)) * 1280, y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)) * 720 }]);
  };
  const startZone = () => { if (!assignment) { setError('Select a camera assigned to this use case first.'); return; } setEditing(null); setZoneName(''); setZoneType(useCase.zone_types?.[0]?.key || ''); setReference('bottom_center'); setPoints([]); setTool('draw'); setError(''); };
  const editZone = (zone) => { setEditing(zone); setZoneName(zone.name); setZoneType(zone.zone_type || useCase.zone_types?.[0]?.key || ''); setReference(zone.reference || 'bottom_center'); setPoints((zone.polygon || []).map((point) => ({ x: (Array.isArray(point) ? point[0] : point.x) * 1280, y: (Array.isArray(point) ? point[1] : point.y) * 720 }))); setTool('draw'); };
  const saveZone = async () => {
    if (!assignment || points.length < 3 || !zoneName.trim()) { setError('Choose a name and draw at least three points before saving.'); return; }
    setSaving(true); setError('');
    try { await adapter.saveZone(assignment.id, editing, { name: zoneName.trim(), zone_type: zoneType, reference }, points.map((point) => ({ x: point.x / 1280, y: point.y / 720 }))); setZones(await adapter.loadZones(assignment.id)); setPoints([]); setEditing(null); setTool('select'); }
    catch (exception) { setError(exception.response?.data?.detail || exception.message || 'Zone could not be saved.'); }
    finally { setSaving(false); }
  };
  const removeZone = async (zone) => { if (!assignment || !window.confirm(`Delete “${zone.name}”?`)) return; try { await adapter.deleteZone(assignment.id, zone.id); setZones(await adapter.loadZones(assignment.id)); } catch (exception) { setError(exception.response?.data?.detail || exception.message || 'Zone could not be deleted.'); } };
  const toggleZone = async (zone) => { if (!assignment) return; try { await adapter.patchZone(assignment.id, zone.id, { enabled: zone.enabled === false }); setZones(await adapter.loadZones(assignment.id)); } catch (exception) { setError(exception.response?.data?.detail || exception.message || 'Zone status could not be changed.'); } };

  return <main className="mx-auto max-w-6xl p-4 text-slate-900 sm:p-6">
    <section className="rounded-xl border border-slate-200 bg-white p-4 sm:p-5">
      <header className="mb-4 flex items-center justify-between gap-3"><h1 className="text-base font-semibold">Region &amp; Zone Management</h1><span className="rounded-full bg-emerald-100 px-2.5 py-1 text-[11px] font-semibold text-emerald-700">Common module</span></header>
        <div className="grid gap-3 sm:grid-cols-2">
        <label className={fieldLabel}>Use case<select className={input} value={useCase.id} onChange={(event) => onUseCaseChange(event.target.value)}>{useCases.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
        <div><label className={fieldLabel}>Room / Location</label><div className="flex gap-2"><select className={input} value={locationId} onChange={(event) => { setFrameUrl(''); setPoints([]); refresh(event.target.value, ''); }}>{!locations.length && <option value="">No locations configured</option>}{locations.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select><button type="button" className={`${btn} mt-1 shrink-0 bg-slate-100 text-slate-700`} onClick={() => setDialog('location')} title="Add location" aria-label="Add location"><Plus size={16}/></button></div></div>
      </div>
      <div className="mt-4"><div className="mb-2 flex items-center justify-between"><label className={fieldLabel}>Camera</label><button type="button" className={`${btn} bg-slate-100 text-slate-700`} disabled={!locationId} onClick={() => setDialog('camera')}><Plus size={14}/> Add camera</button></div>
        {camera ? <div role="button" tabIndex={0} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectCamera(camera.id); } }} onClick={() => selectCamera(camera.id)} className="w-full cursor-pointer rounded-lg border border-slate-200 bg-white p-3 text-left hover:border-blue-300">
          <span className="flex items-center justify-between gap-3"><b className="text-sm">{camera.name}</b><span className="flex items-center gap-2"><span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${previewStatus === 'live' ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-600'}`}>{previewStatus === 'live' ? 'Connected' : previewStatus === 'stopped' ? 'Preview stopped' : 'Configured'}</span><button type="button" className="rounded p-1 text-slate-500 hover:bg-slate-100" onClick={(event) => { event.stopPropagation(); retryPreview(); }} aria-label="Retry camera preview"><RefreshCw size={14}/></button></span></span>
          <span className="mt-2 block text-xs text-slate-500">{camera.sources?.[0]?.masked_source || 'Source configured'}</span>
        </div> : <div className="rounded-lg border border-dashed border-slate-300 p-4 text-sm text-slate-500">{locationId ? 'No camera is assigned to this use case in this location.' : 'Add a location to register its first camera.'}</div>}
        {cameras.length > 1 && <div className="mt-2 flex flex-wrap gap-2">{cameras.map((item) => <button key={item.id} onClick={() => selectCamera(item.id)} className={`${btn} ${item.id === cameraId ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-slate-700'}`}>{item.name}</button>)}</div>}
      </div>
    </section>
    <section className="mt-5 border-t border-slate-200 pt-5"><h2 className="mb-3 text-sm font-semibold">Camera preview and zone editor</h2>
      <div className="mb-3 flex flex-wrap items-center gap-2"><button className={`${btn} ${tool === 'select' ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-slate-700'}`} onClick={() => { setTool('select'); setPoints([]); }}><Camera size={13}/> Select</button><button className={`${btn} ${tool === 'draw' ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-700'}`} disabled={!assignment} onClick={startZone}><Plus size={13}/> Draw zone</button><button className={`${btn} bg-slate-100 text-slate-700`} disabled={!points.length} onClick={() => setPoints((current) => current.slice(0, -1))}><Undo2 size={13}/> Undo</button><button className={`${btn} bg-slate-100 text-slate-700`} disabled={!points.length} onClick={() => { setPoints([]); setEditing(null); setZoneName(''); }}><X size={13}/> Clear</button>{previewStatus === 'live' && <><button className={`${btn} bg-blue-100 text-blue-700`} onClick={capturePreviewFrame}><Camera size={13}/> Capture frame</button><button className={`${btn} bg-red-100 text-red-700`} onClick={stopPreview}><X size={13}/> Stop preview</button></>}{previewStatus === 'connecting' && <button className={`${btn} bg-red-100 text-red-700`} onClick={stopPreview}><X size={13}/> Stop preview</button>}{frameUrl && <button className={`${btn} bg-slate-100 text-slate-700`} onClick={showLivePreview}>Live preview</button>}{(previewStatus === 'stopped' || previewStatus === 'error') && activeSource?.source_type === 'browser_webcam' && <button className={`${btn} bg-blue-100 text-blue-700`} onClick={retryPreview}>{previewStatus === 'error' ? 'Retry preview' : 'Start preview'}</button>}<label className={`${btn} cursor-pointer bg-slate-100 text-slate-700`}><ImagePlus size={13}/> Upload image<input type="file" accept="image/*" className="hidden" onChange={setReferenceImage}/></label>
        {points.length > 0 && <div className="ml-auto flex flex-wrap items-center gap-2"><input className="min-h-8 w-40 rounded-md border border-slate-300 px-2 text-xs" value={zoneName} onChange={(event) => setZoneName(event.target.value)} placeholder="Zone name" aria-label="Zone name"/>{!isVault && <select className="min-h-8 rounded-md border border-slate-300 px-2 text-xs" value={zoneType} onChange={(event) => setZoneType(event.target.value)} aria-label="Zone type">{(useCase.zone_types || []).map((type) => <option key={type.key} value={type.key}>{type.label}</option>)}</select>}<select className="min-h-8 rounded-md border border-slate-300 px-2 text-xs" value={reference} onChange={(event) => setReference(event.target.value)} aria-label="Zone reference"><option value="bottom_center">Bottom center</option><option value="center">Center</option></select><button className={`${btn} bg-emerald-100 text-emerald-800`} disabled={saving || points.length < 3} onClick={saveZone}><Check size={13}/>{saving ? 'Saving…' : 'Save changes'}</button></div>}
      </div>
      <div ref={stageRef} className="relative overflow-hidden rounded-xl bg-[#26363c]" style={{ aspectRatio: String(frameAspect) }} onClick={addPoint} role="img" aria-label="Camera preview and polygon editor">
        {frameUrl ? <img src={frameUrl} alt="Captured or uploaded zone reference frame" className="absolute inset-0 h-full w-full object-fill"/> : <>
          {activeSource?.source_type === 'browser_webcam' && <video ref={previewRef} autoPlay playsInline muted onLoadedMetadata={(event) => { const video = event.currentTarget; if (video.videoWidth && video.videoHeight) setFrameAspect(video.videoWidth / video.videoHeight); }} className="absolute inset-0 h-full w-full object-fill"/>}
          {previewStatus !== 'live' && <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-3 text-center text-white"><Video size={24}/><b className="text-sm">{previewStatus === 'connecting' ? 'Connecting to camera…' : previewStatus === 'stopped' ? 'Preview stopped' : activeSource?.source_type === 'browser_webcam' ? 'Camera preview unavailable' : 'Camera preview'}</b><span className="max-w-lg text-xs text-slate-300">{previewMessage || (activeSource?.source_type === 'browser_webcam' ? 'Allow browser camera access to start preview.' : 'Select a Browser webcam source, or upload an image frame.')}</span>{(previewStatus === 'error' || previewStatus === 'stopped') && activeSource?.source_type === 'browser_webcam' && <button type="button" className="pointer-events-auto rounded-full bg-white/15 px-3 py-1.5 text-xs font-semibold text-white" onClick={retryPreview}>{previewStatus === 'error' ? 'Retry preview' : 'Start preview'}</button>}</div>}
        </>}
        <canvas ref={canvasRef} width="1280" height="720" className={`absolute inset-0 h-full w-full ${tool === 'draw' ? 'cursor-crosshair' : 'cursor-default'}`}/>
      </div>
      {!frameUrl && <p className="mt-2 text-xs text-slate-500">Capture a frame from the live preview or upload an image before drawing. Vault polygons use normalized raw, unmirrored frame coordinates.</p>}
      {error && <p role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    </section>
    <section className="mt-5"><div className="flex items-end justify-between gap-3"><div><h2 className="text-base font-semibold">Configured zones</h2><p className="mt-1 text-xs text-slate-500">{zones.length} {zones.length === 1 ? 'zone' : 'zones'} configured</p></div><span className="rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-semibold text-emerald-700">{enabledCount} enabled</span></div>
      <div className="mt-3 space-y-2">{zones.map((zone) => <article key={zone.id} className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white p-3"><button type="button" className="flex min-w-0 items-start gap-2 text-left" onClick={() => editZone(zone)}><span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${zone.enabled === false ? 'bg-slate-300' : 'bg-emerald-300'}`}/><span className="min-w-0"><b className="block truncate text-sm">{zone.name}</b><span className="mt-1 block text-xs text-slate-500">Polygon · {zone.enabled === false ? 'Disabled' : 'Enabled'}{zone.zone_type ? ` · ${zone.zone_type}` : ''}</span></span></button><div className="flex shrink-0 items-center gap-1"><button type="button" className="rounded p-2 text-slate-600 hover:bg-slate-100" onClick={() => editZone(zone)} aria-label={`Edit ${zone.name}`}><Pencil size={15}/></button><button type="button" className="rounded p-2 text-xs text-slate-600 hover:bg-slate-100" onClick={() => toggleZone(zone)} aria-label={`${zone.enabled === false ? 'Enable' : 'Disable'} ${zone.name}`}>{zone.enabled === false ? <Check size={15}/> : 'Off'}</button><button type="button" className="rounded p-2 text-slate-600 hover:bg-red-50 hover:text-red-700" onClick={() => removeZone(zone)} aria-label={`Delete ${zone.name}`}><Trash2 size={15}/></button></div></article>)}{!zones.length && <div className="rounded-lg border border-dashed border-slate-300 p-5 text-sm text-slate-500">{loading ? 'Loading zones…' : assignment ? 'No zones configured for this camera yet.' : 'Select an assigned camera to view its zones.'}</div>}</div>
    </section>
    {dialog && <RegistrySetupDialog mode={dialog} location={locations.find((item) => item.id === locationId)} useCase={useCase} onClose={() => setDialog('')} onSaved={(newLocationId) => { setFrameUrl(''); return refresh(newLocationId || locationId, ''); }}/>}
  </main>;
}

export default function CommonRegionsZonesPage() {
  const [params] = useSearchParams();
  const [useCases, setUseCases] = useState([]); const [selectedId, setSelectedId] = useState(() => params.get('use_case') || 'vault_room'); const [error, setError] = useState('');
  useEffect(() => { let active = true; regionsRegistryApi.get('/use-cases').then((items) => { if (active) setUseCases(items); }).catch((exception) => { if (active) setError(exception.response?.data?.detail || exception.message || 'Could not load use cases.'); }); return () => { active = false; }; }, []);
  const selected = useCases.find((item) => item.id === selectedId);
  const selector = <label className="text-xs text-slate-600">Use case<select aria-label="Use case" className="ml-2 rounded-lg border border-slate-300 bg-white p-2 text-sm" value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>{useCases.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>;
  if (selectedId === 'branch_exterior') return <div className="min-h-full bg-[#f5f6fa]"><header className="mx-auto flex max-w-6xl items-center justify-between px-4 pt-5 sm:px-6"><h1 className="text-base font-semibold">Region &amp; Zone Management</h1>{selector}</header><Suspense fallback={<div className="p-6 text-sm text-slate-500">Loading Branch Exterior editor…</div>}><BxLayout><LegacyBranchRegionsZonesPage/></BxLayout></Suspense></div>;
  return <div className="min-h-full bg-[#f5f6fa]">{error ? <div className="mx-auto max-w-6xl p-6 text-sm text-red-700" role="alert">{error}</div> : selected && <CommonUseCaseEditor key={selected.id} useCase={selected} useCases={useCases} onUseCaseChange={setSelectedId} initialLocationId={selected.id === params.get('use_case') ? params.get('location_id') || '' : ''} initialCameraId={selected.id === params.get('use_case') ? params.get('camera_id') || '' : ''}/>}</div>;
}
