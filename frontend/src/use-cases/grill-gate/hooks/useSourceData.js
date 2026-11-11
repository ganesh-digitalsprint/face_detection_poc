import { useCallback, useEffect, useRef, useState } from 'react';
import { useDispatch } from 'react-redux';
import { describeError } from '../../../utils/errors.js';
import {
  getLiveActiveAlerts, getLiveCrossings, getLiveGateState, getLiveMeshEvents, getLiveMeshStatus, listGrillGateVideoJobs,
} from '../api/grillGate.js';
import { analysedFps } from '../liveMonitoringModel.js';
import { updateCrossingCounts, updateGateProgress } from '../../../store/slices/gateMonitoringSlice.js';

const LIVE_POLL_MS = 3000;
const emptyLive = (assignmentId) => ({
  assignmentId, gate: null, crossings: [], crossingTotal: 0, entryCount: 0, exitCount: 0, mesh: null, meshEvents: [],
  alerts: [], alertsAvailable: true, alertsError: '', alertsLoading: Boolean(assignmentId),
  alertsRequestAttempted: false, fps: null, error: '', loaded: false, now: Date.now(),
});

/** One monitoring poll for the selected assignment; local alerts are always requested with the same assignment scope. */
export function fetchLiveMonitoringData(assignmentId, workerActive, signal) {
  if (!assignmentId) return Promise.resolve(null);
  return Promise.allSettled([
    // A detector only exists while a worker runs; asking otherwise is a guaranteed 404.
    workerActive ? getLiveGateState(assignmentId, signal) : null,
    getLiveCrossings(assignmentId, { limit: 25 }, signal),
    getLiveCrossings(assignmentId, { limit: 1, direction: 'OUTSIDE_TO_INSIDE' }, signal),
    getLiveCrossings(assignmentId, { limit: 1, direction: 'INSIDE_TO_OUTSIDE' }, signal),
    getLiveMeshStatus(assignmentId, signal),
    getLiveMeshEvents(assignmentId, { limit: 25 }, signal),
    getLiveActiveAlerts(assignmentId, { limit: 25 }, signal),
  ]);
}

/** Live-camera data for one assignment. One read cycle at a time; data never survives a change of assignment. */
export function useLiveMonitoring(assignmentId, workerActive) {
  const dispatch = useDispatch();
  const [state, setState] = useState(() => emptyLive(assignmentId));
  const runRef = useRef(null);
  const workerActiveRef = useRef(workerActive);
  workerActiveRef.current = workerActive;

  useEffect(() => {
    setState(emptyLive(assignmentId));
    if (!assignmentId) return undefined;
    let stopped = false;
    let timer = null;
    let running = false;
    let sample = null;
    const controller = new AbortController();
    const { signal } = controller;

    const run = async () => {
      if (stopped || running) return;
      running = true;
      window.clearTimeout(timer);
      setState((current) => current.assignmentId === assignmentId
        ? { ...current, alertsLoading: true }
        : current);
      const [gate, crossings, entries, exits, mesh, meshEvents, alerts] = await fetchLiveMonitoringData(
        assignmentId, workerActiveRef.current, signal);
      running = false;
      if (stopped) return;
      const at = Date.now();
      // gate-state can still be 404 while a detector starts or stops, which is not an error.
      const gateValue = gate.status === 'fulfilled' ? gate.value : null;
      dispatch(updateGateProgress({
        sessionId: `live:${assignmentId}`,
        progress: gateValue?.progress,
        observedAt: at,
      }));
      dispatch(updateCrossingCounts({ sessionId: `live:${assignmentId}`,
        entryCount: entries.status === 'fulfilled' ? entries.value.total : null,
        exitCount: exits.status === 'fulfilled' ? exits.value.total : null,
        observedAt: at, timebase: 'wall' }));
      const gateFailed = gate.status === 'rejected' && gate.reason?.response?.status !== 404;
      const failure = [gateFailed ? gate : null, crossings, mesh, meshEvents].find((item) => item?.status === 'rejected');
      if (alerts.status === 'rejected') {
        const error = describeError(alerts.reason);
        console.warn('Grill Gate local alerts request failed', {
          assignmentId, endpoint: `/api/v1/grill-gate/assignments/${assignmentId}/alerts/active`,
          status: error.status, message: error.message,
        });
      }
      setState((current) => ({
        ...current,
        gate: gateValue,
        crossings: crossings.status === 'fulfilled' ? crossings.value.items : current.crossings,
        crossingTotal: crossings.status === 'fulfilled' ? crossings.value.total : current.crossingTotal,
        entryCount: entries.status === 'fulfilled' ? entries.value.total : current.entryCount,
        exitCount: exits.status === 'fulfilled' ? exits.value.total : current.exitCount,
        mesh: mesh.status === 'fulfilled' ? mesh.value : current.mesh,
        meshEvents: meshEvents.status === 'fulfilled' ? meshEvents.value.items : current.meshEvents,
        alerts: alerts.status === 'fulfilled' ? alerts.value.items : current.alerts,
        alertsAvailable: alerts.status === 'fulfilled',
        alertsError: alerts.status === 'rejected' ? describeError(alerts.reason).message : '',
        alertsLoading: false,
        alertsRequestAttempted: true,
        fps: analysedFps(sample, gateValue, at) ?? (gateValue ? current.fps : null),
        error: failure ? describeError(failure.reason).message : '',
        loaded: true,
        now: at,
      }));
      sample = Number.isFinite(gateValue?.processed_frames) ? { frames: gateValue.processed_frames, at } : null;
      if (document.visibilityState === 'visible') timer = window.setTimeout(run, LIVE_POLL_MS);
    };
    runRef.current = run;
    run();
    const onVisibility = () => { if (document.visibilityState === 'visible') run(); };
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      controller.abort();
      document.removeEventListener('visibilitychange', onVisibility);
      runRef.current = null;
    };
  }, [assignmentId, dispatch]);

  const refresh = useCallback(() => runRef.current?.(), []);
  return { ...(state.assignmentId === assignmentId ? state : emptyLive(assignmentId)), refresh };
}

