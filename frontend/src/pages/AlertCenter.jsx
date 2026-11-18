// @refresh reset
import { alertAuthority, authorityErrorMessage } from '../api/alertAuthority.js';
import ServiceAlertDetail from '../components/alerts/CommonAlertDetail.jsx';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { AlertCard } from '../components/alerts/AlertPresentation.jsx';
import { Bell, RefreshCw } from 'lucide-react';
import { getServiceAlert, getServiceAudit } from '../api/alertService.js';
import {
  buildAlertParams, buildLifecycleBody,
  describeServiceError, isStaleConflict, useCaseLabel,
} from '../api/alertServiceModel.js';
import { ALERT_POLL_MS } from '../config/services.js';
import useServiceAlerts from '../hooks/useServiceAlerts.js';
import useAlertEvidence from '../hooks/useAlertEvidence.js';
import { evidenceFields, matchesEvidence } from '../api/alertEvidence.js';
import './AlertCenter.css';
import AlertFilterToolbar from '../components/alerts/AlertFilterToolbar.jsx';
<<<<<<< HEAD
import { clearAlertCenterFilters, updateAlertCenterQuery } from './alertCenterFilters.js';
import { coverageOfAlert } from '../use-cases/face-mask/coverageModel.js';
=======
import { availableBranchOptions, branchFilterLabel } from '../components/alerts/AlertFilterToolbar.jsx';
import { buildAlertSummaryParams, clearAlertCenterFilters, updateAlertCenterQuery } from './alertCenterFilters.js';
import AlertAnalytics from '../components/alerts/AlertAnalytics.jsx';
import { platformApi } from '../features/branches/api.js';
>>>>>>> origin/merge/branch/pull

function SummaryTile({ label, value, critical = false, note = 'History unavailable' }) {
  return <section className={`alert-kpi ${critical ? 'alert-kpi-critical' : ''}`} aria-label={label}>
    <div><p>{label}</p><strong>{value ?? '—'}</strong><small>{note}</small></div>
    <span className="alert-kpi-neutral-trend" title="Historical KPI data is not available" aria-label="Historical KPI data unavailable"><i /></span>
  </section>;
}

export { default as ServiceAlertDetail } from '../components/alerts/CommonAlertDetail.jsx';

