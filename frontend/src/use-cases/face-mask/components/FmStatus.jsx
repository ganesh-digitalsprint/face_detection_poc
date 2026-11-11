import { createContext, useContext, useMemo } from 'react';
import { api, ServiceDownError } from '../api/index.js';
import usePolling from '../hooks/usePolling.js';

/** @typedef {'checking' | 'online' | 'degraded' | 'offline'} FmState */
const FmStatusContext = createContext({ state: 'checking', health: null, online: null, refresh: () => {} });

export const useFmStatus = () => useContext(FmStatusContext);

/**
 * One health poll for the whole Face Mask area (/api/health every 10 s) plus the "Cameras online x / y" count.
 * online: the service answers. degraded: it answers but the database or required model files are not ready.
 * offline: it does not answer. An offline Face Mask never affects the global API chip or any other use case.
 */
export function FmStatusProvider({ children }) {
  const health = usePolling(() => api.get('/health'), 10000);
  const cams = usePolling(async () => (health.error instanceof ServiceDownError ? null : api.get('/cameras/online')), 10000, [health.error]);

  const value = useMemo(() => {
    let state = 'checking';
    if (health.error instanceof ServiceDownError) state = 'offline';
    else if (health.data) state = health.data.status === 'ok' ? 'online' : 'degraded';
    else if (health.error) state = 'degraded';
    return { state, health: health.data, online: cams.data, refresh: health.reload };
  }, [health.data, health.error, health.reload, cams.data]);

  return <FmStatusContext.Provider value={value}>{children}</FmStatusContext.Provider>;
}
