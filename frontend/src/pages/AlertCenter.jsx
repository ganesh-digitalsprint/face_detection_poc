import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Bell, RefreshCw } from 'lucide-react';
import { getServiceAudit, transitionServiceAlert } from '../api/alertService.js';
import {
  ACTIVE_STATUSES, SEVERITIES, STATUSES, USE_CASE_LABELS, availableActions, buildAlertParams, buildLifecycleBody,
  describeServiceError, isStaleConflict, useCaseLabel,
} from '../api/alertServiceModel.js';
import { ALERT_POLL_MS, ALERT_SERVICE_ACTIONS_ENABLED } from '../config/services.js';
import useServiceAlerts from '../hooks/useServiceAlerts.js';

const SEVERITY_STYLE = {
  CRITICAL: 'bg-red-100 text-red-800', HIGH: 'bg-orange-100 text-orange-800',
  WARNING: 'bg-amber-100 text-amber-800', INFO: 'bg-sky-100 text-sky-800',
};
const STATUS_STYLE = {
  OPEN: 'bg-red-50 text-red-700', ACKNOWLEDGED: 'bg-amber-50 text-amber-800',
  RESOLVED: 'bg-emerald-50 text-emerald-700', DISMISSED: 'bg-slate-100 text-slate-600',
};
const SOURCE_LINK = { vault_monitoring: '/alerts/vault', branch_exterior: '/alerts/branch' };
const fmt = (iso) => (iso ? new Date(iso).toLocaleString([], { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—');

function Pill({ className, children }) {
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${className}`}>{children}</span>;
}

function SummaryTile({ label, value, critical = false }) {
  return <section className={`vault-card min-h-24 p-4 ${critical ? 'border-red-200' : ''}`} aria-label={label}>
    <p className="text-xs text-slate-500">{label}</p>
    <p className={`mt-2 text-2xl font-bold tabular-nums ${critical ? 'text-red-700' : 'text-[#152449]'}`}>{value ?? '—'}</p>
  </section>;
}

function AlertRow({ alert, selected, onSelect }) {
  return <button type="button" onClick={() => onSelect(alert.id)} aria-pressed={selected}
    className={`vault-card block w-full p-4 text-left ${selected ? 'ring-2 ring-[#34479B]' : ''}`}>
    <div className="flex flex-wrap items-center gap-2">
      <Pill className="bg-[#eef1fb] text-[#26365F]">{useCaseLabel(alert.useCase)}</Pill>
      <Pill className={SEVERITY_STYLE[alert.severity] || 'bg-slate-100 text-slate-700'}>{alert.severity}</Pill>
      <Pill className={STATUS_STYLE[alert.status] || 'bg-slate-100 text-slate-700'}>{alert.status}</Pill>
      <span className="ml-auto text-xs text-slate-500">{fmt(alert.occurredAt)}</span>
    </div>
    <p className="mt-2 font-semibold text-[#152449]">{alert.title}</p>
    <p className="mt-1 line-clamp-2 text-sm text-slate-600">{alert.summary}</p>
    <p className="mt-2 text-xs text-slate-500">
      {alert.sourceEventType}
      {alert.cameraName || alert.cameraId ? ` · ${alert.cameraName || alert.cameraId}` : ''}
      {alert.zoneName ? ` · ${alert.zoneName}` : ''}
      {alert.sessionRef ? ` · session ${alert.sessionRef.slice(0, 8)}` : ''}
    </p>
  </button>;
}

function Timeline({ audit }) {
  if (audit.loading) return <p className="text-xs text-slate-500">Loading timeline…</p>;
  if (audit.error) return <p className="text-xs text-red-700" role="alert">{audit.error}</p>;
  if (!audit.rows.length) return <p className="text-xs text-slate-500">No timeline entries.</p>;
  return <ol className="space-y-2 border-l border-slate-200 pl-3" aria-label="Event timeline">
    {audit.rows.map((row) => <li key={row.id} className="text-xs">
      <p className="font-semibold text-[#152449]">{row.action}{row.from_status && row.to_status ? ` · ${row.from_status} → ${row.to_status}` : ''}</p>
      <p className="text-slate-500">{fmt(row.created_at)}{row.actor_id ? ` · ${row.actor_id}` : ''}</p>
      {row.details?.note && <p className="text-slate-600">{row.details.note}</p>}
    </li>)}
  </ol>;
}

function Detail({ alert, audit, actionsEnabled, pending, notice, onAction, onClose }) {
  const [note, setNote] = useState('');
  useEffect(() => setNote(''), [alert.id, alert.rowVersion]);
  const actions = availableActions(alert, actionsEnabled);
  const sourceLink = SOURCE_LINK[alert.useCase];
  return <div className="vault-card sticky top-24 space-y-4 p-4 sm:p-5">
    <div className="flex items-start justify-between gap-2">
      <div><p className="text-xs font-semibold uppercase text-slate-500">Alert details</p>
        <h2 className="mt-1 text-lg font-bold text-[#152449]">{alert.title}</h2></div>
      <button type="button" onClick={onClose} className="min-h-9 rounded px-2 text-sm text-slate-500" aria-label="Close alert details">Close</button>
    </div>
    <p className="text-sm text-slate-700">{alert.summary}</p>
    <dl className="grid grid-cols-2 gap-3 text-xs">
      <div><dt className="text-slate-500">Source</dt><dd className="mt-1 font-bold">{useCaseLabel(alert.useCase)}</dd></div>
      <div><dt className="text-slate-500">Source event</dt><dd className="mt-1 break-all font-bold">{alert.sourceEventId}</dd></div>
      <div><dt className="text-slate-500">Severity</dt><dd className="mt-1 font-bold">{alert.severity}{alert.sourceSeverity && alert.sourceSeverity !== alert.severity ? ` (source: ${alert.sourceSeverity})` : ''}</dd></div>
      <div><dt className="text-slate-500">Status</dt><dd className="mt-1 font-bold">{alert.status}{alert.sourceStatus ? ` (source: ${alert.sourceStatus})` : ''}</dd></div>
      <div><dt className="text-slate-500">Occurred</dt><dd className="mt-1 font-bold">{fmt(alert.occurredAt)}</dd></div>
      <div><dt className="text-slate-500">Occurrences</dt><dd className="mt-1 font-bold">{alert.occurrenceCount}</dd></div>
      {alert.acknowledgedAt && <div><dt className="text-slate-500">Acknowledged</dt><dd className="mt-1 font-bold">{fmt(alert.acknowledgedAt)} · {alert.acknowledgedBy}</dd></div>}
      {alert.resolvedAt && <div><dt className="text-slate-500">Resolved</dt><dd className="mt-1 font-bold">{fmt(alert.resolvedAt)} · {alert.resolvedBy}</dd></div>}
      {alert.dismissedAt && <div><dt className="text-slate-500">Dismissed</dt><dd className="mt-1 font-bold">{fmt(alert.dismissedAt)} · {alert.dismissedBy}</dd></div>}
    </dl>
    {alert.resolutionNote && <p className="text-xs text-slate-600">Note: {alert.resolutionNote}</p>}
    <div><h3 className="mb-2 text-xs font-semibold uppercase text-slate-500">Timeline</h3><Timeline audit={audit} /></div>
    {actions.length > 0 && <div className="space-y-2">
      <textarea aria-label="Note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} rows={2}
        placeholder="Note (required to resolve or dismiss)" className="w-full rounded-lg border border-slate-200 p-2 text-sm" />
      <div className="flex flex-wrap gap-2">
        {actions.map((action) => <button key={action.target} type="button" disabled={pending} onClick={() => onAction(alert, action.target, note)}
          className="min-h-10 flex-1 rounded-lg border border-slate-200 px-3 text-sm font-semibold text-[#26365F] disabled:opacity-50">{action.label}</button>)}
      </div>
    </div>}
    {!actionsEnabled && <p className="text-xs text-slate-500">Read-only: {useCaseLabel(alert.useCase)} remains the lifecycle authority for this alert while shadow ingestion is in effect.</p>}
    {notice && <p className="text-sm text-slate-700" role="status" aria-live="polite">{notice}</p>}
    {sourceLink && <Link to={sourceLink} className="block text-center text-sm font-semibold text-[#34479B] underline">Open in {useCaseLabel(alert.useCase)}</Link>}
  </div>;
}

export default function AlertCenter() {
  const [query, setQuery] = useSearchParams();
  const status = query.get('status') || '';
  const useCase = query.get('use_case') || '';
  const severity = query.get('severity') || '';
  const sourceType = query.get('type') || '';
  const from = query.get('from') || '';
  const to = query.get('to') || '';
  const sort = query.get('sort') || 'newest';
  const [typeInput, setTypeInput] = useState(sourceType);
  const [selectedId, setSelectedId] = useState(null);
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState('');
  const [audit, setAudit] = useState({ loading: false, rows: [], error: '' });

  const params = useMemo(() => buildAlertParams({ status, useCase, severity, sourceType, from, to, sort, limit: 25 }),
    [status, useCase, severity, sourceType, from, to, sort]);
  const feed = useServiceAlerts({ params, status, pollMs: ALERT_POLL_MS });
  const selected = feed.items.find((item) => item.id === selectedId) || null;

  const setFilter = (key, value) => {
    const next = new URLSearchParams(query);
    if (value) next.set(key, value); else next.delete(key);
    setQuery(next);
  };
  useEffect(() => setTypeInput(sourceType), [sourceType]);
  useEffect(() => {
    if (typeInput === sourceType) return undefined;
    const timer = window.setTimeout(() => setFilter('type', typeInput.trim()), 350);
    return () => window.clearTimeout(timer);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typeInput]);

  // Timeline for the selected alert; reloads when the alert's version changes (e.g. after an action or a poll).
  const selectedVersion = selected?.rowVersion;
  useEffect(() => {
    if (!selectedId) return undefined;
    const ctl = new AbortController();
    setAudit((current) => ({ ...current, loading: true, error: '' }));
    getServiceAudit(selectedId, ctl.signal)
      .then((rows) => setAudit({ loading: false, rows, error: '' }))
      .catch((error) => { if (!ctl.signal.aborted) setAudit({ loading: false, rows: [], error: describeServiceError(error).message }); });
    return () => ctl.abort();
  }, [selectedId, selectedVersion]);

  const act = useCallback(async (alert, target, note) => {
    setNotice('');
    let body;
    try { body = buildLifecycleBody(alert, target, note); } catch (err) { setNotice(err.message); return; }
    setPending(true);
    try {
      const updated = await transitionServiceAlert(alert.id, target, body);
      feed.applyUpdate(updated);
      setNotice(`Alert ${updated.status.toLowerCase()}.`);
    } catch (error) {
      const info = describeServiceError(error);
      setNotice(info.message);
      if (isStaleConflict(info)) await feed.refresh();
    } finally { setPending(false); }
  }, [feed]);

  const noFilters = !status && !useCase && !severity && !sourceType && !from && !to;
  const clearFilters = () => setQuery(new URLSearchParams());
  const bySeverity = feed.summary?.by_severity;
  const byStatus = feed.summary?.by_status;
  const input = 'min-h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm';

  return <div className="mx-auto max-w-[1600px] space-y-5">
    <header className="flex flex-wrap items-center justify-between gap-4">
      <div><h2 className="text-2xl font-bold text-[#152449]">Alert Center</h2>
        <p className="mt-1 text-sm text-slate-500">Alerts published to the Alert Service by Vault and Branch Exterior monitoring</p></div>
      <div className="flex flex-wrap items-center gap-2">
        {feed.lastUpdated && <span className="text-xs text-slate-500">Updated {feed.lastUpdated.toLocaleTimeString()}</span>}
        <button type="button" onClick={feed.refresh} className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700">
          <RefreshCw className="h-4 w-4" aria-hidden />Refresh</button>
        <select aria-label="Sort alerts" value={sort} onChange={(e) => setFilter('sort', e.target.value === 'newest' ? '' : e.target.value)} className={input}>
          <option value="newest">Newest first</option><option value="oldest">Oldest first</option></select>
      </div>
    </header>
    {feed.summaryError && <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900" role="status">{describeServiceError(feed.summaryError).message}</div>}
    {feed.stale && <div className="rounded-xl border border-sky-200 bg-sky-50 p-3 text-sm text-sky-900" role="status">
      The list may be out of date. <button type="button" onClick={feed.refresh} className="font-semibold underline">Reload</button></div>}
    <section className="grid grid-cols-2 gap-3 xl:grid-cols-4" aria-label="Alert summary">
      <SummaryTile label="Total" value={feed.summary?.total} /><SummaryTile label="Open" value={byStatus?.OPEN} />
      <SummaryTile label="Acknowledged" value={byStatus?.ACKNOWLEDGED} />
      <SummaryTile label="High / Critical" value={bySeverity ? bySeverity.HIGH + bySeverity.CRITICAL : undefined} critical />
    </section>
    <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      <section className="min-w-0">
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-white p-2">
          <div className="flex flex-wrap gap-1" role="tablist" aria-label="Alert status">
            {['', ...STATUSES].map((item) => <button key={item || 'all'} type="button" role="tab" aria-selected={status === item}
              onClick={() => setFilter('status', item)}
              className={`min-h-10 rounded-lg px-3 text-sm font-semibold ${status === item ? 'bg-[#34479B] text-white' : 'text-slate-600 hover:bg-slate-50'}`}>
              {item ? item.charAt(0) + item.slice(1).toLowerCase() : 'All'}</button>)}
          </div>
          <span className="mx-1 h-7 border-l border-slate-200" aria-hidden />
          <select aria-label="Filter by source" value={useCase} onChange={(e) => setFilter('use_case', e.target.value)} className={input}>
            <option value="">Source: All</option>
            {Object.entries(USE_CASE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
          <select aria-label="Filter by severity" value={severity} onChange={(e) => setFilter('severity', e.target.value)} className={input}>
            <option value="">Severity: All</option>{SEVERITIES.map((item) => <option key={item}>{item}</option>)}</select>
          <input aria-label="Filter by event type" value={typeInput} onChange={(e) => setTypeInput(e.target.value)} placeholder="Event type" className={`${input} min-w-32 flex-1`} />
          <label className="flex items-center gap-2 text-xs text-slate-500">From
            <input aria-label="From date" type="datetime-local" value={from} onChange={(e) => setFilter('from', e.target.value)} className={input} /></label>
          <label className="flex items-center gap-2 text-xs text-slate-500">To
            <input aria-label="To date" type="datetime-local" value={to} onChange={(e) => setFilter('to', e.target.value)} className={input} /></label>
        </div>
        {feed.error && <div className="mt-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800" role="alert">
          <p>{describeServiceError(feed.error).message}</p>
          <button type="button" onClick={feed.refresh} className="mt-2 font-semibold underline">Retry</button></div>}
        {!feed.error && feed.loading && !feed.items.length && <div className="mt-4 space-y-3" aria-label="Loading alerts">
          {[0, 1, 2].map((x) => <div key={x} className="h-28 animate-pulse rounded-xl bg-slate-100" />)}</div>}
        {!feed.loading && !feed.error && !feed.items.length && <div className="mt-4 rounded-xl border border-slate-200 bg-white p-10 text-center">
          <Bell className="mx-auto h-8 w-8 text-slate-300" aria-hidden />
          <p className="mt-3 font-semibold text-[#152449]">{noFilters ? 'No alerts yet' : 'No results'}</p>
          {!noFilters && <button type="button" onClick={clearFilters} className="mt-2 text-sm font-semibold text-[#34479B] underline">Clear filters</button>}</div>}
        <div className="mt-3 space-y-3">{feed.items.map((alert) => <AlertRow key={alert.id} alert={alert} selected={alert.id === selectedId} onSelect={setSelectedId} />)}</div>
        {feed.hasMore && <button type="button" disabled={feed.loading} onClick={feed.loadMore}
          className="mt-4 min-h-11 w-full rounded-lg border border-slate-200 bg-white text-sm font-semibold text-[#34479B] disabled:opacity-50">{feed.loading ? 'Loading…' : 'Load more'}</button>}
        <p className="mt-3 text-xs text-slate-500">Active alerts are {ACTIVE_STATUSES.join(' and ').toLowerCase()}; resolved and dismissed alerts are history.</p>
      </section>
      <aside className="min-w-0" aria-label="Alert details">
        {selected
          ? <Detail alert={selected} audit={audit} actionsEnabled={ALERT_SERVICE_ACTIONS_ENABLED} pending={pending} notice={notice} onAction={act} onClose={() => setSelectedId(null)} />
          : <div className="hidden rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 xl:block">Select an alert to view details and its timeline.</div>}
      </aside>
    </div>
  </div>;
}
