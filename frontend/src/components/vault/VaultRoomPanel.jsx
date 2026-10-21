import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, Bell, CheckCircle2, Clock3, DoorClosed, DoorOpen, Info, LockKeyhole, ShieldCheck, UserRound, UserRoundPlus, CircleAlert, Copy, Wifi, WifiOff } from 'lucide-react';
import Button from '../common/Button.jsx';
import ErrorMessage from '../common/ErrorMessage.jsx';
import { getSessionAlerts, getVaultSessions } from '../../api/vaultRoom.js';

const card = 'vault-card p-4 sm:p-5';
const stateNames = { IDLE:'Idle', ENTRY_BUFFER:'Entering', ACTIVE:'Session active', EXPIRED_OPEN:'Expired', CLOSED:'Closed' };
const mmss = (n) => `${String(Math.floor(Math.max(0, n ?? 0) / 60)).padStart(2,'0')}:${String(Math.max(0, n ?? 0) % 60).padStart(2,'0')}`;
const ALERT_NAMES = { COUNT_MISMATCH:'Count mismatch', EXCESS_PERSON:'Excess person', UNAUTHORIZED_ENTRY:'Unauthorized entry', FEED_LOST:'Feed lost', SESSION_EXPIRED:'Session expired' };
const END_REASONS = { AUTO_LOCK_NO_ENTRY:'no one entered', AUTO_LOCK_ROOM_EMPTY:'the room was empty for 60 seconds', CLOSED_BY_BUTTON:'closed manually' };
const localTime = (value) => value ? new Intl.DateTimeFormat(undefined, { hour:'2-digit', minute:'2-digit', second:'2-digit' }).format(new Date(value)) : '—';
const durationText = (seconds) => seconds == null ? 'ongoing' : `${Math.floor(seconds)} s`;

function useAlertClock(enabled) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!enabled) return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [enabled]);
  return now;
}

