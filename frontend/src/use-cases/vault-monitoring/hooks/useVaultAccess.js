import { useCallback, useEffect, useReducer, useRef } from 'react';
import { getVaultAuthenticationConfig, startLivenessSession, submitLivenessFrame } from '../api/vault.js';
import { describeError } from '../../../utils/errors.js';
import { BACKEND_TIMEOUT_STATUS } from '../utils/dualControl.js';

// Keep requests sequential, but resume capture promptly after each response.
// This avoids overlapping uploads while providing more challenge samples.
const FRAME_INTERVAL_MS = 50;
const MAX_CONSECUTIVE_FAILURES = 3;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Backend statuses after which the session can never progress again.
const TERMINAL_STATUSES = ['ACCESS_GRANTED', BACKEND_TIMEOUT_STATUS, 'EXPIRED'];
const ACTIVE_ROOM_STATES = new Set(['ENTRY_BUFFER', 'ACTIVE', 'EXPIRED_OPEN']);

const INITIAL = {
  phase: 'idle', // idle | starting | liveness | done | error
  ended: null, // null | ACCESS_GRANTED | SESSION_EXPIRED | DENIED | CANCELLED
  endReason: null,
  challenge: null,
  liveness: null, // last LivenessDecision from the backend
  result: null, // last full VaultAuthenticationResponse
  status: null,
  authenticatedCount: 0,
  requiredCount: null,
  testMode: false,
  config: null,
  configError: null,
  configLoading: true,
  selectedRequiredPersons: null,
  custodians: [], // backend `authenticated_custodians`, ordered by slot
  expiresAt: null, // backend-provided ISO timestamp; the only basis for the countdown
  handoffUntil: null,
  handoffPending: false,
  now: Date.now(),
  error: null,
  roomConflict: null,
};

// Only the backend can finish a session with a decision; everything else keeps the session open.
function frameOutcome(response) {
  if (!TERMINAL_STATUSES.includes(response.status)) return null;
  if (response.status !== 'ACCESS_GRANTED') return 'SESSION_EXPIRED';
  // The UI never infers a grant: a terminal status without `access_granted` is a denial.
  return response.access_granted === true ? 'ACCESS_GRANTED' : 'DENIED';
}

function reducer(state, action) {
  switch (action.type) {
    case 'configLoading':
      return { ...state, configLoading: true, configError: null };
    case 'starting':
      return {
        ...state,
        phase: 'starting', ended: null, endReason: null, challenge: null,
        liveness: null, result: null, status: null, authenticatedCount: 0,
        requiredCount: state.selectedRequiredPersons ?? state.config?.required_persons ?? null,
        testMode: (state.selectedRequiredPersons ?? state.config?.required_persons) === 1,
        custodians: [], expiresAt: null, handoffUntil: null, handoffPending: false,
        now: Date.now(), error: null, roomConflict: null,
      };
    case 'config':
      return {
        ...state, config: action.config, configError: null, configLoading: false,
        requiredCount: action.config.required_persons,
        selectedRequiredPersons: action.config.required_persons,
        testMode: action.config.test_mode,
      };
    case 'configError':
      return { ...state, configError: action.error, configLoading: false };
    case 'selectRequiredPersons':
      return {
        ...state,
        selectedRequiredPersons: action.value,
        requiredCount: action.value,
        testMode: action.value < 2,
      };
    case 'session':
      return {
        ...state, phase: 'liveness', challenge: action.challenge,
        status: action.session.status, authenticatedCount: 0,
        requiredCount: action.session.required_persons,
        testMode: action.session.test_mode,
        custodians: [],
        expiresAt: action.session.expires_at,
        handoffUntil: null,
        handoffPending: false,
        now: Date.now(),
      };
    case 'frame': {
      const { response, ended } = action;
      const now = Date.now();
      return {
        ...state,
        phase: ended ? 'done' : 'liveness',
        ended,
        challenge: response.next_challenge ?? response.liveness.challenge,
        liveness: response.liveness,
        result: response,
        status: response.status,
        authenticatedCount: response.authenticated_count ?? 0,
        requiredCount: response.required_count ?? state.requiredCount,
        testMode: response.test_mode ?? state.testMode,
        custodians: response.authenticated_custodians ?? state.custodians,
        handoffUntil: response.handoff_remaining_seconds > 0
          ? now + response.handoff_remaining_seconds * 1000
          : null,
        handoffPending: !ended && (response.handoff_remaining_seconds > 0
          || (state.handoffPending && response.reason !== 'NEXT_PERSON_READY')),
        now,
      };
    }
    case 'ended':
      return {
        ...state, phase: 'done', ended: action.ended, endReason: action.reason ?? null,
        handoffUntil: null, handoffPending: false,
      };
    case 'error':
      return { ...state, phase: 'error', error: action.error, handoffUntil: null, handoffPending: false };
    case 'roomBlocked':
      return {
        ...state, phase: 'idle', ended: null, endReason: null, challenge: null,
        liveness: null, result: null, status: null, error: null,
        handoffUntil: null, handoffPending: false, roomConflict: action.info,
      };
    case 'roomConflictCleared':
      return { ...state, roomConflict: null };
    case 'reset':
      return {
        ...INITIAL,
        config: state.config,
        configError: state.configError,
        configLoading: state.configLoading,
        selectedRequiredPersons: state.config?.required_persons ?? null,
        requiredCount: state.config?.required_persons ?? null,
        testMode: state.config?.test_mode ?? false,
        now: Date.now(),
      };
    case 'tick':
      return { ...state, now: action.now };
    default:
      return state;
  }
}

