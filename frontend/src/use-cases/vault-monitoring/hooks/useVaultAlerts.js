import { useCallback, useEffect, useRef, useState } from 'react';
import { getAlerts, normalizeAlert } from '../api/alerts.js';

export default function useVaultAlerts({ scope = 'active', limit = 5, params = {} } = {}) {
  const [items, setItems] = useState([]);
  const [nextCursor, setNextCursor] = useState(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const requestSequence = useRef(0);
  const loadedPages = useRef(1);
  const inFlight = useRef(false);
  const refresh = useCallback(async ({ append = false, quiet = false } = {}) => {
    if (quiet && inFlight.current) return;
    const requestId = ++requestSequence.current;
    inFlight.current = true;
    if (!quiet) setLoading(true);
    try {
      // Refresh all loaded pages so background synchronization preserves pagination.
      const pageCount = quiet ? loadedPages.current : 1;
      let response, cursor = append ? nextCursor : null;
      const incoming = [];
      for (let page = 0; page < pageCount; page += 1) {
        response = await getAlerts({ scope, limit, ...params, ...(cursor ? { cursor } : {}) });
        if (requestId !== requestSequence.current) return;
        incoming.push(...(response.items || []).map(normalizeAlert));
        cursor = response.next_cursor;
        if (!cursor) break;
      }
      if (requestId !== requestSequence.current) return;
      setItems((current) => {
        const rows = append ? [...current, ...incoming] : incoming;
        return [...new Map(rows.map((row) => [row.id, row])).values()];
      });
      setNextCursor(response.next_cursor || null);
      setHasMore(Boolean(response.has_more));
      loadedPages.current = append ? loadedPages.current + 1 : pageCount;
      setError(null);
    } catch (err) {
      if (requestId === requestSequence.current) setError(err);
    } finally {
      if (requestId === requestSequence.current) { inFlight.current = false; setLoading(false); }
    }
  }, [scope, limit, params, nextCursor]);
  useEffect(() => {
    setItems([]);
    setNextCursor(null);
    setHasMore(false);
    setLoading(true);
    setError(null);
    loadedPages.current = 1;
    refresh();
    return () => { requestSequence.current += 1; };
  // refresh changes with cursor only after a load more.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, limit, JSON.stringify(params)]);
  const refreshRef=useRef(refresh); refreshRef.current=refresh;
  useEffect(()=>{
    const tick=()=>{if(document.visibilityState==='visible')refreshRef.current({ quiet: true });};
    const timer=window.setInterval(tick,5000);document.addEventListener('visibilitychange',tick);
    return()=>{window.clearInterval(timer);document.removeEventListener('visibilitychange',tick);};
  },[]);
  return { items, nextCursor, hasMore, loading, error, refresh, loadMore: () => refresh({ append: true }) };
}
