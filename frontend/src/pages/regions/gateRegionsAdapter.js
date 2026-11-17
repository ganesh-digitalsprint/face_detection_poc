import * as gate from '../../use-cases/grill-gate/api/grillGate.js';

export function fromGateZone(zone, assignment, camera) {
  return {
    id: zone.id, use_case: 'grill_gate', source_kind: 'live', assignment_id: assignment.id,
    camera_id: assignment.camera_id, camera: camera?.name || assignment.camera_id,
    name: zone.name, zone_type: zone.zone_type, zone_type_label: zone.zone_type_label,
    points: (zone.polygon || []).length, enabled: zone.enabled !== false, direction: false,
  };
}

export function fromGateVideoZone(zone, job) {
  return {
    id: zone.id || zone.zone_key, use_case: 'grill_gate', source_kind: 'video', job_id: job.job_id,
    camera_id: job.job_id, camera: job.filename, name: zone.name, zone_type: zone.zone_type,
    points: (zone.polygon || []).length, enabled: zone.enabled !== false, direction: false,
  };
}

export async function listAllGateJobs(api = gate) {
  const jobs = [];
  for (let offset = 0; ; offset += 100) {
    const page = await api.listGrillGateVideoJobs({ limit: 100, offset });
    const batch = page.items || [];
    jobs.push(...batch);
    if (batch.length < 100 || (page.total != null && jobs.length >= page.total)) break;
  }
  return jobs;
}

// Uses Gate's existing stores. One failed source is reported without dropping healthy rows.
export async function loadGateZoneRows(api = gate) {
  const [assignmentsResult, camerasResult, jobsResult] = await Promise.allSettled([
    api.listGrillGateAssignments(), api.listGrillGateCameras(), listAllGateJobs(api),
  ]);
  if (assignmentsResult.status === 'rejected' && jobsResult.status === 'rejected') throw assignmentsResult.reason;
  const assignments = assignmentsResult.status === 'fulfilled' ? assignmentsResult.value : [];
  const cameras = camerasResult.status === 'fulfilled' ? camerasResult.value : [];
  const jobs = jobsResult.status === 'fulfilled' ? jobsResult.value : [];
  const cameraById = new Map(cameras.map((camera) => [camera.id, camera]));
  const [live, video] = await Promise.all([
    Promise.allSettled(assignments.map((assignment) => api.listAssignmentZones(assignment.id))),
    Promise.allSettled(jobs.map((job) => api.getVideoJobConfig(job.job_id))),
  ]);
  const failures = [assignmentsResult, camerasResult, jobsResult, ...live, ...video].filter((result) => result.status === 'rejected');
  return {
    rows: [
      ...live.flatMap((result, index) => result.status === 'fulfilled'
        ? result.value.map((zone) => fromGateZone(zone, assignments[index], cameraById.get(assignments[index].camera_id))) : []),
      ...video.flatMap((result, index) => result.status === 'fulfilled'
        ? (result.value.zones || []).map((zone) => fromGateVideoZone(zone, jobs[index])) : []),
    ],
    partialError: failures.length ? `${failures.length} Gate source configuration(s) could not be loaded.` : '',
  };
}

export const createGateZoneWrites = (api = gate) => ({
  create: api.createAssignmentZone,
  update: api.updateAssignmentZone,
  remove: api.deleteAssignmentZone,
  setEnabled: (assignmentId, zoneId, enabled) => api.updateAssignmentZone(assignmentId, zoneId, { enabled }),
  saveVideo: api.putVideoJobConfig,
});
