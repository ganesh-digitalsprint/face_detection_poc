import { prepareZonePolygons, zoneValidationMessage, zoneValidationIndex } from '../../../utils/zonePolygons.js';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Check, EyeOff, Eye, Trash2, Undo2 } from 'lucide-react';
import { describeError } from '../../../utils/errors.js';
import {
  copyVideoJobConfig, createAssignmentZone, createGrillGateZoneConfiguration, deleteAssignmentZone,
  deleteGrillGateZoneConfiguration, duplicateGrillGateZoneConfiguration, getGrillGateZoneConfiguration,
  getLivePreview, getVideoJobConfig, getVideoJobFrame, listGrillGateZoneConfigurations,
  measureVideoJobEndpoints, putVideoJobConfig, saveAssignmentCalibration, updateAssignmentZone,
  updateAssignmentConfiguration, updateGrillGateZoneConfiguration,
} from '../api/grillGate.js';
import { CALIBRATION_STARTING_VALUES, calibrationFromForm, calibrationToForm, formLine, formatSeconds, mergeGrillGateAlertConfiguration, polygonPoints, zoneColor, zoneTypesForStrategy } from '../grillGateModel.js';
import { useAuthorizedJpeg } from '../hooks/useSourceData.js';
import { countZoneChanges, normalizeZonePoints, zoneForSave } from '../liveMonitoringModel.js';
import { formatVideoTime } from '../videoJobModel.js';
import { initialVideoZoneConfigurationSelection, rememberVideoZoneConfigurationSelection, videoAlertConfigurationWithAssignmentDefault, videoAlertThresholdInputValue } from '../videoZoneConfigurationSelection.js';
import { btnGhost, btnPrimary, Card, ErrorNote } from './ui.jsx';
import FrameCanvas from '../../../components/regions/PolygonFrameCanvas.jsx';

const smallField = 'mt-1 min-h-9 w-full rounded-md border border-[#D0D7E6] bg-white px-2.5 text-sm text-[#1C2B4D] outline-none focus:border-[#34479B] focus:ring-2 focus:ring-[#34479B]/20 disabled:bg-[#F4F6FB]';
const ALERT_RULES = [
  ['gate_open', 'Alert when the gate stays open without a crossing for (seconds)', 'max_gate_open_seconds', 'Threshold (s)'],
  ['partially_open', 'Gate partially open too long', 'max_partially_open_seconds', 'Max partially open (s)'],
  ['mesh_occupancy', 'Too many people in mesh area', 'max_mesh_occupancy', 'Max people'],
];


