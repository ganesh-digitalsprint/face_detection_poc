/**
 * Pure Grill Gate view-model helpers (no React, so `node --test` can cover them).
 *
 * Everything here maps real backend payloads into display state. Nothing derives gate state, crossings,
 * mesh counts or alerts: those belong to backend stages that do not exist yet.
 */

/** Zone types the backend configures for grill_gate (labels come from GET /regions/use-cases). */
export const ZONE_COLORS = {
  gate_leaf_roi: '#7c93ff',
  gate_approach: '#4f7cf7',
  gate_interior: '#34d399',
  mesh_area: '#a78bfa',
};
export const zoneColor = (type) => ZONE_COLORS[type] ?? '#94a3b8';

/** Gate states the future backend gate-state service will report; rendered only when supplied. */
export const GATE_STATES = {
  CLOSED: { label: 'CLOSED', tone: 'text-emerald-700' },
  OPENING: { label: 'OPENING', tone: 'text-sky-700' },
  OPEN: { label: 'OPEN', tone: 'text-amber-700' },
  PARTIALLY_OPEN: { label: 'PARTIALLY OPEN', tone: 'text-amber-700' },
  CLOSING: { label: 'CLOSING', tone: 'text-sky-700' },
  UNKNOWN: { label: 'UNKNOWN', tone: 'text-[#69758F]' },
};

/** Worker statuses come from GrillGateCameraWorker.status(); the backend already flips connected -> stale. */
const CONNECTION = {
  connecting: { key: 'starting', label: 'Starting', tone: 'info', detail: 'Worker started; opening the camera source.' },
  connected: { key: 'connected', label: 'Connected', tone: 'ok', detail: 'Worker is receiving fresh frames.' },
  reconnecting: { key: 'reconnecting', label: 'Reconnecting', tone: 'warn', detail: 'Frames stopped; the worker is retrying the source.' },
  stale: { key: 'stale', label: 'Stale', tone: 'warn', detail: 'No fresh frame within the configured stale interval.' },
  stopping: { key: 'stopping', label: 'Stopping', tone: 'info', detail: 'Worker is shutting down.' },
  stopped: { key: 'disconnected', label: 'Disconnected', tone: 'idle', detail: 'Worker stopped.' },
  failed: { key: 'failed', label: 'Failed', tone: 'bad', detail: 'Camera connection failed after the retry limit.' },
};

/** Workers are keyed by camera server-side; match on assignment so another assignment's worker never shows here. */
export function workerForAssignment(workers, assignmentId) {
  if (!Array.isArray(workers) || !assignmentId) return null;
  return workers.find((worker) => worker?.assignment_id === assignmentId) ?? null;
}

/** Display state for the selected assignment. `statusError` wins: unknown is safer than a last-known "connected". */
export function connectionView(worker, { statusError = null, loaded = true } = {}) {
  if (statusError) return { key: 'unknown', label: 'Status unavailable', tone: 'bad', detail: statusError };
  if (!loaded) return { key: 'checking', label: 'Checking', tone: 'info', detail: 'Loading worker status…' };
  if (!worker) return { key: 'available', label: 'Not connected', tone: 'idle', detail: 'Assignment available; no capture worker is running.' };
  const base = CONNECTION[worker.status] ?? { key: 'unknown', label: String(worker.status || 'Unknown'), tone: 'bad', detail: 'Unrecognised worker status.' };
  const detail = worker.status === 'reconnecting' && worker.reconnect_attempt
    ? `${base.detail} Attempt ${worker.reconnect_attempt}.` : base.detail;
  return { ...base, detail: worker.error && worker.status !== 'connected' ? worker.error : detail };
}

/** A worker that is running (or trying to). Connect is idempotent server-side, but the button should not invite it. */
export const workerIsActive = (worker) => Boolean(worker && ['connecting', 'connected', 'reconnecting', 'stale', 'stopping'].includes(worker.status));

/** Bounded refresh: fast only while a state is changing, slower once settled, idle otherwise. */
export function workerPollDelay(worker) {
  if (!worker) return 15000;
  if (['connecting', 'reconnecting', 'stopping'].includes(worker.status)) return 2000;
  if (['connected', 'stale'].includes(worker.status)) return 5000;
  return 15000;
}

