import { useEffect, useState } from 'react';
import { ArrowDownLeft, ArrowUpRight, BellOff, History, Users } from 'lucide-react';
import { getGateState } from '../api/grillGate.js';
import { formatClock, GATE_STATES } from '../grillGateModel.js';
import { jobCanStart, jobIsActive } from '../videoJobModel.js';
import { Card, Pill, StatCard } from './ui.jsx';

/**
 * Dashboard monitoring panels. They render a monitoring snapshot (see EMPTY_MONITORING); today no backend stage
 * supplies one for live cameras, so the page passes the empty snapshot and these show neutral zero/empty states. For
 * an uploaded video the page passes videoMonitoring(); a null value there means the backend does not report it.
 * List items carry stable backend ids as React keys and a video-relative `timeLabel` where one applies.
 */

const timeOf = (iso) => (iso ? new Date(iso).toLocaleTimeString() : '');
const clock = (seconds) => (seconds == null ? '—' : formatClock(seconds));

function EmptyState({ icon: Icon, children }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-8 text-center">
      <Icon size={22} className="text-[#69758F]" aria-hidden />
      <p className="text-sm text-[#55607A]">{children}</p>
    </div>
  );
}

export function MonitoringStats({ monitoring }) {
  const video = monitoring.source === 'video';
  const gate = GATE_STATES[monitoring.gateState] ?? GATE_STATES.UNKNOWN;
  const gateValue = video && !monitoring.gateState ? '—' : (GATE_STATES[monitoring.gateState]?.label ?? monitoring.gateState ?? gate.label);
  const gateReported = video && monitoring.gateState;
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard label="Gate state" value={gateValue} valueClass={gateReported ? gate.tone : 'text-[#69758F] !text-xl'}
        badge={<span className="flex items-center gap-1.5 text-xs text-[#55607A]"><span className="h-2 w-2 rounded-full bg-slate-400" aria-hidden />{gateReported ? `At crossing ${monitoring.gateStateTimeLabel}` : 'No gate state reported'}</span>} />
      <StatCard label="Gate open duration" value={clock(monitoring.gateOpenSeconds)} valueClass="text-[#0F1B3D]" sub={video ? 'Not reported for video jobs' : 'Continuous open duration'} />
      <StatCard label="Time since last crossing" value={clock(monitoring.secondsSinceCrossing)} valueClass="text-[#0F1B3D]" sub={video ? 'Video time since last ENTRY/EXIT' : 'Since last ENTRY/EXIT'} />
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

/** Video jobs have no gate-state endpoint; the only backend value is the state recorded on each crossing event. */
export function VideoGateStatePanel({ monitoring, job }) {
  const state = monitoring.gateState;
  const tone = state === 'CLOSED' ? 'ok' : ['OPEN', 'PARTIALLY_OPEN'].includes(state) ? 'warn' : monitoring.statusTone;
  const note = !job ? 'Save or select a video to see its results.'
    : jobCanStart(job) ? 'Select Process Video to start this job.'
      : state ? `Reported by the crossing event at ${monitoring.gateStateTimeLabel}.`
        : jobIsActive(job) ? 'Processing. Gate state appears here when a crossing event reports it.'
          : 'This job recorded no crossing events, so no gate state was reported.';
  return (
    <Card title="Gate State" aside={<Pill tone={tone} dot>{state ?? monitoring.status}</Pill>}>
      <dl className="grid grid-cols-2 gap-3">
        <div><dt className="text-xs text-[#55607A]">Gate progress</dt><dd className="mt-1 text-2xl font-bold text-[#0F1B3D]">—</dd></div>
        <div><dt className="text-xs text-[#55607A]">Confidence</dt><dd className="mt-1 text-2xl font-bold text-[#0F1B3D]">—</dd></div>
      </dl>
      <p className="mt-3 text-xs text-[#55607A]">{note}</p>
      {job && <p className="mt-1 text-xs text-[#55607A]">Progress and confidence are not reported for uploaded-video jobs.</p>}
    </Card>
  );
}

export function CrossingEventsPanel({ monitoring }) {
  const total = monitoring.crossingTotal ?? monitoring.crossings.length;
  return (
    <Card title="Recent Crossing Events" aside={`${total} ${total === 1 ? 'event' : 'events'}`}>
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
              <span className="font-semibold tabular-nums text-[#0F1B3D]">{event.timeLabel ?? timeOf(event.at)}</span>
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
    <Card title="Active Alerts" aside={`${monitoring.activeAlertCount ?? monitoring.alerts.length} open`}>
      {monitoring.alertsAvailable === false && <p role="status" className="mb-2 text-xs text-amber-800">The shared Alert Service is unavailable, so this job’s alerts cannot be listed right now.</p>}
      {monitoring.alerts.length > 0 && (
        <ul className="space-y-2">
          {monitoring.alerts.map((alert) => (
            <li key={alert.id} className={`rounded-lg border-l-2 p-3 ${alert.active === false ? 'border-slate-300 bg-[#F7F8FC]' : 'border-amber-400 bg-[#FFFBEB]'}`}>
              <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-[#0F1B3D]"><Pill tone={alert.active === false ? 'idle' : 'warn'}>{alert.severity}</Pill>{alert.title ?? alert.type}<span className="ml-auto text-xs font-normal tabular-nums text-[#55607A]">{alert.timeLabel ?? timeOf(alert.at)}</span></p>
              {alert.message && <p className="mt-1 text-xs text-[#55607A]">{alert.message}</p>}
              {alert.status && <p className="mt-1 text-[11px] text-[#69758F]">{alert.type} · {alert.status}</p>}
            </li>
          ))}
        </ul>
      )}
      {monitoring.alertsAvailable !== false && !(monitoring.activeAlertCount ?? monitoring.alerts.length) && <EmptyState icon={BellOff}>No active alerts</EmptyState>}
    </Card>
  );
}

export function MeshPanel({ monitoring }) {
  const video = monitoring.source === 'video';
  return (
    <Card title="Mesh Area Monitoring" aside={<Pill tone={monitoring.status === 'INACTIVE' ? 'idle' : video ? monitoring.statusTone : 'purple'}>{monitoring.status}</Pill>}>
      <dl className="grid grid-cols-2 gap-3">
        <div><dt className="text-xs text-[#55607A]">Current people</dt><dd className="mt-1 text-2xl font-bold text-[#0F1B3D]">{monitoring.meshPeopleCount}</dd></div>
        <div><dt className="text-xs text-[#55607A]">Gathering duration</dt><dd className="mt-1 text-2xl font-bold text-[#0F1B3D]">{clock(monitoring.meshGatheringSeconds)}</dd></div>
      </dl>
      {monitoring.status === 'INACTIVE' && <EmptyState icon={Users}>Waiting for monitoring data.</EmptyState>}
      {video && (monitoring.meshEvents.length ? (
        <ul className="mt-2 divide-y divide-[#E3E7F0]">
          {monitoring.meshEvents.map((event) => (
            <li key={event.id} className="flex items-center justify-between gap-3 py-2 text-xs"><span className="text-[#0F1B3D]">{event.title}</span><span className="tabular-nums text-[#55607A]">{event.timeLabel}</span></li>
          ))}
        </ul>
      ) : <EmptyState icon={Users}>No mesh events yet</EmptyState>)}
      {video && <p className="mt-1 text-xs text-[#55607A]">Occupancy comes from this job’s mesh events. Gathering duration is not reported.</p>}
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
              <p className="text-xs tabular-nums text-[#55607A]">{event.timeLabel ?? timeOf(event.at)}</p>
            </li>
          ))}
        </ol>
      ) : <EmptyState icon={History}>No monitoring events available</EmptyState>}
    </Card>
  );
}
