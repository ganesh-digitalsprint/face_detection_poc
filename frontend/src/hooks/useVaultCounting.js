import { useCallback, useEffect, useRef, useState } from 'react';
import { analyzeVaultFrame } from '../api/vaultRoom.js';
import { describeError } from '../utils/errors.js';

const INITIAL = { tracks: [], rawCount: 0, latency: null, medianRequestMs: null, measuredFps: null,
  processingMs: null, lastFrameAt: null, imageWidth: 640, imageHeight: 360, status: 'idle', error: null };

function wait(ms, timers) {
  return new Promise((resolve) => {
    const id = window.setTimeout(() => { timers.delete(id); resolve(); }, ms);
    timers.set(id, resolve);
  });
}

function encodeFrame(video) {
  const width = 640;
  const height = Math.max(1, Math.round(width * video.videoHeight / video.videoWidth));
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d', { alpha: false });
  if (!context) throw new Error('Frame capture is unavailable in this browser.');
  // Draw raw video pixels: the preview's CSS mirror transform is not part of the upload.
  context.drawImage(video, 0, 0, width, height);
  return new Promise((resolve, reject) => canvas.toBlob((blob) => {
    if (blob) resolve(blob);
    else reject(new Error('Could not encode the room camera frame.'));
  }, 'image/jpeg', 0.7));
}

const targetFps = (value) => {
  const parsed = value == null ? 5 : Number(value);
  return Math.min(5, Math.max(0.5, Number.isFinite(parsed) ? parsed : 5));
};

