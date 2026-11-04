import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { describeError } from '../../../utils/errors.js';
import { connectGrillGateAssignment, disconnectGrillGateAssignment } from '../api/grillGate.js';
import { connectionView, workerForAssignment } from '../grillGateModel.js';
import { useAssignmentZones, useGrillGateRegistry, useGrillGateWorkers } from '../hooks/useGrillGate.js';
import CameraPanel from '../components/CameraPanel.jsx';
import ConfigurationView from '../components/ConfigurationView.jsx';
import { AlertsPanel, CrossingEventsPanel, MeshPanel, MonitoringStats, TimelinePanel } from '../components/MonitoringPanels.jsx';
import { ErrorNote, Pill } from '../components/ui.jsx';

const VIEWS = [['monitor', 'Monitoring'], ['config', 'Configuration']];
const itemLabel = (item) => `${item.camera?.code?.toUpperCase() ?? 'CAMERA'} · ${item.camera?.name ?? item.assignment.camera_id}`;

function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => { const id = window.setInterval(() => setNow(new Date()), 1000); return () => window.clearInterval(id); }, []);
  return <time className="text-sm text-slate-300" dateTime={now.toISOString()}>{now.toLocaleString(undefined, { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' })}</time>;
}

export default function GrillGatePage() {
  const [params, setParams] = useSearchParams();
  const registry = useGrillGateRegistry();
  const requested = params.get('assignment');
  const item = registry.items.find((entry) => entry.assignment.id === requested) ?? registry.items[0] ?? null;
  const assignmentId = item?.assignment.id ?? '';
  const view = params.get('view') === 'config' ? 'config' : 'monitor';

  const workers = useGrillGateWorkers(assignmentId);
  const zones = useAssignmentZones(assignmentId);
  const worker = workerForAssignment(workers.workers, assignmentId);
  const connection = connectionView(worker, { statusError: workers.error, loaded: workers.loaded });

  const [busy, setBusy] = useState(null);
  const [actionError, setActionError] = useState('');
  const selectedRef = useRef(assignmentId);
  selectedRef.current = assignmentId;
  useEffect(() => { setActionError(''); }, [assignmentId]);

  const setParam = (name, value) => setParams((current) => { const next = new URLSearchParams(current); next.set(name, value); return next; }, { replace: true });

  /** Results for an assignment the operator has since navigated away from are dropped. */
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

  const monitoring = item?.assignment.calibration?.monitoring ?? null;
  const line = item?.assignment.calibration?.directional_crossing;
  const savedLine = line ? { start: line.line_start, end: line.line_end } : null;
  const cameraPanelProps = {
    item, worker, connection, statusError: workers.error, checkedAt: workers.checkedAt,
    zones: zones.zones, zoneTypes: registry.zoneTypes, busy, actionError,
    onConnect: () => runAction('connect', connectGrillGateAssignment),
    onDisconnect: () => runAction('disconnect', disconnectGrillGateAssignment),
    onRefresh: workers.refresh,
  };

  return (
    <div className="-m-4 min-h-[calc(100vh-4.5rem)] bg-[#0b1222] p-4 text-slate-200 sm:-m-6 sm:p-6">
      <header className="mb-5 flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-bold text-white">Grill Gate Monitoring</h2>
        {registry.items.length > 0 && (
          <label className="flex items-center">
            <span className="sr-only">Camera assignment</span>
            <select
              className="rounded-md border border-[#3c5ba4]/60 bg-[#1b2a52] px-2 py-1 text-xs font-semibold text-[#9db4ff] outline-none focus:ring-2 focus:ring-[#5b7cfa]/40"
              value={assignmentId}
              onChange={(event) => setParam('assignment', event.target.value)}
            >
              {registry.items.map((entry) => (
                <option key={entry.assignment.id} value={entry.assignment.id}>{itemLabel(entry)}{entry.location ? ` — ${entry.location.name}` : ''}</option>
              ))}
            </select>
          </label>
        )}
        {item && <Pill tone={connection.tone} dot>{connection.label}</Pill>}
        <nav className="flex rounded-lg bg-white/5 p-1 ring-1 ring-white/10" aria-label="Grill Gate views">
          {VIEWS.map(([id, text]) => (
            <button key={id} type="button" aria-pressed={view === id} onClick={() => setParam('view', id)}
              className={`rounded-md px-3 py-1 text-xs font-semibold ${view === id ? 'bg-[#3c5ba4] text-white' : 'text-slate-300 hover:text-white'}`}>
              {text}
            </button>
          ))}
        </nav>
        <div className="ml-auto"><Clock /></div>
      </header>

      <div className="mb-4 space-y-2 empty:hidden">
        <ErrorNote>{registry.error && `Could not load Grill Gate assignments: ${registry.error}`}</ErrorNote>
        <ErrorNote>{view === 'monitor' && zones.error && `Could not load zones: ${zones.error}`}</ErrorNote>
      </div>

      {registry.loading && !registry.items.length && <p className="text-sm text-slate-400">Loading Grill Gate camera assignments…</p>}

      {!registry.loading && !registry.error && !registry.items.length && (
        <div className="rounded-xl border border-dashed border-[#2c3b5c] bg-[#121b2f] p-8 text-center">
          <p className="font-semibold text-slate-100">No Grill Gate camera is assigned</p>
          <p className="mt-2 text-sm text-slate-400">Register a camera with a server-side source and assign it to Grill Gate Monitoring in Regions &amp; Zones.</p>
          <Link to="/regions?use_case=grill_gate" className="mt-4 inline-block rounded-lg bg-[#3c5ba4] px-4 py-2 text-sm font-semibold text-white">Open Regions &amp; Zones</Link>
        </div>
      )}

      {item && view === 'monitor' && (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(340px,480px)]">
          <div className="min-w-0 space-y-5">
            <CameraPanel {...cameraPanelProps} line={savedLine} />
            <MonitoringStats monitoring={monitoring} />
            <TimelinePanel />
          </div>
          <div className="space-y-5">
            <CrossingEventsPanel line={savedLine} />
            <AlertsPanel />
            <MeshPanel monitoring={monitoring} meshZones={zones.zones.filter((zone) => zone.zone_type === 'mesh_area')} />
          </div>
        </div>
      )}

      {item && view === 'config' && (
        <ConfigurationView
          key={assignmentId}
          item={item}
          worker={worker}
          zones={zones.zones}
          zonesLoading={zones.loading}
          zonesError={zones.error}
          zoneTypes={registry.zoneTypes}
          onSaved={registry.replaceAssignment}
          cameraPanelProps={cameraPanelProps}
        />
      )}
    </div>
  );
}
