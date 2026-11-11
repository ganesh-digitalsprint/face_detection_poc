import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api, fmApiUrl } from '../api/index.js';
import usePolling from '../hooks/usePolling.js';
import RoiCanvas from './RoiCanvas.jsx';
import { arrowToVector, describeDirection, isValidPolygon } from './roiMath.js';
import { Empty, PageState } from './ui.jsx';

const EMPTY_DRAFT = { points: [], closed: false, arrow: null };

/**
 * Face Mask zones (zone type "Entry ROI") for the common Regions & Zones page. Rule: a camera may have several entry
 * ROIs (one per door); every ROI needs >= 3 points and an inward direction, and only ENABLED ROIs reach running streams.
 */
export default function EntryRoiPanel() {
  const [params, setParams] = useSearchParams();
  const cams = usePolling(() => api.get('/cameras'), 5000);
  const cameras = cams.data || [];
  const cameraId = params.get('camera') || '';
  const camera = cameras.find((c) => c.id === cameraId) || null;
  const isFile = camera && ['upload', 'folder'].includes(camera.cam_type);

  const rois = usePolling(() => (cameraId ? api.get(`/roi?camera_id=${cameraId}`) : []), 0, [cameraId]);
  const [mode, setMode] = useState('view');
  const [draft, setDraft] = useState(EMPTY_DRAFT);
  const [name, setName] = useState('Grill Gate');
  const [pos, setPos] = useState(0);
  const [aspect, setAspect] = useState(4 / 3);
  const [imgError, setImgError] = useState('');
  const [error, setError] = useState('');
  const [saved, setSaved] = useState('');
  const [busy, setBusy] = useState(false);
  const [nonce, setNonce] = useState(0);

  useEffect(() => { setDraft(EMPTY_DRAFT); setMode('view'); setImgError(''); setPos(0); setError(''); setSaved(''); }, [cameraId]);

  const imageUrl = cameraId ? fmApiUrl(`/streams/${cameraId}/snapshot?pos=${pos}&n=${nonce}`) : '';
  const vector = arrowToVector(draft.arrow?.done ? draft.arrow : null, aspect);
  const ready = draft.closed && isValidPolygon(draft.points) && vector && name.trim();

  const startDrawing = () => { setDraft(EMPTY_DRAFT); setMode('polygon'); setSaved(''); setError(''); };
  const save = async () => {
    setBusy(true); setError('');
    try {
      await api.post('/roi', {
        camera_id: cameraId, name: name.trim(),
        polygon: draft.points.map((p) => ({ x: Number(p.x.toFixed(4)), y: Number(p.y.toFixed(4)) })), inward_vector: vector,
      });
      setSaved(`Saved "${name.trim()}".${camera?.stream?.running ? ' It is already applied to the running stream - no restart needed.' : ' It will be used the next time this camera runs.'}`);
      setDraft(EMPTY_DRAFT); setMode('view');
      await rois.reload();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const remove = async (roi) => {
    if (!window.confirm(`Delete the entry ROI "${roi.name}"?`)) return;
    try { await api.del(`/roi/${roi.id}`); await rois.reload(); } catch (e) { setError(e.message); }
  };
  const toggle = async (roi) => {
    try { await api.patch(`/roi/${roi.id}`, { enabled: !roi.enabled }); await rois.reload(); } catch (e) { setError(e.message); }
  };
  const rename = async (roi) => {
    const next = window.prompt('New name for this entry', roi.name);
    if (!next || !next.trim() || next.trim() === roi.name) return;
    try { await api.patch(`/roi/${roi.id}`, { name: next.trim() }); await rois.reload(); } catch (e) { setError(e.message); }
  };

  return (
    <PageState loading={cams.loading} error={cams.error} data={cams.data} onRetry={cams.reload}
      isEmpty={(d) => d.length === 0} emptyIcon="📷" emptyText="Add a camera or analyse a video on Face Mask → Live monitoring first, then draw its entry area here.">
      <div className="bx-card bx-mb-16">
        <label className="bx-field" style={{ margin: 0 }}>Camera
          <select className="bx-input" value={cameraId} onChange={(e) => setParams((prev) => { const next = new URLSearchParams(prev); if (e.target.value) next.set('camera', e.target.value); else next.delete('camera'); return next; })}>
            <option value="">— Select a camera —</option>
            {cameras.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
      </div>

      {!camera && <Empty icon="🎯">Select a camera to draw its Entry ROI (polygon + inward arrow).</Empty>}

      {camera && (
        <div className="bx-two-col">
          <div className="bx-card">
            <div className="bx-card-title">
              {mode === 'polygon' && !draft.closed && 'Step 1 of 2 - click the corners of the entry area. Click the first point or press Enter to close it. Backspace undoes a point.'}
              {mode === 'polygon' && draft.closed && 'Area closed. Now draw the arrow.'}
              {mode === 'arrow' && (!draft.arrow?.done ? 'Step 2 of 2 - click where a person starts, then click in the direction they walk when ENTERING.' : 'Arrow set.')}
              {mode === 'view' && 'Camera view - draw a new Entry ROI, or review the saved ones.'}
            </div>
            {imgError && <div className="bx-diag" role="alert">{imgError} <button type="button" className="bx-btn bx-btn-sm" onClick={() => { setImgError(''); setNonce((n) => n + 1); }}>Retry</button></div>}
            <RoiCanvas imageUrl={imageUrl} saved={rois.data || []} draft={draft} mode={mode} onDraft={setDraft} onAspect={setAspect}
              onImageError={() => setImgError('Could not read a picture from this camera. Is it reachable and enabled?')} />
            {isFile && (
              <label className="bx-field" style={{ marginTop: 10 }}>Position in the video
                <input type="range" min="0" max="1" step="0.05" value={pos} onChange={(e) => setPos(Number(e.target.value))} />
              </label>
            )}
            <div className="bx-row bx-gap-8 bx-wrap" style={{ marginTop: 10 }}>
              {mode === 'view' && <button type="button" className="bx-btn bx-btn-primary" onClick={startDrawing}>+ Draw a new entry</button>}
              {mode === 'polygon' && draft.closed && <button type="button" className="bx-btn bx-btn-primary" onClick={() => setMode('arrow')}>Next: draw the inward arrow</button>}
              {mode === 'polygon' && !draft.closed && draft.points.length >= 3 && <button type="button" className="bx-btn" onClick={() => setDraft({ ...draft, closed: true })}>Close the area</button>}
              {mode === 'arrow' && <button type="button" className="bx-btn" onClick={() => setDraft({ ...draft, arrow: null })}>Redraw arrow</button>}
              {mode !== 'view' && <button type="button" className="bx-btn bx-btn-ghost" onClick={() => { setDraft(EMPTY_DRAFT); setMode('view'); }}>Cancel</button>}
            </div>
          </div>

          <div className="bx-card">
            {mode === 'arrow' && draft.arrow?.done && (
              <>
                <div className="bx-card-title">Save this zone (Entry ROI)</div>
                {error && <div className="bx-diag" role="alert">{error}</div>}
                <label className="bx-field">Name
                  <input className="bx-input" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} placeholder="e.g. Grill Gate" />
                </label>
                <div className="bx-hint">Inward direction: <b>{describeDirection(vector)}</b>. People who move this way inside the area are evaluated; people passing by, waiting or leaving are ignored.</div>
                <button type="button" className="bx-btn bx-btn-primary" disabled={!ready || busy} onClick={save} style={{ marginTop: 10 }}>{busy ? 'Saving…' : 'Save entry area'}</button>
              </>
            )}
            {saved && <div className="bx-hint" role="status">{saved}</div>}
            {mode !== 'arrow' && error && <div className="bx-diag" role="alert">{error}</div>}
            <div className="bx-card-title" style={{ marginTop: mode === 'arrow' ? 18 : 0 }}>Saved zones for {camera.name}</div>
            <PageState loading={rois.loading} error={rois.error} data={rois.data} onRetry={rois.reload}
              isEmpty={(d) => d.length === 0} emptyIcon="🚪" emptyText="No Entry ROI yet. Without one, nobody is evaluated for this camera.">
              {(rois.data || []).map((roi) => (
                <div key={roi.id} className="bx-zone-item">
                  <div><b>{roi.name}</b>{!roi.enabled && <span className="bx-muted"> (disabled)</span>}<div className="bx-muted" style={{ fontSize: 12 }}>Entry ROI · {roi.polygon.length} points · inward: {describeDirection(roi.inward_vector)}</div></div>
                  <div className="bx-row bx-gap-8">
                    <button type="button" className="bx-btn bx-btn-sm" aria-pressed={roi.enabled} onClick={() => toggle(roi)}>{roi.enabled ? 'Disable' : 'Enable'}</button>
                    <button type="button" className="bx-btn bx-btn-sm" onClick={() => rename(roi)}>Rename</button>
                    <button type="button" className="bx-btn bx-btn-sm bx-btn-ghost" onClick={() => remove(roi)}>Delete</button>
                  </div>
                </div>
              ))}
            </PageState>
          </div>
        </div>
      )}
    </PageState>
  );
}
