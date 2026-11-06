import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { describeError } from '../../../utils/errors.js';
import { connectGrillGateAssignment, disconnectGrillGateAssignment } from '../api/grillGate.js';
import { connectionView, EMPTY_MONITORING, workerForAssignment } from '../grillGateModel.js';
import { useAssignmentZones, useGrillGateRegistry, useGrillGateWorkers } from '../hooks/useGrillGate.js';
import CalibrationView from '../components/CalibrationView.jsx';
import CameraConfigView from '../components/CameraConfigView.jsx';
import { AlertsView, EventHistoryView } from '../components/HistoryViews.jsx';
import LiveFeedPanel from '../components/LiveFeedPanel.jsx';
import { AlertsPanel, CrossingEventsPanel, GateStatePanel, MeshPanel, MonitoringStats, TimelinePanel } from '../components/MonitoringPanels.jsx';
import ZonesView from '../components/ZonesView.jsx';
import { ErrorNote, Pill } from '../components/ui.jsx';

// The dashboard is the landing view; every other screen opens only when the operator selects its tab.
const VIEWS = [
  ['monitor', 'Overview'],
  ['camera', 'Camera'],
  ['zones', 'Regions & Zones'],
  ['calibration', 'Calibration'],
  ['alerts', 'Alerts'],
  ['events', 'Event History'],
];
const VIEW_IDS = new Set(VIEWS.map(([id]) => id));
// No backend stage supplies gate state, crossings, mesh counts, events or alerts yet: show the empty snapshot.
const monitoring = EMPTY_MONITORING;

