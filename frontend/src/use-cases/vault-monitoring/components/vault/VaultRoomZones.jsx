import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Box, Eye, EyeOff, Pencil, Plus, RotateCcw, Trash2, Save } from 'lucide-react';
import PolygonFrameCanvas from '../../../../components/regions/PolygonFrameCanvas.jsx';
import VaultVideoScrubber from './VaultVideoScrubber.jsx';
import { VAULT_REGIONS, vaultRegionColor } from '../../hooks/useVaultRoomRegions.js';

const button = 'inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border border-[#d0d7e6] bg-white px-3 text-sm font-medium text-[#34479b] hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50';

export default function VaultRoomZones({ regions, previewRef, previewSlotRef, replay, camera, active = true }) {
  const [target, setTarget] = useState(null);
  const [frame, setFrame] = useState(null);
  const [newName, setNewName] = useState('');
  const [addingProfile, setAddingProfile] = useState(false);
  const connected = ['ready', 'connected', 'streaming', 'starting', 'connecting', 'reconnecting', 'stopping'].includes(camera.status);
  const profileLocked = connected || replay.active || replay.busy || regions.editing || regions.dirty || regions.saving;
  const locked = regions.loading || regions.saving || regions.preparing || replay.busy;
  useEffect(() => {
    const root = previewRef.current;
    if (!root) return undefined;
    const refresh = () => {
      const stage = root.querySelector('.room-camera-frame');
      setTarget(stage);
      const media = stage?.querySelector('video, img');
      const width = media?.videoWidth || media?.naturalWidth;
      const height = media?.videoHeight || media?.naturalHeight;
      setFrame((current) => width && height ? current?.width === width && current?.height === height ? current : { width, height } : null);
    };
    refresh();
    root.addEventListener('loadedmetadata', refresh, true); root.addEventListener('load', refresh, true);
    const observer = new MutationObserver(refresh); observer.observe(root, { childList: true, subtree: true });
    return () => { observer.disconnect(); root.removeEventListener('loadedmetadata', refresh, true); root.removeEventListener('load', refresh, true); };
  }, [previewRef, replay.enabled, replay.localUrl, camera.status]);

  const pause = async () => {
    if (replay.enabled) {
      previewRef.current?.querySelector('video')?.pause();
      await replay.pauseForEditing();
    }
  };
  const edit = (id) => regions.start('edit', id, pause);
  const finish = () => regions.finish(frame);
  const editable = regions.editId ? regions.zones.find((row) => row.id === regions.editId) : null;
  const configInUse = connected || replay.active;
  const profileName = regions.profiles.find((profile) => profile.id === regions.profileId)?.name || 'Vault Room';
  // The portal lives in the shared preview, outside this section's hidden subtree.
  // Mount it only in the editor; hiding the section does not hide portalled polygons.
  const overlay = active && target && frame && createPortal(<PolygonFrameCanvas frame={frame} zones={regions.visibleZones}
    zoneColor={vaultRegionColor} editId={active ? regions.editId : null} drawing={active ? regions.drawing : null} overlayOnly
    mirrored={!replay.enabled && camera.kind === 'webcam'} preserveAspectRatio={replay.enabled ? 'xMidYMid meet' : 'xMidYMid slice'}
    readOnly={locked || !active} onFinishPolygon={finish}
    onPoint={(point) => regions.setDrawing((current) => current ? { ...current, points: [...current.points, point] } : current)}
    onMoveZone={(id, polygon) => regions.change(regions.zones.map((row) => row.id === id ? { ...row, polygon } : row))} />, target);
  return <section hidden={!active} className="room-zones-section vault-card bg-white" aria-label="Vault Room zones and regions">
    {overlay}
    <div className="zone-section-header flex flex-wrap items-center gap-3 border-b border-[#e3e7f0] p-5">
      <h3 className="mr-auto flex items-center gap-3 font-bold text-[#0f1b3d]"><span className="zone-section-icon"><Box size={18} aria-hidden /></span>Zones &amp; Regions</h3>
      <button type="button" className={button} disabled={profileLocked} onClick={() => setAddingProfile((value) => !value)}><Plus size={15} aria-hidden />New profile</button>
      <button type="button" className={button} disabled={locked || regions.editing} onClick={regions.reload}><RotateCcw size={14} aria-hidden />{regions.dirty ? 'Discard changes' : 'Reload'}</button>
    </div>
    {addingProfile && <form className="flex flex-wrap gap-2 px-4 pt-4" onSubmit={async (event) => { event.preventDefault(); await regions.createProfile(newName); setAddingProfile(false); setNewName(''); }}><input aria-label="New Vault Room profile name" required maxLength={80} value={newName} onChange={(event) => setNewName(event.target.value)} className="min-h-10 rounded-xl border border-slate-300 px-3 text-sm" /><button className={button} disabled={profileLocked}>Create profile</button></form>}
    <div className="zone-editor-layout">
    <div className="zone-canvas-column">
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <select aria-label="Vault monitoring region" value={regions.selectedType} disabled={regions.editing || locked} onChange={(event) => regions.setSelectedType(event.target.value)} className="min-h-10 rounded-xl border border-[#d0d7e6] bg-white px-3 text-sm text-[#34479b]">{VAULT_REGIONS.map((region) => <option key={region.key} value={region.key}>{region.label}</option>)}</select>
      <button type="button" className={`${button} zone-primary-button`} disabled={!frame || regions.editing || locked} onClick={() => regions.start('draw', null, pause)}><Plus size={16} aria-hidden />Draw polygon</button>
      {(regions.drawing || regions.editId) && <><button type="button" className={button} disabled={locked || (regions.drawing && regions.drawing.points.length < 3)} onClick={finish}>Finish {regions.drawing ? 'polygon' : 'editing'}</button><button type="button" className={button} onClick={regions.cancel}>Cancel</button></>}
      {regions.drawing && <button type="button" className={button} onClick={() => regions.setDrawing((current) => ({ ...current, points: current.points.slice(0, -1) }))}>Undo point</button>}
    </div>
    {regions.editing && <p className="pb-3 text-xs text-[#55607a]">{regions.drawing ? 'Click corners on the video; click the first point or Finish polygon to close.' : `Drag a vertex or move ${editable?.name || 'the polygon'}, then finish editing.`} Playback stays paused until you resume it.</p>}
    <div ref={previewSlotRef} className="zone-frame-preview-slot" />
    <VaultVideoScrubber previewRef={previewRef} replay={replay} editing={regions.editing} active={active} />
    {!frame && <p className="mt-3 text-xs text-[#747da6]">Connect a camera or choose a video to configure regions on its actual frame.</p>}
    {replay.file && <p className="mt-2 text-xs text-[#747da6]">Drag the slider to pick a frame, then draw your regions on it.</p>}
    </div>
    <div className="zone-bottom-layout">
    <div className="zone-list-column">
    <div className="mb-3 flex min-h-10 items-center justify-between gap-3"><h4 className="text-sm font-bold text-[#0f1b3d]">Regions <span className="font-medium text-[#747da6]">({regions.zones.length})</span></h4><span className={`rounded-full px-3 py-1.5 text-xs font-semibold ${regions.dirty ? 'bg-amber-100 text-amber-800' : 'bg-[#dcf7ed] text-[#008d68]'}`}>{regions.loading ? 'Loading…' : regions.error ? 'Profile unavailable' : regions.dirty ? 'Unsaved changes' : 'Profile loaded'}</span></div>
    <div className="space-y-3">{regions.zones.map((row) => <div key={row.id} className="zone-region-card">
      <span className="zone-region-color" style={{ background: vaultRegionColor(row.id) }} aria-hidden />
      <div className="min-w-0 flex-1"><p className="text-sm font-semibold text-[#0f1b3d]">{row.name}</p><p className="mt-1 text-xs text-[#747da6]">{row.polygon.length} points</p><p className="mt-0.5 break-all text-[11px] text-[#747da6]">{row.id}</p></div>
      <div className="flex shrink-0 items-center gap-1">
      <button type="button" className="zone-icon-button" aria-label={`${regions.hidden.has(row.id) ? 'Show' : 'Hide'} ${row.name}`} disabled={regions.editing} onClick={() => regions.setHidden((current) => { const next = new Set(current); if (next.has(row.id)) next.delete(row.id); else next.add(row.id); return next; })}>{regions.hidden.has(row.id) ? <EyeOff size={17} /> : <Eye size={17} />}</button>
      <button type="button" className="zone-icon-button" aria-label={`Edit ${row.name}`} disabled={!frame || locked || regions.editing} onClick={() => edit(row.id)}><Pencil size={15} /></button>
      <button type="button" className="zone-icon-button" aria-label={`Delete ${row.name}`} disabled={locked || regions.editing} onClick={() => regions.change(regions.zones.filter((zone) => zone.id !== row.id))}><Trash2 size={16} /></button>
      </div>
      {regions.editId === row.id && <label className="zone-region-confirm text-xs text-[#747da6]">Reference point <select aria-label={`${row.name} reference point`} value={row.reference || 'bottom_center'} disabled={locked} onChange={(event) => regions.change(regions.zones.map((zone) => zone.id === row.id ? { ...zone, reference: event.target.value } : zone))} className="ml-2 min-h-8 rounded-lg border border-slate-200 px-2 text-xs"><option value="bottom_center">Bottom center</option><option value="center">Bounding-box center</option></select></label>}
      {regions.editId === row.id && ['person_monitoring_roi', 'vault_area_roi'].includes(row.id) && <label className="zone-region-confirm text-xs text-[#747da6]">Confirmation <input aria-label={`${row.name} confirmation seconds`} type="number" min={0} max={60} step={0.1} value={row.confirmation_seconds ?? 1} disabled={locked} onChange={(event) => regions.change(regions.zones.map((zone) => zone.id === row.id ? { ...zone, confirmation_seconds: Number(event.target.value) } : zone))} className="mx-2 min-h-8 w-16 rounded-lg border border-slate-200 px-2 text-xs" />seconds</label>}
    </div>)}</div>
    {!regions.zones.length && <div className="rounded-2xl border border-dashed border-[#e1e5f5] p-5 text-sm leading-6 text-[#747da6]">No regions configured yet. Select a region and draw its polygon on the preview.</div>}
    </div>
    <aside className="zone-save-panel" aria-label="Save region configuration">
      <h4 className="text-sm font-bold text-[#0f1b3d]">Save changes</h4>
      <p className="mt-2 text-xs leading-5 text-[#747da6]">Review your regions, then save before starting monitoring.</p>
      <dl className="zone-save-summary">
        <div><dt>Profile</dt><dd>{profileName}</dd></div>
        <div><dt>Regions</dt><dd>{regions.zones.length}</dd></div>
        <div><dt>Visible on frame</dt><dd>{regions.visibleZones.length} of {regions.zones.length}</dd></div>
      </dl>
      <button type="button" className={`${button} zone-primary-button`} disabled={locked || regions.editing || !regions.dirty} onClick={() => regions.save(frame)}><Save size={15} aria-hidden />{regions.saving ? 'Saving…' : regions.dirty ? 'Save configuration' : 'Saved'}</button>
      <button type="button" className={button} disabled={locked || regions.editing || !regions.dirty} onClick={regions.reload}>Discard changes</button>
    </aside>
    </div>
    <p className="zone-editor-footer text-xs leading-5 text-[#747da6]">Visibility does not disable detection. {configInUse ? 'Saved changes apply to the next monitoring run.' : 'Save before starting monitoring.'}<span>{regions.dirty ? 'You have unsaved changes' : 'All changes saved'}</span></p>
    </div>
    {regions.error && <p role="alert" className="px-4 pb-4 text-sm text-red-700">{regions.error}</p>}
    {regions.notice && <p role="status" className="px-4 pb-4 text-sm text-green-700">{regions.notice}</p>}
  </section>;
}
