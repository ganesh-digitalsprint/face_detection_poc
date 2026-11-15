const UI_KEY = 'vault-room-ui:v1';
const REPLAY_KEY = 'vault-room-replay:v1';
const views = ['entrance', 'room', 'zones'];
const sources = ['webcam', 'rtsp', 'upload'];
const scopes = ['active', 'history', 'events'];
const identifier = (value) => typeof value === 'string' && /^[a-zA-Z0-9_-]{1,128}$/.test(value);
const read = (key) => { try { return JSON.parse(globalThis.localStorage.getItem(key)); } catch { return null; } };
const write = (key, value) => { try { globalThis.localStorage.setItem(key, JSON.stringify(value)); } catch { /* Optional browser storage. */ } };

export function readVaultUi() {
  const saved = read(UI_KEY);
  return { view: views.includes(saved?.view) ? saved.view : 'entrance',
    source: sources.includes(saved?.source) ? saved.source : 'webcam',
    scope: scopes.includes(saved?.scope) ? saved.scope : 'active' };
}
export function saveVaultUi(patch) {
  const next = { ...readVaultUi(), ...patch };
  write(UI_KEY, { view: views.includes(next.view) ? next.view : 'entrance',
    source: sources.includes(next.source) ? next.source : 'webcam', scope: scopes.includes(next.scope) ? next.scope : 'active' });
}
export function vaultUiFromSearch(search, saved = readVaultUi()) {
  const params = new URLSearchParams(search);
  return { ...saved, view: views.includes(params.get('view')) ? params.get('view') : saved.view,
    source: sources.includes(params.get('source')) ? params.get('source') : saved.source };
}
export function readReplayContext() {
  const saved = read(REPLAY_KEY);
  if (saved?.version !== 1 || !identifier(saved.sessionId) || !identifier(saved.sourceId) || !identifier(saved.profileId)) return null;
  return { sessionId: saved.sessionId, sourceId: saved.sourceId, profileId: saved.profileId };
}
export function saveReplayContext(context) {
  if (!identifier(context.sessionId) || !identifier(context.sourceId) || !identifier(context.profileId)) return;
  write(REPLAY_KEY, { version: 1, sessionId: context.sessionId, sourceId: context.sourceId, profileId: context.profileId });
}
export function restoredReplay(context) {
  return context ? { session_id: context.sessionId, source_id: context.sourceId, status: 'restoring',
    metadata: null, state: {}, events: [], alerts: [], frame_sequence: 0,
    current_time: 0, processed_frames: 0, progress: 0, finalized: true } : null;
}
