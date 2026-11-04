import { useEffect, useState } from 'react';
import { api, coveringLabel, fmApiUrl, qs } from '../api/index.js';
import { PageState } from '../components/ui.jsx';
import usePolling from '../hooks/usePolling.js';

const STATUSES = ['OPEN', 'UNDER_REVIEW', 'CONFIRMED', 'FALSE_POSITIVE', 'CLOSED'];

// Field definitions: label, hint, type and the same limits the server enforces (the server remains the authority).
const FIELDS = [
  ['visibility_threshold', 'Concealment threshold', '0 to 1. A frame counts as "concealed" when its concealment score reaches this. Higher = fewer alerts, more missed.', 'number', { min: 0, max: 1, step: 0.05 }],
  ['frames_to_confirm', 'Frames to confirm', 'How many concealed frames (out of the window below) are needed before an event is raised.', 'number', { min: 1, max: 60, step: 1 }],
  ['confirm_window', 'Confirmation window (frames)', 'The last N evaluated frames considered. Must be at least "frames to confirm".', 'number', { min: 1, max: 120, step: 1 }],
  ['min_head_height_px', 'Minimum head height (px)', 'Smaller heads are too small to judge: wait for a better frame, never alert.', 'number', { min: 1, max: 1000, step: 1 }],
  ['min_sharpness', 'Minimum sharpness', 'Blurrier heads are skipped (variance of Laplacian).', 'number', { min: 0, max: 5000, step: 5 }],
  ['min_brightness', 'Minimum brightness', 'Darker heads are skipped (0-255).', 'number', { min: 0, max: 255, step: 1 }],
  ['max_brightness', 'Maximum brightness', 'Over-exposed heads are skipped (0-255). Must be above the minimum.', 'number', { min: 0, max: 255, step: 1 }],
  ['max_yaw_degrees', 'Maximum head turn (degrees)', 'A head turned away more than this is not judged: wait, never alert.', 'number', { min: 1, max: 180, step: 1 }],
  ['clip_pre_seconds', 'Clip: seconds before', 'Recorded before the event.', 'number', { min: 0, max: 60, step: 1 }],
  ['clip_post_seconds', 'Clip: seconds after', 'Recorded after the event.', 'number', { min: 0, max: 60, step: 1 }],
  ['cooldown_seconds', 'Duplicate cooldown (seconds)', 'A track that breaks and restarts in the same spot within this time does not create a second event.', 'number', { min: 0, max: 300, step: 1 }],
];

function clientErrors(v) {
  const errors = {};
  FIELDS.forEach(([key, label, , , lim]) => {
    const n = Number(v[key]);
    if (v[key] === '' || Number.isNaN(n)) errors[key] = 'Enter a number.';
    else if (n < lim.min || n > lim.max) errors[key] = `Must be between ${lim.min} and ${lim.max}.`;
  });
  if (!errors.frames_to_confirm && !errors.confirm_window && Number(v.frames_to_confirm) > Number(v.confirm_window)) errors.frames_to_confirm = 'Cannot be larger than the confirmation window.';
  if (!errors.min_brightness && !errors.max_brightness && Number(v.min_brightness) >= Number(v.max_brightness)) errors.min_brightness = 'Must be below the maximum brightness.';
  return errors;
}

