import { useEffect, useRef, useState } from 'react';
import { Pencil } from 'lucide-react';

export default function InlineName({ type, entry, selected, onSelect, onRename, children }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(entry.name);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const input = useRef(null);
  const clickTimer = useRef(null);
  const cancelled = useRef(false);
  useEffect(() => { if (!editing) setName(entry.name); }, [entry.name, editing]);
  useEffect(() => () => clearTimeout(clickTimer.current), []);
  useEffect(() => { if (editing) input.current?.select(); }, [editing]);
  const begin = () => { clearTimeout(clickTimer.current); setError(''); setName(entry.name); cancelled.current = false; setEditing(true); };
  const cancel = () => { cancelled.current = true; setError(''); setName(entry.name); setEditing(false); };
  const save = async () => {
    if (cancelled.current || busy) return;
    const trimmed = name.trim();
    if (!trimmed || trimmed.length > 120) { setError('Name must be 1–120 characters.'); return; }
    if (trimmed === entry.name) { setEditing(false); return; }
    setBusy(true); setError('');
    try { await onRename(type, entry, trimmed); setEditing(false); }
    catch (failure) { setError(failure.message || 'Could not rename.'); }
    finally { setBusy(false); }
  };
  return <div role="button" tabIndex={0} aria-label={`${type} ${entry.name}`} aria-selected={selected} onClick={() => { if (!editing) { clearTimeout(clickTimer.current); clickTimer.current = setTimeout(onSelect, 550); } }} onDoubleClick={(event) => { event.preventDefault(); begin(); }} onKeyDown={(event) => {
    if (editing) return;
    if (event.key === 'F2') { event.preventDefault(); begin(); }
    else if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(); }
  }} className={`group w-full rounded-lg border px-3 py-2 text-left text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand ${selected ? 'border-brand bg-indigo-50 text-navy' : 'border-slate-200 bg-white hover:bg-slate-50'}`}>
    <span className="flex items-center justify-between gap-2">
      {editing ? <input ref={input} value={name} disabled={busy} maxLength={120} aria-label={`Rename ${type}`} onChange={(event) => setName(event.target.value)} onClick={(event) => event.stopPropagation()} onDoubleClick={(event) => event.stopPropagation()} onKeyDown={(event) => { event.stopPropagation(); if (event.key === 'Enter') { event.preventDefault(); save(); } else if (event.key === 'Escape') { event.preventDefault(); cancel(); } }} onBlur={save} className="min-w-0 flex-1 rounded border border-brand bg-white px-2 py-1 text-sm" /> : <b className="min-w-0 truncate">{entry.name}</b>}
      {!editing && <button type="button" aria-label={`Rename ${type} ${entry.name}`} title="Rename (F2)" onClick={(event) => { event.stopPropagation(); begin(); }} className="rounded p-1 text-slate-500 opacity-100 hover:text-brand focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand sm:opacity-0 sm:group-hover:opacity-100 sm:focus:opacity-100"><Pencil className="h-3.5 w-3.5" /></button>}
    </span>
    {children}
    {error && <span role="alert" className="mt-1 block text-xs text-red-700">{error}</span>}
  </div>;
}
