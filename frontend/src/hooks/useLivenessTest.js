import { useCallback, useEffect, useReducer, useRef } from 'react';
import {
  analyzeTestFrame, endTestSession, resetTestBaseline, setTestChallenge, startTestSession,
} from '../api/livenessTest.js';
import { describeError } from '../utils/errors.js';

// Sequential loop: the next frame is captured only after the previous response arrives,
// so frames are never sent faster than the backend answers.
const JPEG_QUALITY = 0.8;
const MAX_CONSECUTIVE_FAILURES = 3;
const RETRY_DELAY_MS = 300;
const HISTORY_SIZE = 60;
const FPS_WINDOW = 10;
const COPY_RESET_MS = 2000;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export const DETECTORS = Object.freeze({ MEDIAPIPE: 'mediapipe', DEEPFACE: 'deepface', BOTH: 'both' });

const INITIAL = {
  phase: 'idle', // idle | starting | running | frozen | error
  sessionId: null,
  detector: DETECTORS.MEDIAPIPE,
  challenge: null,
  analysis: null,
  thresholds: null,
  history: [], // [{ yaw, pitch }] newest last
  stats: { fps: 0, lastElapsed: null, frames: 0, dropped: 0 },
  frozenFrame: null, // object URL of the frame on screen while frozen (memory only)
  copyStatus: null, // null | copied | failed
  error: null,
};

/** Result of the selected detector, or the first one returned (compare mode). */
export function primaryResult(analysis, detector) {
  const results = analysis?.results ?? [];
  return results.find((r) => r.detector === detector) ?? results.find((r) => r.visible) ?? results[0] ?? null;
}

function appendHistory(history, analysis, detector) {
  const pose = primaryResult(analysis, detector)?.pose;
  if (!pose || pose.yaw == null || pose.pitch == null) return history;
  return [...history, { yaw: pose.yaw, pitch: pose.pitch }].slice(-HISTORY_SIZE);
}

function reducer(state, action) {
  switch (action.type) {
    case 'starting':
      return { ...state, phase: 'starting', error: null };
    case 'session':
      return { ...state, phase: 'running', sessionId: action.sessionId, error: null };
    case 'frame': {
      const { analysis, fps } = action;
      const elapsed = Math.max(0, ...(analysis.results ?? []).map((r) => r.elapsed_ms ?? 0));
      return {
        ...state,
        analysis,
        thresholds: analysis.thresholds ?? state.thresholds,
        history: appendHistory(state.history, analysis, state.detector),
        stats: { ...state.stats, fps, lastElapsed: elapsed, frames: state.stats.frames + 1 },
      };
    }
    case 'dropped':
      return { ...state, stats: { ...state.stats, dropped: state.stats.dropped + 1 } };
    case 'freeze':
      return { ...state, phase: 'frozen', frozenFrame: action.url };
    case 'unfreeze':
      return { ...state, phase: 'running', frozenFrame: null };
    case 'detector':
      return { ...state, detector: action.detector, history: [] };
    case 'challenge':
      return { ...state, challenge: action.challenge };
    case 'baseline':
      return { ...state, history: [] };
    case 'thresholds':
      return state.thresholds ? state : { ...state, thresholds: action.thresholds };
    case 'copy':
      return { ...state, copyStatus: action.status };
    case 'error':
      return { ...state, phase: 'error', error: action.error, frozenFrame: null };
    case 'stopped':
      return {
        ...INITIAL, detector: state.detector, challenge: state.challenge, thresholds: state.thresholds,
      };
    default:
      return state;
  }
}

function fpsFrom(timestamps) {
  if (timestamps.length < 2) return 0;
  const seconds = (timestamps[timestamps.length - 1] - timestamps[0]) / 1000;
  return seconds > 0 ? (timestamps.length - 1) / seconds : 0;
}

/**
 * Drives one liveness *test* session (never a vault session) from any camera exposing captureFrame().
 * @param {{ captureFrame: (opts?: { quality?: number }) => Promise<Blob> }} camera
 * @param {{ initialThresholds?: object|null }} [options]
 */
