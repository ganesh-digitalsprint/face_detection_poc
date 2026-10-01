import { useEffect, useState } from 'react';
import { getHealth } from '../api/health.js';

/** Poll the real backend health endpoint. status: checking | ok | degraded | offline */
export default function useHealth(intervalMs = 30000) {
  const [health, setHealth] = useState({ status: 'checking', detail: null });
  useEffect(() => {
    let active = true;
    const check = async () => {
      try {
        const detail = await getHealth();
        if (active) setHealth({ status: detail.status === 'ok' ? 'ok' : 'degraded', detail });
      } catch {
        if (active) setHealth({ status: 'offline', detail: null });
      }
    };
    check();
    const id = setInterval(check, intervalMs);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [intervalMs]);
  return health;
}