export function VaultRoomVideoOverlay({ roomState, connection, counting, mirrored = false }) {
  const [showBoxes, setShowBoxes] = useState(() => {
    try { return window.localStorage.getItem('vault-room-show-boxes') !== 'false'; } catch { return true; }
  });
  const state = roomState?.state ?? 'IDLE';
  const entry = roomState?.entry_buffer_remaining_seconds ?? 0;
  const remaining = roomState?.remaining_seconds;
  const alerts = roomState?.open_alerts ?? [];
  const has = (type) => alerts.some((alert) => alert.type === type);
  let banner = ['bg-slate-200 text-slate-800', 'No active session'];
  let countdown = false;
  if (roomState?.lock_countdown_remaining_seconds != null && roomState?.stable_count === 0 && roomState?.feed === 'LIVE') {
    banner = ['bg-[#0F1B3D] text-white', `Room empty ? locking in ${Math.ceil(roomState.lock_countdown_remaining_seconds)}s`]; countdown = true;
  } else if (has('EXCESS_PERSON')) banner = ['bg-[#FDE9E7] text-[#B3261E]', `Excess person detected ? ${roomState.stable_count ?? '?'} present, ${roomState.expected_persons ?? '?'} expected`];
  else if (has('UNAUTHORIZED_ENTRY')) banner = ['bg-[#FDE9E7] text-[#B3261E]', 'Unauthorized entry detected'];
  else if (has('COUNT_MISMATCH')) banner = ['bg-[#FFF4DC] text-[#6B4500]', roomState.stable_count === 0 ? 'Room empty' : `${roomState.stable_count ?? '?'} of ${roomState.expected_persons ?? '?'} present`];
  else if (has('FEED_LOST') || roomState?.feed === 'STALE') banner = ['bg-[#FFF4DC] text-[#6B4500]', 'Camera feed lost ? counting paused'];
  else if (roomState?.detector_status === 'unavailable' || counting?.status === 'unavailable') banner = ['bg-slate-200 text-[#55607A]', 'People counting unavailable'];
  else if (roomState?.detector_status === 'loading') banner = ['bg-slate-200 text-[#55607A]', 'Loading people-counting model...'];
  else if (state === 'ENTRY_BUFFER') banner = ['bg-blue-100 text-blue-900', `Entering... ${entry}s`];
  else if (state === 'ACTIVE' && roomState?.stable_count != null && roomState.stable_count === roomState.expected_persons) banner = ['bg-[#E6F6EE] text-[#0B7A4B]', `${roomState.stable_count} of ${roomState.expected_persons} present ? ${mmss(remaining)} left`];
  else if (state === 'ACTIVE') banner = remaining <= 60 ? ['bg-[#FFF4DC] text-[#6B4500]', '1 minute remaining'] : ['bg-[#E6F6EE] text-[#0B7A4B]', `Session active ? ${mmss(remaining)} left`];
  else if (state === 'EXPIRED_OPEN') banner = ['bg-[#FDE9E7] text-[#B3261E]', 'Session expired ? door still unlocked'];
  else if (state === 'CLOSED') banner = ['bg-slate-200 text-slate-800', roomState?.end_reason?.startsWith('AUTO_LOCK_')
    ? `Vault locked automatically: ${END_REASONS[roomState.end_reason] || 'automatic timeout'}`
    : 'Vault closed'];
  const width = counting?.imageWidth || 640;
  const height = counting?.imageHeight || 360;
  const count = roomState?.stable_count;
  const expected = roomState?.expected_persons;
  const boxTone = count == null || expected == null ? '#D18A00' : count > expected ? '#B3261E' : count === expected ? '#0B7A4B' : '#D18A00';
  const toggleBoxes = () => {
    const next = !showBoxes; setShowBoxes(next);
    try { window.localStorage.setItem('vault-room-show-boxes', String(next)); } catch { /* Optional preference only. */ }
  };
  return <>
    <span className="absolute left-3 top-3 z-10 inline-flex items-center gap-2 rounded-full bg-black/60 px-3 py-1.5 text-xs font-semibold text-white sm:left-4 sm:top-4"><span className="h-2 w-2 rounded-full bg-red-500" aria-hidden /> Live ? Vault room (demo)</span>
    <span className="absolute right-3 top-3 z-10 rounded-full bg-white px-3 py-1.5 text-xs font-bold text-[#0F1B3D] sm:right-4 sm:top-4">{stateNames[state]}</span>
    {(connection === 'reconnecting' || connection === 'offline') && <span className="absolute left-3 top-12 z-10 rounded-full bg-amber-100 px-3 py-1.5 text-xs font-semibold text-[#6B4500] sm:left-4">Reconnecting...</span>}
    <span className="absolute left-3 top-12 z-10 rounded-full bg-white/95 px-3 py-1.5 text-xs font-bold text-[#0F1B3D] sm:left-4">{count ?? '?'} of {expected ?? '?'} present</span>
    <button type="button" aria-pressed={showBoxes} onClick={toggleBoxes} className="absolute right-3 top-12 z-10 inline-flex min-h-11 items-center rounded-full bg-white/95 px-3 text-xs font-bold text-[#0F1B3D] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand sm:right-4">{showBoxes ? 'Hide boxes' : 'Show boxes'}</button>
    {showBoxes && counting?.tracks?.length > 0 && <svg aria-hidden className="pointer-events-none absolute inset-0 h-full w-full" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid slice">
      {counting.tracks.map((track) => {
        const boxWidth = track.w * width; const boxHeight = track.h * height;
        const x = (mirrored ? 1 - track.x - track.w : track.x) * width; const y = track.y * height;
        return <g key={track.track_id}><rect x={x} y={y} width={boxWidth} height={boxHeight} rx="8" fill="none" stroke={boxTone} strokeWidth="3" vectorEffect="non-scaling-stroke" />
          <rect x={x} y={Math.max(0, y - 26)} width="132" height="24" rx="6" fill={boxTone} />
          <text x={x + 8} y={Math.max(17, y - 9)} fill="white" fontSize="14" fontWeight="700">Person {track.track_id}</text></g>;
      })}
    </svg>}
    <div role="status" aria-live="polite" className={`absolute inset-x-3 bottom-3 z-10 rounded-lg px-4 py-3 text-center text-sm font-bold shadow-lg sm:inset-x-5 sm:bottom-5 ${banner[0]}`}>
      {countdown ? <><LockKeyhole className="mr-1 inline h-4 w-4" aria-hidden />Room empty ? locking in <span aria-hidden="true">{Math.ceil(roomState.lock_countdown_remaining_seconds)}s</span><span className="sr-only">Auto-lock countdown active</span></> : <>{state === 'ACTIVE' && remaining <= 60 ? <AlertTriangle className="mr-1 inline h-4 w-4" aria-hidden /> : <Info className="mr-1 inline h-4 w-4" aria-hidden />}{banner[1]}</>}
    </div>
  </>;
}

