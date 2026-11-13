import { useEffect, useRef, useState } from 'react';
import { Activity, ChevronRight, Clock3, DoorOpen, ImageOff, Info, UserRound, UsersRound, X } from 'lucide-react';
import { createPortal } from 'react-dom';
import { getActivityEvent, getActivityEvidence } from '../../api/activityEvents.js';
import { loadSnapshot } from '../../../../components/alerts/snapshotResource.js';
import { describeError } from '../../../../utils/errors.js';
import { ACTIVITY_CATEGORIES, activityCategory, activityTime, activityVideoTime, activityZone } from '../../utils/activityEvents.js';

const icons = { PERSON_DETECTED: UserRound, PERSON_ENTERED: UsersRound, SESSION_STARTED: Clock3, VAULT_AREA_ENTERED: DoorOpen };
function Snapshot({ event, large = false }) {
  const [retry, setRetry] = useState(0);
  const [image, setImage] = useState({ loading: false, url: '', error: '' });
  useEffect(() => {
    setImage({ loading: false, url: '', error: '' });
    if (!event.evidence_reference) return undefined;
    return loadSnapshot({ ref: event.id, fetchBlob: getActivityEvidence, onChange: setImage });
  }, [event.id, event.evidence_reference, retry]);
  if (!event.evidence_reference) return large ? <p className="activity-evidence-missing">No evidence was captured for this event.</p> : null;
  return <span className={large ? 'activity-evidence-full' : 'activity-evidence-thumb'}>
    {image.url && !image.error ? <img src={image.url} alt={large ? `Evidence for ${event.type}` : 'Activity evidence thumbnail'} onError={() => setImage((current) => ({ ...current, error: 'Evidence image could not be displayed.' }))} />
      : <span className="activity-evidence-placeholder"><ImageOff size={large ? 24 : 16} aria-hidden /><span>{image.loading ? 'Loading evidence…' : image.error || 'Evidence unavailable'}</span></span>}
    {large && image.error && <button type="button" onClick={() => setRetry((n) => n + 1)} className="activity-text-button">Retry evidence</button>}
  </span>;
}

