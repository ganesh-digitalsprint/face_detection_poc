import { BellOff, History, Users } from 'lucide-react';
import { formatClock, GATE_STATES } from '../grillGateModel.js';
import { btnGhost, Card, Pill, StatCard } from './ui.jsx';

/**
 * Dashboard panels for one source. They render a monitoring snapshot from liveMonitoring() or videoMonitoring() and
 * hold no data of their own, so a section can only ever show its own source. A null value means the backend has not
 * reported it, shown as "—" rather than as zero. List items carry stable backend ids as React keys.
 */

const clock = (seconds) => (seconds == null ? '—' : formatClock(seconds));

function EmptyState({ icon: Icon, children }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-6 text-center">
      <Icon size={22} className="text-[#69758F]" aria-hidden />
      <p className="text-sm text-[#55607A]">{children}</p>
    </div>
  );
}

const gateLabel = (state) => GATE_STATES[state]?.label ?? state;

export function MonitoringStats({ monitoring }) {
  const state = monitoring.gateState;
  const tone = GATE_STATES[state]?.tone ?? 'text-[#69758F]';
  return (
    <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
      <StatCard label="Gate state" value={state ? gateLabel(state) : '—'} valueClass={state && state !== 'UNKNOWN' ? tone : 'text-[#69758F]'}
        sub={monitoring.gateStateTimeLabel ? `At crossing ${monitoring.gateStateTimeLabel}` : null} />
      <StatCard label="Gate open duration" value={clock(monitoring.gateOpenSeconds)} valueClass="text-[#0F1B3D]" />
      <StatCard label="Since last crossing" value={clock(monitoring.secondsSinceCrossing)} valueClass="text-[#0F1B3D]" />
      <StatCard label="People in mesh area" value={monitoring.meshPeopleCount} valueClass="text-[#0F1B3D]" />
    </div>
  );
}

export function GateStatePanel({ monitoring, note }) {
  const state = monitoring.gateState;
  const tone = state === 'CLOSED' ? 'ok' : ['OPEN', 'PARTIALLY_OPEN'].includes(state) ? 'warn' : ['OPENING', 'CLOSING'].includes(state) ? 'info' : 'idle';
  const progress = Number.isFinite(monitoring.gateProgress) ? `${Math.round(Math.max(0, Math.min(1, monitoring.gateProgress)) * 100)}%` : '—';
  const confidence = Number.isFinite(monitoring.gateConfidence) ? monitoring.gateConfidence.toFixed(2) : '—';
  return (
    <Card title="Gate State" aside={<Pill tone={tone} className="!rounded-full">{state ? gateLabel(state) : monitoring.status}</Pill>}>
      <dl className="grid grid-cols-2 gap-3">
        <div><dt className="text-xs text-[#55607A]">Gate progress</dt><dd className="mt-1 text-2xl font-bold text-[#0F1B3D]">{progress}</dd></div>
        <div><dt className="text-xs text-[#55607A]">Confidence</dt><dd className="mt-1 text-2xl font-bold text-[#0F1B3D]">{confidence}</dd></div>
      </dl>
      {note && <p className="mt-3 text-xs text-[#55607A]">{note}</p>}
    </Card>
  );
}

export function CrossingEventsPanel({ monitoring }) {
  const total = monitoring.crossingTotal ?? monitoring.crossings.length;
  return (
    <Card title="Recent Crossing Events" aside={`${total} ${total === 1 ? 'event' : 'events'}`}>
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-lg bg-[#F7F8FC] p-3 ring-1 ring-[#E3E7F0]">
          <p className="text-xs text-[#55607A]">ENTRY</p>
          <p className="mt-1 text-2xl font-bold text-[#0F1B3D]">{monitoring.entryCount}</p>
        </div>
        <div className="rounded-lg bg-[#F7F8FC] p-3 ring-1 ring-[#E3E7F0]">
          <p className="text-xs text-[#55607A]">EXIT</p>
          <p className="mt-1 text-2xl font-bold text-[#0F1B3D]">{monitoring.exitCount}</p>
        </div>
      </div>
      {monitoring.crossings.length ? (
        <ul className="mt-2 max-h-64 divide-y divide-[#E3E7F0] overflow-y-auto">
          {monitoring.crossings.map((event) => (
            <li key={event.id} className="flex items-center gap-4 py-2.5 text-sm">
              <span className="w-16 shrink-0 whitespace-nowrap tabular-nums text-[#55607A]">{event.timeLabel}</span>
              <span className="min-w-0 truncate text-[#0F1B3D]">{event.direction}{event.cameraLabel ? ` · ${event.cameraLabel.toLowerCase().replace('track ', 'track #')}` : ''}</span>
            </li>
          ))}
        </ul>
      ) : <p className="mt-3 text-sm text-[#55607A]">No crossing events yet</p>}
    </Card>
  );
}

function AlertActions({ alert, busy, onAction }) {
  if (!onAction) return null;
  const actions = ['acknowledge', 'resolve'].filter((action) => alert.actions?.includes(action));
  if (!actions.length) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {actions.map((action) => (
        <button key={action} type="button" className={btnGhost} disabled={busy} onClick={() => onAction(alert, action)}>
          {action === 'acknowledge' ? 'Acknowledge' : 'Resolve'}
        </button>
      ))}
    </div>
  );
}