function TimerCard({ roomState, progress }) {
  const state = roomState?.state ?? 'IDLE';
  const entry = roomState?.entry_buffer_remaining_seconds ?? 0;
  const remaining = roomState?.remaining_seconds;
  const alert = state === 'EXPIRED_OPEN';
  const DoorIcon = roomState?.door === 'UNLOCKED' ? DoorOpen : DoorClosed;
  return <section className={card} aria-labelledby="room-timer-title">
    <h2 id="room-timer-title" className="vault-heading flex items-center gap-2"><Clock3 className="h-5 w-5 text-brand" aria-hidden /> Session timer</h2>
    {state === 'ENTRY_BUFFER' ? <p className="mt-3 text-3xl font-bold tabular-nums text-[#0F1B3D]">{entry}s <span className="text-sm font-medium text-[#55607A]">entry window</span></p>
      : state === 'ACTIVE' ? <><p className={`mt-3 text-3xl font-bold tabular-nums ${remaining <= 60 ? 'text-[#6B4500]' : 'text-[#0F1B3D]'}`}>{mmss(remaining)}</p>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100" aria-label="Session time remaining"><div className={`h-full transition-[width] motion-reduce:transition-none ${remaining <= 60 ? 'bg-amber-500' : 'bg-[#34479B]'}`} style={{ width:`${progress}%` }} /></div></>
      : <p className={`mt-3 text-2xl font-bold ${alert ? 'text-[#B3261E]' : 'text-[#55607A]'}`}>{alert ? 'Expired' : stateNames[state]}</p>}
    {roomState?.lock_countdown_remaining_seconds != null && roomState?.stable_count === 0 && roomState?.state !== 'CLOSED' && <p aria-live="off" className="mt-2 flex items-center gap-2 text-sm font-bold text-[#B3261E]"><LockKeyhole className="h-4 w-4" aria-hidden />Locking in {Math.ceil(roomState.lock_countdown_remaining_seconds)}s</p>}
    <div className="mt-4 flex items-center gap-2 border-t border-slate-100 pt-3 text-sm font-semibold text-[#0F1B3D]"><DoorIcon className="h-5 w-5" aria-hidden /> Door {roomState?.door === 'UNLOCKED' ? 'Unlocked' : 'Locked'}</div>
  </section>;
}