/** Saved videos for the job list; re-read when `refreshKey` changes (selection, status, delete). */
export function useVideoJobList(refreshKey) {
  const [state, setState] = useState({ jobs: [], loaded: false, error: '' });
  const requestRef = useRef(0);
  const reload = useCallback(async () => {
    const request = ++requestRef.current;
    try {
      const page = await listGrillGateVideoJobs();
      if (request === requestRef.current) setState({ jobs: page.items, loaded: true, error: '' });
      return page.items;
    } catch (exception) {
      if (request === requestRef.current) setState((current) => ({ ...current, loaded: true, error: describeError(exception).message }));
      return null;
    }
  }, []);
  useEffect(() => { reload(); }, [reload, refreshKey]);
  return { ...state, reload };
}

/**
 * A JPEG fetched through the authenticated client and shown as a blob URL, which is revoked when replaced or on
 * unmount. The current image stays up while the next loads, and a slow request is never overlapped: the newest
 * key waits and runs after it.
 */
export function useAuthorizedJpeg(load, key) {
  const [state, setState] = useState({ url: null, error: '', key: null });
  const loadRef = useRef(load);
  loadRef.current = load;
  const urlRef = useRef(null);
  const busyRef = useRef(false);
  const nextRef = useRef(null);
  const mountedRef = useRef(true);

  const fetchKey = useCallback(async (requested) => {
    if (busyRef.current) { nextRef.current = requested; return; }
    busyRef.current = true;
    nextRef.current = null;
    const loader = loadRef.current;
    try {
      const blob = await loader();
      if (!mountedRef.current) return;
      const url = URL.createObjectURL(blob);
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
      urlRef.current = url;
      setState({ url, error: '', key: requested });
    } catch (exception) {
      if (mountedRef.current) setState((current) => ({ ...current, error: describeError(exception).message, key: requested }));
    } finally {
      busyRef.current = false;
      const next = nextRef.current;
      if (mountedRef.current && next != null) fetchKey(next);
    }
  }, []);

  useEffect(() => {
    if (key == null) {
      nextRef.current = null;
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
      setState({ url: null, error: '', key: null });
      return;
    }
    fetchKey(key);
  }, [key, fetchKey]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    };
  }, []);

  return state;
}
