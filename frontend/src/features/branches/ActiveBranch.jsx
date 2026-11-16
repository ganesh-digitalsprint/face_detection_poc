import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { PLATFORM_BASE_URL } from '../../config/services.js';
import { readStored, SCOPE_KEY } from './scopeState.js';

const Context = createContext(null);

export function ActiveBranchProvider({ children }) {
  const [scope, setScope] = useState(() => {
    const value = readStored(SCOPE_KEY);
    return value && ['zone', 'city', 'branch'].includes(value.type) && (value.id || value.code) ? value : null;
  });
  const [reconnecting, setReconnecting] = useState(Boolean(scope));
  const [notice, setNotice] = useState('');
  useEffect(() => {
    if (!scope) { localStorage.removeItem(SCOPE_KEY); return; }
    localStorage.setItem(SCOPE_KEY, JSON.stringify(scope));
  }, [scope]);
  useEffect(() => {
    if (!scope) { setReconnecting(false); return undefined; }
    let live = true;
    let timer;
    let attempts = 0;
    const validate = async () => {
      try {
        if (scope.type === 'branch') {
          const response = await fetch(`${PLATFORM_BASE_URL}/branches/${encodeURIComponent(scope.id || scope.code)}`);
          if (!response.ok && response.status !== 404) throw new Error('Platform unavailable');
          let branch = response.ok ? await response.json() : null;
          let cityName = '';
          if (scope.code) {
            const lookup = await fetch(`${PLATFORM_BASE_URL}/branches/search?query=${encodeURIComponent(scope.code)}&limit=100`);
            if (!lookup.ok) throw new Error('Platform unavailable');
            const match = (await lookup.json()).find((entry) => entry.code === scope.code);
            if (match) { branch = match; cityName = match.city_name; }
          }
          if (!branch && response.status === 404) {
            if (live) { setScope(null); setNotice('The active branch no longer exists; showing all branches.'); }
            return;
          }
          if (branch && live) setScope((old) => old && old.type === 'branch' && (old.id === branch.id || old.code === branch.code)
            ? { ...old, id: branch.id, code: branch.code, name: branch.name, subtitle: `${branch.code}${cityName ? ` · ${cityName}` : ''}` } : old);
        } else {
          const zonesResponse = await fetch(`${PLATFORM_BASE_URL}/zones`);
          if (!zonesResponse.ok) throw new Error('Platform unavailable');
          const zones = await zonesResponse.json();
          if (scope.type === 'zone') {
            const found = zones.find((zone) => zone.id === scope.id);
            if (found && live) setScope((old) => old?.id === found.id ? { ...old, name: found.name } : old);
          } else {
            for (const zone of zones) {
              const response = await fetch(`${PLATFORM_BASE_URL}/cities?zone_id=${encodeURIComponent(zone.id)}`);
              if (!response.ok) throw new Error('Platform unavailable');
              const found = (await response.json()).find((city) => city.id === scope.id);
              if (found && live) { setScope((old) => old?.id === found.id ? { ...old, name: found.name, subtitle: zone.name } : old); break; }
            }
          }
        }
        if (live) { setReconnecting(false); attempts = 0; timer = setTimeout(validate, 30000); }
      } catch {
        if (live) { setReconnecting(true); timer = setTimeout(validate, Math.min(30000, 1000 * 2 ** attempts)); attempts += 1; }
      }
    };
    validate();
    return () => { live = false; clearTimeout(timer); };
  }, [scope?.id, scope?.type]);
  const value = useMemo(() => ({ scope, setScope, reconnecting, notice, clearNotice: () => setNotice('') }), [scope, reconnecting, notice]);
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