function CustodiansCard({ roomState }) {
  const employees = roomState?.employees ?? [];
  const required = roomState?.required_persons;
  return <section className={card} aria-labelledby="room-custodian-title">
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 id="room-custodian-title" className="vault-heading">Custodians</h2>
      {roomState?.test_mode && <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-bold text-[#6B4500]">TEST MODE · 1 person</span>}</div>
    <p className="mt-1 text-sm text-[#55607A]">{employees.length} of {required ?? '—'} custodians</p>
    {employees.length ? <ul className="mt-3 divide-y divide-slate-100">{employees.map((person) => <li key={`${person.slot}-${person.employee_id}`} className="flex items-start gap-3 py-3">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#E9EDFF] font-bold text-[#34479B]" aria-hidden>{(person.name || person.employee_id || '?').slice(0,1).toUpperCase()}</span>
      <div className="min-w-0 flex-1"><p className="font-semibold text-[#0F1B3D]">{person.name || person.employee_id}</p><p className="text-xs text-[#55607A]">{person.employee_id}{person.designation ? ` · ${person.designation}` : ''}{person.department ? ` · ${person.department}` : ''}</p>
        <span className="mt-1 inline-flex items-center gap-1 rounded-full bg-[#E6F6EE] px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-[#0B6B43]"><ShieldCheck className="h-3 w-3" aria-hidden /> Custodian {person.slot} · Authorization active</span></div>
    </li>)}</ul> : <p className="mt-3 text-sm text-[#55607A]">No custodians recorded.</p>}
  </section>;
}

function PresenceCard({ roomState }) {
  const count = roomState?.stable_count; const expected = roomState?.expected_persons;
  const feedLost = roomState?.feed === 'STALE' || roomState?.open_alerts?.some((item) => item.type === 'FEED_LOST');
  let status = 'Unknown'; let tone = 'bg-slate-100 text-[#55607A]';
  if (count == null) status = roomState?.feed === 'NONE' ? 'Waiting' : 'Unknown';
  else if (expected != null && count > expected) { status = 'Excess'; tone = 'bg-[#FDE9E7] text-[#B3261E]'; }
  else if (expected != null && count === expected) { status = 'OK'; tone = 'bg-[#E6F6EE] text-[#0B7A4B]'; }
  else if (roomState?.state === 'ENTRY_BUFFER') status = 'Waiting';
  else { status = 'Mismatch'; tone = 'bg-[#FFF4DC] text-[#6B4500]'; }
  const regular = Array.from({ length: Math.max(0, expected ?? 0) }, (_, i) => i);
  const extra = Array.from({ length: Math.max(0, (count ?? 0) - regular.length) }, (_, i) => i);
  return <section className={card} aria-labelledby="room-presence-title">
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 id="room-presence-title" className="vault-heading flex items-center gap-2"><UserRound className="h-5 w-5 text-brand" aria-hidden /> People in the room</h2>
      {roomState?.test_mode && <span className="rounded-full bg-[#FFF4DC] px-3 py-1 text-xs font-bold text-[#6B4500]">TEST MODE</span>}</div>
    <div className="mt-3 flex flex-wrap items-center gap-3"><p className="text-3xl font-bold tabular-nums text-[#0F1B3D]">{count ?? '?'} <span className="text-lg font-semibold text-[#55607A]">of {expected ?? '?'}</span></p><span className={`rounded-full px-3 py-1 text-xs font-bold ${tone}`}>{status}</span></div>
    {expected != null && <div className="mt-2 flex items-center gap-2" aria-label={`${count ?? 'Unknown'} people counted; ${expected} expected`}>
      {regular.map((slot) => <UserRound key={`slot-${slot}`} className={`h-6 w-6 ${count != null && count > slot ? 'fill-[#34479B] text-[#34479B]' : 'text-[#8790A5]'}`} aria-hidden />)}
      {extra.map((slot) => <UserRoundPlus key={`extra-${slot}`} className="h-6 w-6 text-[#B3261E]" aria-hidden />)}
    </div>}
    <p className="mt-3 inline-flex items-center gap-2 text-sm font-semibold text-[#55607A]">{feedLost ? <WifiOff className="h-4 w-4 text-[#6B4500]" aria-hidden /> : <Wifi className="h-4 w-4 text-[#0B7A4B]" aria-hidden />}{roomState?.feed === 'LIVE' ? 'Live' : feedLost ? 'Lost' : 'Waiting for feed'}</p>
    {roomState?.zones?.length > 0 && <div className="mt-4 border-t border-slate-100 pt-3"><h3 className="text-sm font-bold text-[#0F1B3D]">Zone occupancy</h3><ul className="mt-2 space-y-1">{roomState.zones.map((zone) => <li key={zone.id} className="flex items-center justify-between gap-3 text-sm"><span className="text-[#55607A]">{zone.name}</span><span className="font-semibold tabular-nums text-[#0F1B3D]">{zone.count}</span></li>)}</ul></div>}
  </section>;
}

function AlertsCard({ roomState }) {
  const open = roomState?.open_alerts ?? [];
  const history = [...(roomState?.alerts ?? [])].sort((a,b) => Date.parse(b.opened_at) - Date.parse(a.opened_at));
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!open.length && !history.some((item) => !item.closed_at)) return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [open.length, history.some((item) => !item.closed_at)]);
  const age = (alert) => alert.duration_seconds ?? (alert.opened_at ? Math.max(0, (now - Date.parse(alert.opened_at)) / 1000) : null);
  const copyLog = async () => {
    const text = history.map((item) => `${localTime(item.opened_at)}  ${(item.severity || 'info').toUpperCase()}  ${item.type}  ${item.message}  (${durationText(item.duration_seconds ?? age(item))})`).join('\n');
    try { await navigator.clipboard.writeText(text); } catch { /* Clipboard can be unavailable outside secure contexts. */ }
  };
  return <section className={card} aria-labelledby="room-alert-title"><h2 id="room-alert-title" className="vault-heading flex items-center gap-2"><Bell className="h-5 w-5" aria-hidden /> Alerts</h2>
    <h3 className="mt-4 text-sm font-bold text-[#0F1B3D]">Open alerts</h3>
    {open.length ? <ul className="mt-2 space-y-2">{open.map((alert) => <li key={alert.id} className={`rounded-lg border p-3 text-sm ${alert.severity === 'critical' ? 'border-red-200 bg-[#FDE9E7] text-[#B3261E]' : 'border-amber-200 bg-[#FFF4DC] text-[#6B4500]'}`}>
      <p className="flex items-center gap-2 font-bold"><CircleAlert className="h-4 w-4" aria-hidden />{ALERT_NAMES[alert.type]}</p><p className="mt-1">{alert.message}</p>
      <p className="mt-1 text-xs">since <time title={alert.opened_at}>{localTime(alert.opened_at)}</time> ? {durationText(age(alert))} ? {alert.count_at_open ?? '?'} of {alert.expected ?? '?'}</p>
    </li>)}</ul> : <p className="mt-2 text-sm text-[#55607A]">No active alerts</p>}
    <div className="mt-5 flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-bold text-[#0F1B3D]">Alert history (this session)</h3><button type="button" onClick={copyLog} disabled={!history.length} className="inline-flex min-h-11 items-center gap-2 rounded-lg px-3 text-sm font-semibold text-[#34479B] hover:bg-[#F4F6FB] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:text-slate-400"><Copy className="h-4 w-4" aria-hidden />Copy alert log</button></div>
    {history.length ? <ol className="mt-2 max-h-64 space-y-2 overflow-auto">{history.map((alert) => <li key={alert.id} className="rounded-lg border border-slate-200 p-3 text-sm text-[#0F1B3D]">
      <p className="font-semibold">{ALERT_NAMES[alert.type] || alert.type} ? {(alert.severity || 'info').toUpperCase()}</p><p className="mt-1 text-[#55607A]">{alert.message}</p>
      <p className="mt-1 text-xs text-[#55607A]">Opened <time title={alert.opened_at}>{localTime(alert.opened_at)}</time> ? {alert.closed_at ? <>Closed <time title={alert.closed_at}>{localTime(alert.closed_at)}</time></> : 'ongoing'} ? {durationText(age(alert))} ? {alert.count_at_open ?? '?'} of {alert.expected ?? '?'}</p>
    </li>)}</ol> : <p className="mt-2 text-sm text-[#55607A]">No alerts in this session</p>}
  </section>;
}

