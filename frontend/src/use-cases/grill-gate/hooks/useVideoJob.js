import { processedVideoTimestamp, videoIsFinal } from '../videoTimerClock.js';
import { store } from '../../../store/index.js';
import { gateSession } from '../../../store/slices/gateMonitoringSlice.js';
import { videoMonitoring } from '../videoJobModel.js';
import { evaluateOpenTimer } from '../openTimerRuntime.js';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useDispatch } from 'react-redux';
import { describeError } from '../../../utils/errors.js';
import { clearPersistedGateMonitoring, persistor } from '../../../store/index.js';
import { getGrillGateVideoJob, getGrillGateVideoResults, getVideoJobConfig, uploadGrillGateVideo } from '../api/grillGate.js';
import { createVideoJobPoller } from '../videoJobPoller.js';
import { resetGateMonitoring, updateVideoTimerSample, updateCrossingCounts, updateGateProgress } from '../../../store/slices/gateMonitoringSlice.js';

const latestCrossingTime = (events, direction, currentSeconds) => {
  const times = events.filter((event) => event.direction === direction
    && Number.isFinite(event.video_time_seconds) && event.video_time_seconds >= 0
    && event.video_time_seconds <= currentSeconds).map((event) => event.video_time_seconds * 1000);
  return times.length ? Math.max(...times) : null;
};

const backgroundPollers = new Map();

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
  const [pollerGeneration, setPollerGeneration] = useState(0);
  const pollerRef = useRef(null);
  const pollerEpochRef = useRef(0);

  useEffect(() => {
    const pollerEpoch = ++pollerEpochRef.current;
    setState(idle(jobId));
    if (!jobId) return undefined;
    backgroundPollers.get(jobId)?.stop();
    backgroundPollers.delete(jobId);
    const sessionId = `video:${jobId}`;
    const poller = createVideoJobPoller({
      jobId, api,
      onUpdate: (next) => {

        const videoTimestamp = processedVideoTimestamp(next);
        const previous = gateSession(store.getState().gateMonitoring, sessionId);
        const alreadyFinal = videoIsFinal(previous.videoProcessingStatus);
        const videoAt = Number.isFinite(videoTimestamp) ? videoTimestamp * 1000 : null;
        if (pollerEpoch === pollerEpochRef.current) setState({ ...next });
        if (alreadyFinal) return;
        if (videoAt == null) {
          dispatch(updateVideoTimerSample({ sessionId, status: next.job?.status }));
          evaluateOpenTimer(videoMonitoring({ ...next, gateClassification: gateSession(store.getState().gateMonitoring, sessionId) }));
          return;
        }
        if (Number.isFinite(previous.videoTimestampSeconds) && videoTimestamp < previous.videoTimestampSeconds) {
          dispatch(updateVideoTimerSample({ sessionId, status: next.job?.status }));
          return;
        }
        dispatch(updateGateProgress({ sessionId, progress: next.monitoring?.progress,
          observedAt: videoAt, timebase: 'video' }));
        const crossingEvents = (next.events ?? []).filter((event) => event.event_type === 'CROSSING_COMPLETED');
        dispatch(updateCrossingCounts({ sessionId,
          entryCount: crossingEvents.filter((event) => event.direction === 'OUTSIDE_TO_INSIDE').length,
          exitCount: crossingEvents.filter((event) => event.direction === 'INSIDE_TO_OUTSIDE').length,
          entryCrossingAt: latestCrossingTime(crossingEvents, 'OUTSIDE_TO_INSIDE', videoTimestamp),
          exitCrossingAt: latestCrossingTime(crossingEvents, 'INSIDE_TO_OUTSIDE', videoTimestamp),
          observedAt: videoAt, timebase: 'video' }));
        // Observe the last processed frame as part of the active run before freezing it.
        // This also covers a new crossing cycle discovered in the final response.
        if (videoIsFinal(next.job?.status) && ['PROCESSING', 'CANCEL_REQUESTED'].includes(previous.videoProcessingStatus)) {
          dispatch(updateVideoTimerSample({ sessionId, timestampSeconds: videoTimestamp, status: previous.videoProcessingStatus }));
          evaluateOpenTimer(videoMonitoring({ ...next, job: { ...next.job, status: 'PROCESSING' },
            gateClassification: gateSession(store.getState().gateMonitoring, sessionId) }));
        }
        dispatch(updateVideoTimerSample({ sessionId, timestampSeconds: videoTimestamp, status: next.job?.status }));
        evaluateOpenTimer(videoMonitoring({ ...next, gateClassification: gateSession(store.getState().gateMonitoring, sessionId) }));

      },
      isVisible: () => true,
    });
    pollerRef.current = poller;
    poller.start();
    const onVisibility = () => { if (document.visibilityState === 'visible') poller.poke(); };
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      if (['QUEUED', 'PROCESSING', 'CANCEL_REQUESTED'].includes(poller.state.job?.status)) {
        backgroundPollers.set(jobId, poller);
      } else poller.stop();
      if (pollerRef.current === poller) pollerRef.current = null;
    };
  }, [jobId, dispatch, pollerGeneration]);

  const refresh = useCallback(() => pollerRef.current?.poke(), []);
  const resetMonitoring = useCallback(async () => {
    if (!jobId) return;
    pollerEpochRef.current += 1;
    pollerRef.current?.stop();
    pollerRef.current = null;
    setState(idle(jobId));
    dispatch(resetGateMonitoring({ sessionId: `video:${jobId}` }));
    await persistor.flush();
    await clearPersistedGateMonitoring();
    setPollerGeneration((generation) => generation + 1);
  }, [dispatch, jobId]);
  // Until the effect above runs for a new id, the previous job's data must not render under it.
  return { ...(state.jobId === jobId ? state : idle(jobId)), refresh, resetMonitoring };
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
