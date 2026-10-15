import { useCallback, useState } from 'react';

const STORAGE_KEY = 'livenessTest:overlay';
const DEFAULTS = Object.freeze({ faceBox: true, landmarks: true, labels: true, axes: true });

function read() {
  try {
    const saved = JSON.parse(window.localStorage.getItem(STORAGE_KEY));
    if (!saved || typeof saved !== 'object') return DEFAULTS;
    // Only known boolean flags are accepted from storage.
    return Object.fromEntries(Object.keys(DEFAULTS).map((key) => [
      key, typeof saved[key] === 'boolean' ? saved[key] : DEFAULTS[key],
    ]));
  } catch {
    return DEFAULTS;
  }
}

/** Overlay visibility flags; the only Liveness Test state that is persisted. */
export default function useOverlayToggles() {
  const [toggles, setToggles] = useState(read);
  const setToggle = useCallback((key, value) => {
    setToggles((prev) => {
      const next = { ...prev, [key]: value };
      try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      } catch {
        /* storage unavailable: the choice just isn't remembered */
      }
      return next;
    });
  }, []);
  return [toggles, setToggle];
}
