import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { CheckCircle2, Circle } from 'lucide-react';
import { platformApi } from './api.js';

const card = 'rounded-xl border border-slate-200 bg-white p-5 shadow-sm';
const field = 'mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800';
const label = 'block text-xs font-medium text-slate-700';
const blank = { name: '', code: '', status: 'active', address: '', pincode: '', timezone: 'Asia/Kolkata', manager: '', phone: '', email: '' };

function validate(form, cityId) {
  const errors = {};
  if (!cityId) errors.city = 'Choose a zone and city.';
  if (form.name.trim().length < 2) errors.name = 'Enter a branch name.';
  if (!/^[A-Za-z][A-Za-z0-9-]{2,38}$/.test(form.code)) errors.code = 'Use 3–39 letters, digits or dashes, starting with a letter.';
  if (form.pincode && !/^\d{6}$/.test(form.pincode)) errors.pincode = 'Pincode must be 6 digits.';
  if (form.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) errors.email = 'Enter a valid email address.';
  if (form.phone && !/^\+?[0-9\s()-]{8,20}$/.test(form.phone)) errors.phone = 'Enter a valid phone number.';
  return errors;
}

export default function NewBranch() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [zones, setZones] = useState([]);
  const [cities, setCities] = useState([]);
  const [zoneId, setZoneId] = useState(params.get('zone') || '');
  const [cityId, setCityId] = useState(params.get('city') || '');
  const [form, setForm] = useState(blank);
  const [connectNow, setConnectNow] = useState(false);
  const [error, setError] = useState('');
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState('');
  const [newName, setNewName] = useState('');
  const errors = useMemo(() => validate(form, cityId), [form, cityId]);
  const zone = zones.find((entry) => entry.id === zoneId);
  const city = cities.find((entry) => entry.id === cityId);
  const dirty = zoneId || cityId || Object.entries(form).some(([key, value]) => value !== blank[key]);
  const set = (name, value) => setForm((old) => ({ ...old, [name]: value }));

  useEffect(() => {
    platformApi('/zones').then(setZones).catch((e) => setError(e.message));
    platformApi('/branches/next-code').then((data) => setForm((old) => ({ ...old, code: old.code || data.code }))).catch(() => {});
  }, []);
  useEffect(() => {
    setCities([]);
    if (zoneId) platformApi(`/cities?zone_id=${encodeURIComponent(zoneId)}`).then(setCities).catch((e) => setError(e.message));
  }, [zoneId]);
  const addPlace = async (event) => {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const result = await platformApi(adding === 'zone' ? '/zones' : '/cities', { method: 'POST', body: JSON.stringify(adding === 'zone' ? { name: newName } : { name: newName, zone_id: zoneId }) });
      if (adding === 'zone') { setZones((items) => [...items, result]); setZoneId(result.id); setCityId(''); }
      else { setCities((items) => [...items, result]); setCityId(result.id); }
      setAdding(''); setNewName('');
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const save = async (andCamera = false) => {
    setTouched(true); setError('');
    if (Object.keys(errors).length) return;
    setBusy(true);
    try {
      const result = await platformApi('/branches', { method: 'POST', body: JSON.stringify({ ...form, city_id: cityId }) });
      const query = `zone=${zoneId}&city=${cityId}&branch=${result.id}`;
      navigate(andCamera ? `/branches/hierarchy/cameras/new?${query}` : `/branches/hierarchy?${query}`, { state: { success: `${result.name} was added.` } });
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const cancel = () => { if (!dirty || window.confirm('Discard the unsaved branch?')) navigate('/branches/hierarchy'); };
  const check = (done, text) => <li className="flex items-center gap-2 text-xs text-slate-600">{done ? <CheckCircle2 className="h-4 w-4 text-emerald-500" /> : <Circle className="h-4 w-4 text-slate-300" />}{text}</li>;

  return <div className="mx-auto max-w-6xl space-y-4">
    <div><p className="text-xs text-slate-500">Branches › Add New Branch</p><h1 className="mt-1 text-2xl font-semibold text-navy">Add New Branch</h1><p className="text-sm text-slate-500">Place the branch in a zone and city, add its details, then connect cameras.</p></div>
    {error && <p role="alert" className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
      <div className="space-y-4">
        <section className={card}><h2 className="font-semibold text-navy">1 · Zone and city</h2><p className="mb-4 text-xs text-slate-500">Pick where this branch sits in the hierarchy.</p><div className="grid gap-3 sm:grid-cols-2"><label className={label}>Zone<select className={field} value={zoneId} onChange={(e) => { setZoneId(e.target.value); setCityId(''); }}><option value="">Select zone</option>{zones.map((entry) => <option key={entry.id} value={entry.id}>{entry.name}</option>)}</select></label><label className={label}>City<select className={field} value={cityId} disabled={!zoneId} onChange={(e) => setCityId(e.target.value)}><option value="">Select city</option>{cities.map((entry) => <option key={entry.id} value={entry.id}>{entry.name}</option>)}</select></label></div>{touched && errors.city && <p className="mt-2 text-xs text-red-700">{errors.city}</p>}<p className="mt-3 text-xs text-slate-500">Zone or city not listed? <button className="text-brand underline" onClick={() => setAdding('zone')}>+ Add zone</button> · <button disabled={!zoneId} className="text-brand underline disabled:text-slate-400" onClick={() => setAdding('city')}>+ Add city</button></p></section>
        <section className={card}><h2 className="font-semibold text-navy">2 · Branch details</h2><p className="mb-4 text-xs text-slate-500">Name, code, and address.</p><div className="grid gap-3 sm:grid-cols-2"><label className={`${label} sm:col-span-2`}>Branch name<input className={field} value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="Branch name" />{touched && errors.name && <span className="text-xs text-red-700">{errors.name}</span>}</label><label className={label}>Branch code<input className={field} value={form.code} onChange={(e) => set('code', e.target.value)} placeholder="C99127-01" />{touched && errors.code && <span className="text-xs text-red-700">{errors.code}</span>}</label><label className={label}>Status<select className={field} value={form.status} onChange={(e) => set('status', e.target.value)}><option value="active">Active</option><option value="inactive">Inactive</option></select></label><label className={`${label} sm:col-span-2`}>Address<input className={field} value={form.address} onChange={(e) => set('address', e.target.value)} placeholder="Street address" /></label><label className={label}>Pincode<input className={field} value={form.pincode} onChange={(e) => set('pincode', e.target.value)} placeholder="6 digits" />{touched && errors.pincode && <span className="text-xs text-red-700">{errors.pincode}</span>}</label><label className={label}>Time zone<select className={field} value={form.timezone} onChange={(e) => set('timezone', e.target.value)}><option value="Asia/Kolkata">Asia/Kolkata (IST)</option><option value="UTC">UTC</option></select></label></div></section>
        <section className={card}><h2 className="font-semibold text-navy">3 · Contact</h2><p className="mb-4 text-xs text-slate-500">Who to reach at this branch.</p><div className="grid gap-3 sm:grid-cols-2"><label className={label}>Branch manager<input className={field} value={form.manager} onChange={(e) => set('manager', e.target.value)} placeholder="Full name" /></label><label className={label}>Contact phone<input className={field} value={form.phone} onChange={(e) => set('phone', e.target.value)} placeholder="Phone number" />{touched && errors.phone && <span className="text-xs text-red-700">{errors.phone}</span>}</label><label className={`${label} sm:col-span-2`}>Email<input type="email" className={field} value={form.email} onChange={(e) => set('email', e.target.value)} placeholder="name@example.com" />{touched && errors.email && <span className="text-xs text-red-700">{errors.email}</span>}</label></div></section>
        <section className={card}><h2 className="font-semibold text-navy">4 · Cameras</h2><p className="mb-3 text-xs text-slate-500">Connect cameras now or after saving.</p><div className="grid gap-3 sm:grid-cols-2"><button type="button" aria-pressed={!connectNow} onClick={() => setConnectNow(false)} className={`rounded-md border p-3 text-left text-sm ${!connectNow ? 'border-brand bg-indigo-50' : 'border-slate-300'}`}><b>Add cameras later</b><span className="block text-xs text-slate-500">Save the branch first</span></button><button type="button" aria-pressed={connectNow} onClick={() => setConnectNow(true)} className={`rounded-md border p-3 text-left text-sm ${connectNow ? 'border-brand bg-indigo-50' : 'border-slate-300'}`}><b>Connect recorder now</b><span className="block text-xs text-slate-500">Open Add camera next</span></button></div></section>
      </div>
      <aside className={`${card} lg:sticky lg:top-20`}><h2 className="font-semibold text-navy">Where it will appear</h2><div className="my-4 space-y-1 text-sm"><p className="rounded bg-slate-50 px-2 py-1">{zone?.name || 'Choose zone'}</p><p className="ml-3 rounded bg-slate-50 px-2 py-1">{city?.name || 'Choose city'}</p><p className="ml-6 rounded border border-dashed border-brand px-2 py-1">{form.name || 'New branch'}</p></div><ul className="space-y-2">{check(Boolean(zone && city), 'Zone and city chosen')}{check(Boolean(form.name && form.code && !errors.name && !errors.code), 'Branch name and code')}{check(Boolean(form.address), 'Address')}{check(Boolean(form.manager), 'Contact person')}{check(false, 'Cameras connected')}</ul><button type="button" disabled={busy} onClick={() => save(connectNow)} className="mt-5 w-full rounded-md bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-50">{busy ? 'Saving…' : connectNow ? 'Save and add cameras' : 'Save branch'}</button><button type="button" onClick={cancel} className="mt-2 w-full rounded-md border border-slate-300 px-3 py-2 text-sm">Cancel</button></aside>
    </div>
    {adding && <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/50 p-4"><form onSubmit={addPlace} role="dialog" aria-modal="true" aria-label={`Add ${adding}`} className={`${card} w-full max-w-sm space-y-4`}><h2 className="font-semibold text-navy">Add {adding}</h2><label className={label}>Name<input autoFocus required minLength={2} maxLength={120} value={newName} onChange={(e) => setNewName(e.target.value)} className={field} /></label><div className="flex justify-end gap-2"><button type="button" onClick={() => { setAdding(''); setNewName(''); }} className="rounded-md border px-3 py-2 text-sm">Cancel</button><button disabled={busy} className="rounded-md bg-brand px-3 py-2 text-sm text-white">Save</button></div></form></div>}
  </div>;
}
