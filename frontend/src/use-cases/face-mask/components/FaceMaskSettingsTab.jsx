import { useEffect, useState } from 'react';
import { api } from '../api/index.js';
import usePolling from '../hooks/usePolling.js';
import { CHANNELS, COMMON_FIELDS, NUMERIC, SPECIFIC_FIELDS, settingsErrors } from './faceMaskSettingsModel.js';
import { PageState } from './ui.jsx';

function NumberField({ field, values, errors, onChange }) {
  const [key, label, hint, lim] = field;
  return (
    <label className="bx-field">{label}
      <input className="bx-input" type="number" {...lim} value={values[key]} aria-invalid={!!errors[key]}
        onChange={(e) => onChange(key, e.target.value)} />
      {errors[key] ? <span style={{ color: 'var(--bx-red)', fontSize: 12 }}>{errors[key]}</span> : <span className="bx-hint">{hint}</span>}
    </label>
  );
}

/** Settings > Face Mask: every Face Mask setting, stored and applied by the Face Mask service (YAML defaults + saved overrides). */
export default function FaceMaskSettingsTab() {
  const server = usePolling(() => api.get('/settings'), 0);
  const [values, setValues] = useState(null);
  const [serverError, setServerError] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  const load = (s) => setValues({
    ...Object.fromEntries(NUMERIC.map(([k]) => [k, String(s[k])])),
    analyzer: s.analyzer, head_down_policy: s.head_down_policy,
    ...Object.fromEntries(CHANNELS.map(([k]) => [k, Boolean(s[k])])),
  });
  useEffect(() => { if (server.data) load(server.data); }, [server.data]);

  const errors = values ? settingsErrors(values) : {};
  const invalid = Object.keys(errors).length > 0;
  const setValue = (key, value) => setValues((v) => ({ ...v, [key]: value }));

  const save = async () => {
    setBusy(true); setServerError(''); setNote('');
    try {
      const body = {
        ...Object.fromEntries(NUMERIC.map(([k]) => [k, Number(values[k])])),
        analyzer: values.analyzer, head_down_policy: values.head_down_policy,
        ...Object.fromEntries(CHANNELS.map(([k]) => [k, values[k]])),
      };
      load(await api.put('/settings', body));
      setNote('Saved. New values apply to cameras started from now on (stop and start a running camera). Person detection confidence needs a Face Mask service restart.');
    } catch (e) { setServerError(e.message); } finally { setBusy(false); }
  };
  const reset = async () => {
    if (!window.confirm('Reset every Face Mask setting to the defaults from config/use_cases/face_mask.yaml?')) return;
    setBusy(true); setServerError(''); setNote('');
    try { load(await api.post('/settings/reset')); setNote('Defaults restored.'); } catch (e) { setServerError(e.message); } finally { setBusy(false); }
  };

  return (
    <PageState loading={server.loading} error={server.error} data={server.data} onRetry={server.reload}>
      {values && (
        <>
          {serverError && <div className="bx-diag" role="alert">{serverError}</div>}
          {note && <div className="bx-hint" role="status">{note}</div>}

          <div className="bx-card bx-mb-16">
            <div className="bx-card-title">Common settings</div>
            <p className="bx-hint">These mean the same thing in every use case. Each service still keeps its own copy today, so changing them here only changes Face Mask.</p>
            <div className="bx-field-row" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))' }}>
              {COMMON_FIELDS.map((f) => <NumberField key={f[0]} field={f} values={values} errors={errors} onChange={setValue} />)}
            </div>
            <fieldset style={{ border: 0, padding: 0, margin: '8px 0 0' }}>
              <legend className="bx-hint">Alert channels</legend>
              <div className="bx-row bx-gap-12 bx-wrap">
                {CHANNELS.map(([k, label]) => (
                  <label key={k} className="bx-row bx-gap-8"><input type="checkbox" checked={values[k]} onChange={(e) => setValue(k, e.target.checked)} /> {label}</label>
                ))}
              </div>
            </fieldset>
          </div>

          <div className="bx-card bx-mb-16">
            <div className="bx-card-title">Face Mask detection</div>
            <div className="bx-field-row" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))' }}>
              <label className="bx-field">Analyzer
                <select className="bx-input" value={values.analyzer} onChange={(e) => setValue('analyzer', e.target.value)}>
                  <option value="heuristic">Heuristic (no training data needed)</option>
                  <option value="classifier">Trained classifier (falls back to heuristic if no model file)</option>
                </select>
                <span className="bx-hint">The heuristic cannot reliably catch skin-coloured masks, a cap hiding the face, or helmets with visors. A classifier trained on your footage can.</span>
              </label>
              <label className="bx-field">Head looking down, face not visible
                <select className="bx-input" value={values.head_down_policy} onChange={(e) => setValue('head_down_policy', e.target.value)}>
                  <option value="concealed_if_frontal_body_and_no_skin">Concealed if the body faces the camera and no skin is visible</option>
                  <option value="unable">Never alert (unable to assess)</option>
                </select>
                <span className="bx-hint">A head turned away (body not facing the camera) is never an alert with either option.</span>
              </label>
              {SPECIFIC_FIELDS.map((f) => <NumberField key={f[0]} field={f} values={values} errors={errors} onChange={setValue} />)}
            </div>
            <p className="bx-hint" role="note">
              <b>Unable to assess:</b> when a head is too small, blurry, too dark or too bright, or turned away, Face Mask waits for a better frame.
              If none comes it records "unable to assess" and never raises a concealment alert. These thresholds only decide when a frame is good enough to judge.
            </p>
          </div>

          <div className="bx-row bx-gap-8">
            <button type="button" className="bx-btn bx-btn-primary" disabled={invalid || busy} onClick={save}>{busy ? 'Saving…' : 'Save settings'}</button>
            <button type="button" className="bx-btn" disabled={busy} onClick={reset}>Reset to defaults</button>
          </div>
        </>
      )}
    </PageState>
  );
}
