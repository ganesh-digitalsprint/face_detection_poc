import { useMemo } from 'react';
import { timezones } from './branchValidation.js';

const card = 'rounded-xl border border-slate-200 bg-white p-5 shadow-sm';
const field = 'mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800';
const label = 'block text-xs font-medium text-slate-700';

export default function BranchFields({ zones, cities, zoneId, cityId, onZone, onCity, form, onField, errors, touched, onAdd, editing = false, codeState = 'idle' }) {
  const zoneOptions = useMemo(() => zones.map((item) => <option key={item.id} value={item.id}>{item.name}</option>), [zones]);
  const cityOptions = useMemo(() => cities.map((item) => <option key={item.id} value={item.id}>{item.name}</option>), [cities]);
  const input = (key, title, opts = {}) => <label className={`${label} ${opts.wide ? 'sm:col-span-2' : ''}`}>{title}<input type={opts.type || 'text'} className={field} maxLength={opts.maxLength} value={form[key]} onChange={(event) => onField(key, event.target.value)} placeholder={opts.placeholder || title} />{touched && errors[key] && <span className="text-xs text-red-700">{errors[key]}</span>}</label>;
  return <>
    <section className={card}><h2 className="font-semibold text-navy">1 · Zone and city</h2><p className="mb-4 text-xs text-slate-500">Pick where this branch sits in the hierarchy.</p><div className="grid gap-3 sm:grid-cols-2"><label className={label}>Zone<select className={field} value={zoneId} onChange={(event) => onZone(event.target.value)}><option value="">Select zone</option>{zoneOptions}</select></label><label className={label}>City<select className={field} value={cityId} disabled={!zoneId} onChange={(event) => onCity(event.target.value)}><option value="">Select city</option>{cityOptions}</select></label></div>{touched && errors.city && <p className="mt-2 text-xs text-red-700">{errors.city}</p>}<p className="mt-3 text-xs text-slate-500">Zone or city not listed? <button type="button" className="text-brand underline" onClick={() => onAdd('zone')}>+ Add zone</button> · <button type="button" disabled={!zoneId} className="text-brand underline disabled:text-slate-400" onClick={() => onAdd('city')}>+ Add city</button></p></section>
    <section className={card}><h2 className="font-semibold text-navy">2 · Branch details</h2><p className="mb-4 text-xs text-slate-500">Name, code, and address.</p><div className="grid gap-3 sm:grid-cols-2">
      {input('name', 'Branch name', { wide: true, maxLength: 120 })}
      <div>{input('code', 'Branch code', { placeholder: 'C99127-01' })}{editing && <p className="mt-1 text-xs text-slate-500">The code is shown in uploads, alerts and reports.</p>}{codeState === 'taken' && <p role="alert" className="text-xs text-red-700">This code is already in use.</p>}</div>
      <label className={label}>Status<select className={field} value={form.status} onChange={(event) => onField('status', event.target.value)}><option value="active">Active</option><option value="inactive">Inactive</option></select></label>
      {input('address', 'Address', { wide: true, placeholder: 'Street address' })}
      {input('pincode', 'Pincode', { placeholder: '6 digits' })}
      <label className={label}>Time zone<select className={field} value={form.timezone} onChange={(event) => onField('timezone', event.target.value)}>{timezones.map((zone) => <option value={zone} key={zone}>{zone === 'Asia/Kolkata' ? 'Asia/Kolkata (IST)' : zone}</option>)}</select>{touched && errors.timezone && <span className="text-xs text-red-700">{errors.timezone}</span>}</label>
    </div></section>
    <section className={card}><h2 className="font-semibold text-navy">3 · Contact</h2><p className="mb-4 text-xs text-slate-500">Who to reach at this branch.</p><div className="grid gap-3 sm:grid-cols-2">{input('manager', 'Branch manager', { placeholder: 'Full name' })}{input('phone', 'Contact phone', { placeholder: 'Phone number' })}{input('email', 'Email', { wide: true, type: 'email', placeholder: 'name@example.com' })}</div></section>
  </>;
}