/**
 * Starts one dual-control session and feeds frames until the backend grants access or expires it.
 */
export default function useVaultAccess(camera, paused = false, room = {}) {
  const [state, dispatch] = useReducer(reducer, INITIAL);
  const runId = useRef(0);
  const cameraRef = useRef(camera);
  cameraRef.current = camera;
  const pausedRef = useRef(paused);
  pausedRef.current = paused;
  const roomStateRef = useRef(room.roomState);
  roomStateRef.current = room.roomState;
  const roomConflictRef = useRef(state.roomConflict);
  roomConflictRef.current = state.roomConflict;
  const roomConflictObservedRef = useRef(null);
  const refreshRoomStateRef = useRef(room.refreshState);
  refreshRoomStateRef.current = room.refreshState;

  const loadConfig = useCallback(async () => {
    dispatch({ type: 'configLoading' });
    try {
      dispatch({ type: 'config', config: await getVaultAuthenticationConfig() });
    } catch (err) {
      dispatch({ type: 'configError', error: describeError(err) });
    }
  }, []);

  useEffect(() => { loadConfig(); }, [loadConfig]);

  const cancelLoop = useCallback(() => { runId.current += 1; }, []);

  const blockForRoomSession = useCallback((details = {}) => {
    const current = roomStateRef.current;
    roomConflictObservedRef.current = {
      state: current?.state ?? null,
      sessionId: current?.session_id ?? null,
      activeSeen: false,
    };
    const info = {
      state: details.vault_room_state ?? details.state ?? current?.state
        ?? state.config?.vault_room_state ?? 'ACTIVE',
      remaining_seconds: details.remaining_seconds ?? current?.remaining_seconds
        ?? state.config?.vault_room_remaining_seconds ?? null,
      entry_buffer_remaining_seconds: details.entry_buffer_remaining_seconds
        ?? current?.entry_buffer_remaining_seconds ?? 0,
    };
    cancelLoop();
    dispatch({ type: 'roomBlocked', info });
    const refresh = refreshRoomStateRef.current;
    if (refresh) {
      refresh().then((next) => {
        if (ACTIVE_ROOM_STATES.has(next?.state)) {
          dispatch({ type: 'roomBlocked', info: next });
        } else {
          dispatch({ type: 'roomConflictCleared' });
        }
      }).catch(() => {});
    }
  }, [cancelLoop, state.config]);

  useEffect(() => {
    const current = room.roomState;
    const observed = roomConflictObservedRef.current;
    if (!current || !observed || !roomConflictRef.current) return;
    if (ACTIVE_ROOM_STATES.has(current.state)) {
      observed.activeSeen = true;
      return;
    }
    if (observed.activeSeen || current.state !== observed.state || current.session_id !== observed.sessionId) {
      roomConflictObservedRef.current = null;
      dispatch({ type: 'roomConflictCleared' });
    }
  }, [room.roomState?.state, room.roomState?.session_id]);

  const loop = useCallback(async (id, sessionId) => {
    let failures = 0;
    while (runId.current === id) {
      // The room view reuses this camera; pause entrance submissions without cancelling the session.
      if (pausedRef.current) {
        await sleep(FRAME_INTERVAL_MS);
        continue;
      }
      let blob;
      try {
        blob = await cameraRef.current.captureFrame();
      } catch (err) {
        if (runId.current !== id) return;
        dispatch({ type: 'error', error: { message: err.message || 'Camera unavailable.', camera: true } });
        return;
      }
      // Never send a frame captured for a session that was stopped or restarted meanwhile.
      if (runId.current !== id) return;
      // The user may have switched views while the frame was being encoded.
      if (pausedRef.current) continue;
      try {
        const response = await submitLivenessFrame(sessionId, blob);
        if (runId.current !== id) return;
        failures = 0;
        if (response.reason === 'VAULT_ROOM_SESSION_ACTIVE') {
          blockForRoomSession();
          return;
        }
        const ended = frameOutcome(response);
        dispatch({ type: 'frame', response, ended });
        if (ended) return;
        // No frames are captured or sent while the custodians swap places.
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
      await sleep(FRAME_INTERVAL_MS);
    }
    return undefined;
  }, [blockForRoomSession]);

  const start = useCallback(async () => {
    const currentRoom = roomStateRef.current;
    const blockedState = ACTIVE_ROOM_STATES.has(currentRoom?.state);
    const configBlocked = !currentRoom && state.config?.new_access_allowed === false;
    if (blockedState || configBlocked || state.roomConflict) {
      blockForRoomSession(blockedState ? currentRoom : state.roomConflict ?? {
        vault_room_state: state.config?.vault_room_state,
        remaining_seconds: state.config?.vault_room_remaining_seconds,
      });
      return;
    }
    cancelLoop();
    const id = runId.current;
    dispatch({ type: 'starting' });
    try {
      if (!state.config) throw new Error('Vault configuration is unavailable. Retry loading configuration.');
      const requested = state.config.allow_mode_select ? state.selectedRequiredPersons : null;
      const session = await startLivenessSession(requested);
      if (runId.current !== id) return;
      if (!session.session_ref) {
        throw new Error('The server did not return a vault session reference. Restart the backend after applying its database migrations.');
      }
      dispatch({ type: 'session', session, challenge: session.challenge });
      loop(id, session.session_ref);
    } catch (err) {
      if (runId.current === id && err?.response?.status === 409
          && err?.response?.data?.code === 'VAULT_ROOM_SESSION_ACTIVE') {
        blockForRoomSession(err.response.data.details ?? {});
        return;
      }
      if (runId.current === id) dispatch({ type: 'error', error: describeError(err) });
    }
  }, [blockForRoomSession, cancelLoop, loop, state.config, state.roomConflict, state.selectedRequiredPersons]);

  const cancel = useCallback(() => {
    cancelLoop();
    dispatch({ type: 'ended', ended: 'CANCELLED' });
  }, [cancelLoop]);

  const reset = useCallback(() => { cancelLoop(); dispatch({ type: 'reset' }); }, [cancelLoop]);

  // Stop any in-flight loop when the page unmounts.
  useEffect(() => cancelLoop, [cancelLoop]);

  useEffect(() => {
    if (!state.expiresAt || state.phase === 'done' || state.phase === 'idle' || state.phase === 'error') {
      return undefined;
    }
    const timer = window.setInterval(() => dispatch({ type: 'tick', now: Date.now() }), 250);
    return () => window.clearInterval(timer);
  }, [state.expiresAt, state.phase]);

  const remainingSeconds = state.expiresAt
    ? Math.max(0, Math.ceil((Date.parse(state.expiresAt) - state.now) / 1000))
    : null;
  const handoffRemaining = state.handoffUntil
    ? Math.max(0, Math.ceil((state.handoffUntil - state.now) / 1000))
    : 0;
  const selectRequiredPersons = useCallback((value) => {
    dispatch({ type: 'selectRequiredPersons', value });
  }, []);

  const currentRoom = room.roomState;
  const roomIsActive = ACTIVE_ROOM_STATES.has(currentRoom?.state);
  const configBlocksRoom = !currentRoom && state.config?.new_access_allowed === false;
  const roomBlockInfo = roomIsActive ? currentRoom
    : state.roomConflict ?? (configBlocksRoom ? {
      state: state.config?.vault_room_state,
      remaining_seconds: state.config?.vault_room_remaining_seconds,
    } : null);
  const roomBlocked = roomIsActive || configBlocksRoom || Boolean(state.roomConflict);
  return { ...state, remainingSeconds, handoffRemaining, start, cancel, reset, loadConfig, selectRequiredPersons,
    roomBlocked, roomBlockInfo };
}
