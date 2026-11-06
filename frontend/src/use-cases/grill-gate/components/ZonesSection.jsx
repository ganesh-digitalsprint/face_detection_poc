import { useEffect, useMemo, useRef, useState } from 'react';
import { Check, EyeOff, Eye, Trash2, Undo2 } from 'lucide-react';
import { describeError } from '../../../utils/errors.js';
import {
  copyVideoJobConfig, createAssignmentZone, deleteAssignmentZone, getLivePreview, getVideoJobConfig, getVideoJobFrame,
  measureVideoJobEndpoints, putVideoJobConfig, saveAssignmentCalibration, updateAssignmentZone,
} from '../api/grillGate.js';
import { CALIBRATION_STARTING_VALUES, calibrationFromForm, calibrationToForm, formLine, formatSeconds, polygonPoints, zoneColor } from '../grillGateModel.js';
import { useAuthorizedJpeg } from '../hooks/useSourceData.js';
import { countZoneChanges, normalizeZonePoints, zoneForSave } from '../liveMonitoringModel.js';
import { formatVideoTime } from '../videoJobModel.js';
import CalibrationView from './CalibrationView.jsx';
import { btnGhost, btnPrimary, Card, ErrorNote } from './ui.jsx';

const smallField = 'mt-1 min-h-9 w-full rounded-md border border-[#D0D7E6] bg-white px-2.5 text-sm text-[#1C2B4D] outline-none focus:border-[#34479B] focus:ring-2 focus:ring-[#34479B]/20 disabled:bg-[#F4F6FB]';
const clamp = (value) => Math.max(0, Math.min(1, value));
const ALERT_RULES = [
  ['gate_open', 'Gate open too long', 'max_gate_open_seconds', 'Max open (s)'],
  ['partially_open', 'Gate partially open too long', 'max_partially_open_seconds', 'Max partially open (s)'],
  ['mesh_occupancy', 'Too many people in mesh area', 'max_mesh_occupancy', 'Max people'],
];

