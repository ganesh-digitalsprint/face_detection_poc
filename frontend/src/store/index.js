import { combineReducers, configureStore } from '@reduxjs/toolkit';
import { FLUSH, PAUSE, PERSIST, PURGE, REGISTER, REHYDRATE, createTransform, persistReducer, persistStore } from 'redux-persist';
import storageModule from 'redux-persist/lib/storage/index.js';
import gateMonitoringReducer, { initialGateMonitoringState } from './slices/gateMonitoringSlice.js';

const persistedFields = ['sessionId', 'gateState', 'lastValidProgress', 'lastUpdatedAt', 'direction', 'transitions',
  'videoTimestampSeconds', 'videoProcessingStatus', 'videoGateOpenStoppedSeconds', 'sessions', 'alertRequests', 'lastEntryCount', 'lastExitCount', 'gateOpenedAt', 'cycleStartedAt', 'timerTimebase', 'lastCrossingAt', 'lastCrossingId', 'seenCrossingIds'];
const storage = storageModule.default ?? storageModule;
export const projectPersistedGateMonitoring = (state) => Object.fromEntries(
  persistedFields.map((key) => [key, state?.[key] ?? (key === 'transitions' ? [] : null)]),
);

export const restorePersistedGateMonitoring = (saved) => {
  const state = initialGateMonitoringState(saved?.sessionId ?? null);
  if (['CLOSED', 'PARTIALLY_OPEN', 'FULLY_OPEN'].includes(saved?.gateState)) state.gateState = saved.gateState;
  if (typeof saved?.lastValidProgress === 'number' && Number.isFinite(saved.lastValidProgress)
      && saved.lastValidProgress >= 0 && saved.lastValidProgress <= 1) state.lastValidProgress = saved.lastValidProgress;
  if (typeof saved?.lastUpdatedAt === 'number' || typeof saved?.lastUpdatedAt === 'string') state.lastUpdatedAt = saved.lastUpdatedAt;
  if (saved?.direction === 'OPENING' || saved?.direction === 'CLOSING') state.direction = saved.direction;
  if (Array.isArray(saved?.transitions)) state.transitions = saved.transitions.slice(-100);
  if (Number.isFinite(saved?.gateOpenedAt) && Number.isFinite(saved?.cycleStartedAt)
      && ['wall', 'video'].includes(saved?.timerTimebase)) {
    state.gateOpenedAt = saved.gateOpenedAt;
    state.cycleStartedAt = saved.cycleStartedAt;
    state.timerTimebase = saved.timerTimebase;
  }
  if (Number.isFinite(saved?.lastCrossingAt)) state.lastCrossingAt = saved.lastCrossingAt;
  if (typeof saved?.lastCrossingId === 'string') state.lastCrossingId = saved.lastCrossingId;
  if (Array.isArray(saved?.seenCrossingIds)) state.seenCrossingIds = saved.seenCrossingIds.filter((id) => typeof id === 'string').slice(-200);
  state.videoTimestampSeconds = Number.isFinite(saved?.videoTimestampSeconds) && saved.videoTimestampSeconds >= 0
    ? saved.videoTimestampSeconds : null;
  state.videoProcessingStatus = saved?.videoProcessingStatus ?? null;
  state.videoGateOpenStoppedSeconds = Number.isFinite(saved?.videoGateOpenStoppedSeconds) && saved.videoGateOpenStoppedSeconds >= 0
    ? saved.videoGateOpenStoppedSeconds : null;
  state.sessions = saved?.sessions ?? {};
  state.alertRequests = saved?.alertRequests ?? {};
  state.lastEntryCount = saved?.lastEntryCount ?? null;
  state.lastExitCount = saved?.lastExitCount ?? null;
  return state;
};

const gateMonitoringTransform = createTransform(
  projectPersistedGateMonitoring,
  restorePersistedGateMonitoring,
  { whitelist: ['gateMonitoring'] },
);

const rootReducer = combineReducers({ gateMonitoring: gateMonitoringReducer });
const persistedReducer = persistReducer({
  key: 'grill-gate-monitoring',
  version: 1,
  storage,
  whitelist: ['gateMonitoring'],
  transforms: [gateMonitoringTransform],
}, rootReducer);

export const store = configureStore({
  reducer: persistedReducer,
  middleware: (getDefaultMiddleware) => getDefaultMiddleware({
    serializableCheck: { ignoredActions: [FLUSH, PAUSE, PERSIST, PURGE, REGISTER, REHYDRATE] },
  }),
});
export const persistor = persistStore(store);

/** Remove only the persisted gate-monitoring snapshot, preserving other root persistence data. */
export async function clearPersistedGateMonitoring() {
  const storageKey = 'persist:grill-gate-monitoring';
  const serialized = await storage.getItem(storageKey);
  if (!serialized) return;
  try {
    const persistedRoot = JSON.parse(serialized);
    delete persistedRoot.gateMonitoring;
    await storage.setItem(storageKey, JSON.stringify(persistedRoot));
  } catch {
    // Leave malformed or unavailable persistence untouched; the in-memory Redux reset still applies.
  }
}
