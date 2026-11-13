import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { PLATFORM_BASE_URL } from '../../config/services.js';

const KEY = 'fedbank.activeScope.v1';
const Context = createContext(null);

export function ActiveBranchProvider({ children }) {
  const [scope, setScope] = useState(() => {
    try {
      const value = JSON.parse(localStorage.getItem(KEY) || 'null');
      return value && ['zone', 'city', 'branch'].includes(value.type) && value.id ? value : null;
    } catch { return null; }
  });
  useEffect(() => {
    if (!scope) { localStorage.removeItem(KEY); return; }
    localStorage.setItem(KEY, JSON.stringify(scope));
  }, [scope]);
  useEffect(() => {
    if (!scope) return undefined;
    let live = true;
    const validate = async () => {
      try {
        let exists = false;
        if (scope.type === 'branch') {
          const response = await fetch(`${PLATFORM_BASE_URL}/branches/${encodeURIComponent(scope.id)}`);
          if (!response.ok && response.status !== 404) return;
          exists = response.ok;
        } else {
          const zonesResponse = await fetch(`${PLATFORM_BASE_URL}/zones`);
          if (!zonesResponse.ok) return;
          const zones = await zonesResponse.json();
          if (scope.type === 'zone') exists = zones.some((zone) => zone.id === scope.id);
          else for (const zone of zones) {
            const response = await fetch(`${PLATFORM_BASE_URL}/cities?zone_id=${encodeURIComponent(zone.id)}`);
            if (!response.ok) return;
            if ((await response.json()).some((city) => city.id === scope.id)) { exists = true; break; }
          }
        }
        if (live && !exists) setScope(null);
      } catch { /* Preserve selection while platform is offline. */ }
    };
    validate();
    return () => { live = false; };
  }, [scope?.id, scope?.type]);
  const value = useMemo(() => ({ scope, setScope }), [scope]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useActiveBranch() {
  const value = useContext(Context);
  if (!value) throw new Error('ActiveBranchProvider is missing');
  return value;
}

export function useOptionalActiveBranch() {
  return useContext(Context);
}
