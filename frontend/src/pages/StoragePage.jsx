import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Download, FileJson, Film, FolderOpen, HardDrive, Image, RefreshCw, Search, Trash2, Upload, X } from 'lucide-react';
import { BRANCH_BASE_URL } from '../config/services.js';

const endpoint = `${BRANCH_BASE_URL}/api/storage`;
const categories = [
  ['all', 'All files'], ['sample_videos', 'Sample videos'], ['uploads', 'Uploads'],
  ['clips', 'Clips'], ['screenshots', 'Screenshots'], ['evidence', 'Evidence'],
  ['annotated', 'Annotated'], ['temp', 'Temporary'],
];
const protectedCategories = new Set(['clips', 'screenshots', 'evidence']);
const fmt = (bytes) => bytes == null ? '—' : bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(1)} GB` : bytes >= 1024 ** 2 ? `${(bytes / 1024 ** 2).toFixed(1)} MB` : `${(bytes / 1024).toFixed(1)} KB`;
const fileUrl = (item) => `${endpoint}/file/${item.path.split('/').map(encodeURIComponent).join('/')}`;
const labelFor = (category) => categories.find(([key]) => key === category)?.[1] || category;
const iconFor = (item) => item.name.toLowerCase().endsWith('.json') ? FileJson : item.duration != null ? Film : Image;

function Stat({ icon: Icon, label, value, detail }) {
  return <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
    <div className="flex items-start justify-between gap-3">
      <div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p><p className="mt-2 text-2xl font-semibold tabular-nums text-navy">{value}</p></div>
      <span className="rounded-lg bg-slate-100 p-2 text-brand"><Icon className="h-5 w-5" aria-hidden /></span>
    </div>
    <p className="mt-2 text-xs text-slate-500">{detail}</p>
  </div>;
}

function Preview({ item, onClose }) {
  const url = fileUrl(item);
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/60 p-4" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section role="dialog" aria-modal="true" aria-label={`Preview ${item.name}`} className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl bg-white shadow-xl">
      <div className="flex items-center justify-between gap-4 border-b border-slate-200 px-5 py-4">
        <div className="min-w-0"><h2 className="truncate text-base font-semibold text-navy">{item.name}</h2><p className="text-xs text-slate-500">{labelFor(item.category)} · {fmt(item.size)}</p></div>
        <button type="button" onClick={onClose} aria-label="Close preview" className="rounded-md p-2 text-slate-500 hover:bg-slate-100"><X className="h-5 w-5" /></button>
      </div>
      <div className="min-h-0 overflow-auto bg-slate-50 p-4">
        {item.name.toLowerCase().endsWith('.json') ? <p className="py-10 text-center text-sm text-slate-600">Download this details file to view it.</p> : item.duration != null ? <video src={url} controls className="mx-auto max-h-[65vh] w-full rounded-lg bg-black" /> : <img src={url} alt={item.name} className="mx-auto max-h-[65vh] max-w-full rounded-lg object-contain" />}
      </div>
      <div className="flex justify-end border-t border-slate-200 px-5 py-3"><a href={url} download={item.name} className="inline-flex items-center gap-2 rounded-md bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-dark"><Download className="h-4 w-4" />Download</a></div>
    </section>
  </div>;
}

export default function StoragePage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState('all');
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState(null);
  const [uploadCategory, setUploadCategory] = useState('uploads');
  const [uploadFile, setUploadFile] = useState(null);
  const uploadInput = useRef(null);

  const refresh = useCallback(async () => {
    setBusy(true); setError('');
    try {
      const response = await fetch(endpoint);
      if (!response.ok) throw new Error(`Storage service returned ${response.status}`);
      setData(await response.json());
    } catch (e) { setError(`${e.message}. Start Branch Exterior on port 8011.`); }
    finally { setBusy(false); }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    if (!selected) return undefined;
    const onKeyDown = (event) => { if (event.key === 'Escape') setSelected(null); };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [selected]);

  const files = useMemo(() => (data?.files || []).filter((item) =>
    (tab === 'all' || item.category === tab) && `${item.name} ${item.owner} ${item.path}`.toLowerCase().includes(query.trim().toLowerCase())), [data, tab, query]);

  const upload = async () => {
    if (!uploadFile) return;
    const form = new FormData(); form.append('file', uploadFile);
    setBusy(true); setError('');
    try {
      const response = await fetch(`${endpoint}/upload?category=${uploadCategory}`, { method: 'POST', body: form });
      if (!response.ok) throw new Error((await response.json()).detail || `Upload failed (${response.status})`);
      setUploadFile(null); if (uploadInput.current) uploadInput.current.value = ''; await refresh();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const remove = async (item) => {
    if (!window.confirm(`Delete ${item.name}? This cannot be undone. Referenced files are protected.`)) return;
    setBusy(true); setError('');
    try {
      const response = await fetch(fileUrl(item), { method: 'DELETE' });
      if (!response.ok) throw new Error((await response.json()).detail || `Delete failed (${response.status})`);
      if (selected?.path === item.path) setSelected(null);
      await refresh();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  return <div className="mx-auto max-w-[1440px] space-y-6 text-slate-800">
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div><h1 className="text-2xl font-semibold tracking-tight text-navy">Storage</h1><p className="mt-1 text-sm text-slate-500">Manage shared videos and review media from every use case.</p></div>
      <button type="button" onClick={refresh} disabled={busy} className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium hover:bg-slate-50 disabled:opacity-50"><RefreshCw className={`h-4 w-4 ${busy ? 'animate-spin' : ''}`} />Refresh</button>
    </header>
    {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{error}</p>}

    <section aria-label="Storage summary" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Stat icon={HardDrive} label="Total used" value={fmt(data?.total_bytes)} detail={`${data?.files?.length ?? 0} files in shared storage`} />
      <Stat icon={Film} label="Sample videos" value={data?.categories?.sample_videos?.count ?? '—'} detail={fmt(data?.categories?.sample_videos?.bytes)} />
      <Stat icon={Upload} label="Uploads" value={data ? data.categories?.uploads?.count ?? 0 : '—'} detail={fmt(data ? data.categories?.uploads?.bytes ?? 0 : null)} />
      <Stat icon={FolderOpen} label="Disk available" value={fmt(data?.disk_free_bytes)} detail="Free space on the storage drive" />
    </section>

    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_280px]">
      <section className="min-w-0 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm" aria-label="Stored files">
        <div className="border-b border-slate-200 px-4 pt-4 sm:px-5">
          <div className="flex flex-wrap items-center justify-between gap-3 pb-4">
            <div><h2 className="text-base font-semibold text-navy">Files</h2><p className="text-xs text-slate-500">Browse, preview, or download shared media.</p></div>
            <label className="relative block w-full sm:w-64"><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" aria-hidden /><span className="sr-only">Search storage</span><input aria-label="Search storage" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search files or use case" className="w-full rounded-md border border-slate-300 py-2 pl-9 pr-3 text-sm outline-none focus:border-brand" /></label>
          </div>
          <nav aria-label="Storage categories" className="flex gap-1 overflow-x-auto pb-0.5">
            {categories.map(([key, label]) => <button type="button" key={key} onClick={() => setTab(key)} aria-current={tab === key ? 'page' : undefined} className={`shrink-0 border-b-2 px-3 py-2 text-sm font-medium ${tab === key ? 'border-brand text-brand' : 'border-transparent text-slate-500 hover:text-navy'}`}>{label}<span className="ml-1 text-xs tabular-nums text-slate-400">{key === 'all' ? data?.files?.length ?? 0 : data?.categories?.[key]?.count ?? 0}</span></button>)}
          </nav>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] table-fixed text-left text-sm">
            <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500"><tr><th scope="col" className="w-[38%] px-5 py-3">File</th><th scope="col" className="w-[17%] px-3 py-3">Use case</th><th scope="col" className="w-[12%] px-3 py-3">Size</th><th scope="col" className="w-[16%] px-3 py-3">Modified</th><th scope="col" className="w-[17%] px-3 py-3 text-right">Actions</th></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {files.map((item) => { const Icon = iconFor(item); return <tr key={item.path} className="hover:bg-slate-50">
                <td className="px-5 py-3"><div className="flex min-w-0 items-center gap-3"><span className="shrink-0 rounded-md bg-slate-100 p-2 text-brand"><Icon className="h-4 w-4" aria-hidden /></span><div className="min-w-0"><button type="button" onClick={() => setSelected(item)} title={item.name} className="block max-w-full truncate text-left font-medium text-navy hover:text-brand hover:underline">{item.name}</button><span className="text-xs text-slate-500">{labelFor(item.category)}{item.duration != null ? ` · ${item.duration}s · ${item.resolution || 'video'}` : ''}</span></div></div></td>
                <td className="truncate px-3 py-3 text-slate-600" title={item.owner}>{item.owner}</td><td className="px-3 py-3 tabular-nums text-slate-600">{fmt(item.size)}</td><td className="px-3 py-3 text-slate-600">{new Date(item.modified * 1000).toLocaleDateString()}</td>
                <td className="px-3 py-3"><div className="flex justify-end gap-1"><button type="button" onClick={() => setSelected(item)} title={`Preview ${item.name}`} aria-label={`Preview ${item.name}`} className="rounded-md p-2 text-slate-600 hover:bg-slate-100 hover:text-brand"><Search className="h-4 w-4" /></button><a href={fileUrl(item)} download={item.name} title={`Download ${item.name}`} aria-label={`Download ${item.name}`} className="rounded-md p-2 text-slate-600 hover:bg-slate-100 hover:text-brand"><Download className="h-4 w-4" /></a>{!protectedCategories.has(item.category) && <button type="button" onClick={() => remove(item)} title={`Delete ${item.name}`} aria-label={`Delete ${item.name}`} className="rounded-md p-2 text-slate-500 hover:bg-red-50 hover:text-red-700"><Trash2 className="h-4 w-4" /></button>}</div></td>
              </tr>; })}
            </tbody>
          </table>
          {!busy && files.length === 0 && <div className="px-5 py-12 text-center text-sm text-slate-500">{data ? 'No files match this view.' : 'No files loaded yet.'}</div>}
          {busy && !data && <div className="px-5 py-12 text-center text-sm text-slate-500">Loading storage…</div>}
        </div>
      </section>

      <aside className="space-y-5">
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm" aria-label="Upload video">
          <h2 className="flex items-center gap-2 text-base font-semibold text-navy"><Upload className="h-4 w-4 text-brand" />Upload a video</h2>
          <p className="mt-1 text-xs leading-5 text-slate-500">Videos uploaded here are available in use-case video pickers.</p>
          <label className="mt-5 block text-xs font-medium text-slate-600">Save to<select value={uploadCategory} onChange={(e) => setUploadCategory(e.target.value)} className="mt-1 block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800"><option value="uploads">Uploads</option><option value="sample_videos">Sample videos</option></select></label>
          <label className="mt-4 block text-xs font-medium text-slate-600">Video file<input ref={uploadInput} aria-label="Upload video" type="file" accept="video/*" onChange={(e) => setUploadFile(e.target.files?.[0] || null)} className="mt-1 block w-full text-xs text-slate-600 file:mr-2 file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-2 file:text-xs file:font-medium file:text-navy hover:file:bg-slate-200" /></label>
          <button type="button" onClick={upload} disabled={!uploadFile || busy} className="mt-4 w-full rounded-md bg-brand px-3 py-2 text-sm font-medium text-white hover:bg-brand-dark disabled:cursor-not-allowed disabled:opacity-50">{busy ? 'Please wait…' : 'Upload video'}</button>
          <p className="mt-3 text-xs text-slate-400">Maximum file size: 500 MB.</p>
        </section>
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm" aria-label="Storage by use case">
          <h2 className="text-base font-semibold text-navy">By use case</h2>
          <div className="mt-3 divide-y divide-slate-100">{Object.entries(data?.owners || {}).map(([name, stats]) => <div key={name} className="flex items-center justify-between gap-3 py-2.5 text-sm"><span className="min-w-0 truncate text-slate-600" title={name}>{name}</span><span className="shrink-0 text-right font-medium tabular-nums text-navy">{stats.count}<span className="ml-2 text-xs font-normal text-slate-500">{fmt(stats.bytes)}</span></span></div>)}{data && !Object.keys(data.owners || {}).length && <p className="py-3 text-sm text-slate-500">No media yet.</p>}</div>
        </section>
      </aside>
    </div>
    {selected && <Preview item={selected} onClose={() => setSelected(null)} />}
  </div>;
}
