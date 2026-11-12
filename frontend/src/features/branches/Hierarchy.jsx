import { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { Check, Search, Video } from 'lucide-react';
import { useActiveBranch } from './ActiveBranch.jsx';
import { platformApi } from './api.js';
import CameraDrawer from './CameraDrawer.jsx';

const card = 'rounded-xl border border-slate-200 bg-white p-4 shadow-sm';
const item = (active) => `w-full rounded-lg border px-3 py-2 text-left text-sm ${active ? 'border-brand bg-indigo-50 text-navy' : 'border-slate-200 bg-white hover:bg-slate-50'}`;

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
  const [search, setSearch] = useState('');
  const [limit, setLimit] = useState(5);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState('');
  const { setScope } = useActiveBranch();
  const zone = zones.find((entry) => entry.id === zoneId);
  const city = cities.find((entry) => entry.id === cityId);
  const branch = branches.items.find((entry) => entry.id === branchId);
  const inDrawer = location.pathname.endsWith('/cameras/new');

  const loadZones = () => platformApi('/zones').then(setZones).catch((e) => setError(e.message)).finally(() => setLoading(false));
  useEffect(() => { loadZones(); }, []);
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
  }, [branchId]);

  const select = (kind, id) => {
    const next = new URLSearchParams();
    if (kind === 'zone' && id) next.set('zone', id);
    if (kind === 'city' || kind === 'branch') { if (zoneId) next.set('zone', zoneId); if (id || kind === 'branch') next.set('city', kind === 'city' ? id : cityId); }
    if (kind === 'branch' && id) next.set('branch', id);
    setSearch(''); setLimit(5); setParams(next);
  };
  const apply = () => {
    if (branch) setScope({ type: 'branch', id: branch.id, name: branch.name, subtitle: `${branch.code} · ${city?.name || ''}` });
    else if (city) setScope({ type: 'city', id: city.id, name: city.name, subtitle: zone?.name || '' });
    else if (zone) setScope({ type: 'zone', id: zone.id, name: zone.name, subtitle: 'Zone' });
    else setScope(null);
  };
  const refresh = () => { loadZones(); if (cityId) platformApi(`/branches?city_id=${cityId}&limit=${limit}`).then(setBranches); };

  return <div className="mx-auto max-w-[1440px] space-y-4">
    <div><p className="text-xs text-slate-500">Branches › Branch Hierarchy</p><h1 className="mt-1 text-2xl font-semibold text-navy">Branch Hierarchy</h1><p className="text-sm text-slate-500">Drill down Zone → City → Branch. Cameras load only for the branch you select.</p></div>
    {error && <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    <div className={`${card} flex flex-wrap items-center justify-between gap-3`}><div className="flex flex-wrap items-center gap-2 text-sm text-navy"><span className="rounded-full bg-slate-100 px-3 py-1">{zone?.name || 'All zones'}</span><span>›</span><span className="rounded-full bg-slate-100 px-3 py-1">{city?.name || 'All cities'}</span><span>›</span><span className="rounded-full bg-indigo-50 px-3 py-1 font-medium">{branch?.name || 'All branches'}</span><span className="ml-2 text-xs text-slate-500">Scope: {branch ? '1 branch' : city ? `${branches.total} branches` : zone ? `${zone.branch_count} branches` : 'all branches'}{branch ? ` · ${cameras.length} cameras` : ''}</span></div><button type="button" onClick={apply} className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white">Apply as active {branch ? 'branch' : 'scope'}</button></div>
    <div className="grid gap-4 md:grid-cols-3">
      <section className={card}><div className="mb-3 flex items-center justify-between"><h2 className="font-semibold text-navy">1 · Zone</h2><button onClick={() => setModal('zone')} className="text-xs font-medium text-brand">+ Add zone</button></div>{loading ? <p className="text-sm text-slate-500">Loading zones…</p> : zones.length ? <div className="space-y-2">{zones.map((entry) => <button key={entry.id} onClick={() => select('zone', entry.id)} className={item(entry.id === zoneId)}><span className="flex justify-between gap-2"><b className="truncate">{entry.name}</b>{entry.id === zoneId && <Check className="h-4 w-4" />}</span><span className="text-xs text-slate-500">{entry.city_count} cities · {entry.branch_count} branches</span></button>)}</div> : <p className="text-sm text-slate-500">No zones yet. Add a zone to begin.</p>}</section>
      <section className={card}><div className="mb-3 flex items-center justify-between"><h2 className="font-semibold text-navy">2 · City</h2><button disabled={!zoneId} onClick={() => setModal('city')} className="text-xs font-medium text-brand disabled:text-slate-400">+ Add city</button></div>{!zoneId ? <p className="text-sm text-slate-500">Select a zone first.</p> : cities.length ? <div className="space-y-2">{cities.map((entry) => <button key={entry.id} onClick={() => select('city', entry.id)} className={item(entry.id === cityId)}><span className="flex justify-between gap-2"><b>{entry.name}</b>{entry.id === cityId && <Check className="h-4 w-4" />}</span><span className="text-xs text-slate-500">{entry.branch_count} branches</span></button>)}</div> : <p className="text-sm text-slate-500">No cities yet. + Add city</p>}</section>
      <section className={card}><div className="mb-3 flex items-center justify-between"><h2 className="font-semibold text-navy">3 · Branch</h2><Link to={`/branches/new?zone=${zoneId}&city=${cityId}`} className="text-xs font-medium text-brand">+ Add branch</Link></div>{cityId && <label className="mb-3 flex items-center gap-2 rounded-md border px-2"><Search className="h-4 w-4 text-slate-400" /><input aria-label="Search branch or code" placeholder="Search branch or code" value={search} onChange={(e) => setSearch(e.target.value)} className="w-full py-2 text-sm outline-none" /></label>}{!cityId ? <p className="text-sm text-slate-500">Select a city first.</p> : branches.items.length ? <div className="space-y-2">{branches.items.map((entry) => <button key={entry.id} onClick={() => select('branch', entry.id)} className={item(entry.id === branchId)}><span className="flex justify-between gap-2"><b className="truncate"><span className={`mr-2 inline-block h-2 w-2 rounded-full ${entry.status === 'active' ? 'bg-emerald-500' : 'bg-slate-400'}`} />{entry.name}</b>{entry.id === branchId && <Check className="h-4 w-4 shrink-0" />}</span><span className="text-xs text-slate-500">{entry.code} · {entry.camera_count} cameras</span></button>)}{branches.total > branches.items.length && <button onClick={() => setLimit((value) => value + 20)} className="text-xs font-medium text-brand">+ {branches.total - branches.items.length} more branches</button>}</div> : <p className="text-sm text-slate-500">No branches yet. Add a branch.</p>}</section>
    </div>
    {branchId && <section className={card}><div className="mb-4 flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold text-navy">4 · Cameras · {branch?.name || 'Selected branch'}</h2><p className="text-xs text-slate-500">Loaded only for this branch. Pick a different branch above to reload the list.</p></div><Link to={`/branches/hierarchy/cameras/new?zone=${zoneId}&city=${cityId}&branch=${branchId}`} className="rounded-md bg-brand px-3 py-2 text-sm text-white">+ Add camera</Link></div>{cameras.length ? <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{cameras.map((camera) => <div key={camera.id} className="overflow-hidden rounded-lg border"><div className="grid h-28 place-items-center bg-navy text-slate-400"><Video className="h-5 w-5" /></div><div className="p-3"><span className="text-xs text-slate-500">{camera.status === 'live' ? 'Live' : 'Offline'}</span><h3 className="text-sm font-semibold">{camera.code} · {camera.name}</h3><p className="text-xs text-slate-500">{camera.width ? `${camera.width}×${camera.height} · ${camera.codec || 'Unknown codec'}` : 'No recent frame'}</p></div></div>)}</div> : <p className="text-sm text-slate-500">No cameras in this branch yet.</p>}</section>}
    {modal && <AddName type={modal} parentId={zoneId} onClose={() => setModal('')} onDone={refresh} />}
    {inDrawer && branchId && <CameraDrawer branchId={branchId} onClose={() => navigate(`/branches/hierarchy?zone=${zoneId}&city=${cityId}&branch=${branchId}`)} onSaved={() => { platformApi(`/branches/${branchId}/cameras`).then(setCameras); navigate(`/branches/hierarchy?zone=${zoneId}&city=${cityId}&branch=${branchId}`, { state: { success: 'Cameras added.' } }); }} />}
  </div>;
}
