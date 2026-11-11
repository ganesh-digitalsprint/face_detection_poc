import { createSlice } from '@reduxjs/toolkit';

export const GATE_MONITORING_DWELL_MS = 200;
export const GATE_STATES = Object.freeze(['UNKNOWN', 'CLOSED', 'PARTIALLY_OPEN', 'FULLY_OPEN']);
const CONFIRMED_STATES = new Set(GATE_STATES.slice(1));
const MAX_TRANSITIONS = 100;

export const initialGateMonitoringState = (sessionId = null) => ({
  sessionId,
  alertRequests: {},
  videoTimestampSeconds: null,
  videoProcessingStatus: null,
  videoGateOpenStoppedSeconds: null,
  gateState: 'UNKNOWN',
  lastValidProgress: null,
  currentProgress: null,
  measurementAvailable: false,
  lastUpdatedAt: null,
  direction: null,
  transitions: [],
  candidateState: null,
  candidateSince: null,
  candidateTimebase: null,
  gateOpenedAt: null,
  cycleStartedAt: null,
  timerTimebase: null,
  lastCrossingAt: null,
  lastCrossingId: null,
  seenCrossingIds: [],
  lastEntryCount: null,
  lastExitCount: null,
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
    updateVideoTimerSample(state, action) {
      const { sessionId, timestampSeconds, status } = action.payload ?? {};
      if (sessionId !== state.sessionId
          || ['COMPLETED', 'FAILED', 'CANCELLED'].includes(state.videoProcessingStatus)) return;
      if (Number.isFinite(timestampSeconds) && timestampSeconds >= 0
          && (state.videoTimestampSeconds == null || timestampSeconds >= state.videoTimestampSeconds)) {
        state.videoTimestampSeconds = timestampSeconds;
      }
      if (typeof status === 'string') state.videoProcessingStatus = status;
    },
    setOpenTimerRequest(state, action) {
      state.alertRequests ??= {};
      state.alertRequests[action.payload.cycleId] = action.payload;
    },
    restoreGateMonitoring(state, action) {
      const sessionId = action.payload?.sessionId ?? null;
      if (state.sessionId !== sessionId) return initialGateMonitoringState(sessionId);
      state.currentProgress = null;
      state.measurementAvailable = false;
      state.candidateState = null;
      state.candidateSince = null;
      state.candidateTimebase = null;
    },
    resetGateMonitoring(_state, action) {
      return initialGateMonitoringState(action.payload?.sessionId ?? null);
    },
    updateGateProgress(state, action) {
      const { sessionId = null, progress, observedAt = Date.now(), timebase = 'wall' } = action.payload ?? {};
      if (sessionId !== state.sessionId) return;

      // Late or terminal video samples cannot reopen a completed footage timer.
      if (timebase === 'video' && (['COMPLETED', 'FAILED', 'CANCELLED'].includes(state.videoProcessingStatus)
          || !Number.isFinite(observedAt) || observedAt < 0
          || (Number.isFinite(state.videoTimestampSeconds) && observedAt < state.videoTimestampSeconds * 1000)
          || ((state.timerTimebase === 'video' || state.candidateTimebase === 'video')
            && Number.isFinite(state.lastUpdatedAt) && observedAt < state.lastUpdatedAt))) return;
      state.lastUpdatedAt = observedAt;
      if (typeof progress !== 'number' || !Number.isFinite(progress) || progress < 0 || progress > 1) {
        state.currentProgress = null;
        state.measurementAvailable = false;
        state.candidateState = null;
        state.candidateSince = null;
        state.candidateTimebase = null;
        return;
      }

      state.currentProgress = progress;
      state.lastValidProgress = progress;
      state.measurementAvailable = true;
      const candidate = classifyGateProgress(state.gateState, progress);
      if (candidate === state.gateState) {
        if (state.gateState === 'FULLY_OPEN' && state.gateOpenedAt == null) {
          state.gateOpenedAt = observedAt;
          state.cycleStartedAt = observedAt;
          state.timerTimebase = timebase;
        }
        state.candidateState = null;
        state.candidateSince = null;
        state.candidateTimebase = null;
        return;
      }
      if (candidate !== state.candidateState || timebase !== state.candidateTimebase) {
        state.candidateState = candidate;
        state.candidateSince = observedAt;
        state.candidateTimebase = timebase;
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
      state.transitions.push({ fromState: previousState, toState: candidate, progress, at: observedAt, timebase, direction });
      if (state.transitions.length > MAX_TRANSITIONS) state.transitions.splice(0, state.transitions.length - MAX_TRANSITIONS);
      if (candidate === 'FULLY_OPEN') {
        if (timebase === 'video') state.videoGateOpenStoppedSeconds = null;
        state.gateOpenedAt = observedAt;
        state.cycleStartedAt = observedAt;
        state.timerTimebase = timebase;
        state.lastCrossingAt = null;
        state.lastCrossingId = null;
        state.seenCrossingIds = [];
      } else if (previousState === 'FULLY_OPEN') {
        if (timebase === 'video' && Number.isFinite(state.gateOpenedAt)) {
          state.videoGateOpenStoppedSeconds = Math.max(0, (observedAt - state.gateOpenedAt) / 1000);
        }
        state.gateOpenedAt = null;
        state.cycleStartedAt = null;
        state.timerTimebase = null;
        state.lastCrossingAt = null;
        state.lastCrossingId = null;
        state.seenCrossingIds = [];
      }
      state.candidateState = null;
      state.candidateSince = null;
      state.candidateTimebase = null;
    },
    recordQualifyingCrossing(state, action) {
      const { sessionId = null, eventId, at, timebase = 'wall' } = action.payload ?? {};
      if (sessionId !== state.sessionId || (timebase === 'video' && ['COMPLETED', 'FAILED', 'CANCELLED'].includes(state.videoProcessingStatus))
          || state.gateState !== 'FULLY_OPEN'
          || !eventId || !Number.isFinite(at) || timebase !== state.timerTimebase
          || (state.gateOpenedAt != null && at < state.gateOpenedAt)
          || state.seenCrossingIds.includes(eventId)) return;
      state.seenCrossingIds.push(eventId);
      if (state.seenCrossingIds.length > 200) state.seenCrossingIds.shift();
      if (state.cycleStartedAt != null && at <= state.cycleStartedAt) return;
      state.lastCrossingId = eventId;
      state.lastCrossingAt = at;
      state.cycleStartedAt = at;
    },
    updateCrossingCounts(state, action) {
      const { sessionId = null, entryCount = null, exitCount = null, observedAt = Date.now(), timebase = 'wall', entryCrossingAt = null, exitCrossingAt = null } = action.payload ?? {};
      if (sessionId !== state.sessionId || (timebase === 'video'
          && (['COMPLETED', 'FAILED', 'CANCELLED'].includes(state.videoProcessingStatus)
            || (Number.isFinite(state.videoTimestampSeconds) && observedAt < state.videoTimestampSeconds * 1000)))) return;
      const entryIncreased = Number.isFinite(entryCount) && Number.isFinite(state.lastEntryCount)
        && entryCount > state.lastEntryCount;
      const exitIncreased = Number.isFinite(exitCount) && Number.isFinite(state.lastExitCount)
        && exitCount > state.lastExitCount;
      const eventTimes = [entryIncreased ? entryCrossingAt : null, exitIncreased ? exitCrossingAt : null]
        .filter((at) => Number.isFinite(at) && at >= 0 && at <= observedAt);
      const resetAt = timebase === 'video' && eventTimes.length ? Math.max(...eventTimes) : observedAt;
      if ((entryIncreased || exitIncreased) && state.gateState === 'FULLY_OPEN'
          && timebase === state.timerTimebase && Number.isFinite(observedAt)
          && (state.gateOpenedAt == null || resetAt >= state.gateOpenedAt)
          && (timebase !== 'video' || state.cycleStartedAt == null || resetAt >= state.cycleStartedAt)) {
        state.lastCrossingAt = resetAt;
        state.cycleStartedAt = resetAt;
      }
      if (Number.isFinite(entryCount)) state.lastEntryCount = entryCount;
      if (Number.isFinite(exitCount)) state.lastExitCount = exitCount;
    },
  },
});

