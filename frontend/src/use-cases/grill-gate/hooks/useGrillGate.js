import { useCallback, useEffect, useRef, useState } from 'react';
import { describeError } from '../../../utils/errors.js';
import {
  listAssignmentZones, listGrillGateAssignments, listGrillGateCameras, listGrillGateLocations,
  listGrillGateWorkers, listGrillGateZoneTypes,
} from '../api/grillGate.js';
import { workerForAssignment, workerPollDelay } from '../grillGateModel.js';

/** Active Grill Gate assignments joined with their registry camera and location. */
export function useGrillGateRegistry() {
  const [state, setState] = useState({ items: [], zoneTypes: [], loading: true, error: '' });
  const requestRef = useRef(0);

  const reload = useCallback(async () => {
    const request = ++requestRef.current;
    setState((current) => ({ ...current, loading: true, error: '' }));
    try {
      const [assignments, cameras, locations, zoneTypes] = await Promise.all([
        listGrillGateAssignments(), listGrillGateCameras(), listGrillGateLocations(), listGrillGateZoneTypes(),
      ]);
      if (request !== requestRef.current) return;
      const cameraById = new Map(cameras.map((camera) => [camera.id, camera]));
      const locationById = new Map(locations.map((location) => [location.id, location]));
      const items = assignments.map((assignment) => {
        const camera = cameraById.get(assignment.camera_id) ?? null;
        return { assignment, camera, location: camera ? locationById.get(camera.location_id) ?? null : null };
      });
      setState({ items, zoneTypes, loading: false, error: '' });
    } catch (error) {
      if (request === requestRef.current) setState((current) => ({ ...current, loading: false, error: describeError(error).message }));
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  /** Replace one assignment with the server's response (e.g. after a calibration PATCH). */
  const replaceAssignment = useCallback((updated) => {
    setState((current) => ({
      ...current,
      items: current.items.map((item) => (item.assignment.id === updated.id ? { ...item, assignment: updated } : item)),
    }));
  }, []);

  return { ...state, reload, replaceAssignment };
}

/**
 * Worker health from GET /grill-gate/workers. There is no push channel for Grill Gate, so this polls with a
 * bounded, state-dependent delay, pauses while the tab is hidden, and aborts in-flight requests on unmount.
 */
export function useGrillGateWorkers(assignmentId) {
  const [workers, setWorkers] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState('');
  const [checkedAt, setCheckedAt] = useState(null);
  const timerRef = useRef(null);
  const abortRef = useRef(null);
  const assignmentRef = useRef(assignmentId);
  assignmentRef.current = assignmentId;

  const refresh = useCallback(async () => {
    window.clearTimeout(timerRef.current);
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    let next = [];
    try {
      next = await listGrillGateWorkers(controller.signal);
      if (controller.signal.aborted) return;
      setWorkers(next); setError(''); setLoaded(true); setCheckedAt(new Date());
    } catch (exception) {
      if (controller.signal.aborted || exception?.code === 'ERR_CANCELED') return;
      setError(describeError(exception).message); setLoaded(true);
    }
    if (document.visibilityState === 'visible') {
      timerRef.current = window.setTimeout(refresh, workerPollDelay(workerForAssignment(next, assignmentRef.current)));
    }
  }, []);

  useEffect(() => {
    refresh();
    const onVisibility = () => { if (document.visibilityState === 'visible') refresh(); else window.clearTimeout(timerRef.current); };
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      window.clearTimeout(timerRef.current);
      abortRef.current?.abort();
    };
  }, [refresh]);

  // A new selection may need a faster cadence; restart the chain immediately.
  useEffect(() => { if (assignmentId) refresh(); }, [assignmentId, refresh]);

  return { workers, loaded, error, checkedAt, refresh };
}

/** Zones for one assignment; responses for a previously selected assignment are discarded. */
export function useAssignmentZones(assignmentId) {
  const [state, setState] = useState({ zones: [], loading: false, error: '' });
  const requestRef = useRef(0);

  const reload = useCallback(async () => {
    const request = ++requestRef.current;
    if (!assignmentId) { setState({ zones: [], loading: false, error: '' }); return; }
    setState((current) => ({ ...current, loading: true, error: '' }));
    try {
      const zones = await listAssignmentZones(assignmentId);
      if (request === requestRef.current) setState({ zones, loading: false, error: '' });
      return zones;
    } catch (error) {
      if (request === requestRef.current) setState({ zones: [], loading: false, error: describeError(error).message });
      return null;
    }
  }, [assignmentId]);

  useEffect(() => { reload(); }, [reload]);
  return { ...state, reload };
}