export function AlertsPanel({ monitoring, onAction, busyAlertId, error }) {
  const active = monitoring.activeAlertCount ?? monitoring.alerts.length;
  return (
    <Card title="Active Alerts" aside={`${active} open`}>
      {monitoring.alertsAvailable === false && <p role="status" className="mb-2 text-xs text-amber-800">The shared Alert Service is unavailable, so alerts cannot be listed right now.</p>}
      {error && <p role="alert" className="mb-2 text-xs text-rose-800">{error}</p>}
      {monitoring.alerts.length > 0 && (
        <ul className="space-y-2">
          {monitoring.alerts.map((alert) => (
            <li key={alert.id} className="rounded-lg bg-[#F7F8FC] p-3 ring-1 ring-[#E3E7F0]">
              <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-[#0F1B3D]">
                <Pill tone={alert.active === false ? 'idle' : alert.severity === 'INFO' ? 'info' : alert.severity === 'WARNING' ? 'warn' : 'bad'} className="!rounded-full">{alert.severity}</Pill>
                {alert.title ?? alert.type}
              </p>
              <p className="mt-1 text-xs text-[#55607A]">{monitoring.source === 'video' && alert.timeLabel ? `Video time ${alert.timeLabel} · ` : alert.timeLabel ? `${alert.timeLabel} · ` : ''}Status {alert.status}</p>
              <AlertActions alert={alert} busy={busyAlertId === alert.id} onAction={onAction} />
            </li>
          ))}
        </ul>
      )}
      {monitoring.alertsAvailable !== false && !active && !monitoring.alerts.length && <p className="text-sm text-[#55607A]">No active alerts</p>}
    </Card>
  );
}

export function MeshPanel({ monitoring }) {
  return (
    <Card title="Mesh Area Monitoring">
      <dl className="grid grid-cols-2 gap-3">
        <div><dt className="text-xs text-[#55607A]">Current people</dt><dd className="mt-1 text-2xl font-bold text-[#0F1B3D]">{monitoring.meshPeopleCount}</dd></div>
        <div><dt className="text-xs text-[#55607A]">Gathering duration</dt><dd className="mt-1 text-2xl font-bold text-[#0F1B3D]">{clock(monitoring.meshGatheringSeconds)}</dd></div>
      </dl>
      {monitoring.meshEvents?.length ? (
        <ul className="mt-2 divide-y divide-[#E3E7F0]">
          {monitoring.meshEvents.map((event) => (
            <li key={event.id} className="flex items-center justify-between gap-3 py-2 text-xs"><span className="text-[#0F1B3D]">{event.title}</span><span className="tabular-nums text-[#55607A]">{event.timeLabel}</span></li>
          ))}
        </ul>
      ) : <EmptyState icon={Users}>No mesh events yet</EmptyState>}
    </Card>
  );
}

export function TimelinePanel({ monitoring, note }) {
  return (
    <Card title="Monitoring Event Timeline">
      {monitoring.events.length ? (
        <ol className="max-h-80 divide-y divide-[#E3E7F0] overflow-y-auto border-t border-[#E3E7F0]">
          {monitoring.events.map((event) => (
            <li key={event.id} className="flex items-center gap-6 py-2.5 text-sm">
              <span className="w-16 shrink-0 whitespace-nowrap tabular-nums text-[#55607A]">{event.timeLabel}</span>
              <span className="min-w-0 text-[#0F1B3D]">{event.title}</span>
            </li>
          ))}
        </ol>
      ) : <EmptyState icon={History}>No monitoring events available</EmptyState>}
      {note && <p className="mt-2 text-xs text-[#55607A]">{note}</p>}
    </Card>
  );
}

/** Dark frame area shared by the live and video previews. Buttons for a preview sit below it, never on it. */
export function PreviewStage({ url, alt, message, badge, aspect = 16 / 9 }) {
  return (
    <div className="relative overflow-hidden rounded-lg bg-[#18202E]" style={{ aspectRatio: String(aspect) }}>
      {url && <img src={url} alt={alt} className="absolute inset-0 h-full w-full object-contain" />}
      {!url && <p className="absolute inset-0 flex items-center justify-center p-6 text-center text-sm text-slate-200">{message}</p>}
      {badge && <span className="absolute left-3 top-3">{badge}</span>}
    </div>
  );
}
