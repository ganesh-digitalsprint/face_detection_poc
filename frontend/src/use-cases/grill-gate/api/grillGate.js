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

/** Uploaded-video jobs. Configuration can be a template assignment ID or a self-contained video config. */
export const uploadGrillGateVideo = (file, configurationOrAssignmentId, { onProgress, signal } = {}) => {
  const body = new FormData();
  body.append('video', file, file.name);
  if (typeof configurationOrAssignmentId === 'string') {
    body.append('template_assignment_id', configurationOrAssignmentId);
  } else if (configurationOrAssignmentId) {
    body.append('configuration', JSON.stringify(configurationOrAssignmentId));
  }
  return client.post(`${root}/videos`, body, {
    headers, signal, onUploadProgress: (event) => onProgress?.(event.total ? event.loaded / event.total : null),
  }).then((r) => r.data);
};
export const startGrillGateVideoJob = (jobId) =>
  client.post(`${root}/videos/${encodeURIComponent(jobId)}/start`, undefined, { headers, timeout: 15000 }).then((r) => r.data);
export const reprocessGrillGateVideoJob = (jobId, zoneConfigurationId = null) =>
  client.post(`${root}/videos/${encodeURIComponent(jobId)}/reprocess`,
    zoneConfigurationId ? { zone_configuration_id: zoneConfigurationId } : {},
    { headers, timeout: 15000 }).then((r) => r.data);
export const cancelGrillGateVideoJob = (jobId) =>
  client.post(`${root}/videos/${encodeURIComponent(jobId)}/cancel`, undefined, { headers, timeout: 15000 }).then((r) => r.data);
export const getGrillGateVideoJob = (jobId, signal) =>
  client.get(`${root}/videos/${encodeURIComponent(jobId)}`, { headers, signal, timeout: 10000 }).then((r) => r.data);
export const listGrillGateVideoJobs = (params = { limit: 25 }) =>
  client.get(`${root}/videos`, { params, headers, timeout: 10000 }).then((r) => r.data);
/** Events for this job only, plus alerts matched server-side on resource_refs.video_job_id. */
export const getGrillGateVideoResults = (jobId, params, signal) =>
  client.get(`${root}/videos/${encodeURIComponent(jobId)}/results`, { params, headers, signal, timeout: 30000 }).then((r) => r.data);
export const deleteGrillGateVideoJob = (jobId) =>
  client.delete(`${root}/videos/${encodeURIComponent(jobId)}`, { headers, timeout: 15000 }).then((r) => r.data);
export const getVideoJobConfig = (jobId, signal) =>
  client.get(`${root}/videos/${encodeURIComponent(jobId)}/config`, { headers, signal, timeout: 10000 }).then((r) => r.data);
export const putVideoJobConfig = (jobId, config) =>
  client.put(`${root}/videos/${encodeURIComponent(jobId)}/config`, config, { headers, timeout: 15000 }).then((r) => r.data);
export const copyVideoJobConfig = (jobId, source) =>
  client.post(`${root}/videos/${encodeURIComponent(jobId)}/config/copy`, source, { headers, timeout: 15000 }).then((r) => r.data);
export const measureVideoJobEndpoints = (jobId, closedT, openT) =>
  client.post(`${root}/videos/${encodeURIComponent(jobId)}/measure-endpoints`, { closed_t: closedT, open_t: openT }, { headers, timeout: 60000 }).then((r) => r.data);
export const listGrillGateZoneConfigurations = () =>
  client.get(`${root}/zone-configurations`, { headers, timeout: 10000 }).then((r) => r.data);
export const getGrillGateZoneConfiguration = (id) =>
  client.get(`${root}/zone-configurations/${encodeURIComponent(id)}`, { headers, timeout: 10000 }).then((r) => r.data);
export const createGrillGateZoneConfiguration = (configuration) =>
  client.post(`${root}/zone-configurations`, configuration, { headers, timeout: 15000 }).then((r) => r.data);
