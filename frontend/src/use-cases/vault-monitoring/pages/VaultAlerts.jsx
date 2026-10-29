import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams, Link, useNavigate } from 'react-router-dom';
import { Bell, ExternalLink, RefreshCw } from 'lucide-react';
import { createIncidentFromAlert, getAlertMeta, getAlertSummary, updateAlert } from '../api/alerts.js';
import { describeError } from '../../../utils/errors.js';
import AlertCard from '../components/alerts/AlertCard.jsx';
import useVaultAlerts from '../hooks/useVaultAlerts.js';
import useAlertThumbnails from '../hooks/useAlertThumbnails.js';

function SummaryTile({ label, value, critical = false }) {
  return <section className={`vault-card min-h-24 p-4 ${critical ? 'border-red-200' : ''}`} aria-label={label}>
    <p className="text-xs text-slate-500">{label}</p><p className={`mt-2 text-2xl font-bold tabular-nums ${critical ? 'text-red-700' : 'text-[#152449]'}`}>{value ?? '—'}</p>
  </section>;
}

export default function VaultAlerts() {
  const [query, setQuery] = useSearchParams();
  const navigate = useNavigate();
  const scope = query.get('scope') || 'active';
  const severity = query.get('severity') || '';
  const alertType = query.get('alert_type') || '';
  const cameraId = query.get('camera_id') || '';
  const sessionRef = query.get('session_ref') || '';
  const [sessionSearch, setSessionSearch] = useState(sessionRef);
  const sort = query.get('sort') || 'newest';
  const dateFrom = query.get('from') || '';
  const dateTo = query.get('to') || '';
  const params = useMemo(() => ({ sort, ...(severity ? { severity: [severity] } : {}), ...(alertType ? { alert_type: [alertType] } : {}), ...(cameraId ? { camera_id: cameraId } : {}), ...(sessionRef ? { session_ref: sessionRef } : {}), ...(dateFrom ? { from: new Date(dateFrom).toISOString() } : {}), ...(dateTo ? { to: new Date(new Date(dateTo).getTime() + 60000).toISOString() } : {}) }), [sort, severity, alertType, cameraId, sessionRef, dateFrom, dateTo]);
  const feed = useVaultAlerts({ scope, limit: 25, params });
  const thumbnails = useAlertThumbnails(feed.items);
  const [summary, setSummary] = useState(null);
  const [meta, setMeta] = useState(null);
  const [metaError, setMetaError] = useState(null);
  const [summaryError, setSummaryError] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [pendingId, setPendingId] = useState(null);
  const [notice, setNotice] = useState('');
  const setFilter = (key, value) => { const next = new URLSearchParams(query); if (value) next.set(key, value); else next.delete(key); next.delete('cursor'); setQuery(next); };
  const refreshSummary = useCallback(async () => {
    try { setSummary(await getAlertSummary({ scope, ...params })); setSummaryError(null); }
    catch (error) { setSummaryError(describeError(error).message); }
  }, [scope, params]);
  useEffect(() => { refreshSummary(); }, [refreshSummary]);
  useEffect(() => { setSessionSearch(sessionRef); }, [sessionRef]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const next = new URLSearchParams(query);
      if (sessionSearch.trim()) next.set('session_ref', sessionSearch.trim()); else next.delete('session_ref');
      if (next.toString() !== query.toString()) setQuery(next, { replace: true });
    }, 350);
    return () => window.clearTimeout(timer);
  }, [sessionSearch]);
  useEffect(() => { getAlertMeta().then(setMeta).catch((error) => setMetaError(describeError(error).message)); }, []);
  const selected = feed.items.find((item) => item.id === selectedId) || null;
  const act = async (alert, action, note) => {
    setPendingId(alert.id); setNotice('');
    try {
      await updateAlert(alert.id, action, { ...(note ? { note } : {}), expected_version: alert.rowVersion });
      setNotice(`${action === 'acknowledge' ? 'Alert acknowledged' : action === 'dismiss' ? 'Alert discarded' : 'Alert resolved'}.`);
      await Promise.all([feed.refresh(), refreshSummary()]);
    } catch (error) {
      const info = describeError(error);
      setNotice(info.code === 'VERSION_CONFLICT' ? 'This alert changed. The latest version has been reloaded.' : info.message);
      if (info.status === 409) await feed.refresh();
    } finally { setPendingId(null); }
  };
  const openIncident = async () => {
    if (!selected) return;
    setPendingId(selected.id); setNotice('');
    try {
      const incident = selected.incidentId ? { id: selected.incidentId } : await createIncidentFromAlert(selected.id);
      navigate(`/vault-alerts/incidents/${encodeURIComponent(incident.id)}?alert=${encodeURIComponent(selected.id)}`);
    } catch (error) { setNotice(describeError(error).message); }
    finally { setPendingId(null); }
  };
  const clearFilters = () => setQuery(new URLSearchParams({ scope }));
  const noFilters = !severity && !alertType && !cameraId && !sessionRef && !dateFrom && !dateTo;
  return <div className="mx-auto max-w-[1600px] space-y-5">
    <header className="flex flex-wrap items-center justify-between gap-4">
      <div><h2 className="text-2xl font-bold text-[#152449]">Alerts</h2><p className="mt-1 text-sm text-slate-500">Vault Monitoring alerts. Alerts from every use case are in the <Link to="/alert-center" className="font-semibold text-[#34479B] underline">Alert Center</Link>.</p></div>
      <div className="flex flex-wrap items-center gap-2"><button type="button" onClick={() => { feed.refresh(); refreshSummary(); }} className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700"><RefreshCw className="h-4 w-4" aria-hidden/>Refresh</button><select aria-label="Sort alerts" value={sort} onChange={(e) => setFilter('sort', e.target.value)} className="min-h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm"><option value="newest">Newest first</option><option value="oldest">Oldest first</option></select></div>
    </header>
    {(summaryError || metaError) && <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900" role="status">{summaryError || metaError}</div>}
    <section className="grid grid-cols-2 gap-3 xl:grid-cols-4" aria-label="Alert summary">
      <SummaryTile label="Open alerts" value={summary?.open}/><SummaryTile label="Unacknowledged" value={summary?.unacknowledged}/><SummaryTile label="High / Critical open" value={summary?.high_or_critical_open} critical/><SummaryTile label="Incidents investigating" value={summary?.incidents_investigating}/>
    </section>
    <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
      <section className="min-w-0">
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-white p-2" role="tablist" aria-label="Alert scope">
          {['active','history','all'].map((item) => <button key={item} type="button" role="tab" aria-selected={scope === item} onClick={() => setFilter('scope', item)} className={`min-h-10 rounded-lg px-4 text-sm font-semibold capitalize ${scope === item ? 'bg-[#34479B] text-white' : 'text-slate-600 hover:bg-slate-50'}`}>{item}{item === 'active' && summary ? ` · ${summary.open}` : ''}</button>)}
          <span className="mx-1 h-7 border-l border-slate-200" aria-hidden/>
          <select aria-label="Filter by use case" disabled={!meta?.use_cases?.length} onChange={(e) => setFilter('use_case', e.target.value)} className="min-h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm disabled:hidden"><option value="">Use case: All</option>{(meta?.use_cases || []).map((item) => <option key={item} value={item}>{item}</option>)}</select>
          <select aria-label="Filter by severity" value={severity} onChange={(e) => setFilter('severity', e.target.value)} className="min-h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm"><option value="">Severity: All</option>{(meta?.severities || ['CRITICAL','HIGH','WARNING','INFO']).map((item) => <option key={item}>{item}</option>)}</select>
          <select aria-label="Filter by alert type" value={alertType} onChange={(e) => setFilter('alert_type', e.target.value)} className="min-h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm"><option value="">Type: All</option>{(meta?.alert_types || []).map((item) => <option key={item}>{item}</option>)}</select>
          <select aria-label="Filter by camera" value={cameraId} onChange={(e) => setFilter('camera_id', e.target.value)} className="min-h-10 max-w-40 rounded-lg border border-slate-200 bg-white px-3 text-sm"><option value="">Camera: All</option>{(meta?.cameras || []).filter(Boolean).map((item) => <option key={item}>{item}</option>)}</select>
          <input aria-label="Filter by session reference" value={sessionSearch} onChange={(e) => setSessionSearch(e.target.value)} placeholder="Session reference" className="min-h-10 min-w-36 flex-1 rounded-lg border border-slate-200 px-3 text-sm"/>
          <label className="flex items-center gap-2 text-xs text-slate-500">From <input aria-label="From date" type="datetime-local" value={dateFrom} onChange={(e) => setFilter('from', e.target.value)} className="min-h-10 rounded-lg border border-slate-200 px-2 text-sm text-slate-700"/></label>
          <label className="flex items-center gap-2 text-xs text-slate-500">To <input aria-label="To date" type="datetime-local" value={dateTo} onChange={(e) => setFilter('to', e.target.value)} className="min-h-10 rounded-lg border border-slate-200 px-2 text-sm text-slate-700"/></label>
          {meta?.branches?.length > 0 && <select aria-label="Filter by branch" onChange={(e) => setFilter('branch_id', e.target.value)} className="min-h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm"><option value="">Branch: All</option>{meta.branches.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>}
        </div>
        {notice && <p className="mt-3 text-sm text-slate-700" role="status" aria-live="polite">{notice}</p>}
        {feed.error && <div className="mt-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800"><p>{describeError(feed.error).message}</p><button type="button" onClick={() => feed.refresh()} className="mt-2 font-semibold underline">Retry</button></div>}
        {!feed.error && feed.loading && !feed.items.length && <div className="mt-4 space-y-3" aria-label="Loading alerts">{[0,1,2].map((x) => <div key={x} className="h-36 animate-pulse rounded-xl bg-slate-100"/>)}</div>}
        {!feed.loading && !feed.error && !feed.items.length && <div className="mt-4 rounded-xl border border-slate-200 bg-white p-10 text-center"><Bell className="mx-auto h-8 w-8 text-slate-300" aria-hidden/><p className="mt-3 font-semibold text-[#152449]">{noFilters ? 'No alerts yet' : 'No results'}</p>{!noFilters && <button type="button" onClick={clearFilters} className="mt-2 text-sm font-semibold text-[#34479B] underline">Clear filters</button>}</div>}
        <div className="mt-3 space-y-3">{feed.items.map((alert) => <AlertCard key={alert.id} alert={alert} variant="row" thumbnailUrl={thumbnails[alert.primaryEvidenceId]} pending={pendingId === alert.id} onAction={act} onSelect={(item) => setSelectedId(item.id)}/>)}</div>
        {feed.hasMore && <button type="button" disabled={feed.loading} onClick={feed.loadMore} className="mt-4 min-h-11 w-full rounded-lg border border-slate-200 bg-white text-sm font-semibold text-[#34479B] disabled:opacity-50">{feed.loading ? 'Loading…' : 'Load more'}</button>}
      </section>
      <aside className="min-w-0" aria-label="Alert details">
        {selected ? <div className="vault-card sticky top-24 space-y-4 p-4 sm:p-5"><div className="flex items-start justify-between gap-2"><div><p className="text-xs font-semibold uppercase text-slate-500">Alert details</p><h2 className="mt-1 text-lg font-bold text-[#152449]">{selected.title}</h2></div><button type="button" onClick={() => setSelectedId(null)} className="min-h-9 rounded px-2 text-sm text-slate-500" aria-label="Close alert details">Close</button></div>
          <AlertCard alert={selected} variant="drawer" pending={pendingId === selected.id} onAction={act} thumbnailUrl={thumbnails[selected.primaryEvidenceId]}/>
          <dl className="grid grid-cols-2 gap-3 text-xs"><div><dt className="text-slate-500">Observed / required</dt><dd className="mt-1 font-bold">{selected.observedCount ?? '—'} / {selected.requiredCount ?? '—'}</dd></div><div><dt className="text-slate-500">First seen</dt><dd className="mt-1 font-bold">{selected.firstSeenAt ? new Date(selected.firstSeenAt).toLocaleTimeString([], { timeZoneName: 'short' }) : '—'}</dd></div><div><dt className="text-slate-500">Session</dt><dd className="mt-1 break-all font-bold">{selected.sessionRef || '—'}</dd></div><div><dt className="text-slate-500">Incident</dt><dd className="mt-1 font-bold">{selected.incidentNumber || 'Not linked'}</dd></div></dl>
          {selected.incidentId ? <Link to={`/vault-alerts/incidents/${encodeURIComponent(selected.incidentId)}?alert=${encodeURIComponent(selected.id)}`} className="flex min-h-10 items-center justify-center gap-2 rounded-lg border border-slate-200 text-sm font-semibold text-[#26365F]">Open incident <ExternalLink className="h-4 w-4" aria-hidden/></Link> : <button type="button" disabled={pendingId === selected.id} onClick={openIncident} className="min-h-10 w-full rounded-lg border border-slate-200 text-sm font-semibold text-[#26365F] disabled:opacity-50">Open incident</button>}
        </div> : <div className="hidden rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 xl:block">Select an alert to view details.</div>}
      </aside>
    </div>
  </div>;
}
