import client from './client.js';

const root = '/api/v1';
// Shared POC operator key is public in the browser bundle; configure a real
// user/session auth provider before exposing operator actions beyond local dev.
const operatorHeaders = import.meta.env.VITE_VAULT_ROOM_API_KEY
  ? { 'X-API-Key': import.meta.env.VITE_VAULT_ROOM_API_KEY }
  : {};

export const getAlerts = (params = {}) => client.get(`${root}/alerts`, { params, headers: operatorHeaders }).then((r) => r.data);
export const getAlertSummary = (params = {}) => client.get(`${root}/alerts/summary`, { params, headers: operatorHeaders }).then((r) => r.data);
export const getAlertMeta = () => client.get(`${root}/alerts/meta`, { headers: operatorHeaders }).then((r) => r.data);
export const getAlert = (id) => client.get(`${root}/alerts/${encodeURIComponent(id)}`, { headers: operatorHeaders }).then((r) => r.data);
export const getIncident = (id) => client.get(`${root}/incidents/${encodeURIComponent(id)}`, { headers: operatorHeaders }).then((r) => r.data);
export const updateAlert = (id, action, payload = {}) =>
  client.post(`${root}/alerts/${encodeURIComponent(id)}/${action}`, payload, { headers: operatorHeaders }).then((r) => r.data);
export const createIncidentFromAlert = (id) =>
  client.post(`${root}/alerts/${encodeURIComponent(id)}/incident`, undefined, { headers: operatorHeaders }).then((r) => r.data);
export const getEvidenceAccess = (ids, variant = 'thumb') =>
  client.post(`${root}/evidence/access`, { ids, variant }, { headers: operatorHeaders }).then((r) => r.data);

/** Keep all raw API field access in this adapter; UI components consume this view model. */
export function normalizeAlert(item) {
  return {
    id: item.id,
    type: item.alert_type,
    severity: item.severity,
    status: item.status,
    title: item.title,
    message: item.message,
    source: item.source,
    sessionRef: item.session_ref,
    cameraId: item.camera_id,
    incidentId: item.incident_id,
    incidentNumber: item.incident_number,
    observedCount: item.observed_count,
    requiredCount: item.required_count,
    firstSeenAt: item.first_seen_at,
    lastSeenAt: item.last_seen_at,
    occurrenceCount: item.occurrence_count,
    createdAt: item.created_at,
    updatedAt: item.updated_at,
    evidenceCount: item.evidence_count,
    evidenceStatus: item.evidence_status,
    primaryEvidenceId: item.primary_evidence_id,
    rowVersion: item.row_version,
    allowedActions: Array.isArray(item.allowed_actions) ? item.allowed_actions : [],
    branchId: item.branch_id,
    branchName: item.branch_name,
    useCase: item.use_case,
  };
}
