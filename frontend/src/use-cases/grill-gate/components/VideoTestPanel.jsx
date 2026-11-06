import { useEffect, useMemo, useRef, useState } from 'react';
import { Check, CircleHelp, Eye, EyeOff, Maximize, Pause, Pencil, Play, Plus, RotateCcw, Save, Trash2, Undo2, Upload, Video, X } from 'lucide-react';
import {
  createAssignmentZone, deleteAssignmentZone, saveAssignmentCalibration, updateAssignmentZone,
} from '../api/grillGate.js';
import { polygonPoints, zoneColor } from '../grillGateModel.js';
import { btnGhost, btnPrimary, Card, ErrorNote, Pill } from './ui.jsx';

const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const clamp = (v) => Math.max(0, Math.min(1, v));
const errorMessage = (exception) => {
  const detail = exception?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((entry) => {
    const location = Array.isArray(entry?.loc) ? `${entry.loc.join('.')}: ` : '';
    return `${location}${entry?.msg ?? JSON.stringify(entry)}`;
  }).join('; ');
  if (detail != null) return JSON.stringify(detail);
  return exception?.message || 'Could not save zone changes.';
};
const formatTime = (value) => {
  if (!Number.isFinite(value)) return '00:00';
  const whole = Math.max(0, Math.floor(value));
  return `${String(Math.floor(whole / 60)).padStart(2, '0')}:${String(whole % 60).padStart(2, '0')}`;
};
const calibrationLine = (calibration) => {
  const line = calibration?.directional_crossing;
  return line?.line_start && line?.line_end
    ? { start: line.line_start, end: line.line_end }
    : null;
};
const zoneType = (types, key) => types.find((entry) => entry.key === key);
const normalizeZone = (zone) => ({ ...zone, polygon: polygonPoints(zone.polygon).map(({ x, y }) => ({ x, y })) });

