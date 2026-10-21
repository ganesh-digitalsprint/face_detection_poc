import { useCallback, useEffect, useRef, useState } from 'react';
import { closeVault as requestCloseVault, getVaultRoomState, openVaultEvents } from '../api/vaultRoom.js';

const INITIAL = { state: 'IDLE', session_id: null, required_persons: null, test_mode: null,
  entry_buffer_remaining_seconds: 0, remaining_seconds: null, door: 'LOCKED', employees: [],
  open_alerts: [], expired_alert_level: 0, video_source: 'browser', stable_count: null,
  expected_persons: null, feed: 'NONE', accepts_frames: false, recommended_fps: null,
  detector_status: 'loading', lock_countdown_remaining_seconds: null, alerts: [] };

export default function useVaultRoom() {
  const [roomState, setRoomState] = useState(null);
  const [events, setEvents] = useState([]);
  const [criticalAlert, setCriticalAlert] = useState(null);
  const [connection, setConnection] = useState('connecting');
  const [closeSummary, setCloseSummary] = useState(null);
  const [closing, setClosing] = useState(false);
  const [error, setError] = useState(null);
  const [reloadToken, setReloadToken] = useState(0);
  const countdownRef = useRef(null);
  const eventIdsRef = useRef(new Set());
  const initialDurationRef = useRef(null);
  const sessionIdRef = useRef(null);
  const failureCount = useRef(0);
  const lastStateAt = useRef(performance.now());
  const abortRef = useRef(null);
  const closeFlight = useRef(null);

  const applyState = useCallback((next) => {
    if (!next || typeof next !== 'object') return;
    lastStateAt.current = performance.now();
    if (next.session_id !== sessionIdRef.current) {
      sessionIdRef.current = next.session_id;
      initialDurationRef.current = null;
      setCriticalAlert(null);
    }
    if (next.state === 'ACTIVE' && Number.isFinite(next.remaining_seconds)) {
      initialDurationRef.current = initialDurationRef.current == null
        ? next.remaining_seconds : Math.max(initialDurationRef.current, next.remaining_seconds);
    }
    countdownRef.current = { at: performance.now(), state: next.state,
      entry: next.entry_buffer_remaining_seconds ?? 0, remaining: next.remaining_seconds };
    setRoomState({ ...INITIAL, ...next });
  }, []);

  const addEvent = useCallback((event) => {
    if (!event?.id || eventIdsRef.current.has(event.id)) return;
    eventIdsRef.current.add(event.id);
    if (eventIdsRef.current.size > 500) eventIdsRef.current.delete(eventIdsRef.current.values().next().value);
    if (event.severity === 'critical' && event.type === 'ALERT_OPENED') setCriticalAlert(event);
    setEvents((current) => [event, ...current].slice(0, 200));
  }, []);

  useEffect(() => {
    const watchdog = window.setInterval(() => {
      if (performance.now() - lastStateAt.current > 4000) setConnection('offline');
    }, 1000);
    return () => window.clearInterval(watchdog);
  }, []);

  useEffect(() => {
    let disposed = false;
    let retryTimer;
    let delay = 1000;
    const connect = async () => {
      while (!disposed) {
        const controller = new AbortController();
        abortRef.current = controller;
        setConnection(failureCount.current ? (failureCount.current >= 3 ? 'offline' : 'reconnecting') : 'connecting');
        try {
          await openVaultEvents(
            (snapshot) => { applyState(snapshot.state); for (const item of snapshot.events ?? []) eventIdsRef.current.add(item.id);
              setEvents((prev) => {
              const byId = new Map(prev.map((item) => [item.id, item]));
              for (const item of snapshot.events ?? []) byId.set(item.id, item);
              return [...byId.values()].slice(-200).reverse();
            }); },
            (event) => addEvent(event),
            (state) => { applyState(state); setConnection('live'); setError(null); delay = 1000; failureCount.current = 0; },
            controller.signal,
          );
          if (!disposed) throw new Error('Vault event stream ended.');
        } catch (err) {
          if (disposed || controller.signal.aborted) return;
          failureCount.current += 1;
          setConnection('reconnecting');
          setError(err?.message || 'Connection to vault room was lost.');
          await new Promise((resolve) => { retryTimer = window.setTimeout(resolve, delay); });
          delay = Math.min(delay * 2, 10000);
        }
      }
    };
    connect();
    return () => { disposed = true; abortRef.current?.abort(); window.clearTimeout(retryTimer); };
  // Keep the SSE connection for the whole page lifetime. Changes to room state must not reconnect it.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadToken, applyState, addEvent]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      const base = countdownRef.current;
      if (!base) return;
      const elapsed = Math.floor((performance.now() - base.at) / 1000);
      setRoomState((current) => {
        if (!current) return current;
        if (base.state === 'ENTRY_BUFFER') return { ...current, entry_buffer_remaining_seconds: Math.max(0, base.entry - elapsed) };
        if (base.state === 'ACTIVE' && base.remaining != null) return { ...current, remaining_seconds: Math.max(0, base.remaining - elapsed) };
        return current;
      });
    }, 250);
    return () => window.clearInterval(timer);
  }, []);

  const close = useCallback(async () => {
    if (closeFlight.current) return closeFlight.current;
    setClosing(true);
    closeFlight.current = requestCloseVault().then((summary) => {
      setCloseSummary(summary);
      setRoomState((current) => current ? { ...current, ...summary, state: 'CLOSED', door: 'LOCKED',
        remaining_seconds: null, entry_buffer_remaining_seconds: 0, accepts_frames: false } : current);
      return summary;
    }).finally(() => { setClosing(false); closeFlight.current = null; });
    return closeFlight.current;
  }, []);
  const refreshState = useCallback(async () => {
    const next = await getVaultRoomState();
    applyState(next);
    return next;
  }, [applyState]);
  const clearEvents = useCallback(() => setEvents([]), []);
  const retry = useCallback(() => { setError(null); setConnection('reconnecting'); setReloadToken((n) => n + 1); }, []);
  return { roomState, events, criticalAlert, connection, closeSummary, closing, error, closeVault: close, clearEvents, retry, refreshState,
    countdownProgress: roomState?.state === 'ACTIVE' && initialDurationRef.current
      ? Math.max(0, Math.min(100, (roomState.remaining_seconds / initialDurationRef.current) * 100)) : 0 };
}
