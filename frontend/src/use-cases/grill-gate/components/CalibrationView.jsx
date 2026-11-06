import { useState } from 'react';
import { Crosshair, RotateCcw, Save } from 'lucide-react';
import { describeError } from '../../../utils/errors.js';
import { saveAssignmentCalibration } from '../api/grillGate.js';
import { calibrationStatus, calibrationToForm, formLine, formToCalibration } from '../grillGateModel.js';
import CameraStage, { ZoneOverlay } from './CameraStage.jsx';
import { btnGhost, btnPrimary, Card, ErrorNote, Pill } from './ui.jsx';

const input = 'mt-1 min-h-9 w-full rounded-md border border-[#D0D7E6] bg-white px-2.5 text-sm text-[#1C2B4D] outline-none focus:border-[#34479B] focus:ring-2 focus:ring-[#34479B]/20';
const label = 'block text-xs text-[#55607A]';

function NumberField({ form, setField, name, text, step = 'any', min, max }) {
  return (
    <label className={label}>{text}
      <input className={input} type="number" inputMode="decimal" step={step} min={min} max={max}
        value={form[name]} onChange={(event) => setField(name, event.target.value)} />
    </label>
  );
}

function SelectField({ form, setField, name, text, options }) {
  return (
    <label className={label}>{text}
      <select className={input} value={form[name]} onChange={(event) => setField(name, event.target.value)}>
        <option value="">Select…</option>
        {options.map(([value, caption]) => <option key={value} value={value}>{caption}</option>)}
      </select>
    </label>
  );
}

function Fieldset({ title, hint, children }) {
  return (
    <fieldset className="border-t border-[#E3E7F0] pt-4 first:border-t-0 first:pt-0">
      <legend className="text-sm font-semibold text-[#0F1B3D]">{title}</legend>
      {hint && <p className="mt-1 text-xs leading-5 text-[#55607A]">{hint}</p>}
      <div className="mt-3 grid gap-3 sm:grid-cols-2">{children}</div>
    </fieldset>
  );
}

