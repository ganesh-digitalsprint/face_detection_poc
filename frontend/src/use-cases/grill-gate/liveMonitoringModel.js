import { alertView, crossingView, eventTitle, mergeTimeline } from './videoJobModel.js';
import { crossingTimestamp, elapsedSeconds, latestConfirmedOpenTimestamp, latestFullyOpenTimestamp,
  openWithoutCrossingSeconds as calculateOpenWithoutCrossingSeconds, timerTimestamp } from './monitoringTimers.js';

/**
 * The dashboard snapshot for one live camera, in the same shape as videoMonitoring(). Everything here comes from the
 * assignment-scoped APIs; a null value means the backend has not reported it, which panels show as "—".
 */
// A timestamp with no zone is UTC, which is how the backend stores it.
const serverTime = (iso) => new Date(/(Z|[+-]\d{2}:?\d{2})$/.test(String(iso)) ? iso : `${iso}Z`);
const clockLabel = (iso) => (iso ? serverTime(iso).toLocaleTimeString(undefined, { hourCycle: 'h23' }) : '');
export function liveMonitoring({ gate = null, crossings = [], crossingTotal = 0, entryCount = 0, exitCount = 0, mesh = null,
  meshEvents = [], alerts = [], alertsAvailable = true, alertsError = '', alertsLoading = false,
  alertsRequestAttempted = false, now = Date.now() } = {}, gateClassification = {}) {
  const alertViews = alerts.map((alert) => alertView(alert, clockLabel(alert.triggered_at ?? alert.occurred_at)))
    .filter((alert) => alert.active);
  const gateState = gateClassification.gateState ?? 'UNKNOWN';
  // The timer card follows the confirmed state displayed by the Gate State panel.
  const timerGateState = gateState;
  const isFullyOpen = timerGateState === 'FULLY_OPEN';
  const gateOpenAt = timerTimestamp(gate?.gate_open_since)
    ?? latestConfirmedOpenTimestamp(gate?.recent_transitions, 'wall')
    ?? (gateClassification.timerTimebase === 'wall' && Number.isFinite(gateClassification.gateOpenedAt)
      ? gateClassification.gateOpenedAt : latestFullyOpenTimestamp(gateClassification.transitions, 'wall'));
  const eventCrossingAt = crossingTimestamp(crossings, 'wall');
  const reportedCrossingAt = timerTimestamp(gate?.last_crossing_at);
  const lastCrossingAt = reportedCrossingAt ?? eventCrossingAt
    ?? (Number.isFinite(gateClassification.lastCrossingAt) ? gateClassification.lastCrossingAt : null);
  const countDrivenCycleStart = gateClassification.timerTimebase === 'wall'
    && Number.isFinite(gateClassification.cycleStartedAt) ? gateClassification.cycleStartedAt : null;
  const cycleStart = countDrivenCycleStart
    ?? (lastCrossingAt != null && gateOpenAt != null && lastCrossingAt > gateOpenAt ? lastCrossingAt : gateOpenAt);
  const gateOpenSeconds = isFullyOpen
    ? elapsedSeconds(gateOpenAt, now)
    : null;
  const openWithoutCrossingSeconds = isFullyOpen
    ? calculateOpenWithoutCrossingSeconds({ gateState: timerGateState, openedAt: cycleStart, lastCrossingAt: null, now })
    : null;
  const threshold = gate?.open_without_crossing_threshold_seconds;
  return {
    source: 'live',
    status: gate ? 'ACTIVE' : 'INACTIVE',
    statusTone: gate ? 'ok' : 'idle',
    gateState,
    timerGateState,
    gateSessionId: gateClassification.sessionId ?? null,
    gateStateTimeLabel: '',
    gateDirection: gateClassification.direction ?? null,
    gateOpenSeconds,
    timerNow: now,
    cycleStartedAt: cycleStart,
    gateOpenSince: gateOpenAt == null ? null : new Date(gateOpenAt).toISOString(),
    openWithoutCrossingSeconds,
    openWithoutCrossingThresholdSeconds: gate?.open_without_crossing_threshold_seconds ?? null,
    thresholdConfigured: gate?.threshold_configured,
    timerProgressPercent: openWithoutCrossingSeconds != null && Number.isFinite(threshold) && threshold > 0
      ? Math.min(100, (openWithoutCrossingSeconds / threshold) * 100) : null,
    timerSourceTimestamp: gate?.source_timestamp ?? null,
    lastCrossingAt: lastCrossingAt == null ? null : new Date(lastCrossingAt).toISOString(),
    lastCrossingDirection: gate?.last_crossing_direction ?? null,
    secondsSinceCrossing: lastCrossingAt == null ? null : elapsedSeconds(lastCrossingAt, now),
    timerState: isFullyOpen
      ? (alertViews.some((alert) => alert.type === 'GATE_OPEN_TOO_LONG') ? 'ALERT_RAISED'
        : threshold != null && openWithoutCrossingSeconds >= threshold ? 'THRESHOLD_REACHED' : 'COUNTING')
      : gate?.timer_state ?? 'NOT_COUNTING',
    entryCount,
    exitCount,
    meshPeopleCount: mesh?.occupancy_count ?? 0,
    meshGatheringSeconds: null,
    meshEvents: meshEvents.slice(0, 5).map((event) => ({ id: event.event_id, title: eventTitle(event), timeLabel: clockLabel(event.occurred_at) })),
    crossingTotal,
    crossings: crossings.map((event) => crossingView(event, (item) => clockLabel(item.occurred_at))),
    alerts: alertViews,
    activeAlertCount: alertViews.length,
    alertsAvailable,
    alertsError,
    alertsLoading,
    alertsRequestAttempted,
    events: mergeTimeline([...crossings, ...meshEvents], gate?.recent_transitions ?? [], {
      keyOf: (item) => serverTime(item.occurred_at ?? item.at).getTime(),
      labelOf: (item) => clockLabel(item.occurred_at ?? item.at),
    }),
  };
}

