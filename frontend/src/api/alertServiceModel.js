// Pure helpers for the Alert Service (Contract v1, docs/alert-service-contract.md).
// No browser or network access here so the logic can be unit tested with `node --test`.
export const STATUSES = ['OPEN', 'ACKNOWLEDGED', 'RESOLVED', 'DISMISSED'];
export const SEVERITIES = ['CRITICAL', 'HIGH', 'WARNING', 'INFO'];
export const ACTIVE_STATUSES = ['OPEN', 'ACKNOWLEDGED'];

export const USE_CASE_LABELS = {
  vault_monitoring: 'Vault Monitoring',
  branch_exterior: 'Branch Exterior',
  grill_gate: 'Grill Gate Monitoring',
  face_mask: 'Face Mask',
};

/** Lifecycle actions as the contract names them: target status -> endpoint segment. */
export const LIFECYCLE = {
  ACKNOWLEDGED: { path: 'acknowledgements', label: 'Acknowledge', noteRequired: false },
  RESOLVED: { path: 'resolution', label: 'Resolve', noteRequired: true },
  DISMISSED: { path: 'dismissal', label: 'Discard', noteRequired: true },
};

export const useCaseLabel = (useCase) => USE_CASE_LABELS[useCase] || useCase || 'Unknown source';

export function alertDetailLocationFields(alert) {
  const refs = alert.resourceRefs || {};
  const domain = alert.domainData || {};
  return [
    ['Camera name', alert.cameraName || refs.camera_name],
    ['Branch', alert.branchName || refs.branch_name],
    ['Branch code', alert.branchCode || refs.branch_code],
    ['Place', alert.placeName || refs.place_name || domain.place_name || alert.locationName || refs.location_name || alert.zoneName],
    ['Region', alert.regionName || refs.region_name || domain.region_name],
    ['Branch manager', alert.branchManager || refs.branch_manager || domain.branch_manager],
  ];
}

