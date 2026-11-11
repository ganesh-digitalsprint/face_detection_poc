import GrillGateAlerts from './GrillGateAlerts.jsx';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { describeError } from '../../../utils/errors.js';
import {
  createCameraSource, createGrillGateAssignment, createRegistryCamera, getLivePreview,
  listAllRegistryLocations, updateAssignmentConfiguration, updateCameraSource,
} from '../api/grillGate.js';
import { mergeAssignmentConfiguration, workerIsActive } from '../grillGateModel.js';
import { useAuthorizedJpeg } from '../hooks/useSourceData.js';
import { cameraCode, connectionReferenceError } from '../liveMonitoringModel.js';
import { CrossingEventsPanel, GateStatePanel, MonitoringStats, PreviewStage, TimelinePanel } from './MonitoringPanels.jsx';
import { btnGhost, btnPrimary, Card, ErrorNote, Pill } from './ui.jsx';

const field = 'mt-1 min-h-10 w-full rounded-md border border-[#D0D7E6] bg-white px-3 text-sm text-[#1C2B4D] outline-none focus:border-[#34479B] focus:ring-2 focus:ring-[#34479B]/20 disabled:bg-[#F4F6FB] disabled:text-[#69758F]';
const fieldLabel = 'block text-xs text-[#55607A]';
const NEW_CAMERA = '__new__';
// Only source types the backend's capture worker can open.
const SOURCE_TYPES = [['rtsp', 'RTSP'], ['nvr_channel', 'NVR channel'], ['http_stream', 'HTTP stream'], ['server_webcam', 'Server webcam']];
const LIVE_PREVIEW_MS = 1000;

const assignedSource = (item) => {
  const sourceId = item?.assignment?.configuration?.source_id;
  return item?.camera?.sources?.find((source) => source.id === sourceId) ?? item?.camera?.sources?.[0] ?? null;
};

