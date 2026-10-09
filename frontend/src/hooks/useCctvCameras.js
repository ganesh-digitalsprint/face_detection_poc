import { useEffect, useState } from 'react';
import { listCCTVCameras } from '../api/streams.js';
import { describeError } from '../utils/errors.js';

/** Loads the configured CCTV cameras once. */
export default function useCctvCameras(enabled) {
  const [state, setState] = useState({ cameras: null, error: null });

  useEffect(() => {
    if (!enabled || state.cameras) return undefined;
    let cancelled = false;
    listCCTVCameras()
      .then((cameras) => !cancelled && setState({ cameras, error: null }))
      .catch((err) => !cancelled && setState({ cameras: null, error: describeError(err).message }));
    return () => { cancelled = true; };
  }, [enabled, state.cameras]);

  return { ...state, loading: enabled && !state.cameras && !state.error };
}
