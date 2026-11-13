import { useEffect, useRef, useState } from 'react';
import { activateRoomRegionProfile, createRoomRegionProfile, getRoomRegionProfile, listRoomRegionProfiles, saveRoomRegionProfile } from '../api/vaultRoom.js';
import { prepareZonePolygons } from '../../../utils/zonePolygons.js';
import { describeError } from '../../../utils/errors.js';

export const VAULT_REGIONS = [
  { key: 'person_monitoring_roi', label: 'Person Monitoring Area', color: '#7c93ff' },
  { key: 'vault_area_roi', label: 'Vault Area', color: '#4f7cf7' },
  { key: 'vault_door_roi', label: 'Vault Door', color: '#34d399' },
  { key: 'tray_area_roi', label: 'Tray Area', color: '#a78bfa' },
  { key: 'ornament_area_roi', label: 'Ornament Area', color: '#f59e0b' },
  { key: 'vault_door_handle_roi', label: 'Vault Door Handle', color: '#f472b6' },
];
export const vaultRegionColor = (key) => VAULT_REGIONS.find((entry) => entry.key === key)?.color || '#94a3b8';
const keyFor = (source) => `vault-room-region-profile:${source}`;
const remembered = (source) => { try { return localStorage.getItem(keyFor(source)) || source; } catch { return source; } };
const normalize = (rows) => rows.map((zone) => ({ ...zone, zone_type: zone.id, polygon: zone.polygon.map((p) => Array.isArray(p) ? { x: p[0], y: p[1] } : p) }));
const profileError = (error) => error?.response?.status === 404 && error.response.data?.detail === 'Not Found'
  ? 'The connected Vault backend has not loaded region profile routes. Restart Vault Monitoring, then reload the profile.'
  : describeError(error).message;