export function formatSeconds(seconds) {
  if (seconds == null || !Number.isFinite(Number(seconds))) return '—';
  const value = Number(seconds);
  if (value < 1) return `${Math.round(value * 1000)} ms`;
  if (value < 60) return `${value.toFixed(1)} s`;
  const total = Math.round(value);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h ? `${h}h ${m}m` : `${m}m ${String(s).padStart(2, '0')}s`;
}

/** Dashboard timer display: mm:ss, or h:mm:ss past an hour. Missing values show the empty-state 00:00. */
export function formatClock(seconds) {
  const total = Number.isFinite(Number(seconds)) && seconds != null ? Math.max(0, Math.floor(Number(seconds))) : 0;
  const h = Math.floor(total / 3600);
  const mm = String(Math.floor((total % 3600) / 60)).padStart(2, '0');
  const ss = String(total % 60).padStart(2, '0');
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/**
 * Empty dashboard snapshot. These are presentation defaults, not measurements: no backend stage produces gate
 * state, crossings, mesh counts, monitoring events or Grill Gate alerts yet. A future monitoring API should
 * return this same shape so the dashboard renders real values without a redesign.
 */
export const EMPTY_MONITORING = Object.freeze({
  status: 'INACTIVE',
  gateState: 'UNKNOWN',
  gateOpenSeconds: 0,
  openWithoutCrossingSeconds: null,
  secondsSinceCrossing: 0,
  entryCount: 0,
  exitCount: 0,
  meshPeopleCount: 0,
  meshGatheringSeconds: 0,
  crossings: [],
  alerts: [],
  events: [],
});

/** What the dashboard's camera preview should say for the selected assignment's worker. */
export function previewState(connection) {
  if (connection.key === 'unknown') return { key: 'unknown', title: 'Camera status unavailable', detail: connection.detail, canConnect: false };
  if (connection.key === 'checking') return { key: 'checking', title: 'Checking camera…', detail: '', canConnect: false };
  if (['starting', 'reconnecting', 'stopping'].includes(connection.key)) return { key: 'busy', title: `${connection.label}…`, detail: connection.detail, canConnect: false };
  if (['connected', 'stale'].includes(connection.key)) {
    return { key: 'connected', title: connection.key === 'stale' ? 'Camera feed is stale' : 'Camera connected', detail: 'The backend does not provide a video stream for Grill Gate yet, so no image is shown.', canConnect: false };
  }
  return {
    key: 'empty', title: 'No Camera Connected', canConnect: true,
    detail: connection.key === 'failed' ? `${connection.detail} Connect again to retry.` : 'Connect a camera to start Grill Gate Monitoring.',
  };
}

const REQUIRED_CALIBRATION_KEYS = ['reference_frame', 'sliding_gate', 'calibrated_at'];

/**
 * Calibration readiness for operators. The backend validates on save; this only reports what is visible:
 * missing document, unsupported version, missing gate_leaf_roi zone, or frame size differing from the worker.
 */
export function calibrationStatus(calibration, { worker = null, zones = [] } = {}) {
  if (!calibration) return { key: 'missing', tone: 'warn', label: 'Not calibrated', issues: ['No calibration is saved on this assignment.'] };
  const issues = [];
  if (calibration.schema_version !== 1 || REQUIRED_CALIBRATION_KEYS.some((name) => calibration[name] == null)) {
    return { key: 'invalid', tone: 'bad', label: 'Unsupported calibration', issues: ['The stored calibration is not a schema_version 1 Grill Gate document. Recalibrate this assignment.'] };
  }
  const frame = calibration.reference_frame;
  if (worker?.width && worker?.height && (worker.width !== frame.width || worker.height !== frame.height)) {
    issues.push(`Camera frames are ${worker.width}×${worker.height} but calibration was made at ${frame.width}×${frame.height}. Coordinates are never rescaled; recalibrate.`);
  }
  const gateZone = calibration.sliding_gate?.gate_roi_zone_key ?? 'gate_leaf_roi';
  if (!zones.some((zone) => zone.zone_type === gateZone && zone.enabled !== false)) {
    issues.push(`No enabled ${gateZone} zone is configured for the gate reference.`);
  }
  if ((calibration.monitoring?.thresholds_status ?? 'unset') === 'unset') issues.push('Monitoring thresholds are not set.');
  if (issues.length) return { key: 'attention', tone: 'warn', label: 'Needs attention', issues };
  return { key: 'ready', tone: 'ok', label: calibration.monitoring?.thresholds_status === 'approved' ? 'Calibrated · approved' : 'Calibrated · provisional', issues: [] };
}

/** PATCH /assignments replaces `configuration`, so changing one key must carry the rest (e.g. grill_gate_alerts). */
export const mergeAssignmentConfiguration = (current, changes) => ({ ...(current ?? {}), ...changes });

/** Merge live Grill Gate alert edits without dropping existing assignment settings or alert rules. */
export const mergeGrillGateAlertConfiguration = (current, alertConfiguration) => ({
  ...(current ?? {}),
  grill_gate_alerts: { ...(current?.grill_gate_alerts ?? {}), ...(alertConfiguration ?? {}) },
});

/** Reference positions are progress-space endpoints for the geometry detector, not operator settings. */
const FIXED_GATE_REFERENCE = { closed_reference_position: '0', open_reference_position: '1', horizontal_movement_direction: 'left_to_right' };

/** Baseline values used internally while advanced calibration inputs are hidden. */
export const CALIBRATION_STARTING_VALUES = {
  closed_tolerance: '0.1', open_tolerance: '0.1', confidence_threshold: '0.5', hysteresis_fraction: '0.05',
  closed_seconds: '0.5', opening_seconds: '0.3', open_seconds: '0.5', partially_open_seconds: '1', closing_seconds: '0.3',
  outside_side: 'left', inside_side: 'right', dead_band_fraction: '0.05', minimum_crossing_displacement: '0.02',
};

const FORM_META_KEYS = new Set(['width', 'height', 'thresholds_status']);
export const calibrationFormIsBlank = (form) => Object.entries(form).every(([key, value]) => FORM_META_KEYS.has(key) || !String(value ?? '').trim());

/** The calibration document for a source's own frame; nothing is rescaled, and blank forms stay unsaved. */
export function calibrationFromForm(form, frame) {
  if (calibrationFormIsBlank(form)) return null;
  return formToCalibration({ ...form, ...FIXED_GATE_REFERENCE, width: frame?.width ?? form.width, height: frame?.height ?? form.height });
}

/** Group configured zones under every backend zone type, keeping unknown types visible. */
export function zoneCoverage(zoneTypes, zones) {
  const list = Array.isArray(zones) ? zones : [];
  const rows = (zoneTypes ?? []).map((type) => ({ ...type, zones: list.filter((zone) => zone.zone_type === type.key) }));
  const known = new Set(rows.map((row) => row.key));
  const other = list.filter((zone) => !known.has(zone.zone_type));
  if (other.length) rows.push({ key: '__other', label: 'Other / unknown type', description: 'Zones whose type is not configured for Grill Gate.', zones: other });
  return rows;
}

export const THREE_ZONE_TYPES = Object.freeze(['gate_leaf_roi', 'gate_approach', 'gate_interior', 'mesh_area']);
export const zoneTypesForStrategy = (zoneTypes) => (zoneTypes ?? []).filter((type) => THREE_ZONE_TYPES.includes(type.key));

/** Normalized [[x, y], ...] or [{x, y}, ...] -> [{x, y}]. */
export const polygonPoints = (polygon) => (polygon ?? []).map((point) => (Array.isArray(point) ? { x: point[0], y: point[1] } : point));

const str = (value) => (value == null ? '' : String(value));

/** Form state is all strings so blank inputs stay blank; no business threshold gets a silent default. */
export function calibrationToForm(calibration, worker = null) {
  const gate = calibration?.sliding_gate ?? {};
  const line = calibration?.directional_crossing ?? {};
  const monitor = calibration?.monitoring ?? {};
  const durations = gate.state_confirmation_durations ?? {};
  return {
    width: str(calibration?.reference_frame?.width ?? worker?.width),
    height: str(calibration?.reference_frame?.height ?? worker?.height),
    closed_reference_position: str(gate.closed_reference_position),
    open_reference_position: str(gate.open_reference_position),
    horizontal_movement_direction: str(gate.horizontal_movement_direction),
    closed_tolerance: str(gate.position_thresholds?.closed_tolerance),
    open_tolerance: str(gate.position_thresholds?.open_tolerance),
    confidence_threshold: str(gate.confidence_threshold),
    closed_seconds: str(durations.closed_seconds),
    opening_seconds: str(durations.opening_seconds),
    open_seconds: str(durations.open_seconds),
    partially_open_seconds: str(durations.partially_open_seconds),
    closing_seconds: str(durations.closing_seconds),
    hysteresis_fraction: str(gate.hysteresis_fraction),
    line_start_x: str(line.line_start?.x),
    line_start_y: str(line.line_start?.y),
    line_end_x: str(line.line_end?.x),
    line_end_y: str(line.line_end?.y),
    outside_side: str(line.outside_side),
    inside_side: str(line.inside_side),
    dead_band_fraction: str(line.dead_band_fraction),
    minimum_crossing_displacement: str(line.minimum_crossing_displacement),
    thresholds_status: str(monitor.thresholds_status || 'unset'),
    maximum_continuous_open_seconds: str(monitor.maximum_continuous_open_seconds),
    crossing_inactivity_seconds: str(monitor.crossing_inactivity_seconds),
    minimum_mesh_gathering_count: str(monitor.minimum_mesh_gathering_count),
    mesh_gathering_seconds: str(monitor.mesh_gathering_seconds),
    suspicious_activity_seconds: str(monitor.suspicious_activity_seconds),
  };
}

// Blank required numbers are sent as null so the backend reports the exact field; we do not guess values.
const num = (value) => (String(value ?? '').trim() === '' ? null : Number(value));
const int = (value) => (String(value ?? '').trim() === '' ? null : Number.parseInt(value, 10));
const choice = (value) => (value ? value : null);

/** Build schema_version 1 config; optional advanced fields use the shared starting values. */
export function formToCalibration(form, calibratedAt = new Date()) {
  const withDefault = (name) => (String(form[name] ?? '').trim() === '' ? CALIBRATION_STARTING_VALUES[name] : form[name]);
  const line = formLine(form);
  return {
    schema_version: 1,
    reference_frame: { width: int(form.width), height: int(form.height) },
    coordinate_system: 'normalized_raw',
    calibrated_at: calibratedAt.toISOString(),
    sliding_gate: {
      gate_roi_zone_key: 'gate_leaf_roi',
      closed_reference_position: num(form.closed_reference_position),
      open_reference_position: num(form.open_reference_position),
      horizontal_movement_direction: choice(form.horizontal_movement_direction),
      position_thresholds: { closed_tolerance: num(withDefault('closed_tolerance')), open_tolerance: num(withDefault('open_tolerance')) },
      confidence_threshold: num(withDefault('confidence_threshold')),
      state_confirmation_durations: {
        closed_seconds: num(withDefault('closed_seconds')),
        opening_seconds: num(withDefault('opening_seconds')),
        open_seconds: num(withDefault('open_seconds')),
        partially_open_seconds: num(withDefault('partially_open_seconds')),
        closing_seconds: num(withDefault('closing_seconds')),
      },
      hysteresis_fraction: num(withDefault('hysteresis_fraction')),
    },
    ...(line ? { directional_crossing: {
      line_start: line.start,
      line_end: line.end,
      outside_side: choice(withDefault('outside_side')),
      inside_side: choice(withDefault('inside_side')),
      entry_direction: 'outside_to_inside',
      exit_direction: 'inside_to_outside',
      dead_band_fraction: num(withDefault('dead_band_fraction')),
      minimum_crossing_displacement: num(withDefault('minimum_crossing_displacement')),
    } } : {}),
    monitoring: {
      thresholds_status: form.thresholds_status || 'unset',
      maximum_continuous_open_seconds: num(form.maximum_continuous_open_seconds),
      crossing_inactivity_seconds: num(form.crossing_inactivity_seconds),
      minimum_mesh_gathering_count: int(form.minimum_mesh_gathering_count),
      mesh_gathering_seconds: num(form.mesh_gathering_seconds),
      suspicious_activity_seconds: num(form.suspicious_activity_seconds),
    },
  };
}

/** Line preview from form strings; null until both endpoints are valid normalized numbers. */
export function formLine(form) {
  const values = [form.line_start_x, form.line_start_y, form.line_end_x, form.line_end_y].map(num);
  if (values.some((value) => value == null || !Number.isFinite(value) || value < 0 || value > 1)) return null;
  return { start: { x: values[0], y: values[1] }, end: { x: values[2], y: values[3] } };
}
