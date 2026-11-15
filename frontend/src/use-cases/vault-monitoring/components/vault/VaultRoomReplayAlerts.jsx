import { useEffect, useState } from 'react';
import { Bell } from 'lucide-react';
import { getRoomReplayEvidence } from '../../api/vaultRoom.js';
import { getAlert, normalizeAlert, updateAlert } from '../../api/alerts.js';
import CompactAlertCard from '../../../../components/alerts/CompactAlertCard.jsx';
import { SourceAlertDetail } from '../../../../components/alerts/AlertPresentation.jsx';
import LifecycleConfirmation from '../../../../components/alerts/LifecycleConfirmation.jsx';
import { describeError } from '../../../../utils/errors.js';
import { readVaultUi, saveVaultUi } from '../../utils/replayStorage.js';

export const visibleReplayAlertScope = (scope) => scope;

export default function VaultRoomReplayAlerts({ replay, activity = null }) {
  const [scope, setScopeState] = useState(() => readVaultUi().scope);
  const setScope = (scope) => { setScopeState(scope); saveVaultUi({ scope }); };
  const [selected, setSelected] = useState(null);
  const [evidence, setEvidence] = useState('');
  const [thumbnails, setThumbnails] = useState({});
  const [error, setError] = useState('');
  const [persisted, setPersisted] = useState(null);
  const [pending, setPending] = useState(false);
  const [confirmTarget, setConfirmTarget] = useState(null);
  const [notice, setNotice] = useState('');
  const [statusOverrides, setStatusOverrides] = useState({});
  useEffect(() => { setSelected(null); setPersisted(null); setNotice(''); setStatusOverrides({}); }, [replay.session_id]);
  const scopedSelected = selected?.session_id === replay.session_id ? selected : null;
  useEffect(() => {
    const controller = new AbortController(); const urls = [];
    setThumbnails({});
    (replay.alerts || []).filter((item) => item.evidence_url).forEach((item) => {
      getRoomReplayEvidence(replay.session_id, item.id, controller.signal).then((blob) => {
        if (controller.signal.aborted) return;
        const url = URL.createObjectURL(blob); urls.push(url);
        setThumbnails((current) => ({ ...current, [item.id]: url }));
      }).catch(() => {});
    });
    return () => { controller.abort(); urls.forEach((url) => URL.revokeObjectURL(url)); };
  }, [replay.session_id, (replay.alerts || []).map((item) => `${item.id}:${item.evidence_url || ''}`).join('|')]);
  useEffect(() => {
    setEvidence(''); setError('');
    if (!scopedSelected?.evidence_url || !replay.session_id || thumbnails[scopedSelected.id]) {
      if (thumbnails[scopedSelected?.id]) setEvidence(thumbnails[scopedSelected.id]);
      return undefined;
    }
    const controller = new AbortController(); let url;
    getRoomReplayEvidence(replay.session_id, scopedSelected.id, controller.signal).then((blob) => {
      if (!controller.signal.aborted) { url = URL.createObjectURL(blob); setEvidence(url); }
    }).catch((err) => { if (!controller.signal.aborted) setError(describeError(err).message); });
    return () => { controller.abort(); if (url) URL.revokeObjectURL(url); };
  }, [scopedSelected?.id, replay.session_id, thumbnails]);
  useEffect(() => {
    setPersisted(null); setNotice(''); setConfirmTarget(null);
    if (!scopedSelected?.source_alert_id) return undefined;
    const controller = new AbortController();
    getAlert(scopedSelected.source_alert_id, controller.signal).then((row) => {
      if (!controller.signal.aborted && row.id === scopedSelected.source_alert_id && row.session_ref === replay.session_id) {
        const normalized = normalizeAlert(row); setPersisted(normalized);
        setStatusOverrides((current) => ({ ...current, [scopedSelected.id]: normalized.status }));
      }
    }).catch((err) => { if (!controller.signal.aborted) setNotice(describeError(err).message); });
    return () => controller.abort();
  }, [scopedSelected?.id, scopedSelected?.source_alert_id, replay.session_id]);
  const replayAlerts = (replay.alerts || []).filter((item) => item.session_id === replay.session_id)
    .map((item) => statusOverrides[item.id] ? { ...item, status: statusOverrides[item.id] } : item);
  const visibleScope = visibleReplayAlertScope(scope, replayAlerts);
  const isActive = (item) => ['OPEN', 'ACKNOWLEDGED'].includes(item.status);
  const alerts = replayAlerts.filter((item) => visibleScope === 'active' ? isActive(item) : !isActive(item));
  const metadata = scopedSelected?.metadata || {};
  const confidence = persisted?.mobilePhoneConfidence ?? metadata.mobile_phone_confidence;
  const detection = persisted?.mobilePhoneDetections?.[0] || scopedSelected?.detections?.[0];
  const snapshotRef = scopedSelected && evidence ? { id: scopedSelected.id, type: 'snapshot',
    captured_at: metadata.mobile_phone_detected_at, width: scopedSelected.evidence_width, height: scopedSelected.evidence_height } : null;
  const persistentId = persisted?.id || scopedSelected?.source_alert_id || null;
  const detailAlert = scopedSelected ? {
    id: scopedSelected.id, sourceEventId: persistentId,
    displayAlertId: persistentId || 'Pending persistence',
    displaySourceEventId: persistentId || 'Pending persistence',
    sourceEventType: 'MOBILE_PHONE_DETECTED', useCase: 'vault_monitoring',
    title: 'Mobile Phone Detected', severity: persisted?.severity || scopedSelected.severity,
    status: persisted?.status || scopedSelected.status, summary: persisted?.message ||
      (Number.isFinite(confidence) ? `Mobile phone detected with ${(confidence * 100).toFixed(0)}% confidence.` : scopedSelected.message),
    occurredAt: persisted?.firstSeenAt || metadata.mobile_phone_detected_at || scopedSelected.created_at,
    cameraName: persisted?.cameraName || metadata.camera_name || 'Uploaded video',
    sourceType: persisted?.sourceType || metadata.source_type, sessionRef: replay.session_id,
    evidenceManaged: true, evidenceChecked: true, evidenceRefs: snapshotRef ? [snapshotRef] : [],
    evidenceSnapshots: snapshotRef ? [{ ref: snapshotRef, url: evidence }] : [], snapshotCount: snapshotRef ? 1 : 0,
    evidenceCount: snapshotRef ? 1 : 0, evidenceStatus: snapshotRef ? 'CAPTURED' : persisted?.evidenceStatus || 'UNAVAILABLE',
    branchName: persisted?.branchName || metadata.branch_name, branchCode: persisted?.branchCode || metadata.branch_code,
    placeName: persisted?.placeName || metadata.place_name, regionName: persisted?.regionName || metadata.region_name,
    branchManager: persisted?.branchManager || metadata.branch_manager,
  } : null;
  const act = async (action, note) => {
    if (!persisted || pending || !persisted.allowedActions.includes(action)) return;
    setPending(true); setNotice('');
    try {
      const row = await updateAlert(persisted.id, action, { expected_version: persisted.rowVersion, ...(note ? { note } : {}) });
      const updated = normalizeAlert(row); setPersisted(updated);
      setStatusOverrides((current) => ({ ...current, [scopedSelected.id]: updated.status }));
      setNotice(`Alert ${updated.status.toLowerCase()}.`);
    } catch (err) { setNotice(describeError(err).message); }
    finally { setPending(false); }
  };
  return <section className="vault-card flex min-h-[440px] flex-col p-4 sm:p-5" aria-label="Replay test alerts">
    <h2 className="vault-heading flex flex-wrap items-center gap-2"><Bell className="h-5 w-5" aria-hidden />{activity ? 'Alerts & events' : 'Replay alerts'} <span className="rounded-full bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-900">Replay test</span></h2>
    <p className="mt-2 text-xs text-slate-500">Uses existing vault rules. Mobile-phone incidents are retained for operator review; other replay alerts remain local.</p>
    <div role="tablist" aria-label="Replay alert scope" className="mt-3 flex flex-wrap gap-2">{['active', 'history', ...(activity ? ['events'] : [])].map((item) => <button type="button" role="tab" key={item} aria-selected={visibleScope === item} onClick={() => setScope(item)} className={`min-h-9 rounded-lg px-3 text-xs font-semibold ${visibleScope === item ? 'bg-[#34479B] text-white' : 'border border-slate-200'}`}>{item === 'events' ? `Events (${activity.total})` : `${item === 'active' ? 'Active' : 'History'} (${replayAlerts.filter((alert) => item === 'active' ? isActive(alert) : !isActive(alert)).length})`}</button>)}{visibleScope === 'events' && <div className="ml-auto flex items-center gap-2">
      <button type="button" className="activity-text-button rounded-lg border border-[#5551df]/30 bg-white px-3 hover:bg-slate-50" onClick={() => activity.refresh()} disabled={activity.loading}>Refresh</button>
      <button type="button" className="activity-text-button rounded-lg border border-[#5551df]/30 bg-white px-3 hover:bg-slate-50" onClick={activity.requestClear} disabled={!activity.canClear}>Clear events</button>
    </div>}</div>
    {visibleScope === 'events' ? activity.content : <>
    <div className="room-alert-list mt-3 space-y-3">{alerts.length ? alerts.map((item) => <CompactAlertCard key={item.id}
      alert={{ ...item, summary: item.message }} thumbnailUrl={thumbnails[item.id]} onSelect={() => setSelected(item)} />) : <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-500">No {visibleScope} replay alerts.</p>}</div>
    {detailAlert && <div className="mt-4"><SourceAlertDetail alert={detailAlert} onClose={() => setSelected(null)}>
      <dl className="grid grid-cols-2 gap-3 border-t border-slate-200 pt-3 text-xs">
        <div><dt>Detected object</dt><dd>Mobile phone</dd></div>
        <div><dt>Confidence</dt><dd>{Number.isFinite(confidence) ? `${(confidence * 100).toFixed(0)}%` : 'Unavailable'}</dd></div>
        <div><dt>Bounding box</dt><dd>{Array.isArray(detection?.bbox) ? detection.bbox.map((value) => Number(value).toFixed(3)).join(', ') : 'Unavailable'}</dd></div>
        <div><dt>Video time</dt><dd>{Number.isFinite(persisted?.videoTimestampSeconds ?? metadata.video_timestamp_seconds) ? `${(persisted?.videoTimestampSeconds ?? metadata.video_timestamp_seconds).toFixed(2)} s` : 'Unavailable'}</dd></div>
        <div><dt>Confirmation duration</dt><dd>{Number.isFinite(persisted?.mobilePhoneConfirmationSeconds ?? metadata.mobile_phone_confirmation_seconds) ? `${persisted?.mobilePhoneConfirmationSeconds ?? metadata.mobile_phone_confirmation_seconds} s` : 'Unavailable'}</dd></div>
        <div><dt>Source type</dt><dd>{detailAlert.sourceType === 'uploaded_video' ? 'Uploaded video' : detailAlert.sourceType || 'Unavailable'}</dd></div>
        <div><dt>Camera name</dt><dd>{detailAlert.cameraName}</dd></div>
        <div><dt>Replay session ID</dt><dd className="break-all">{replay.session_id}</dd></div>
        <div><dt>Branch</dt><dd>{detailAlert.branchName || 'Unavailable'}</dd></div>
        <div><dt>Branch code</dt><dd>{detailAlert.branchCode || 'Unavailable'}</dd></div>
        <div><dt>Place</dt><dd>{detailAlert.placeName || 'Unavailable'}</dd></div>
        <div><dt>Region</dt><dd>{detailAlert.regionName || 'Unavailable'}</dd></div>
        <div><dt>Branch manager</dt><dd>{detailAlert.branchManager || 'Unavailable'}</dd></div>
      </dl>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      {notice && <p role="status" className="text-sm text-slate-600">{notice}</p>}
      {persisted && <div className="flex flex-wrap gap-2">{persisted.allowedActions.map((action) => <button key={action} type="button" disabled={pending}
        onClick={() => action === 'acknowledge' ? act(action) : setConfirmTarget(action)} className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-[#34479B] disabled:opacity-50">
        {{ acknowledge:'Acknowledge', resolve:'Resolve', dismiss:'Discard' }[action]}</button>)}</div>}
      {confirmTarget && <LifecycleConfirmation target={confirmTarget === 'dismiss' ? 'DISMISSED' : 'RESOLVED'} pending={pending}
        onClose={() => setConfirmTarget(null)} onConfirm={(reason) => { act(confirmTarget, reason); setConfirmTarget(null); }} />}
    </SourceAlertDetail></div>}
    </>}
  </section>;
}
