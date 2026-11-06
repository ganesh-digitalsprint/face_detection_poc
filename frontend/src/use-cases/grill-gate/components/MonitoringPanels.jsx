import { useEffect, useState } from 'react';
import { ArrowDownLeft, ArrowUpRight, BellOff, History, Users } from 'lucide-react';
import { getGateState } from '../api/grillGate.js';
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
      <Icon size={22} className="text-[#69758F]" aria-hidden />
      <p className="text-sm text-[#55607A]">{children}</p>
    </div>
  );
}

export function MonitoringStats({ monitoring }) {
  const gate = GATE_STATES[monitoring.gateState] ?? GATE_STATES.UNKNOWN;
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard label="Gate state" value={gate.label} valueClass={monitoring.gateState === 'UNKNOWN' ? 'text-[#69758F] !text-xl' : gate.tone}
        badge={<span className="flex items-center gap-1.5 text-xs text-[#55607A]"><span className="h-2 w-2 rounded-full bg-slate-400" aria-hidden />No gate state reported</span>} />
      <StatCard label="Gate open duration" value={formatClock(monitoring.gateOpenSeconds)} valueClass="text-[#0F1B3D]" sub="Continuous open duration" />
      <StatCard label="Time since last crossing" value={formatClock(monitoring.secondsSinceCrossing)} valueClass="text-[#0F1B3D]" sub="Since last ENTRY/EXIT" />
      <StatCard label="People in mesh area" value={monitoring.meshPeopleCount} valueClass="text-[#0F1B3D]" sub="Current detected people" />
    </div>
  );
}

export function GateStatePanel({ assignmentId, worker }) {
  const [state, setState] = useState(null);
  const [error, setError] = useState('');
  const connected = Boolean(assignmentId && worker?.status === 'connected');

  useEffect(() => {
    setState(null);
    setError('');
    if (!connected) return undefined;
    let cancelled = false;
    let timer;
    const poll = async () => {
      try {
        const value = await getGateState(assignmentId);
        if (!cancelled) { setState(value); setError(''); }
      } catch (exception) {
        if (!cancelled) {
          const detail = exception?.response?.data?.detail;
          const message = typeof detail === 'string' ? detail
            : Array.isArray(detail) ? detail.map((item) => item?.msg ?? JSON.stringify(item)).join('; ')
              : exception?.message ?? 'Gate-state status unavailable.';
          setError(message);
        }
      } finally {
        if (!cancelled) timer = window.setTimeout(poll, 1000);
      }
    };
    poll();
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [assignmentId, connected]);

  const progress = Number.isFinite(state?.progress) ? Math.round(Math.max(0, Math.min(1, state.progress)) * 100) : null;
  const confidence = Number.isFinite(state?.confidence) ? `${Math.round(state.confidence * 100)}%` : '—';
  const tone = state?.state === 'CLOSED' ? 'ok' : ['OPEN', 'PARTIALLY_OPEN'].includes(state?.state) ? 'warn' : 'idle';
  return (
    <Card title="Gate State" aside={<Pill tone={tone} dot>{state?.state ?? (connected ? 'Starting' : 'Inactive')}</Pill>}>
      <dl className="grid grid-cols-2 gap-3">
        <div><dt className="text-xs text-[#55607A]">Gate progress</dt><dd className="mt-1 text-2xl font-bold text-[#0F1B3D]">{progress == null ? '—' : `${progress}%`}</dd></div>
        <div><dt className="text-xs text-[#55607A]">Confidence</dt><dd className="mt-1 text-2xl font-bold text-[#0F1B3D]">{confidence}</dd></div>
      </dl>
      {error && <p role="status" className="mt-3 text-xs text-amber-800">{error}</p>}
      {state?.error && <p role="status" className="mt-3 text-xs text-amber-800">{state.error}</p>}
      {!connected && <p className="mt-3 text-xs text-[#55607A]">Connect the camera worker to start gate-state detection.</p>}
    </Card>
  );
}

export function CrossingEventsPanel({ monitoring }) {
  return (
    <Card title="Recent Crossing Events" aside={`${monitoring.crossings.length} events`}>
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-lg bg-[#F7F8FC] p-3 ring-1 ring-[#E3E7F0]">
          <p className="flex items-center gap-1.5 text-xs text-[#55607A]"><ArrowDownLeft size={13} className="text-emerald-700" aria-hidden />ENTRY</p>
          <p className="mt-1 text-2xl font-bold text-[#0F1B3D]">{monitoring.entryCount}</p>
        </div>
        <div className="rounded-lg bg-[#F7F8FC] p-3 ring-1 ring-[#E3E7F0]">
          <p className="flex items-center gap-1.5 text-xs text-[#55607A]"><ArrowUpRight size={13} className="text-sky-700" aria-hidden />EXIT</p>
          <p className="mt-1 text-2xl font-bold text-[#0F1B3D]">{monitoring.exitCount}</p>
        </div>
      </div>
      {monitoring.crossings.length ? (
        <ul className="mt-2 divide-y divide-[#E3E7F0]">
          {monitoring.crossings.map((event) => (
            <li key={event.id} className="flex items-center gap-3 py-3">
              <Pill tone={event.direction === 'ENTRY' ? 'ok' : 'info'}>{event.direction}</Pill>
              <span className="font-semibold text-[#0F1B3D]">{timeOf(event.at)}</span>
              {event.details && <span className="min-w-0 truncate text-xs text-[#55607A]">{event.details}</span>}
              <span className="ml-auto text-xs text-[#55607A]">{event.cameraLabel}</span>
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
            <li key={alert.id} className="rounded-lg border-l-2 border-amber-400 bg-[#FFFBEB] p-3">
              <p className="flex items-center gap-2 text-sm font-semibold text-[#0F1B3D]"><Pill tone="warn">{alert.severity}</Pill>{alert.type}<span className="ml-auto text-xs font-normal text-[#55607A]">{timeOf(alert.at)}</span></p>
              {alert.message && <p className="mt-1 text-xs text-[#55607A]">{alert.message}</p>}
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
        <div><dt className="text-xs text-[#55607A]">Current people</dt><dd className="mt-1 text-2xl font-bold text-[#0F1B3D]">{monitoring.meshPeopleCount}</dd></div>
        <div><dt className="text-xs text-[#55607A]">Gathering duration</dt><dd className="mt-1 text-2xl font-bold text-[#0F1B3D]">{formatClock(monitoring.meshGatheringSeconds)}</dd></div>
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
            <li key={event.id} className="min-w-[150px] border-t-2 border-[#34479B] pt-2">
              <p className="text-sm font-semibold text-[#0F1B3D]">{event.title}</p>
              <p className="text-xs text-[#55607A]">{timeOf(event.at)}</p>
            </li>
          ))}
        </ol>
      ) : <EmptyState icon={History}>No monitoring events available</EmptyState>}
    </Card>
  );
}
