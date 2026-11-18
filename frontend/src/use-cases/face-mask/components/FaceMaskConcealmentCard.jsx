import { useState } from 'react';
import { Camera, ChevronRight } from 'lucide-react';
import { coveringLabel, fmtTime } from '../api/index.js';
import { incidentStatusForEvent } from '../pages/liveEventsModel.js';
import { coverageLabel, coverageSeverity, coverageTitle } from '../coverageModel.js';
import { Badge } from './ui.jsx';

export default function FaceMaskConcealmentCard({ event, common, thumbnailUrl, onSelect }) {
  const [imageFailed, setImageFailed] = useState(false);
  const severity = coverageSeverity(event, common?.severity) || '—';
  const incident = common?.status || incidentStatusForEvent(event.status);
  return <button type="button" onClick={() => onSelect(event.id)} aria-label={`${coverageTitle(event.coverage_state)}, ${event.camera_name || event.camera_id}, open event details`}
    className="flex w-full items-center gap-3 border-b border-slate-200 px-3 py-3 text-left hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-[#34479B]">
    <span className="flex h-16 w-20 shrink-0 items-center justify-center overflow-hidden rounded-md bg-slate-100 text-slate-400">
      {thumbnailUrl && !imageFailed ? <img src={thumbnailUrl} alt="Concealment event snapshot" className="h-full w-full object-cover" onError={() => setImageFailed(true)} /> : <Camera size={22} aria-label="Snapshot unavailable" />}
    </span>
    <span className="min-w-0 flex-1 text-xs leading-5 text-slate-700">
      <strong className="block text-sm text-slate-900">{coverageTitle(event.coverage_state)}</strong>
      <span className="block truncate">Camera: {event.camera_name || event.camera_id || '—'}</span>
      <span className="block">Covering: {coveringLabel(event.covering_type)} · Coverage: {coverageLabel(event.coverage_state)} · <Badge kind="sev" value={severity.toLowerCase()} text={severity} /></span>
      <span className="block">{fmtTime(event.first_seen)} · Score: {Number(event.score || 0).toFixed(2)} · Track ID: {event.track_id}</span>
      <span className="block">Incident: {incident} · Review: {event.status || '—'}</span>
    </span>
    <ChevronRight size={18} className="shrink-0 text-slate-500" aria-hidden="true" />
  </button>;
}
