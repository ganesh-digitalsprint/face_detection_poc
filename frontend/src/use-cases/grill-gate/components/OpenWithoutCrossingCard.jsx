import { useSelector } from 'react-redux';
import { gateSession } from '../../../store/slices/gateMonitoringSlice.js';
import { formatClock, GATE_STATES } from '../grillGateModel.js';
import { Pill } from './ui.jsx';

const clock = (seconds) => (seconds == null ? '\u2014' : formatClock(seconds));
const gateLabel = (state) => GATE_STATES[state]?.label ?? state;

/** Display only: the page controller owns threshold requests and Redux owns cycles. */
export default function OpenWithoutCrossingCard({ monitoring, gateState }) {
  const stopped = ['PARTIALLY_OPEN', 'CLOSED'].includes(gateState);
  const recorded = !stopped && monitoring.finalTimer && (monitoring.openWithoutCrossingSeconds == null || !monitoring.timerRecorded)
    ? monitoring.recordedTimerDisplay : null;
  const threshold = recorded?.thresholdSeconds ?? monitoring.openWithoutCrossingThresholdSeconds;
  const gate = useSelector((state) => gateSession(state.gateMonitoring, monitoring.gateSessionId));
  const cycleId = `${monitoring.gateSessionId}:${monitoring.cycleStartedAt}`;
  const request = gate.alertRequests?.[cycleId];
  const finalTimer = monitoring.finalTimer;
  const elapsed = recorded?.elapsedSeconds ?? monitoring.openWithoutCrossingSeconds;
  const sinceCrossing = Number.isFinite(monitoring.secondsSinceCrossing)
    ? Math.max(0, monitoring.source === 'video' ? Math.floor(monitoring.secondsSinceCrossing) : Math.round(monitoring.secondsSinceCrossing)) : null;
  const thresholdConfigured = monitoring.thresholdConfigured === true
    || (monitoring.thresholdConfigured == null && threshold != null);
  const timerUnavailable = !recorded && gateState === 'FULLY_OPEN' && elapsed == null;
  const timerState = stopped ? 'NOT_COUNTING' : (request?.status === 'COUNTING' ? null : request?.status) ?? (gateState !== 'FULLY_OPEN' ? 'NOT_COUNTING'
      : threshold != null && elapsed != null && elapsed >= threshold ? 'THRESHOLD_REACHED' : 'COUNTING');
  const timerNotRecorded = monitoring.source === 'video' && finalTimer && !monitoring.timerRecorded && !recorded && !stopped;
  const tone = timerState === 'ALERT_RAISED' ? 'bad' : timerState === 'NOT_COUNTING' ? 'idle' : 'info';
  const notCounting = timerState === 'NOT_COUNTING' && !recorded;
  const value = notCounting ? '00:00' : recorded ? `${clock(elapsed)} / ${clock(threshold)}`
    : timerNotRecorded ? 'No persisted timer duration is available for this job.'
    : timerUnavailable ? '\u2014' : gateState !== 'FULLY_OPEN' ? '\u2014'
      : `${clock(elapsed)} / ${thresholdConfigured && threshold != null ? clock(threshold) : '\u2014'}`;
  const support = notCounting ? (gateState ? `Gate is ${gateLabel(gateState).toLowerCase()}` : 'Waiting for gate state')
    : recorded ? `${recorded.source === 'alert' ? 'Recorded alert duration' : 'Saved video timer'}: ${elapsed} s${recorded.videoTimeSeconds != null ? ` at video ${clock(recorded.videoTimeSeconds)}` : ''}`
    : request?.status === 'ALERT_REQUEST_PENDING' ? 'Creating backend alert...'
    : request?.status === 'ALERT_REQUEST_FAILED' ? 'Alert request failed. Retrying...' : timerNotRecorded ? '' : timerUnavailable ? 'Timer data unavailable'
    : timerState === 'ALERT_RAISED' ? 'Alert: GATE_OPEN_TOO_LONG'
      : timerState === 'THRESHOLD_REACHED' ? 'Threshold reached - backend alert pending'
        : gateState === 'FULLY_OPEN' && !thresholdConfigured ? 'Threshold not configured'
          : gateState === 'FULLY_OPEN' ? (sinceCrossing != null ? `Last crossing: ${sinceCrossing} seconds ago` : 'No crossing since gate opened')
            : gateState ? `Gate is ${gateLabel(gateState).toLowerCase()}` : '';
  const chip = finalTimer ? 'FINAL' : notCounting ? 'NOT COUNTING' : request?.status === 'ALERT_REQUEST_PENDING' ? 'ALERT REQUEST PENDING'
    : request?.status === 'ALERT_REQUEST_FAILED' ? 'ALERT REQUEST FAILED' : timerUnavailable ? 'TIMER UNAVAILABLE'
    : timerState === 'ALERT_RAISED' ? 'ALERT RAISED' : timerState === 'THRESHOLD_REACHED' ? 'THRESHOLD REACHED'
      : gateState === 'FULLY_OPEN' ? 'COUNTING' : 'NOT COUNTING';

  return <div className={`rounded-xl border p-3 ${timerState === 'ALERT_RAISED' ? 'border-rose-300 bg-rose-50' : 'border-[#E3E7F0] bg-white'}`}>
    <div className="flex items-center justify-between gap-2">
      <p className="text-xs text-[#55607A]">Open without crossing</p>
      <Pill tone={timerNotRecorded ? 'idle' : tone} className="!rounded-full">{chip}</Pill>
    </div>
    <p className={`mt-1 text-[#0F1B3D] ${timerNotRecorded ? 'text-xs font-medium leading-5' : 'text-2xl font-bold tabular-nums'}`}>{value}</p>
    {support && !timerNotRecorded && <p className="mt-1.5 text-xs text-[#55607A]">{monitoring.source === 'video' && 'Video time \u00b7 '}{support}</p>}
  </div>;
}