const labels = { SESSION_GRANTED:'Access granted', SESSION_STARTED:'Session started', SESSION_ENDING_SOON:'1 minute remaining', SESSION_EXPIRED:'Session expired', DOOR_LOCKED:'Door locked', SESSION_CLOSED:'Vault closed',
  PERSONS_PRESENT:'Persons present', ZONE_ENTERED:'Person entered zone', ZONE_LEFT:'Person left zone', ALERT_OPENED:'Alert opened', ALERT_CLOSED:'Alert closed', AUTO_LOCK_COUNTDOWN:'Auto-lock countdown started', AUTO_LOCK_CANCELLED:'Auto-lock cancelled', FEED_LOST:'Camera feed lost', FEED_RESTORED:'Camera feed restored', DETECTOR_UNAVAILABLE:'People-counting detector unavailable' };
function eventLabel(event) {
  if (event.type === 'PERSONS_PRESENT') return `${event.data?.count ?? event.data?.expected ?? ''} persons present`;
  if (event.type === 'ZONE_ENTERED' || event.type === 'ZONE_LEFT') return `Person ${event.type === 'ZONE_ENTERED' ? 'entered' : 'left'} ${event.data?.zone_name || event.data?.zone_id || 'zone'}`;
  if (event.type === 'ALERT_OPENED') return `Alert opened: ${ALERT_NAMES[event.data?.alert_type] || event.data?.alert_type || 'alert'}`;
  if (event.type === 'ALERT_CLOSED') return `Alert closed: ${ALERT_NAMES[event.data?.alert_type] || event.data?.alert_type || 'alert'}${event.data?.duration_seconds != null ? ` (${Math.round(event.data.duration_seconds)} s)` : ''}`;
  return labels[event.type] || event.message;
}
function EventTimeline({ events, clearEvents }) {
  const Icon = (event) => event.severity === 'critical' ? AlertTriangle : event.type === 'DOOR_LOCKED' || event.type === 'SESSION_CLOSED' ? LockKeyhole : CheckCircle2;
  return <section className={card} aria-labelledby="room-events-title"><div className="flex items-center justify-between gap-2"><h2 id="room-events-title" className="vault-heading">Event timeline</h2><button type="button" onClick={clearEvents} className="min-h-11 rounded px-2 text-sm font-semibold text-[#34479B] hover:bg-slate-50">Clear view</button></div>
    {events.length ? <ol className="mt-2 max-h-64 space-y-2 overflow-auto">{events.map((event) => { const EventIcon = Icon(event); return <li key={event.id} className={`flex gap-3 rounded-md p-2 text-sm ${event.severity === 'critical' ? 'bg-red-50 font-semibold text-[#B3261E]' : 'text-[#0F1B3D]'}`}>
      <EventIcon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden /><time className="shrink-0 text-xs text-[#55607A]">{event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : ''}</time><span>{eventLabel(event)}</span>
    </li>; })}</ol> : <p className="mt-2 text-sm text-[#55607A]">No events yet.</p>}
  </section>;
}

