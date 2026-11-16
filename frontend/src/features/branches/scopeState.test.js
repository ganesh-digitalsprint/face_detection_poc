import test from 'node:test';
import assert from 'node:assert/strict';
import { persistSelection, readStored, sameScope, selectionFromSearch, SELECTION_KEY } from './scopeState.js';

function storage() {
  const values = new Map();
  return { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key) };
}

test('hierarchy selection survives a page reload without query parameters', () => {
  const local = storage();
  persistSelection(new URLSearchParams('zone=z1&city=c1&branch=b1'), local);
  assert.equal(selectionFromSearch('', local).toString(), 'zone=z1&city=c1&branch=b1');
  assert.deepEqual(readStored(SELECTION_KEY, local), { zone: 'z1', city: 'c1', branch: 'b1' });
});

test('URL deep link takes precedence over stored selection and explicit all clears it', () => {
  const local = storage();
  persistSelection(new URLSearchParams('zone=z1&city=c1'), local);
  assert.equal(selectionFromSearch('?zone=z2', local).get('zone'), 'z2');
  assert.equal(selectionFromSearch('?all=1', local).get('zone'), null);
  persistSelection(new URLSearchParams('all=1'), local);
  assert.equal(readStored(SELECTION_KEY, local), null);
});

test('active scope compares stable branch code when available', () => {
  assert.equal(sameScope({ type: 'branch', id: 'old-id', code: 'C99127-01' }, 'branch', 'C99127-01'), true);
  assert.equal(sameScope({ type: 'branch', id: 'old-id', code: 'C99127-01' }, 'branch', 'other'), false);
});
