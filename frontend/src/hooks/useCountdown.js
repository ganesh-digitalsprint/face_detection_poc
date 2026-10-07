import { useEffect, useRef, useState } from 'react';
import { secondsRemaining } from '../utils/dualControl.js';

const TICK_MS = 250;

/**
 * Whole seconds left until the backend-provided `expiresAt`, recomputed from the wall clock on
 * every tick (no accumulated drift). The interval lives only while `active` and is cleared on
 * every change of session, so an old timer can never touch a new session.
 * `onExpire` fires once when the local clock reaches zero.
 */
export default function useCountdown(expiresAt, active, onExpire) {
  const [tick, setTick] = useState({ key: null, seconds: 0 });
  const onExpireRef = useRef(onExpire);
  onExpireRef.current = onExpire;

  useEffect(() => {
    if (!active || !expiresAt) return undefined;
    const update = () => {
      const seconds = secondsRemaining(expiresAt);
      setTick((prev) => (prev.key === expiresAt && prev.seconds === seconds ? prev : { key: expiresAt, seconds }));
      return seconds;
    };
    const id = setInterval(() => {
      if (update() <= 0) {
        clearInterval(id);
        onExpireRef.current?.();
      }
    }, TICK_MS);
    if (update() <= 0) {
      clearInterval(id);
      onExpireRef.current?.();
    }
    return () => clearInterval(id);
  }, [expiresAt, active]);

  if (!expiresAt) return 0;
  // A stale tick from a previous session is ignored until the new session's first tick.
  return tick.key === expiresAt ? tick.seconds : secondsRemaining(expiresAt);
}
