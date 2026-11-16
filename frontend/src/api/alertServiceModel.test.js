import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  alertDetailLocationFields, availableActions, buildAlertParams, buildLifecycleBody, describeServiceError, isStaleConflict, matchesStatus,
  mergeById, normalizeServiceAlert, replaceAlert, useCaseLabel,
} from './alertServiceModel.js';

const raw = (overrides = {}) => ({
  id: 'a-1', use_case: 'branch_exterior', producer: 'branch-exterior-monitoring', source_event_id: 'evt-1',
  source_event_type: 'loitering', category: 'security', severity: 'WARNING', source_severity: 'medium',
  title: 'Loitering at Front Door', summary: 'Person lingering', status: 'OPEN', source_status: 'open',
  occurred_at: '2026-10-28T12:00:00Z', first_seen_at: '2026-10-28T12:00:00Z', last_seen_at: '2026-10-28T12:00:05Z',
  resource_refs: { camera_id: 'cam-1', camera_name: 'Front Door', zone_name: 'ATM' },
  domain_data: { confidence: 0.9 }, occurrence_count: 1, row_version: 3,
  allowed_actions: ['ACKNOWLEDGED', 'DISMISSED', 'RESOLVED'], ...overrides,
});

test('normalizes an Alert Service record, keeping source identity and raw severity', () => {
  const alert = normalizeServiceAlert(raw());
  assert.equal(alert.useCase, 'branch_exterior');
  assert.equal(alert.sourceEventId, 'evt-1');
  assert.equal(alert.severity, 'WARNING');
  assert.equal(alert.sourceSeverity, 'medium');
  assert.equal(alert.cameraName, 'Front Door');
  assert.equal(alert.zoneName, 'ATM');
  assert.equal(alert.rowVersion, 3);
  assert.deepEqual(alert.allowedActions, ['ACKNOWLEDGED', 'DISMISSED', 'RESOLVED']);
});

test('normalizing tolerates missing optional fields', () => {
  const alert = normalizeServiceAlert({ id: 'x', use_case: 'vault_monitoring', status: 'OPEN' });
  assert.equal(alert.cameraId, null);
  assert.equal(alert.sessionRef, null);
  assert.deepEqual(alert.allowedActions, []);
  assert.equal(alert.occurrenceCount, 1);
  assert.equal(alert.branchId, null);
  assert.equal(alert.branchCode, null);
  assert.equal(alert.cameraName, null);
  assert.equal(alert.sourceId, null);
  assert.equal(alert.placeName, null);
  assert.equal(alert.regionName, null);
  assert.equal(alert.branchManager, null);
});

test('normalizes configured Gate branch metadata for the alert detail page', () => {
  const alert = normalizeServiceAlert(raw({ use_case: 'grill_gate', resource_refs: {
    camera_id: 'gate-camera', camera_name: 'Entrance camera', branch_id: 'branch-1',
    branch_code: 'C99127-01', branch_name: 'Koramangala', place_name: 'Bengaluru', region_name: 'South',
    branch_manager: 'Configured manager' } }));
  assert.equal(alert.cameraName, 'Entrance camera');
  assert.equal(alert.branchName, 'Koramangala');
  assert.equal(alert.branchCode, 'C99127-01');
  assert.equal(alert.placeName, 'Bengaluru');
  assert.equal(alert.regionName, 'South');
  assert.equal(alert.branchManager, 'Configured manager');
  assert.deepEqual(Object.fromEntries(alertDetailLocationFields(alert)), {
    'Camera name': 'Entrance camera', 'Camera ID': 'gate-camera', Branch: 'Koramangala', 'Branch code': 'C99127-01', Place: 'Bengaluru',
    Region: 'South', 'Branch manager': 'Configured manager',
  });
});