function ZoneEditor({ item, zones, zoneTypes, reloadZones, onCalibrationSaved, file, objectUrl, calibration, onFile, onFrameDimensions }) {
  const videoRef = useRef(null);
  const stageRef = useRef(null);
  const svgRef = useRef(null);
  const dragRef = useRef(null);
  const [frame, setFrame] = useState(null);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [draftZones, setDraftZones] = useState(() => zones.map(normalizeZone));
  const [localSavedZones, setLocalSavedZones] = useState(null);
  const [drawing, setDrawing] = useState(null);
  const [editId, setEditId] = useState(null);
  const [draftName, setDraftName] = useState('');
  const [draftType, setDraftType] = useState(zoneTypes[0]?.key ?? 'gate_leaf_roi');
  const [lineDraft, setLineDraft] = useState(null);
  const [savedLine, setSavedLine] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [saving, setSaving] = useState(false);

  const reference = calibration?.reference_frame;
  const hasAssignment = Boolean(item?.assignment?.id);
  const localConfigKey = frame && file
    ? `grill-gate-video-zones:${encodeURIComponent(file.name)}:${file.size}:${file.lastModified}:${frame.width}x${frame.height}`
    : null;
  const dimensionsMatch = Boolean(frame && reference && frame.width === reference.width && frame.height === reference.height);
  const calibrationMismatch = Boolean(frame && reference && !dimensionsMatch);
  const lineChanged = !equal(lineDraft, savedLine);
  const zonesChanged = !equal(draftZones, localSavedZones ?? zones.map(normalizeZone));
  const dirty = zonesChanged || lineChanged;
  const editedZone = draftZones.find((zone) => zone.id === editId);

  useEffect(() => {
    if (!dirty && !saving) setDraftZones(zones.map(normalizeZone));
  }, [zones, dirty, saving]);

  const handleMetadata = () => {
    const video = videoRef.current;
    if (!video?.videoWidth || !video?.videoHeight) return;
    const nextFrame = { width: video.videoWidth, height: video.videoHeight };
    setFrame(nextFrame);
    onFrameDimensions?.(nextFrame);
    setDuration(Number.isFinite(video.duration) ? video.duration : 0);
    if (!hasAssignment) {
      const key = `grill-gate-video-zones:${encodeURIComponent(file.name)}:${file.size}:${file.lastModified}:${nextFrame.width}x${nextFrame.height}`;
      try {
        const stored = JSON.parse(window.localStorage.getItem(key) || 'null');
        if (Array.isArray(stored?.zones)) {
          const restored = stored.zones.map(normalizeZone);
          setDraftZones(restored);
          setLocalSavedZones(restored);
          setLineDraft(stored.line ?? null);
          setSavedLine(stored.line ?? null);
          setNotice('Restored this video’s locally saved zone configuration.');
        } else {
          setLocalSavedZones(null);
        }
      } catch {
        setError('Could not read this video’s saved browser configuration.');
      }
    }
    const compatible = reference && reference.width === nextFrame.width && reference.height === nextFrame.height;
    const nextLine = compatible ? calibrationLine(calibration) : null;
    setLineDraft(nextLine);
    setSavedLine(nextLine);
  };

  const pickPoint = (event) => {
    const svg = svgRef.current;
    if (!svg || !frame) return null;
    const matrix = svg.getScreenCTM();
    if (!matrix) return null;
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    const raw = point.matrixTransform(matrix.inverse());
    if (raw.x < 0 || raw.y < 0 || raw.x > frame.width || raw.y > frame.height) return null;
    return { x: Math.round((raw.x / frame.width) * 10000) / 10000, y: Math.round((raw.y / frame.height) * 10000) / 10000 };
  };

  const handleCanvasPointerDown = (event) => {
    if (!drawing || !svgRef.current) return;
    const point = pickPoint(event);
    if (!point) return;
    if (drawing === 'line') {
      if (!lineDraft?.start) setLineDraft({ start: point, end: null });
      else { setLineDraft((current) => ({ ...current, end: point })); setDrawing(null); }
      return;
    }
    setDrawing((current) => ({ ...current, points: [...current.points, point] }));
  };

  const handleDragStart = (event, zone, kind, index = -1) => {
    if (drawing || !frame) return;
    event.stopPropagation();
    const point = pickPoint(event);
    if (!point) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    dragRef.current = { zoneId: zone.id, kind, index, origin: point, polygon: zone.polygon.map((p) => ({ ...p })) };
  };

  const handleDrag = (event) => {
    const drag = dragRef.current;
    if (!drag) return;
    const point = pickPoint(event);
    if (!point) return;
    const dx = point.x - drag.origin.x;
    const dy = point.y - drag.origin.y;
    setDraftZones((current) => current.map((zone) => {
      if (zone.id !== drag.zoneId) return zone;
      const polygon = drag.polygon.map((vertex, index) => {
        if (drag.kind === 'point' && index === drag.index) return { x: point.x, y: point.y };
        if (drag.kind !== 'move') return vertex;
        return { x: clamp(vertex.x + dx), y: clamp(vertex.y + dy) };
      });
      return { ...zone, polygon };
    }));
  };

  const startPolygon = () => {
    const type = zoneType(zoneTypes, draftType);
    setError(''); setNotice(''); setEditId(null);
    setDraftName(type?.label ?? 'New zone');
    setDrawing({ kind: 'polygon', points: [] });
  };

  const finishPolygon = () => {
    if (!drawing || drawing === 'line' || drawing.points.length < 3) return;
    const name = draftName.trim();
    if (!name) { setError('Enter a name for this zone before finishing.'); return; }
    const key = `${draftType}_${Date.now().toString(36)}`.slice(0, 40);
    setDraftZones((current) => [...current, {
      id: `draft-${key}`, zone_key: key, name, zone_type: draftType,
      description: zoneType(zoneTypes, draftType)?.description ?? '',
      polygon: drawing.points, enabled: true, coordinate_system: 'normalized_raw',
    }]);
    setDrawing(null); setDraftName(''); setNotice('Zone added to the draft. Save changes to persist it.');
  };

  const startLine = () => {
    setDrawing('line'); setLineDraft({ start: null, end: null }); setError(''); setNotice('Click two points on the video to set the directional ENTRY/EXIT line.');
  };

  const saveChanges = async () => {
    if (saving) return;
    if (!item?.assignment?.id) {
      if (!localConfigKey) {
        setError('Wait for the video frame dimensions to load before saving this local configuration.');
        return;
      }
      try {
        window.localStorage.setItem(localConfigKey, JSON.stringify({
          zones: draftZones.map((zone) => ({ ...zone, id: String(zone.id).startsWith('draft-') ? zone.zone_key : zone.id })),
          line: lineDraft?.start && lineDraft?.end ? lineDraft : null,
          frame,
        }));
        const locallySaved = draftZones.map(normalizeZone);
        setDraftZones(locallySaved);
        setLocalSavedZones(locallySaved);
        setSavedLine(lineDraft?.start && lineDraft?.end ? lineDraft : null);
        setError('');
        setNotice('Configuration saved in this browser for this video. It has not been sent to a camera or backend.');
      } catch {
        setError('Could not save locally. Check that browser storage is available.');
      }
      return;
    }
    setSaving(true); setError(''); setNotice('');
    const assignmentId = item.assignment.id;
    const originals = new Map(zones.map((zone) => [zone.id, normalizeZone(zone)]));
    try {
      for (const original of zones) {
        if (!draftZones.some((zone) => zone.id === original.id)) {
          await deleteAssignmentZone(assignmentId, original.id);
          continue;
        }
        const next = draftZones.find((zone) => zone.id === original.id);
        const before = originals.get(original.id);
        const patch = {};
        for (const key of ['name', 'zone_type', 'enabled']) if (next[key] !== before[key]) patch[key] = next[key];
        if (!equal(next.polygon, before.polygon)) patch.polygon = next.polygon.map(({ x, y }) => [x, y]);
        if (Object.keys(patch).length) await updateAssignmentZone(assignmentId, original.id, patch);
      }
      for (const zone of draftZones.filter((entry) => String(entry.id).startsWith('draft-'))) {
        await createAssignmentZone(assignmentId, {
          zone_key: zone.zone_key, name: zone.name, description: zone.description,
          zone_type: zone.zone_type, polygon: zone.polygon.map(({ x, y }) => [x, y]),
          coordinate_system: 'normalized_raw', enabled: zone.enabled !== false,
        });
      }
      let calibrationUpdated = false;
      if (lineChanged && lineDraft?.start && lineDraft?.end && dimensionsMatch && calibration) {
        const updated = await saveAssignmentCalibration(assignmentId, {
          ...calibration,
          reference_frame: { width: frame.width, height: frame.height },
          coordinate_system: 'normalized_raw',
          directional_crossing: {
            ...calibration.directional_crossing,
            line_start: lineDraft.start, line_end: lineDraft.end,
            entry_direction: 'outside_to_inside', exit_direction: 'inside_to_outside',
          },
        });
        onCalibrationSaved?.(updated);
        setSavedLine(lineDraft);
        calibrationUpdated = true;
      }
      const refreshedZones = await reloadZones();
      if (Array.isArray(refreshedZones)) setDraftZones(refreshedZones.map(normalizeZone));
      setEditId(null); setDrawing(null);
      if (lineChanged && !calibrationUpdated) {
        setNotice('Zones saved. The virtual line remains a local draft because no matching, complete calibration exists. Match the calibration frame and save it before persisting this line.');
      } else {
        setNotice(calibrationUpdated ? 'Zones and directional line saved.' : 'Zone changes saved.');
      }
    } catch (exception) {
      setError(errorMessage(exception));
      await reloadZones();
    } finally {
      setSaving(false);
    }
  };

  const cancelChanges = () => {
    setDraftZones(zones.map(normalizeZone));
    setLocalSavedZones(null);
    setDrawing(null); setEditId(null); setError(''); setNotice('Changes discarded.');
    const compatible = frame && reference?.width === frame.width && reference?.height === frame.height;
    const saved = compatible ? calibrationLine(calibration) : null;
    setLineDraft(saved); setSavedLine(saved);
  };

  const line = lineDraft?.start && lineDraft?.end ? lineDraft : null;
  const step = speed;
  const videoLabel = useMemo(() => file?.name || '', [file]);

  return (
    <div className="space-y-4" onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); onFile?.(event.dataTransfer.files?.[0] ?? null); }}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-[#0F1B3D]">Video Test Mode</p>
          <p className="text-xs text-[#55607A]">Local playback only. No camera worker or monitoring is started.</p>
        </div>
        <Pill tone="info" dot>VIDEO TEST MODE</Pill>
      </div>

      {!file ? (
        <label className="flex min-h-44 cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-[#C7D0E2] bg-[#F7F8FC] px-5 text-center hover:border-[#34479B] hover:bg-[#EEF1FA]">
          <Upload size={25} className="text-[#34479B]" aria-hidden />
          <span className="font-semibold text-[#0F1B3D]">Upload a CCTV video to start testing</span>
          <span className="text-xs text-[#55607A]">Drop a video here or choose a file (MP4, WebM, MOV; browser support varies).</span>
          <input className="sr-only" type="file" accept="video/mp4,video/webm,video/quicktime,.mp4,.webm,.mov" onChange={(event) => onFile(event.target.files?.[0] ?? null)} />
        </label>
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[#E3E7F0] bg-[#F7F8FC] px-3 py-2">
            <span className="flex min-w-0 items-center gap-2 text-sm text-[#0F1B3D]"><Video size={16} className="shrink-0 text-[#34479B]" aria-hidden /><span className="truncate" title={videoLabel}>{videoLabel}</span></span>
            <label className={btnGhost}><Upload size={13} aria-hidden /> Replace video<input className="sr-only" type="file" accept="video/mp4,video/webm,video/quicktime,.mp4,.webm,.mov" onChange={(event) => onFile(event.target.files?.[0] ?? null)} /></label>
            <button type="button" className={btnGhost} onClick={() => onFile(null)}><X size={13} aria-hidden /> Remove video</button>
          </div>

          {calibrationMismatch && <div role="status" className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            This video is {frame.width} × {frame.height}; the saved calibration is {reference.width} × {reference.height}. Existing calibration and line overlays are not reused or rescaled for this video.
          </div>}

          <div ref={stageRef} className="relative aspect-video overflow-hidden rounded-lg bg-[#18202E]">
            <video ref={videoRef} src={objectUrl} className="absolute inset-0 h-full w-full object-contain" playsInline preload="metadata"
              onLoadedMetadata={handleMetadata} onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
              onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onDurationChange={(event) => setDuration(event.currentTarget.duration || 0)}>
              Your browser cannot play this video format.
            </video>
            {frame && <svg ref={svgRef} viewBox={`0 0 ${frame.width} ${frame.height}`} preserveAspectRatio="xMidYMid meet"
              className={`absolute inset-0 h-full w-full touch-none ${drawing ? 'cursor-crosshair' : ''}`}
              onPointerDown={handleCanvasPointerDown} onPointerMove={handleDrag} onPointerUp={() => { dragRef.current = null; }}
              aria-label="Video zone drawing canvas">
              {draftZones.map((zone) => {
                const points = polygonPoints(zone.polygon);
                if (points.length < 3) return null;
                const color = zoneColor(zone.zone_type);
                const selected = editId === zone.id;
                return <g key={zone.id} opacity={zone.enabled === false ? 0.3 : 1}>
                  <polygon points={points.map(({ x, y }) => `${x * frame.width},${y * frame.height}`).join(' ')}
                    fill={`${color}22`} stroke={color} strokeWidth={selected ? 3 : 2} vectorEffect="non-scaling-stroke"
                    onPointerDown={selected ? (event) => handleDragStart(event, zone, 'move') : undefined} />
                  {selected && points.map((point, index) => <circle key={index} cx={point.x * frame.width} cy={point.y * frame.height} r="7"
                    fill="white" stroke={color} strokeWidth="3" vectorEffect="non-scaling-stroke"
                    onPointerDown={(event) => handleDragStart(event, zone, 'point', index)} />)}
                  <text x={Math.min(...points.map((p) => p.x)) * frame.width} y={Math.min(...points.map((p) => p.y)) * frame.height - 8}
                    fill={color} stroke="#18202E" strokeWidth="3" paintOrder="stroke" fontSize={Math.max(15, frame.width * 0.014)} fontWeight="700">{zone.name}</text>
                </g>;
              })}
              {drawing?.kind === 'polygon' && drawing.points.length > 0 && <g>
                <polyline points={drawing.points.map((p) => `${p.x * frame.width},${p.y * frame.height}`).join(' ')} fill="none" stroke={zoneColor(draftType)} strokeWidth="3" vectorEffect="non-scaling-stroke" />
                {drawing.points.map((p, index) => <circle key={index} cx={p.x * frame.width} cy={p.y * frame.height} r="5" fill="white" stroke={zoneColor(draftType)} strokeWidth="2" vectorEffect="non-scaling-stroke" />)}
              </g>}
              {lineDraft?.start && <g>
                {lineDraft.end && <line x1={lineDraft.start.x * frame.width} y1={lineDraft.start.y * frame.height} x2={lineDraft.end.x * frame.width} y2={lineDraft.end.y * frame.height}
                  stroke="#FFFFFF" strokeWidth="3" strokeDasharray="9 6" vectorEffect="non-scaling-stroke" />}
                {[lineDraft.start, lineDraft.end].filter(Boolean).map((p, index) => <circle key={index} cx={p.x * frame.width} cy={p.y * frame.height} r="6" fill="#34479B" stroke="white" strokeWidth="2" vectorEffect="non-scaling-stroke" />)}
                {lineDraft.end && <text x={lineDraft.end.x * frame.width + 12} y={lineDraft.end.y * frame.height - 10} fill="white" stroke="#18202E" strokeWidth="3" paintOrder="stroke" fontSize={Math.max(14, frame.width * 0.012)} fontWeight="700">ENTRY / EXIT line</text>}
              </g>}
            </svg>}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className={btnGhost} onClick={() => { const v = videoRef.current; if (!v) return; if (v.paused) v.play(); else v.pause(); }}>
              {playing ? <Pause size={13} aria-hidden /> : <Play size={13} aria-hidden />}{playing ? 'Pause' : 'Play'}
            </button>
            <span className="min-w-[92px] text-xs tabular-nums text-[#55607A]">{formatTime(currentTime)} / {formatTime(duration)}</span>
            <input aria-label="Video position" type="range" min="0" max={duration || 0} step="0.05" value={Math.min(currentTime, duration || 0)}
              onChange={(event) => { if (videoRef.current) videoRef.current.currentTime = Number(event.target.value); }} className="min-w-[120px] flex-1 accent-[#34479B]" />
            <select aria-label="Playback speed" value={speed} onChange={(event) => { const value = Number(event.target.value); setSpeed(value); if (videoRef.current) videoRef.current.playbackRate = value; }}
              className="rounded-md border border-[#D0D7E6] bg-white px-2 py-1.5 text-xs text-[#34479B]">
              {[0.5, 1, 1.5, 2].map((value) => <option key={value} value={value}>{value}×</option>)}
            </select>
            <button type="button" className={btnGhost} title="Replay video" onClick={() => { if (videoRef.current) { videoRef.current.currentTime = 0; videoRef.current.play(); } }}><RotateCcw size={13} aria-hidden /> Replay</button>
            <button type="button" className={btnGhost} title="Fullscreen" onClick={() => stageRef.current?.requestFullscreen?.()}><Maximize size={13} aria-hidden /> Fullscreen</button>
          </div>

          <div className="rounded-lg border border-[#E3E7F0] bg-white p-3">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div><p className="text-sm font-semibold text-[#0F1B3D]">Draw zones on this video</p><p className="text-xs text-[#55607A]">Coordinates use the {frame?.width ?? '—'} × {frame?.height ?? '—'} raw frame. The aspect ratio is preserved.</p></div>
              <div className="flex flex-wrap gap-2">
                <select aria-label="Zone type" value={draftType} onChange={(event) => setDraftType(event.target.value)} className="rounded-md border border-[#D0D7E6] bg-white px-2 py-1.5 text-xs text-[#34479B]">
                  {zoneTypes.map((type) => <option key={type.key} value={type.key}>{type.label}</option>)}
                </select>
                <button type="button" className={btnGhost} disabled={!frame} onClick={startPolygon}><Plus size={13} aria-hidden /> Draw polygon</button>
                <button type="button" className={btnGhost} disabled={!frame} onClick={startLine}><CircleHelp size={13} aria-hidden /> Draw ENTRY/EXIT line</button>
              </div>
            </div>

            {drawing?.kind === 'polygon' && <div className="mb-3 flex flex-wrap items-center gap-2 rounded-md bg-[#F4F6FB] p-2">
              <label className="text-xs text-[#55607A]">Zone name <input value={draftName} onChange={(event) => setDraftName(event.target.value)} className="ml-1 rounded border border-[#D0D7E6] px-2 py-1 text-[#1C2B4D]" /></label>
              <span className="text-xs text-[#55607A]">Click at least 3 points on the video.</span>
              <button type="button" className={btnGhost} onClick={() => setDrawing((current) => ({ ...current, points: current.points.slice(0, -1) }))}><Undo2 size={13} aria-hidden /> Undo point</button>
              <button type="button" className={btnPrimary} disabled={drawing.points.length < 3} onClick={finishPolygon}><Check size={13} aria-hidden /> Finish polygon</button>
              <button type="button" className={btnGhost} onClick={() => setDrawing(null)}>Cancel</button>
            </div>}
            {drawing === 'line' && <div className="mb-3 flex flex-wrap items-center gap-2 rounded-md bg-[#EEF1FA] p-2 text-xs text-[#34479B]">
              Click two points for the directional line. This dashed line is separate from the gate_crossing polygon.
              <button type="button" className={btnGhost} onClick={() => { setDrawing(null); setLineDraft(savedLine); }}>Cancel line</button>
            </div>}
            {editedZone && <div className="mb-3 flex flex-wrap items-center gap-2 rounded-md bg-[#F4F6FB] p-2">
              <label className="text-xs text-[#55607A]">Name <input value={editedZone.name} onChange={(event) => setDraftZones((list) => list.map((zone) => zone.id === editId ? { ...zone, name: event.target.value } : zone))} className="ml-1 rounded border border-[#D0D7E6] px-2 py-1 text-[#1C2B4D]" /></label>
              <span className="text-xs text-[#55607A]">Drag a point to reshape; drag inside the outline to move it.</span>
              <button type="button" className={btnGhost} onClick={() => setEditId(null)}>Done editing</button>
            </div>}

            <ul className="divide-y divide-[#E3E7F0]">
              {draftZones.map((zone) => <li key={zone.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <span className="flex min-w-0 items-center gap-2 text-sm text-[#0F1B3D]"><span className="h-2.5 w-2.5 rounded-full" style={{ background: zoneColor(zone.zone_type) }} aria-hidden />{zone.name}<span className="text-xs text-[#69758F]">{zone.zone_type}</span></span>
                <span className="flex items-center gap-1">
                  <button type="button" className={btnGhost} aria-label={`${zone.enabled === false ? 'Enable' : 'Hide'} ${zone.name}`} onClick={() => setDraftZones((list) => list.map((entry) => entry.id === zone.id ? { ...entry, enabled: entry.enabled === false } : entry))}>{zone.enabled === false ? <Eye size={13} /> : <EyeOff size={13} />}</button>
                  <button type="button" className={btnGhost} aria-label={`Edit ${zone.name} polygon`} onClick={() => { setEditId(zone.id); setDraftName(zone.name); setDraftType(zone.zone_type); setDrawing(null); }}><Pencil size={13} /></button>
                  <button type="button" className={btnGhost} aria-label={`Delete ${zone.name}`} onClick={() => { setDraftZones((list) => list.filter((entry) => entry.id !== zone.id)); if (editId === zone.id) setEditId(null); }}><Trash2 size={13} /></button>
                </span>
              </li>)}
              {!draftZones.length && <li className="py-3 text-sm text-[#69758F]">No zones configured for this assignment.</li>}
            </ul>

            {line && <p className="mt-2 text-xs text-[#55607A]">Directional ENTRY/EXIT line is shown dashed. It is a calibration reference, not the gate_crossing polygon.</p>}
            {error && <div className="mt-3"><ErrorNote>{error}</ErrorNote></div>}
            {notice && <p role="status" className="mt-3 rounded-lg bg-[#EEF1FA] p-2 text-xs text-[#34479B]">{notice}</p>}
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-[#E3E7F0] pt-3">
              <p className="text-xs text-[#55607A]">Video playback does not run gate, crossing, mesh, or alert monitoring.</p>
              <span className="flex gap-2">
                <button type="button" className={btnGhost} disabled={!dirty || saving} onClick={cancelChanges}>Cancel</button>
                <button type="button" className={btnPrimary} disabled={!dirty || saving} onClick={saveChanges}><Save size={13} aria-hidden /> {saving ? 'Saving…' : 'Save changes'}</button>
              </span>
            </div>
            {lineChanged && !dimensionsMatch && <p className="mt-2 text-xs text-amber-800">The line is a local draft. To persist it, save a complete calibration with matching video dimensions in the Calibration tab.</p>}
          </div>
        </>
      )}
    </div>
  );
}

/** Browser-local video test UI; files never enter the camera source registry or worker API. */
export default function VideoTestPanel({ item, zones, zoneTypes, reloadZones, onCalibrationSaved, file, onFile, onFrameDimensions }) {
  const [dragging, setDragging] = useState(false);
  const objectUrl = useMemo(() => file ? URL.createObjectURL(file) : null, [file]);
  useEffect(() => () => { if (objectUrl) URL.revokeObjectURL(objectUrl); }, [objectUrl]);
  const acceptFile = (candidate) => {
    if (!candidate) return;
    if (!candidate.type.startsWith('video/')) return;
    onFile(candidate);
  };

  return (
    <div onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)}
      onDrop={(event) => { event.preventDefault(); setDragging(false); acceptFile(event.dataTransfer.files?.[0]); }}
      className={dragging ? 'rounded-lg ring-2 ring-[#34479B]' : ''}>
      {file && objectUrl ? (
        <ZoneEditor key={`${item?.assignment?.id}:${file.name}:${file.size}`} item={item} zones={zones} zoneTypes={zoneTypes}
          reloadZones={reloadZones} onCalibrationSaved={onCalibrationSaved} file={file} objectUrl={objectUrl} calibration={item?.assignment?.calibration}
          onFile={onFile} onFrameDimensions={onFrameDimensions} />
      ) : (
        <div className="flex min-h-44 flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-[#C7D0E2] bg-[#F7F8FC] px-5 text-center">
          <Upload size={25} className="text-[#34479B]" aria-hidden />
          <span className="font-semibold text-[#0F1B3D]">Upload a CCTV video to start testing</span>
          <span className="text-xs text-[#55607A]">Drop MP4, WebM or MOV here, or choose a local file.</span>
          <label className={btnPrimary}>
            <Upload size={13} aria-hidden /> Choose video
            <input className="sr-only" type="file" accept="video/mp4,video/webm,video/quicktime,.mp4,.webm,.mov" onChange={(event) => acceptFile(event.target.files?.[0])} />
          </label>
        </div>
      )}
    </div>
  );
}