export default function useVaultRoomRegions(enabled) {
  const [source, setSource] = useState('webcam');
  const [profileId, setProfileId] = useState(() => remembered('webcam'));
  const [profiles, setProfiles] = useState([]);
  const [zones, setZones] = useState([]);
  const [version, setVersion] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [drawing, setDrawing] = useState(null);
  const [editId, setEditId] = useState(null);
  const [hidden, setHidden] = useState(new Set());
  const [selectedType, setSelectedType] = useState(VAULT_REGIONS[0].key);
  const [reload, setReload] = useState(0);
  const editingBackup = useRef(null);
  const [preparing, setPreparing] = useState(false);
  const contextKey = JSON.stringify([enabled, source, profileId]);
  const context = useRef({ key: contextKey, epoch: 0 });
  if (context.current.key !== contextKey) context.current = { key: contextKey, epoch: context.current.epoch + 1 };
  const [loadedEpoch, setLoadedEpoch] = useState(-1);
  const currentSnapshot = enabled && loadedEpoch === context.current.epoch;

  useEffect(() => { setSaving(false); setPreparing(false); editingBackup.current = null; }, [contextKey]);

  useEffect(() => {
    if (!enabled) {
      setSource('webcam'); setProfileId(remembered('webcam')); setDrawing(null); setEditId(null);
    }
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return undefined;
    let active = true;
    listRoomRegionProfiles().then((items) => { if (active) setProfiles(items); })
      .catch((err) => { if (active) setError(profileError(err)); });
    return () => { active = false; };
  }, [enabled, reload]);
  useEffect(() => {
    if (!enabled) return undefined;
    const controller = new AbortController();
    const epoch = context.current.epoch;
    setZones([]);
    setLoading(true); setError(''); setNotice(''); setDrawing(null); setEditId(null); setHidden(new Set());
    getRoomRegionProfile(profileId, controller.signal).then((profile) => {
      if (controller.signal.aborted || context.current.epoch !== epoch) return;
      setZones(normalize(profile.zones)); setVersion(profile.version); setDirty(false);
      setLoadedEpoch(epoch);
    }).catch((err) => { if (!controller.signal.aborted && context.current.epoch === epoch) setError(profileError(err)); })
      .finally(() => { if (!controller.signal.aborted && context.current.epoch === epoch) setLoading(false); });
    return () => controller.abort();
  }, [enabled, source, profileId, reload]);

  const selectProfile = (id, nextSource = source) => {
    setProfileId(id);
    try { localStorage.setItem(keyFor(nextSource), id); } catch { /* Browser storage can be unavailable. */ }
  };
  const selectSource = (kind) => {
    const nextSource = kind === 'rtsp' ? 'cctv' : kind;
    setSource(nextSource); setProfileId(remembered(nextSource));
  };
  const change = (next) => { if (currentSnapshot) { setZones(next); setDirty(true); setNotice(''); } };
  const cancel = () => {
    if (editId && editingBackup.current) { setZones(editingBackup.current.zones); setDirty(editingBackup.current.dirty); }
    setDrawing(null); setEditId(null); setError(''); editingBackup.current = null;
  };
  const start = async (kind, id, pause) => {
    if (!currentSnapshot || loading || saving) return;
    const epoch = context.current.epoch;
    setPreparing(true); setError('');
    try {
      await pause();
      if (context.current.epoch !== epoch) return;
      setHidden((current) => { const next = new Set(current); next.delete(id || selectedType); return next; });
      editingBackup.current = { zones: structuredClone(zones), dirty };
      if (kind === 'draw') setDrawing({ kind: 'polygon', zoneType: selectedType, points: [] });
      else setEditId(id);
    } catch (err) { if (context.current.epoch === epoch) setError(err.message || 'Could not pause playback.'); }
    finally { if (context.current.epoch === epoch) setPreparing(false); }
  };
  const finish = (frame) => {
    if (!currentSnapshot || loading) return;
    try {
      if (drawing) {
        const type = VAULT_REGIONS.find((entry) => entry.key === drawing.zoneType);
        const previous = zones.find((entry) => entry.id === type.key);
        const row = { id: type.key, zone_type: type.key, name: type.label, reference: previous?.reference || 'bottom_center',
          enabled: true, confirmation_seconds: previous?.confirmation_seconds ?? 1, polygon: drawing.points };
        const normalized = prepareZonePolygons([row], frame)[0];
        change([...zones.filter((entry) => entry.id !== type.key), ...normalize([normalized])]);
      } else {
        prepareZonePolygons(zones, frame); setDirty(true);
      }
      setDrawing(null); setEditId(null); editingBackup.current = null; setError('');
    } catch (err) { setError(err.message); }
  };
  const save = async (frame) => {
    if (!currentSnapshot || loading || saving) return;
    const epoch = context.current.epoch;
    setSaving(true); setError('');
    try {
      const clean = prepareZonePolygons(zones, frame).map(({ zone_type, ...entry }) => entry);
      const result = await saveRoomRegionProfile(profileId, { version, zones: clean });
      if (context.current.epoch !== epoch) return;
      setZones(normalize(result.zones)); setVersion(result.version); setDirty(false);
      setNotice('Configuration saved. It will be used when monitoring starts.');
    } catch (err) { if (context.current.epoch === epoch) setError(err.response ? profileError(err) : err.message); }
    finally { if (context.current.epoch === epoch) setSaving(false); }
  };
  const createProfile = async (name) => {
    const epoch = context.current.epoch;
    setSaving(true); setError('');
    try {
      const profile = await createRoomRegionProfile(name);
      if (context.current.epoch !== epoch) return;
      setProfiles((items) => [...items, profile]); selectProfile(profile.id);
    }
    catch (err) { if (context.current.epoch === epoch) setError(describeError(err).message); }
    finally { if (context.current.epoch === epoch) setSaving(false); }
  };
  const beforeConnect = async () => {
    if (!currentSnapshot || dirty || loading || drawing || editId) throw new Error('Save or cancel region changes before connecting.');
    const epoch = context.current.epoch;
    await activateRoomRegionProfile(profileId);
    if (context.current.epoch !== epoch) throw new Error('The camera selection changed. Connect the selected source again.');
  };
  const displayedZones = currentSnapshot ? zones : [];
  return { profileId, profiles, zones: displayedZones, visibleZones: displayedZones.filter((row) => !hidden.has(row.id)), source,
    dirty: currentSnapshot && dirty, loading: loading || !currentSnapshot, saving, error, notice,
    drawing: currentSnapshot ? drawing : null, editId: currentSnapshot ? editId : null, hidden, selectedType, setSelectedType,
    setDrawing, setHidden, setError, selectProfile, selectSource, change, cancel, start, finish, save,
    createProfile, beforeConnect, preparing, reload: () => setReload((n) => n + 1),
    ready: currentSnapshot && !dirty && !loading && !saving && !drawing && !editId && !error,
    editing: Boolean(currentSnapshot && (drawing || editId || preparing)) };
}
