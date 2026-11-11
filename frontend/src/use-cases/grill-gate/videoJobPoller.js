import { jobIsActive, jobIsTerminal, mergeEvents, processingFps } from './videoJobModel.js';

const PAGE_SIZE = 500;
// Events sharing a video time are ordered by id, so re-read a short overlap rather than trusting the last offset.
const OVERLAP = 50;
const MAX_RETRY_MS = 15000;

/**
 * Controlled polling of one video job (GET job + GET results), kept free of React so it can be tested directly.
 * One request cycle runs at a time, polling stops at a terminal status, and nothing is published after stop().
 */
export function createVideoJobPoller({
  jobId, api, onUpdate, intervalMs = 2000, isVisible = () => true, now = () => Date.now(),
  setTimer = (fn, ms) => setTimeout(fn, ms), clearTimer = (id) => clearTimeout(id),
}) {
  const state = { jobId, job: null, monitoring: null, events: [], transitions: [], alerts: [], alertsAvailable: true, fps: null, loading: true, error: '', notFound: false };
  let stopped = false;
  let inFlight = false;
  let pending = false;
  let timer = null;
  let failures = 0;
  let sample = null;
  let controller = null;

  const publish = () => { if (!stopped) onUpdate({ ...state }); };

  const readResults = async (signal, fromStart) => {
    let offset = fromStart ? 0 : Math.max(0, state.events.length - OVERLAP);
    for (;;) {
      const page = await api.getResults(jobId, { limit: PAGE_SIZE, offset }, signal);
      if (stopped) return;
      state.events = mergeEvents(state.events, page.items);
      state.transitions = page.transitions ?? [];
      state.alerts = page.alerts ?? [];
      state.alertsAvailable = page.alerts_available !== false;
      state.monitoring = page.monitoring ?? null;
      if ((page.items?.length ?? 0) < PAGE_SIZE) return;
      offset += page.items.length;
    }
  };

  const schedule = (delay) => {
    clearTimer(timer);
    timer = null;
    if (!stopped && isVisible()) timer = setTimer(tick, delay);
  };

  async function tick() {
    if (stopped) return;
    if (inFlight) { pending = true; return; }
    inFlight = true;
    pending = false;
    controller = new AbortController();
    let keepPolling = false;
    let failed = false;
    try {
      const job = await api.getJob(jobId, controller.signal);
      if (stopped) return;
      let effectiveJob = job;
      if (!Object.hasOwn(job, 'alert_configuration') && api.getConfig) {
        try {
          const config = await api.getConfig(jobId, controller.signal);
          if (config?.alert_configuration) effectiveJob = { ...job, alert_configuration: config.alert_configuration };
        } catch {
          // The job status remains usable if the optional saved-config endpoint is temporarily unavailable.
        }
      }
      const at = now();
      state.fps = processingFps(job, sample, at) ?? (job.status === 'PROCESSING' ? state.fps : null);
      sample = job.status === 'PROCESSING' ? { frames: job.frame_count, at } : null;
      state.job = effectiveJob;
      // The worker flushes its events before writing a terminal status, so this read of a finished job is complete.
      await readResults(controller.signal, jobIsTerminal(job));
      if (stopped) return;
      state.error = '';
      failures = 0;
      keepPolling = jobIsActive(job);
    } catch (exception) {
      if (stopped || exception?.code === 'ERR_CANCELED') return;
      if (exception?.response?.status === 404) {
        state.notFound = true;
        state.error = 'This video job no longer exists.';
      } else {
        failed = true;
        failures += 1;
        state.error = api.describeError(exception);
      }
    } finally {
      inFlight = false;
    }
    state.loading = false;
    publish();
    // Last-known results stay on screen while a failed cycle retries with a bounded backoff.
    if (pending) tick();
    else if (failed) schedule(Math.min(MAX_RETRY_MS, intervalMs * 2 ** failures));
    else if (keepPolling) schedule(intervalMs);
  }

  return {
    start: tick,
    /** Refresh now, e.g. after POST .../start. A request already running is followed by one more. */
    poke: () => { clearTimer(timer); timer = null; return tick(); },
    stop: () => { stopped = true; clearTimer(timer); controller?.abort(); },
    get state() { return { ...state }; },
  };
}