/** Frames analysed per second between two status reads; null until there are two to compare. */
export function analysedFps(previous, gate, nowMs) {
  if (!previous || !Number.isFinite(gate?.processed_frames)) return null;
  const elapsed = (nowMs - previous.at) / 1000;
  const frames = gate.processed_frames - previous.frames;
  return elapsed > 0 && frames >= 0 ? frames / elapsed : null;
}

const REFERENCE_FORMS = {
  server_webcam: { pattern: /^device:[0-9]{1,4}$/, message: 'A server webcam reference looks like device:0.' },
};
const ENV_REFERENCE = { pattern: /^env:[A-Za-z_][A-Za-z0-9_]{0,127}$/, message: 'Enter env:NAME, naming a server environment variable that holds the address.' };

/** Same rule as the backend's resolve_connection_ref; raw URLs are never accepted or stored. */
export function connectionReferenceError(sourceType, reference) {
  const value = String(reference ?? '').trim();
  if (!value) return 'Enter a connection reference.';
  const rule = REFERENCE_FORMS[sourceType] ?? ENV_REFERENCE;
  return rule.pattern.test(value) ? '' : rule.message;
}

export const cameraCode = (name) => String(name ?? '').trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 39);

/** Zone-editor helpers: polygons as {x, y} while editing, and a stable comparison for the unsaved-changes count. */
export const normalizeZonePoints = (zone) => ({
  ...zone,
  polygon: (zone.polygon ?? []).map((point) => (Array.isArray(point) ? { x: point[0], y: point[1] } : { x: point.x, y: point.y })),
});

const zoneSignature = (zone) => JSON.stringify([zone.name, zone.zone_type, zone.enabled !== false, zone.polygon, zone.properties ?? null]);

export function countZoneChanges(baseline, draft) {
  const before = new Map(baseline.map((zone) => [zone.id, zoneSignature(zone)]));
  const after = new Set(draft.map((zone) => zone.id));
  const removed = baseline.filter((zone) => !after.has(zone.id)).length;
  const changed = draft.filter((zone) => before.get(zone.id) !== zoneSignature(zone)).length;
  return removed + changed;
}

export const zoneForSave = (zone) => {
  const { id, polygon, ...rest } = zone;
  return { ...rest, ...(String(id).startsWith('draft-') ? {} : { id }), polygon: polygon.map(({ x, y }) => [x, y]), coordinate_system: 'normalized_raw' };
};