function Reports() {
  const cams = usePolling(() => api.get('/cameras'), 15000);
  const [f, setF] = useState({ from: '', to: '', camera_id: '', status: '', covering_type: '' });
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));
  const iso = (local) => (local ? new Date(local).toISOString() : '');
  const url = fmApiUrl(`/reports/events.csv${qs({ date_from: iso(f.from), date_to: iso(f.to), camera_id: f.camera_id, status: f.status, covering_type: f.covering_type })}`);
  return (
    <div className="bx-card bx-mb-16">
      <div className="bx-card-title">Events report (CSV)</div>
      <div className="bx-field-row" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))' }}>
        <label className="bx-field">From <input className="bx-input" type="datetime-local" value={f.from} onChange={set('from')} /></label>
        <label className="bx-field">To <input className="bx-input" type="datetime-local" value={f.to} onChange={set('to')} /></label>
        <label className="bx-field">Camera
          <select className="bx-input" value={f.camera_id} onChange={set('camera_id')}>
            <option value="">All cameras</option>{(cams.data || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <label className="bx-field">Status
          <select className="bx-input" value={f.status} onChange={set('status')}>
            <option value="">All</option>{STATUSES.map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
          </select>
        </label>
        <label className="bx-field">Covering
          <select className="bx-input" value={f.covering_type} onChange={set('covering_type')}>
            <option value="">Any</option>
            {['lower_face_covering', 'full_face_covering', 'head_covering'].map((c) => <option key={c} value={c}>{coveringLabel(c)}</option>)}
          </select>
        </label>
      </div>
      <a className="bx-btn bx-btn-primary" href={url} download="face_mask_events.csv">Download CSV</a>
      <div className="bx-hint" style={{ marginTop: 10 }}>The report contains times, cameras, scores and review notes. It contains no identity information, because none is ever collected.</div>
    </div>
  );
}

function Settings() {
  const server = usePolling(() => api.get('/settings'), 0);
  const [values, setValues] = useState(null);
  const [analyzer, setAnalyzer] = useState('heuristic');
  const [policy, setPolicy] = useState('concealed_if_frontal_body_and_no_skin');
  const [serverError, setServerError] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  const load = (s) => { setValues(Object.fromEntries(FIELDS.map(([k]) => [k, String(s[k])]))); setAnalyzer(s.analyzer); setPolicy(s.head_down_policy); };
  useEffect(() => { if (server.data) load(server.data); }, [server.data]);

  const errors = values ? clientErrors(values) : {};
  const invalid = Object.keys(errors).length > 0;

  const save = async () => {
    setBusy(true); setServerError(''); setNote('');
    try {
      const body = Object.fromEntries(FIELDS.map(([k]) => [k, Number(values[k])]));
      load(await api.put('/settings', { ...body, analyzer, head_down_policy: policy }));
      setNote('Saved. New values apply to cameras started from now on - stop and start a running camera to use them.');
    } catch (e) { setServerError(e.message); } finally { setBusy(false); }
  };
  const reset = async () => {
    if (!window.confirm('Reset every setting to the defaults from face_mask.yaml?')) return;
    setBusy(true); setServerError(''); setNote('');
    try { load(await api.post('/settings/reset')); setNote('Defaults restored.'); } catch (e) { setServerError(e.message); } finally { setBusy(false); }
  };

  return (
    <div className="bx-card">
      <div className="bx-card-title">Detection settings</div>
      <PageState loading={server.loading} error={server.error} data={server.data} onRetry={server.reload}>
        {values && (
          <>
            {serverError && <div className="bx-diag" role="alert">{serverError}</div>}
            {note && <div className="bx-hint" role="status">{note}</div>}
            <div className="bx-field-row" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))' }}>
              <label className="bx-field">Analyzer
                <select className="bx-input" value={analyzer} onChange={(e) => setAnalyzer(e.target.value)}>
                  <option value="heuristic">Heuristic (no training data needed)</option>
                  <option value="classifier">Trained classifier (falls back to heuristic if no model file)</option>
                </select>
                <span className="bx-hint">The heuristic cannot reliably catch skin-coloured masks, a cap hiding the face, or helmets with visors. A classifier trained on your footage can.</span>
              </label>
              <label className="bx-field">Head looking down, face not visible
                <select className="bx-input" value={policy} onChange={(e) => setPolicy(e.target.value)}>
                  <option value="concealed_if_frontal_body_and_no_skin">Concealed if the body faces the camera and no skin is visible</option>
                  <option value="unable">Never alert (unable to assess)</option>
                </select>
                <span className="bx-hint">A head turned away (body not facing the camera) is never an alert with either option.</span>
              </label>
              {FIELDS.map(([key, label, hint, type, lim]) => (
                <label key={key} className="bx-field">{label}
                  <input className="bx-input" type={type} {...lim} value={values[key]} aria-invalid={!!errors[key]}
                    onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))} />
                  {errors[key] ? <span style={{ color: 'var(--bx-red)', fontSize: 12 }}>{errors[key]}</span> : <span className="bx-hint">{hint}</span>}
                </label>
              ))}
            </div>
            <div className="bx-row bx-gap-8">
              <button type="button" className="bx-btn bx-btn-primary" disabled={invalid || busy} onClick={save}>{busy ? 'Saving…' : 'Save settings'}</button>
              <button type="button" className="bx-btn" disabled={busy} onClick={reset}>Reset to defaults</button>
            </div>
          </>
        )}
      </PageState>
    </div>
  );
}

export default function ReportsSettings() {
  return (
    <>
      <Reports />
      <Settings />
    </>
  );
}