function Summary({ summary }) {
  if (!summary) return null;
  return <section className="vault-card border-[#BFE5D1] bg-[#E6F6EE] p-4" aria-live="polite"><h2 className="font-bold text-[#0B6B43]">Vault closed</h2>
    <p className="mt-1 text-sm text-[#0B6B43]">Duration: {mmss(summary.duration_seconds)} · End reason: {summary.end_reason} · {summary.expired_before_close ? 'Session had expired before closing.' : 'Session closed before expiry.'}</p>
  </section>;
}

function CloseDialog({ open, onCancel, onConfirm, closing, triggerRef, roomState }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    ref.current?.querySelector('button')?.focus();
    const keydown = (event) => {
      if (event.key === 'Escape') { event.preventDefault(); onCancel(); }
      if (event.key !== 'Tab') return;
      const nodes = [...ref.current.querySelectorAll('button:not([disabled])')];
      const first = nodes[0], last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', keydown);
    return () => { document.removeEventListener('keydown', keydown); triggerRef.current?.focus(); };
  }, [open, onCancel, triggerRef]);
  if (!open) return null;
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0B1224]/55 p-4" onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
    <section ref={ref} role="dialog" aria-modal="true" aria-labelledby="close-vault-title" className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
      <h2 id="close-vault-title" className="text-xl font-bold text-[#0F1B3D]">Close the vault door?</h2><p className="mt-2 text-sm text-[#55607A]">This will lock the simulated door and end the current room session.</p>
      {roomState?.stable_count != null && roomState.stable_count > 0 && <p className="mt-3 rounded-lg bg-[#FFF4DC] p-3 text-sm font-semibold text-[#6B4500]">{roomState.stable_count} {roomState.stable_count === 1 ? 'person is' : 'people are'} still detected inside.{roomState.stable_count !== roomState.expected_persons && <span className="block">Fewer or more than expected.</span>}</p>}
      <div className="mt-5 flex justify-end gap-3"><Button variant="secondary" onClick={onCancel} className="min-h-11">Cancel</Button><Button variant="danger" loading={closing} onClick={onConfirm} className="min-h-11">Close vault</Button></div>
    </section>
  </div>;
}

