export const SCOPE_KEY = 'fedbank.activeScope.v1';
export const SELECTION_KEY = 'fedbank.hierarchySelection.v1';

export function readStored(key, storage = globalThis.localStorage) {
  try { return JSON.parse(storage.getItem(key) || 'null'); } catch { return null; }
}

export function validSelection(value) {
  return value && typeof value === 'object' && ['zone', 'city', 'branch'].every((key) => !value[key] || typeof value[key] === 'string');
}

export function selectionFromSearch(search, storage = globalThis.localStorage) {
  const params = new URLSearchParams(search);
  if (params.has('all')) return params;
  if (['zone', 'city', 'branch'].some((key) => params.has(key))) return params;
  const saved = readStored(SELECTION_KEY, storage);
  if (!validSelection(saved)) return params;
  for (const key of ['zone', 'city', 'branch']) if (saved[key]) params.set(key, saved[key]);
  return params;
}

export function persistSelection(params, storage = globalThis.localStorage) {
  if (params.has('all')) { storage.removeItem(SELECTION_KEY); return; }
  storage.setItem(SELECTION_KEY, JSON.stringify(Object.fromEntries(['zone', 'city', 'branch'].map((key) => [key, params.get(key) || '']))));
}

export function sameScope(scope, type, id) {
  return scope ? scope.type === type && (scope.id === id || (type === 'branch' && scope.code === id)) : !type;
}
