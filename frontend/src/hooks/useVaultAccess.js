import { useCallback, useEffect, useReducer, useRef } from 'react';
import { startLivenessSession, submitLivenessFrame } from '../api/vault.js';
import { describeError } from '../utils/errors.js';
import { BACKEND_TIMEOUT_STATUS, deriveDualState } from '../utils/dualControl.js';
import useCountdown from './useCountdown.js';

// Keep requests sequential, but resume capture promptly after each response.
// This avoids overlapping uploads while providing more challenge samples.
const FRAME_INTERVAL_MS = 50;
const MAX_CONSECUTIVE_FAILURES = 3;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const INITIAL = {
  phase: 'idle', // idle | starting | liveness | done | error
  sessionId: null,
  expiresAt: null, // backend-provided ISO timestamp; the only basis for the countdown
  requiredPersons: 2,
  authenticatedCount: 0,
  custodians: [], // employee ids in the order the backend verified them
  secondActive: false,
  ended: null, // null | ACCESS_GRANTED | SESSION_EXPIRED | DENIED | CANCELLED
  endReason: null,
  challenge: null,
  liveness: null, // last LivenessDecision from the backend
  result: null, // last full VaultAuthenticationResponse
  status: null,
  authenticatedCount: 0,
  requiredCount: 2,
  expiresAt: null,
  handoffUntil: null,
  handoffPending: false,
  now: Date.now(),
  error: null,
};

function applyFrame(state, response) {
  const count = response.authenticated_count ?? state.authenticatedCount;
  const employeeId = response.recognition?.employee_id;
  const verified = count > state.authenticatedCount;
  const custodians =
    verified && employeeId && !state.custodians.includes(employeeId)
      ? [...state.custodians, employeeId]
      : state.custodians;
  return {
    ...state,
    challenge: response.next_challenge ?? response.liveness.challenge,
    liveness: response.liveness,
    result: response,
    authenticatedCount: count,
    requiredPersons: response.required_count ?? state.requiredPersons,
    custodians,
    // Second custodian is "authenticating" once a face is in front of the camera after the first
    // custodian was verified (not on the very frame that verified the first one).
    secondActive: state.authenticatedCount >= 1 && count >= 1 && response.liveness.reason !== FACE_MISSING,
  };
}

// Only the backend can finish a session with a decision; everything else keeps the session open.
function frameOutcome(response) {
  if (response.access_granted === true && response.status === 'ACCESS_GRANTED') return 'ACCESS_GRANTED';
  if (response.status === BACKEND_TIMEOUT_STATUS) return 'SESSION_EXPIRED';
  return null;
}

function reducer(state, action) {
  switch (action.type) {
    case 'starting':
      return { ...INITIAL, phase: 'starting' };
    case 'session':
      return {
        ...state, phase: 'liveness', challenge: action.challenge,
        status: action.session.status, authenticatedCount: 0,
        requiredCount: action.session.required_persons ?? 2,
        expiresAt: action.session.expires_at,
        handoffUntil: null,
        handoffPending: false,
        now: Date.now(),
      };
    case 'frame': {
      const { response } = action;
      return {
        ...state,
        phase: action.terminal ? 'done' : 'liveness',
        challenge: response.next_challenge ?? response.liveness.challenge,
        liveness: response.liveness,
        result: response,
        status: response.status,
        authenticatedCount: response.authenticated_count ?? 0,
        requiredCount: response.required_count ?? state.requiredCount,
        handoffUntil: response.handoff_remaining_seconds > 0
          ? Date.now() + response.handoff_remaining_seconds * 1000
          : null,
        handoffPending: response.handoff_remaining_seconds > 0
          || (state.handoffPending && response.reason !== 'NEXT_PERSON_READY'),
      };
    }
    case 'frame': {
      const next = applyFrame(state, action.response);
      return action.ended
        ? { ...next, phase: 'done', ended: action.ended, sessionId: null }
        : next;
    }
    case 'ended':
      return { ...state, phase: 'done', ended: action.ended, endReason: action.reason ?? null, sessionId: null };
    case 'error':
      return { ...state, phase: 'error', error: action.error };
    case 'reset':
      return INITIAL;
    case 'tick':
      return { ...state, now: action.now };
    default:
      return state;
  }
}

// The dual-control session continues across person-level liveness attempts.
const isTerminal = (response) =>
  ['ACCESS_GRANTED', 'DUAL_AUTHENTICATION_TIMEOUT'].includes(response.status);

/**
 * Starts one dual-control session and feeds frames until the backend grants access or expires it.
 */
export default function useVaultAccess(camera) {
  const [state, dispatch] = useReducer(reducer, INITIAL);
  const runId = useRef(0);
  const cameraRef = useRef(camera);
  cameraRef.current = camera;

  const cancelLoop = useCallback(() => { runId.current += 1; }, []);

  const loop = useCallback(async (id, sessionId) => {
    let failures = 0;
    while (runId.current === id) {
      let blob;
      try {
        blob = await cameraRef.current.captureFrame();
      } catch (err) {
        dispatch({ type: 'error', error: { message: err.message || 'Camera unavailable.', camera: true } });
        return;
      }
      try {
        const response = await submitLivenessFrame(sessionId, blob);
        if (runId.current !== id) return;
        failures = 0;
        const terminal = isTerminal(response);
        dispatch({ type: 'frame', response, terminal });
        if (terminal) return;
        if (response.handoff_remaining_seconds > 0) {
          await sleep(response.handoff_remaining_seconds * 1000);
          if (runId.current !== id) return;
        }
      } catch (err) {
        if (runId.current !== id) return;
        const described = describeError(err, { 404: 'Vault session not found.' });
        if (described.status === 404) {
          return dispatch({ type: 'ended', ended: 'DENIED', reason: 'Vault session not found' });
        }
        failures += 1;
        if (!described.status || failures >= MAX_CONSECUTIVE_FAILURES) {
          return dispatch({ type: 'error', error: described });
        }
      }
      await new Promise((resolve) => setTimeout(resolve, FRAME_INTERVAL_MS));
    }
    return undefined;
  }, []);

  const start = useCallback(async () => {
    cancelLoop();
    const id = runId.current;
    dispatch({ type: 'starting' });
    try {
      const session = await startLivenessSession();
      if (runId.current !== id) return;
      dispatch({ type: 'session', session, challenge: session.challenge });
      loop(id, session.session_id);
    } catch (err) {
      if (runId.current === id) dispatch({ type: 'error', error: describeError(err) });
    }
  }, [cancelLoop, loop]);

  const cancel = useCallback(() => {
    cancelLoop();
    dispatch({ type: 'ended', ended: 'CANCELLED' });
  }, [cancelLoop]);

  const reset = useCallback(() => { cancelLoop(); dispatch({ type: 'reset' }); }, [cancelLoop]);

  useEffect(() => {
    if (!state.expiresAt || state.phase === 'done' || state.phase === 'idle') return undefined;
    const timer = window.setInterval(() => dispatch({ type: 'tick', now: Date.now() }), 250);
    return () => window.clearInterval(timer);
  }, [state.expiresAt, state.phase]);

  const remainingSeconds = state.expiresAt
    ? Math.max(0, Math.ceil((Date.parse(state.expiresAt) - state.now) / 1000))
    : null;
  const handoffRemaining = state.handoffUntil
    ? Math.max(0, Math.ceil((state.handoffUntil - state.now) / 1000))
    : 0;
  return { ...state, remainingSeconds, handoffRemaining, start, reset };
}
