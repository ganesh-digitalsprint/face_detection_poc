import { createSlice } from '@reduxjs/toolkit';

export const GATE_MONITORING_DWELL_MS = 200;
export const GATE_STATES = Object.freeze(['UNKNOWN', 'CLOSED', 'PARTIALLY_OPEN', 'FULLY_OPEN']);
const CONFIRMED_STATES = new Set(GATE_STATES.slice(1));
const MAX_TRANSITIONS = 100;

export const initialGateMonitoringState = (sessionId = null) => ({
  sessionId,
  gateState: 'UNKNOWN',
  lastValidProgress: null,
  currentProgress: null,
  measurementAvailable: false,
  lastUpdatedAt: null,
  direction: null,
  transitions: [],
  candidateState: null,
  candidateSince: null,
});

/** Return the state hysteresis selects for this exact normalized progress sample. */
export function classifyGateProgress(currentState, progress) {
  if (typeof progress !== 'number' || !Number.isFinite(progress) || progress < 0 || progress > 1) return null;
  switch (currentState) {
    case 'CLOSED':
      return progress >= 0.25 ? 'PARTIALLY_OPEN' : 'CLOSED';
    case 'PARTIALLY_OPEN':
      if (progress >= 0.8) return 'FULLY_OPEN';
      return progress < 0.2 ? 'CLOSED' : 'PARTIALLY_OPEN';
    case 'FULLY_OPEN':
      if (progress < 0.2) return 'CLOSED';
      return progress < 0.75 ? 'PARTIALLY_OPEN' : 'FULLY_OPEN';
    default:
      if (progress >= 0.8) return 'FULLY_OPEN';
      return progress >= 0.25 ? 'PARTIALLY_OPEN' : 'CLOSED';
  }
}

const directionBetween = (from, to) => {
  if (!CONFIRMED_STATES.has(from) || !CONFIRMED_STATES.has(to) || from === to) return null;
  const rank = { CLOSED: 0, PARTIALLY_OPEN: 1, FULLY_OPEN: 2 };
  return rank[to] > rank[from] ? 'OPENING' : 'CLOSING';
};

const elapsedMilliseconds = (start, end) => {
  const startMs = typeof start === 'number' ? start : Date.parse(start);
  const endMs = typeof end === 'number' ? end : Date.parse(end);
  return Number.isFinite(startMs) && Number.isFinite(endMs) ? endMs - startMs : 0;
};

const gateMonitoringSlice = createSlice({
  name: 'gateMonitoring',
  initialState: initialGateMonitoringState(),
  reducers: {
    restoreGateMonitoring(state, action) {
      const sessionId = action.payload?.sessionId ?? null;
      if (state.sessionId !== sessionId) return initialGateMonitoringState(sessionId);
      state.currentProgress = null;
      state.measurementAvailable = false;
      state.candidateState = null;
      state.candidateSince = null;
    },
    resetGateMonitoring(_state, action) {
      return initialGateMonitoringState(action.payload?.sessionId ?? null);
    },
    updateGateProgress(state, action) {
      const { sessionId = null, progress, observedAt = Date.now() } = action.payload ?? {};
      if (sessionId !== state.sessionId) return;

      state.lastUpdatedAt = observedAt;
      if (typeof progress !== 'number' || !Number.isFinite(progress) || progress < 0 || progress > 1) {
        state.currentProgress = null;
        state.measurementAvailable = false;
        state.candidateState = null;
        state.candidateSince = null;
        return;
      }

      state.currentProgress = progress;
      state.lastValidProgress = progress;
      state.measurementAvailable = true;
      const candidate = classifyGateProgress(state.gateState, progress);
      if (candidate === state.gateState) {
        state.candidateState = null;
        state.candidateSince = null;
        return;
      }
      if (candidate !== state.candidateState) {
        state.candidateState = candidate;
        state.candidateSince = observedAt;
        return;
      }
      // Confirm only on another valid API sample. The existing video/live
      // poll intervals are 2 s/3 s, so UI confirmation can be slower than this
      // 200 ms minimum; never use a timeout to infer an unobserved measurement.
      if (elapsedMilliseconds(state.candidateSince, observedAt) < GATE_MONITORING_DWELL_MS) return;

      const previousState = state.gateState;
      const direction = directionBetween(previousState, candidate);
      state.gateState = candidate;
      state.direction = direction ?? state.direction;
      state.transitions.push({ fromState: previousState, toState: candidate, progress, at: observedAt, direction });
      if (state.transitions.length > MAX_TRANSITIONS) state.transitions.splice(0, state.transitions.length - MAX_TRANSITIONS);
      state.candidateState = null;
      state.candidateSince = null;
    },
  },
});

export const { restoreGateMonitoring, resetGateMonitoring, updateGateProgress } = gateMonitoringSlice.actions;
export const selectGateMonitoring = (state) => state.gateMonitoring;
export default gateMonitoringSlice.reducer;
