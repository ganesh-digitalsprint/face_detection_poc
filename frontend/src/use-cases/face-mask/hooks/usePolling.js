import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Load `fetcher()` now and every `intervalMs` (0 = once). Returns { data, error, loading, reload }.
 * `error` is kept until the next success, and the previous `data` stays visible during a refresh,
 * so a slow or failed poll never blanks a page.
 * @param {() => Promise<any>} fetcher
 * @param {number} intervalMs
 * @param {any[]} deps re-run (and show loading) when these change
 */
export default function usePolling(fetcher, intervalMs = 0, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const load = useCallback(async () => {
    try {
      const data = await fetcherRef.current();
      setState({ data, error: null, loading: false });
    } catch (error) {
      setState((s) => ({ data: s.data, error, loading: false }));
    }
  }, []);

  useEffect(() => {
    let alive = true;
    setState((s) => ({ ...s, loading: true }));
    const run = () => { if (alive) load(); };
    run();
    const id = intervalMs > 0 ? setInterval(run, intervalMs) : null;
    return () => { alive = false; if (id) clearInterval(id); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load, intervalMs, ...deps]);

  return { ...state, reload: load };
}