function FrameCanvas({ frame, imageUrl, emptyMessage, zones, editId, drawing, line, lineDraft, readOnly, onPoint, onMoveZone }) {
  const svgRef = useRef(null);
  const dragRef = useRef(null);

  const pointFrom = (event) => {
    const svg = svgRef.current;
    const matrix = svg?.getScreenCTM();
    if (!matrix) return null;
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const raw = point.matrixTransform(matrix.inverse());
    if (raw.x < 0 || raw.y < 0 || raw.x > frame.width || raw.y > frame.height) return null;
    return { x: Math.round((raw.x / frame.width) * 10000) / 10000, y: Math.round((raw.y / frame.height) * 10000) / 10000 };
  };
  const onCanvasDown = (event) => {
    if (!drawing || readOnly) return;
    const point = pointFrom(event);
    if (point) onPoint(point);
  };
  const startDrag = (event, zone, kind, index = -1) => {
    if (drawing || readOnly) return;
    event.stopPropagation();
    const point = pointFrom(event);
    if (!point) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    dragRef.current = { zoneId: zone.id, kind, index, origin: point, polygon: zone.polygon.map((p) => ({ ...p })) };
  };
  const onDrag = (event) => {
    const drag = dragRef.current;
    if (!drag) return;
    const point = pointFrom(event);
    if (!point) return;
    onMoveZone(drag.zoneId, drag.polygon.map((vertex, index) => {
      if (drag.kind === 'point') return index === drag.index ? point : vertex;
      return { x: clamp(vertex.x + point.x - drag.origin.x), y: clamp(vertex.y + point.y - drag.origin.y) };
    }));
  };

  const width = frame?.width ?? 16;
  const height = frame?.height ?? 9;
  const fontSize = Math.max(14, width * 0.016);
  return (
    <div className="relative overflow-hidden rounded-lg bg-[#18202E]" style={{ aspectRatio: String(width / height) }}>
      {imageUrl && <img src={imageUrl} alt="Reference frame for drawing zones" className="absolute inset-0 h-full w-full object-fill" />}
      {!imageUrl && <p className="absolute inset-0 flex items-center justify-center p-6 text-center text-sm text-slate-200">{emptyMessage}</p>}
      {frame && (
        <svg ref={svgRef} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-label="Zones on the frame"
          className={`absolute inset-0 h-full w-full touch-none ${drawing ? 'cursor-crosshair' : ''}`}
          onPointerDown={onCanvasDown} onPointerMove={onDrag} onPointerUp={() => { dragRef.current = null; }}>
          {zones.map((zone) => {
            const points = polygonPoints(zone.polygon);
            if (points.length < 3) return null;
            const color = zoneColor(zone.zone_type);
            const selected = editId === zone.id;
            return (
              <g key={zone.id} opacity={zone.enabled === false ? 0.3 : 1}>
                <polygon points={points.map(({ x, y }) => `${x * width},${y * height}`).join(' ')} fill={`${color}33`} stroke={color}
                  strokeWidth={selected ? 3 : 2} vectorEffect="non-scaling-stroke"
                  className={selected && !readOnly ? 'cursor-move' : ''}
                  onPointerDown={selected ? (event) => startDrag(event, zone, 'move') : undefined} />
                {selected && !readOnly && points.map((point, index) => (
                  <circle key={index} cx={point.x * width} cy={point.y * height} r={Math.max(6, width * 0.006)} fill="white" stroke={color} strokeWidth="3"
                    vectorEffect="non-scaling-stroke" className="cursor-grab" onPointerDown={(event) => startDrag(event, zone, 'point', index)} />
                ))}
                <text x={Math.min(...points.map((p) => p.x)) * width + fontSize * 0.5} y={(points.reduce((sum, p) => sum + p.y, 0) / points.length) * height}
                  fill="white" stroke="#18202E" strokeWidth="3" paintOrder="stroke" fontSize={fontSize} pointerEvents="none">{zone.name}</text>
              </g>
            );
          })}
          {drawing?.kind === 'polygon' && drawing.points.length > 0 && (
            <g>
              <polyline points={drawing.points.map((p) => `${p.x * width},${p.y * height}`).join(' ')} fill="none" stroke={zoneColor(drawing.zoneType)} strokeWidth="3" vectorEffect="non-scaling-stroke" />
              {drawing.points.map((p, index) => <circle key={index} cx={p.x * width} cy={p.y * height} r={Math.max(5, width * 0.005)} fill="white" stroke={zoneColor(drawing.zoneType)} strokeWidth="2" vectorEffect="non-scaling-stroke" />)}
            </g>
          )}
          {lineDraft && <circle cx={lineDraft.x * width} cy={lineDraft.y * height} r={Math.max(6, width * 0.006)} fill="white" />}
          {line && (
            <g pointerEvents="none">
              <line x1={line.start.x * width} y1={line.start.y * height} x2={line.end.x * width} y2={line.end.y * height} stroke="white" strokeWidth="3" strokeDasharray="10 7" vectorEffect="non-scaling-stroke" />
              <text x={line.start.x * width + fontSize * 0.6} y={line.start.y * height + fontSize} fill="white" stroke="#18202E" strokeWidth="3" paintOrder="stroke" fontSize={fontSize}>ENTRY / EXIT line</text>
            </g>
          )}
        </svg>
      )}
    </div>
  );
}

