import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Camera, ChevronDown, FileVideo2, Play, RefreshCw, Search, Upload } from 'lucide-react';
import { BRANCH_BASE_URL } from '../../config/services.js';
import { useOptionalActiveBranch } from '../../features/branches/ActiveBranch.jsx';
import { platformApi } from '../../features/branches/api.js';
import { UploadWorkspace } from '../../features/video-uploads/VideoUploads.jsx';
import { uploadVideo, validateVideo } from '../../features/video-uploads/uploader.js';
import { filterSources, flattenSources, rememberSourceKey, savedSourceKey, sourceCatalog } from './sourceCatalog.js';
import './SourcePicker.css';

const fmtSize = (bytes) => Number.isFinite(Number(bytes)) ? `${(Number(bytes) / 1048576).toFixed(1)} MB` : '';
const fmtDuration = (seconds) => Number.isFinite(Number(seconds)) && Number(seconds) > 0
  ? `${Math.floor(Number(seconds) / 60)}:${String(Math.floor(Number(seconds) % 60)).padStart(2, '0')}` : '';
const fmtDate = (date) => date ? new Date(date).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '';

async function defaultBranch(scope) {
  if (scope?.type === 'branch' && scope.id) return scope.id;
  const branches = await platformApi('/branches/search?query=Default&limit=100');
  const branch = branches.find((item) => /^default(?: branch)?$/i.test(item.name));
  if (!branch) throw new Error('No Default branch is configured. Use More options to select a branch.');
  return branch.id;
}

