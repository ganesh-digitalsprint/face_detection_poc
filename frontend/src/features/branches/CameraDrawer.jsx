import { useEffect, useMemo, useRef, useState } from 'react';
import { Eye, EyeOff, X } from 'lucide-react';
import { platformApi, useCases } from './api.js';
import { maskedPreview, parseRtspUrl } from './rtsp.js';

const input = 'mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800';
const field = 'block text-xs font-medium text-slate-700';
const initial = { mode: 'nvr', scheme: 'rtsp', host: '', rtsp_port: 554, stream: 1, username: '', password: '', template_key: 'hikvision', custom_path: '', transport: 'tcp', timeout_seconds: 3 };

export default function CameraDrawer({ branchId, onClose, onSaved }) {
  const panel = useRef(null);
  const [branch, setBranch] = useState(null);
  const [templates, setTemplates] = useState({});
  const [form, setForm] = useState(initial);
  const [fullUrl, setFullUrl] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [step, setStep] = useState(1);
  const [channels, setChannels] = useState([]);
  const [selected, setSelected] = useState({});
  const [devices, setDevices] = useState([]);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [tested, setTested] = useState(false);
  const set = (key, value) => { setForm((old) => ({ ...old, [key]: value })); setTested(false); setChannels([]); };
  const chosen = channels.filter((channel) => selected[channel.channel_no]);
  const preview = useMemo(() => maskedPreview(form, templates), [form, templates]);

  useEffect(() => {
    platformApi(`/branches/${encodeURIComponent(branchId)}`).then(setBranch).catch((e) => setError(e.message));
    platformApi('/rtsp-templates').then(setTemplates).catch((e) => setError(e.message));
    panel.current?.querySelector('button')?.focus();
  }, [branchId]);
  useEffect(() => {
    const keydown = (event) => {
      if (event.key === 'Escape') onClose();
      if (event.key !== 'Tab' || !panel.current) return;
      const focusable = [...panel.current.querySelectorAll('button:not([disabled]),input:not([disabled]),select:not([disabled]),a[href]')];
      if (!focusable.length) return;
      const first = focusable[0]; const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', keydown);
    return () => document.removeEventListener('keydown', keydown);
  }, [onClose]);

  const test = async () => {
    setBusy(true); setError(''); setMessage('');
    try {
      if (fullUrl) parseRtspUrl(fullUrl);
      const result = await platformApi(`/recorders/test?timeout_seconds=${form.timeout_seconds}`, { method: 'POST', body: JSON.stringify({ ...form, branch_id: branchId }) });
      setTested(result.connected);
      setChannels(result.channels.map((entry) => ({ ...entry, name: `Camera ${entry.channel_no}`, use_case: 'branch_exterior' })));
      setSelected(Object.fromEntries(result.channels.map((entry) => [entry.channel_no, true])));
      if (result.connected) setMessage(`Connected · ${result.channel_count} channel${result.channel_count === 1 ? '' : 's'} found`);
      else setError(result.reason || 'No channels responded.');
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const discover = async () => {
    setBusy(true); setError('');
    try {
      const result = await platformApi('/onvif/discover', { method: 'POST' });
      setDevices(result.devices); if (!result.devices.length) setMessage(result.hint);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const save = async () => {
    if (!chosen.length) return;
    setBusy(true); setError('');
    try {
      await platformApi('/cameras/bulk', { method: 'POST', body: JSON.stringify({ recorder: { ...form, branch_id: branchId }, cameras: chosen.map((channel) => ({ channel_no: channel.channel_no, name: channel.name, use_case: channel.use_case, width: channel.width, height: channel.height, fps: channel.fps, codec: channel.codec })) }) });
      onSaved();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  return <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/55" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section ref={panel} role="dialog" aria-modal="true" aria-label="Add camera" className="flex h-full w-full max-w-[560px] flex-col bg-white shadow-2xl">
      <div className="border-b border-slate-200 px-5 py-4"><div className="flex items-start justify-between gap-3"><div><p className="text-xs text-slate-500">Branches › Branch Hierarchy › Add camera</p><h2 className="mt-1 text-lg font-semibold text-navy">Add camera</h2><p className="text-xs text-slate-500">Connect a recorder or camera over RTSP.</p></div><button type="button" onClick={onClose} aria-label="Close drawer" className="rounded-md border p-2 text-slate-500"><X className="h-4 w-4" /></button></div><p className="mt-3 rounded-md border border-indigo-100 bg-indigo-50 px-3 py-2 text-xs text-navy">Adding to <b>{branch ? `${branch.name} · ${branch.code}` : 'selected branch'}</b></p></div>
      <div aria-label="Camera setup steps" className="flex gap-4 border-b px-5 py-3 text-xs"><span aria-current={step === 1 ? 'step' : undefined} className={step === 1 ? 'font-semibold text-brand' : 'text-slate-500'}>1 · Connect</span><span aria-current={step === 2 ? 'step' : undefined} className={step === 2 ? 'font-semibold text-brand' : 'text-slate-500'}>2 · Channels & use case</span></div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4">
        {error && <p role="alert" className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
        {message && <p role="status" className={`rounded-md p-3 text-sm ${tested ? 'border border-emerald-200 bg-emerald-50 text-emerald-700' : 'bg-slate-50 text-slate-600'}`}>{message}</p>}
        {step === 1 ? <>
          <div className="grid grid-cols-3 gap-2">{[['nvr', 'NVR / recorder', 'RTSP, many channels'], ['single', 'Single camera', 'One RTSP URL'], ['onvif', 'Auto-discover', 'ONVIF Beta']].map(([mode, title, detail]) => <button type="button" key={mode} aria-pressed={form.mode === mode} onClick={() => set('mode', mode)} className={`rounded-md border p-2 text-left text-xs ${form.mode === mode ? 'border-brand bg-indigo-50' : 'border-slate-200'}`}><b className="block text-navy">{title}</b><span className="text-slate-500">{detail}</span></button>)}</div>
          {form.mode === 'onvif' && <div><button type="button" onClick={discover} disabled={busy} className="rounded-md border px-3 py-2 text-sm">Discover devices</button><p className="mt-1 text-xs text-slate-500">Beta: discovery requires multicast access from this server to the camera network.</p>{devices.map((device) => <button type="button" key={device.host} onClick={() => set('host', device.host)} className="mt-2 block w-full rounded-md border p-2 text-left text-sm">{device.host}{device.model ? ` · ${device.model}` : ''}</button>)}</div>}
          {form.mode === 'single' && <label className={field}>Full RTSP URL (optional)<input value={fullUrl} onChange={(event) => { const value = event.target.value; setFullUrl(value); try { const parsed = parseRtspUrl(value); setForm((old) => ({ ...old, ...parsed, template_key: 'generic' })); setError(''); } catch { if (value) setError('Only RTSP/RTSPS camera URLs are allowed.'); } }} type="password" autoComplete="off" className={input} placeholder="rtsp://camera-host:554/live" /></label>}
          <label className={field}>Recorder host / IP<input className={input} value={form.host} onChange={(e) => set('host', e.target.value)} placeholder="Private IP address" /></label>
          <div className="grid grid-cols-2 gap-3"><label className={field}>RTSP port<input type="number" min="1" max="65535" className={input} value={form.rtsp_port} onChange={(e) => set('rtsp_port', Number(e.target.value))} /></label><label className={field}>Stream<select className={input} value={form.stream} onChange={(e) => set('stream', Number(e.target.value))}><option value="1">Main stream</option><option value="2">Sub stream</option></select></label></div>
          <div className="grid grid-cols-2 gap-3"><label className={field}>Username<input className={input} value={form.username} autoComplete="off" onChange={(e) => set('username', e.target.value)} /></label><label className={field}>Password<div className="flex items-center gap-1"><input type={showPassword ? 'text' : 'password'} className={input} value={form.password} autoComplete="new-password" onChange={(e) => set('password', e.target.value)} /><button type="button" aria-label={showPassword ? 'Hide password' : 'Show password'} onClick={() => setShowPassword(!showPassword)}>{showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}</button></div></label></div>
          <div aria-label="Masked RTSP URL preview" className="break-all rounded-md bg-navy p-3 font-mono text-xs text-white">{preview}</div>
          <details className="rounded-md border p-3 text-sm"><summary className="cursor-pointer font-medium">Advanced</summary><div className="mt-3 space-y-3"><label className={field}>Vendor / URL template<select className={input} value={form.template_key} onChange={(e) => set('template_key', e.target.value)}>{Object.keys(templates).map((key) => <option key={key} value={key}>{key}</option>)}<option value="generic">Generic custom path</option></select></label>{form.template_key === 'generic' && <label className={field}>RTSP path<input className={input} value={form.custom_path} onChange={(e) => set('custom_path', e.target.value)} placeholder="/live" /></label>}<label className={field}>Transport<select className={input} value={form.transport} onChange={(e) => set('transport', e.target.value)}><option value="tcp">TCP</option><option value="udp">UDP</option></select></label><label className={field}>Connect timeout (seconds)<input type="number" min="1" max="10" className={input} value={form.timeout_seconds} onChange={(e) => set('timeout_seconds', Number(e.target.value))} /></label></div></details>
        </> : <><div className="flex justify-between text-sm"><b>{channels.length} channels found · {chosen.length} selected</b><button type="button" onClick={() => setSelected(Object.fromEntries(channels.map((channel) => [channel.channel_no, true])))} className="text-brand underline">Select all</button></div>{channels.map((channel, index) => <div key={channel.channel_no} className="flex items-start gap-2 rounded-md border p-3"><input type="checkbox" checked={Boolean(selected[channel.channel_no])} onChange={(e) => setSelected((old) => ({ ...old, [channel.channel_no]: e.target.checked }))} aria-label={`Select channel ${channel.channel_no}`} className="mt-2" /><div className="min-w-0 flex-1"><input aria-label={`Channel ${channel.channel_no} name`} value={channel.name} onChange={(e) => setChannels((old) => old.map((entry, at) => at === index ? { ...entry, name: e.target.value } : entry))} className={input} /><p className="mt-1 text-xs text-slate-500">CH-{String(channel.channel_no).padStart(2, '0')} · {channel.width}×{channel.height} · {channel.codec || 'Codec unknown'}</p></div><select aria-label={`Channel ${channel.channel_no} use case`} value={channel.use_case} onChange={(e) => setChannels((old) => old.map((entry, at) => at === index ? { ...entry, use_case: e.target.value } : entry))} className="mt-1 rounded-md border px-2 py-2 text-xs">{useCases.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></div>)}</>}
      </div>
      <footer className="flex justify-end gap-2 border-t border-slate-200 px-5 py-4"><button type="button" onClick={onClose} className="rounded-md border px-3 py-2 text-sm">Cancel</button>{step === 2 ? <><button type="button" onClick={() => setStep(1)} className="rounded-md border px-3 py-2 text-sm">Back</button><button type="button" disabled={!chosen.length || busy} onClick={save} className="rounded-md bg-brand px-3 py-2 text-sm text-white disabled:opacity-50">Add {chosen.length} cameras{branch ? ` to ${branch.name}` : ''}</button></> : <><button type="button" onClick={test} disabled={busy || !form.host} className="rounded-md border px-3 py-2 text-sm">{busy ? 'Testing…' : 'Test connection'}</button><button type="button" onClick={() => setStep(2)} disabled={!tested} className="rounded-md bg-brand px-3 py-2 text-sm text-white disabled:opacity-50">Next: choose channels</button></>}</footer>
    </section>
  </div>;
}