export const updateGrillGateZoneConfiguration = (id, configuration) =>
  client.put(`${root}/zone-configurations/${encodeURIComponent(id)}`, configuration, { headers, timeout: 15000 }).then((r) => r.data);
export const duplicateGrillGateZoneConfiguration = (id, name) =>
  client.post(`${root}/zone-configurations/${encodeURIComponent(id)}/duplicate`, { name }, { headers, timeout: 15000 }).then((r) => r.data);
export const deleteGrillGateZoneConfiguration = (id) =>
  client.delete(`${root}/zone-configurations/${encodeURIComponent(id)}`, { headers, timeout: 15000 }).then((r) => r.data);

/** JPEGs go through this authenticated client as blobs; the operator key never appears in a URL. */
const getJpeg = (path, params, signal) =>
  client.get(`${root}${path}`, { params, headers, signal, responseType: 'blob', timeout: 30000 }).then((r) => r.data);
export const getVideoJobFrame = (jobId, t, signal) => getJpeg(`/videos/${encodeURIComponent(jobId)}/frame`, { t }, signal);
export const getVideoJobPreview = (jobId, signal) => getJpeg(`/videos/${encodeURIComponent(jobId)}/preview`, undefined, signal);
export const getLivePreview = (assignmentId, signal) => getJpeg(`/assignments/${encodeURIComponent(assignmentId)}/preview`, undefined, signal);

/** Live-camera monitoring reads, scoped to one assignment. */
const assignmentGet = (assignmentId, path, params, signal) =>
  client.get(`${root}/assignments/${encodeURIComponent(assignmentId)}/${path}`, { params, headers, signal, timeout: 10000 }).then((r) => r.data);
export const getLiveGateState = (assignmentId, signal) => assignmentGet(assignmentId, 'gate-state', undefined, signal);
export const getLiveCrossings = (assignmentId, params, signal) => assignmentGet(assignmentId, 'crossings', params, signal);
export const getLiveMeshStatus = (assignmentId, signal) => assignmentGet(assignmentId, 'mesh-status', undefined, signal);
export const getLiveMeshEvents = (assignmentId, params, signal) => assignmentGet(assignmentId, 'mesh-events', params, signal);
export const getLiveActiveAlerts = (assignmentId, params, signal) => assignmentGet(assignmentId, 'alerts/active', params, signal);
export const getLiveAlertHistory = (assignmentId, params, signal) => assignmentGet(assignmentId, 'alerts/history', params, signal);
export const getGrillGateAlert = (alertId) =>
  client.get(`${root}/alerts/${encodeURIComponent(alertId)}`, { headers, timeout: 15000 }).then((r) => r.data);

/** Alert lifecycle for live and uploaded-video alerts alike; a resolve needs a note. */
export const acknowledgeGrillGateAlert = (alertId, expectedVersion) =>
  client.post(`${root}/alerts/${encodeURIComponent(alertId)}/acknowledge`, { expected_version: expectedVersion }, { headers, timeout: 15000 }).then((r) => r.data);
export const resolveGrillGateAlert = (alertId, expectedVersion, note) =>
  client.post(`${root}/alerts/${encodeURIComponent(alertId)}/resolve`, { expected_version: expectedVersion, note }, { headers, timeout: 15000 }).then((r) => r.data);

/** Common registry writes behind the Camera & source form (backend routes/regions.py). */
export const listAllRegistryLocations = () => regionsRegistryApi.get('/locations');
export const createRegistryCamera = (camera) => regionsRegistryApi.post('/cameras', camera);
export const createCameraSource = (source) => regionsRegistryApi.post('/sources', source);
export const updateCameraSource = (sourceId, source) => regionsRegistryApi.patch(`/sources/${encodeURIComponent(sourceId)}`, source);
export const createGrillGateAssignment = (cameraId, sourceId) =>
  regionsRegistryApi.post('/assignments', { camera_id: cameraId, use_case: USE_CASE, configuration: { source_id: sourceId } });
export const updateAssignmentConfiguration = (assignmentId, configuration) =>
  regionsRegistryApi.patch(`/assignments/${encodeURIComponent(assignmentId)}`, { configuration });

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