function AlertRulesCard({ rules, onChange, disabled, isVideo }) {
  const set = (changes) => onChange({ ...rules, ...changes });
  return (
    <Card title={isVideo ? 'Alert rules for this video' : 'Live camera alert rules'}>
      <p className="mb-3 text-xs leading-5 text-[#55607A]">{isVideo ? 'This existing threshold is used for the uploaded video’s progress timer and alert. No second threshold is needed.' : 'Set this threshold, then check its box to enable the rule.'}</p>
      <p className="mb-3 text-xs leading-5 text-[#55607A]">Resets every time someone completes an ENTRY or EXIT.</p>
      <div className="space-y-3">
        {ALERT_RULES.map(([key, title, thresholdKey, thresholdLabel]) => {
          const threshold = videoAlertThresholdInputValue(rules, thresholdKey);
          const isSet = threshold !== '';
          return (
            <div key={key} className="grid items-end gap-2 sm:grid-cols-[1fr_110px]">
              <label className="flex items-center gap-2 text-sm text-[#0F1B3D]">
                <input type="checkbox" checked={Boolean(rules[`${key}_enabled`]) && isSet} disabled={disabled || !isSet}
                  onChange={(event) => set({ [`${key}_enabled`]: event.target.checked })} />
                {title}
              </label>
              <label className="block text-xs text-[#55607A]">{thresholdLabel}
                <input className={smallField} type="number" min="0" step="any" value={threshold} disabled={disabled}
                  onChange={(event) => {
                    const value = event.target.value === '' ? null : Number(event.target.value);
                    set({ [thresholdKey]: value, ...(value == null ? { [`${key}_enabled`]: false } : {}) });
                  }} />
              </label>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function zoneConfigurationListError(exception) {
  if (exception?.response?.status === 404) {
    return 'The running backend does not expose saved zone configurations. Restart the updated Grill Gate API, then reload this page.';
  }
  return describeError(exception).message;
}

function CalibrationCard({ source, frame, savedFrame, disabled, prefillNote, measuredLabel, duration, frameTime, measuring, measureError, onMeasure, canMeasure }) {
  const matches = savedFrame && frame && savedFrame.width === frame.width && savedFrame.height === frame.height;
  const [closedT, setClosedT] = useState('');
  const [openT, setOpenT] = useState('');
  return (
    <Card title="Calibration">
      <div className="space-y-1 text-sm text-[#55607A]">
        <p>{frame ? `Video frame ${frame.width} × ${frame.height}` : 'Video frame size is not known yet.'}
          {savedFrame && frame && (matches ? ' ✓ matches this source' : '')}
        </p>
        {savedFrame && frame && !matches && <p className="text-amber-800">Saved calibration is {savedFrame.width} × {savedFrame.height}, so it must be redone for this source. Coordinates are never rescaled.</p>}
        {measuredLabel && <p>{measuredLabel}</p>}
      </div>
      {prefillNote && <p className="mt-2 text-xs text-[#55607A]">{prefillNote}</p>}
      {source === 'video' ? (
        <div className="mt-3 rounded-md bg-[#F7F8FC] p-3 ring-1 ring-[#E3E7F0]">
          <p className="text-xs text-[#55607A]">Optional: pick fully closed and open frames to tune the detector's endpoint positions{duration ? ` (0 to ${formatSeconds(duration)})` : ''}. The detector can use its standard geometry defaults if measurement fails.</p>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <label className="block text-xs text-[#55607A]">Closed time (s)
              <input className={smallField} type="number" min="0" step="0.1" value={closedT} disabled={disabled} onChange={(event) => setClosedT(event.target.value)} />
              <button type="button" className="mt-1 text-xs font-semibold text-[#34479B] underline disabled:opacity-40" disabled={disabled} onClick={() => setClosedT(String(frameTime))}>Use frame shown</button>
            </label>
            <label className="block text-xs text-[#55607A]">Open time (s)
              <input className={smallField} type="number" min="0" step="0.1" value={openT} disabled={disabled} onChange={(event) => setOpenT(event.target.value)} />
              <button type="button" className="mt-1 text-xs font-semibold text-[#34479B] underline disabled:opacity-40" disabled={disabled} onClick={() => setOpenT(String(frameTime))}>Use frame shown</button>
            </label>
          </div>
          <button type="button" className={`${btnGhost} mt-2`} disabled={disabled || measuring || !canMeasure || closedT === '' || openT === ''}
            onClick={() => onMeasure(Number(closedT), Number(openT))}>{measuring ? 'Measuring…' : 'Measure endpoints'}</button>
          {!canMeasure && !disabled && <p className="mt-1 text-xs text-amber-800">Endpoint measurement unlocks after an enabled Sliding gate leaf zone is saved. You can still save all drafted zones together.</p>}
          {measureError && <p role="alert" className="mt-1 text-xs text-rose-800">{measureError}</p>}
        </div>
      ) : (
        <p className="mt-3 text-xs leading-5 text-[#55607A]">Measure endpoints needs a chosen closed and open frame, so it is available for uploaded videos only.</p>
      )}
      <p className="mt-3 text-xs leading-5 text-[#55607A]">Standard gate-state thresholds and ENTRY/EXIT line-side defaults are applied automatically. The line itself can still be drawn on the frame.</p>
    </Card>
  );
}

/** One source's editor. Mounted per source, so switching "Apply zones to" can never carry drafts across. */
function SourceEditor({ source, assignmentItem, job, liveZones, zoneTypes, otherJobs, worker, reloadLiveZones, onLiveCalibrationSaved, onVideoConfigSaved, onZoneConfigurationsChanged = () => {} }) {
  const isVideo = source === 'video';
  const assignment = assignmentItem?.assignment ?? null;
  const frame = useMemo(() => {
    if (isVideo) return job?.width && job?.height ? { width: job.width, height: job.height } : null;
    if (worker?.width && worker?.height) return { width: worker.width, height: worker.height };
    return assignment?.calibration?.reference_frame ?? null;
  }, [isVideo, job?.width, job?.height, worker?.width, worker?.height, assignment?.calibration?.reference_frame]);

  const [loaded, setLoaded] = useState(!isVideo);
  const [loadError, setLoadError] = useState('');
  const [editable, setEditable] = useState(true);
  const [baseZones, setBaseZones] = useState([]);
  const [zones, setZones] = useState([]);
  const crossingStrategy = 'three_zone';
  const [savedCalibration, setSavedCalibration] = useState(isVideo ? null : assignment?.calibration ?? null);
  const baseFormRef = useRef(calibrationToForm(null));
  const baseZoneConfigurationRef = useRef('');
  // What Cancel returns to: the opening draft, including values prefilled from the assignment.
  const openingRef = useRef({ form: calibrationToForm(null), rules: {}, note: '' });
  const [form, setForm] = useState(() => calibrationToForm(null));
  const [baseRules, setBaseRules] = useState({});
  const [rules, setRules] = useState({});
  const [prefillNote, setPrefillNote] = useState('');
  const [drawing, setDrawing] = useState(null);
  const [lineStart, setLineStart] = useState(null);
  const [editId, setEditId] = useState(null);
  const [draftType, setDraftType] = useState(zoneTypes[0]?.key ?? 'gate_leaf_roi');
  const [draftName, setDraftName] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [copySource, setCopySource] = useState('');
  const [copying, setCopying] = useState(false);
  const [measuring, setMeasuring] = useState(false);
  const [measureError, setMeasureError] = useState('');
  const [frameSeconds, setFrameSeconds] = useState(0);
  const [frameKey, setFrameKey] = useState(0);
  const [liveFrameRequest, setLiveFrameRequest] = useState(0);
  const [savedZoneConfigurations, setSavedZoneConfigurations] = useState([]);
  const [selectedZoneConfigurationId, setSelectedZoneConfigurationId] = useState('');
  const [zoneConfigurationName, setZoneConfigurationName] = useState('');
  const [zoneConfigurationBusy, setZoneConfigurationBusy] = useState(false);

  const applyConfig = (config) => {
    const nextZones = (config.zones ?? []).map(normalizeZonePoints);
    setBaseZones(nextZones);
    setZones(nextZones);
    setSavedCalibration(config.calibration ?? null);
    const savedForm = calibrationToForm(config.calibration, frame);
    baseFormRef.current = savedForm;
    setEditable(config.editable !== false);
    setBaseRules(config.alert_configuration ?? {});
    setSelectedZoneConfigurationId(config.zone_configuration_id ?? config.id ?? '');
    baseZoneConfigurationRef.current = config.zone_configuration_id ?? '';
    if (config.name) setZoneConfigurationName(config.name);
    setDrawing(null); setLineStart(null); setEditId(null);
    // A job with nothing saved yet starts from the assignment's values, shown and unsaved until Save Changes.
    const template = assignment?.calibration;
    const templateFits = template?.reference_frame?.width === frame?.width && template?.reference_frame?.height === frame?.height;
    let openingForm = savedForm;
    let note = '';
    if (!config.calibration && template && config.editable !== false) {
      const prefilled = { ...calibrationToForm(template, frame), width: String(frame?.width ?? ''), height: String(frame?.height ?? '') };
      openingForm = templateFits ? prefilled : { ...prefilled, line_start_x: '', line_start_y: '', line_end_x: '', line_end_y: '' };
      note = `Calibration prefilled from ${assignmentItem.camera?.name ?? 'the assignment'}${templateFits ? '' : ' without its line, because the frame sizes differ'}. It will be saved with this video’s configuration.`;
    } else if (!config.calibration && frame && config.editable !== false) {
      openingForm = { ...savedForm, ...CALIBRATION_STARTING_VALUES,
        width: String(frame.width), height: String(frame.height),
        closed_reference_position: '0', open_reference_position: '1',
        horizontal_movement_direction: 'left_to_right', thresholds_status: 'unset' };
      note = 'This video has no saved reference calibration. The existing standard gate-state defaults are ready to save; endpoint measurement is optional.';
    }
    const templateRules = assignment?.configuration?.grill_gate_alerts;
    const openingRules = videoAlertConfigurationWithAssignmentDefault(config.alert_configuration, templateRules, config.editable !== false);
    openingRef.current = { form: openingForm, rules: openingRules, note };
    setForm(openingForm);
    setPrefillNote(note);
    setRules(openingRules);
  };

  useEffect(() => {
    let current = true;
    listGrillGateZoneConfigurations().then(({ items }) => { if (current) setSavedZoneConfigurations(items ?? []); })
      .catch((exception) => { if (current) setError(zoneConfigurationListError(exception)); });
    return () => { current = false; };
  }, []);

  useEffect(() => {
    if (!isVideo) return undefined;
    let cancelled = false;
    getVideoJobConfig(job.job_id).then(async (config) => {
      if (cancelled) return;
      const preferredId = initialVideoZoneConfigurationSelection(job);
      if (preferredId) {
        try {
          const saved = await getGrillGateZoneConfiguration(preferredId);
          const ref = saved.reference_frame;
          if (ref?.width === frame?.width && ref?.height === frame?.height) {
            if (!cancelled) {
              applyConfig({ ...saved, editable: config.editable, zone_configuration_id: saved.id });
              setLoaded(true);
              rememberVideoZoneConfigurationSelection(job, saved.id);
            }
            return;
          }
          rememberVideoZoneConfigurationSelection(job, '');
          if (!cancelled) setError(`Saved configuration ${saved.name} does not match this video's frame size; showing the video's saved configuration.`);
        } catch (exception) {
          if (exception?.response?.status === 404) {
            // Fall back to the immutable job snapshot if this saved configuration was removed.
            rememberVideoZoneConfigurationSelection(job, '');
          } else if (!cancelled) {
            setError(`Could not reload the selected saved configuration: ${describeError(exception).message}`);
          }
        }
      }
      if (!cancelled) { applyConfig(config); setLoaded(true); }
    })
      .catch((exception) => { if (!cancelled) { setLoadError(describeError(exception).message); setLoaded(true); } });
    return () => { cancelled = true; };
  }, [isVideo, job?.job_id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (isVideo) return;
    const nextZones = liveZones.filter((zone) => !['gate_trigger', 'gate_crossing'].includes(zone.zone_type)).map(normalizeZonePoints);
    setBaseZones(liveZones.map(normalizeZonePoints));
    setZones((current) => (countZoneChanges(baseZones, current) ? current : nextZones));
  }, [liveZones]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (isVideo) return;
    const savedRules = assignment?.configuration?.grill_gate_alerts ?? {};
    setBaseRules(savedRules);
    setRules(savedRules);
  }, [isVideo, assignment?.id, assignment?.configuration]);

  useEffect(() => {
    if (isVideo) return;
    const savedForm = calibrationToForm(assignment?.calibration, frame);
    baseFormRef.current = savedForm;
    setForm(savedForm);
    setSavedCalibration(assignment?.calibration ?? null);
  }, [isVideo, assignment?.id, assignment?.calibration]); // eslint-disable-line react-hooks/exhaustive-deps

  const image = useAuthorizedJpeg(
    (signal) => (isVideo ? getVideoJobFrame(job.job_id, frameSeconds, signal) : getLivePreview(assignment?.id, signal)),
    isVideo ? (job?.video_available ? `${job.job_id}:${frameKey}` : null) : (assignment?.id && worker?.status === 'connected' ? `${assignment.id}:${liveFrameRequest}` : null),
  );

  const zoneChanges = countZoneChanges(baseZones, zones);
  const formChanged = JSON.stringify(form) !== JSON.stringify(baseFormRef.current);
  const rulesChanged = JSON.stringify(rules) !== JSON.stringify(baseRules);
  const changeCount = zoneChanges + (formChanged ? 1 : 0) + (rulesChanged ? 1 : 0);
  const finishedVideo = isVideo && ['COMPLETED', 'FAILED', 'CANCELLED'].includes(job?.status);
  const canEditConfiguration = editable || finishedVideo;
  const readOnly = !canEditConfiguration || !frame;
  const line = formLine(form);
  const gateZone = zones.find((zone) => zone.zone_type === 'gate_leaf_roi' && zone.enabled !== false);
  const savedGateZone = baseZones.some((zone) => zone.zone_type === 'gate_leaf_roi' && zone.enabled !== false);
  const measured = gateZone?.properties?.measured_endpoints;
  const usedKeys = new Set(zones.map((zone) => zone.zone_type));
  const activeZoneTypes = zoneTypesForStrategy(zoneTypes);
  const visibleZones = zones;
  const legend = activeZoneTypes.filter((type) => usedKeys.has(type.key) || true);


  const setField = (name, value) => setForm((current) => {
    const next = { ...current, [name]: value };
    // Sides must be opposite; mirror the choice visibly instead of letting the backend reject it.
    if (name === 'outside_side' && value) next.inside_side = value === 'left' ? 'right' : 'left';
    if (name === 'inside_side' && value) next.outside_side = value === 'left' ? 'right' : 'left';
    return next;
  });

  const startPolygon = () => {
    setError(''); setNotice(''); setEditId(null); setLineStart(null);
    setDraftName(zoneTypes.find((type) => type.key === draftType)?.label ?? 'New zone');
    setDrawing({ kind: 'polygon', zoneType: draftType, points: [] });
  };
  const startLine = () => {
    setError(''); setNotice(''); setEditId(null); setLineStart(null);
    setDrawing({ kind: 'line' });
  };
  const onPoint = (point) => {
    if (drawing?.kind === 'polygon') {
      setDrawing((current) => ({ ...current, points: [...current.points, point] }));
    } else if (drawing?.kind === 'line') {
      if (!lineStart) { setLineStart(point); return; }
      setForm((current) => ({ ...current, line_start_x: String(lineStart.x), line_start_y: String(lineStart.y), line_end_x: String(point.x), line_end_y: String(point.y) }));
      setLineStart(null);
      setDrawing(null);
    }
  };
  const finishPolygon = () => {
    if (drawing?.points?.length < 3) return;
    const name = draftName.trim();
    if (!name) { setError('Enter a name for this zone.'); return; }
    let polygon;
    try {
      polygon = prepareZonePolygons([{ name, polygon: drawing.points }], frame)[0].polygon
        .map(([x, y]) => ({ x, y }));
    } catch (exception) { setError(zoneValidationMessage(exception)); return; }
    const key = `${drawing.zoneType}_${Date.now().toString(36)}`.slice(0, 40);
    setZones((current) => [...current, { id: `draft-${key}`, zone_key: key, name, zone_type: drawing.zoneType,
      description: zoneTypes.find((type) => type.key === drawing.zoneType)?.description ?? '', polygon, enabled: true }]);
    setDrawing(null);
    setError('');
  };
  const moveZone = (zoneId, polygon) => setZones((current) => current.map((zone) => (zone.id === zoneId ? { ...zone, polygon } : zone)));
  const renameZone = (zoneId, name) => setZones((current) => current.map((zone) => (zone.id === zoneId ? { ...zone, name } : zone)));

  const cancel = () => {
    setZones(baseZones.filter((zone) => !['gate_trigger', 'gate_crossing'].includes(zone.zone_type)));
    if (isVideo) {
      setForm(openingRef.current.form);
      setRules(openingRef.current.rules);
      setPrefillNote(openingRef.current.note);
    } else {
      setForm(baseFormRef.current);
      setRules(baseRules);
    }
    setDrawing(null); setLineStart(null); setEditId(null); setError('');
    setSelectedZoneConfigurationId(baseZoneConfigurationRef.current);
    setZoneConfigurationName(savedZoneConfigurations.find((item) => item.id === baseZoneConfigurationRef.current)?.name ?? '');
    setNotice('Changes discarded.');
  };

  const calibrationToSave = () => (formChanged ? calibrationFromForm(form, frame) : savedCalibration);

  const saveVideo = async () => {
    if (!editable) {
      const baseName = (job.filename || 'Gate video').replace(/\.[^.]+$/, '').trim();
      const enteredName = zoneConfigurationName.trim();
      const nameBase = selectedZoneConfigurationId
        ? `${enteredName || baseName} edited ${new Date().toLocaleString()}`
        : (enteredName || `${baseName} reprocess ${new Date().toLocaleString()}`);
      const name = nameBase.slice(0, 120);
      const saved = await createGrillGateZoneConfiguration(namedConfigurationPayload(name));
      setSelectedZoneConfigurationId(saved.id);
      rememberVideoZoneConfigurationSelection(job, saved.id);
      setZoneConfigurationName(saved.name);
      setRules(saved.alert_configuration ?? rules);
      setBaseZones(prepareZonePolygons(zones, frame).map(normalizeZonePoints));
      setZones(prepareZonePolygons(zones, frame).map(normalizeZonePoints));
      setSavedCalibration(saved.calibration ?? null);
      baseFormRef.current = form;
      setBaseRules(saved.alert_configuration ?? rules);
      setEditId(null); setDrawing(null); setLineStart(null);
      onZoneConfigurationsChanged?.();
      await refreshZoneConfigurations();
      setNotice(`Saved “${saved.name}” for reprocessing. The completed run keeps its original configuration.`);
      return;
    }
    const updated = await putVideoJobConfig(job.job_id, {
      calibration: calibrationToSave(), zones: prepareZonePolygons(zones, frame).map(normalizeZonePoints).map(zoneForSave), alert_configuration: rules,
      zone_configuration_id: selectedZoneConfigurationId || null,
    });
    applyConfig(updated);
    rememberVideoZoneConfigurationSelection(job, updated.zone_configuration_id || '');
    onVideoConfigSaved();
  };

  const namedConfigurationPayload = (name) => ({
    name,
    reference_frame: frame,
    calibration: calibrationToSave(),
    zones: prepareZonePolygons(zones, frame).map(normalizeZonePoints).map(zoneForSave),
    alert_configuration: rules,
  });

  const refreshZoneConfigurations = async () => {
    const { items } = await listGrillGateZoneConfigurations();
    setSavedZoneConfigurations(items ?? []);
  };

  const loadNamedZoneConfiguration = async (configurationId) => {
    setError(''); setNotice('');
    if (!configurationId) {
      setSelectedZoneConfigurationId(''); setZoneConfigurationName('');
      if (isVideo) rememberVideoZoneConfigurationSelection(job, '');
      return;
    }
    setZoneConfigurationBusy(true);
    try {
      const configuration = await getGrillGateZoneConfiguration(configurationId);
      const ref = configuration.reference_frame;
      if (ref?.width !== frame?.width || ref?.height !== frame?.height) {
        throw new Error(`This configuration uses ${ref?.width} × ${ref?.height}; the selected source is ${frame?.width} × ${frame?.height}. Zones are not rescaled.`);
      }
      if (isVideo && !canEditConfiguration) throw new Error('This video is currently processing, so its configuration is locked.');
      setZones((configuration.zones ?? []).map(normalizeZonePoints));
      setSavedCalibration(configuration.calibration ?? null);
      const nextForm = calibrationToForm(configuration.calibration, frame);
      setForm(nextForm);
      if (!formChanged) baseFormRef.current = calibrationToForm(savedCalibration, frame);
      setRules(configuration.alert_configuration ?? {});
      setSelectedZoneConfigurationId(configuration.id);
      if (isVideo) rememberVideoZoneConfigurationSelection(job, configuration.id);
      setZoneConfigurationName(configuration.name);
      setDrawing(null); setLineStart(null); setEditId(null);
      setNotice(`Loaded “${configuration.name}”. Review the polygons and settings, then Save Changes before processing.`);
    } catch (exception) {
      setError(describeError(exception).message);
    } finally {
      setZoneConfigurationBusy(false);
    }
  };

  const saveNamedZoneConfiguration = async (mode) => {
    if (zoneConfigurationBusy || readOnly) return;
    const name = zoneConfigurationName.trim();
    if (!name) { setError('Enter a name for the zone configuration.'); return; }
    if (!frame || !calibrationToSave()) { setError('Save a valid calibration before saving a reusable zone configuration.'); return; }
    setZoneConfigurationBusy(true); setError(''); setNotice('');
    try {
      let saved;
      const payload = namedConfigurationPayload(name);
      if (mode === 'update' && selectedZoneConfigurationId) {
        saved = await updateGrillGateZoneConfiguration(selectedZoneConfigurationId, payload);
        setNotice(`Updated “${saved.name}”. Existing video runs keep their saved configuration snapshots.`);
      } else if (mode === 'save_as' && selectedZoneConfigurationId && !changeCount) {
        saved = await duplicateGrillGateZoneConfiguration(selectedZoneConfigurationId, name);
        setSelectedZoneConfigurationId(saved.id);
        setNotice(`Created “${saved.name}” as a separate configuration.`);
      } else {
        saved = await createGrillGateZoneConfiguration(payload);
        setSelectedZoneConfigurationId(saved.id);
        setNotice(`Saved “${saved.name}”.`);
      }
      setZones(prepareZonePolygons(zones, frame).map(normalizeZonePoints));
      setZoneConfigurationName(saved.name);
      setRules(saved.alert_configuration ?? rules);
      if (isVideo) rememberVideoZoneConfigurationSelection(job, saved.id);
      await refreshZoneConfigurations();
      onZoneConfigurationsChanged?.();
    } catch (exception) {
      setError(zoneValidationMessage(exception, zones));
      if (zoneValidationIndex(exception) != null) setEditId(zones[zoneValidationIndex(exception)]?.id);
    } finally {
      setZoneConfigurationBusy(false);
    }
  };

  const saveAsZoneConfiguration = async () => saveNamedZoneConfiguration('save_as');

  const deleteSavedZoneConfiguration = async () => {
    const saved = savedZoneConfigurations.find((entry) => entry.id === selectedZoneConfigurationId);
    if (!saved || !window.confirm(`Delete saved zone configuration “${saved.name}”? Existing job snapshots will remain unchanged.`)) return;
    setZoneConfigurationBusy(true); setError(''); setNotice('');
    try {
      await deleteGrillGateZoneConfiguration(saved.id);
      setSelectedZoneConfigurationId(''); setZoneConfigurationName('');
      if (isVideo) rememberVideoZoneConfigurationSelection(job, '');
      await refreshZoneConfigurations();
      onZoneConfigurationsChanged?.();
      setNotice(`Deleted “${saved.name}”.`);
    } catch (exception) { setError(describeError(exception).message); }
    finally { setZoneConfigurationBusy(false); }
  };

  const saveLive = async () => {
    const cleanedZones = prepareZonePolygons(zones, frame).map(normalizeZonePoints);
    const assignmentId = assignment.id;
    const changedZoneConfiguration = Boolean(zoneChanges);
    const changedCalibration = formChanged;
    let savedAssignment = null;
    const originals = new Map(baseZones.map((zone) => [zone.id, zone]));
    for (const original of baseZones) {
      const next = cleanedZones.find((zone) => zone.id === original.id);
      if (!next) { await deleteAssignmentZone(assignmentId, original.id); continue; }
      const before = originals.get(original.id);
      const patch = {};
      for (const key of ['name', 'zone_type', 'enabled']) if (next[key] !== before[key]) patch[key] = next[key];
      if (JSON.stringify(next.polygon) !== JSON.stringify(before.polygon)) patch.polygon = next.polygon.map(({ x, y }) => [x, y]);
      if (Object.keys(patch).length) await updateAssignmentZone(assignmentId, original.id, patch);
    }
    for (const zone of cleanedZones.filter((entry) => String(entry.id).startsWith('draft-'))) {
      const { id, ...body } = zoneForSave(zone);
      await createAssignmentZone(assignmentId, body);
    }
    if (changedCalibration) {
      savedAssignment = await saveAssignmentCalibration(assignmentId, calibrationFromForm(form, frame));
      onLiveCalibrationSaved(savedAssignment);
    }
    if (rulesChanged) {
      try {
        const configuration = mergeGrillGateAlertConfiguration(assignment.configuration, rules);
        savedAssignment = await updateAssignmentConfiguration(assignmentId, configuration);
        const confirmedRules = savedAssignment.configuration?.grill_gate_alerts ?? rules;
        setRules(confirmedRules);
        setBaseRules(confirmedRules);
        onLiveCalibrationSaved(savedAssignment);
      } catch (exception) {
        const persistedRules = assignment.configuration?.grill_gate_alerts ?? {};
        setRules(persistedRules);
        setBaseRules(persistedRules);
        const savedParts = [changedZoneConfiguration && 'zones', changedCalibration && 'calibration'].filter(Boolean);
        const savedLabel = savedParts.length === 2 ? 'Zones and calibration were saved'
          : savedParts[0] === 'zones' ? 'Zones were saved'
            : savedParts[0] === 'calibration' ? 'Calibration was saved' : '';
        const prefix = savedLabel
          ? `${savedLabel}, but alert settings were not saved:`
          : 'Alert settings were not saved:';
        throw new Error(`${prefix} ${describeError(exception).message}`);
      }
    }
    await reloadLiveZones();
    setBaseZones(cleanedZones);
    setZones(cleanedZones);
    setEditId(null); setDrawing(null);
  };

  const save = async () => {
    if (saving || !changeCount) return;
    setSaving(true); setError(''); setNotice('');
    try {
      prepareZonePolygons(zones, frame);
      if (isVideo) await saveVideo(); else await saveLive();
      setPrefillNote('');
      if (!finishedVideo) setNotice('Changes saved.');
    } catch (exception) {
      setError(zoneValidationMessage(exception, zones));
      if (zoneValidationIndex(exception) != null) setEditId(zones[zoneValidationIndex(exception)]?.id);
    } finally {
      setSaving(false);
    }
  };

  const copyFrom = async () => {
    if (!copySource) return;
    if (changeCount && !window.confirm('Copying replaces your unsaved changes and this video’s saved zones and calibration. Continue?')) return;
    setCopying(true); setError(''); setNotice('');
    try {
      const [kind, id] = copySource.split(':');
      let updated;
      if (kind === 'saved') {
        const saved = await getGrillGateZoneConfiguration(id);
        if (saved.reference_frame?.width !== frame?.width || saved.reference_frame?.height !== frame?.height) {
          throw new Error(`This configuration uses ${saved.reference_frame?.width} × ${saved.reference_frame?.height}; this video uses ${frame?.width} × ${frame?.height}. Zones are not rescaled.`);
        }
        updated = await putVideoJobConfig(job.job_id, {
          calibration: saved.calibration,
          zones: saved.zones,
          alert_configuration: saved.alert_configuration ?? {},
          zone_configuration_id: saved.id,
        });
        setZoneConfigurationName(saved.name);
      } else {
        updated = await copyVideoJobConfig(job.job_id, kind === 'job' ? { source_job_id: id } : { source_assignment_id: id });
      }
      applyConfig(updated);
      if (isVideo) rememberVideoZoneConfigurationSelection(job, updated.zone_configuration_id || '');
      onVideoConfigSaved();
      setNotice(kind === 'saved'
        ? 'Copied and saved into this video’s own editable configuration.'
        : 'Copied. These are this video’s own values now, and you can edit them.');
    } catch (exception) {
      setError(describeError(exception).message);
    } finally {
      setCopying(false);
    }
  };

  const measure = async (closedT, openT) => {
    setMeasuring(true); setMeasureError(''); setNotice('');
    try {
      const { endpoints } = await measureVideoJobEndpoints(job.job_id, closedT, openT);
      setZones((current) => current.map((zone) => (zone.id !== gateZone?.id ? zone : {
        ...zone,
        properties: { ...(zone.properties ?? {}), gate_geometry: { ...(zone.properties?.gate_geometry ?? {}), ...endpoints }, measured_endpoints: { closed_t: closedT, open_t: openT } },
      })));
      setNotice('Endpoints measured from the video. Select Save Changes to persist them for backend processing.');
    } catch (exception) {
      setMeasureError(describeError(exception).message);
    } finally {
      setMeasuring(false);
    }
  };

  if (!loaded) return <p className="text-sm text-[#55607A]">Loading this source&rsquo;s zones…</p>;
  if (loadError) return <ErrorNote>{loadError}</ErrorNote>;

  const drawHelp = drawing?.kind === 'line'
    ? (lineStart ? 'Click the second point of the ENTRY/EXIT line.' : 'Click the first point of the ENTRY/EXIT line.')
    : null;
  const emptyMessage = isVideo ? (job?.video_available ? 'Loading frame…' : 'The stored video is no longer available.')
    : worker?.status === 'connected' ? (image.error || 'Waiting for a frame…') : 'Connect the camera to draw on its latest frame.';

  return (
    <div className="space-y-4">
      {isVideo && !canEditConfiguration && <p role="status" className="rounded-lg bg-[#EEF1FA] p-3 text-sm text-[#34479B]">This video is processing, so its zones and calibration are locked.</p>}
      {finishedVideo && <p role="status" className="rounded-lg bg-[#EEF1FA] p-3 text-sm text-[#34479B]">Edit zones after processing, then save them as a reusable configuration for Process Again. The completed run’s snapshot stays unchanged.</p>}
      {error && <ErrorNote>{error}</ErrorNote>}
      <Card title="Saved zone configurations">
        <p className="mb-3 text-xs leading-5 text-[#55607A]">Load a saved configuration to review and edit it for this source. Frame dimensions must match; zones are never silently rescaled.</p>
        <div className="flex flex-wrap items-end gap-2">
          <label className="min-w-56 flex-1 text-xs text-[#55607A]">Select Saved Zone Configuration
            <select aria-label="Select Saved Zone Configuration" value={selectedZoneConfigurationId}
              disabled={zoneConfigurationBusy || (isVideo && !canEditConfiguration)} onChange={(event) => loadNamedZoneConfiguration(event.target.value)} className={smallField}>
              <option value="">Create new configuration</option>
              {savedZoneConfigurations.map((configuration) => <option key={configuration.id} value={configuration.id}>{configuration.name}</option>)}
            </select>
          </label>
          <label className="min-w-48 flex-1 text-xs text-[#55607A]">Configuration name
            <input value={zoneConfigurationName} maxLength={120} onChange={(event) => setZoneConfigurationName(event.target.value)} disabled={readOnly || zoneConfigurationBusy} className={smallField} />
          </label>
        </div>
        {isVideo && !canEditConfiguration && <p className="mt-2 text-xs text-[#55607A]">This video is processing. Its configuration will unlock when processing finishes.</p>}
        <div className="mt-3 flex flex-wrap gap-2">
          {!selectedZoneConfigurationId && <button type="button" className={btnPrimary} disabled={readOnly || zoneConfigurationBusy} onClick={() => saveNamedZoneConfiguration('create')}>{zoneConfigurationBusy ? 'Saving…' : 'Save Zone Configuration'}</button>}
          {selectedZoneConfigurationId && <button type="button" className={btnPrimary} disabled={readOnly || zoneConfigurationBusy} onClick={() => saveNamedZoneConfiguration('update')}>{zoneConfigurationBusy ? 'Saving…' : 'Update Saved Configuration'}</button>}
          {selectedZoneConfigurationId && <button type="button" className={btnGhost} disabled={readOnly || zoneConfigurationBusy} onClick={saveAsZoneConfiguration}>Save As New</button>}
          {selectedZoneConfigurationId && <button type="button" className={btnGhost} disabled={readOnly || zoneConfigurationBusy} onClick={deleteSavedZoneConfiguration}>Delete Configuration</button>}
        </div>
      </Card>
      <Card title="Zones on the frame" aside={!isVideo && worker?.status === 'connected' ? (
        <button type="button" className={btnGhost} onClick={() => setLiveFrameRequest((value) => value + 1)}>Refresh frame</button>
      ) : null}>
        <FrameCanvas zoneColor={zoneColor} frame={frame} imageUrl={image.url} emptyMessage={emptyMessage} zones={visibleZones} editId={editId} drawing={drawing} line={line} lineDraft={lineStart}
          readOnly={readOnly} onPoint={onPoint} onFinishPolygon={finishPolygon} onMoveZone={moveZone} />
        {isVideo && job?.duration_seconds > 0 && (
          <label className="mt-3 flex items-center gap-3 text-xs text-[#55607A]">
            <span className="w-14 shrink-0 tabular-nums">{formatVideoTime(frameSeconds)}</span>
            <input type="range" min="0" max={job.duration_seconds} step="0.1" value={frameSeconds} aria-label="Reference frame time" className="min-w-0 flex-1 accent-[#34479B]"
              onChange={(event) => setFrameSeconds(Number(event.target.value))}
              onPointerUp={() => setFrameKey((value) => value + 1)} onKeyUp={() => setFrameKey((value) => value + 1)} />
          </label>
        )}
        <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[#55607A]">
          {legend.map((type) => <li key={type.key} className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm" style={{ background: zoneColor(type.key) }} aria-hidden />{type.label}</li>)}
        </ul>
      </Card>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.7fr)_minmax(320px,1fr)]">
        <div className="min-w-0 space-y-4">
          <Card title="Zones" aside={(
            <span className="flex flex-wrap justify-end gap-2">
              <select aria-label="Zone type to draw" value={draftType} disabled={readOnly || Boolean(drawing)} onChange={(event) => setDraftType(event.target.value)}
                className="min-h-9 max-w-44 rounded-lg border border-[#D0D7E6] bg-white px-2 text-xs text-[#34479B] disabled:opacity-40">
                {activeZoneTypes.map((type) => <option key={type.key} value={type.key}>{type.label}</option>)}
              </select>
              <button type="button" className={btnGhost} disabled={readOnly || Boolean(drawing)} onClick={startPolygon}>+ Draw polygon</button>
              <button type="button" className={btnGhost} disabled={readOnly || Boolean(drawing)} onClick={startLine}>Draw ENTRY/EXIT line</button>
            </span>
          )}>
            {drawing?.kind === 'polygon' && (
              <div className="mb-3 flex flex-wrap items-center gap-2 rounded-md bg-[#F4F6FB] p-2">
                <label className="text-xs text-[#55607A]">Zone name <input value={draftName} onChange={(event) => setDraftName(event.target.value)} className="ml-1 rounded border border-[#D0D7E6] px-2 py-1 text-[#1C2B4D]" /></label>
                <span className="text-xs text-[#55607A]">Click at least 3 corners in order, then click near the first corner or Finish polygon.</span>
                <button type="button" className={btnGhost} disabled={!drawing.points.length} onClick={() => setDrawing((current) => ({ ...current, points: current.points.slice(0, -1) }))}><Undo2 size={13} aria-hidden /> Undo point</button>
                <button type="button" className={btnPrimary} disabled={drawing.points.length < 3} onClick={finishPolygon}><Check size={13} aria-hidden /> Finish polygon</button>
                <button type="button" className={btnGhost} onClick={() => setDrawing(null)}>Cancel</button>
              </div>
            )}
            {drawHelp && (
              <div className="mb-3 flex flex-wrap items-center gap-2 rounded-md bg-[#EEF1FA] p-2 text-xs text-[#34479B]">
                {drawHelp} This line is separate from the crossing corridor polygon.
                <button type="button" className={btnGhost} onClick={() => { setDrawing(null); setLineStart(null); }}>Cancel</button>
              </div>
            )}
            <ul className="divide-y divide-[#E3E7F0] border-t border-[#E3E7F0]">
              {zones.map((zone) => (
                <li key={zone.id} className="flex flex-wrap items-center gap-3 py-2.5">
                  <span className="h-2 w-10 shrink-0 rounded-full" style={{ background: zoneColor(zone.zone_type) }} aria-hidden />
                  <span className="min-w-0 flex-1 text-sm text-[#0F1B3D]">
                    {editId === zone.id && !readOnly
                      ? <input aria-label="Zone name" value={zone.name} onChange={(event) => renameZone(zone.id, event.target.value)} className="rounded border border-[#D0D7E6] px-2 py-0.5" />
                      : zone.name}
                    <span className="ml-2 text-xs text-[#69758F]">{zone.zone_type}</span>
                    {zone.enabled === false && <span className="ml-2 text-xs text-[#69758F]">hidden</span>}
                  </span>
                  <span className="flex shrink-0 items-center gap-1">
                    <button type="button" className={btnGhost} disabled={readOnly} aria-label={`${zone.enabled === false ? 'Show' : 'Hide'} ${zone.name}`}
                      onClick={() => setZones((current) => current.map((entry) => (entry.id === zone.id ? { ...entry, enabled: entry.enabled === false } : entry)))}>
                      {zone.enabled === false ? <Eye size={13} aria-hidden /> : <EyeOff size={13} aria-hidden />}
                    </button>
                    <button type="button" className={btnGhost} disabled={readOnly || Boolean(drawing)} aria-pressed={editId === zone.id} onClick={() => setEditId(editId === zone.id ? null : zone.id)}>{editId === zone.id ? 'Done' : 'Edit'}</button>
                    <button type="button" className={btnGhost} disabled={readOnly} aria-label={`Delete ${zone.name}`}
                      onClick={() => { setZones((current) => current.filter((entry) => entry.id !== zone.id)); if (editId === zone.id) setEditId(null); }}><Trash2 size={13} aria-hidden /></button>
                  </span>
                </li>
              ))}
              {!zones.length && <li className="py-3 text-sm text-[#55607A]">No zones yet. Choose a zone type and draw a polygon.</li>}
            </ul>
            {editId && <p className="mt-2 text-xs text-[#55607A]">Drag a point to reshape the zone, or drag inside it to move it.</p>}
            {line && <p className="mt-2 text-xs text-[#55607A]">ENTRY/EXIT line set: ({line.start.x}, {line.start.y}) to ({line.end.x}, {line.end.y}). Crossing events use the approach and interior endpoint zones; this line alone does not create events.</p>}
          </Card>
          <AlertRulesCard rules={rules} onChange={setRules} disabled={!canEditConfiguration} isVideo={isVideo} />
        </div>
        <div className="min-w-0 space-y-4">
          <CalibrationCard source={source} frame={frame} savedFrame={savedCalibration?.reference_frame}
            disabled={!canEditConfiguration} prefillNote={prefillNote}
            measuredLabel={measured ? `Closed frame at ${formatVideoTime(measured.closed_t)} · Open frame at ${formatVideoTime(measured.open_t)}` : ''}
            duration={job?.duration_seconds} frameTime={frameSeconds} measuring={measuring} measureError={measureError} onMeasure={measure} canMeasure={savedGateZone} />
          {isVideo && editable && (
            <Card title="Copy zones & calibration from…">
              <p className="mb-2 text-xs leading-5 text-[#55607A]">Copied only when frame sizes match, as this video&rsquo;s own editable values.</p>
              <div className="flex flex-wrap gap-2">
                <select aria-label="Copy from" className={`${smallField} !mt-0 min-w-0 flex-1`} value={copySource} onChange={(event) => setCopySource(event.target.value)}>
                  <option value="">Choose a source…</option>
                  {assignment && <option value={`assignment:${assignment.id}`}>Live camera · {assignmentItem.camera?.name ?? assignment.camera_id}</option>}
                  {otherJobs.map((row) => <option key={row.job_id} value={`job:${row.job_id}`}>Video · {row.filename}</option>)}
                  {savedZoneConfigurations.map((configuration) => <option key={configuration.id} value={`saved:${configuration.id}`}>Saved configuration · {configuration.name}</option>)}
                </select>
                <button type="button" className={btnGhost} disabled={!copySource || copying} onClick={copyFrom}>{copying ? 'Copying…' : 'Copy'}</button>
              </div>
            </Card>
          )}
          <Card>
            <p className="text-sm text-[#55607A]">{changeCount ? `Unsaved changes: ${changeCount}` : 'No unsaved changes'}</p>
            {notice && <p role="status" className="mt-1 text-xs text-[#34479B]">{notice}</p>}
            <div className="mt-3 flex flex-wrap gap-2">
              <button type="button" className={btnGhost} disabled={!changeCount || saving} onClick={cancel}>Cancel</button>
              <button type="button" className={btnPrimary} disabled={!changeCount || saving || !canEditConfiguration} onClick={save}>{saving ? 'Saving…' : 'Save Changes'}</button>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

export default function ZonesSection({ apply, onApplyChange, assignmentItem, job, otherJobs, liveZones, zoneTypes, worker, reloadLiveZones, onLiveCalibrationSaved, onVideoConfigSaved, onZoneConfigurationsChanged }) {
  const choices = [
    ['live', assignmentItem ? `Live camera · ${assignmentItem.camera?.name ?? 'assignment'}` : 'Live camera', Boolean(assignmentItem)],
    ['video', job ? `Uploaded video · ${job.filename}` : 'Uploaded video', Boolean(job)],
  ];
  const selected = apply === 'video' && job ? 'video' : apply === 'live' && assignmentItem ? 'live' : job ? 'video' : assignmentItem ? 'live' : null;
  return (
    <div className="space-y-4">
      <Card title="Apply zones to">
        <div className="flex flex-wrap gap-2" role="group" aria-label="Apply zones to">
          {choices.map(([key, text, enabled]) => (
            <button key={key} type="button" aria-pressed={selected === key} disabled={!enabled} onClick={() => onApplyChange(key)}
              className={`min-h-10 rounded-lg px-3 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-40 ${selected === key ? 'bg-[#34479B] text-white' : 'bg-white text-[#34479B] ring-1 ring-[#E3E7F0] hover:bg-[#F4F6FB]'}`}>
              {text}
            </button>
          ))}
        </div>
        <p className="mt-2 text-xs text-[#55607A]">Each source keeps its own zones and calibration. Nothing is shared or rescaled.</p>
      </Card>
      {!selected && <p className="text-sm text-[#55607A]">Assign a camera or upload a video first.</p>}
      {selected && (
        <SourceEditor key={selected === 'video' ? `video:${job.job_id}` : `live:${assignmentItem.assignment.id}`} source={selected} assignmentItem={assignmentItem} job={job}
          liveZones={liveZones} zoneTypes={zoneTypes} otherJobs={otherJobs} worker={worker} reloadLiveZones={reloadLiveZones}
          onLiveCalibrationSaved={onLiveCalibrationSaved} onVideoConfigSaved={onVideoConfigSaved}
          onZoneConfigurationsChanged={onZoneConfigurationsChanged} />
      )}
    </div>
  );
}
