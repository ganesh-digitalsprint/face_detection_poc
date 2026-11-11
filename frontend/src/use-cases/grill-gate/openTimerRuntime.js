import { store } from '../../store/index.js';
import { gateSession, setOpenTimerRequest } from '../../store/slices/gateMonitoringSlice.js';
import { evaluateLiveOpenGateAlert, evaluateVideoOpenGateAlert } from './api/grillGate.js';
import { createOpenTimerController } from './openTimerController.js';
const controller = createOpenTimerController({
  isCurrent: (m) => {
    const gate = gateSession(store.getState().gateMonitoring, m.gateSessionId);
    const captured = gate.alertRequests?.[`${m.gateSessionId}:${m.cycleStartedAt}`];
    return Boolean(captured) || (gate.gateState === 'FULLY_OPEN' && gate.cycleStartedAt === m.cycleStartedAt);
  },
  scheduleRetry: (fn, delay) => setTimeout(fn, delay),
  read: (sessionId, cycleId) => gateSession(store.getState().gateMonitoring, sessionId).alertRequests?.[cycleId],
  write: (value) => store.dispatch(setOpenTimerRequest(value)),
  request: async (m, payload) => {
    const id = m.gateSessionId.slice(m.source === 'video' ? 6 : 5);
    const evaluate = m.source === 'video' ? evaluateVideoOpenGateAlert : evaluateLiveOpenGateAlert;
    return evaluate(id, payload.elapsed_seconds, payload.threshold_seconds, payload);
  },
});


const liveThresholdTimers = new Map();
export function evaluateOpenTimer(m) {
  if (m.source === 'live' && m.gateSessionId) {
    clearTimeout(liveThresholdTimers.get(m.gateSessionId));
    liveThresholdTimers.delete(m.gateSessionId);
    const remaining = m.openWithoutCrossingThresholdSeconds - m.openWithoutCrossingSeconds;
    if (m.gateState === 'FULLY_OPEN' && m.status === 'ACTIVE' && m.cycleStartedAt != null
        && m.openWithoutCrossingSeconds != null && remaining > 0) {
      liveThresholdTimers.set(m.gateSessionId, setTimeout(() => {
        liveThresholdTimers.delete(m.gateSessionId);
        controller({ ...m, openWithoutCrossingSeconds: (Date.now() - m.cycleStartedAt) / 1000 });
      }, remaining * 1000));
    }
  }
  return controller(m);
}