export default function CalibrationView({ item, worker, zones, onSaved }) {
  const assignment = item.assignment;
  const saved = assignment.calibration;
  const [form, setForm] = useState(() => calibrationToForm(saved, worker));
  const [pickTarget, setPickTarget] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const status = calibrationStatus(saved, { worker, zones });
  const line = formLine(form);
  const frameWidth = Number(form.width) || worker?.width;
  const frameHeight = Number(form.height) || worker?.height;

  const setField = (name, value) => setForm((current) => {
    const next = { ...current, [name]: value };
    // Sides must be opposite; mirror the choice visibly instead of letting the backend reject it.
    if (name === 'outside_side' && value) next.inside_side = value === 'left' ? 'right' : 'left';
    if (name === 'inside_side' && value) next.outside_side = value === 'left' ? 'right' : 'left';
    return next;
  });

  const pick = ({ x, y }) => {
    const prefix = pickTarget === 'start' ? 'line_start' : 'line_end';
    setForm((current) => ({ ...current, [`${prefix}_x`]: String(x), [`${prefix}_y`]: String(y) }));
    setPickTarget(pickTarget === 'start' ? 'end' : null);
  };

  const save = async (event) => {
    event.preventDefault();
    if (saved && !window.confirm(`Replace the calibration saved ${new Date(saved.calibrated_at).toLocaleString()}? The previous values are overwritten.`)) return;
    setSaving(true); setError(''); setNotice('');
    try {
      const updated = await saveAssignmentCalibration(assignment.id, formToCalibration(form));
      onSaved(updated);
      setForm(calibrationToForm(updated.calibration, worker));
      setNotice('Calibration saved and validated by the backend.');
    } catch (exception) {
      setError(describeError(exception).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(380px,520px)]">
      <Card title="Calibration preview" aside={pickTarget ? <Pill tone="info">Click to set line {pickTarget}</Pill> : null} className="self-start">
        <CameraStage aspect={frameWidth && frameHeight ? frameWidth / frameHeight : 16 / 9} onPick={pickTarget ? pick : null}
          label="Calibration preview: configured zones and the directional virtual line">
          <ZoneOverlay zones={zones} line={line} />
        </CameraStage>
        <p className="mt-3 text-xs leading-5 text-[#55607A]">
          Shows configured zones and the virtual line in normalized raw-frame coordinates. No camera image is available from the backend,
          so use the zone outlines as the reference when picking line points.
        </p>
      </Card>

      <Card title="Calibration" aside={<Pill tone={status.tone}>{status.label}</Pill>}>
        {saved && <p className="mb-2 text-xs text-[#55607A]">Saved {new Date(saved.calibrated_at).toLocaleString()} · reference {saved.reference_frame?.width}×{saved.reference_frame?.height} · {saved.coordinate_system}</p>}
        {status.issues.length > 0 && (
          <ul className="mb-4 space-y-1 rounded-lg bg-amber-500/10 p-3 text-xs leading-5 text-amber-200 ring-1 ring-amber-400/30">
            {status.issues.map((issue) => <li key={issue}>• {issue}</li>)}
          </ul>
        )}
        <form onSubmit={save} className="space-y-5">
          <Fieldset title="Reference frame" hint={worker?.width ? `The connected worker currently reports ${worker.width}×${worker.height}.` : 'Connect the camera to read its actual frame size.'}>
            <NumberField form={form} setField={setField} name="width" text="Width (px)" step="1" min="1" />
            <NumberField form={form} setField={setField} name="height" text="Height (px)" step="1" min="1" />
          </Fieldset>

          <Fieldset title="Sliding gate reference" hint="Normalized horizontal positions (0–1) of the gate leaf, measured inside the gate_leaf_roi zone.">
            <NumberField form={form} setField={setField} name="closed_reference_position" text="Closed position" min="0" max="1" />
            <NumberField form={form} setField={setField} name="open_reference_position" text="Open position" min="0" max="1" />
            <SelectField form={form} setField={setField} name="horizontal_movement_direction" text="Opening direction"
              options={[['left_to_right', 'Left → right'], ['right_to_left', 'Right → left']]} />
            <NumberField form={form} setField={setField} name="confidence_threshold" text="Confidence threshold" min="0" max="1" />
            <NumberField form={form} setField={setField} name="closed_tolerance" text="Closed tolerance" min="0" max="1" />
            <NumberField form={form} setField={setField} name="open_tolerance" text="Open tolerance" min="0" max="1" />
            <NumberField form={form} setField={setField} name="hysteresis_fraction" text="Hysteresis fraction (< 0.5)" min="0" max="0.5" />
            <span />
            <NumberField form={form} setField={setField} name="closed_seconds" text="Confirm CLOSED (s)" min="0" />
            <NumberField form={form} setField={setField} name="opening_seconds" text="Confirm OPENING (s)" min="0" />
            <NumberField form={form} setField={setField} name="open_seconds" text="Confirm OPEN (s)" min="0" />
            <NumberField form={form} setField={setField} name="partially_open_seconds" text="Confirm PARTIALLY_OPEN (s)" min="0" />
            <NumberField form={form} setField={setField} name="closing_seconds" text="Confirm CLOSING (s)" min="0" />
          </Fieldset>

          <Fieldset title="Directional crossing line" hint="An oriented virtual line, separate from the gate_crossing corridor polygon. ENTRY is outside → inside; EXIT is inside → outside.">
            <div className="flex flex-wrap gap-2 sm:col-span-2">
              <button type="button" className={btnGhost} onClick={() => setPickTarget('start')}><Crosshair size={13} aria-hidden /> Pick start on stage</button>
              <button type="button" className={btnGhost} onClick={() => setPickTarget('end')}><Crosshair size={13} aria-hidden /> Pick end on stage</button>
              {pickTarget && <button type="button" className={btnGhost} onClick={() => setPickTarget(null)}>Cancel pick</button>}
            </div>
            <NumberField form={form} setField={setField} name="line_start_x" text="Start x" min="0" max="1" />
            <NumberField form={form} setField={setField} name="line_start_y" text="Start y" min="0" max="1" />
            <NumberField form={form} setField={setField} name="line_end_x" text="End x" min="0" max="1" />
            <NumberField form={form} setField={setField} name="line_end_y" text="End y" min="0" max="1" />
            <SelectField form={form} setField={setField} name="outside_side" text="Outside is on the line's" options={[['left', 'Left side'], ['right', 'Right side']]} />
            <SelectField form={form} setField={setField} name="inside_side" text="Inside is on the line's" options={[['left', 'Left side'], ['right', 'Right side']]} />
            <NumberField form={form} setField={setField} name="dead_band_fraction" text="Dead-band fraction" min="0" max="1" />
            <NumberField form={form} setField={setField} name="minimum_crossing_displacement" text="Min. crossing displacement" min="0" max="2" />
          </Fieldset>

          <Fieldset title="Monitoring thresholds" hint="No defaults: leave blank to keep a threshold unset. Approved status requires all five values.">
            <SelectField form={form} setField={setField} name="thresholds_status" text="Thresholds status"
              options={[['unset', 'Unset'], ['provisional', 'Provisional'], ['approved', 'Approved']]} />
            <NumberField form={form} setField={setField} name="maximum_continuous_open_seconds" text="Max continuous open (s)" min="0" />
            <NumberField form={form} setField={setField} name="crossing_inactivity_seconds" text="Crossing inactivity (s)" min="0" />
            <NumberField form={form} setField={setField} name="minimum_mesh_gathering_count" text="Mesh gathering count" step="1" min="1" />
            <NumberField form={form} setField={setField} name="mesh_gathering_seconds" text="Mesh gathering (s)" min="0" />
            <NumberField form={form} setField={setField} name="suspicious_activity_seconds" text="Suspicious activity (s)" min="0" />
          </Fieldset>

          <ErrorNote>{error}</ErrorNote>
          {notice && <p className="rounded-lg bg-emerald-500/10 p-3 text-sm text-emerald-200 ring-1 ring-emerald-400/30" role="status">{notice}</p>}
          <div className="flex flex-wrap justify-end gap-2">
            <button type="button" className={btnGhost} disabled={saving} onClick={() => { setForm(calibrationToForm(saved, worker)); setError(''); setNotice(''); }}>
              <RotateCcw size={13} aria-hidden /> Revert to saved
            </button>
            <button type="submit" className={btnPrimary} disabled={saving}><Save size={13} aria-hidden /> {saving ? 'Saving…' : 'Save calibration'}</button>
          </div>
        </form>
      </Card>
    </div>
  );
}
