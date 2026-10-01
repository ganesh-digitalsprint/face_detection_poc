import { useCallback, useRef, useState } from 'react';
import { describeError } from '../utils/errors.js';

/**
 * Wrap an async API call with loading/error/data state.
 * Blocks re-entry while a request is in flight (double-click safe).
 */
export default function useApiAction(fn, errorOverrides = {}) {
  const [state, setState] = useState({ loading: false, error: null, data: null });
  const inFlight = useRef(false);

  const run = useCallback(
    async (...args) => {
      if (inFlight.current) return undefined;
      inFlight.current = true;
      setState({ loading: true, error: null, data: null });
      try {
        const data = await fn(...args);
        setState({ loading: false, error: null, data });
        return data;
      } catch (err) {
        setState({ loading: false, error: describeError(err, errorOverrides), data: null });
        return undefined;
      } finally {
        inFlight.current = false;
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [fn],
  );

  const reset = useCallback(() => setState({ loading: false, error: null, data: null }), []);
  return { ...state, run, reset };
}
