import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { CheckCircle2, Circle } from 'lucide-react';
import { platformApi } from './api.js';
import { useActiveBranch } from './ActiveBranch.jsx';
import BranchFields from './BranchFields.jsx';
import { blankBranch, branchFields, validateBranch } from './branchValidation.js';
import { countLabel } from './countLabel.js';

const card = 'rounded-xl border border-slate-200 bg-white p-5 shadow-sm';
const field = 'mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800';
const hierarchy = (zone, city, branch) => `/branches/hierarchy?zone=${encodeURIComponent(zone)}&city=${encodeURIComponent(city)}&branch=${encodeURIComponent(branch)}`;
const fromBranch = (branch) => Object.fromEntries(branchFields.map((key) => [key, branch[key] ?? blankBranch[key]]));

export default function EditBranch() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { scope, setScope } = useActiveBranch();
  const [original, setOriginal] = useState(null);
  const [version, setVersion] = useState('');
  const [zones, setZones] = useState([]);
  const [cities, setCities] = useState([]);
  const [zoneId, setZoneId] = useState('');
  const [cityId, setCityId] = useState('');
  const [form, setForm] = useState(blankBranch);
  const [cameras, setCameras] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [touched, setTouched] = useState(false);
  const [error, setError] = useState('');
  const [conflict, setConflict] = useState(false);
  const [codeState, setCodeState] = useState('idle');
  const [adding, setAdding] = useState('');
  const [newName, setNewName] = useState('');
  const errors = useMemo(() => validateBranch(form, cityId), [form, cityId]);
  const dirty = Boolean(original && (zoneId !== original.zoneId || cityId !== original.cityId || branchFields.some((key) => form[key] !== original.form[key])));
  const zone = zones.find((item) => item.id === zoneId);
  const city = cities.find((item) => item.id === cityId);
  const back = hierarchy(original?.zoneId || zoneId, original?.cityId || cityId, id);
  const set = (key, value) => setForm((old) => ({ ...old, [key]: value }));
  useEffect(() => {
    Promise.all([platformApi(`/branches/${encodeURIComponent(id)}`), platformApi('/zones'), platformApi(`/branches/${encodeURIComponent(id)}/cameras`)]).then(([branch, places, cameraRows]) => {
      const nextForm = fromBranch(branch);
      setOriginal({ zoneId: branch.zone_id, cityId: branch.city_id, zoneName: branch.zone_name, cityName: branch.city_name, form: nextForm });
      setZoneId(branch.zone_id); setCityId(branch.city_id); setForm(nextForm);
      setVersion(branch.updated_at); setZones(places); setCameras(cameraRows);
    }).catch((failure) => setError(failure.message)).finally(() => setLoading(false));
  }, [id]);
  useEffect(() => {
    setCities([]);
    if (zoneId) platformApi(`/cities?zone_id=${encodeURIComponent(zoneId)}`).then(setCities).catch((failure) => setError(failure.message));
  }, [zoneId]);
  useEffect(() => {
    if (!original || form.code.toUpperCase() === original.form.code.toUpperCase() || errors.code) { setCodeState('idle'); return; }
    let active = true;
    setCodeState('checking');
    const timer = setTimeout(() => platformApi(`/branches/code-available?code=${encodeURIComponent(form.code)}&exclude_id=${encodeURIComponent(id)}`)
      .then((result) => { if (active) setCodeState(result.available ? 'available' : 'taken'); })
      .catch(() => { if (active) setCodeState('unknown'); }), 300);
    return () => { active = false; clearTimeout(timer); };
  }, [id, form.code, original, errors.code]);
  const addPlace = async (event) => {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const result = await platformApi(adding === 'zone' ? '/zones' : '/cities', { method: 'POST', body: JSON.stringify(adding === 'zone' ? { name: newName } : { name: newName, zone_id: zoneId }) });
      if (adding === 'zone') { setZones((items) => [...items, result]); setZoneId(result.id); setCityId(''); }
      else { setCities((items) => [...items, result]); setCityId(result.id); }
      setAdding(''); setNewName('');
    } catch (failure) { setError(failure.message); } finally { setBusy(false); }
  };
  const save = async () => {
    setTouched(true); setError(''); setConflict(false);
    if (!dirty || Object.keys(errors).length || codeState === 'checking' || codeState === 'taken') return;
    setBusy(true);
    try {
      const delta = Object.fromEntries(branchFields.filter((key) => form[key] !== original.form[key]).map((key) => [key, form[key]]));
      if (cityId !== original.cityId) { delta.city_id = cityId; delta.zone_id = zoneId; }
      const changed = await platformApi(`/branches/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify({ ...delta, updated_at: version }) });
      if (scope?.type === 'branch' && scope.id === id) setScope({ ...scope, name: changed.name, code: changed.code, subtitle: `${changed.code} · ${city?.name || ''}` });
      navigate(hierarchy(zoneId, cityId, id), { state: { success: 'Branch updated' } });
    } catch (failure) { setError(failure.message); setConflict(failure.message.includes('changed by someone else')); }
    finally { setBusy(false); }
  };
  const reloadVersion = async () => {
    try {
      const latest = await platformApi(`/branches/${encodeURIComponent(id)}`);
      setForm((draft) => Object.fromEntries(branchFields.map((key) => [key, draft[key] !== original.form[key] ? draft[key] : latest[key] ?? blankBranch[key]])));
      if (zoneId === original.zoneId && cityId === original.cityId) { setZoneId(latest.zone_id); setCityId(latest.city_id); }
      setOriginal({ zoneId: latest.zone_id, cityId: latest.city_id, zoneName: latest.zone_name, cityName: latest.city_name, form: fromBranch(latest) });
      setVersion(latest.updated_at); setConflict(false);
      setError('Latest version loaded. Your typed changes are still here; review before saving again.');
    } catch (failure) { setError(failure.message); }
  };
  const cancel = () => { if (!dirty || window.confirm('Discard unsaved branch changes?')) navigate(back); };
  const confirmLeave = (event) => { if (dirty && !window.confirm('Discard unsaved branch changes?')) event.preventDefault(); };
  if (loading) return <div role="status" className={`${card} animate-pulse text-sm text-slate-500`}>Loading branch details…</div>;
  if (!original) return <div className={card}><p role="alert" className="text-red-700">{error || 'Branch not found.'}</p><Link to="/branches/hierarchy" className="text-brand underline">Back to Branch Hierarchy</Link></div>;
  const checklist = (done, text) => <li key={text} className="flex items-center gap-2 text-xs text-slate-600">{done ? <CheckCircle2 className="h-4 w-4 text-emerald-500" /> : <Circle className="h-4 w-4 text-slate-300" />}{text}</li>;
  return <div className="mx-auto max-w-6xl space-y-4">
    <div><p className="text-xs text-slate-500">Branches › Branch Hierarchy › Edit branch</p><h1 className="mt-1 text-2xl font-semibold text-navy">Edit branch</h1><p className="text-sm text-slate-500">Update this branch and its place in the hierarchy.</p></div>
    {error && <p role="alert" className={`rounded-md border p-3 text-sm ${conflict ? 'border-amber-200 bg-amber-50 text-amber-800' : 'border-red-200 bg-red-50 text-red-700'}`}>{error}{conflict && <button onClick={reloadVersion} className="ml-2 font-medium underline">Reload latest version</button>}</p>}
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
      <div className="space-y-4"><BranchFields editing zones={zones} cities={cities} zoneId={zoneId} cityId={cityId} onZone={(value) => { setZoneId(value); setCityId(''); }} onCity={setCityId} form={form} onField={set} errors={errors} touched={touched} onAdd={setAdding} codeState={codeState} />
        <section className={card}><h2 className="font-semibold text-navy">4 · Cameras</h2><p className="mt-2 text-sm">{countLabel(cameras.length, 'camera')} · {cameras.filter((item) => item.status === 'live').length} live · {cameras.filter((item) => item.status === 'offline').length} offline</p><div className="mt-3 flex gap-3"><Link to={back} onClick={confirmLeave} className="text-sm text-brand underline">Manage cameras</Link><Link to={`/branches/hierarchy/cameras/new?zone=${zoneId}&city=${cityId}&branch=${id}`} onClick={confirmLeave} className="text-sm text-brand underline">+ Add camera</Link></div></section>
      </div>
      <aside className={`${card} lg:sticky lg:top-20`}><h2 className="font-semibold text-navy">Where it will appear</h2><p className="mt-3 text-xs text-slate-500">Current: {original.zoneName} › {original.cityName} › {original.form.name} · {original.form.code}{original.cityId !== cityId ? ' (moving)' : ''}</p><div className="my-4 space-y-1 text-sm"><p className="rounded bg-slate-50 px-2 py-1">{zone?.name || 'Choose zone'}</p><p className="ml-3 rounded bg-slate-50 px-2 py-1">{city?.name || 'Choose city'}</p><p className="ml-6 rounded border border-dashed border-brand px-2 py-1">{form.name || 'Branch'}</p></div><ul className="space-y-2">{checklist(Boolean(zone && city), 'Zone and city chosen')}{checklist(Boolean(form.name && form.code && !errors.name && !errors.code && codeState !== 'taken'), 'Branch name and code')}{checklist(Boolean(form.address), 'Address')}{checklist(Boolean(form.manager), 'Contact person')}{checklist(cameras.length > 0, 'Cameras connected')}</ul><button type="button" disabled={busy || !dirty || Object.keys(errors).length > 0 || codeState === 'taken' || codeState === 'checking'} onClick={save} className="mt-5 w-full rounded-md bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-50">{busy ? 'Saving…' : 'Save changes'}</button><button type="button" onClick={cancel} className="mt-2 w-full rounded-md border border-slate-300 px-3 py-2 text-sm">Cancel</button><Link to={back} onClick={confirmLeave} className="mt-3 block text-center text-xs text-brand">Back to Branch Hierarchy</Link></aside>
    </div>
    {adding && <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/50 p-4"><form onSubmit={addPlace} role="dialog" aria-modal="true" aria-label={`Add ${adding}`} className={`${card} w-full max-w-sm space-y-4`}><h2 className="font-semibold text-navy">Add {adding}</h2><label className="block text-xs font-medium">Name<input autoFocus required minLength={2} maxLength={120} value={newName} onChange={(event) => setNewName(event.target.value)} className={field} /></label><div className="flex justify-end gap-2"><button type="button" onClick={() => setAdding('')} className="rounded-md border px-3 py-2 text-sm">Cancel</button><button disabled={busy} className="rounded-md bg-brand px-3 py-2 text-sm text-white">Save</button></div></form></div>}
  </div>;
}