export default function VaultRoomPanel({ room, onRetry }) {
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const [sessions, setSessions] = useState([]);
  const [sessionsError, setSessionsError] = useState(null);
  const [selectedSession, setSelectedSession] = useState(null);
  const [selectedAlerts, setSelectedAlerts] = useState([]);
  const [selectedAlertsError, setSelectedAlertsError] = useState(null);
  const [loadingSession, setLoadingSession] = useState(null);
  const [announcedId, setAnnouncedId] = useState(null);
  const critical = room.criticalAlert;
  useEffect(() => {
    if (critical && critical.id !== announcedId) setAnnouncedId(critical.id);
  }, [critical?.id, announcedId]);
  const showSessions = async () => {
    if (!sessionsOpen) {
      setSessionsOpen(true);
      try { setSessions(await getVaultSessions(20)); setSessionsError(null); }
      catch (err) { setSessionsError(err.message || 'Could not load previous sessions.'); }
    } else setSessionsOpen(false);
  };
  return <>
    <div className="grid gap-4">
      {!room.roomState && !room.error && <section className={card} role="status">Connecting to vault room…</section>}
      {room.error && <div className="space-y-2"><ErrorMessage error={room.error} /><Button variant="secondary" onClick={onRetry} className="min-h-11">Retry connection</Button></div>}
      <PresenceCard roomState={room.roomState} />
      <TimerCard roomState={room.roomState} progress={room.countdownProgress} />
      <CustodiansCard roomState={room.roomState} />
      <AlertsCard roomState={room.roomState} />
      <EventTimeline events={room.events} clearEvents={room.clearEvents} />
      <Summary summary={room.closeSummary} />
      {sessionsError && <ErrorMessage error={sessionsError} />}
      <button type="button" onClick={showSessions} aria-expanded={sessionsOpen} className="min-h-11 self-start font-semibold text-[#34479B] hover:underline">{sessionsOpen ? 'Hide previous sessions' : 'Previous sessions'}</button>
      {sessionsOpen && <section className={`${card} overflow-x-auto`} aria-label="Previous vault sessions"><table className="w-full min-w-[690px] text-left text-xs"><thead><tr className="text-[#55607A]"><th className="p-2">Start time</th><th className="p-2">Duration</th><th className="p-2">Peak count</th><th className="p-2">Alert count</th><th className="p-2">End reason</th><th className="p-2">Expired</th></tr></thead>
        <tbody>{sessions.map((item) => <tr key={item.session_id} tabIndex={0} aria-label={`Load alerts for session ${item.session_id}`} onClick={async () => {
          setSelectedSession(item.session_id); setLoadingSession(item.session_id); setSelectedAlertsError(null);
          try { setSelectedAlerts(await getSessionAlerts(item.session_id)); } catch (err) { setSelectedAlertsError(err.message || 'Could not load session alerts.'); }
          finally { setLoadingSession(null); }
        }} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); event.currentTarget.click(); } }} className="cursor-pointer border-t border-slate-100 hover:bg-[#F4F6FB] focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand"><td className="p-2">{(item.started_at || item.granted_at) ? new Date(item.started_at || item.granted_at).toLocaleString() : '—'}</td><td className="p-2">{mmss(item.duration_seconds)}</td><td className="p-2">{item.peak_count ?? '—'}</td><td className="p-2">{item.alert_count ?? 0}</td><td className="p-2">{END_REASONS[item.end_reason] || item.end_reason}</td><td className="p-2">{item.expired_before_close ? 'Yes' : 'No'}</td></tr>)}</tbody></table>{!sessions.length && <p className="p-2 text-sm text-[#55607A]">No previous sessions.</p>}
        {selectedSession && <div className="mt-4 border-t border-slate-200 pt-3"><h3 className="font-bold text-[#0F1B3D]">Alerts for selected session</h3>{loadingSession && <p role="status" className="mt-2 text-sm text-[#55607A]">Loading alerts…</p>}{selectedAlertsError && <p role="alert" className="mt-2 text-sm text-[#B3261E]">{selectedAlertsError}</p>}{!loadingSession && !selectedAlertsError && (selectedAlerts.length ? <ul className="mt-2 space-y-2">{selectedAlerts.map((alert) => <li key={alert.id} className="rounded border border-slate-200 p-3 text-sm"><p className="font-semibold">{ALERT_NAMES[alert.type] || alert.type} · {alert.severity}</p><p>{alert.message}</p><p className="text-xs text-[#55607A]">{localTime(alert.opened_at)} · {alert.closed_at ? localTime(alert.closed_at) : 'ongoing'} · {durationText(alert.duration_seconds)}</p></li>)}</ul> : <p className="mt-2 text-sm text-[#55607A]">No alerts in this session.</p>)}</div>}</section>}
      {critical && announcedId === critical.id && <div role="alert" className="sr-only">Critical alert: {critical.message}</div>}
    </div>
  </>;
}

