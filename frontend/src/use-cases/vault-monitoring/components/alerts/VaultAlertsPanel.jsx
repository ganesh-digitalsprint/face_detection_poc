import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Bell, Copy, ExternalLink } from 'lucide-react';
import { Link } from 'react-router-dom';
import { getAlertSummary, updateAlert } from '../../api/alerts.js';
import { describeError } from '../../../../utils/errors.js';
import useVaultAlerts from '../../hooks/useVaultAlerts.js';
import useAlertThumbnails from '../../hooks/useAlertThumbnails.js';
import AlertCard from './AlertCard.jsx';

function VaultAlertsPanel({ liveEvents = [] }) {
  const [scope, setScope] = useState('active');
  const [pendingId, setPendingId] = useState(null);
  const [message, setMessage] = useState('');
  const params = useMemo(() => ({}), []);
  const feed = useVaultAlerts({ scope, limit: 5, params });
  const refreshFeed = useRef(feed.refresh);
  refreshFeed.current = feed.refresh;
  const thumbnails = useAlertThumbnails(feed.items);
  const [summary, setSummary] = useState(null);
  const seenLiveEventIds = useRef(new Set());
  const refreshSummary = useCallback(() => getAlertSummary({ scope: 'active' }).then(setSummary).catch(() => setSummary(null)), []);
  useEffect(() => { refreshSummary(); }, [refreshSummary]);
  useEffect(() => {
    const fresh = liveEvents.filter((event) => event?.channel === 'alerts'
      && event.entity?.type === 'alert'
      && (event.event_id || event.id)
      && !seenLiveEventIds.current.has(event.event_id || event.id));
    if (!fresh.length) return undefined;
    for (const event of fresh) {
      const id = event.event_id || event.id;
      seenLiveEventIds.current.add(id);
      if (seenLiveEventIds.current.size > 500) {
        seenLiveEventIds.current.delete(seenLiveEventIds.current.values().next().value);
      }
    }
    const timer = window.setTimeout(() => {
      refreshFeed.current();
      refreshSummary();
    }, 80);
    return () => window.clearTimeout(timer);
  }, [liveEvents, refreshSummary]);
  const act = async (alert, action, note) => {
    setPendingId(alert.id); setMessage('');
    try {
      await updateAlert(alert.id, action, { ...(note ? { note } : {}), expected_version: alert.rowVersion });
      await Promise.all([feed.refresh(), refreshSummary()]);
    } catch (error) {
      const info = describeError(error);
      setMessage(info.code === 'VERSION_CONFLICT' ? 'This alert changed. Refreshing the latest version.' : info.message);
      if (info.status === 409) await feed.refresh();
    } finally { setPendingId(null); }
  };
  const copyLog = async () => {
    try { await navigator.clipboard.writeText(feed.items.map((item) => `${new Date(item.createdAt).toLocaleString()} ${item.severity} ${item.title}: ${item.message}`).join('\n')); setMessage('Alert log copied.'); }
    catch { setMessage('Could not copy the alert log.'); }
  };
  return <section className="vault-card flex min-h-[440px] flex-col p-4 sm:p-5" aria-labelledby="room-alert-title">
    <div className="flex items-center justify-between gap-2"><h2 id="room-alert-title" className="vault-heading flex items-center gap-2"><Bell className="h-5 w-5" aria-hidden />Alerts {scope === 'active' && summary && <span className="rounded-full bg-red-700 px-2 py-0.5 text-[10px] text-white">{summary.open} open</span>}</h2><Link to="/vault-alerts" className="inline-flex min-h-9 items-center gap-1 text-xs font-semibold text-[#34479B] underline">View all <ExternalLink className="h-3 w-3" aria-hidden /></Link></div>
    <div className="mt-3 flex items-center gap-1" role="tablist" aria-label="Alert scope">
      {['active', 'history'].map((item) => <button key={item} type="button" role="tab" aria-selected={scope === item} onClick={() => setScope(item)} className={`min-h-9 rounded-lg px-3 text-xs font-semibold ${scope === item ? 'bg-[#34479B] text-white' : 'border border-slate-200 bg-white text-slate-700'}`}>{item === 'active' ? 'Active' : 'History'}</button>)}
      <span className="ml-auto text-xs text-slate-500">This session</span>
    </div>
    {message && <p className="mt-2 text-xs text-slate-600" role="status" aria-live="polite">{message}</p>}
    {feed.error && <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900"><p>{describeError(feed.error).message}</p><button type="button" onClick={() => feed.refresh()} className="mt-2 font-semibold underline">Retry</button></div>}
    {feed.loading && !feed.items.length && <div className="mt-4 space-y-3" aria-label="Loading alerts"><div className="h-28 animate-pulse rounded-xl bg-slate-100"/><div className="h-28 animate-pulse rounded-xl bg-slate-100"/></div>}
    {!feed.loading && !feed.error && feed.items.length === 0 && <p className="mt-4 rounded-lg bg-slate-50 p-4 text-sm text-slate-600">{scope === 'active' ? 'No active alerts.' : 'No alerts in history.'}</p>}
    <div className="mt-3 space-y-3">{feed.items.map((alert) => <AlertCard key={alert.id} alert={alert} variant="compact" thumbnailUrl={thumbnails[alert.primaryEvidenceId]} pending={pendingId === alert.id} onAction={act}/>)}</div>
    <div className="mt-auto flex items-center justify-between gap-2 pt-4"><span className="text-xs text-slate-500">{scope === 'active' ? 'No other active alerts' : ''}</span><button type="button" onClick={copyLog} disabled={!feed.items.length} className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-slate-200 px-3 text-xs font-semibold text-[#34479B] hover:bg-slate-50 disabled:opacity-50"><Copy className="h-4 w-4" aria-hidden/>Copy alert log</button></div>
  </section>;
}

export default memo(VaultAlertsPanel);
