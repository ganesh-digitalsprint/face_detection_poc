import client from '../../../api/client.js';
import { regionsRegistryApi } from '../../../api/regionsRegistry.js';

// Same shared POC operator key as the Vault Room and registry modules; no separate auth path.
const key = import.meta.env?.VITE_VAULT_ROOM_API_KEY;
const headers = key ? { 'X-API-Key': key } : {};
const root = '/api/v1/grill-gate';
const USE_CASE = 'grill_gate';

/** Capture-worker lifecycle (backend/use_cases/vault_monitoring/app/api/routes/grill_gate.py). */
export const listGrillGateWorkers = (signal) =>
  client.get(`${root}/workers`, { headers, signal, timeout: 10000 }).then((r) => r.data);
/** Returns `{ created, worker }`; 202 when a worker was started, 200 when one already existed. */
export const connectGrillGateAssignment = (assignmentId) =>
  client.post(`${root}/assignments/${encodeURIComponent(assignmentId)}/connect`, undefined, { headers, timeout: 15000 }).then((r) => r.data);
/** Waits for the worker to stop server-side (up to GRILL_GATE_SHUTDOWN_TIMEOUT_SECONDS), so allow a longer timeout. */
export const disconnectGrillGateAssignment = (assignmentId) =>
  client.delete(`${root}/assignments/${encodeURIComponent(assignmentId)}/connect`, { headers, timeout: 25000 }).then((r) => r.data);
/** Gate-state detector status; returns measurement metadata only, never frame data or source references. */
export const getGateState = (assignmentId) =>
  client.get(`${root}/assignments/${encodeURIComponent(assignmentId)}/gate-state`, { headers, timeout: 5000 }).then((r) => r.data);

/** Common registry reads scoped to Grill Gate (backend routes/regions.py). */
export const listGrillGateLocations = () => regionsRegistryApi.get(`/locations?use_case=${USE_CASE}`);
export const listGrillGateCameras = () => regionsRegistryApi.get(`/cameras?use_case=${USE_CASE}`);
export const listGrillGateAssignments = () => regionsRegistryApi.get(`/assignments?use_case=${USE_CASE}`);
export const listGrillGateZoneTypes = async () =>
  (await regionsRegistryApi.get('/use-cases')).find((item) => item.id === USE_CASE)?.zone_types ?? [];
export const listAssignmentZones = (assignmentId) =>
  regionsRegistryApi.get(`/assignments/${encodeURIComponent(assignmentId)}/zones`);
export const createAssignmentZone = (assignmentId, zone) =>
  regionsRegistryApi.post(`/assignments/${encodeURIComponent(assignmentId)}/zones`, zone);
export const updateAssignmentZone = (assignmentId, zoneId, zone) =>
  regionsRegistryApi.patch(`/assignments/${encodeURIComponent(assignmentId)}/zones/${encodeURIComponent(zoneId)}`, zone);
export const deleteAssignmentZone = (assignmentId, zoneId) =>
  regionsRegistryApi.del(`/assignments/${encodeURIComponent(assignmentId)}/zones/${encodeURIComponent(zoneId)}`);
/** Stage 1 calibration is stored on the assignment and validated server-side; pass null to clear it. */
export const saveAssignmentCalibration = (assignmentId, calibration) =>
  regionsRegistryApi.patch(`/assignments/${encodeURIComponent(assignmentId)}`, { calibration });
