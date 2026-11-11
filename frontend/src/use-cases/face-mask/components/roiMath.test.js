import assert from 'node:assert/strict';
import test from 'node:test';
import {
  arrowToVector, centroid, describeDirection, isNear, isValidPolygon, toNormalised, vectorToArrow,
} from './roiMath.js';

const rect = { left: 100, top: 50, width: 400, height: 200 };

test('toNormalised maps CSS pixels to 0..1 and clamps outside the image', () => {
  assert.deepEqual(toNormalised(300, 150, rect), { x: 0.5, y: 0.5 });
  assert.deepEqual(toNormalised(50, 400, rect), { x: 0, y: 1 });
});

test('isNear measures in pixels, not in normalised units', () => {
  const size = { width: 400, height: 200 };
  assert.equal(isNear({ x: 0.5, y: 0.5 }, { x: 0.52, y: 0.5 }, size), true);   // 8 px
  assert.equal(isNear({ x: 0.5, y: 0.5 }, { x: 0.6, y: 0.5 }, size), false);   // 40 px
});

test('arrowToVector straight up is (0,-1) whatever the aspect ratio', () => {
  assert.deepEqual(arrowToVector({ x1: 0.5, y1: 0.8, x2: 0.5, y2: 0.4 }, 4 / 3), { x: 0, y: -1 });
});

test('arrowToVector keeps the pixel-space angle on a non-square picture', () => {
  // Equal normalised dx and dy on a 2:1 picture is NOT 45 degrees in pixels: dx covers twice the pixels.
  const v = arrowToVector({ x1: 0.2, y1: 0.2, x2: 0.4, y2: 0.4 }, 2);
  assert.ok(Math.abs(v.x - 0.8944) < 1e-3 && Math.abs(v.y - 0.4472) < 1e-3);
});

test('arrowToVector rejects a zero-length arrow and a missing one', () => {
  assert.equal(arrowToVector({ x1: 0.3, y1: 0.3, x2: 0.3, y2: 0.3 }, 1.5), null);
  assert.equal(arrowToVector(null, 1.5), null);
});

test('vectorToArrow is the inverse of arrowToVector', () => {
  const aspect = 16 / 9;
  const original = { x1: 0.5, y1: 0.7, x2: 0.62, y2: 0.45 };
  const vector = arrowToVector(original, aspect);
  const back = vectorToArrow({ x: 0.5, y: 0.7 }, vector, aspect, Math.hypot((original.x2 - original.x1) * aspect, original.y2 - original.y1));
  assert.ok(Math.abs(back.x2 - original.x2) < 1e-3 && Math.abs(back.y2 - original.y2) < 1e-3);
});

test('centroid and isValidPolygon', () => {
  const square = [{ x: 0.2, y: 0.2 }, { x: 0.8, y: 0.2 }, { x: 0.8, y: 0.8 }, { x: 0.2, y: 0.8 }];
  assert.deepEqual(centroid(square), { x: 0.5, y: 0.5 });
  assert.equal(isValidPolygon(square), true);
  assert.equal(isValidPolygon(square.slice(0, 2)), false);
  assert.equal(isValidPolygon([{ x: 0.1, y: 0.1 }, { x: 0.1, y: 0.1 }, { x: 0.1, y: 0.1 }]), false);
  assert.equal(isValidPolygon([{ x: 2, y: 0.1 }, { x: 0.5, y: 0.2 }, { x: 0.3, y: 0.9 }]), false);
  assert.equal(isValidPolygon([{ x: NaN, y: 0.1 }, { x: 0.5, y: 0.2 }, { x: 0.3, y: 0.9 }]), false);
});

test('describeDirection', () => {
  assert.equal(describeDirection({ x: 0, y: -1 }), 'up');
  assert.equal(describeDirection({ x: 1, y: 0 }), 'right');
  assert.equal(describeDirection({ x: -0.7, y: 0.7 }), 'down-left');
});