test('normalizes Vault snapshot metadata for all centralized detail fields', () => {
  const alert = normalizeServiceAlert(raw({ use_case: 'vault_monitoring', resource_refs: {
    camera_id: 'vault-camera', camera_name: 'Vault Room Camera', branch_id: 'branch-1',
    branch_code: 'C99127-01', branch_name: 'Koramangala', place_name: 'Bengaluru', region_name: 'South',
    branch_manager: 'Existing Manager' } }));
  assert.deepEqual(Object.fromEntries(alertDetailLocationFields(alert)), {
    'Camera name': 'Vault Room Camera', 'Camera ID': 'vault-camera', Branch: 'Koramangala', 'Branch code': 'C99127-01', Place: 'Bengaluru',
    Region: 'South', 'Branch manager': 'Existing Manager',
  });
});

test('Branch Exterior place stays geographic while detection zone remains a separate field', () => {
  const alert = normalizeServiceAlert(raw({resource_refs:{camera_id:'legacy-camera',camera_name:'Front',
    branch_id:'branch-1',branch_code:'P001',branch_name:'Central',place_name:'Pune',region_name:'West',
    branch_manager:'A. Manager',zone_name:'Whole scene'}}));
  const fields = Object.fromEntries(alertDetailLocationFields(alert));
  assert.equal(fields.Place, 'Pune');
  assert.equal(fields['Branch code'], 'P001');
  assert.equal(alert.zoneName, 'Whole scene');
  assert.notEqual(fields.Place, alert.zoneName);
});

test('a detection zone is never used as a fabricated geographic place', () => {
  const alert = normalizeServiceAlert(raw({resource_refs:{camera_id:'legacy-camera',zone_name:'Whole scene'}}));
  const fields = Object.fromEntries(alertDetailLocationFields(alert));
  assert.equal(fields.Place, null);
  assert.equal(alert.zoneName, 'Whole scene');
});

test('Branch Exterior preserves the source evidence failure state and diagnostic', () => {
  const alert = normalizeServiceAlert(raw({evidence_status:'FAILED',domain_data:{confidence:0.63,track_ids:[3],
    evidence_status:'FAILED',evidence_unavailable_reason:'snapshot_write_failed'}}));
  assert.equal(alert.evidenceStatus, 'FAILED');
  assert.equal(alert.evidenceUnavailableReason, 'snapshot_write_failed');
  assert.equal(alert.domainData.confidence, 0.63);
  assert.deepEqual(alert.domainData.track_ids, [3]);
});

test('missing Grill Gate branch metadata stays unattributed without fabricated display values', () => {
  const alert = normalizeServiceAlert(raw({ use_case: 'grill_gate', resource_refs: { video_job_id: 'job-1' } }));
  assert.equal(alert.branchId, null);
  assert.equal(alert.cameraId, null);
  assert.deepEqual(Object.fromEntries(alertDetailLocationFields(alert)), {
    'Camera name': undefined, 'Camera ID': undefined, Branch: undefined, 'Branch code': undefined,
    Place: null, Region: undefined, 'Branch manager': undefined,
  });
});

test('normalization retains nested references and detailed Branch subtypes for old and new responses', () => {
  const refs = { branch_id: 'branch', branch_name: 'Known branch', camera_id: 'source-camera',
    camera_name: 'Original camera', source_id: 'source', assignment_id: 'assignment',
    session_ref: 'session', registry_camera_id: 'registry-camera', location_id: 'location' };
  const alert = normalizeServiceAlert(raw({ source_event_type: 'anomaly', title: 'Anomaly at Original camera',
    resource_refs: refs, domain_data: { kind: 'unattended_bag' } }));
  assert.equal(alert.sourceEventType, 'anomaly');
  assert.equal(alert.sourceEventSubtype, 'unattended_bag');
  assert.equal(alert.displayEventType, 'unattended_bag');
  assert.equal(alert.title, 'Unattended bag at Original camera');
  assert.equal(alert.branchId, 'branch');
  assert.equal(alert.branchName, 'Known branch');
  assert.equal(alert.cameraId, 'source-camera');
  assert.equal(alert.registryCameraId, 'registry-camera');
  assert.equal(alert.sessionRef, 'session');
  assert.equal(alert.sourceId, 'source');
  assert.deepEqual(alert.resourceRefs, refs);
  assert.equal(alert.sourceSeverity, 'medium');
  assert.equal(alert.sourceStatus, 'open');
});