export const { updateVideoTimerSample, setOpenTimerRequest, restoreGateMonitoring, resetGateMonitoring, updateGateProgress, recordQualifyingCrossing, updateCrossingCounts } = gateMonitoringSlice.actions;
export const selectGateMonitoring = (state) => state.gateMonitoring;
// Keep each source alive when the visible tab changes. The root projection preserves
// the existing selector contract; background samples are routed to their own session.
export default function reducer(state, action) {
  const sessionId = action.payload?.sessionId;
  const sessions = state?.sessions ?? {};
  if (sessionId && sessionId !== state?.sessionId) {
    const next = gateMonitoringSlice.reducer(sessions[sessionId] ?? initialGateMonitoringState(sessionId), action);
    if (action.type === restoreGateMonitoring.type || !state?.sessionId) {
      const { sessions: ignored, ...previous } = state ?? {};
      return { ...next, sessions: { ...sessions, ...(state?.sessionId ? { [state.sessionId]: previous } : {}), [sessionId]: next } };
    }
    return { ...state, sessions: { ...sessions, [sessionId]: next } };
  }
  const next = gateMonitoringSlice.reducer(state, action);
  return { ...next, sessions };
}
export const gateSession = (state, sessionId) => state.sessionId === sessionId ? state : state.sessions?.[sessionId] ?? initialGateMonitoringState(sessionId);
