import assert from 'node:assert/strict';
import test from 'node:test';
import { countLabel } from './countLabel.js';

test('branch hierarchy count labels handle irregular and regular plurals', () => {
  assert.equal(countLabel(0, 'city'), '0 cities');
  assert.equal(countLabel(1, 'city'), '1 city');
  assert.equal(countLabel(3, 'city'), '3 cities');
  assert.equal(countLabel(0, 'branch'), '0 branches');
  assert.equal(countLabel(1, 'branch'), '1 branch');
  assert.equal(countLabel(2, 'camera'), '2 cameras');
  assert.equal(countLabel(1, 'alert'), '1 alert');
});
