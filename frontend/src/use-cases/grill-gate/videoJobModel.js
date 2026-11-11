import { recordedVideoTimer } from './recordedVideoTimer.js';
import { processedVideoTimestamp, videoIsFinal } from './videoTimerClock.js';
/**
 * Pure uploaded-video view models (no React, so `node --test` can cover them).
 *
 * Maps GET /grill-gate/videos[/{id}[/results]] payloads into display state. The backend calculates gate geometry
 * and normalized progress; the persisted Redux slice classifies gate state from that progress.
 */
import { crossingTimestamp, elapsedSeconds,
  openWithoutCrossingSeconds as calculateOpenWithoutCrossingSeconds } from './monitoringTimers.js';

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
  EVENTS_NOT_PERSISTED: 'Processing finished, but not all of this job\u2019s events could be stored.',
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
  if (!item?.assignment?.id) return '';
  if (!item.assignment.calibration) return 'This assignment has no gate calibration. Save one under the Calibration tab first.';
  if (!zones.some((zone) => zone.zone_type === 'gate_leaf_roi' && zone.enabled !== false)) return 'This assignment has no enabled gate_leaf_roi zone. Draw and save one first.';
  return '';
}

const localConfigPrefix = (file) => file
  ? `grill-gate-video-zones:${encodeURIComponent(file.name)}:${file.size}:${file.lastModified}:`
  : '';

/** Read the zone draft saved for this exact video and package it as explicit backend configuration. */
export function localVideoConfiguration(file, storage = globalThis.localStorage) {
  if (!file || !storage) return null;
  const prefix = localConfigPrefix(file);
  let saved = null;
  try {
    for (let index = 0; index < storage.length; index += 1) {
      const key = storage.key(index);
      if (key?.startsWith(prefix)) {
        saved = JSON.parse(storage.getItem(key) || 'null');
        if (saved?.frame?.width && saved?.frame?.height) break;
      }
    }
  } catch {
    return null;
  }
  const zones = Array.isArray(saved?.zones) ? saved.zones : [];
  const zone = zones.find((entry) => entry.zone_type === 'gate_leaf_roi' && entry.enabled !== false);
  const line = saved?.line;
  if (!saved?.frame?.width || !saved?.frame?.height || !zone) return null;
  return {
    zone,
    zones,
    calibration: {
      schema_version: 1,
      reference_frame: saved.frame,
      coordinate_system: 'normalized_raw',
      calibrated_at: new Date().toISOString(),
      sliding_gate: {
        gate_roi_zone_key: 'gate_leaf_roi',
        closed_reference_position: 0,
        open_reference_position: 1,
        horizontal_movement_direction: 'left_to_right',
        position_thresholds: { closed_tolerance: 0.1, open_tolerance: 0.1 },
        confidence_threshold: 0.5,
        state_confirmation_durations: {
          closed_seconds: 0.5, opening_seconds: 0.3, open_seconds: 0.5,
          partially_open_seconds: 1, closing_seconds: 0.3,
        },
        hysteresis_fraction: 0.05,
      },
      ...(line?.start && line?.end ? { directional_crossing: {
        line_start: line.start,
        line_end: line.end,
        outside_side: 'left',
        inside_side: 'right',
        entry_direction: 'outside_to_inside',
        exit_direction: 'inside_to_outside',
        dead_band_fraction: 0.05,
        minimum_crossing_displacement: 0.02,
      } } : {}),
    },
    alert_configuration: {},
  };
}

