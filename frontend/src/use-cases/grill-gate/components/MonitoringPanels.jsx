import { BellOff, History, Users } from 'lucide-react';
import { useSelector } from 'react-redux';
import { formatClock, GATE_STATES } from '../grillGateModel.js';
import { btnGhost, Card, Pill, StatCard } from './ui.jsx';

const UNKNOWN_GATE = Object.freeze({ gateState: 'UNKNOWN', direction: null });
function useGateClassification(monitoring) {
  const current = useSelector((state) => state.gateMonitoring);
  return monitoring.gateSessionId && current.sessionId === monitoring.gateSessionId ? current : UNKNOWN_GATE;
}

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

function LegacyMonitoringStats({ monitoring }) {
  const gate = useGateClassification(monitoring);
  const state = gate.gateState;
  const tone = GATE_STATES[state]?.tone ?? 'text-[#69758F]';
  return (
    <div className="grid grid-cols-2 gap-3 xl:grid-cols-3">
      <StatCard label="Gate state" value={state ? gateLabel(state) : '—'} valueClass={state && state !== 'UNKNOWN' ? tone : 'text-[#69758F]'}
        sub={monitoring.gateStateTimeLabel ? `At crossing ${monitoring.gateStateTimeLabel}` : null} />
      <StatCard label="Open without crossing" value={state === 'FULLY_OPEN' ? clock(monitoring.openWithoutCrossingSeconds) : 'â€”'} valueClass="text-[#0F1B3D]" />
      <StatCard label="People in mesh area" value={monitoring.meshPeopleCount} valueClass="text-[#0F1B3D]" />
    </div>
  );
}

