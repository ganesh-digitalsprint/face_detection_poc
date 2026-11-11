import { videoIsFinal } from './videoTimerClock.js';

const seconds = (value) => Number.isFinite(value) && value >= 0 ? value : null;

/** Presentation only: never restore a Redux cycle or supply alert-evaluation elapsed time. */
export function recordedVideoTimer({ job, monitoring, alerts = [] }) {
  if (!job?.job_id || !videoIsFinal(job.status)) return null;
  const reported = { ...(job.monitoring || {}), ...(monitoring || {}) };
  const saved = seconds(reported.open_without_crossing_seconds);
  if (saved != null) return { source: 'monitoring', elapsedSeconds: saved,
    thresholdSeconds: seconds(reported.open_without_crossing_threshold_seconds),
    videoTimeSeconds: seconds(reported.video_timestamp) };
  const candidates = alerts.filter((alert) => alert.source_event_type === 'GATE_OPEN_TOO_LONG'
    && String(alert.video_job_id || alert.resource_refs?.video_job_id || alert.domain_data?.video_job_id || '') === String(job.job_id)
    && seconds(alert.gate_open_duration_seconds ?? alert.domain_data?.gate_open_duration_seconds ?? alert.domain_data?.open_without_crossing_seconds) != null);
  // An earlier incident is not the final cycle. Label it as an incident observation,
  // and choose the latest observation rather than the largest historical duration.
  candidates.sort((a,b) => {
    const at = seconds(a.domain_data?.video_time_seconds), bt = seconds(b.domain_data?.video_time_seconds);
    if (at != null && bt != null && at !== bt) return bt - at;
    return String(b.triggered_at || b.occurred_at || '').localeCompare(String(a.triggered_at || a.occurred_at || ''));
  });
  const alert = candidates[0];
  return alert ? { source: 'alert', alertId: alert.id,
    elapsedSeconds: alert.gate_open_duration_seconds ?? alert.domain_data?.gate_open_duration_seconds ?? alert.domain_data?.open_without_crossing_seconds,
    thresholdSeconds: seconds(alert.configured_threshold_seconds ?? alert.domain_data?.configured_threshold_seconds),
    videoTimeSeconds: seconds(alert.domain_data?.video_time_seconds) } : null;
}
