import { useCallback, useEffect, useRef, useState } from 'react';
import { getActivityEvents } from '../api/activityEvents.js';
import { latestActivityNotificationId, mergeActivities, readChronologicalActivityPages } from '../utils/activityEvents.js';

const PAGE_SIZE = 25;
const empty = (key) => ({ key, items: [], total: 0, loading: false, loadingMore: false, error: null });

export default function useVaultActivityEvents({ sessionId, source, sourceId, replay, enabled, liveEvents = [] }) {
  const key = JSON.stringify([enabled, sessionId, source, sourceId, replay]);
  const [state, setState] = useState(() => empty(key));
  const operation = useRef(null);
  const refresh = useCallback((options) => operation.current?.(options), []);
  useEffect(() => {
    let active = true, controller, count = 0, wanted = PAGE_SIZE, inFlight = false, sequence = 0, knownTotal = 0, hasLoaded = false;
    setState({ ...empty(key), loading: Boolean(enabled && sessionId) });
    if (!enabled || !sessionId) { operation.current = null; return undefined; }
    const fetch = async ({ append = false, quiet = false } = {}) => {
      if (quiet && inFlight) return;
      controller?.abort(); controller = new AbortController();
      const request = ++sequence; inFlight = true;
      setState((current) => ({ ...current, loading: !quiet && !append, loadingMore: append }));
      try {
        const offset = append ? count : 0;
        const limit = append ? PAGE_SIZE : wanted;
        const signal = controller.signal;
        const page = await readChronologicalActivityPages(
          async (pagination) => {
            const result = await getActivityEvents(sessionId, { source, source_id: sourceId, replay, ...pagination }, signal);
            if (!active || request !== sequence) throw new DOMException('Obsolete activity request', 'AbortError');
            return result;
          },
          { offset, limit, pageSize: PAGE_SIZE, followNewEvents: !append && hasLoaded && count >= knownTotal });
        if (!active || request !== sequence) return;
        const { items: incoming, total } = page;
        count = page.nextOffset; wanted = Math.max(PAGE_SIZE, count); knownTotal = total; hasLoaded = true;
        const scoped = incoming.filter((event) => event.session_id === sessionId && event.source === source
          && (!sourceId || event.source_id === sourceId) && event.replay === replay);
        setState((current) => ({ key, items: mergeActivities(append ? [...current.items, ...scoped] : scoped), total, loading: false, loadingMore: false, error: null }));
      } catch (error) {
        if (active && request === sequence && !controller.signal.aborted) setState((current) => ({ ...current, loading: false, loadingMore: false, error }));
      } finally { if (request === sequence) inFlight = false; }
    };
    operation.current = fetch; fetch();
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') fetch({ quiet: true }); }, 3000);
    return () => { active = false; sequence += 1; controller?.abort(); window.clearInterval(timer); operation.current = null; };
  }, [key, enabled, sessionId, source, sourceId, replay]);
  const notificationId = latestActivityNotificationId(liveEvents, { sessionId, source, sourceId, replay });
  useEffect(() => { if (notificationId) refresh({ quiet: true }); }, [notificationId, refresh]);
  // Render-time key guard prevents even a single stale frame when switching contexts.
  return { ...(state.key === key ? state : empty(key)), key, sessionId,
    refresh, loadMore: () => refresh({ append: true }), hasMore: state.key === key && state.items.length < state.total };
}
