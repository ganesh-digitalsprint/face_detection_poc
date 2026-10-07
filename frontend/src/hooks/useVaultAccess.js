import { useCallback, useEffect, useReducer, useRef } from 'react';
import { startLivenessSession, submitLivenessFrame } from '../api/vault.js';
import { describeError } from '../utils/errors.js';

// Keep requests sequential, but resume capture promptly after each response.
// This avoids overlapping uploads while providing more challenge samples.
const FRAME_INTERVAL_MS = 50;
const MAX_CONSECUTIVE_FAILURES = 3;
const MAX_UNKNOWN_IDENTITY_RETRIES = 3;
const PENDING = 'LIVENESS_PENDING';
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const INITIAL = {
  phase: 'idle', // idle | starting | liveness | done | error
  challenge: null,
  liveness: null, // last LivenessDecision from the backend
  result: null, // last full VaultAuthenticationResponse
  error: null,
};

function reducer(state, action) {
  switch (action.type) {
    case 'starting':
      return { ...INITIAL, phase: 'starting' };
    case 'session':
      return { ...state, phase: 'liveness', challenge: action.challenge };
    case 'frame': {
      const { response } = action;
      return {
        ...state,
        phase: action.terminal ? 'done' : 'liveness',
        challenge: response.liveness.challenge,
        liveness: response.liveness,
        result: response,
      };
    }
    case 'expired':
      return { ...state, phase: 'done', result: null, liveness: { ...(state.liveness ?? {}), passed: false, status: 'EXPIRED', reason: 'Liveness session expired' } };
    case 'error':
      return { ...state, phase: 'error', error: action.error };
    case 'reset':
      return INITIAL;
    default:
      return state;
  }
}

// Verification ends once liveness fails/expires, or the backend returns a final decision.
const isTerminal = (response) =>
  ['FAILED', 'EXPIRED'].includes(response.liveness.status) ||
  ![PENDING, 'LOOK_AT_CAMERA', 'UNKNOWN_EMPLOYEE'].includes(response.reason);

/**
 * Drives one vault verification attempt: start a backend liveness session, then feed it
 * camera frames until the backend reports a final decision. All decisions come from the backend.
 */
export default function useVaultAccess(camera) {
  const [state, dispatch] = useReducer(reducer, INITIAL);
  const runId = useRef(0);
  const cameraRef = useRef(camera);
  cameraRef.current = camera;

  const cancel = useCallback(() => { runId.current += 1; }, []);

  const loop = useCallback(async (id, sessionId) => {
    let failures = 0;
    let unknownIdentityRetries = 0;
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
        const retryUnknownIdentity =
          response.reason === 'UNKNOWN_EMPLOYEE' &&
          unknownIdentityRetries < MAX_UNKNOWN_IDENTITY_RETRIES;
        if (retryUnknownIdentity) unknownIdentityRetries += 1;
        const terminal = retryUnknownIdentity ? false : isTerminal(response);
        dispatch({ type: 'frame', response, terminal });
        if (terminal) return;
      } catch (err) {
        if (runId.current !== id) return;
        const described = describeError(err, { 404: 'Liveness session not found.' });
        if (described.status === 404) return dispatch({ type: 'expired' });
        failures += 1;
        if (!described.status || failures >= MAX_CONSECUTIVE_FAILURES) {
          return dispatch({ type: 'error', error: described });
        }
      }
      await sleep(FRAME_INTERVAL_MS);
    }
    return undefined;
  }, []);

  const start = useCallback(async () => {
    cancel();
    const id = runId.current;
    dispatch({ type: 'starting' });
    try {
      const session = await startLivenessSession();
      if (runId.current !== id) return;
      dispatch({ type: 'session', challenge: session.challenge });
      loop(id, session.session_id);
    } catch (err) {
      if (runId.current === id) dispatch({ type: 'error', error: describeError(err) });
    }
  }, [cancel, loop]);

  const reset = useCallback(() => { cancel(); dispatch({ type: 'reset' }); }, [cancel]);

  useEffect(() => cancel, [cancel]);

  return { ...state, start, reset };
}
