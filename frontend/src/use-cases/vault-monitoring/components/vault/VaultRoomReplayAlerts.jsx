import { useEffect, useState } from 'react';
import { Bell } from 'lucide-react';
import { getRoomReplayEvidence } from '../../api/vaultRoom.js';
import CompactAlertCard from '../../../../components/alerts/CompactAlertCard.jsx';
import { describeError } from '../../../../utils/errors.js';
import { readVaultUi, saveVaultUi } from '../../utils/replayStorage.js';

export default function VaultRoomReplayAlerts({ replay, activity = null }) {
  const [scope, setScopeState] = useState(() => readVaultUi().scope);
  const setScope = (scope) => { setScopeState(scope); saveVaultUi({ scope }); };
  const [selected, setSelected] = useState(null);
  const [evidence, setEvidence] = useState('');
  const [error, setError] = useState('');
  useEffect(() => { setSelected(null); }, [replay.session_id]);
  useEffect(() => {
    setEvidence(''); setError('');
    if (!selected?.evidence_url || !replay.session_id) return undefined;
    const controller = new AbortController(); let url;
    getRoomReplayEvidence(replay.session_id, selected.id, controller.signal).then((blob) => {
      if (!controller.signal.aborted) { url = URL.createObjectURL(blob); setEvidence(url); }
    }).catch((err) => { if (!controller.signal.aborted) setError(describeError(err).message); });
    return () => { controller.abort(); if (url) URL.revokeObjectURL(url); };
  }, [selected?.id, replay.session_id]);
  const alerts = (replay.alerts || []).filter((item) => scope === 'active' ? item.status === 'OPEN' : item.status !== 'OPEN');
  return <section className="vault-card flex min-h-[440px] flex-col p-4 sm:p-5" aria-label="Replay test alerts">
    <h2 className="vault-heading flex flex-wrap items-center gap-2"><Bell className="h-5 w-5" aria-hidden />{activity ? 'Alerts & events' : 'Replay alerts'} <span className="rounded-full bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-900">Replay test</span></h2>
    <p className="mt-2 text-xs text-slate-500">Uses existing vault rules. These alerts and evidence stay separate from live monitoring.</p>
    <div role="tablist" aria-label="Replay alert scope" className="mt-3 flex flex-wrap gap-2">{['active', 'history', ...(activity ? ['events'] : [])].map((item) => <button type="button" role="tab" key={item} aria-selected={scope === item} onClick={() => setScope(item)} className={`min-h-9 rounded-lg px-3 text-xs font-semibold ${scope === item ? 'bg-[#34479B] text-white' : 'border border-slate-200'}`}>{item === 'events' ? `Events (${activity.total})` : `${item === 'active' ? 'Active' : 'History'} (${(replay.alerts || []).filter((alert) => item === 'active' ? alert.status === 'OPEN' : alert.status !== 'OPEN').length})`}</button>)}{scope === 'events' && <button type="button" className="activity-text-button ml-auto" onClick={() => activity.refresh()} disabled={activity.loading}>Refresh</button>}</div>
    {scope === 'events' ? activity.content : <>
    <div className="room-alert-list mt-3 space-y-3">{alerts.length ? alerts.map((item) => <CompactAlertCard key={item.id}
      alert={{ ...item, summary: item.message }} onSelect={() => setSelected(item)} />) : <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-500">No {scope} replay alerts.</p>}</div>
    {selected && <div className="mt-4 rounded-xl border border-slate-200 p-3" aria-label="Replay evidence">
      <div className="flex justify-between gap-3"><p className="text-sm font-semibold">{selected.type.replaceAll('_', ' ')}</p><button type="button" onClick={() => setSelected(null)} className="text-sm text-[#34479B]">Close</button></div>
      <p className="mt-2 text-sm">{selected.message}</p>
      {evidence && <img src={evidence} alt="Test evidence captured when the replay alert opened" className="mt-3 w-full rounded-lg" />}
      {error && <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}
      {!selected.evidence_url && <p className="mt-2 text-xs text-slate-500">No frame evidence available.</p>}
    </div>}
    </>}
  </section>;
}
