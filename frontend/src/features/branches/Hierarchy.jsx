import { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { Search, Video } from 'lucide-react';
import { useActiveBranch } from './ActiveBranch.jsx';
import { platformApi } from './api.js';
import CameraDrawer from './CameraDrawer.jsx';
import { countLabel } from './countLabel.js';
import InlineName from './InlineName.jsx';
import { persistSelection, selectionFromSearch, sameScope } from './scopeState.js';

const card = 'rounded-xl border border-slate-200 bg-white p-4 shadow-sm';

function AddName({ type, parentId, onDone, onClose }) {
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const save = async (event) => {
    event.preventDefault(); setBusy(true); setError('');
    try {
      await platformApi(type === 'zone' ? '/zones' : '/cities', { method: 'POST', body: JSON.stringify(type === 'zone' ? { name } : { name, zone_id: parentId }) });
      onDone(); onClose();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  return <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/50 p-4" role="presentation"><form onSubmit={save} role="dialog" aria-modal="true" aria-label={`Add ${type}`} className={`${card} w-full max-w-sm space-y-4`}><h2 className="text-lg font-semibold text-navy">Add {type}</h2><label className="block text-sm">Name<input autoFocus required minLength={2} maxLength={120} value={name} onChange={(e) => setName(e.target.value)} className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2" /></label>{error && <p role="alert" className="text-sm text-red-700">{error}</p>}<div className="flex justify-end gap-2"><button type="button" onClick={onClose} className="rounded-md border px-3 py-2 text-sm">Cancel</button><button disabled={busy} className="rounded-md bg-brand px-3 py-2 text-sm text-white disabled:opacity-50">Save</button></div></form></div>;
}

export default function Hierarchy() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const zoneId = params.get('zone') || '';
  const cityId = params.get('city') || '';
  const branchId = params.get('branch') || '';
  const [zones, setZones] = useState([]);
  const [cities, setCities] = useState([]);
  const [branches, setBranches] = useState({ items: [], total: 0 });
  const [cameras, setCameras] = useState([]);
  const [selectedBranch, setSelectedBranch] = useState(null);
  const [search, setSearch] = useState('');
  const [limit, setLimit] = useState(5);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState('');
  const [flash, setFlash] = useState(null);
  const { scope, setScope, reconnecting, notice, clearNotice } = useActiveBranch();
  const zone = zones.find((entry) => entry.id === zoneId);
  const city = cities.find((entry) => entry.id === cityId);
  const branch = branches.items.find((entry) => entry.id === branchId) || (selectedBranch?.id === branchId ? selectedBranch : null);
  const inDrawer = location.pathname.endsWith('/cameras/new');

  const loadZones = () => platformApi('/zones').then(setZones).catch((e) => setError(e.message)).finally(() => setLoading(false));
  useEffect(() => {
    if (![...params.keys()].some((key) => ['zone', 'city', 'branch'].includes(key))) {
      const restored = selectionFromSearch(location.search);
      if ([...restored.keys()].length) setParams(restored, { replace: true });
    }
    loadZones();
  }, []);
  useEffect(() => {
    if (!location.search && [...selectionFromSearch('')].length) return;
    persistSelection(params);
  }, [params, location.search]);
  useEffect(() => {
    setCities([]); setBranches({ items: [], total: 0 }); setCameras([]);
    if (!zoneId) return;
    platformApi(`/cities?zone_id=${encodeURIComponent(zoneId)}`).then(setCities).catch((e) => setError(e.message));
  }, [zoneId]);
  useEffect(() => {
    setBranches({ items: [], total: 0 }); setCameras([]);
    if (!cityId) return;
    const timer = setTimeout(() => platformApi(`/branches?city_id=${encodeURIComponent(cityId)}&search=${encodeURIComponent(search)}&limit=${limit}`).then(setBranches).catch((e) => setError(e.message)), 200);
    return () => clearTimeout(timer);
  }, [cityId, search, limit]);
  useEffect(() => {
    setCameras([]);
    if (!branchId) return;
    platformApi(`/branches/${encodeURIComponent(branchId)}/cameras`).then(setCameras).catch((e) => setError(e.message));
    platformApi(`/branches/${encodeURIComponent(branchId)}`).then(setSelectedBranch).catch((e) => setError(e.message));
  }, [branchId]);

  const select = (kind, id) => {
    const next = new URLSearchParams();
    if (!id && kind === 'zone') next.set('all', '1');
    if (kind === 'zone' && id) next.set('zone', id);
    if (kind === 'city' || kind === 'branch') { if (zoneId) next.set('zone', zoneId); if (id || kind === 'branch') next.set('city', kind === 'city' ? id : cityId); }
    if (kind === 'branch' && id) next.set('branch', id);
    setSearch(''); setLimit(5); setParams(next);
  };
  const apply = () => {
    if (branch) setScope({ type: 'branch', id: branch.id, code: branch.code, name: branch.name, subtitle: `${branch.code} · ${city?.name || ''}` });
    else if (city) setScope({ type: 'city', id: city.id, name: city.name, subtitle: zone?.name || '' });
    else if (zone) setScope({ type: 'zone', id: zone.id, name: zone.name, subtitle: 'Zone' });
    else setScope(null);
  };
  const refresh = () => { loadZones(); if (cityId) platformApi(`/branches?city_id=${cityId}&limit=${limit}`).then(setBranches); };
  const rename = async (type, entry, name) => {
    const update = (row) => row.id === entry.id ? { ...row, name } : row;
    if (type === 'zone') setZones((rows) => rows.map(update));
    if (type === 'city') setCities((rows) => rows.map(update));
    if (type === 'branch') { setBranches((rows) => ({ ...rows, items: rows.items.map(update) })); setSelectedBranch((row) => row?.id === entry.id ? update(row) : row); }
    try {
      const changed = await platformApi(`/${type}s/${encodeURIComponent(entry.id)}`, { method: 'PATCH', body: JSON.stringify({ name, updated_at: entry.updated_at || null }) });
      const replace = (row) => row.id === entry.id ? { ...row, ...changed } : row;
      if (type === 'zone') setZones((rows) => rows.map(replace));
      if (type === 'city') setCities((rows) => rows.map(replace));
      if (type === 'branch') { setBranches((rows) => ({ ...rows, items: rows.items.map(replace) })); setSelectedBranch((row) => row?.id === entry.id ? replace(row) : row); }
      setScope((old) => old?.type === type && old?.id === entry.id ? { ...old, name: changed.name } : old);
      setFlash({ kind: 'success', text: `${type[0].toUpperCase()}${type.slice(1)} renamed.` });
    } catch (failure) {
      const rollback = (row) => row.id === entry.id ? entry : row;
      if (type === 'zone') setZones((rows) => rows.map(rollback));
      if (type === 'city') setCities((rows) => rows.map(rollback));
      if (type === 'branch') { setBranches((rows) => ({ ...rows, items: rows.items.map(rollback) })); setSelectedBranch((row) => row?.id === entry.id ? entry : row); }
      setFlash({ kind: 'error', text: failure.message || 'Rename failed.' });
      throw failure;
    }
  };

  return <div className="mx-auto max-w-[1440px] space-y-4">
    <div><p className="text-xs text-slate-500">Branches › Branch Hierarchy</p><h1 className="mt-1 text-2xl font-semibold text-navy">Branch Hierarchy</h1><p className="text-sm text-slate-500">Drill down Zone → City → Branch. Cameras load only for the branch you select.</p></div>
    {error && <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    {flash && <div role="status" className={`flex justify-between rounded-md p-3 text-sm ${flash.kind === 'error' ? 'bg-red-50 text-red-700' : 'bg-emerald-50 text-emerald-700'}`}><span>{flash.text}</span><button type="button" onClick={() => setFlash(null)} aria-label="Dismiss notification">×</button></div>}
    {notice && <p role="status" className="rounded-md bg-amber-50 p-3 text-sm text-amber-800">{notice} <button onClick={clearNotice} className="underline">Dismiss</button></p>}
    <div className={`${card} flex flex-wrap items-center justify-between gap-3`}><div className="flex flex-wrap items-center gap-2 text-sm text-navy"><span className="rounded-full bg-slate-100 px-3 py-1">{zone?.name || (zoneId ? 'Loading zone…' : 'All zones')}</span><span>›</span><span className="rounded-full bg-slate-100 px-3 py-1">{city?.name || (cityId ? 'Loading city…' : 'All cities')}</span><span>›</span><span className="rounded-full bg-indigo-50 px-3 py-1 font-medium">{branch?.name || (branchId ? 'Loading branch…' : 'All branches')}</span><span className="ml-2 text-xs text-slate-500">Scope: {branch ? '1 branch' : city ? countLabel(branches.total, 'branch') : zone ? countLabel(zone.branch_count, 'branch') : 'all branches'}{branch ? ` · ${countLabel(cameras.length, 'camera')}` : ''}</span>{reconnecting && <span className="text-xs text-amber-700">Reconnecting…</span>}</div><button type="button" onClick={apply} disabled={Boolean((zoneId && !zone) || (cityId && !city) || (branchId && !branch)) || sameScope(scope, branch ? 'branch' : city ? 'city' : zone ? 'zone' : '', branch?.id || city?.id || zone?.id)} className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white disabled:opacity-60">{sameScope(scope, branch ? 'branch' : city ? 'city' : zone ? 'zone' : '', branch?.id || city?.id || zone?.id) ? 'Active' : `Apply as active ${branch ? 'branch' : 'scope'}`}</button></div>
    <div className="grid gap-4 md:grid-cols-3">
      <section className={card}><div className="mb-3 flex items-center justify-between"><h2 className="font-semibold text-navy">1 · Zone</h2><button onClick={() => setModal('zone')} className="text-xs font-medium text-brand">+ Add zone</button></div>{loading ? <p className="text-sm text-slate-500">Loading zones…</p> : zones.length ? <div className="space-y-2">{zones.map((entry) => <InlineName key={entry.id} type="zone" entry={entry} selected={entry.id === zoneId} onSelect={() => select('zone', entry.id)} onRename={rename}><span className="text-xs text-slate-500">{countLabel(entry.city_count, 'city')} · {countLabel(entry.branch_count, 'branch')}</span></InlineName>)}</div> : <p className="text-sm text-slate-500">No zones yet. Add a zone to begin.</p>}</section>
      <section className={card}><div className="mb-3 flex items-center justify-between"><h2 className="font-semibold text-navy">2 · City</h2><button disabled={!zoneId} onClick={() => setModal('city')} className="text-xs font-medium text-brand disabled:text-slate-400">+ Add city</button></div>{!zoneId ? <p className="text-sm text-slate-500">Select a zone first.</p> : cities.length ? <div className="space-y-2">{cities.map((entry) => <InlineName key={entry.id} type="city" entry={entry} selected={entry.id === cityId} onSelect={() => select('city', entry.id)} onRename={rename}><span className="text-xs text-slate-500">{countLabel(entry.branch_count, 'branch')}</span></InlineName>)}</div> : <p className="text-sm text-slate-500">No cities yet. + Add city</p>}</section>
      <section className={card}><div className="mb-3 flex items-center justify-between"><h2 className="font-semibold text-navy">3 · Branch</h2><Link to={`/branches/new?zone=${zoneId}&city=${cityId}`} className="text-xs font-medium text-brand">+ Add branch</Link></div>{cityId && <label className="mb-3 flex items-center gap-2 rounded-md border px-2"><Search className="h-4 w-4 text-slate-400" /><input aria-label="Search branch or code" placeholder="Search branch or code" value={search} onChange={(e) => setSearch(e.target.value)} className="w-full py-2 text-sm outline-none" /></label>}{!cityId ? <p className="text-sm text-slate-500">Select a city first.</p> : branches.items.length ? <div className="space-y-2">{branches.items.map((entry) => <InlineName key={entry.id} type="branch" entry={entry} selected={entry.id === branchId} onSelect={() => select('branch', entry.id)} onRename={rename}><span className="text-xs text-slate-500">{entry.code} · {countLabel(entry.camera_count, 'camera')}</span></InlineName>)}{branches.total > branches.items.length && <button onClick={() => setLimit((value) => value + 20)} className="text-xs font-medium text-brand">+ {branches.total - branches.items.length} more branches</button>}</div> : <p className="text-sm text-slate-500">No branches yet. Add a branch.</p>}</section>
    </div>
    {branchId && <section className={card}><div className="mb-4 flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold text-navy">4 · Cameras · {branch?.name || 'Selected branch'}</h2><p className="text-xs text-slate-500">Loaded only for this branch. Pick a different branch above to reload the list.</p>{cameras.some((camera) => camera.status === 'recorded') && <span className="rounded-full bg-indigo-50 px-2 py-1 text-xs text-brand">{cameras.filter((camera) => camera.status === 'recorded').length} recorded</span>}</div><Link to={`/branches/hierarchy/cameras/new?zone=${zoneId}&city=${cityId}&branch=${branchId}`} className="rounded-md bg-brand px-3 py-2 text-sm text-white">+ Add camera</Link></div>{cameras.length ? <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{cameras.map((camera) => <div key={camera.id} className="overflow-hidden rounded-lg border"><div className="grid h-28 place-items-center bg-navy text-slate-400"><Video className="h-5 w-5" /></div><div className="p-3"><span className="text-xs text-slate-500">{camera.status === 'recorded' ? 'Recorded' : camera.status === 'live' ? 'Live' : 'Offline'}</span><h3 className="text-sm font-semibold">{camera.code} · {camera.name}</h3><p className="text-xs text-slate-500">{camera.width ? `${camera.width}×${camera.height} · ${camera.codec || 'Unknown codec'}` : 'No recent frame'}</p></div></div>)}</div> : <p className="text-sm text-slate-500">No cameras in this branch yet.</p>}</section>}
    {modal && <AddName type={modal} parentId={zoneId} onClose={() => setModal('')} onDone={refresh} />}
    {inDrawer && branchId && <CameraDrawer branchId={branchId} onClose={() => navigate(`/branches/hierarchy?zone=${zoneId}&city=${cityId}&branch=${branchId}`)} onCameraAdded={() => platformApi(`/branches/${branchId}/cameras`).then(setCameras)} onSaved={() => { platformApi(`/branches/${branchId}/cameras`).then(setCameras); navigate(`/branches/hierarchy?zone=${zoneId}&city=${cityId}&branch=${branchId}`, { state: { success: 'Cameras added.' } }); }} />}
  </div>;
}
