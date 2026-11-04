import { Plug, PlugZap, RefreshCw } from 'lucide-react';
import { Link } from 'react-router-dom';
import { connectionView, formatSeconds, workerForAssignment, workerIsActive } from '../grillGateModel.js';
import { btnDanger, btnGhost, btnPrimary, Card, ErrorNote, Pill } from './ui.jsx';

const timeOf = (iso) => (iso ? new Date(iso).toLocaleTimeString() : '—');

/** Assignments from the common registry with their actual capture-worker health. */
export default function CameraConfigView({ items, selectedId, onSelect, workers, busy, actionError, onConnect, onDisconnect }) {
  const selected = items.find((item) => item.assignment.id === selectedId) ?? null;
  const worker = workerForAssignment(workers.workers, selectedId);
  const connection = connectionView(worker, { statusError: workers.error, loaded: workers.loaded });
  const active = workerIsActive(worker) && !workers.error;

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(320px,420px)_minmax(0,1fr)]">
      <Card title="Camera assignments" aside={<Link to="/regions?use_case=grill_gate" className="font-semibold text-[#8aa2ff] hover:underline">Manage in Regions &amp; Zones</Link>}>
        <ul className="space-y-2">
          {items.map((item) => {
            const state = connectionView(workerForAssignment(workers.workers, item.assignment.id), { statusError: workers.error, loaded: workers.loaded });
            const current = item.assignment.id === selectedId;
            return (
              <li key={item.assignment.id}>
                <button type="button" onClick={() => onSelect(item.assignment.id)} aria-pressed={current}
                  className={`w-full rounded-lg p-3 text-left ring-1 transition ${current ? 'bg-[#1b2a52] ring-[#5b7cfa]' : 'bg-[#0f1729] ring-[#22304d] hover:ring-[#3c5ba4]'}`}>
                  <span className="flex items-center justify-between gap-2">
                    <b className="text-sm text-slate-100">{item.camera?.code?.toUpperCase() ?? 'CAMERA'} · {item.camera?.name ?? item.assignment.camera_id}</b>
                    <Pill tone={state.tone}>{state.label}</Pill>
                  </span>
                  <span className="mt-1 block text-xs text-slate-400">
                    {item.location?.name ?? 'Unknown location'} · {item.camera?.sources?.[0]?.masked_source ?? 'No active source'}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </Card>

      <Card title={selected ? `Worker · ${selected.camera?.name ?? selected.assignment.camera_id}` : 'Worker'} aside={<Pill tone={connection.tone} dot>{connection.label}</Pill>}>
        <div className="flex flex-wrap items-center gap-2">
          {active ? (
            <button type="button" className={btnDanger} onClick={onDisconnect} disabled={Boolean(busy) || worker?.status === 'stopping'}>
              <Plug size={14} aria-hidden /> {busy === 'disconnect' ? 'Disconnecting…' : 'Disconnect camera'}
            </button>
          ) : (
            <button type="button" className={btnPrimary} onClick={onConnect} disabled={Boolean(busy) || !selected}>
              <PlugZap size={14} aria-hidden /> {busy === 'connect' ? 'Connecting…' : 'Connect camera'}
            </button>
          )}
          <button type="button" className={btnGhost} onClick={workers.refresh}><RefreshCw size={14} aria-hidden /> Refresh status</button>
          <span className="text-xs text-slate-400">{connection.detail}</span>
        </div>
        {actionError && <div className="mt-3"><ErrorNote>{actionError}</ErrorNote></div>}
        <dl className="mt-4 grid grid-cols-2 gap-4 border-t border-[#22304d] pt-4 text-xs sm:grid-cols-4">
          {[
            ['Worker status', worker?.status ?? (workers.error ? 'unknown' : 'not started')],
            ['Last frame', timeOf(worker?.last_frame_at)],
            ['Frame age', formatSeconds(worker?.frame_age_seconds)],
            ['Resolution', worker?.width && worker?.height ? `${worker.width}×${worker.height}` : '—'],
            ['Frames captured', worker?.sequence_number ?? '—'],
            ['Reconnect attempt', worker?.reconnect_attempt ?? '—'],
            ['Consumers', worker?.consumer_count ?? '—'],
            ['Source type', worker?.source_type ?? selected?.camera?.sources?.[0]?.source_type ?? '—'],
          ].map(([label, value]) => (
            <div key={label}><dt className="text-slate-400">{label}</dt><dd className="mt-0.5 font-semibold text-slate-100">{String(value)}</dd></div>
          ))}
        </dl>
        <p className="mt-4 text-[11px] text-slate-500">
          {workers.error ? `Last status check failed: ${workers.error}` : workers.checkedAt ? `Status checked ${workers.checkedAt.toLocaleTimeString()}` : 'Checking worker status…'}
        </p>
      </Card>
    </div>
  );
}
