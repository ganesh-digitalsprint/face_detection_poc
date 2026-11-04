import assert from 'node:assert/strict';
import test from 'node:test';
import { buildCombinedCsv, trimBranchCsv } from './briefExport.js';
import {
  branchBriefParams, branchCsvParams, DEFAULT_FILTERS, describeFilters, faceMaskParams, includesUseCase, resolveRange,
} from './briefFilters.js';
import { parseCsv, toCsv } from '../../utils/csv.js';

const NOW = new Date('2026-11-04T12:00:00Z');
const f = (over) => ({ ...DEFAULT_FILTERS, ...over });

test('resolveRange: presets look back from now; All time is open ended', () => {
  assert.equal(resolveRange(f({ period: '7d' }), NOW).hours, 168);
  assert.equal(resolveRange(f({ period: 'all' }), NOW).since, null);
});

test('resolveRange: custom range validates order', () => {
  const bad = resolveRange(f({ period: 'custom', from: '2026-11-03T10:00', to: '2026-11-02T10:00' }), NOW);
  assert.match(bad.error, /before/);
});

test('Branch brief params cap at 720 hours and say so; filters pass through', () => {
  const all = branchBriefParams(f({ period: 'all' }), NOW);
  assert.equal(all.params.hours, 720);
  assert.equal(all.capped, true);
  const one = branchBriefParams(f({ camera: 'branch_exterior:c1', status: 'open' }), NOW);
  assert.deepEqual(one.params, { hours: 24, camera_id: 'c1', status: 'open' });
});

test('a camera of another use case does not leak into this service query', () => {
  assert.equal(branchCsvParams(f({ camera: 'face_mask:x' }), NOW).camera_id, undefined);
  assert.equal(faceMaskParams(f({ camera: 'branch_exterior:y' }), NOW).camera_id, undefined);
  assert.equal(includesUseCase(f({ camera: 'face_mask:x' }), 'branch_exterior'), false);
});

test('Face Mask params: status upper-cased, covering only for Face Mask or All', () => {
  assert.equal(faceMaskParams(f({ status: 'under_review', covering: 'helmet' }), NOW).status, 'UNDER_REVIEW');
  assert.equal(faceMaskParams(f({ useCase: 'face_mask', covering: 'helmet' }), NOW).covering_type, 'helmet');
  assert.equal(faceMaskParams(f({ useCase: 'branch_exterior', covering: 'helmet' }), NOW).covering_type, undefined);
});

test('describeFilters prints what was applied', () => {
  assert.match(describeFilters(f({ useCase: 'face_mask', status: 'confirmed' })), /Face Mask.*Last 24 hours.*confirmed/);
});

test('CSV round trip keeps quotes, commas and newlines', () => {
  const rows = [['a', 'b'], ['x,y', 'say "hi"\nnow']];
  assert.deepEqual(parseCsv(toCsv(rows)), rows);
});

test('combined CSV merges services, names skipped ones and neutralises formulas', () => {
  const fm = 'event_id,first_seen_utc,last_seen_utc,camera_id,camera_name,roi_name,track_id,status,score,covering_type,frames_evaluated,clip_status,reviewer,remarks,reviewed_at_utc\r\ne1,2026-11-04T10:00:00Z,,c,Gate,Grill,3,OPEN,0.900,helmet,9,ready,,=cmd(),\r\n';
  const out = buildCombinedCsv({ face_mask: fm }, { skipped: [{ label: 'Branch Exterior', reason: 'service unavailable' }], filtersText: 'Use case: All' });
  assert.match(out, /^# Filters: Use case: All\r\n# Skipped Branch Exterior: service unavailable\r\nuse_case,/);
  assert.match(out, /face_mask,e1,2026-11-04T10:00:00Z,Gate,Grill,3,helmet,0.900,,OPEN,,'=cmd\(\),/);
});

test('trimBranchCsv drops rows after the end of the range', () => {
  const csv = 'id,created_at\r\na,2026-11-01T00:00:00Z\r\nb,2026-11-03T00:00:00Z\r\n';
  const out = parseCsv(trimBranchCsv(csv, new Date('2026-11-02T00:00:00Z')));
  assert.deepEqual(out.map((r) => r[0]), ['id', 'a']);
});