function EventDetails({ event: initial }) {
  const [detail, setDetail] = useState(initial);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    getActivityEvent(initial.id, controller.signal).then((event) => { if (!controller.signal.aborted) setDetail(event); })
      .catch((err) => { if (!controller.signal.aborted) setError(describeError(err).message); });
    return () => controller.abort();
  }, [initial.id]);
  return <div className="activity-event-details">
    <p className="activity-event-description">{detail.description || 'Activity recorded.'}</p>
    {error && <p role="alert" className="activity-error">Could not refresh event details: {error}</p>}
    <Snapshot event={detail} large />
    <dl className="activity-detail-grid">
      {Object.entries({ Event: detail.type, 'Video time': activityVideoTime(detail.video_timestamp_seconds),
        Recorded: Number.isFinite(Date.parse(detail.created_at)) ? new Date(detail.created_at).toLocaleString() : 'Unavailable',
        'Tracking IDs': detail.track_ids?.join(', ') || 'Not recorded', 'Person count': detail.person_count ?? 'Not recorded',
        Zone: activityZone(detail.zone_id), Source: detail.source, 'Camera ID': detail.camera_id,
        'Session ID': detail.session_id, Mode: detail.replay ? 'Replay test' : detail.test_mode ? 'Test mode' : 'Live monitoring' }).map(([label, value]) =>
        <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
    </dl>
    {detail.metadata && Object.keys(detail.metadata).length > 0 && <details className="activity-metadata"><summary>Additional event details</summary><pre>{JSON.stringify(detail.metadata, null, 2)}</pre></details>}
  </div>;
}

function ActivityDialog({ title, onClose, children }) {
  const ref = useRef(null);
  useEffect(() => {
    const trigger = document.activeElement;
    const dialog = ref.current; dialog.showModal();
    return () => { dialog.close(); if (trigger?.isConnected) trigger.focus(); };
  }, []);
  return createPortal(<dialog ref={ref} aria-label={title} className="vault-activity-dialog" onCancel={onClose} onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="activity-dialog-heading"><h2>{title}</h2><button type="button" aria-label="Close activity viewer" onClick={onClose}><X size={20} /></button></div>
    <div className="activity-dialog-body">{children}</div>
  </dialog>, document.body);
}

export default function VaultActivityEvents({ feed, status, replay }) {
  const [category, setCategory] = useState('All');
  const [selected, setSelected] = useState(null);
  const [logOpen, setLogOpen] = useState(false);
  useEffect(() => { setCategory('All'); setSelected(null); setLogOpen(false); }, [feed.key]);
  const filtered = feed.items.filter((event) => category === 'All' || activityCategory(event.type) === category);
  const completed = ['completed', 'stopped', 'error'].includes(status);
  const close = () => { setSelected(null); setLogOpen(false); };
  const timeline = (expanded = false) => <>
    {feed.loading && !feed.items.length && <div role="status" className="activity-loading">Loading activity events…</div>}
    {feed.error && <div role="alert" className="activity-error">{describeError(feed.error).message}<button type="button" onClick={() => feed.refresh()} className="activity-text-button">Retry events</button></div>}
    {!feed.loading && !feed.error && !filtered.length && <div className="activity-empty"><Info size={20} aria-hidden /><p>{!feed.sessionId ? replay ? 'Choose and process a video to view its activity events.' : 'Activity events will appear when a monitoring session starts.' : category !== 'All' ? `No ${category.toLowerCase()} events in the loaded history.` : completed ? 'No activity events were recorded for this replay.' : 'No activity events yet. New events appear here automatically.'}</p></div>}
    <ol className={`activity-timeline ${expanded ? 'is-expanded' : ''}`} aria-label="Activity event timeline">
      {filtered.map((event) => { const Icon = icons[event.type] || Activity; return <li key={event.id}>
        <button type="button" className="activity-event-row" aria-label={`View ${event.type} at ${activityTime(event)}`} onClick={() => setSelected(event)}>
          <span className={`activity-event-icon tone-${activityCategory(event.type).toLowerCase()}`}><Icon size={17} aria-hidden /></span>
          <span className="activity-event-content"><strong>{event.type}</strong><span className="activity-event-description">{event.description || 'Activity recorded.'}</span>
            <span className="activity-event-source">Vault Room Camera{event.replay ? ' · Replay test' : ''}</span>
            <span className="activity-event-facts">{event.track_ids?.length ? `Track ${event.track_ids.join(', ')}` : `${event.person_count ?? 0} people`}{event.person_count > 1 && event.track_ids?.length ? ` · ${event.person_count} people` : ''}{event.zone_id ? ` · ${activityZone(event.zone_id)}` : ''}</span>
          </span>
          <span className="activity-event-trailing"><time dateTime={event.created_at} title={event.created_at}>{activityTime(event)}</time>{event.evidence_reference && <Snapshot event={event} />}<ChevronRight size={15} aria-hidden /></span>
        </button>
      </li>; })}
    </ol>
    {feed.hasMore && <button type="button" onClick={feed.loadMore} disabled={feed.loadingMore || feed.loading} className="activity-load-more">{feed.loadingMore ? 'Loading more events…' : 'Load more events'}</button>}
  </>;
  return <div className="vault-activity-events">
    <div role="group" aria-label="Activity event category" className="activity-filter-pills">{ACTIVITY_CATEGORIES.map((item) => <button type="button" key={item} aria-pressed={category === item} onClick={() => setCategory(item)}>{item}</button>)}</div>
    {timeline()}
    {completed && feed.sessionId && <p className="activity-completed" role="status">{status === 'completed' ? 'Processing complete' : status === 'stopped' ? 'Processing stopped' : 'Processing ended with an error'} · {feed.total} recorded {feed.total === 1 ? 'event' : 'events'}</p>}
    <button type="button" className="activity-text-button activity-open-log" onClick={() => setLogOpen(true)}>Open Event Log ›</button>
    {(selected || logOpen) && <ActivityDialog title={selected ? selected.type : 'Activity Event Log'} onClose={close}>
      {selected ? <>{logOpen && <button type="button" className="activity-text-button" onClick={() => setSelected(null)}>Back to event log</button>}<EventDetails key={selected.id} event={selected} /></> : <><p className="activity-log-note">{feed.total} events in this session · oldest first</p>{timeline(true)}</>}
    </ActivityDialog>}
  </div>;
}
