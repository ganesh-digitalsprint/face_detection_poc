/**
 * Pure uploaded-video view models (no React, so `node --test` can cover them).
 *
 * Everything maps GET /grill-gate/videos[/{id}[/results]] payloads into display state. The backend does the
 * decoding and detection; nothing here estimates progress or creates monitoring values.
 */

/** Statuses written by GrillGateVideoJobs. UPLOADED is the only state POST .../start accepts. */
export const VIDEO_JOB_STATUS = {
  UPLOADED: { label: 'Ready to process', tone: 'info' },
  QUEUED: { label: 'Queued', tone: 'info' },
  PROCESSING: { label: 'Processing', tone: 'info' },
  CANCEL_REQUESTED: { label: 'Cancelling', tone: 'warn' },
  COMPLETED: { label: 'Completed', tone: 'ok' },
  FAILED: { label: 'Failed', tone: 'bad' },
  CANCELLED: { label: 'Cancelled', tone: 'idle' },
};
export const videoJobStatus = (status) => VIDEO_JOB_STATUS[status] ?? { label: String(status || 'Unknown'), tone: 'idle' };

const ACTIVE = new Set(['QUEUED', 'PROCESSING', 'CANCEL_REQUESTED']);
const TERMINAL = new Set(['COMPLETED', 'FAILED', 'CANCELLED']);
export const jobIsActive = (job) => ACTIVE.has(job?.status);
export const jobIsTerminal = (job) => TERMINAL.has(job?.status);
export const jobCanStart = (job) => job?.status === 'UPLOADED';
export const jobCanCancel = (job) => job?.status === 'UPLOADED' || job?.status === 'QUEUED' || job?.status === 'PROCESSING';

const ERROR_CODES = {
  PROCESS_INTERRUPTED: 'The server restarted while this job was running. The stored video is not reprocessed automatically.',
  VIDEO_PIPELINE_FAILED: 'Video processing failed. Check that the video dimensions match the calibration used for this job.',
  VIDEO_FILE_MISSING: 'The stored video file is no longer on the server, so this job cannot run.',
};
export const jobErrorMessage = (code) => (code ? ERROR_CODES[code] ?? `Processing failed (${code}).` : '');

/** Backend upload rules from validate_video: extension must be .mp4 or .avi. Size limits are enforced server-side. */
export function validateVideoFile(file) {
  if (!file) return 'Choose a video file.';
  const name = String(file.name ?? '').toLowerCase();
  if (!name.endsWith('.mp4') && !name.endsWith('.avi')) return 'Only MP4 and AVI videos can be processed. Other formats can be previewed here but not saved.';
  if (!file.size) return 'This video file is empty.';
  return '';
}

/** Why the selected assignment cannot supply the job's configuration snapshot; '' when it can. */
export function templateBlocker(item, zones = []) {
  if (!item?.assignment?.id) return 'Assign a camera to Grill Gate first: a saved video copies that assignment’s zones and calibration.';
  if (!item.assignment.calibration) return 'This assignment has no gate calibration. Save one under the Calibration tab first.';
  if (!zones.some((zone) => zone.zone_type === 'gate_leaf_roi' && zone.enabled !== false)) return 'This assignment has no enabled gate_leaf_roi zone. Draw and save one first.';
  return '';
}

/** Video-relative timestamp, e.g. 01:12.4. The backend's occurred_at for a video is job start plus this offset. */
export function formatVideoTime(seconds) {
  const value = Number(seconds);
  if (seconds == null || !Number.isFinite(value)) return '—';
  const total = Math.max(0, value);
  const minutes = Math.floor(total / 60);
  return `${String(minutes).padStart(2, '0')}:${(total - minutes * 60).toFixed(1).padStart(4, '0')}`;
}

/** Keep the first copy of each stable backend id, so a re-read page can never duplicate an entry. */
export function mergeEvents(existing, incoming) {
  const seen = new Set(existing.map((event) => event.event_id));
  const added = (incoming ?? []).filter((event) => !seen.has(event.event_id) && seen.add(event.event_id));
  if (!added.length) return existing;
  return [...existing, ...added].sort((a, b) => (a.video_time_seconds ?? 0) - (b.video_time_seconds ?? 0));
}

const DIRECTION = { OUTSIDE_TO_INSIDE: 'ENTRY', INSIDE_TO_OUTSIDE: 'EXIT' };
const ACTIVE_ALERT = new Set(['OPEN', 'ACKNOWLEDGED']);
const zoneLabel = (zone) => String(zone ?? '').replace(/^gate_/, '').replace(/_/g, ' ');
const newestFirst = (list) => [...list].reverse();

