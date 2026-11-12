import { useCallback, useEffect, useState } from 'react';
import { BRANCH_BASE_URL } from '../../config/services.js';
import { availableStoredVideos } from './storageVideos.js';
import { useOptionalActiveBranch } from '../../features/branches/ActiveBranch.jsx';

const base = `${BRANCH_BASE_URL}/api/storage`;

/** Bridges existing file-upload analyzers to the common sample/upload library. */
export default function StorageVideoPicker({ onFile, disabled = false, accept = '.mp4,.avi,.mov,.mkv,.webm' }) {
  const scope = useOptionalActiveBranch()?.scope;
  const [files, setFiles] = useState([]);
  const [selected, setSelected] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const refresh = useCallback(async () => {
    try {
      const response = await fetch(base);
      if (!response.ok) throw new Error(`Storage service returned ${response.status}`);
      const data = await response.json();
      setFiles(availableStoredVideos(data.files, accept).filter((item) =>
        !scope || !item.branch_id || item[`${scope.type}_id`] === scope.id));
      setError('');
    } catch (e) { setError(`${e.message}. Start Branch Exterior on port 8011.`); }
  }, [accept, scope?.id, scope?.type]);
  useEffect(() => { refresh(); }, [refresh]);
  const choose = async () => {
    const item = files.find((entry) => entry.path === selected);
    if (!item) return;
    setBusy(true); setError('');
    try {
      const url = item.upload_id ? `/platform/uploads/${encodeURIComponent(item.upload_id)}/file` : `${base}/file/${item.path.split('/').map(encodeURIComponent).join('/')}`;
      const response = await fetch(url);
      if (!response.ok) throw new Error(`Could not open video (${response.status})`);
      const blob = await response.blob();
      onFile(new File([blob], item.name, { type: blob.type || 'video/mp4', lastModified: Date.now() }));
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  return <div className="space-y-1 text-sm">
    <div className="flex flex-wrap gap-2"><select aria-label="Server video" value={selected} onChange={(e) => setSelected(e.target.value)} disabled={disabled || busy} className="min-w-56 rounded border p-2"><option value="">Pick a video from shared storage</option>{files.map((item) => <option key={item.path} value={item.path}>{item.name} ({item.category}, {(item.size / 1048576).toFixed(1)} MB)</option>)}</select><button type="button" onClick={choose} disabled={!selected || disabled || busy} className="rounded border px-3 py-1">{busy ? 'Loading…' : 'Use video'}</button><button type="button" onClick={refresh} disabled={busy} className="rounded border px-3 py-1">Refresh</button></div>
    {error && <p role="alert" className="text-red-700">{error}</p>}
  </div>;
}