function AlertRulesCard({ rules, onChange, disabled }) {
  const set = (changes) => onChange({ ...rules, ...changes });
  return (
    <Card title="Alert rules for this video">
      <p className="mb-3 text-xs leading-5 text-[#55607A]">Copied from the assignment when one exists, and editable here. A rule stays off until its threshold is set.</p>
      <div className="space-y-3">
        {ALERT_RULES.map(([key, title, thresholdKey, thresholdLabel]) => {
          const threshold = rules[thresholdKey];
          const isSet = threshold != null && threshold !== '';
          return (
            <div key={key} className="grid items-end gap-2 sm:grid-cols-[1fr_110px]">
              <label className="flex items-center gap-2 text-sm text-[#0F1B3D]">
                <input type="checkbox" checked={Boolean(rules[`${key}_enabled`]) && isSet} disabled={disabled || !isSet}
                  onChange={(event) => set({ [`${key}_enabled`]: event.target.checked })} />
                {title}
              </label>
              <label className="block text-xs text-[#55607A]">{thresholdLabel}
                <input className={smallField} type="number" min="0" step="any" value={threshold ?? ''} disabled={disabled}
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

function CalibrationCard({ source, frame, savedFrame, form, setField, onStartingValues, showStartingValues, disabled, prefillNote, measuredLabel, duration, frameTime, measuring, measureError, onMeasure, canMeasure }) {
  const matches = savedFrame && frame && savedFrame.width === frame.width && savedFrame.height === frame.height;
  const [closedT, setClosedT] = useState('');
  const [openT, setOpenT] = useState('');
  return (
    <Card title="Calibration">
      <div className="space-y-1 text-sm text-[#55607A]">
        <p>{frame ? `Reference frame ${frame.width} × ${frame.height}` : 'Reference frame size is not known yet.'}
          {savedFrame && frame && (matches ? ' ✓ matches this source' : '')}
        </p>
        {savedFrame && frame && !matches && <p className="text-amber-800">Saved calibration is {savedFrame.width} × {savedFrame.height}, so it must be redone for this source. Coordinates are never rescaled.</p>}
        {measuredLabel && <p>{measuredLabel}</p>}
      </div>
      {prefillNote && <p className="mt-2 text-xs text-[#55607A]">{prefillNote}</p>}
      {source === 'video' ? (
        <div className="mt-3 rounded-md bg-[#F7F8FC] p-3 ring-1 ring-[#E3E7F0]">
          <p className="text-xs text-[#55607A]">Pick a video time where the door is fully closed and one where it is fully open{duration ? ` (0 to ${formatSeconds(duration)})` : ''}. Uses the saved gate zone.</p>
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
          {!canMeasure && !disabled && <p className="mt-1 text-xs text-amber-800">Save a Sliding gate leaf zone first.</p>}
          {measureError && <p role="alert" className="mt-1 text-xs text-rose-800">{measureError}</p>}
        </div>
      ) : (
        <p className="mt-3 text-xs leading-5 text-[#55607A]">Measure endpoints needs a chosen closed and open frame, so it is available for uploaded videos only.</p>
      )}
      <details className="mt-3">
        <summary className="cursor-pointer text-sm font-semibold text-[#34479B]">Calibration values</summary>
        <div className="mt-3">
          {showStartingValues && !disabled && (
            <button type="button" className={`${btnGhost} mb-3`} onClick={onStartingValues}>Use starting values</button>
          )}
          <CalibrationView form={form} setField={setField} disabled={disabled} />
        </div>
      </details>
    </Card>
  );
}

/** One source's editor. Mounted per source, so switching "Apply zones to" can never carry drafts across. */
function SourceEditor({ source, assignmentItem, job, liveZones, zoneTypes, otherJobs, worker, reloadLiveZones, onLiveCalibrationSaved, onVideoConfigSaved }) {
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
  const [savedCalibration, setSavedCalibration] = useState(isVideo ? null : assignment?.calibration ?? null);
  const baseFormRef = useRef(calibrationToForm(null));
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

  const applyConfig = (config) => {
    const nextZones = (config.zones ?? []).map(normalizeZonePoints);
    setBaseZones(nextZones);
    setZones(nextZones);
    setSavedCalibration(config.calibration ?? null);
    const savedForm = calibrationToForm(config.calibration, frame);
    baseFormRef.current = savedForm;
    setEditable(config.editable !== false);
    setBaseRules(config.alert_configuration ?? {});
    setDrawing(null); setLineStart(null); setEditId(null);
    // A job with nothing saved yet starts from the assignment's values, shown and unsaved until Save Changes.
    const template = assignment?.calibration;
    const templateFits = template?.reference_frame?.width === frame?.width && template?.reference_frame?.height === frame?.height;
    let openingForm = savedForm;
    let note = '';
    if (!config.calibration && template && config.editable !== false) {
      const prefilled = { ...calibrationToForm(template, frame), width: String(frame?.width ?? ''), height: String(frame?.height ?? '') };
      openingForm = templateFits ? prefilled : { ...prefilled, line_start_x: '', line_start_y: '', line_end_x: '', line_end_y: '' };
      note = `Values prefilled from ${assignmentItem.camera?.name ?? 'the assignment'}${templateFits ? '' : ' without its line, because the frame sizes differ'}. Review them and select Save Changes.`;
    }
    const hasRules = config.alert_configuration && Object.keys(config.alert_configuration).some((key) => key.startsWith('max_') && config.alert_configuration[key] != null);
    const templateRules = assignment?.configuration?.grill_gate_alerts;
    const openingRules = !hasRules && !config.calibration && templateRules && config.editable !== false ? { ...config.alert_configuration, ...templateRules } : config.alert_configuration ?? {};
    openingRef.current = { form: openingForm, rules: openingRules, note };
    setForm(openingForm);
    setPrefillNote(note);
    setRules(openingRules);
  };

  useEffect(() => {
    if (!isVideo) return undefined;
    let cancelled = false;
    getVideoJobConfig(job.job_id).then((config) => { if (!cancelled) { applyConfig(config); setLoaded(true); } })
      .catch((exception) => { if (!cancelled) { setLoadError(describeError(exception).message); setLoaded(true); } });
    return () => { cancelled = true; };
  }, [isVideo, job?.job_id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (isVideo) return;
    const nextZones = liveZones.map(normalizeZonePoints);
    setBaseZones(nextZones);
    setZones((current) => (countZoneChanges(baseZones, current) ? current : nextZones));
  }, [liveZones]); // eslint-disable-line react-hooks/exhaustive-deps

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
  const readOnly = !editable || !frame;
  const line = formLine(form);
  const gateZone = zones.find((zone) => zone.zone_type === 'gate_leaf_roi' && zone.enabled !== false);
  const savedGateZone = baseZones.some((zone) => zone.zone_type === 'gate_leaf_roi' && zone.enabled !== false);
  const measured = gateZone?.properties?.measured_endpoints;
  const usedKeys = new Set(zones.map((zone) => zone.zone_type));
  const legend = zoneTypes.filter((type) => usedKeys.has(type.key) || true);

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
    const key = `${drawing.zoneType}_${Date.now().toString(36)}`.slice(0, 40);
    setZones((current) => [...current, { id: `draft-${key}`, zone_key: key, name, zone_type: drawing.zoneType,
      description: zoneTypes.find((type) => type.key === drawing.zoneType)?.description ?? '', polygon: drawing.points, enabled: true }]);
    setDrawing(null);
    setError('');
  };
  const moveZone = (zoneId, polygon) => setZones((current) => current.map((zone) => (zone.id === zoneId ? { ...zone, polygon } : zone)));
  const renameZone = (zoneId, name) => setZones((current) => current.map((zone) => (zone.id === zoneId ? { ...zone, name } : zone)));

  const cancel = () => {
    setZones(baseZones);
    if (isVideo) {
      setForm(openingRef.current.form);
      setRules(openingRef.current.rules);
      setPrefillNote(openingRef.current.note);
    } else {
      setForm(baseFormRef.current);
    }
    setDrawing(null); setLineStart(null); setEditId(null); setError('');
    setNotice('Changes discarded.');
  };

  const calibrationToSave = () => (formChanged ? calibrationFromForm(form, frame) : savedCalibration);

  const saveVideo = async () => {
    const updated = await putVideoJobConfig(job.job_id, {
      calibration: calibrationToSave(), zones: zones.map(zoneForSave), alert_configuration: rules,
    });
    applyConfig(updated);
    onVideoConfigSaved();
  };

  const saveLive = async () => {
    const assignmentId = assignment.id;
    const originals = new Map(baseZones.map((zone) => [zone.id, zone]));
    for (const original of baseZones) {
      const next = zones.find((zone) => zone.id === original.id);
      if (!next) { await deleteAssignmentZone(assignmentId, original.id); continue; }
      const before = originals.get(original.id);
      const patch = {};
      for (const key of ['name', 'zone_type', 'enabled']) if (next[key] !== before[key]) patch[key] = next[key];
      if (JSON.stringify(next.polygon) !== JSON.stringify(before.polygon)) patch.polygon = next.polygon.map(({ x, y }) => [x, y]);
      if (Object.keys(patch).length) await updateAssignmentZone(assignmentId, original.id, patch);
    }
    for (const zone of zones.filter((entry) => String(entry.id).startsWith('draft-'))) {
      const { id, ...body } = zoneForSave(zone);
      await createAssignmentZone(assignmentId, body);
    }
    if (formChanged) {
      const updated = await saveAssignmentCalibration(assignmentId, calibrationFromForm(form, frame));
      onLiveCalibrationSaved(updated);
    }
    await reloadLiveZones();
    setEditId(null); setDrawing(null);
  };

  const save = async () => {
    if (saving || !changeCount) return;
    setSaving(true); setError(''); setNotice('');
    try {
      if (isVideo) await saveVideo(); else await saveLive();
      setPrefillNote('');
      setNotice('Changes saved.');
    } catch (exception) {
      setError(describeError(exception).message);
      if (!isVideo) await reloadLiveZones();
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
      const updated = await copyVideoJobConfig(job.job_id, kind === 'job' ? { source_job_id: id } : { source_assignment_id: id });
      applyConfig(updated);
      onVideoConfigSaved();
      setNotice('Copied. These are this video’s own values now, and you can edit them.');
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
      setNotice('Endpoints measured. Select Save Changes to keep them.');
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
      {!editable && <p role="status" className="rounded-lg bg-[#EEF1FA] p-3 text-sm text-[#34479B]">This job has started, so its zones and calibration are locked.</p>}
      {error && <ErrorNote>{error}</ErrorNote>}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.7fr)_minmax(320px,1fr)]">
        <div className="min-w-0 space-y-4">
          <Card title="Zones" aside={(
            <span className="flex flex-wrap justify-end gap-2">
              <select aria-label="Zone type to draw" value={draftType} disabled={readOnly || Boolean(drawing)} onChange={(event) => setDraftType(event.target.value)}
                className="min-h-9 max-w-44 rounded-lg border border-[#D0D7E6] bg-white px-2 text-xs text-[#34479B] disabled:opacity-40">
                {zoneTypes.map((type) => <option key={type.key} value={type.key}>{type.label}</option>)}
              </select>
              <button type="button" className={btnGhost} disabled={readOnly || Boolean(drawing)} onClick={startPolygon}>+ Draw polygon</button>
              <button type="button" className={btnGhost} disabled={readOnly || Boolean(drawing)} onClick={startLine}>Draw ENTRY/EXIT line</button>
            </span>
          )}>
            {drawing?.kind === 'polygon' && (
              <div className="mb-3 flex flex-wrap items-center gap-2 rounded-md bg-[#F4F6FB] p-2">
                <label className="text-xs text-[#55607A]">Zone name <input value={draftName} onChange={(event) => setDraftName(event.target.value)} className="ml-1 rounded border border-[#D0D7E6] px-2 py-1 text-[#1C2B4D]" /></label>
                <span className="text-xs text-[#55607A]">Click at least 3 points on the frame below.</span>
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
            {line && <p className="mt-2 text-xs text-[#55607A]">ENTRY/EXIT line set: ({line.start.x}, {line.start.y}) to ({line.end.x}, {line.end.y}).</p>}
          </Card>
          {isVideo && <AlertRulesCard rules={rules} onChange={setRules} disabled={!editable} />}
        </div>
        <div className="min-w-0 space-y-4">
          <CalibrationCard source={source} frame={frame} savedFrame={savedCalibration?.reference_frame} form={form} setField={setField}
            onStartingValues={() => setForm((current) => ({ ...current, ...CALIBRATION_STARTING_VALUES }))}
            showStartingValues={isVideo && !assignment?.calibration} disabled={!editable} prefillNote={prefillNote}
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
              <button type="button" className={btnPrimary} disabled={!changeCount || saving || !editable} onClick={save}>{saving ? 'Saving…' : 'Save Changes'}</button>
            </div>
          </Card>
        </div>
      </div>
      <Card title="Zones on the frame" aside={!isVideo && worker?.status === 'connected' ? (
        <button type="button" className={btnGhost} onClick={() => setLiveFrameRequest((value) => value + 1)}>Refresh frame</button>
      ) : null}>
        <FrameCanvas frame={frame} imageUrl={image.url} emptyMessage={emptyMessage} zones={zones} editId={editId} drawing={drawing} line={line} lineDraft={lineStart}
          readOnly={readOnly} onPoint={onPoint} onMoveZone={moveZone} />
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
    </div>
  );
}

export default function ZonesSection({ apply, onApplyChange, assignmentItem, job, otherJobs, liveZones, zoneTypes, worker, reloadLiveZones, onLiveCalibrationSaved, onVideoConfigSaved }) {
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
          onLiveCalibrationSaved={onLiveCalibrationSaved} onVideoConfigSaved={onVideoConfigSaved} />
      )}
    </div>
  );
}
