import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizePolygon, polygonError, segmentsIntersect, prepareZonePolygons,
  isPolygonClosingClick, zoneValidationMessage, zoneValidationIndex, validatedZoneConfiguration } from './zonePolygons.js';
import { buildRegistryAdapter } from '../use-cases/branch-exterior/regionsAdapters.js';

const square = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]];
const mesh = [[0.0497, 0.8337], [0.1681, 0.8059], [0.3091, 0.9947], [0.0946, 0.9971], [0.0497, 0.8313]];
const frame = { width: 1920, height: 1080 };

test('CSS-pixel completion detects a near-first click without changing original vertices', () => {
  const original = structuredClone(square);
  assert.equal(isPolygonClosingClick(square, [0.105, 0.1], { width: 1000, height: 500 }), true);
  assert.equal(isPolygonClosingClick(square, [0.12, 0.1], { width: 1000, height: 500 }), false);
  assert.equal(isPolygonClosingClick(square.slice(0, 2), square[0], frame), false);
  assert.deepEqual(square, original);
  assert.equal(square.length, 4);
});

test('exact closing and consecutive duplicate points normalize without reordering', () => {
  assert.deepEqual(normalizePolygon([...square, square[0]]), square);
  assert.deepEqual(normalizePolygon([square[0], square[0], ...square.slice(1), square[0]]), square);
  assert.deepEqual(normalizePolygon(square.map(([x, y]) => ({ x, y }))), square);
});

test('provided Mesh polygon is reduced only after validating a redundant small crossing tail', () => {
  assert.match(polygonError(mesh), /intersect/);
  const cleaned = normalizePolygon(mesh, frame);
  assert.deepEqual(cleaned, mesh.slice(0, -1));
  assert.equal(polygonError(cleaned), '');
  assert.equal(mesh.length, 5, 'saved editor input remains available');
  assert.equal(normalizePolygon(mesh).length, 5, 'no resolution means no guessed near-point deletion');
  assert.equal(normalizePolygon(mesh, { width: 3840, height: 2160 }).length, 5,
    'native-pixel tolerance does not grow with frame resolution');
});

test('legitimate close corners and valid concave polygons are preserved', () => {
  const close = [...square, [0.1001, 0.1001]];
  assert.equal(polygonError(close), '');
  assert.deepEqual(normalizePolygon(close, frame), close);
  assert.equal(polygonError([[0.1, 0.1], [0.9, 0.1], [0.5, 0.5], [0.9, 0.9], [0.1, 0.9]]), '');
});

test('genuine crossings, repeated vertices, collinear overlaps, and degenerate polygons are rejected', () => {
  const invalid = [
    [[0.1, 0.1], [0.9, 0.9], [0.9, 0.1], [0.1, 0.9]],
    [...square, square[1]],
    [[0.1, 0.1], [0.9, 0.1], [0.5, 0.1], [0.5, 0.9], [0.1, 0.9]],
    [[0.1, 0.1], [0.2, 0.2], [0.3, 0.3]],
    [[0.1, 0.1], [0.1, 0.1], [0.5, 0.9]],
    [[0.1, 0.1], [0.1001, 0.1], [0.1, 0.1001]],
  ];
  for (const polygon of invalid) assert.ok(polygonError(polygon));
  const bowtie = invalid[0];
  assert.deepEqual(normalizePolygon(bowtie, frame), bowtie);
});

test('segment intersections include endpoint touches and collinear overlap', () => {
  assert.equal(segmentsIntersect([0, 0], [1, 0], [0.5, 0], [0.8, 0]), true);
  assert.equal(segmentsIntersect([0, 0], [1, 0], [1, 0], [1, 1]), true);
  assert.equal(segmentsIntersect([0, 0], [0.2, 0], [0.3, 0], [1, 0]), false);
  assert.equal(polygonError(square), '', 'adjacent intended endpoints remain valid');
});

test('non-finite, malformed, out-of-range, and precision-collapsed coordinates are blocked', () => {
  for (const vertex of [[NaN, 0.1], [Infinity, 0.1], [-0.1, 0.1], [1.1, 0.1], ['0.1', 0.1], [0.1, 0.1, 0.3]]) {
    assert.ok(polygonError([vertex, ...square.slice(1)]));
    assert.throws(() => prepareZonePolygons([{ name: 'Bad corner', polygon: [vertex, ...square.slice(1)] }]));
  }
});

test('complete configurations validate independently, identify bad zone, and preserve every draft', () => {
  const zones = [{ id: 'ok', name: 'Door', polygon: square },
    { id: 'bad', name: 'Mesh gathering area', polygon: [[0, 0], [1, 1], [1, 0], [0, 1]] }];
  const before = structuredClone(zones);
  assert.throws(() => prepareZonePolygons(zones, frame), (e) => {
    assert.match(e.message, /^Mesh gathering area: Polygon edges intersect/);
    assert.equal(e.zoneIndex, 1); assert.equal(e.zoneId, 'bad'); return true;
  });
  assert.deepEqual(zones, before);
});

test('Pydantic location maps zones[3] to its name and selected outline', () => {
  const zones = [{}, {}, {}, { id: 'mesh', name: 'Mesh gathering area' }];
  const error = { response: { data: { detail: [{ loc: ['body', 'zones', 3, 'polygon'],
    msg: 'Value error, The zone outline crosses itself; click the corners in order' }] } } };
  assert.equal(zoneValidationMessage(error, zones),
    'Mesh gathering area: The zone outline crosses itself; click the corners in order');
  assert.equal(zoneValidationIndex(error), 3);
});

test('configuration save guard safely normalizes existing Mesh data with frame metadata', () => {
  const original = { calibration: { reference_frame: frame, gate_roi_zone_key: 'gate_leaf_roi' },
    zones: [{ name: 'Gate', zone_key: 'gate_leaf_roi_mwc7nojd', zone_type: 'gate_leaf_roi', polygon: square },
      { name: 'Mesh gathering area', polygon: mesh }] };
  const normalized = validatedZoneConfiguration(original);
  assert.deepEqual(normalized.zones[1].polygon, mesh.slice(0, -1));
  assert.equal(original.zones[1].polygon.length, 5);
  assert.equal(normalized.calibration.gate_roi_zone_key, 'gate_leaf_roi', 'logical type contract is unchanged');
  assert.equal(normalized.zones[0].zone_key, 'gate_leaf_roi_mwc7nojd');
});

test('all common registry use cases reject invalid saves before making an API request', async () => {
  for (const useCase of ['vault-room', 'grill-gate', 'other-monitoring']) {
    const calls = [];
    const client = { post: async (...args) => calls.push(args), patch: async (...args) => calls.push(args) };
    const adapter = buildRegistryAdapter(client, useCase);
    await assert.rejects(adapter.saveZone('assignment', null, { name: 'Mesh gathering area' },
      [[0, 0], [1, 1], [1, 0], [0, 1]].map(([x, y]) => ({ x, y }))), /Mesh gathering area: Polygon edges intersect/);
    assert.equal(calls.length, 0);
    await adapter.saveZone('assignment', null, { name: 'Mesh gathering area' }, mesh.map(([x, y]) => ({ x, y })), frame);
    assert.equal(calls.length, 1);
    assert.equal(calls[0][1].polygon.length, 4);
  }
});