/** Source selection only. Processing always delegates to the page's existing backend flow. */
export default function SourcePicker({ useCase, cameras, statuses = {}, browseVideos, onProcess, children }) {
  const scope = useOptionalActiveBranch()?.scope;
  const [inventory, setInventory] = useState([]);
  const [browse, setBrowse] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [processError, setProcessError] = useState('');
  const [selectedKey, setSelectedKey] = useState(() => savedSourceKey(localStorage, useCase));
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [focused, setFocused] = useState(0);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadBytes, setUploadBytes] = useState(0);
  const [uploadSize, setUploadSize] = useState(0);
  const [more, setMore] = useState(false);
  const panel = useRef(null);
  const search = useRef(null);
  const fileInput = useRef(null);
  const abort = useRef(null);
  const load = useCallback(async () => {
    setLoading(true); setError('');
    const [media, available] = await Promise.allSettled([
      fetch(`${BRANCH_BASE_URL}/api/storage`).then((response) => { if (!response.ok) throw new Error(`Storage returned ${response.status}`); return response.json(); }),
      browseVideos(),
    ]);
    if (media.status === 'fulfilled') setInventory(media.value.files || []);
    else {
      setError('Common storage is unavailable. Start Branch Exterior on port 8011.');
      if (available.status === 'fulfilled') {
        const entries = Array.isArray(available.value) ? available.value : available.value?.files || [];
        setInventory(entries.map((entry) => ({ ...entry, category: ['uploads', 'upload'].includes(entry.folder || entry.source) ? 'uploads' : 'sample_videos',
          size: Number(entry.size_mb || 0) * 1048576, upload_id: String(entry.path).startsWith('upload:') ? String(entry.path).slice(7) : undefined })));
      }
    }
    if (available.status === 'fulfilled') setBrowse(Array.isArray(available.value) ? available.value : available.value?.files || []);
    else setError((old) => `${old} Video list is unavailable; retry after starting this use-case service.`.trim());
    setLoading(false);
  }, [browseVideos]);
  useEffect(() => { load(); }, [load]);
  // Legacy use-case cameras have no branch metadata; keep them visible until the registry maps them.
  const scopedCameras = useMemo(() => cameras.filter((camera) => !scope || !camera.branch_id
    || (scope.type === 'branch' ? camera.branch_id === scope.id
      : !camera[`${scope.type}_id`] || camera[`${scope.type}_id`] === scope.id)), [cameras, scope?.id, scope?.type]);
  const groups = useMemo(() => sourceCatalog({ files: inventory, browse, cameras: scopedCameras, statuses }), [inventory, browse, scopedCameras, statuses]);
  const all = useMemo(() => flattenSources(groups), [groups]);
  const selected = all.find((item) => item.id === selectedKey);
  const visible = useMemo(() => filterSources(groups, query), [groups, query]);
  const options = flattenSources(visible);
  useEffect(() => { if (selectedKey && !loading && !error && !selected) { setSelectedKey(''); rememberSourceKey(localStorage, useCase, ''); } }, [selectedKey, selected, loading, error, useCase]);
  useEffect(() => { if (open) { load(); setTimeout(() => search.current?.focus(), 0); } }, [open, load]);
  useEffect(() => {
    if (!open) return undefined;
    const close = (event) => { if (panel.current && !panel.current.contains(event.target)) setOpen(false); };
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  }, [open]);
  const pick = (item) => {
    setSelectedKey(item.id); setOpen(false); setQuery(''); setProcessError('');
    rememberSourceKey(localStorage, useCase, item.id);
  };
  const process = async () => {
    if (!selected || busy) return;
    setBusy(true); setProcessError('');
    try { await onProcess(selected); } catch (cause) { setProcessError(cause.message); }
    finally { setBusy(false); }
  };
  const upload = async (file) => {
    if (!file) return;
    setProcessError('');
    try { validateVideo(file); } catch (cause) { setProcessError(cause.message); return; }
    const controller = new AbortController(); abort.current = controller;
    setUploadSize(file.size); setUploadBytes(0); setUploading(true);
    try {
      const branchId = await defaultBranch(scope);
      const result = await uploadVideo(file, { branchId, useCase, signal: controller.signal, onProgress: setUploadBytes });
      for (let count = 0; count < 120; count += 1) {
        if (controller.signal.aborted) return;
        const detail = await platformApi(`/uploads/${encodeURIComponent(result.id)}`);
        if (detail.status === 'failed') throw new Error(detail.error || 'Video validation failed.');
        if (detail.status === 'uploaded') break;
        if (count === 119) throw new Error('Video is still processing. Refresh the picker when it is ready.');
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      await load();
      const key = `upload:${result.id}`;
      setSelectedKey(key);
      rememberSourceKey(localStorage, useCase, key);
    } catch (cause) { if (!controller.signal.aborted) setProcessError(cause.message); }
    finally { abort.current = null; setUploading(false); if (fileInput.current) fileInput.current.value = ''; }
  };
  const handleKeys = (event) => {
    if (event.key === 'Escape') { event.preventDefault(); setOpen(false); return; }
    if (!['ArrowDown', 'ArrowUp', 'Enter'].includes(event.key)) return;
    event.preventDefault();
    if (event.key === 'ArrowDown') setFocused((value) => Math.min(value + 1, options.length - 1));
    if (event.key === 'ArrowUp') setFocused((value) => Math.max(value - 1, 0));
    if (event.key === 'Enter' && options[focused]) pick(options[focused]);
  };
  const renderItems = (items) => items.map((item) => {
    const details = item.kind === 'camera'
      ? [item.code, item.width && item.height ? `${item.width}×${item.height}` : '', item.codec].filter(Boolean).join(' · ')
      : [fmtSize(item.size), fmtDuration(item.duration), item.created_at || item.modified ? `Uploaded ${item.created_at ? fmtDate(item.created_at) : new Date(item.modified * 1000).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}` : ''].filter(Boolean).join(' · ');
    return <button key={item.id} type="button" role="option" aria-selected={item.id === selectedKey} id={`source-option-${options.indexOf(item)}`}
      onMouseEnter={() => setFocused(options.indexOf(item))} onClick={() => pick(item)}
      className={`source-picker-option${item.id === selectedKey ? ' is-selected' : ''}${options[focused]?.id === item.id ? ' is-focused' : ''}`}>
      {item.kind === 'camera' ? <Camera size={19} aria-hidden /> : <FileVideo2 size={19} aria-hidden />}
      <span className="source-picker-option-text"><b>{item.name}</b><small>{details}</small></span>
      {item.status && <span className="source-picker-status">{item.status}</span>}
    </button>;
  });
  return <div className="bx-card bx-mb-16 source-picker-card">
    <div className="bx-card-title">Select a camera or video</div>
    <p className="bx-muted source-picker-subtitle">The selected camera or video is analysed in the live view below.</p>
    <div className="source-picker-row" ref={panel}>
      <div className="source-picker-anchor">
        <button type="button" role="combobox" aria-label="Choose a camera or video" aria-expanded={open} aria-controls="source-picker-list" aria-haspopup="listbox"
          onClick={() => { setOpen((value) => !value); setFocused(0); }} onKeyDown={(event) => {
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); setOpen(true); setFocused(0); }
            else if (event.key === 'Escape') setOpen(false);
            else if (event.key.length === 1 && !event.ctrlKey && !event.altKey && !event.metaKey) { setQuery(event.key); setOpen(true); setFocused(0); }
          }} className="source-picker-trigger">
          <span className="source-picker-icon"><FileVideo2 size={22} aria-hidden /></span>
          <span className="source-picker-trigger-text"><b>{selected?.name || 'Choose a camera or video'}</b><small>{selected ? `${selected.kind === 'camera' ? 'Camera' : 'Video'}${selected.status ? ` · ${selected.status}` : ''}` : `${groups.cameras.length} cameras · ${groups.uploads.length + groups.samples.length} videos · or upload a new file`}</small></span>
          <ChevronDown size={20} aria-hidden />
        </button>
        {open && <div className="source-picker-panel" onKeyDown={handleKeys}>
          <div className="source-picker-search"><Search size={17} aria-hidden /><input ref={search} aria-label="Search cameras and videos" placeholder="Search cameras and videos" value={query} onChange={(event) => { setQuery(event.target.value); setFocused(0); }} /><button type="button" aria-label="Refresh sources" onClick={load}><RefreshCw size={17} aria-hidden /></button></div>
          <div id="source-picker-list" role="listbox" aria-label="Cameras and videos" aria-activedescendant={options[focused] ? `source-option-${focused}` : undefined} className="source-picker-list">
            {loading && <p className="bx-muted source-picker-message">Loading cameras and videos…</p>}
            {error && <p role="alert" className="bx-diag source-picker-message">{error} <button type="button" onClick={load}>Retry</button></p>}
            {!loading && [['Cameras', visible.cameras], ['Uploaded videos', visible.uploads], ['Sample videos', visible.samples]].map(([title, items]) => items.length > 0 && <div role="group" aria-label={title} key={title}><div className="source-picker-group">{title}</div>{renderItems(items)}</div>)}
            {!loading && !options.length && <p className="bx-muted source-picker-message">No videos yet. Upload new.</p>}
          </div>
        </div>}
      </div>
      <button type="button" className="bx-btn source-picker-upload" disabled={uploading} onClick={() => fileInput.current?.click()}><Upload size={17} aria-hidden /> Upload new</button>
      <input ref={fileInput} type="file" className="sr-only" aria-label="Upload new video" accept=".mp4,.avi,.mov,.mkv" onChange={(event) => upload(event.target.files?.[0])} />
    </div>
    <button type="button" className="source-picker-more" onClick={() => setMore(true)}>More options</button>
    {uploading && <div className="source-picker-upload-progress"><progress value={uploadBytes} max={uploadSize} aria-label="Video upload progress" /> <span>{fmtSize(uploadBytes)} of {fmtSize(uploadSize)}</span><button type="button" onClick={() => abort.current?.abort()}>Cancel</button></div>}
    {children}
    {processError && <div className="bx-diag" role="alert">{processError}</div>}
    <button type="button" className="bx-btn bx-btn-primary source-picker-process" disabled={!selected || busy || uploading} onClick={process}><Play size={17} aria-hidden /> {busy ? 'Starting…' : selected?.kind === 'camera' ? 'Start monitoring' : 'Process video'}</button>
    {more && <div className="source-picker-modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setMore(false); }}><div role="dialog" aria-modal="true" aria-label="Upload options" className="source-picker-modal"><button type="button" className="bx-btn" onClick={() => { setMore(false); load(); }}>Close</button><UploadWorkspace initialUseCase={useCase} lockedBranch={scope?.type === 'branch' ? { id: scope.id, name: scope.name, code: scope.code } : null} onUploaded={async (detail) => { await load(); const key = `upload:${detail.id}`; setSelectedKey(key); rememberSourceKey(localStorage, useCase, key); }} /></div></div>}
  </div>;
}