export default function AlertCenter() {
  const [query, setQuery] = useSearchParams();
  const status = query.get('status') || '';
  const useCase = query.get('use_case') || '';
  const coverageState = query.get('coverage_state') || '';
  const severity = query.get('severity') || '';
  const sourceType = query.get('type') || '';
  const from = query.get('from') || '';
  const to = query.get('to') || '';
  const sort = query.get('sort') || 'newest';
  const [typeInput, setTypeInput] = useState(sourceType);
  const selectedId = query.get('alert_id');
  const [detailRecord, setDetailRecord] = useState(null);
  const [detailLoadError, setDetailLoadError] = useState('');
  const setSelectedId = (id) => {
    const next = updateAlertCenterQuery(query, 'alert_id', id);
    if (!id) next.delete('source_event_id');
    setQuery(next);
  };
  const group = query.get('group') || '';
  const cameraId = query.get('camera_id') || '';
  const branchId = query.get('branch_id') || '';
  const evidence = query.get('evidence') || '';
  const sourceEventId = query.get('source_event_id') || '';
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState('');
  const [audit, setAudit] = useState({ loading: false, rows: [], error: '' });
  const [branches, setBranches] = useState([]);
  const [branchesLoaded, setBranchesLoaded] = useState(false);
  const [branchError, setBranchError] = useState('');
  useEffect(() => {
    let live = true;
    setBranchError('');
    platformApi('/branches/search?limit=100')
      .then((rows) => { if (live) { setBranches(availableBranchOptions(rows)); setBranchesLoaded(true); } })
      .catch((error) => { if (live) { setBranchError(error.message); setBranchesLoaded(true); } });
    return () => { live = false; };
  }, []);
  const params = useMemo(() => ({ ...buildAlertParams({ status, useCase, severity, sourceType, from, to, sort, limit: 6 }), ...(group && !status ? { group } : {}), ...(cameraId ? { camera_id: cameraId } : {}), ...(branchId ? { branch_id: branchId } : {}), ...(sourceEventId ? { source_event_id: sourceEventId } : {}) }),
    [status, useCase, severity, sourceType, from, to, sort, group, cameraId, branchId, sourceEventId]);
  const summaryParams = useMemo(() => buildAlertSummaryParams(params, branchId), [params, branchId]);
  const feed = useServiceAlerts({ params, summaryParams, status: status || group, pollMs: ALERT_POLL_MS });
  useEffect(() => {
    setDetailRecord(null);
    setDetailLoadError('');
    if (!selectedId) return undefined;
    const controller = new AbortController();
    getServiceAlert(selectedId, controller.signal).then((row) => {
      if (!controller.signal.aborted) setDetailRecord(row);
    }).catch((error) => {
      if (!controller.signal.aborted) setDetailLoadError(describeServiceError(error).message);
    });
    return () => controller.abort();
  }, [selectedId]);
  const evidenceRecords = useMemo(() => detailRecord && detailRecord.id === selectedId && !feed.items.some((row) => row.id === selectedId)
    ? [...feed.items, detailRecord] : feed.items, [feed.items, detailRecord, selectedId]);
  const evidenceItems=useAlertEvidence(evidenceRecords);
  const visibleItems = evidenceItems.filter((item) => feed.items.some((row) => row.id === item.id) && matchesEvidence(item,evidence)
    && (!coverageState || (item.useCase === 'face_mask' && coverageOfAlert(item) === coverageState)));
  const selected = evidenceItems.find((item) => item.id === selectedId || (selectedId === null && sourceEventId && item.sourceEventId === sourceEventId)) || null;
  const [sourceDetail, setSourceDetail] = useState(null);
  const [sourceError, setSourceError] = useState('');
  const [sourceRetry, setSourceRetry] = useState(0);
  const [sourceLoading, setSourceLoading] = useState(false);
  useEffect(() => {
    const ctl=new AbortController(); setSourceError(''); setSourceDetail(null);
    if (!selected) { setSourceLoading(false); return () => ctl.abort(); }
    setSourceLoading(true);
    alertAuthority.load(selected,ctl.signal).then((row)=>{if(!ctl.signal.aborted)setSourceDetail(row);})
      .catch((error)=>{if(!ctl.signal.aborted)setSourceError(authorityErrorMessage(error));})
      .finally(()=>{if(!ctl.signal.aborted)setSourceLoading(false);});
    return ()=>ctl.abort();
  },[selected?.id,selected?.sourceEventVersion,sourceRetry]);
  const detailed = sourceDetail?.id === selected?.id && selected ? {...sourceDetail,...evidenceFields(selected)} : selected;


  const setFilter = (key, value) => {
    const next = updateAlertCenterQuery(query, key, value);
    if (key === 'use_case' && value !== 'face_mask') next.delete('coverage_state');
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
    if (!selected?.id) return undefined;
    const ctl = new AbortController();
    setAudit((current) => ({ ...current, loading: true, error: '' }));
    getServiceAudit(selected.id, ctl.signal)
      .then((rows) => { if (!ctl.signal.aborted) setAudit({ loading: false, rows, error: '' }); })
      .catch((error) => { if (!ctl.signal.aborted) setAudit({ loading: false, rows: [], error: describeServiceError(error).message }); });
    return () => ctl.abort();
  }, [selected?.id, selectedVersion]);

  const act = useCallback(async (alert, target, note) => {
    setNotice('');
    let body;
    try { body = buildLifecycleBody(alert, target, note); } catch (err) { setNotice(err.message); return; }
    setPending(true);
    try {
      const updated = await alertAuthority.transition(alert, target, body);
      feed.applyUpdate(updated);
      setDetailRecord(updated);
      setSourceDetail(updated);
      setNotice(`Alert ${updated.status.toLowerCase()}.`);
    } catch (error) {
      const info = describeServiceError(error);
      setNotice(info.message);
      if (isStaleConflict(info)) {
        try { const latest=await alertAuthority.load(alert);setSourceDetail(latest);feed.applyUpdate(latest); } catch { setSourceError('Could not reload the source alert. Retry after the source service is available.'); }
        await feed.refresh();
      }
    } finally { setPending(false); }
  }, [feed]);

  const noFilters = !group && !branchId && !cameraId && !evidence && !sourceEventId && !status && !useCase && !severity && !sourceType && !coverageState && !from && !to;
  const clearFilters = () => {
    const next = clearAlertCenterFilters(query);
    setTypeInput('');
    next.delete('coverage_state');
    setQuery(next);
  };
  const bySeverity = feed.summary?.by_severity;
  const byStatus = feed.summary?.by_status;
  const checkedEvidence = evidenceItems.filter((item) => item.evidenceChecked
    && (!branchId || item.branchId === branchId));
  const selectedBranchLabel = branchFilterLabel(branchId, branches) || 'All branches';
  const input = 'min-h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm';

  return <div className={`alert-center mx-auto max-w-[1600px] space-y-5 ${selected || selectedId ? 'showing-detail' : ''}`}>
    {(selected || selectedId) && <button type="button" className="center-back" onClick={() => setSelectedId('')}>‹ Alerts{selected ? ` / ${useCaseLabel(selected.useCase)} / ${selected.sourceEventId || selected.id}` : ''}</button>}
    <header className="alert-center-header flex flex-wrap items-center justify-between gap-4">
      <div className="alert-center-heading"><div className="alert-center-title-line"><h2 className="text-2xl font-bold text-[#152449]">Alert Center</h2>
        <span className="alert-center-branch-badge">{selectedBranchLabel}</span></div>
        <p className="mt-1 text-sm text-slate-500">Persisted incidents from Vault, Gate & Mesh, Branch Exterior and Face Mask monitoring</p></div>
      <div className="alert-center-header-controls flex flex-wrap items-center gap-2">
        {feed.lastUpdated && <span className="text-xs text-slate-500">Updated {feed.lastUpdated.toLocaleTimeString()}</span>}
        <label className="alert-center-branch-select" title={branchError ? `Branch registry unavailable: ${branchError}` : 'Filter alerts and analytics by branch'}>
          <span>Branch</span><select aria-label="Filter alerts and analytics by branch" value={branchId}
            disabled={!branchesLoaded || Boolean(branchError)} onChange={(event) => setFilter('branch_id', event.target.value)}>
            <option value="">All branches</option>{branches.map((branch) => <option key={branch.id} value={branch.id}>{branch.name || branch.code || branch.id}</option>)}
          </select>
        </label>
        <button type="button" onClick={feed.refresh} className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-700">
          <RefreshCw className="h-4 w-4" aria-hidden />Refresh</button>
        <select aria-label="Sort alerts" value={sort} onChange={(e) => setFilter('sort', e.target.value === 'newest' ? '' : e.target.value)} className={input}>
          <option value="newest">Newest first</option><option value="oldest">Oldest first</option></select>
      </div>
    </header>
    {feed.summaryError && <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900" role="status">{describeServiceError(feed.summaryError).message}</div>}
    {feed.stale && <div className="rounded-xl border border-sky-200 bg-sky-50 p-3 text-sm text-sky-900" role="status">
      The list may be out of date. <button type="button" onClick={feed.refresh} className="font-semibold underline">Reload</button></div>}
    <section className="center-summary" aria-label="Alert summary">
      <SummaryTile label="Open alerts" value={byStatus ? (byStatus.OPEN || 0) + (byStatus.ACKNOWLEDGED || 0) : undefined} />
      <SummaryTile label="Unacknowledged" value={byStatus?.OPEN} />
      <SummaryTile label="High / Critical" value={bySeverity ? bySeverity.HIGH + bySeverity.CRITICAL : undefined} critical />
      <SummaryTile label="With snapshot (loaded)" value={checkedEvidence.filter((item) => item.snapshotCount > 0).length} note={`${checkedEvidence.length} loaded records checked`} />
      <SummaryTile label="Evidence unavailable (loaded)" value={checkedEvidence.filter((item) => item.evidenceStatus === 'UNAVAILABLE').length} critical note={`${checkedEvidence.length} loaded records checked`} />
    </section>
<<<<<<< HEAD
    <AlertFilterToolbar query={query} onChange={setFilter} onClear={clearFilters}
      typeInput={typeInput} onTypeInput={setTypeInput} />
    {useCase === 'face_mask' && <label className="inline-flex items-center gap-2 text-sm text-slate-700">Coverage
      <select aria-label="Filter Face Mask by coverage" className={input} value={coverageState} onChange={(event) => setFilter('coverage_state', event.target.value)}>
        <option value="">All</option><option value="PARTIALLY_COVERED">Partial</option><option value="FULLY_COVERED">Full</option>
      </select>
    </label>}
    {useCase === 'face_mask' && coverageState && <p className="text-xs text-slate-500">Coverage filtering applies to loaded alerts. Load more to search additional pages.</p>}
    <div className="center-content min-w-0">
=======
    <AlertAnalytics summary={feed.summary} rangeLabel={from || to ? 'Selected date range' : 'All dates'}
      loading={feed.summaryLoading} error={feed.summaryError}
      onRetry={feed.refreshSummary} errorMessage={feed.summaryError ? describeServiceError(feed.summaryError).message : ''}
      onFilter={setFilter} />
    <section className="alert-list-section" aria-label="Alert list">
      <AlertFilterToolbar query={query} onChange={setFilter} onClear={clearFilters}
        typeInput={typeInput} onTypeInput={setTypeInput} branches={branches}
        branchesLoaded={branchesLoaded} branchError={branchError} />
      <div className="center-content min-w-0">
>>>>>>> origin/merge/branch/pull
      <section className="center-list min-w-0">
        {feed.error && <div className="mt-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800" role="alert">
          <p>{describeServiceError(feed.error).message}</p>
          <button type="button" onClick={feed.refresh} className="mt-2 font-semibold underline">Retry</button></div>}
        {!feed.error && feed.loading && !feed.items.length && <div className="mt-4 space-y-3" aria-label="Loading alerts">
          {[0, 1, 2].map((x) => <div key={x} className="h-28 animate-pulse rounded-xl bg-slate-100" />)}</div>}
        {!feed.loading && !feed.error && !visibleItems.length && <div className="mt-4 rounded-xl border border-slate-200 bg-white p-10 text-center">
          <Bell className="mx-auto h-8 w-8 text-slate-300" aria-hidden />
          <p className="mt-3 font-semibold text-[#152449]">{noFilters ? 'No alerts yet' : 'No results'}</p>
          {!noFilters && <button type="button" onClick={clearFilters} className="mt-2 text-sm font-semibold text-[#34479B] underline">Clear filters</button>}</div>}
        {evidence && <p className="mt-2 text-xs text-slate-500">Evidence filtering applies to loaded records. Load more to search additional pages.</p>}
        <div className="mt-3 space-y-3">{visibleItems.map((alert) => <AlertCard key={alert.id} alert={alert} selected={alert.id === selectedId} onSelect={setSelectedId} showMetadata />)}</div>
        {feed.hasMore && <button type="button" disabled={feed.loading} onClick={feed.loadMore}
          className="mt-4 min-h-11 w-full rounded-lg border border-slate-200 bg-white text-sm font-semibold text-[#34479B] disabled:opacity-50">{feed.loading ? 'Loading…' : 'Load more'}</button>}
        <p className="mt-3 text-xs text-slate-500">Showing {visibleItems.length} of {feed.listTotal ?? feed.items.length} alerts</p>
      </section>
      <aside className="center-details min-w-0" aria-label="Alert details">
        {selectedId && !selected && (detailLoadError ? <p role="alert">{detailLoadError}</p> : <p role="status">Loading alert details…</p>)}
        {sourceLoading && <p role="status" className="mb-2 text-sm text-slate-500">Loading latest alert details...</p>}
        {sourceError && <p role="alert" className="mb-2 text-sm text-red-700">{sourceError} <button type="button" onClick={() => setSourceRetry((value) => value + 1)} className="underline">Retry details</button></p>}
        {selected
          ? <ServiceAlertDetail key={selected.id} alert={detailed} audit={audit} actionsEnabled={Boolean(sourceDetail?.id === selected?.id && !sourceLoading && !sourceError)} pending={pending} notice={notice} onAction={act} onClose={() => setSelectedId('')} />
          : null}
      </aside>
      </div>
    </section>
  </div>;
}
