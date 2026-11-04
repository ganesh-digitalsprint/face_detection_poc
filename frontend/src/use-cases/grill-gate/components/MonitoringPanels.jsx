import { formatThreshold } from '../grillGateModel.js';
import { Card, Pending, Pill, StatCard } from './ui.jsx';

/**
 * Monitoring surfaces from the reference design. The current backend stage has a capture worker only: no gate
 * state, crossing, mesh, monitoring-event or Grill Gate alert producer. These panels show configured thresholds
 * (real calibration data) and say plainly that live values are pending; they never synthesize values.
 */

export function MonitoringStats({ monitoring }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard label="Gate state" value="Pending" sub="Gate-state detection is not implemented in the backend yet." />
      <StatCard label="Gate open duration" value="--:--"
        sub={`Needs backend gate state · limit ${formatThreshold(monitoring?.maximum_continuous_open_seconds)}`} />
      <StatCard label="Time since last crossing" value="--:--"
        sub={`Needs crossing detection · inactivity ${formatThreshold(monitoring?.crossing_inactivity_seconds)}`} />
      <StatCard label="People in mesh area" value="—"
        sub={`Mesh detection not implemented · threshold ${monitoring?.minimum_mesh_gathering_count ?? 'not set'}`} />
    </div>
  );
}

export function CrossingEventsPanel({ line }) {
  return (
    <Card title="Recent Crossing Events" aside={<Pill tone="idle">No event source</Pill>}>
      <Pending title="ENTRY / EXIT detection">
        Directional crossing detection is a future backend stage, so there are no ENTRY or EXIT events to list.
        {line ? ' The virtual line is calibrated and ready for it.' : ' The directional virtual line is not calibrated yet.'}
      </Pending>
    </Card>
  );
}

export function AlertsPanel() {
  return (
    <Card title="Active Alerts" aside="0 from backend">
      <Pending title="No Grill Gate alert producer">
        The existing alerts API (/api/v1/alerts) serves Vault Room alerts only. No backend service raises gate-open,
        crossing-inactivity, gathering or Grill Gate camera-feed alerts yet, so none are shown here.
      </Pending>
    </Card>
  );
}

export function MeshPanel({ monitoring, meshZones }) {
  const enabled = meshZones.filter((zone) => zone.enabled !== false);
  return (
    <Card title="Mesh Area Monitoring" aside={<Pill tone="idle">Pending</Pill>}>
      <dl className="grid grid-cols-3 gap-3">
        <div><dt className="text-xs text-slate-400">Current people</dt><dd className="mt-1 text-2xl font-bold text-slate-500">—</dd></div>
        <div><dt className="text-xs text-slate-400">Threshold</dt><dd className="mt-1 text-2xl font-bold text-slate-100">{monitoring?.minimum_mesh_gathering_count ?? '—'}</dd></div>
        <div><dt className="text-xs text-slate-400">Gathering after</dt><dd className="mt-1 text-2xl font-bold text-slate-100">{monitoring?.mesh_gathering_seconds != null ? formatThreshold(monitoring.mesh_gathering_seconds) : '—'}</dd></div>
      </dl>
      <ul className="mt-4 space-y-1.5 text-xs text-slate-400">
        <li>Mesh zone: {enabled.length ? <span className="text-violet-300">{enabled.map((zone) => zone.name).join(', ')}</span> : <span className="text-amber-300">not configured</span>}</li>
        <li>Suspicious activity after: <span className="text-slate-200">{formatThreshold(monitoring?.suspicious_activity_seconds)}</span></li>
        <li>Thresholds status: <span className="text-slate-200">{monitoring?.thresholds_status ?? 'unset'}</span></li>
      </ul>
      <div className="mt-4">
        <Pending title="Person counting">Mesh-area person detection and gathering rules are not implemented in the backend.</Pending>
      </div>
    </Card>
  );
}

export function TimelinePanel() {
  return (
    <Card title="Monitoring Event Timeline">
      <Pending title="No monitoring event records">
        The backend does not persist or stream Grill Gate monitoring events yet. Worker health above comes from live
        status checks and is not an event history.
      </Pending>
    </Card>
  );
}
