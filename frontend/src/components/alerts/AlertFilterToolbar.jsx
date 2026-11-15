import { CalendarDays, ChevronDown, Search, X } from 'lucide-react';
import { startTransition, useEffect, useState } from 'react';
import { SEVERITIES, STATUSES, USE_CASE_LABELS } from '../../api/alertServiceModel.js';
import { useOptionalActiveBranch } from '../../features/branches/ActiveBranch.jsx';
import { platformApi } from '../../features/branches/api.js';
import './AlertFilterToolbar.css';

function FilterChip({ label, value, onChange, children }) {
  return <label className="alert-filter-chip"><span>{label}</span><select aria-label={`Filter by ${label.toLowerCase()}`} value={value} onChange={(event) => onChange(event.target.value)}>{children}</select><ChevronDown size={12} aria-hidden /></label>;
}

export default function AlertFilterToolbar({ query, onChange, onClear, typeInput, onTypeInput }) {
  const branchContext = useOptionalActiveBranch();
  const scope = branchContext?.scope;
  const group = query.get('group') || '';
  const [selectedGroup, setSelectedGroup] = useState(group);
  useEffect(() => setSelectedGroup(group), [group]);
  const status = query.get('status') || '';
  const branchId = query.get('branch_id') || '';
  const cameraId = query.get('camera_id') || '';
  const [cameras, setCameras] = useState([]);
  const [cameraError, setCameraError] = useState('');
  useEffect(() => {
    let live = true;
    setCameras([]);
    setCameraError('');
    if (!branchId) return () => { live = false; };
    platformApi(`/branches/${encodeURIComponent(branchId)}/cameras`)
      .then((rows) => { if (live) setCameras(rows); })
      .catch((error) => { if (live) setCameraError(error.message); });
    return () => { live = false; };
  }, [branchId]);
  const from = query.get('from') || '';
  const to = query.get('to') || '';
  const branchName = scope?.type === 'branch' && scope.id === branchId ? scope.name : branchId;
  const count = ['status', 'branch_id', 'use_case', 'severity', 'evidence', 'type', 'camera_id', 'source_event_id'].filter((key) => query.get(key)).length + (from || to ? 1 : 0);
  return <section className="center-filters alert-filter-toolbar" aria-label="Alert filters">
    <div className="alert-filter-top">
      <div className="alert-filter-tabs" role="tablist" aria-label="Alert scope" style={{'--scope-index': selectedGroup === 'ACTIVE' ? 0 : selectedGroup === 'HISTORY' ? 1 : 2}}>
        <span className="alert-filter-slider" aria-hidden />
        {[['ACTIVE', 'Active'], ['HISTORY', 'History'], ['', 'All']].map(([value, label]) => <button type="button" role="tab" key={label} aria-selected={selectedGroup === value} onClick={() => {
          setSelectedGroup(value);
          startTransition(() => onChange('group', value));
        }}>{label}</button>)}
      </div>
      <label className="alert-filter-search"><Search size={15} aria-hidden /><input type="search" aria-label="Filter by event type" placeholder="Search alert ID, event type or camera" title="Currently searches event type. Combined alert ID and camera search requires API support." value={typeInput} onChange={(event) => onTypeInput(event.target.value)} /></label>
    </div>
    <div className="alert-filter-bottom">
      <FilterChip label="Status" value={status} onChange={(value) => onChange('status', value)}><option value="">All</option>{STATUSES.map((value) => <option key={value} value={value}>{value.charAt(0) + value.slice(1).toLowerCase()}</option>)}</FilterChip>
      {branchId ? <div className="alert-filter-chip alert-filter-branch"><span>Branch</span><strong>{branchName}</strong><button type="button" aria-label="Clear branch filter" onClick={() => { if (scope?.type === 'branch' && scope.id === branchId) branchContext.setScope(null); onChange('branch_id', ''); }}><X size={12} /></button></div>
        : <FilterChip label="Branch" value="" onChange={(value) => onChange('branch_id', value)}><option value="">All</option>{scope?.type === 'branch' && <option value={scope.id}>{scope.name || scope.id}</option>}</FilterChip>}
      <FilterChip label="Camera" value={cameraId} onChange={(value) => onChange('camera_id', value)}><option value="">All</option>{cameras.map((camera) => <option key={camera.id} value={camera.id}>{camera.name || camera.code || camera.id}</option>)}{cameraId && !cameras.some((camera) => camera.id === cameraId) && <option value={cameraId}>{cameraId}</option>}</FilterChip>
      <FilterChip label="Source" value={query.get('use_case') || ''} onChange={(value) => onChange('use_case', value)}><option value="">All</option>{Object.entries(USE_CASE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</FilterChip>
      <FilterChip label="Severity" value={query.get('severity') || ''} onChange={(value) => onChange('severity', value)}><option value="">All</option>{SEVERITIES.map((value) => <option key={value} value={value}>{value}</option>)}</FilterChip>
      <FilterChip label="Evidence" value={query.get('evidence') || ''} onChange={(value) => onChange('evidence', value)}><option value="">Any</option><option value="CAPTURED">Snapshot captured</option><option value="PENDING">Pending</option><option value="UNAVAILABLE">Unavailable</option></FilterChip>
      <details className="alert-filter-dates"><summary className="alert-filter-chip"><CalendarDays size={14} /><span>{from || to ? 'Date range selected' : 'Date range'}</span><ChevronDown size={12} /></summary><div className="alert-filter-date-panel">
        <label>From<input aria-label="From date" type="datetime-local" value={from} onChange={(event) => onChange('from', event.target.value)} /></label>
        <label>To<input aria-label="To date" type="datetime-local" value={to} onChange={(event) => onChange('to', event.target.value)} /></label>
        {cameraError && <span role="status">Camera registry unavailable: {cameraError}</span>}
      </div></details>
      <button type="button" className="alert-filter-clear" onClick={onClear}>Clear all{count > 0 ? ` · ${count}` : ''}</button>
    </div>
  </section>;
}
