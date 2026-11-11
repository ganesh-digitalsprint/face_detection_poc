import { combineReducers, configureStore } from '@reduxjs/toolkit';
import { FLUSH, PAUSE, PERSIST, PURGE, REGISTER, REHYDRATE, createTransform, persistReducer, persistStore } from 'redux-persist';
import storageModule from 'redux-persist/lib/storage/index.js';
import gateMonitoringReducer, { initialGateMonitoringState } from './slices/gateMonitoringSlice.js';

const persistedFields = ['sessionId', 'gateState', 'lastValidProgress', 'lastUpdatedAt', 'direction', 'transitions'];
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
