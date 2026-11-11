import { useCallback, useEffect, useRef, useState } from 'react';
import { useDispatch } from 'react-redux';
import { describeError } from '../../../utils/errors.js';
import { getGrillGateVideoJob, getGrillGateVideoResults, getVideoJobConfig, uploadGrillGateVideo } from '../api/grillGate.js';
import { createVideoJobPoller } from '../videoJobPoller.js';
import { updateGateProgress } from '../../../store/slices/gateMonitoringSlice.js';

const api = {
  getJob: getGrillGateVideoJob,
  getConfig: getVideoJobConfig,
  getResults: getGrillGateVideoResults,
  describeError: (error) => describeError(error).message,
};
const idle = (jobId) => ({ jobId, job: null, monitoring: null, events: [], transitions: [], alerts: [], alertsAvailable: true, fps: null, loading: Boolean(jobId), error: '', notFound: false });

/** Results of one selected video job. A null id stops polling and clears the data, so nothing leaks to Live Camera. */
export function useVideoJob(jobId) {
  const dispatch = useDispatch();
  const [state, setState] = useState(() => idle(jobId));
  const pollerRef = useRef(null);

  useEffect(() => {
    setState(idle(jobId));
    if (!jobId) return undefined;
    const sessionId = `video:${jobId}`;
    const poller = createVideoJobPoller({
      jobId, api,
      onUpdate: (next) => {
        setState(next);
        dispatch(updateGateProgress({ sessionId, progress: next.monitoring?.progress, observedAt: Date.now() }));
      },
      isVisible: () => document.visibilityState === 'visible',
    });
    pollerRef.current = poller;
    poller.start();
    const onVisibility = () => { if (document.visibilityState === 'visible') poller.poke(); };
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      poller.stop();
      if (pollerRef.current === poller) pollerRef.current = null;
    };
  }, [jobId, dispatch]);

  const refresh = useCallback(() => pollerRef.current?.poke(), []);
  // Until the effect above runs for a new id, the previous job's data must not render under it.
  return { ...(state.jobId === jobId ? state : idle(jobId)), refresh };
}

/** One upload at a time; lives on the page so it survives switching tabs, and aborts when the page unmounts. */
export function useVideoUpload() {
  const [state, setState] = useState({ phase: 'idle', progress: null, error: '', fileKey: null });
  const controllerRef = useRef(null);
  useEffect(() => () => controllerRef.current?.abort(), []);

  const upload = useCallback(async (file, configurationOrAssignmentId, fileKey) => {
    if (controllerRef.current) return null;
    const controller = new AbortController();
    controllerRef.current = controller;
    setState({ phase: 'uploading', progress: 0, error: '', fileKey });
    try {
      const saved = await uploadGrillGateVideo(file, configurationOrAssignmentId, {
        signal: controller.signal,
        onProgress: (progress) => setState((current) => ({ ...current, progress })),
      });
      setState({ phase: 'saved', progress: 1, error: '', fileKey });
      return saved;
    } catch (exception) {
      if (!controller.signal.aborted) setState({ phase: 'failed', progress: null, error: describeError(exception).message, fileKey });
      return null;
    } finally {
      controllerRef.current = null;
    }
  }, []);

  return { ...state, upload };
}