function CameraSourceCard({ items, item, worker, connection, frame, fps, statusError, busy, actionError, onConnect, onDisconnect, onSelect, onRegistryChanged }) {
  // Only the operator's own choice opens the new-camera fields; an empty list while loading must not.
  const [adding, setAdding] = useState(false);
  const source = adding ? null : assignedSource(item);
  const [sourceType, setSourceType] = useState(source?.source_type && SOURCE_TYPES.some(([key]) => key === source.source_type) ? source.source_type : 'rtsp');
  const [reference, setReference] = useState('');
  const [locations, setLocations] = useState([]);
  const [locationId, setLocationId] = useState('');
  const [cameraName, setCameraName] = useState('');
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState('');
  const [notice, setNotice] = useState('');
  const active = workerIsActive(worker) && !statusError;

  useEffect(() => {
    if (adding) return;
    const next = assignedSource(item);
    if (next?.source_type && SOURCE_TYPES.some(([key]) => key === next.source_type)) setSourceType(next.source_type);
    setReference('');
    setFormError('');
  }, [item?.assignment.id, adding]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!adding) return undefined;
    let cancelled = false;
    listAllRegistryLocations().then((rows) => {
      if (cancelled) return;
      setLocations(rows);
      setLocationId((current) => current || rows[0]?.id || '');
    }).catch((exception) => { if (!cancelled) setFormError(describeError(exception).message); });
    return () => { cancelled = true; };
  }, [adding]);

  const changeCamera = (value) => {
    setNotice('');
    setAdding(value === NEW_CAMERA);
    if (value !== NEW_CAMERA) onSelect(value);
  };

  const saveSource = async () => {
    const problem = connectionReferenceError(sourceType, reference);
    if (problem) { setFormError(problem); return; }
    if (adding && (!locationId || !cameraCode(cameraName))) { setFormError('Choose a location and enter a camera name.'); return; }
    setSaving(true); setFormError(''); setNotice('');
    const body = { source_type: sourceType, connection_ref: reference.trim() };
    try {
      if (adding) {
        const camera = await createRegistryCamera({ location_id: locationId, code: cameraCode(cameraName), name: cameraName.trim() });
        const created = await createCameraSource({ camera_id: camera.id, ...body });
        const assignment = await createGrillGateAssignment(camera.id, created.id);
        await onRegistryChanged();
        setAdding(false);
        onSelect(assignment.id);
        setCameraName('');
      } else if (source) {
        await updateCameraSource(source.id, body);
        await onRegistryChanged();
      } else {
        const created = await createCameraSource({ camera_id: item.assignment.camera_id, ...body });
        // Merged, so changing the source never drops this assignment's alert rules.
        await updateAssignmentConfiguration(item.assignment.id, mergeAssignmentConfiguration(item.assignment.configuration, { source_id: created.id }));
        await onRegistryChanged();
      }
      setReference('');
      setNotice('Source saved.');
    } catch (exception) {
      setFormError(describeError(exception).message);
    } finally {
      setSaving(false);
    }
  };

  const facts = adding ? [] : [
    source ? `✓ Source saved: ${source.masked_source}` : 'No source saved yet',
    item ? '✓ Assigned to Grill Gate' : null,
    frame ? `frame ${frame.width} × ${frame.height}` : null,
    fps != null ? `analysed at ${fps.toFixed(0)} fps` : null,
  ].filter(Boolean);

  return (
    <Card title="Camera & source" aside={<Pill tone={connection.tone} className="!rounded-full">{connection.label}</Pill>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className={fieldLabel}>Camera
          <select className={field} value={adding ? NEW_CAMERA : item?.assignment.id ?? ''} onChange={(event) => changeCamera(event.target.value)}>
            {!items.length && <option value="">No camera assigned</option>}
            {items.map((entry) => <option key={entry.assignment.id} value={entry.assignment.id}>{entry.camera?.name ?? entry.assignment.camera_id}</option>)}
            <option value={NEW_CAMERA}>Add new camera…</option>
          </select>
        </label>
        <label className={fieldLabel}>Source type
          <select className={field} value={sourceType} disabled={active} onChange={(event) => { setSourceType(event.target.value); setFormError(''); }}>
            {SOURCE_TYPES.map(([key, text]) => <option key={key} value={key}>{text}</option>)}
          </select>
        </label>
        {adding && (
          <>
            <label className={fieldLabel}>Location
              <select className={field} value={locationId} onChange={(event) => setLocationId(event.target.value)}>
                {!locations.length && <option value="">No locations</option>}
                {locations.map((location) => <option key={location.id} value={location.id}>{location.name}</option>)}
              </select>
              {!locations.length && <span className="mt-1 block">Add one in <Link to="/regions?use_case=grill_gate" className="font-semibold text-[#34479B] underline">Regions &amp; Zones</Link>.</span>}
            </label>
            <label className={fieldLabel}>Camera name
              <input className={field} value={cameraName} maxLength={120} onChange={(event) => setCameraName(event.target.value)} placeholder="Grill Gate Cam 1" />
            </label>
          </>
        )}
        <label className={`${fieldLabel} sm:col-span-2`}>Connection reference
          <input className={field} value={reference} disabled={active} autoComplete="off" spellCheck={false}
            placeholder={source?.masked_source ?? (sourceType === 'server_webcam' ? 'device:0' : 'env:GATE_CAM_RTSP')}
            onChange={(event) => { setReference(event.target.value); setFormError(''); }} />
          <span className="mt-1 block leading-5">
            {sourceType === 'server_webcam'
              ? 'Enter the webcam index on the backend machine, for example device:0.'
              : 'Enter env:NAME, where NAME is a server environment variable holding the address and any password. Addresses are not typed here.'}
            {active ? ' Disconnect the camera to change its source.' : ''}
          </span>
        </label>
      </div>
      {facts.length > 0 && <p className="mt-2 text-xs leading-5 text-[#55607A]">{facts.join(' · ')}</p>}
      {notice && <p role="status" className="mt-2 text-xs text-emerald-800">{notice}</p>}
      {(formError || actionError) && <div className="mt-2"><ErrorNote>{formError || actionError}</ErrorNote></div>}
      {!adding && connection.key !== 'connected' && connection.key !== 'available' && connection.key !== 'disconnected' && <p className="mt-2 text-xs text-[#55607A]">{connection.detail}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" className={btnGhost} onClick={saveSource} disabled={saving || active || !reference.trim()}>{saving ? 'Saving…' : 'Save source'}</button>
        <button type="button" className={btnPrimary} onClick={onConnect} disabled={Boolean(busy) || adding || !item || !source || active}>{busy === 'connect' ? 'Connecting…' : 'Connect Camera'}</button>
        <button type="button" className={btnGhost} onClick={onDisconnect} disabled={Boolean(busy) || adding || !active || worker?.status === 'stopping'}>{busy === 'disconnect' ? 'Disconnecting…' : 'Disconnect'}</button>
      </div>
    </Card>
  );
}

function LivePreview({ item, worker, cameraName }) {
  const connected = worker?.status === 'connected';
  const assignmentId = item?.assignment.id;
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!connected) return undefined;
    const id = window.setInterval(() => setTick((value) => value + 1), LIVE_PREVIEW_MS);
    return () => window.clearInterval(id);
  }, [connected]);
  const image = useAuthorizedJpeg((signal) => getLivePreview(assignmentId, signal), connected && assignmentId ? `${assignmentId}:${tick}` : null);
  const width = worker?.width;
  const height = worker?.height;
  return (
    <Card title="Live preview">
      <PreviewStage url={image.url} alt={`Latest frame from ${cameraName}`} aspect={width && height ? width / height : 16 / 9}
        message={connected ? (image.error || 'Waiting for the first frame…') : 'Connect the camera to see its latest frame.'}
        badge={image.url ? <Pill tone="bad" className="!rounded-full">Live</Pill> : null} />
    </Card>
  );
}

export default function LiveCameraSection({ items, item, worker, connection, statusError, busy, actionError, onConnect, onDisconnect, onSelect, onRegistryChanged, monitoring, live }) {
  const frame = worker?.width && worker?.height ? { width: worker.width, height: worker.height } : item?.assignment.calibration?.reference_frame ?? null;

  const gateNote = monitoring.gateState !== 'UNKNOWN' ? null : connection.key === 'connected' ? 'Waiting for the gate-state detector.' : 'Connect the camera to start gate-state detection.';
  return (
    <div className="space-y-4">
      {live.error && <ErrorNote>Could not refresh live monitoring: {live.error}</ErrorNote>}
      <MonitoringStats monitoring={monitoring} />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.7fr)_minmax(320px,1fr)]">
        <div className="min-w-0 space-y-4">
          <TimelinePanel monitoring={monitoring} />
          <CameraSourceCard items={items} item={item} worker={worker} connection={connection} frame={frame} fps={live.fps} statusError={statusError}
            busy={busy} actionError={actionError} onConnect={onConnect} onDisconnect={onDisconnect} onSelect={onSelect} onRegistryChanged={onRegistryChanged} />
        </div>
        <div className="min-w-0 space-y-4">
          <GrillGateAlerts assignmentId={item?.assignment?.id} compact />
          <CrossingEventsPanel monitoring={monitoring} />
          <GateStatePanel monitoring={monitoring} note={gateNote} />
        </div>
      </div>
      <LivePreview item={item} worker={worker} cameraName={item?.camera?.name ?? 'this camera'} />
    </div>
  );
}