test('uploaded Gate references never become fabricated camera IDs', () => {
  const alert = normalizeServiceAlert(raw({ use_case: 'grill_gate', resource_refs: {
    video_job_id: 'job', template_assignment_id: 'template' }, domain_data: { camera_id: 'job' } }));
  assert.equal(alert.videoJobId, 'job');
  assert.equal(alert.templateAssignmentId, 'template');
  assert.equal(alert.cameraId, null);
  assert.equal(alert.branchId, null);
});

test('identifier filters use the same API names as preserved references', () => {
  assert.deepEqual(buildAlertParams({ branchId: 'branch', cameraId: 'camera', assignmentId: 'assignment',
    videoJobId: 'job', sessionRef: 'session', sourceId: 'source', registryCameraId: 'registry', sourceSubtype: 'weapon' }), {
    branch_id: 'branch', camera_id: 'camera', assignment_id: 'assignment', video_job_id: 'job',
    session_ref: 'session', source_id: 'source', registry_camera_id: 'registry', source_event_subtype: 'weapon' });
});

test('useCaseLabel names known sources and falls back to the raw id', () => {
  assert.equal(useCaseLabel('vault_monitoring'), 'Vault Monitoring');
  assert.equal(useCaseLabel('branch_exterior'), 'Branch Exterior');
  assert.equal(useCaseLabel('other_case'), 'other_case');
});

test('buildAlertParams sends only valid, non-empty filters using the contract names', () => {
  const params = buildAlertParams({
    status: 'OPEN', useCase: 'vault_monitoring', severity: 'HIGH', sourceType: ' loitering ',
    from: '2026-10-28T10:00', to: '2026-10-28T11:00', sort: 'oldest', limit: 25, cursor: 'abc',
  });
  assert.equal(params.status, 'OPEN');
  assert.equal(params.use_case, 'vault_monitoring');
  assert.equal(params.severity, 'HIGH');
  assert.equal(params.source_event_type, 'loitering');
  assert.match(params.from, /Z$/);
  assert.match(params.to, /Z$/);
  assert.equal(params.sort, 'oldest');
  assert.equal(params.limit, 25);
  assert.equal(params.cursor, 'abc');
});

test('buildAlertParams drops empty values, unknown enum values and invalid dates', () => {
  assert.deepEqual(buildAlertParams({}), {});
  assert.deepEqual(buildAlertParams({ status: 'bogus', severity: 'catastrophic', from: 'not a date', sourceType: '  ' }), {});
  assert.equal(buildAlertParams({ sort: 'newest' }).sort, undefined);
});

test('availableActions follow the server allowed_actions and the enable flag', () => {
  const open = normalizeServiceAlert(raw());
  assert.deepEqual(availableActions(open, true).map((a) => a.target), ['ACKNOWLEDGED', 'DISMISSED', 'RESOLVED']);
  assert.deepEqual(availableActions(open, false), []);
  const acknowledged = normalizeServiceAlert(raw({ status: 'ACKNOWLEDGED', allowed_actions: ['DISMISSED', 'RESOLVED'] }));
  assert.deepEqual(availableActions(acknowledged, true).map((a) => a.target), ['DISMISSED', 'RESOLVED']);
  const terminal = normalizeServiceAlert(raw({ status: 'RESOLVED', allowed_actions: [] }));
  assert.deepEqual(availableActions(terminal, true), []);
  assert.deepEqual(availableActions(normalizeServiceAlert(raw({ allowed_actions: ['REOPENED'] })), true), []);
});

test('lifecycle body carries the current row version and requires notes for resolve and dismiss', () => {
  const alert = normalizeServiceAlert(raw());
  assert.deepEqual(buildLifecycleBody(alert, 'ACKNOWLEDGED', ''), { expected_version: 3 });
  assert.deepEqual(buildLifecycleBody(alert, 'ACKNOWLEDGED', ' seen '), { expected_version: 3, note: 'seen' });
  assert.deepEqual(buildLifecycleBody(alert, 'RESOLVED', 'fixed'), { expected_version: 3, note: 'fixed' });
  assert.throws(() => buildLifecycleBody(alert, 'RESOLVED', '   '), /requires a note/);
  assert.throws(() => buildLifecycleBody(alert, 'DISMISSED', ''), /requires a note/);
  assert.throws(() => buildLifecycleBody(alert, 'REOPENED', 'x'), /Unsupported/);
});

