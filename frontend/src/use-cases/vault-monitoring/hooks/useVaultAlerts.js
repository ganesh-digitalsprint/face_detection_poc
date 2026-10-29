import { useCallback, useEffect, useRef, useState } from 'react';
import { getAlerts, normalizeAlert } from '../api/alerts.js';

export default function useVaultAlerts({ scope = 'active', limit = 5, params = {} } = {}) {
  const [items, setItems] = useState([]);
  const [nextCursor, setNextCursor] = useState(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const requestSequence = useRef(0);
  const refresh = useCallback(async ({ append = false } = {}) => {
    const requestId = ++requestSequence.current;
    setLoading(true);
    try {
      const response = await getAlerts({ scope, limit, ...params, ...(append && nextCursor ? { cursor: nextCursor } : {}) });
      const incoming = (response.items || []).map(normalizeAlert);
      if (requestId !== requestSequence.current) return;
      setItems((current) => {
        const rows = append ? [...current, ...incoming] : incoming;
        return [...new Map(rows.map((row) => [row.id, row])).values()];
      });
      setNextCursor(response.next_cursor || null);
      setHasMore(Boolean(response.has_more));
      setError(null);
    } catch (err) {
      if (requestId === requestSequence.current) setError(err);
    } finally {
      if (requestId === requestSequence.current) setLoading(false);
    }
  }, [scope, limit, params, nextCursor]);
  useEffect(() => {
    setItems([]);
    setNextCursor(null);
    setHasMore(false);
    setLoading(true);
    setError(null);
    refresh();
    return () => { requestSequence.current += 1; };
  // refresh changes with cursor only after a load more.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, limit, JSON.stringify(params)]);
  return { items, nextCursor, hasMore, loading, error, refresh, loadMore: () => refresh({ append: true }) };
}