/** Pick saved assignment settings when valid; otherwise use the video's own saved local configuration. */
export function videoUploadConfiguration(item, zones, file, storage) {
  const assignmentError = templateBlocker(item, zones);
  if (item?.assignment?.id && !assignmentError) {
    return { value: item.assignment.id, blocker: '', source: 'assignment' };
  }
  const local = localVideoConfiguration(file, storage);
  if (local) return { value: local, blocker: '', source: 'video' };
  return {
    value: null,
    blocker: 'Draw and save an enabled Sliding gate leaf zone on this video first. The video configuration is saved in this browser and sent with the upload; no camera assignment is needed.',
    source: null,
  };
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

const videoTime = (event) => formatVideoTime(event.video_time_seconds);

/** `timeOf` differs by source: video-relative for a job, clock time for a live camera. */
export function crossingView(event, timeOf = videoTime) {
  const route = [event.source_zone, event.destination_zone].filter(Boolean).map(zoneLabel).join(' → ');
  return {
    id: event.event_id, direction: DIRECTION[event.direction] ?? event.direction ?? 'CROSSING',
    timeLabel: timeOf(event), details: route,
    cameraLabel: event.track_id == null ? '' : `Track ${event.track_id}`,
  };
}

/** The Alert Service lists the statuses an alert may move to; the UI offers the matching actions. */
const alertActions = (alert) => (Array.isArray(alert.allowed_actions) ? alert.allowed_actions : [])
  .map((status) => ({ ACKNOWLEDGED: 'acknowledge', RESOLVED: 'resolve' }[status])).filter(Boolean);

export function alertView(alert, timeLabel) {
  const seconds = alert.domain_data?.video_time_seconds;
  const occurredAt = alert.triggered_at ?? alert.occurred_at;
  return {
    id: alert.id, title: alert.title, type: alert.source_event_type, severity: alert.severity, status: alert.status,
    message: alert.summary, timeLabel: timeLabel ?? (seconds == null
      ? (occurredAt ? new Date(occurredAt).toLocaleString() : '') : formatVideoTime(seconds)), active: ACTIVE_ALERT.has(alert.status),
    version: alert.row_version, actions: alertActions(alert), cameraName: alert.camera_name ?? alert.domain_data?.camera_name ?? null,
    cameraId: alert.camera_id ?? alert.resource_refs?.camera_id ?? null,
    assignmentId: alert.assignment_id ?? alert.resource_refs?.assignment_id ?? null,
    gateOpenDurationSeconds: alert.gate_open_duration_seconds ?? alert.domain_data?.gate_open_duration_seconds ?? null,
    configuredThresholdSeconds: alert.configured_threshold_seconds ?? alert.domain_data?.configured_threshold_seconds ?? null,
      evidenceRefs: alert.evidence_refs ?? [], occurredAt,
  };
}

export function eventTitle(event) {
  if (event.event_type === 'CROSSING_COMPLETED') {
    const track = event.track_id == null ? '' : ` · track #${event.track_id}`;
    return `${DIRECTION[event.direction] === 'EXIT' ? 'Exit' : DIRECTION[event.direction] === 'ENTRY' ? 'Entry' : 'Unknown'} crossing${track}`;
  }
  return event.event_type === 'MESH_PERSON_ENTERED' ? 'Person entered mesh area' : 'Person left mesh area';
}

function timelineView(event) {
  return { id: event.event_id, title: eventTitle(event), timeLabel: videoTime(event) };
}

const TRANSITION_TITLES = {
  CLOSED: 'Gate closed', FULLY_OPEN: 'Gate fully open', PARTIALLY_OPEN: 'Gate partially open',
  UNKNOWN: 'Gate state unknown',
  OPEN: 'Gate opened', OPENING: 'Gate opening started', CLOSING: 'Gate closing started',
};
export const transitionTitle = (transition) => TRANSITION_TITLES[transition.to_state] ?? `Gate ${transition.to_state}`;
const transitionId = (transition) => `gate-${transition.sequence_number ?? transition.at}-${transition.to_state}`;

/** Gate transitions merged with stored events, newest first. `keyOf` gives each row its source timestamp. */
export function mergeTimeline(events, transitions, { keyOf, labelOf, limit = 30 }) {
  const rows = [
    ...events.map((event) => ({ id: event.event_id, title: eventTitle(event), key: keyOf(event), timeLabel: labelOf(event) })),
    ...transitions.map((item) => ({ id: transitionId(item), title: transitionTitle(item), key: keyOf(item), timeLabel: labelOf(item) })),
  ];
  return rows.sort((a, b) => b.key - a.key).slice(0, limit);
}

/**
 * The dashboard snapshot for one video job, in the same shape as EMPTY_MONITORING. A null value means the backend
 * does not report it for video jobs, which panels show as "—" rather than as zero.
 */
export function videoMonitoring({ job, monitoring = null, gateClassification = {}, events = [], transitions = [], alerts = [], alertsAvailable = true } = {}) {
  const crossings = events.filter((event) => event.event_type === 'CROSSING_COMPLETED');
  const mesh = events.filter((event) => event.event_type !== 'CROSSING_COMPLETED');
  const alertViews = alerts.map((alert) => alertView(alert)).sort((a, b) => Number(b.active) - Number(a.active));
  const reported = job?.monitoring || monitoring
    ? { ...(job?.monitoring ?? {}), ...(monitoring ?? {}) }
    : null;
  const gateState = gateClassification.gateState ?? 'UNKNOWN';
  const videoTimestamp = Number.isFinite(gateClassification.videoTimestampSeconds)
    ? gateClassification.videoTimestampSeconds : processedVideoTimestamp({ job, monitoring });
  const videoNow = Number.isFinite(videoTimestamp) ? videoTimestamp * 1000 : null;
  const timerGateState = gateState;
  const gateOpenAt = gateClassification.timerTimebase === 'video'
    && Number.isFinite(gateClassification.gateOpenedAt) ? gateClassification.gateOpenedAt : null;
  const crossingAt = crossingTimestamp(crossings, 'video');
  const crossingCandidate = Number.isFinite(gateClassification.lastCrossingAt)
    ? gateClassification.lastCrossingAt : crossingAt;
  const timerCrossingAt = timerGateState === 'FULLY_OPEN' && Number.isFinite(crossingCandidate)
    && Number.isFinite(gateClassification.gateOpenedAt) && crossingCandidate >= gateClassification.gateOpenedAt
    ? crossingCandidate : null;
  const countDrivenCycleStart = gateClassification.timerTimebase === 'video'
    && Number.isFinite(gateClassification.cycleStartedAt) ? gateClassification.cycleStartedAt : null;
  // Open Without Crossing starts only from the confirmed frontend Redux cycle.
  const cycleStart = countDrivenCycleStart
    ?? (gateClassification.timerTimebase === 'video' && Number.isFinite(gateClassification.gateOpenedAt)
      ? gateClassification.gateOpenedAt : null);
  const gateOpenSeconds = timerGateState === 'FULLY_OPEN' ? elapsedSeconds(gateOpenAt, videoNow)
    : Number.isFinite(gateClassification.videoGateOpenStoppedSeconds)
      ? gateClassification.videoGateOpenStoppedSeconds : null;
  const openWithoutCrossingElapsed = timerGateState === 'FULLY_OPEN'
    ? calculateOpenWithoutCrossingSeconds({ gateState: timerGateState, openedAt: cycleStart, now: Number.isFinite(videoTimestamp) ? videoTimestamp * 1000 : null }) : null;
  const jobThreshold = job?.alert_configuration?.max_gate_open_seconds ?? null;
  const hasJobAlertConfiguration = Boolean(job && Object.hasOwn(job, 'alert_configuration'));
  const thresholdSeconds = hasJobAlertConfiguration ? jobThreshold
    : reported && Object.hasOwn(reported, 'open_without_crossing_threshold_seconds')
      ? reported.open_without_crossing_threshold_seconds : null;
  const thresholdConfigured = hasJobAlertConfiguration ? jobThreshold != null
    : reported && typeof reported.threshold_configured === 'boolean'
      ? reported.threshold_configured : thresholdSeconds != null;
  // The end of a file is not a gate observation, so it is left out of the timeline.
  const gateRows = transitions.filter((item) => item.reason !== 'video ended');
  return {
    source: 'video',
    status: job ? videoJobStatus(job.status).label.toUpperCase() : 'NO VIDEO',
    statusTone: job ? videoJobStatus(job.status).tone : 'idle',
    gateState,
    timerGateState,
    gateSessionId: gateClassification.sessionId ?? null,
    gateStateTimeLabel: '',
    gateDirection: gateClassification.direction ?? null,
    gateOpenSeconds,
    timerNow: Number.isFinite(videoTimestamp) ? videoTimestamp * 1000 : null,
    cycleStartedAt: cycleStart,
    videoTimeSeconds: videoTimestamp,
    gateOpenSince: gateOpenAt == null ? null : gateOpenAt / 1000,
    openWithoutCrossingSeconds: openWithoutCrossingElapsed,
    openWithoutCrossingThresholdSeconds: thresholdSeconds,
    thresholdConfigured,
    timerProgressPercent: openWithoutCrossingElapsed != null && thresholdSeconds > 0
      ? Math.round(Math.min(100, (openWithoutCrossingElapsed / thresholdSeconds) * 100) * 100) / 100 : null,
    timerSourceTimestamp: reported?.source_timestamp ?? null,
    lastCrossingAt: timerCrossingAt == null ? null : timerCrossingAt / 1000,
    lastCrossingDirection: reported?.last_crossing_direction ?? null,
    timerState: timerGateState === 'FULLY_OPEN'
      ? (alertViews.some((alert) => alert.type === 'GATE_OPEN_TOO_LONG') ? 'ALERT_RAISED'
        : openWithoutCrossingElapsed == null ? 'TIMER_UNAVAILABLE'
          : thresholdSeconds != null && openWithoutCrossingElapsed >= thresholdSeconds ? 'THRESHOLD_REACHED' : 'COUNTING')
      : 'NOT_COUNTING',
    timerRecorded: cycleStart != null,
    recordedTimerDisplay: recordedVideoTimer({ job, monitoring, alerts }),
    secondsSinceCrossing: elapsedSeconds(timerCrossingAt,
      Number.isFinite(videoTimestamp) ? videoTimestamp * 1000 : null),
    finalTimer: videoIsFinal(gateClassification.videoProcessingStatus) || videoIsFinal(job?.status),
    entryCount: crossings.filter((event) => event.direction === 'OUTSIDE_TO_INSIDE').length,
    exitCount: crossings.filter((event) => event.direction === 'INSIDE_TO_OUTSIDE').length,
    meshPeopleCount: reported?.mesh?.occupancy_count ?? meshOccupancy(mesh),
    meshGatheringSeconds: null,
    meshEvents: newestFirst(mesh).slice(0, 5).map(timelineView),
    crossingTotal: crossings.length,
    crossingConfigStatus: reported?.crossing?.status
      ?? (job?.readiness?.crossing_zones_defined === false ? 'missing_required_zones' : null),
    crossings: newestFirst(crossings).slice(0, 50).map((event) => crossingView(event)),
    alerts: alertViews.filter((alert) => alert.active),
    activeAlertCount: alertViews.filter((alert) => alert.active).length,
    alertsAvailable,
    events: gateRows.length
      ? mergeTimeline(events, gateRows, { keyOf: (item) => item.video_time_seconds ?? 0, labelOf: videoTime })
      : newestFirst(events).slice(0, 30).map(timelineView),
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

/** From the backend's frame totals; a file with no usable frame count reports a percentage only when finished. */
export const jobProgressPercent = (job) => {
  if (job?.status === 'COMPLETED') return 100;
  return Number.isFinite(job?.progress) ? Math.round(job.progress * 100) : null;
};

/** The status pill text: the job's state, with its percentage while it runs. */
export function jobPillLabel(job) {
  if (!job) return 'NONE';
  const percent = jobProgressPercent(job);
  return job.status === 'PROCESSING' && percent != null ? `PROCESSING ${percent}%` : job.status;
}
