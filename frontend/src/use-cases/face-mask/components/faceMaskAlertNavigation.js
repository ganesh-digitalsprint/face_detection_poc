const COMMON_INCIDENT_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function faceMaskIncidentLocation(incidentId) {
  if (typeof incidentId !== 'string' || !COMMON_INCIDENT_ID.test(incidentId)) return null;
  const query = new URLSearchParams({ use_case: 'face_mask', alert_id: incidentId });
  return `/alerts?${query.toString()}`;
}

export const faceMaskAlertCenterLocation = '/alerts?use_case=face_mask';
