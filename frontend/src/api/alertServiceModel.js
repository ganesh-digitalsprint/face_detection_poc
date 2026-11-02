// Pure helpers for the Alert Service (Contract v1, docs/alert-service-contract.md).
// No browser or network access here so the logic can be unit tested with `node --test`.

export const STATUSES = ['OPEN', 'ACKNOWLEDGED', 'RESOLVED', 'DISMISSED'];
export const SEVERITIES = ['CRITICAL', 'HIGH', 'WARNING', 'INFO'];
export const ACTIVE_STATUSES = ['OPEN', 'ACKNOWLEDGED'];

export const USE_CASE_LABELS = {
  vault_monitoring: 'Vault Monitoring',
  branch_exterior: 'Branch Exterior',
};

/** Lifecycle actions as the contract names them: target status -> endpoint segment. */
export const LIFECYCLE = {
  ACKNOWLEDGED: { path: 'acknowledgements', label: 'Acknowledge', noteRequired: false },
  RESOLVED: { path: 'resolution', label: 'Resolve', noteRequired: true },
  DISMISSED: { path: 'dismissal', label: 'Dismiss', noteRequired: true },
};

export const useCaseLabel = (useCase) => USE_CASE_LABELS[useCase] || useCase || 'Unknown source';

/** Convert an Alert Service alert record into the view model used by the UI. */
export function normalizeServiceAlert(item) {
  const refs = item.resource_refs || {};
  return {
    id: item.id,
    useCase: item.use_case,
    producer: item.producer,
    sourceEventId: item.source_event_id,
    sourceEventType: item.source_event_type,
    category: item.category,
    severity: item.severity,
    sourceSeverity: item.source_severity,
    status: item.status,
    sourceStatus: item.source_status,
    title: item.title,
    summary: item.summary,
    occurredAt: item.occurred_at,
    firstSeenAt: item.first_seen_at,
    lastSeenAt: item.last_seen_at,
    receivedAt: item.received_at,
    updatedAt: item.updated_at,
    cameraId: refs.camera_id || null,
    cameraName: refs.camera_name || null,
    zoneName: refs.zone_name || null,
    sessionRef: refs.session_ref || null,
    domainData: item.domain_data || {},
    occurrenceCount: item.occurrence_count ?? 1,
    rowVersion: item.row_version,
    acknowledgedAt: item.acknowledged_at,
    acknowledgedBy: item.acknowledged_by,
    resolvedAt: item.resolved_at,
    resolvedBy: item.resolved_by,
    resolutionNote: item.resolution_note,
    dismissedAt: item.dismissed_at,
    dismissedBy: item.dismissed_by,
    // The service lists the statuses the alert may move to next ("ACKNOWLEDGED", "RESOLVED", ...).
    allowedActions: Array.isArray(item.allowed_actions) ? item.allowed_actions : [],
  };
}

const toIso = (value) => {
  if (!value) return undefined;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? undefined : date.toISOString();
};

/** Build GET /alerts (and /alerts/summary) query params from UI filters; empty filters are omitted. */
export function buildAlertParams({ status, useCase, severity, sourceType, from, to, sort, limit, cursor } = {}) {
  const params = {};
  if (STATUSES.includes(status)) params.status = status;
  if (useCase) params.use_case = useCase;
  if (SEVERITIES.includes(severity)) params.severity = severity;
  if (sourceType && sourceType.trim()) params.source_event_type = sourceType.trim();
  const fromIso = toIso(from);
  const toIsoValue = toIso(to);
  if (fromIso) params.from = fromIso;
  if (toIsoValue) params.to = toIsoValue;
  if (sort === 'oldest') params.sort = 'oldest';
  if (limit) params.limit = limit;
  if (cursor) params.cursor = cursor;
  return params;
}

/** Actions to offer for an alert. Empty when lifecycle actions are disabled or the alert is terminal. */
export function availableActions(alert, enabled) {
  if (!enabled || !alert) return [];
  return alert.allowedActions.filter((target) => LIFECYCLE[target]).map((target) => ({ target, ...LIFECYCLE[target] }));
}

/** Body for a lifecycle call. The note is mandatory for resolve/dismiss, optional for acknowledge. */
export function buildLifecycleBody(alert, target, note) {
  const trimmed = (note || '').trim();
  const rule = LIFECYCLE[target];
  if (!rule) throw new Error(`Unsupported lifecycle action: ${target}`);
  if (rule.noteRequired && !trimmed) throw new Error(`${rule.label} requires a note.`);
  return { expected_version: alert.rowVersion, ...(trimmed ? { note: trimmed } : {}) };
}

/** Replace one alert in a list by id without mutating it (the server copy wins). Unknown ids are ignored. */
export function replaceAlert(list, updated) {
  return list.map((item) => (item.id === updated.id ? updated : item));
}

/** True when an alert belongs in a list filtered by status (no filter means everything matches). */
export function matchesStatus(alert, status) {
  return !status || alert.status === status;
}

/** Merge rows into a list, de-duplicating by id (later rows win) and keeping first-seen order. */
export function mergeById(current, incoming, append) {
  const rows = append ? [...current, ...incoming] : incoming;
  return [...new Map(rows.map((row) => [row.id, row])).values()];
}

/** Turn an axios error from the Alert Service client into `{ status, code, message }` safe to show. */
export function describeServiceError(error) {
  const status = error?.response?.status ?? null;
  const detail = error?.response?.data?.detail;
  const code = detail && typeof detail === 'object' ? detail.code ?? null : null;
  const serverMessage = detail && typeof detail === 'object' ? detail.message : (typeof detail === 'string' ? detail : null);
  if (!status || (status >= 500 && !code)) {
    return { status, code, message: 'Alert Service is unavailable. Start it on port 8012 and check ALERT_SERVICE_URL for the frontend server.' };
  }
  if (status === 401) return { status, code, message: 'Alert Service rejected the operator credentials. Set ALERT_SERVICE_OPERATOR_TOKEN for the frontend server and restart it.' };
  if (status === 403) return { status, code, message: 'This operator token is not authorized for that use case.' };
  if (code === 'AUTH_NOT_CONFIGURED') return { status, code, message: 'Alert Service operator authentication is not configured.' };
  if (code === 'VERSION_CONFLICT') return { status, code, message: 'This alert changed since you loaded it. The latest version has been reloaded.' };
  if (code === 'INVALID_TRANSITION') return { status, code, message: 'That action is not allowed for the alert in its current status. The latest version has been reloaded.' };
  if (code === 'NOTE_REQUIRED') return { status, code, message: 'A note is required for this action.' };
  return { status, code, message: serverMessage || `Alert Service request failed (HTTP ${status}).` };
}

/** True when the error means the shown list is out of date and should be reloaded. */
export const isStaleConflict = (info) => info?.status === 409 || info?.status === 404;
