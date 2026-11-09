const input = 'mt-1 min-h-9 w-full rounded-md border border-[#D0D7E6] bg-white px-2.5 text-sm text-[#1C2B4D] outline-none focus:border-[#34479B] focus:ring-2 focus:ring-[#34479B]/20 disabled:bg-[#F4F6FB] disabled:text-[#69758F]';
const label = 'block text-xs text-[#55607A]';

function NumberField({ form, setField, name, text, step = 'any', min, max, disabled }) {
  return (
    <label className={label}>{text}
      <input className={input} type="number" inputMode="decimal" step={step} min={min} max={max} disabled={disabled}
        value={form[name]} onChange={(event) => setField(name, event.target.value)} />
    </label>
  );
}

function SelectField({ form, setField, name, text, options, disabled, placeholder = true }) {
  return (
    <label className={label}>{text}
      <select className={input} value={form[name]} disabled={disabled} onChange={(event) => setField(name, event.target.value)}>
        {placeholder && <option value="">Select…</option>}
        {options.map(([value, caption]) => <option key={value} value={value}>{caption}</option>)}
      </select>
    </label>
  );
}

function Fieldset({ title, hint, children }) {
  return (
    <fieldset className="border-t border-[#E3E7F0] pt-3">
      <legend className="pr-2 text-sm font-semibold text-[#0F1B3D]">{title}</legend>
      {hint && <p className="text-xs leading-5 text-[#55607A]">{hint}</p>}
      <div className="mt-2 grid gap-3 sm:grid-cols-2">{children}</div>
    </fieldset>
  );
}

/**
 * The editable calibration values for one source. The parent owns the form and saves it with Save Changes, together
 * with that source's zones; the frame size always comes from the source and is never rescaled.
 */
export default function CalibrationView({ form, setField, disabled = false }) {
  const shared = { form, setField, disabled };
  return (
    <div className="space-y-3">
      <Fieldset title="Gate state" hint="The gate's closed and open positions are fixed at 0 and 1: gate progress is measured between the endpoints from Measure endpoints.">
        <NumberField {...shared} name="closed_tolerance" text="Closed tolerance" min="0" max="1" />
        <NumberField {...shared} name="open_tolerance" text="Open tolerance" min="0" max="1" />
        <NumberField {...shared} name="confidence_threshold" text="Confidence threshold" min="0" max="1" />
        <NumberField {...shared} name="hysteresis_fraction" text="Hysteresis (below 0.5)" min="0" max="0.5" />
        <NumberField {...shared} name="closed_seconds" text="Confirm CLOSED (s)" min="0" />
        <NumberField {...shared} name="opening_seconds" text="Confirm OPENING (s)" min="0" />
        <NumberField {...shared} name="open_seconds" text="Confirm OPEN (s)" min="0" />
        <NumberField {...shared} name="partially_open_seconds" text="Confirm PARTIALLY OPEN (s)" min="0" />
        <NumberField {...shared} name="closing_seconds" text="Confirm CLOSING (s)" min="0" />
      </Fieldset>
      <Fieldset title="ENTRY/EXIT reference line (optional)" hint="Three-Zone crossings use the approach and interior polygons. This line can be saved as an optional calibration reference.">
        <SelectField {...shared} name="outside_side" text="Outside is on the line's" options={[['left', 'Left side'], ['right', 'Right side']]} />
        <SelectField {...shared} name="inside_side" text="Inside is on the line's" options={[['left', 'Left side'], ['right', 'Right side']]} />
        <NumberField {...shared} name="dead_band_fraction" text="Dead-band fraction" min="0" max="1" />
        <NumberField {...shared} name="minimum_crossing_displacement" text="Min. crossing displacement" min="0" max="2" />
      </Fieldset>
    </div>
  );
}