function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => { const id = window.setInterval(() => setNow(new Date()), 1000); return () => window.clearInterval(id); }, []);
  return <time className="text-sm text-[#55607A]" dateTime={now.toISOString()}>{now.toLocaleString(undefined, { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' })}</time>;
}

export default function GrillGatePage() {
  const [params, setParams] = useSearchParams();
  const registry = useGrillGateRegistry();
  const requested = params.get('assignment');
  const item = registry.items.find((entry) => entry.assignment.id === requested) ?? registry.items[0] ?? null;
  const assignmentId = item?.assignment.id ?? '';
  const view = VIEW_IDS.has(params.get('view')) ? params.get('view') : 'monitor';

  const workers = useGrillGateWorkers(assignmentId);
  const zones = useAssignmentZones(assignmentId);
  const worker = workerForAssignment(workers.workers, assignmentId);
  const connection = connectionView(worker, { statusError: workers.error, loaded: workers.loaded });

  const [busy, setBusy] = useState(null);
  const [sourceMode, setSourceMode] = useState('live');
  const [testFile, setTestFile] = useState(null);
  const [actionError, setActionError] = useState('');
  const selectedRef = useRef(assignmentId);
  selectedRef.current = assignmentId;
  useEffect(() => { setActionError(''); }, [assignmentId]);

  const setParam = (name, value) => setParams((current) => {
    const next = new URLSearchParams(current);
    if (name === 'view' && value === 'monitor') next.delete('view'); else next.set(name, value);
    return next;
  }, { replace: name === 'assignment' });

  /** Results for an assignment the operator has since moved away from are dropped. */
  const runAction = async (kind, call) => {
    const target = assignmentId;
    if (!target || busy) return;
    setBusy(kind); setActionError('');
    try {
      await call(target);
    } catch (exception) {
      if (selectedRef.current === target) setActionError(describeError(exception).message);
    } finally {
      setBusy(null);
      workers.refresh();
    }
  };
  const actions = {
    busy, actionError,
    onConnect: () => runAction('connect', connectGrillGateAssignment),
    onDisconnect: () => runAction('disconnect', disconnectGrillGateAssignment),
  };

  return (
    <div className="-m-4 min-h-[calc(100vh-4.5rem)] bg-[#F4F6FB] p-4 text-[#1C2B4D] sm:-m-6 sm:p-6">
      <header className="mb-4 flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-bold text-[#0F1B3D]">Grill Gate Monitoring</h2>
        {registry.items.length > 0 && (
          <label className="flex items-center">
            <span className="sr-only">Camera assignment</span>
            <select
              className="rounded-md border border-[#D0D7E6] bg-white px-2 py-1 text-xs font-semibold text-[#34479B] outline-none focus:border-[#34479B] focus:ring-2 focus:ring-[#34479B]/20"
              value={assignmentId}
              onChange={(event) => setParam('assignment', event.target.value)}
            >
              {registry.items.map((entry) => (
                <option key={entry.assignment.id} value={entry.assignment.id}>
                  {entry.camera?.code?.toUpperCase() ?? 'CAMERA'} · {entry.camera?.name ?? entry.assignment.camera_id}{entry.location ? ` — ${entry.location.name}` : ''}
                </option>
              ))}
            </select>
          </label>
        )}
        <span className="flex items-center gap-2 text-xs text-[#55607A]">Camera <Pill tone={item ? connection.tone : 'idle'} dot>{item ? connection.label : 'Not connected'}</Pill></span>
        <span className="flex items-center gap-2 text-xs text-[#55607A]"
          title="Gate, crossing and mesh monitoring are not provided by the backend yet.">
          Monitoring <Pill tone="idle" dot>{monitoring.status}</Pill>
        </span>
        <div className="ml-auto"><Clock /></div>
      </header>

      {registry.error && <div className="mb-4"><ErrorNote>Could not load Grill Gate camera assignments: {registry.error}</ErrorNote></div>}
      {registry.loading && !registry.items.length && <p className="mb-4 text-sm text-[#55607A]">Loading Grill Gate camera assignments…</p>}
      {!registry.loading && !registry.error && !registry.items.length && view !== 'monitor' && view !== 'alerts' && view !== 'events' && (
        <div className="rounded-xl border border-dashed border-[#D0D7E6] bg-white p-8 text-center">
          <p className="font-semibold text-[#0F1B3D]">No Grill Gate camera is assigned</p>
          <p className="mt-2 text-sm text-[#55607A]">Register a camera with a server-side source and assign it to Grill Gate Monitoring.</p>
          <Link to="/regions?use_case=grill_gate" className="mt-4 inline-block rounded-lg bg-[#34479B] px-4 py-2 text-sm font-semibold text-white">Open Regions &amp; Zones</Link>
        </div>
      )}

      {view === 'monitor' && (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(340px,480px)]">
          <div className="min-w-0 space-y-5">
            <LiveFeedPanel item={item} worker={worker} connection={connection} statusError={workers.error} {...actions}
              sourceMode={sourceMode} onSourceModeChange={setSourceMode} testFile={testFile} onTestFileChange={setTestFile}
              zones={zones.zones} zoneTypes={registry.zoneTypes} reloadZones={zones.reload}
              onCalibrationSaved={registry.replaceAssignment} />
            {!registry.loading && !registry.error && !registry.items.length && (
              <p className="text-sm text-[#55607A]">No camera is assigned to Grill Gate yet. Assign one under the <button type="button" className="font-semibold text-[#34479B] hover:underline" onClick={() => setParam('view', 'camera')}>Camera</button> tab.</p>
            )}
            <MonitoringStats monitoring={monitoring} />
            <TimelinePanel monitoring={monitoring} />
          </div>
          <div className="space-y-5">
            <GateStatePanel assignmentId={assignmentId} worker={worker} />
            <CrossingEventsPanel monitoring={monitoring} />
            <AlertsPanel monitoring={monitoring} />
            <MeshPanel monitoring={monitoring} />
          </div>
        </div>
      )}

      {view === 'camera' && registry.items.length > 0 && (
        <CameraConfigView items={registry.items} selectedId={assignmentId} onSelect={(id) => setParam('assignment', id)} workers={workers} {...actions} />
      )}
      {view === 'zones' && item && (
        <ZonesView item={item} zones={zones.zones} loading={zones.loading} error={zones.error} zoneTypes={registry.zoneTypes} />
      )}
      {view === 'calibration' && item && (
        <CalibrationView key={assignmentId} item={item} worker={worker} zones={zones.zones} onSaved={registry.replaceAssignment} />
      )}
      {view === 'alerts' && <AlertsView />}
      {view === 'events' && <EventHistoryView />}
    </div>
  );
}
