import { api } from './api/index.js';
import { regionsRegistryApi } from '../../api/regionsRegistry.js';

export const REGIONS_USE_CASES = [
  { id: 'branch-exterior', label: 'Branch Exterior Monitoring', enabled: true },
  { id: 'vault-room', label: 'Vault Room Monitoring', enabled: false },
  { id: 'grill-gate', label: 'Grill Gate Monitoring', enabled: false },
];

export function branchLocations(cameras = []) {
  const names = [...new Set(cameras.map((camera) => String(camera.location || '').trim()))];
  return names.map((name) => ({ id: name || '__unassigned__', name: name || 'Unassigned location' }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

export function branchCamerasForLocation(cameras = [], locationId = '') {
  return cameras.filter((camera) => (String(camera.location || '').trim() || '__unassigned__') === locationId);
}

export function buildZoneSavePayload(cameraId, body, polygon, editing = false) {
  const zone = { ...body, polygon };
  return editing ? zone : { camera_id: cameraId, ...zone };
}

export function selectionResponseIsCurrent(requestId, latestRequestId, cameraId, selectedCameraId) {
  return requestId === latestRequestId && cameraId === selectedCameraId;
}

export function buildBranchAdapter(client) {
  return {
    id: 'branch-exterior',
    label: 'Branch Exterior Monitoring',
    enabled: true,
    listCameras: () => client.get('/cameras'),
    listLocations: branchLocations,
    camerasForLocation: branchCamerasForLocation,
    listCameraStatuses: () => client.get('/cameras/status/all'),
    loadZones: (cameraId) => client.get(`/zones?camera_id=${encodeURIComponent(cameraId)}`),
    saveZone: async (cameraId, editing, body, polygon) => {
      const payload = buildZoneSavePayload(cameraId, body, polygon, Boolean(editing));
      try {
        if (editing) await client.patch(`/zones/${editing.id}`, payload);
        else await client.post('/zones', payload);
        return '';
      } catch (error) {
        if (!/^422/.test(String(error.message))) throw error;
        const base = {
          name: body.name, zone_type: body.zone_type, restricted: body.restricted, polygon,
        };
        const alerts = { alert_mode: body.alert_mode, alert_severity: body.alert_severity };
        let zoneId = editing?.id;
        if (editing) await client.patch(`/zones/${zoneId}`, base);
        else zoneId = (await client.post('/zones', { camera_id: cameraId, ...base })).id;
        try {
          await client.patch(`/zones/${zoneId}`, alerts);
          return '';
        } catch (alertError) {
          return `The zone's outline, name and type were saved, but the server refused the alert rule:\n\n${alertError.message}\n\nThis usually means backend/app/schemas/zone.py on the server is older than this page. Replace it with the latest one, restart the server, then use Edit zone to choose the alert rule again.`;
        }
      }
    },
    patchZone: (zoneId, patch) => client.patch(`/zones/${zoneId}`, patch),
    deleteZone: (_cameraId, zoneId) => client.del(`/zones/${zoneId}`),
  };
}

function asEditorZone(zone) {
  return { ...zone, polygon: (zone.polygon || []).map((point) => Array.isArray(point)
    ? { x: point[0], y: point[1] } : point) };
}

function zoneKey(name) {
  const key = String(name || 'zone').trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40);
  return key || `zone-${Date.now().toString(36)}`;
}

export function buildRegistryAdapter(client, useCase) {
  const useCaseId = useCase.replaceAll('-', '_');
  return {
    id: useCase,
    enabled: true,
    listUseCases: () => client.get('/use-cases'),
    listLocations: () => client.get(`/locations?use_case=${encodeURIComponent(useCaseId)}`),
    listCameras: (locationId = '') => client.get(`/cameras?use_case=${encodeURIComponent(useCaseId)}${locationId ? `&location_id=${encodeURIComponent(locationId)}` : ''}`),
    listAssignments: (locationId = '') => client.get(`/assignments?use_case=${encodeURIComponent(useCaseId)}${locationId ? `&location_id=${encodeURIComponent(locationId)}` : ''}`),
    loadZones: async (assignmentId) => (await client.get(`/assignments/${encodeURIComponent(assignmentId)}/zones`)).map(asEditorZone),
    saveZone: async (assignmentId, editing, body, polygon) => {
      const common = {
        name: body.name,
        polygon: polygon.map(({ x, y }) => [x, y]),
        reference: body.reference || 'bottom_center',
        enabled: body.enabled ?? true,
      };
      if (useCase !== 'vault-room') {
        common.coordinate_system = 'normalized_raw';
        common.zone_type = body.zone_type;
        common.description = body.description || '';
        common.properties = body.properties ?? null;
      }
      if (editing) {
        await client.patch(`/assignments/${encodeURIComponent(assignmentId)}/zones/${encodeURIComponent(editing.id)}`, common);
      } else {
        await client.post(`/assignments/${encodeURIComponent(assignmentId)}/zones`, {
          ...common, zone_key: zoneKey(body.zone_key || body.name),
        });
      }
      return '';
    },
    patchZone: (assignmentId, zoneId, patch) => client.patch(`/assignments/${encodeURIComponent(assignmentId)}/zones/${encodeURIComponent(zoneId)}`, patch),
    deleteZone: (assignmentId, zoneId) => client.del(`/assignments/${encodeURIComponent(assignmentId)}/zones/${encodeURIComponent(zoneId)}`),
  };
}

export const vaultRegionsAdapter = buildRegistryAdapter(regionsRegistryApi, 'vault-room');
export const grillRegionsAdapter = buildRegistryAdapter(regionsRegistryApi, 'grill-gate');

export const branchRegionsAdapter = buildBranchAdapter(api);

// The legacy Branch editor remains Branch-only; the common page calls the other adapters directly.
export const REGIONS_ADAPTERS = [
  branchRegionsAdapter,
  { ...vaultRegionsAdapter, label: 'Vault Room Monitoring', enabled: false },
  { ...grillRegionsAdapter, label: 'Grill Gate Monitoring', enabled: false },
];