test('replaceAlert swaps the server copy in place without mutating the list', () => {
  const list = [normalizeServiceAlert(raw({ id: 'a' })), normalizeServiceAlert(raw({ id: 'b' }))];
  const updated = normalizeServiceAlert(raw({ id: 'b', status: 'ACKNOWLEDGED', row_version: 4 }));
  const next = replaceAlert(list, updated);
  assert.equal(next[1].status, 'ACKNOWLEDGED');
  assert.equal(next[1].rowVersion, 4);
  assert.equal(list[1].status, 'OPEN');
  assert.deepEqual(replaceAlert(list, normalizeServiceAlert(raw({ id: 'zzz' }))).map((a) => a.id), ['a', 'b']);
});

test('matchesStatus keeps rows that fit the status filter and drops the rest', () => {
  const acknowledged = normalizeServiceAlert(raw({ status: 'ACKNOWLEDGED' }));
  assert.equal(matchesStatus(acknowledged, ''), true);
  assert.equal(matchesStatus(acknowledged, 'ACKNOWLEDGED'), true);
  assert.equal(matchesStatus(acknowledged, 'OPEN'), false);
});

test('mergeById de-duplicates when paging and replaces the list on a fresh load', () => {
  const a = normalizeServiceAlert(raw({ id: 'a' }));
  const b = normalizeServiceAlert(raw({ id: 'b' }));
  const bNewer = normalizeServiceAlert(raw({ id: 'b', status: 'RESOLVED' }));
  assert.deepEqual(mergeById([a, b], [bNewer], true).map((x) => `${x.id}:${x.status}`), ['a:OPEN', 'b:RESOLVED']);
  assert.deepEqual(mergeById([a, b], [bNewer], false).map((x) => x.id), ['b']);
});

const failure = (status, detail) => ({ response: { status, data: detail === undefined ? undefined : { detail } } });

test('describeServiceError maps unavailable, auth, conflict and validation errors', () => {
  assert.match(describeServiceError({}).message, /unavailable/);
  assert.match(describeServiceError(failure(502)).message, /unavailable/);
  assert.match(describeServiceError(failure(401, { code: 'UNAUTHENTICATED', message: 'x' })).message, /ALERT_SERVICE_OPERATOR_TOKEN/);
  assert.match(describeServiceError(failure(403, { code: 'FORBIDDEN', message: 'x' })).message, /not authorized/);
  assert.match(describeServiceError(failure(503, { code: 'AUTH_NOT_CONFIGURED', message: 'x' })).message, /not configured/);
  assert.match(describeServiceError(failure(409, { code: 'VERSION_CONFLICT', message: 'x' })).message, /changed/);
  assert.match(describeServiceError(failure(409, { code: 'INVALID_TRANSITION', message: 'x' })).message, /not allowed/);
  assert.match(describeServiceError(failure(422, { code: 'NOTE_REQUIRED', message: 'x' })).message, /note is required/);
  assert.equal(describeServiceError(failure(404, { code: 'ALERT_NOT_FOUND', message: 'Alert not found' })).message, 'Alert not found');
  assert.match(describeServiceError(failure(418)).message, /HTTP 418/);
});

test('stale conflicts trigger a reload; other errors do not', () => {
  assert.equal(isStaleConflict(describeServiceError(failure(409, { code: 'VERSION_CONFLICT', message: 'x' }))), true);
  assert.equal(isStaleConflict(describeServiceError(failure(404, { code: 'ALERT_NOT_FOUND', message: 'x' }))), true);
  assert.equal(isStaleConflict(describeServiceError(failure(401, { code: 'UNAUTHENTICATED', message: 'x' }))), false);
});

test('Face Mask alerts have a source label (and so appear in the source filter)', async () => {
  const { USE_CASE_LABELS, useCaseLabel } = await import('./alertServiceModel.js');
  assert.equal(useCaseLabel('face_mask'), 'Face Mask');
  assert.ok(Object.keys(USE_CASE_LABELS).includes('face_mask'));
});
