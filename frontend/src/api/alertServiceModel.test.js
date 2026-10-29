import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  availableActions, buildAlertParams, buildLifecycleBody, describeServiceError, isStaleConflict, matchesStatus,
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
