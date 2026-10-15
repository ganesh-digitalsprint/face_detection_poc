import { useCallback, useEffect, useState } from 'react';
import { getTestConfig } from '../api/livenessTest.js';
import { describeError } from '../utils/errors.js';

// One config request shared by the sidebar and the page.
// The app has no user roles, so the backend config call is the only gate:
//   200 -> enabled, 404 -> disabled, anything else -> error (item hidden, page offers Retry).
let cache = null; // { status, config, error } once settled
let pending = null;
const listeners = new Set();

function publish(next) {
  cache = next;
  listeners.forEach((listener) => listener(next));
}

function load() {
  if (pending) return pending;
  pending = getTestConfig()
    .then((config) => publish({ status: 'enabled', config, error: null }))
    .catch((err) => {
      const described = describeError(err);
      publish(described.status === 404
        ? { status: 'disabled', config: null, error: null }
        : { status: 'error', config: null, error: described });
    })
    .finally(() => { pending = null; });
  return pending;
}

const CHECKING = { status: 'checking', config: null, error: null };

/** @returns {{ status: 'checking'|'enabled'|'disabled'|'error', config: object|null, error: object|null, retry: () => void }} */
export default function useLivenessTestFeature() {
  const [state, setState] = useState(cache ?? CHECKING);

  useEffect(() => {
    listeners.add(setState);
    if (!cache) load();
    else setState(cache);
    return () => { listeners.delete(setState); };
  }, []);

  const retry = useCallback(() => {
    publish(CHECKING);
    load();
  }, []);

  return { ...state, retry };
}
