import { useEffect, useState } from 'react';
import { ChevronDown, Download, Folder, RotateCcw } from 'lucide-react';
import { getRoomRegionProfile } from '../../api/vaultRoom.js';
import { VAULT_REGIONS, vaultRegionColor } from '../../hooks/useVaultRoomRegions.js';
import { describeError } from '../../../../utils/errors.js';

export default function VaultSavedZones({ regions, open, monitoringActive }) {
  const [selectedId, setSelectedId] = useState(regions.profileId);
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const profiles = regions.profiles.filter((profile) => (profile.version ?? 1) > 0);
  const selected = profiles.find((profile) => profile.id === selectedId);
  useEffect(() => { setSelectedId(regions.profileId); }, [regions.profileId]);
  useEffect(() => {
    if (open && !regions.profilesLoading && !profiles.some((profile) => profile.id === selectedId)) setSelectedId(profiles[0]?.id || '');
  }, [open, regions.profilesLoading, regions.profiles, selectedId]);
  useEffect(() => {
    if (!open || !selectedId || !selected) { setPreview(null); return undefined; }
    const controller = new AbortController();
    setError('');
    if (regions.savedProfile?.id === selectedId && !(selected.version > regions.savedProfile.version)) {
      setPreview(regions.savedProfile); setLoading(false); return undefined;
    }
    setPreview(null); setLoading(true);
    getRoomRegionProfile(selectedId, controller.signal).then((profile) => { if (!controller.signal.aborted) setPreview(profile); })
      .catch((err) => { if (!controller.signal.aborted) setError(describeError(err).message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [open, selectedId, regions.profiles, regions.savedProfile]);
  if (!open) return null;
  const inUse = preview?.id === regions.profileId && preview?.version === regions.savedProfile?.version && !regions.dirty && !regions.editing;
  const updated = preview?.updated_at || selected?.updated_at || preview?.last_updated;
  const date = updated && Number.isFinite(Date.parse(updated)) ? new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(updated)) : null;
  const load = () => {
    if ((regions.dirty || regions.editing) && !window.confirm(`Load “${preview.name}”? This replaces your unsaved zone changes. Cancel to continue editing.`)) return;
    regions.loadProfile(selectedId);
  };
  return <section className="zone-load-panel" aria-label="Load saved zones">
    <div className="zone-load-heading"><h4><span className="zone-section-icon"><Folder size={19} aria-hidden /></span>Load saved zones <span className="zone-load-count">({profiles.length})</span></h4><p>Zones you save appear here automatically</p></div>
    {regions.profilesLoading && <p role="status" className="zone-load-message">Loading saved configurations…</p>}
    {!regions.profilesLoading && !regions.profilesError && !profiles.length && <p className="zone-load-message">No saved zone configurations yet. Save your regions to load them here later.</p>}
    {profiles.length > 0 && <>
      <div className="zone-load-row">
        <div className="zone-load-selection">
          <div className="min-w-0 flex-1"><p className="zone-load-name">{selected?.name || 'Select a saved configuration'}</p><p className="zone-load-detail">{loading ? 'Loading profile details…' : date ? `Saved ${date}` : preview ? `Saved configuration · Version ${preview.version}` : 'Choose a saved configuration'}</p></div>
          {preview && <span className="zone-load-pill">{preview.zones.length} regions</span>}
          {inUse && <span className="zone-load-in-use" title="Loaded in this editor">In use</span>}
          <ChevronDown size={18} aria-hidden />
          <select aria-label="Saved zone configuration" value={selectedId} disabled={regions.loadingProfile} onChange={(event) => setSelectedId(event.target.value)}>{profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select>
        </div>
        <button type="button" className="zone-load-button" disabled={!preview || loading || regions.loadingProfile || regions.loading || regions.saving || regions.preparing || inUse} onClick={load}><Download size={18} aria-hidden />{regions.loadingProfile ? 'Loading zones…' : inUse ? 'Zones in use' : 'Load zones'}</button>
      </div>
      {preview && <div className="zone-load-chips">{preview.zones.map((zone) => <span key={zone.id}><i style={{ background: vaultRegionColor(zone.id) }} aria-hidden />{zone.name} · {VAULT_REGIONS.find((type) => type.key === zone.id)?.label || zone.zone_type || zone.id}</span>)}</div>}
    </>}
    {(regions.profilesError || error || regions.loadProfileError) && <div role="alert" className="zone-load-error">{regions.profilesError || error || regions.loadProfileError}<button type="button" onClick={() => regions.loadProfileError && preview ? load() : regions.refreshProfiles()}><RotateCcw size={13} aria-hidden />Retry</button></div>}
    {monitoringActive && <p className="zone-load-message">Loading zones changes the editor only. Active monitoring keeps its current configuration.</p>}
  </section>;
}