/** Convert an Alert Service alert record into the view model used by the UI. */
export function normalizeServiceAlert(item) {
  const refs = item.resource_refs || {};
  const cameraName = item.camera_name || refs.camera_name || item.domain_data?.camera_name || null;
  const subtype = item.source_event_subtype || item.domain_data?.source_event_subtype
    || (item.use_case === 'branch_exterior' ? item.domain_data?.kind : null) || null;
  const broad = String(item.source_event_type || '').replaceAll('_', ' ');
  const broadTitle = broad.charAt(0).toUpperCase() + broad.slice(1);
  const useSubtypeTitle = item.use_case === 'branch_exterior' && typeof subtype === 'string'
    && (!item.title || item.title === broadTitle || item.title === `${broadTitle} at ${cameraName}`);
  const typeTitle = typeof subtype === 'string' ? subtype.replaceAll('_', ' ') : '';
  const evidenceRefs=Array.isArray(item.evidence_refs) ? item.evidence_refs.filter((ref)=>ref && typeof ref==='object' && ref.available!==false) : [];
  const snapshotCount=snapshotRefs({evidenceRefs}).length;
  const clipCount=evidenceRefs.filter((ref)=>ref.type==='clip').length;
  return {
    id: item.id,
    useCase: item.use_case,
    producer: item.producer,
    lifecycleOwner: item.lifecycle_owner || item.domain_data?.lifecycle_owner,
    evidenceRefs,
    evidenceCount:evidenceRefs.length,snapshotCount,clipCount,
    evidenceStatus:evidenceRefs.length ? 'CAPTURED' : (item.evidence_status || item.domain_data?.evidence_status)==='PENDING' ? 'PENDING' : 'UNAVAILABLE',
    evidenceUnavailableReason: item.domain_data?.evidence_unavailable_reason || null,
    assignmentId: item.assignment_id || refs.assignment_id || null,
    videoJobId: item.video_job_id || refs.video_job_id || item.domain_data?.video_job_id || null,
    localId: null,
    sourceEventId: item.source_event_id,
    sourceEventVersion: item.source_event_version,
    sourceEventType: item.source_event_type,
    sourceEventSubtype: subtype,
    displayEventType: item.display_event_type || subtype || item.source_event_type,
    resourceRefs: refs,
    category: item.category,
    severity: item.severity,
    sourceSeverity: item.source_severity,
    status: item.status,
    sourceStatus: item.source_status,
    title: useSubtypeTitle ? `${typeTitle.charAt(0).toUpperCase() + typeTitle.slice(1)}${cameraName ? ` at ${cameraName}` : ''}` : item.title,
    summary: item.summary,
    occurredAt: item.occurred_at,
    firstSeenAt: item.first_seen_at,
    lastSeenAt: item.last_seen_at,
    receivedAt: item.received_at,
    updatedAt: item.updated_at,
    cameraId: item.camera_id || refs.camera_id || null,
    cameraName,
    branchId: item.branch_id || refs.branch_id || null,
    branchCode: item.branch_code || refs.branch_code || null,
    branchName: item.branch_name || refs.branch_name || null,
    placeName: item.place_name || refs.place_name || item.domain_data?.place_name || null,
    regionName: item.region_name || refs.region_name || item.domain_data?.region_name || null,
    branchManager: item.branch_manager || refs.branch_manager || item.domain_data?.branch_manager || null,
    registryCameraId: item.registry_camera_id || refs.registry_camera_id || null,
    sourceId: item.source_id || refs.source_id || null,
    sourceType: item.source_type || refs.source_type || null,
    templateAssignmentId: item.template_assignment_id || refs.template_assignment_id || null,
    locationId: item.location_id || refs.location_id || null,
    locationName: item.location_name || refs.location_name || null,
    zoneId: item.zone_id || refs.zone_id || null,
    zoneName: refs.zone_name || null,
    sessionRef: item.session_ref || refs.session_ref || null,
    domainData: item.domain_data || {},
    occurrenceCount: item.occurrence_count ?? 1,
    rowVersion: item.row_version,
    acknowledgementComment: item.acknowledgement_comment ?? item.domain_data?.acknowledgement_comment,
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
export function buildAlertParams({ status, useCase, severity, sourceType, from, to, sort, limit, cursor,
  branchId, cameraId, assignmentId, videoJobId, sessionRef, sourceId, registryCameraId, sourceSubtype } = {}) {
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
  for (const [key, value] of Object.entries({ branch_id: branchId, camera_id: cameraId, assignment_id: assignmentId,
    video_job_id: videoJobId, session_ref: sessionRef, source_id: sourceId,
    registry_camera_id: registryCameraId, source_event_subtype: sourceSubtype })) {
    if (value) params[key] = value;
  }
  return params;
}

/** Actions to offer for an alert. Empty when lifecycle actions are disabled or the alert is terminal. */
export function availableActions(alert, enabled) {
  if (!enabled || !alert) return [];
  const targets = alert.sourceAllowedActions ?? (['grill_gate','vault_monitoring'].includes(alert.useCase) || alert.lifecycleOwner === 'source' ? [] : alert.allowedActions);
  const byStatus = { OPEN: ['ACKNOWLEDGED', 'RESOLVED', 'DISMISSED'], ACKNOWLEDGED: ['RESOLVED', 'DISMISSED'] };
  return (targets || []).filter((target) => byStatus[alert.status]?.includes(target) && LIFECYCLE[target]).map((target) => ({ target, ...LIFECYCLE[target] }));
}

/** Body for a lifecycle call. The note is mandatory for resolve/dismiss, optional for acknowledge. */
export function buildLifecycleBody(alert, target, note) {
  const trimmed = (note || '').trim();
  const rule = LIFECYCLE[target];
  if (!rule) throw new Error(`Unsupported lifecycle action: ${target}`);
  if (rule.noteRequired && !trimmed) throw new Error(`${rule.label} requires a note.`);
  return { expected_version: alert.sourceRowVersion ?? alert.rowVersion, ...(trimmed ? { note: trimmed } : {}) };
}

/** Replace one alert in a list by id without mutating it (the server copy wins). Unknown ids are ignored. */
export function replaceAlert(list, updated) {
  return list.map((item) => (item.id === updated.id ? updated : item));
}

/** True when an alert belongs in a list filtered by status (no filter means everything matches). */
export function matchesStatus(alert, status) {
  return !status || (status === 'ACTIVE' ? ACTIVE_STATUSES.includes(alert.status)
    : status === 'HISTORY' ? ['RESOLVED', 'DISMISSED'].includes(alert.status) : alert.status === status);
}

/** Merge rows into a list, de-duplicating by id (later rows win) and keeping first-seen order. */
export function mergeById(current, incoming, append) {
  const rows = append ? [...current, ...incoming] : incoming;
  return [...new Map(rows.map((row) => [row.useCase === 'grill_gate' && row.sourceEventId ? `grill_gate:${row.sourceEventId}` : row.id, row])).values()];
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


// Local and published Grill Gate records use the same presentation model.
export function normalizeGrillGateAlert(item) {
  const view = normalizeServiceAlert({ ...item, use_case: 'grill_gate' });
  return { ...view, localId: item.id, domainData: {
    ...view.domainData,
    ...(item.gate_open_duration_seconds != null ? { gate_open_duration_seconds: item.gate_open_duration_seconds } : {}),
    ...(item.configured_threshold_seconds != null ? { configured_threshold_seconds: item.configured_threshold_seconds } : {}),
  } };
}

export function alertSourceLink(alert) {
  if (alert.useCase === 'face_mask') return '/face-mask/live';
  if (alert.useCase !== 'grill_gate') return { vault_monitoring: '/vault-access', branch_exterior: '/branch-exterior/live' }[alert.useCase];
  const query = new URLSearchParams({ view: alert.videoJobId ? 'video' : 'live' });
  if (alert.videoJobId) query.set('job', alert.videoJobId);
  else if (alert.assignmentId) query.set('assignment', alert.assignmentId);
  query.set('alert', alert.sourceEventId || alert.id);
  if (['RESOLVED','DISMISSED'].includes(alert.status)) query.set('status','HISTORY');
  return `/grill-gate?${query}`;
}

export function grillAlertMetadata(alert) {
  const d = alert.domainData || {};
  return [
    ['Gate state', d.gate_state],
    ['Observed duration', d.gate_open_duration_seconds ?? d.observed_duration_seconds ?? d.duration_seconds],
    ['Threshold', d.configured_threshold_seconds ?? d.threshold_seconds],
    ['Entry count', d.entry_count], ['Exit count', d.exit_count],
    ['People in mesh area', d.observed_occupancy ?? d.mesh_people_count ?? d.people_count ?? d.current_count],
    ['Maximum mesh occupancy', d.maximum_occupancy],
    ['Video time (seconds)', d.video_time_seconds],
  ].filter(([, value]) => value != null);
}

// Accept only the source-owned, scoped snapshot route. Never fetch arbitrary hosts.
export function grillEvidenceRequest(ref) {
  if (typeof ref?.retrieval_path !== 'string' || !ref.retrieval_path.startsWith('/api/v1/grill-gate/alerts/')) return null;
  const url = new URL(ref.retrieval_path, 'http://local.invalid');
  if (url.origin !== 'http://local.invalid' || !/^\/api\/v1\/grill-gate\/alerts\/[^/]+\/evidence\/[^/]+$/.test(url.pathname)) return null;
  const assignment = url.searchParams.get('assignment_id');
  const video = url.searchParams.get('video_job_id');
  if (Boolean(assignment) === Boolean(video)) return null;
  return { path: url.pathname, params: assignment ? { assignment_id: assignment } : { video_job_id: video } };
}


export function grillSnapshotRefs(alert) {
  return (alert.evidenceRefs || []).filter((ref) => grillEvidenceRequest(ref)
    && (ref.type === 'snapshot' || ref.content_type?.startsWith('image/') || !ref.type));
}

export function snapshotRefs(alert) {
  return (alert.evidenceRefs || []).filter((ref)=>ref.available!==false && (ref.type==='snapshot'
    || ref.content_type?.startsWith('image/') || (!ref.type && grillEvidenceRequest(ref))));
}

export function alertSourceLabel(alert) {
  return alert.cameraName || alert.domainData?.video_filename || alert.domainData?.filename
    || (alert.videoJobId ? `Uploaded video - ${alert.videoJobId}` : alert.cameraId) || 'Monitoring source';
}

export function evidenceLabel(alert) {
  if ((alert.snapshotCount ?? snapshotRefs(alert).length)>0) return 'Snapshot captured';
  if (alert.clipCount>0) return 'Clip available';
  if (alert.evidenceStatus === 'PENDING') return 'Snapshot pending';
  if (alert.evidenceStatus === 'CAPTURED') return 'Snapshot reference unavailable';
  return 'No snapshot attached';
}
