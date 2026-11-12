import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { FileVideo2, UploadCloud } from 'lucide-react';
import { useActiveBranch } from '../branches/ActiveBranch.jsx';
import { platformApi, useCases } from '../branches/api.js';
import { uploadVideo, validateVideo } from './uploader.js';

const fmt = (bytes) => `${(bytes / 1024 ** 2).toFixed(1)} MB`;
const field = 'mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm';

export default function VideoUploads() {
  const { scope } = useActiveBranch();
  const [branchSearch, setBranchSearch] = useState('');
  const [branches, setBranches] = useState([]);
  const [branchId, setBranchId] = useState(scope?.type === 'branch' ? scope.id : '');
  const [cameras, setCameras] = useState([]);
  const [cameraId, setCameraId] = useState('');
  const [useCase, setUseCase] = useState('');
  const [queue, setQueue] = useState([]);
  const [recent, setRecent] = useState({ items: [], total: 0 });
  const [more, setMore] = useState(5);
  const [error, setError] = useState('');
  const [dragging, setDragging] = useState(false);
  const picker = useRef(null);
  const controllers = useRef(new Map());
  const loadRecent = useCallback(() => platformApi(`/uploads?limit=${more}`).then(setRecent).catch((e) => setError(e.message)), [more]);
  useEffect(() => { loadRecent(); }, [loadRecent]);
  useEffect(() => {
    if (!recent.items.some((item) => ['uploading', 'queued'].includes(item.status))) return undefined;
    const timer = setInterval(loadRecent, 3000);
    return () => clearInterval(timer);
  }, [loadRecent, recent.items]);
  useEffect(() => {
    const timer = setTimeout(() => platformApi(`/branches/search?query=${encodeURIComponent(branchSearch)}&limit=30`).then(setBranches).catch((e) => setError(e.message)), 200);
    return () => clearTimeout(timer);
  }, [branchSearch]);
  useEffect(() => {
    if (!branchId) { setCameras([]); setCameraId(''); return; }
    platformApi(`/branches/${encodeURIComponent(branchId)}/cameras`).then(setCameras).catch((e) => setError(e.message));
  }, [branchId]);
  const enqueue = (files) => {
    const additions = [];
    for (const file of files || []) {
      try { validateVideo(file); additions.push({ key: crypto.randomUUID(), file, status: 'ready', bytes: 0, uploadId: null, error: '' }); }
      catch (e) { setError(`${file.name}: ${e.message}`); }
    }
    setQueue((items) => [...items, ...additions]);
  };
  const update = (key, patch) => setQueue((items) => items.map((entry) => entry.key === key ? { ...entry, ...patch } : entry));
  const startOne = async (entry) => {
    const controller = new AbortController(); controllers.current.set(entry.key, controller);
    update(entry.key, { status: 'uploading', error: '' });
    try {
      await uploadVideo(entry.file, { branchId, cameraId, useCase, signal: controller.signal,
        previousId: entry.uploadId, onProgress: (bytes, uploadId) => update(entry.key, { bytes, uploadId }) });
      update(entry.key, { status: 'queued' });
      loadRecent();
    } catch (e) { update(entry.key, { status: controller.signal.aborted ? 'cancelled' : 'failed', error: e.message }); }
    finally { controllers.current.delete(entry.key); }
  };
  const start = () => {
    if (!branchId) { setError('Choose a branch before uploading.'); return; }
    setError('');
    queue.filter((entry) => entry.status === 'ready' || entry.status === 'failed').forEach(startOne);
  };
  const cancel = (entry) => {
    const controller = controllers.current.get(entry.key);
    if (controller) controller.abort(); else setQueue((items) => items.filter((item) => item.key !== entry.key));
  };
  const chooseCamera = (value) => {
    setCameraId(value);
    const camera = cameras.find((entry) => entry.id === value);
    if (camera?.use_cases) setUseCase(camera.use_cases.split(',')[0]);
  };
  const badge = (status) => ({ uploaded: 'bg-emerald-50 text-emerald-700', queued: 'bg-amber-50 text-amber-700', uploading: 'bg-blue-50 text-blue-700', failed: 'bg-red-50 text-red-700' })[status] || 'bg-slate-100 text-slate-600';

  return <div className="mx-auto max-w-[1440px] space-y-4"><div><p className="text-xs text-slate-500">Video Uploads</p><h1 className="mt-1 text-2xl font-semibold text-navy">Video Uploads</h1><p className="text-sm text-slate-500">Upload recorded footage for a branch camera and keep it with that branch.</p></div>
    {error && <p role="alert" className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><h2 className="font-semibold text-navy">Upload a recording</h2><p className="text-xs text-slate-500">MP4, AVI, MOV or MKV up to 2 GB.</p>
      <div className="mt-4 grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]"><div className="space-y-4">
        <div role="button" tabIndex={0} aria-label="Drop videos or browse files" onKeyDown={(e) => { if (e.key === 'Enter') picker.current?.click(); }} onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(e) => { e.preventDefault(); setDragging(false); enqueue(e.dataTransfer.files); }} className={`grid min-h-44 place-items-center rounded-xl border-2 border-dashed p-5 text-center ${dragging ? 'border-brand bg-indigo-50' : 'border-indigo-200 bg-indigo-50/30'}`}><div><UploadCloud className="mx-auto h-8 w-8 text-brand" /><p className="mt-2 text-sm font-semibold text-navy">Drag and drop a video here</p><p className="text-xs text-slate-500">MP4, AVI, MOV or MKV · up to 2 GB</p><button type="button" onClick={() => picker.current?.click()} className="mt-3 rounded-md border bg-white px-4 py-2 text-sm">Browse files</button><input ref={picker} className="sr-only" type="file" accept=".mp4,.avi,.mov,.mkv" multiple onChange={(e) => { enqueue(e.target.files); e.target.value = ''; }} /></div></div>
        <label className="block text-xs font-medium">Branch<input aria-label="Search branches" value={branchSearch} onChange={(e) => setBranchSearch(e.target.value)} placeholder="Search branch or code" className={field} /><select aria-label="Branch" value={branchId} onChange={(e) => { setBranchId(e.target.value); setCameraId(''); }} className={field}><option value="">Choose a branch</option>{branches.map((branch) => <option key={branch.id} value={branch.id}>{branch.name} · {branch.code}</option>)}{branchId && !branches.some((branch) => branch.id === branchId) && <option value={branchId}>{scope?.name || 'Selected branch'}</option>}</select></label>
        <div className="grid gap-3 sm:grid-cols-2"><label className="block text-xs font-medium">Assign to channel<select className={field} value={cameraId} onChange={(e) => chooseCamera(e.target.value)} disabled={!branchId}><option value="">No channel (general upload)</option>{cameras.map((camera) => <option key={camera.id} value={camera.id}>{camera.code} · {camera.name}</option>)}</select></label><label className="block text-xs font-medium">Use case<select className={field} value={useCase} onChange={(e) => setUseCase(e.target.value)}><option value="">Any use case</option>{useCases.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label></div>
        {queue.length > 0 && <div className="space-y-2" aria-label="Upload queue">{queue.map((entry) => <div key={entry.key} className="flex items-center gap-3 rounded-md border p-3"><FileVideo2 className="h-5 w-5 shrink-0 text-brand" /><div className="min-w-0 flex-1"><p className="truncate text-xs font-medium">{entry.file.name}</p><progress value={entry.bytes} max={entry.file.size} className="mt-1 h-1.5 w-full accent-brand" aria-label={`${entry.file.name} progress`} /><p className="text-xs text-slate-500">{fmt(entry.bytes)} of {fmt(entry.file.size)} · {Math.round(entry.bytes / entry.file.size * 100)}% · {entry.status}</p>{entry.error && <p className="text-xs text-red-700">{entry.error}</p>}</div>{entry.status === 'failed' ? <button onClick={() => startOne(entry)} className="text-xs text-brand">Retry</button> : <button onClick={() => cancel(entry)} className="text-xs text-slate-600">Cancel</button>}</div>)}</div>}
        <button type="button" onClick={start} disabled={!branchId || !queue.some((entry) => ['ready', 'failed'].includes(entry.status))} className="w-full rounded-md bg-brand px-4 py-2.5 text-sm font-medium text-white disabled:opacity-50">Upload video</button>
      </div><aside><div className="flex justify-between"><h2 className="text-sm font-semibold text-navy">Recent uploads</h2><Link to="/storage" className="text-xs text-brand">Open Storage</Link></div><div className="mt-3 space-y-2">{recent.items.length ? recent.items.map((item) => <div key={item.id} className="rounded-lg border p-3"><div className="flex items-center justify-between gap-2"><span className="min-w-0 truncate text-sm font-medium" title={item.original_name}>{item.original_name}</span><span className={`shrink-0 rounded-full px-2 py-1 text-[10px] font-medium capitalize ${badge(item.status)}`}>{item.status}</span></div><p className="mt-1 text-xs text-slate-500">{item.branch_name} · {useCases.find(([id]) => id === item.use_case)?.[1] || 'Any use case'} · {fmt(item.size)}</p>{item.error && <p className="mt-1 text-xs text-red-700">{item.error}</p>}{item.status === 'uploaded' && <a href={`/platform/uploads/${item.id}/file`} target="_blank" rel="noreferrer" className="text-xs text-brand">Open video</a>}{item.status === 'failed' && <button onClick={() => platformApi(`/uploads/${item.id}/retry`, { method: 'POST' }).then(loadRecent).catch((e) => setError(e.message))} className="text-xs text-brand">Retry</button>}</div>) : <p className="rounded-lg border border-dashed p-4 text-sm text-slate-500">No uploads yet.</p>}{recent.total > recent.items.length && <button onClick={() => setMore((value) => value + 20)} className="text-xs text-brand">Show more</button>}</div></aside></div>
    </div>
  </div>;
}