export function VaultRoomCloseAction({ room }) {
  const [showDialog, setShowDialog] = useState(false);
  const [closeError, setCloseError] = useState(null);
  const closeTrigger = useRef(null);
  const canClose = ['ENTRY_BUFFER','ACTIVE','EXPIRED_OPEN'].includes(room.roomState?.state);
  const cancelClose = useCallback(() => setShowDialog(false), []);
  const confirmClose = useCallback(async () => {
    try { await room.closeVault(); setShowDialog(false); setCloseError(null); }
    catch (err) { setCloseError(err.message || 'Could not close the vault.'); }
  }, [room.closeVault]);
  return <>
    {closeError && <ErrorMessage error={closeError} />}
    <div className="flex flex-wrap items-center gap-3"><button ref={closeTrigger} type="button" className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:cursor-not-allowed disabled:bg-slate-300" disabled={!canClose || room.connection === 'offline' || room.closing} onClick={() => setShowDialog(true)}><LockKeyhole className="h-4 w-4" aria-hidden />Close vault</button>
      {room.connection !== 'live' && <span className="inline-flex items-center gap-1 text-sm font-semibold text-[#6B4500]"><Info className="h-4 w-4" aria-hidden />Reconnecting...</span>}</div>
    <CloseDialog open={showDialog} onCancel={cancelClose} onConfirm={confirmClose} closing={room.closing} triggerRef={closeTrigger} roomState={room.roomState} />
  </>;
}