export default function useLivenessTest(camera, { initialThresholds = null } = {}) {
  const [state, dispatch] = useReducer(reducer, INITIAL);
  const runId = useRef(0);
  const cameraRef = useRef(camera);
  cameraRef.current = camera;
  const sessionRef = useRef(null);
  const optionsRef = useRef({ detector: state.detector, challenge: state.challenge });
  optionsRef.current = { detector: state.detector, challenge: state.challenge };
  const lastBlobRef = useRef(null);
  const frozenUrlRef = useRef(null);
  const copyTimer = useRef(null);

  useEffect(() => {
    if (initialThresholds) dispatch({ type: 'thresholds', thresholds: initialThresholds });
  }, [initialThresholds]);

  const cancelLoop = useCallback(() => { runId.current += 1; }, []);

  const releaseFrozen = useCallback(() => {
    if (frozenUrlRef.current) URL.revokeObjectURL(frozenUrlRef.current);
    frozenUrlRef.current = null;
  }, []);

  // Best effort: a failed DELETE must never surface as an error.
  const endSession = useCallback(() => {
    const sessionId = sessionRef.current;
    sessionRef.current = null;
    if (sessionId) endTestSession(sessionId).catch(() => {});
  }, []);

  const openSession = useCallback(async () => {
    const created = await startTestSession();
    sessionRef.current = created.session_id;
    return created.session_id;
  }, []);

  const loop = useCallback(async (id) => {
    let failures = 0;
    const timestamps = [];
    const fail = async (error) => {
      failures += 1;
      dispatch({ type: 'dropped' });
      if (failures >= MAX_CONSECUTIVE_FAILURES) {
        dispatch({ type: 'error', error });
        return true;
      }
      await sleep(RETRY_DELAY_MS);
      return false;
    };

    while (runId.current === id) {
      let blob;
      try {
        blob = await cameraRef.current.captureFrame({ quality: JPEG_QUALITY });
      } catch (err) {
        if (runId.current !== id) return;
        if (await fail({ message: err.message || 'Camera unavailable.', camera: true })) return;
        continue;
      }
      if (runId.current !== id) return;
      lastBlobRef.current = blob;
      try {
        const analysis = await analyzeTestFrame(sessionRef.current, blob, optionsRef.current);
        if (runId.current !== id) return;
        failures = 0;
        timestamps.push(performance.now());
        if (timestamps.length > FPS_WINDOW) timestamps.shift();
        dispatch({ type: 'frame', analysis, fps: fpsFrom(timestamps) });
      } catch (err) {
        if (runId.current !== id) return;
        const described = describeError(err, { 404: 'Test session not found.' });
        if (described.status === 404) {
          // The backend dropped the session (restart, timeout): open a fresh one and carry on.
          try {
            const sessionId = await openSession();
            if (runId.current !== id) return;
            dispatch({ type: 'session', sessionId });
            continue;
          } catch (startErr) {
            if (runId.current !== id) return;
            if (await fail(describeError(startErr))) return;
            continue;
          }
        }
        if (await fail(described)) return;
      }
    }
  }, [openSession]);

  const start = useCallback(async () => {
    cancelLoop();
    releaseFrozen();
    endSession();
    const id = runId.current;
    dispatch({ type: 'starting' });
    try {
      const sessionId = await openSession();
      if (runId.current !== id) {
        endSession();
        return;
      }
      dispatch({ type: 'session', sessionId });
      if (optionsRef.current.challenge) {
        await setTestChallenge(sessionId, optionsRef.current.challenge).catch(() => {});
      }
      loop(id);
    } catch (err) {
      if (runId.current === id) dispatch({ type: 'error', error: describeError(err) });
    }
  }, [cancelLoop, endSession, loop, openSession, releaseFrozen]);

  const stop = useCallback(() => {
    cancelLoop();
    releaseFrozen();
    endSession();
    lastBlobRef.current = null;
    dispatch({ type: 'stopped' });
  }, [cancelLoop, endSession, releaseFrozen]);

  const freeze = useCallback(() => {
    if (!lastBlobRef.current) return;
    cancelLoop();
    releaseFrozen();
    frozenUrlRef.current = URL.createObjectURL(lastBlobRef.current);
    dispatch({ type: 'freeze', url: frozenUrlRef.current });
  }, [cancelLoop, releaseFrozen]);

  const unfreeze = useCallback(() => {
    if (!sessionRef.current) return;
    releaseFrozen();
    cancelLoop();
    const id = runId.current;
    dispatch({ type: 'unfreeze' });
    loop(id);
  }, [cancelLoop, loop, releaseFrozen]);

  const resetBaseline = useCallback(async () => {
    dispatch({ type: 'baseline' });
    if (!sessionRef.current) return;
    try {
      await resetTestBaseline(sessionRef.current);
    } catch {
      dispatch({ type: 'dropped' });
    }
  }, []);

  const changeDetector = useCallback((detector) => dispatch({ type: 'detector', detector }), []);

  const changeChallenge = useCallback(async (challenge) => {
    dispatch({ type: 'challenge', challenge });
    if (!sessionRef.current) return;
    try {
      await setTestChallenge(sessionRef.current, challenge);
    } catch {
      dispatch({ type: 'dropped' });
    }
  }, []);

  const copyAnalysisJson = useCallback(async () => {
    window.clearTimeout(copyTimer.current);
    try {
      await navigator.clipboard.writeText(JSON.stringify(state.analysis, null, 2));
      dispatch({ type: 'copy', status: 'copied' });
    } catch {
      dispatch({ type: 'copy', status: 'failed' });
    }
    copyTimer.current = window.setTimeout(() => dispatch({ type: 'copy', status: null }), COPY_RESET_MS);
  }, [state.analysis]);

  // Leaving the page always ends the test session.
  useEffect(() => () => {
    cancelLoop();
    releaseFrozen();
    endSession();
    window.clearTimeout(copyTimer.current);
  }, [cancelLoop, endSession, releaseFrozen]);

  return {
    ...state,
    start, stop, freeze, unfreeze, resetBaseline, changeDetector, changeChallenge, copyAnalysisJson,
  };
}
