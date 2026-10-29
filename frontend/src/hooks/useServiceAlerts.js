import { useCallback, useEffect, useRef, useState } from 'react';
import { getServiceSummary, listServiceAlerts } from '../api/alertService.js';
import { matchesStatus, mergeById, replaceAlert } from '../api/alertServiceModel.js';

const isCanceled = (error) => error?.code === 'ERR_CANCELED' || error?.name === 'CanceledError' || error?.name === 'AbortError';

/**
 * Alert Service list + summary with filters, "load more" pagination and background refresh.
 *
 * - A request counter drops responses from superseded requests (no stale list after a filter change).
 * - Every in-flight request is aborted on filter change and on unmount; the poll timer is cleared on unmount.
 * - Polling pauses while the tab is hidden. If extra pages were loaded, the loaded rows are never silently
 *   replaced: the hook flags `stale` instead so the user can reload.
 */
export default function useServiceAlerts({ params, status, pollMs }) {
  const [items, setItems] = useState([]);
  const [nextCursor, setNextCursor] = useState(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [summary, setSummary] = useState(null);
  const [summaryError, setSummaryError] = useState(null);
  const [stale, setStale] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);

  const paramsRef = useRef(params);
  paramsRef.current = params;
  const cursorRef = useRef(null);
  const pagesRef = useRef(1);
  const sequence = useRef(0);
  const controller = useRef(null);
  const summaryController = useRef(null);
  const paramsKey = JSON.stringify(params);

  const loadSummary = useCallback(async () => {
    summaryController.current?.abort();
    const ctl = new AbortController();
    summaryController.current = ctl;
    const { sort, limit, cursor, ...filters } = paramsRef.current; // eslint-disable-line no-unused-vars
    try {
      setSummary(await getServiceSummary(filters, ctl.signal));
      setSummaryError(null);
    } catch (err) {
      if (!isCanceled(err)) setSummaryError(err);
    }
  }, []);

  const load = useCallback(async ({ append = false, quiet = false } = {}) => {
    const id = ++sequence.current;
    controller.current?.abort();
    const ctl = new AbortController();
    controller.current = ctl;
    if (!quiet) setLoading(true);
    try {
      const page = await listServiceAlerts(
        { ...paramsRef.current, ...(append && cursorRef.current ? { cursor: cursorRef.current } : {}) }, ctl.signal);
      if (id !== sequence.current) return;
      setItems((current) => mergeById(current, page.items, append));
      cursorRef.current = page.nextCursor;
      setNextCursor(page.nextCursor);
      setHasMore(page.hasMore);
      pagesRef.current = append ? pagesRef.current + 1 : 1;
      setError(null);
      setStale(false);
      setLastUpdated(new Date());
    } catch (err) {
      if (!isCanceled(err) && id === sequence.current) setError(err);
    } finally {
      if (id === sequence.current) setLoading(false);
    }
  }, []);

  // Reload from scratch whenever the filters change.
  useEffect(() => {
    setItems([]);
    cursorRef.current = null;
    pagesRef.current = 1;
    setNextCursor(null);
    setHasMore(false);
    setError(null);
    setStale(false);
    load();
    loadSummary();
    return () => { sequence.current += 1; controller.current?.abort(); summaryController.current?.abort(); };
  }, [paramsKey, load, loadSummary]);

  // Background refresh. Timer and abort controllers are released on unmount.
  useEffect(() => {
    if (!pollMs) return undefined;
    const tick = () => {
      if (document.visibilityState === 'hidden') return;
      loadSummary();
      if (pagesRef.current === 1) load({ quiet: true });
      else setStale(true);
    };
    const timer = window.setInterval(tick, pollMs);
    const onVisible = () => { if (document.visibilityState === 'visible') tick(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => { window.clearInterval(timer); document.removeEventListener('visibilitychange', onVisible); };
  }, [pollMs, load, loadSummary]);

  /** Apply a server-confirmed alert update in place; remove it if it no longer matches the status filter. */
  const applyUpdate = useCallback((updated) => {
    setItems((current) => (matchesStatus(updated, status)
      ? replaceAlert(current, updated)
      : current.filter((item) => item.id !== updated.id)));
    loadSummary();
  }, [status, loadSummary]);

  return {
    items, nextCursor, hasMore, loading, error, summary, summaryError, stale, lastUpdated,
    refresh: () => { setStale(false); pagesRef.current = 1; cursorRef.current = null; return Promise.all([load(), loadSummary()]); },
    loadMore: () => load({ append: true }),
    applyUpdate,
  };
}