/** Sequentially uploads the already-mounted shared video only while the room view can count. */
export default function useVaultCounting(videoRef, roomState, enabled, cameraReady, refreshRoomState) {
  const [result, setResult] = useState(INITIAL);
  const [activity, setActivity] = useState(0);
  const [retryToken, setRetryToken] = useState(0);
  const runId = useRef(0);
  const timers = useRef(new Map());
  const request = useRef(null);
  const fpsRef = useRef(roomState?.recommended_fps);
  fpsRef.current = roomState?.recommended_fps;

  useEffect(() => {
    const refresh = () => setActivity((n) => n + 1);
    document.addEventListener('visibilitychange', refresh);
    const video = videoRef.current;
    video?.addEventListener('playing', refresh);
    video?.addEventListener('pause', refresh);
    video?.addEventListener('ended', refresh);
    video?.addEventListener('loadeddata', refresh);
    return () => {
      document.removeEventListener('visibilitychange', refresh);
      video?.removeEventListener('playing', refresh);
      video?.removeEventListener('pause', refresh);
      video?.removeEventListener('ended', refresh);
      video?.removeEventListener('loadeddata', refresh);
    };
  }, [videoRef, cameraReady]);

  useEffect(() => {
    const id = ++runId.current;
    const active = enabled && cameraReady && roomState?.accepts_frames === true
      && roomState?.state !== 'CLOSED' && roomState?.detector_status === 'ready';
    const cancel = () => {
      runId.current += 1;
      request.current?.abort();
      request.current = null;
      for (const [timer, resolve] of timers.current) { window.clearTimeout(timer); resolve(); }
      timers.current.clear();
    };
    if (!active) {
      setResult((current) => ({ ...current, tracks: [], rawCount: 0,
        status: roomState?.detector_status === 'unavailable' ? 'unavailable' : 'idle', error: null }));
      return cancel;
    }

    const timings = [];
    const completions = [];
    const loop = async () => {
      let failures = 0;
      let acceptsFrames = true;
      let underTargetSince = null;
      const recordRequest = (completedAt, processingMs) => {
        const sortedTimings = [...timings].sort((a, b) => a - b);
        const middle = Math.floor(sortedTimings.length / 2);
        const medianRequestMs = sortedTimings.length % 2
          ? sortedTimings[middle] : (sortedTimings[middle - 1] + sortedTimings[middle]) / 2;
        while (completions.length && completedAt - completions[0] > 10000) completions.shift();
        const measuredFps = completions.length > 1
          ? (completions.length - 1) * 1000 / (completions.at(-1) - completions[0]) : null;
        const target = targetFps(fpsRef.current);
        if (measuredFps != null && measuredFps < target * 0.75) underTargetSince ??= completedAt;
        else underTargetSince = null;
        return { medianRequestMs, measuredFps, processingMs, slow: medianRequestMs > 1500
          || (underTargetSince != null && completedAt - underTargetSince >= 10000) };
      };
      while (runId.current === id && acceptsFrames) {
        if (document.visibilityState !== 'visible') {
          setResult((current) => ({ ...current, status: 'idle' }));
          await wait(150, timers.current);
          continue;
        }
        const video = videoRef.current;
        if (!video || video.paused || video.ended || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA
            || !video.videoWidth || !video.videoHeight) {
          setResult((current) => ({ ...current, status: 'idle' }));
          await wait(150, timers.current);
          continue;
        }

        let blob;
        try { blob = await encodeFrame(video); }
        catch (error) {
          if (runId.current !== id) return;
          failures += 1;
          if (failures >= 3) {
            setResult((current) => ({ ...current, status: 'error', error: { status: null, message: error.message } }));
            return;
          }
          await wait(Math.min(500 * (2 ** (failures - 1)), 5000), timers.current);
          continue;
        }
        if (runId.current !== id || document.visibilityState !== 'visible') continue;

        const controller = new AbortController();
        request.current = controller;
        const requestStarted = performance.now();
        setResult((current) => ({ ...current, status: 'busy', error: null }));
        try {
          const frame = await analyzeVaultFrame(blob, controller.signal);
          const completedAt = performance.now();
          if (runId.current !== id) return;
          failures = 0;
          const roundTrip = completedAt - requestStarted;
          timings.push(roundTrip);
          if (timings.length > 10) timings.shift();
          completions.push(completedAt);
          while (completions.length && completedAt - completions[0] > 10000) completions.shift();
          const metrics = recordRequest(completedAt, frame.processing_ms ?? null);
          setResult({ tracks: frame.tracks ?? [], rawCount: frame.raw_count ?? 0,
            latency: frame.processing_ms ?? null, ...metrics, imageWidth: frame.image_width ?? 640,
            imageHeight: frame.image_height ?? 360, lastFrameAt: Date.now(), status: 'running', error: null });
        } catch (error) {
          if (runId.current !== id || controller.signal.aborted) return;
          const completedAt = performance.now();
          timings.push(completedAt - requestStarted);
          if (timings.length > 10) timings.shift();
          completions.push(completedAt);
          const metrics = recordRequest(completedAt, null);
          setResult((current) => ({ ...current, ...metrics }));
          const described = describeError(error);
          if (described.status === 429) {
            setResult((current) => ({ ...current, status: 'busy' }));
            const retryAfter = Number(error?.response?.headers?.['retry-after']);
            await wait(Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter * 1000 : 1000, timers.current);
            continue;
          }
          if (described.status === 409) {
            setResult((current) => ({ ...current, tracks: [], rawCount: 0, status: 'idle' }));
            try {
              const state = await refreshRoomState();
              acceptsFrames = state.accepts_frames === true && state.state !== 'CLOSED';
            } catch { acceptsFrames = false; }
            if (!acceptsFrames) return;
            await wait(250, timers.current);
            continue;
          }
          if (described.status === 503) {
            setResult((current) => ({ ...current, tracks: [], status: 'unavailable', error: described }));
            return;
          }
          failures += 1;
          if (failures >= 3) {
            setResult((current) => ({ ...current, status: 'error', error: described }));
            return;
          }
          await wait(Math.min(500 * (2 ** (failures - 1)), 5000), timers.current);
          continue;
        } finally {
          if (request.current === controller) request.current = null;
        }

        const interval = 1000 / targetFps(fpsRef.current);
        await wait(Math.max(0, interval - (performance.now() - requestStarted)), timers.current);
      }
    };
    loop();
    return cancel;
  }, [enabled, cameraReady, roomState?.accepts_frames, roomState?.state,
    roomState?.detector_status, videoRef, activity, retryToken, refreshRoomState]);

  const retry = useCallback(() => {
    setResult(INITIAL);
    setRetryToken((n) => n + 1);
  }, []);
  return { ...result, retry };
}