/** Occupancy replayed from the job's own enter/exit events; each track counts once. */
function meshOccupancy(events) {
  const inside = new Set();
  for (const event of events) {
    if (event.event_type === 'MESH_PERSON_ENTERED') inside.add(event.track_id);
    else if (event.event_type === 'MESH_PERSON_EXITED') inside.delete(event.track_id);
  }
  return inside.size;
}

function crossingView(event) {
  const route = [event.source_zone, event.destination_zone].filter(Boolean).map(zoneLabel).join(' → ');
  return {
    id: event.event_id, direction: DIRECTION[event.direction] ?? event.direction ?? 'CROSSING',
    timeLabel: formatVideoTime(event.video_time_seconds), details: route,
    cameraLabel: event.track_id == null ? '' : `Track ${event.track_id}`,
  };
}

function alertView(alert) {
  const seconds = alert.domain_data?.video_time_seconds;
  return {
    id: alert.id, title: alert.title, type: alert.source_event_type, severity: alert.severity, status: alert.status,
    message: alert.summary, timeLabel: seconds == null ? '' : formatVideoTime(seconds), active: ACTIVE_ALERT.has(alert.status),
  };
}

function timelineView(event) {
  const title = event.event_type === 'CROSSING_COMPLETED'
    ? `${DIRECTION[event.direction] ?? 'Crossing'} crossing`
    : event.event_type === 'MESH_PERSON_ENTERED' ? 'Person entered mesh area' : 'Person left mesh area';
  return { id: event.event_id, title, timeLabel: formatVideoTime(event.video_time_seconds) };
}

/**
 * The dashboard snapshot for one video job, in the same shape as EMPTY_MONITORING. A null value means the backend
 * does not report it for video jobs, which panels show as "—" rather than as zero.
 */
export function videoMonitoring({ job, events = [], alerts = [], alertsAvailable = true } = {}) {
  const crossings = events.filter((event) => event.event_type === 'CROSSING_COMPLETED');
  const mesh = events.filter((event) => event.event_type !== 'CROSSING_COMPLETED');
  const lastCrossing = crossings.at(-1);
  const alertViews = alerts.map(alertView).sort((a, b) => Number(b.active) - Number(a.active));
  return {
    source: 'video',
    status: job ? videoJobStatus(job.status).label.toUpperCase() : 'NO VIDEO',
    statusTone: job ? videoJobStatus(job.status).tone : 'idle',
    gateState: lastCrossing?.metadata?.gate_state ?? null,
    gateStateTimeLabel: lastCrossing?.metadata?.gate_state ? formatVideoTime(lastCrossing.video_time_seconds) : '',
    gateOpenSeconds: null,
    secondsSinceCrossing: lastCrossing ? Math.max(0, (job?.progress_seconds ?? 0) - (lastCrossing.video_time_seconds ?? 0)) : null,
    entryCount: crossings.filter((event) => event.direction === 'OUTSIDE_TO_INSIDE').length,
    exitCount: crossings.filter((event) => event.direction === 'INSIDE_TO_OUTSIDE').length,
    meshPeopleCount: meshOccupancy(mesh),
    meshGatheringSeconds: null,
    meshEvents: newestFirst(mesh).slice(0, 5).map(timelineView),
    crossingTotal: crossings.length,
    crossings: newestFirst(crossings).slice(0, 50).map(crossingView),
    alerts: alertViews,
    activeAlertCount: alertViews.filter((alert) => alert.active).length,
    alertsAvailable,
    events: newestFirst(events).slice(0, 30).map(timelineView),
  };
}

/** Finished jobs use their own timestamps; running jobs compare two polls, so the rate is measured, not assumed. */
export function processingFps(job, previous, nowMs) {
  if (job?.status === 'COMPLETED' && job.started_at && job.completed_at) {
    const elapsed = (new Date(job.completed_at) - new Date(job.started_at)) / 1000;
    return elapsed > 0 && job.frame_count > 0 ? job.frame_count / elapsed : null;
  }
  if (job?.status !== 'PROCESSING' || !previous) return null;
  const elapsed = (nowMs - previous.at) / 1000;
  const frames = job.frame_count - previous.frames;
  return elapsed > 0 && frames > 0 ? frames / elapsed : null;
}

/** The backend reports processed frames but no total, so a percentage exists only once a job has completed. */
export const jobProgressPercent = (job) => (job?.status === 'COMPLETED' ? 100 : null);
