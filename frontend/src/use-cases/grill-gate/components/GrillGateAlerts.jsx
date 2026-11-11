import GrillGateAlertCard from './GrillGateAlertCard.jsx';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import useServiceAlerts from '../../../hooks/useServiceAlerts.js';
import { normalizeGrillGateAlert } from '../../../api/alertServiceModel.js';
import { AlertCard, SourceAlertDetail } from '../../../components/alerts/AlertPresentation.jsx';
import { describeError } from '../../../utils/errors.js';
import { createGrillAlertApi } from '../grillAlertFeed.js';
import { getLiveActiveAlerts, getLiveAlertHistory, getGrillGateVideoResults, getGrillGateAlert,
  acknowledgeGrillGateAlert, resolveGrillGateAlert } from '../api/grillGate.js';

const reads = { active: getLiveActiveAlerts, history: getLiveAlertHistory, video: getGrillGateVideoResults, detail: getGrillGateAlert };
export default function GrillGateAlerts({ assignmentId, jobId, compact = false }) {
  const [query] = useSearchParams();
  const [status, setStatus] = useState(() => query.get('status') === 'HISTORY' ? 'HISTORY' : 'ACTIVE');
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailError, setDetailError] = useState('');
  const [detailLoading, setDetailLoading] = useState(false);
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState('');
  const scope = jobId ? `video:${jobId}` : `live:${assignmentId || ''}`;
  const scopeRef = useRef(scope); scopeRef.current = scope;
  const adapter = useMemo(() => createGrillAlertApi({ assignmentId, jobId, api: reads }), [assignmentId, jobId]);
  const params = useMemo(() => ({ status, scope }), [status, scope]);
  const feed = useServiceAlerts({ params, status, pollMs: 3000, api: adapter, enabled: Boolean(assignmentId || jobId) });
  useEffect(() => { setSelectedId(null); setDetail(null); setNotice(''); setDetailError(''); }, [scope]);
  const requested = query.get('alert');
  const selected = feed.items.find((a) => a.id === selectedId || (selectedId === null && requested && a.sourceEventId === requested));
  const selectedVersion = selected?.rowVersion;
  const selectedKey = selected?.id;
  useEffect(() => {
    if (!selectedKey) { setDetail(null); return undefined; }
    const ctl = new AbortController();
    setDetailError(''); setDetailLoading(true);
    getGrillGateAlert(selectedKey, ctl.signal).then((row) => {
      if (!ctl.signal.aborted) setDetail(normalizeGrillGateAlert(row));
    }).catch((error) => { if (!ctl.signal.aborted) setDetailError(describeError(error).message); }).finally(() => { if (!ctl.signal.aborted) setDetailLoading(false); });
    return () => ctl.abort();
  }, [selectedKey, selectedVersion, scope]);
  const act = async (target) => {
    const alert = detail?.id === selected?.id ? detail : selected;
    if (!alert || pending) return;
    const note = target === 'RESOLVED' ? window.prompt('Resolution note (required):') : null;
    if (target === 'RESOLVED' && !note?.trim()) return;
    const atScope = scope;
    setPending(true); setNotice('');
    try {
      const row = target === 'ACKNOWLEDGED' ? await acknowledgeGrillGateAlert(alert.localId, alert.rowVersion)
        : await resolveGrillGateAlert(alert.localId, alert.rowVersion, note.trim());
      if (scopeRef.current !== atScope) return;
      const updated = normalizeGrillGateAlert(row);
      adapter.applyUpdate(updated);
      feed.applyUpdate(updated); setDetail(updated); setNotice(`Alert ${updated.status.toLowerCase()}.`);
    } catch (error) { if (scopeRef.current === atScope) setNotice(describeError(error).message); }
    finally { setPending(false); if (scopeRef.current === atScope) feed.refresh(); }
  };
  return <section className="vault-card p-4 sm:p-5" aria-label="Grill Gate alerts">
    <header className="mb-3 flex items-center justify-between gap-3"><h2 className="font-bold text-[#0F1B3D]">{status === 'ACTIVE' ? 'Active Alerts' : 'Alert History'}</h2><Link to="/alerts/all?use_case=grill_gate" className="text-xs font-semibold text-[#34479B]">View all &rsaquo;</Link></header>
    <div className="mb-3 flex gap-2" role="tablist" aria-label="Grill Gate alert status">{['ACTIVE','HISTORY'].map((value) => <button type="button" key={value} role="tab" aria-selected={status === value} onClick={() => { setStatus(value); setSelectedId(''); }} className={`rounded-lg px-3 py-2 text-xs font-semibold ${status === value ? 'bg-[#34479B] text-white' : 'border border-[#E3E7F0] text-[#55607A]'}`}>{value === 'ACTIVE' ? 'Active' : 'History'}{adapter.count(value) != null ? ` (${adapter.count(value)})` : ''}</button>)}<button type="button" onClick={feed.refresh} className="ml-auto text-xs text-[#34479B]">Refresh</button></div>
    {!assignmentId && !jobId && <p className="text-sm text-[#55607A]">Select a camera or uploaded video to load alerts.</p>}
    {feed.error && <p role="alert" className="mb-3 text-sm text-red-800">Could not refresh persisted alerts. Existing records remain visible. {feed.error.message} <button onClick={feed.refresh} className="underline">Retry</button></p>}
    {feed.loading && !feed.items.length && <p role="status" className="text-sm text-[#55607A]">Loading alerts...</p>}
    {!feed.loading && !feed.error && !feed.items.length && (assignmentId || jobId) && <p className="text-sm text-[#55607A]">{status === 'ACTIVE' ? (adapter.count('HISTORY') > 0 ? 'No active alerts. Resolved or dismissed incidents are available in History.' : 'No active alerts.') : feed.hasMore ? 'No matching alerts on this page. Load more alerts below.' : 'No historical alerts.'}</p>}
    <div className={`grid gap-3 ${!compact && selected ? 'xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]' : ''}`}>
      <div className="min-w-0 space-y-3">{feed.items.map((alert) => compact ? <GrillGateAlertCard key={alert.id} alert={alert} selected={selected?.id === alert.id} onSelect={setSelectedId} /> : <AlertCard key={alert.id} alert={alert} selected={selected?.id === alert.id} onSelect={setSelectedId} />)}</div>
      {selected && <div className="min-w-0">{detailLoading && <p role="status" className="mb-2 text-xs text-slate-500">Refreshing alert details...</p>}{detailError && <p role="alert" className="mb-2 text-sm text-red-800">Could not load latest details: {detailError}</p>}<SourceAlertDetail alert={detail?.id === selected.id ? detail : selected} onClose={() => setSelectedId('')}>
        <div className="flex flex-wrap gap-2">{(detail?.id === selected.id ? detail : selected).allowedActions.filter((action) => ['ACKNOWLEDGED','RESOLVED'].includes(action)).map((target) => <button key={target} type="button" disabled={pending} onClick={() => act(target)} className="rounded-lg border border-[#D0D7E6] px-4 py-2 text-sm font-semibold text-[#34479B] disabled:opacity-50">{target === 'ACKNOWLEDGED' ? 'Acknowledge' : 'Resolve'}</button>)}</div>
      </SourceAlertDetail></div>}
    </div>
    {notice && <p role="status" className="mt-3 text-sm text-[#55607A]">{notice}</p>}
    {feed.hasMore && <button type="button" onClick={feed.loadMore} disabled={feed.loading} className="mt-3 text-sm font-semibold text-[#34479B]">Load more alerts</button>}
    {feed.stale && <p className="mt-2 text-xs text-[#55607A]">New updates available. <button onClick={feed.refresh} className="underline">Reload</button></p>}
    <Link to="/alerts/all?use_case=grill_gate" className="mt-3 block text-sm font-semibold text-[#34479B]">Open Alert Center &rsaquo;</Link>
  </section>;
}