export function MonitoringStats({ monitoring }) {
  const gate = useGateClassification(monitoring);
  const state = gate.gateState;
  const threshold = monitoring.openWithoutCrossingThresholdSeconds;
  const elapsed = monitoring.openWithoutCrossingSeconds;
  const percent = Number.isFinite(monitoring.timerProgressPercent)
    ? Math.max(0, Math.min(100, monitoring.timerProgressPercent)) : null;
  const timerState = monitoring.timerState ?? (state === 'FULLY_OPEN' ? 'TIMER_UNAVAILABLE' : 'NOT_COUNTING');
  const thresholdConfigured = monitoring.thresholdConfigured === true
    || (monitoring.thresholdConfigured == null && threshold != null);
  const oldCompletedJob = monitoring.source === 'video' && monitoring.finalTimer && !monitoring.timerRecorded;
  const timerUnavailable = state === 'FULLY_OPEN' && !oldCompletedJob
    && (elapsed == null || monitoring.gateOpenSeconds == null || timerState === 'TIMER_UNAVAILABLE');
  const pillTone = timerState === 'ALERT_RAISED' ? 'bad' : timerState === 'NOT_COUNTING' ? 'idle' : 'info';
  const openSince = monitoring.source === 'video'
    ? (monitoring.videoTimeSeconds != null && monitoring.gateOpenSeconds != null ? clock(Math.max(0, monitoring.videoTimeSeconds - monitoring.gateOpenSeconds)) : null)
    : monitoring.gateOpenSince ? new Date(monitoring.gateOpenSince).toLocaleTimeString(undefined, { hourCycle: 'h23' }) : null;
  const gateSub = state === 'FULLY_OPEN' ? `Since ${openSince ?? '\u2014'}` : state === 'CLOSED' ? 'Gate is closed' : state === 'PARTIALLY_OPEN' ? `Gate is partially open${monitoring.gateDirection ? ` · ${monitoring.gateDirection.toLowerCase()}` : ''}` : 'Gate state unknown';
  const finished = monitoring.finalTimer;
  const timerNotRecorded = oldCompletedJob;
  const value = timerNotRecorded ? 'Timer data not recorded for this job. Upload the video again to capture it.'
    : timerUnavailable ? '\u2014'
      : state !== 'FULLY_OPEN' ? '\u2014'
        : `${clock(elapsed)} / ${thresholdConfigured && threshold != null ? clock(threshold) : '\u2014'}`;
  const lastCrossingText = monitoring.lastCrossingAt
    ? `Last crossing: ${Math.max(0, Math.round(monitoring.secondsSinceCrossing ?? 0))} seconds ago`
    : 'No crossing since gate opened';
  const supportText = timerNotRecorded ? '' : timerUnavailable ? 'Timer data unavailable'
    : state === 'FULLY_OPEN' && !thresholdConfigured ? 'Threshold not configured'
      : state === 'FULLY_OPEN' ? lastCrossingText
        : state === 'CLOSED' ? 'Gate is closed' : state ? `Gate is ${gateLabel(state).toLowerCase()}` : '';
  const chip = timerNotRecorded ? 'FINAL' : finished ? 'FINAL'
    : timerUnavailable ? 'TIMER UNAVAILABLE'
      : timerState === 'ALERT_RAISED' ? 'ALERT RAISED'
    : state === 'FULLY_OPEN' ? 'COUNTING' : 'NOT COUNTING';
  const canShowProgress = state === 'FULLY_OPEN' && thresholdConfigured && threshold > 0 && percent != null && !timerUnavailable && !timerNotRecorded;
  return <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-[1fr_1fr_1.7fr_1fr]">
    <StatCard label="Gate state" value={state ? gateLabel(state) : '\u2014'} valueClass={state && state !== 'UNKNOWN' ? (GATE_STATES[state]?.tone ?? 'text-[#69758F]') : 'text-[#69758F]'} sub={monitoring.gateStateTimeLabel || 'Confirmed state'} />
    <StatCard label="Gate open" value={monitoring.gateOpenSeconds == null ? '\u2014' : clock(monitoring.gateOpenSeconds)} valueClass="text-[#0F1B3D]" sub={`${monitoring.finalTimer ? 'Final · ' : ''}${gateSub}`} />
    <div className={`rounded-xl border p-3 ${timerState === 'ALERT_RAISED' ? 'border-rose-300 bg-rose-50' : 'border-[#E3E7F0] bg-white'}`}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-[#55607A]">Open without crossing</p>
        <Pill tone={timerNotRecorded ? 'idle' : pillTone} className="!rounded-full">{chip}</Pill>
      </div>
      <p className={`mt-1 text-[#0F1B3D] ${timerNotRecorded ? 'text-xs font-medium leading-5' : 'text-2xl font-bold tabular-nums'}`}>{value}</p>
      {canShowProgress && <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[#E3E7F0]" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
        <div className={`h-full rounded-full ${timerState === 'ALERT_RAISED' ? 'bg-rose-600' : 'bg-[#34479B]'}`} style={{ width: `${percent}%` }} />
      </div>}
      {supportText && !timerNotRecorded && <p className="mt-1.5 text-xs text-[#55607A]">{supportText}</p>}
    </div>
    <StatCard label="People in mesh area" value={monitoring.meshPeopleCount} valueClass="text-[#0F1B3D]" sub="Current detected people" />
  </div>;
}

export function GateStatePanel({ monitoring, note }) {
  const gate = useGateClassification(monitoring);
  const state = gate.gateState;
  const tone = state === 'CLOSED' ? 'ok' : ['FULLY_OPEN', 'PARTIALLY_OPEN'].includes(state) ? 'warn' : 'idle';
  const states = [
    ['CLOSED', 'CLOSED'],
    ['PARTIALLY_OPEN', 'PARTIALLY OPEN'],
    ['FULLY_OPEN', 'FULLY OPEN'],
  ];
  return (
    <Card title="Gate State" aside={<Pill tone={tone} className="!rounded-full">{state || monitoring.status}</Pill>}>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        {states.map(([key, label]) => <div key={key} aria-current={state === key ? 'true' : undefined}
          className={`rounded-lg border p-3 ${state === key ? 'border-indigo-400 bg-indigo-50 text-[#0F1B3D]' : 'border-[#E3E7F0] bg-[#F7F8FC] text-[#69758F]'}`}>
          <p className="text-sm font-semibold">{label}</p>
          {state === key && key === 'PARTIALLY_OPEN' && gate.direction && <p className="mt-1 text-xs">{gate.direction}</p>}
        </div>)}
      </div>
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
      ) : <p className="mt-3 text-sm text-[#55607A]">
        {monitoring.crossingConfigStatus === 'missing_required_zones'
          ? 'Crossing detection needs enabled Gate approach and Gate interior endpoint zones.'
          : monitoring.crossingConfigStatus?.startsWith('invalid_zone')
            ? 'Crossing detection is unavailable because a crossing zone is invalid. Review the configured zones.'
            : 'No crossing events yet'}
      </p>}
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

function AlertRow({ alert, busyAlertId, onAction }) {
  const hasDuration = alert.gateOpenDurationSeconds != null || alert.configuredThresholdSeconds != null;
  const evidenceAvailable = alert.evidenceRefs?.length > 0;
  return (
    <li className="rounded-lg bg-[#F7F8FC] p-3 ring-1 ring-[#E3E7F0]">
      <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-[#0F1B3D]">
        <Pill tone={alert.active === false ? 'idle' : alert.severity === 'INFO' ? 'info' : alert.severity === 'WARNING' ? 'warn' : 'bad'} className="!rounded-full">{alert.severity}</Pill>
        {alert.title ?? alert.type}
      </p>
      <p className="mt-1 text-xs text-[#55607A]">
        {alert.cameraName ? `${alert.cameraName} · ` : ''}
        {alert.timeLabel ? `${alert.timeLabel} · ` : ''}Status {alert.status}
        {hasDuration ? ` · Open without crossing ${alert.gateOpenDurationSeconds ?? '—'}s / threshold ${alert.configuredThresholdSeconds ?? '—'}s` : ''}
      </p>
      <details className="mt-2 text-xs text-[#55607A]">
        <summary className="w-fit cursor-pointer font-medium text-[#34479B]">Alert details</summary>
        <p className="mt-2">{alert.message || 'No additional description.'}</p>
        {alert.cameraId && <p className="mt-1">Camera ID: {alert.cameraId}</p>}
        {alert.assignmentId && <p className="mt-1">Assignment ID: {alert.assignmentId}</p>}
        <p className="mt-1">{evidenceAvailable ? 'Evidence reference available.' : 'No snapshot evidence attached.'}</p>
      </details>
      <AlertActions alert={alert} busy={busyAlertId === alert.id} onAction={onAction} />
    </li>
  );
}

export function AlertsPanel({ monitoring, onAction, busyAlertId, error, onHistoryToggle,
  history = [], historyVisible = false, historyLoading = false, historyError = '' }) {
  const active = monitoring.activeAlertCount ?? monitoring.alerts.length;
  return (
    <Card title="Active Alerts" aside={`${active} open`}>
      {monitoring.alertsAvailable === false && <p role="status" className="mb-2 text-xs text-amber-800">{monitoring.alertsError || 'Could not load local Grill Gate alerts.'}</p>}
      {monitoring.source === 'live' && monitoring.alertsLoading && <p role="status" className="mb-2 text-xs text-[#55607A]">Loading local Grill Gate alerts…</p>}
      {monitoring.source === 'live' && !monitoring.alertsLoading && !monitoring.alertsRequestAttempted
        && <p className="mb-2 text-xs text-[#55607A]">Select a live camera assignment to load alerts.</p>}
      {error && <p role="alert" className="mb-2 text-xs text-rose-800">{error}</p>}
      {onHistoryToggle && <button type="button" className={`${btnGhost} mb-2`} onClick={onHistoryToggle} disabled={historyLoading}>
        {historyLoading ? 'Loading history…' : historyVisible ? 'Hide history' : 'View history'}
      </button>}
      {monitoring.alerts.length > 0 && (
        <ul className="space-y-2">
          {monitoring.alerts.map((alert) => <AlertRow key={alert.id} alert={alert} busyAlertId={busyAlertId} onAction={onAction} />)}
        </ul>
      )}
      {monitoring.alertsAvailable !== false && !monitoring.alertsLoading && monitoring.alertsRequestAttempted !== false
        && !active && !monitoring.alerts.length && <p className="text-sm text-[#55607A]">No active Grill Gate alerts.</p>}
      {historyVisible && <div className="mt-3 border-t border-[#E3E7F0] pt-3">
        <h3 className="mb-2 text-sm font-semibold text-[#0F1B3D]">Resolved alert history</h3>
        {historyError && <p role="alert" className="mb-2 text-xs text-rose-800">{historyError}</p>}
        {history.length > 0
          ? <ul className="space-y-2">{history.map((alert) => <AlertRow key={alert.id} alert={alert} busyAlertId={busyAlertId} onAction={onAction} />)}</ul>
          : !historyError && !historyLoading && <p className="text-sm text-[#55607A]">No resolved alerts yet.</p>}
      </div>}
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
export function PreviewStage({ url, alt, message, badge, aspect = 16 / 9, tracks = [], frameWidth, frameHeight }) {
  return (
    <div className="relative overflow-hidden rounded-lg bg-[#18202E]" style={{ aspectRatio: String(aspect) }}>
      {url && <img src={url} alt={alt} className="absolute inset-0 h-full w-full object-contain" />}
      {url && frameWidth > 0 && frameHeight > 0 && tracks.length > 0 && (
        <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox={`0 0 ${frameWidth} ${frameHeight}`} role="img" aria-label="Person tracking boxes">
          {tracks.map((track) => {
            const { track_id: trackId, bbox } = track;
            if (!Array.isArray(bbox) || bbox.length !== 4) return null;
            const [x1, y1, x2, y2] = bbox.map(Number);
            if (![x1, y1, x2, y2].every(Number.isFinite) || x2 <= x1 || y2 <= y1) return null;
            const foot = Array.isArray(track.foot_point) ? track.foot_point.map(Number) : [(x1 + x2) / 2, y2];
            const zones = Array.isArray(track.zone_membership) ? track.zone_membership : [];
            const fontSize = Math.max(14, frameWidth / 72);
            const lineHeight = fontSize * 1.18;
            const padding = fontSize * 0.35;
            const lines = [
              `ID ${trackId} · Zone: ${zones.length ? zones.join(', ') : 'unknown'}`,
              `Origin: ${track.origin_zone || 'unknown'}`,
              `Pending: ${track.pending_destination || 'none'} (${track.destination_frames ?? 0}/${track.required_destination_frames ?? 0})`,
            ];
            const labelWidth = Math.min(frameWidth - x1, Math.max(...lines.map((line) => line.length)) * fontSize * 0.58 + padding * 2);
            const labelY = Math.max(fontSize + padding, y1 + fontSize);
            const labelHeight = lineHeight * lines.length + padding * 2;
            return (
              <g key={trackId}>
                <rect x={x1} y={y1} width={x2 - x1} height={y2 - y1} fill="none" stroke="#34D399" strokeWidth={Math.max(3, frameWidth / 640)} />
                {foot.every(Number.isFinite) && <circle cx={foot[0]} cy={foot[1]} r={Math.max(8, frameWidth / 100)} fill="#F97316" stroke="#FFFFFF" strokeWidth={Math.max(3, frameWidth / 500)} />}
                <rect x={x1} y={labelY - fontSize - padding} width={labelWidth} height={labelHeight}
                  rx={fontSize * 0.22} fill="#111827" fillOpacity="0.82" />
                <text x={x1 + padding} y={labelY} fill="#FFFFFF" fontSize={fontSize} fontWeight="600">
                  {lines.map((line, index) => <tspan key={index} x={x1 + padding} dy={index === 0 ? 0 : lineHeight}>{line}</tspan>)}
                </text>
              </g>
            );
          })}
        </svg>
      )}
      {!url && <p className="absolute inset-0 flex items-center justify-center p-6 text-center text-sm text-slate-200">{message}</p>}
      {badge && <span className="absolute left-3 top-3">{badge}</span>}
    </div>
  );
}
