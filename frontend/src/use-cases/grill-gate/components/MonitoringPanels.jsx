import { ArrowDownLeft, ArrowUpRight, BellOff, History, Users } from 'lucide-react';
import { formatClock, GATE_STATES } from '../grillGateModel.js';
import { Card, Pill, StatCard } from './ui.jsx';

/**
 * Dashboard monitoring panels. They render a monitoring snapshot (see EMPTY_MONITORING); today no backend stage
 * supplies one, so the page passes the empty snapshot and these show neutral zero/empty states. Lists expect items
 * already normalized by a future API adapter: `{ id, ... }` with stable backend ids as React keys.
 */

const timeOf = (iso) => (iso ? new Date(iso).toLocaleTimeString() : '');

function EmptyState({ icon: Icon, children }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-8 text-center">
      <Icon size={22} className="text-slate-500" aria-hidden />
      <p className="text-sm text-slate-400">{children}</p>
    </div>
  );
}

export function MonitoringStats({ monitoring }) {
  const gate = GATE_STATES[monitoring.gateState] ?? GATE_STATES.UNKNOWN;
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard label="Gate state" value={gate.label} valueClass={monitoring.gateState === 'UNKNOWN' ? 'text-slate-400' : gate.tone}
        badge={<span className="flex items-center gap-1.5 text-xs text-slate-400"><span className="h-2 w-2 rounded-full bg-slate-500" aria-hidden />No gate state reported</span>} />
      <StatCard label="Gate open duration" value={formatClock(monitoring.gateOpenSeconds)} valueClass="text-slate-100" sub="Continuous open duration" />
      <StatCard label="Time since last crossing" value={formatClock(monitoring.secondsSinceCrossing)} valueClass="text-slate-100" sub="Since last ENTRY/EXIT" />
      <StatCard label="People in mesh area" value={monitoring.meshPeopleCount} valueClass="text-slate-100" sub="Current detected people" />
    </div>
  );
}

export function CrossingEventsPanel({ monitoring }) {
  return (
    <Card title="Recent Crossing Events" aside={`${monitoring.crossings.length} events`}>
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-lg bg-[#0f1729] p-3 ring-1 ring-[#22304d]">
          <p className="flex items-center gap-1.5 text-xs text-slate-400"><ArrowDownLeft size={13} className="text-emerald-300" aria-hidden />ENTRY</p>
          <p className="mt-1 text-2xl font-bold text-slate-100">{monitoring.entryCount}</p>
        </div>
        <div className="rounded-lg bg-[#0f1729] p-3 ring-1 ring-[#22304d]">
          <p className="flex items-center gap-1.5 text-xs text-slate-400"><ArrowUpRight size={13} className="text-sky-300" aria-hidden />EXIT</p>
          <p className="mt-1 text-2xl font-bold text-slate-100">{monitoring.exitCount}</p>
        </div>
      </div>
      {monitoring.crossings.length ? (
        <ul className="mt-2 divide-y divide-[#22304d]">
          {monitoring.crossings.map((event) => (
            <li key={event.id} className="flex items-center gap-3 py-3">
              <Pill tone={event.direction === 'ENTRY' ? 'ok' : 'info'}>{event.direction}</Pill>
              <span className="font-semibold text-slate-100">{timeOf(event.at)}</span>
              {event.details && <span className="min-w-0 truncate text-xs text-slate-400">{event.details}</span>}
              <span className="ml-auto text-xs text-slate-400">{event.cameraLabel}</span>
            </li>
          ))}
        </ul>
      ) : <EmptyState icon={History}>No crossing events yet</EmptyState>}
    </Card>
  );
}

export function AlertsPanel({ monitoring }) {
  return (
    <Card title="Active Alerts" aside={`${monitoring.alerts.length} open`}>
      {monitoring.alerts.length ? (
        <ul className="space-y-2">
          {monitoring.alerts.map((alert) => (
            <li key={alert.id} className="rounded-lg border-l-2 border-amber-400 bg-[#0f1729] p-3">
              <p className="flex items-center gap-2 text-sm font-semibold text-slate-100"><Pill tone="warn">{alert.severity}</Pill>{alert.type}<span className="ml-auto text-xs font-normal text-slate-400">{timeOf(alert.at)}</span></p>
              {alert.message && <p className="mt-1 text-xs text-slate-400">{alert.message}</p>}
            </li>
          ))}
        </ul>
      ) : <EmptyState icon={BellOff}>No active alerts</EmptyState>}
    </Card>
  );
}

export function MeshPanel({ monitoring }) {
  return (
    <Card title="Mesh Area Monitoring" aside={<Pill tone={monitoring.status === 'INACTIVE' ? 'idle' : 'purple'}>{monitoring.status}</Pill>}>
      <dl className="grid grid-cols-2 gap-3">
        <div><dt className="text-xs text-slate-400">Current people</dt><dd className="mt-1 text-2xl font-bold text-slate-100">{monitoring.meshPeopleCount}</dd></div>
        <div><dt className="text-xs text-slate-400">Gathering duration</dt><dd className="mt-1 text-2xl font-bold text-slate-100">{formatClock(monitoring.meshGatheringSeconds)}</dd></div>
      </dl>
      {monitoring.status === 'INACTIVE' && <EmptyState icon={Users}>Waiting for monitoring data.</EmptyState>}
    </Card>
  );
}

export function TimelinePanel({ monitoring }) {
  return (
    <Card title="Monitoring Event Timeline">
      {monitoring.events.length ? (
        <ol className="flex gap-6 overflow-x-auto pb-1">
          {monitoring.events.map((event) => (
            <li key={event.id} className="min-w-[150px] border-t-2 border-[#5b7cfa] pt-2">
              <p className="text-sm font-semibold text-slate-100">{event.title}</p>
              <p className="text-xs text-slate-400">{timeOf(event.at)}</p>
            </li>
          ))}
        </ol>
      ) : <EmptyState icon={History}>No monitoring events available</EmptyState>}
    </Card>
  );
}
