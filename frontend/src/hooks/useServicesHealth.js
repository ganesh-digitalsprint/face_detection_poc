import { useEffect, useState } from 'react';
import { SERVICES } from '../config/serviceRegistry.js';

const PROBE_TIMEOUT_MS = 4000;

/** GET <base><healthPath>; resolves 'ok' | 'degraded' | 'offline'. Never rejects. */
async function probe(service) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
  try {
    const res = await fetch(`${service.baseUrl}${service.healthPath}`, { signal: controller.signal });
    if (!res.ok) return 'degraded';
    const body = await res.json().catch(() => null);
    return body && body.status && body.status !== 'ok' ? 'degraded' : 'ok';
  } catch {
    return 'offline';
  } finally {
    clearTimeout(timer);
  }
}

/** Overall chip state: ok when all reachable services are ok; offline only when every service is down. */
export function summarize(states) {
  const values = Object.values(states);
  if (values.length === 0 || values.every((v) => v === 'checking')) return 'checking';
  const known = values.filter((v) => v !== 'checking');
  if (known.every((v) => v === 'offline')) return 'offline';
  return known.every((v) => v === 'ok') ? 'ok' : 'degraded';
}

/** Polls every registered backend independently. services: { [id]: 'checking'|'ok'|'degraded'|'offline' } */
export default function useServicesHealth(intervalMs = 30000) {
  const [services, setServices] = useState(() => Object.fromEntries(SERVICES.map((s) => [s.id, 'checking'])));
  useEffect(() => {
    let active = true;
    const check = () => SERVICES.forEach(async (service) => {
      const state = await probe(service);
      if (active) setServices((prev) => (prev[service.id] === state ? prev : { ...prev, [service.id]: state }));
    });
    check();
    const id = setInterval(check, intervalMs);
    return () => { active = false; clearInterval(id); };
  }, [intervalMs]);
  return { services, status: summarize(services) };
}
