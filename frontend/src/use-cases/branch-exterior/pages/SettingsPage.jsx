import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api/index.js';
import { SETTINGS_TABS, resolveSettingsTab } from '../settingsTabs.js';

const DAYS = [['mon', 'Monday'], ['tue', 'Tuesday'], ['wed', 'Wednesday'], ['thu', 'Thursday'], ['fri', 'Friday'], ['sat', 'Saturday'], ['sun', 'Sunday']];
const minutes = (value) => { const [hours, mins] = (value || '').split(':').map(Number); return (hours || 0) * 60 + (mins || 0); };
const durationLabel = (value) => `${Math.floor(value / 60)}h${value % 60 ? ` ${value % 60}m` : ''}`;
const INT = (v) => parseInt(v, 10);
const FLT = (v) => parseFloat(v);
// threshold key -> parser used when saving (same types as the original page)
const PARSE = {
  processing_fps: INT, loiter_seconds_business_hours: INT, loiter_seconds_after_hours: INT, gathering_min_people: INT,
  gathering_distance_m: FLT, gathering_persistence_seconds: INT, movement_tortuosity_threshold: FLT, movement_running_speed_mps: FLT,
  after_hours_grace_minutes: INT, after_hours_min_dwell_seconds: INT, weapon_confidence_threshold: FLT, fight_confidence_threshold: FLT,
  dedupe_cooldown_seconds: INT, evidence_cooldown_seconds: INT, evidence_max_per_day: INT, evidence_post_roll_seconds: INT,
  evidence_retention_days: INT, storage_max_mb: INT, fall_hold_seconds: FLT, group_distance_factor: FLT,
};

function Num({ label, k, form, set, ...rest }) {
  return (
    <label className="bx-field">{label}
      <input className="bx-input" type="number" value={form[k] ?? ''} onChange={(e) => set(k, e.target.value)} {...rest} />
    </label>
  );
}

export default function SettingsPage() {
  const [form, setForm] = useState({});
  const [override, setOverride] = useState(false);
  const [minSev, setMinSev] = useState('high');
  const [webhook, setWebhook] = useState('');
  const [hours, setHours] = useState({});
  const [savedHours, setSavedHours] = useState({});
  const [hoursSave, setHoursSave] = useState({ busy: false, message: '', ok: null });
  const [loadError, setLoadError] = useState('');
  const [params, setParams] = useSearchParams();
  const tab = resolveSettingsTab(params.get('tab'));
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  useEffect(() => {
    api.get('/settings/runtime').then((cfg) => {
      const t = cfg.thresholds;
      setForm({ ...t });
      setMinSev(t.evidence_min_severity); setOverride(!!t.critical_override_on_weapon);
      setWebhook(cfg.notifications.webhook_url || '');
      const h = {};
      DAYS.forEach(([key]) => {
        const w = cfg.operating_hours[key] || []; const closed = w.length !== 2;
        h[key] = { closed, open: closed ? '10:00' : w[0], close: closed ? '18:00' : w[1] };
      });
      setHours(h);
      setSavedHours(h);
    }).catch((e) => setLoadError(e.message));
  }, []);

  const saveThresholds = async () => {
    try {
      const cfg = await api.get('/settings/runtime');
      const parsed = {};
      Object.entries(PARSE).forEach(([k, fn]) => { parsed[k] = fn(form[k]); });
      cfg.thresholds = { ...cfg.thresholds, ...parsed, critical_override_on_weapon: override, evidence_min_severity: minSev };
      await api.post('/settings/runtime', cfg);
      alert('Thresholds saved. Camera workers pick these up automatically (checked every loop).');
    } catch (e) { alert(`Could not save: ${e.message}`); }
  };
  const saveNotify = async () => {
    try {
      const cfg = await api.get('/settings/runtime');
      cfg.notifications.webhook_url = webhook.trim();
      await api.post('/settings/runtime', cfg);
      alert('Notification settings saved.');
    } catch (e) { alert(`Could not save: ${e.message}`); }
  };
  const saveHours = async () => {
    if (hoursInvalid) return;
    setHoursSave({ busy: true, message: '', ok: null });
    try {
      const cfg = await api.get('/settings/runtime');
      const out = {};
      DAYS.forEach(([key]) => { const h = hours[key]; out[key] = h.closed ? [] : [h.open, h.close]; });
      cfg.operating_hours = out;
      await api.post('/settings/runtime', cfg);
      setSavedHours(hours);
      setHoursSave({ busy: false, message: 'Working hours saved successfully.', ok: true });
    } catch (e) { setHoursSave({ busy: false, message: `Could not save working hours: ${e.message}`, ok: false }); }
  };
  const setHour = (key, patch) => setHours((h) => ({ ...h, [key]: { ...h[key], ...patch } }));
  const hoursDirty = JSON.stringify(hours) !== JSON.stringify(savedHours);
  const hoursInvalid = DAYS.some(([key]) => {
    const h = hours[key];
    return h && !h.closed && (!h.open || !h.close || minutes(h.close) <= minutes(h.open));
  });
  const openDays = DAYS.filter(([key]) => hours[key] && !hours[key].closed).length;
  const weeklyMinutes = DAYS.reduce((total, [key]) => {
    const h = hours[key];
    return h && !h.closed && minutes(h.close) > minutes(h.open) ? total + minutes(h.close) - minutes(h.open) : total;
  }, 0);
  const copyMonday = (indexes) => {
    const monday = hours.mon;
    if (!monday) return;
    setHours((current) => {
      const next = { ...current };
      indexes.forEach((index) => { next[DAYS[index][0]] = { ...monday }; });
      return next;
    });
    setHoursSave({ busy: false, message: '', ok: null });
  };

  const n = { form, set };

  return (
    <>
      {loadError && <div className="bx-diag"><b>Could not load settings:</b> {loadError}</div>}
      <div role="group" aria-label="Settings sections" className="bx-row bx-gap-8 bx-wrap" style={{ marginBottom: 16 }}>
        {SETTINGS_TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            aria-current={tab === t.id ? 'true' : undefined}
            className={`bx-btn ${tab === t.id ? 'bx-btn-primary' : ''}`}
            onClick={() => setParams({ tab: t.id }, { replace: true })}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === 'general' && (
        <div className="bx-hours-settings">
          <div className="bx-card">
            <div className="bx-hours-heading">
              <div className="bx-hours-title">
                <div className="bx-card-title">Operating hours</div>
                <p className="bx-hint">Outside these hours, activity is treated as after-hours and intrusion alerts are raised.</p>
              </div>
              <div className="bx-hours-stats">
                <div className="bx-hours-stat"><small>Open days</small><strong>{openDays}</strong></div>
                <div className="bx-hours-stat"><small>Hours per week</small><strong>{durationLabel(weeklyMinutes)}</strong></div>
              </div>
            </div>
            <div className="bx-hours-tools">
              <button type="button" className="bx-btn bx-btn-sm" disabled={!hours.mon} onClick={() => copyMonday([1, 2, 3, 4])}>Copy Monday to weekdays</button>
              <button type="button" className="bx-btn bx-btn-sm" disabled={!hours.mon} onClick={() => copyMonday([1, 2, 3, 4, 5, 6])}>Copy Monday to all days</button>
              <button type="button" className="bx-btn bx-btn-sm" disabled={!hoursDirty} onClick={() => { setHours(savedHours); setHoursSave({ busy: false, message: '', ok: null }); }}>Discard changes</button>
              <span className="bx-hours-timezone">Times are evaluated in UTC</span>
            </div>
            <div className="bx-hours-scale" aria-hidden="true">
              <span /> <span /> <span /> <span />
              <div><span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>24:00</span></div>
              <span />
            </div>
            <div className="bx-hours-list">
            {DAYS.map(([key, label]) => {
              const h = hours[key]; if (!h) return null;
              const openMinute = minutes(h.open);
              const closeMinute = minutes(h.close);
              const invalid = !h.closed && (!h.open || !h.close || closeMinute <= openMinute);
              return (
                <div key={key} className={`bx-hours-day${h.closed ? ' is-closed' : ''}${invalid ? ' is-invalid' : ''}`}>
                  <div className="bx-hours-day-name">{label}</div>
                  <label className="bx-hours-toggle"><input type="checkbox" checked={!h.closed} onChange={(e) => { setHour(key, { closed: !e.target.checked }); setHoursSave({ busy: false, message: '', ok: null }); }} /><span className="bx-hours-switch" aria-hidden="true" /><span>{h.closed ? 'Closed' : 'Open'}</span></label>
                  <label className="bx-field">Opens <input className="bx-input" type="time" value={h.open} disabled={h.closed} aria-label={`${label} opens`} onChange={(e) => { setHour(key, { open: e.target.value }); setHoursSave({ busy: false, message: '', ok: null }); }} /></label>
                  <label className="bx-field">Closes <input className="bx-input" type="time" value={h.close} disabled={h.closed} aria-label={`${label} closes`} onChange={(e) => { setHour(key, { close: e.target.value }); setHoursSave({ busy: false, message: '', ok: null }); }} /></label>
                  <div className={`bx-hours-bar${invalid ? ' has-error' : ''}`} aria-label={h.closed ? 'Closed all day' : invalid ? 'Invalid time range' : `${durationLabel(closeMinute - openMinute)} open`}>
                    {!h.closed && !invalid && <span style={{ left: `${(openMinute / 1440) * 100}%`, width: `${((closeMinute - openMinute) / 1440) * 100}%` }} />}
                  </div>
                  <div className="bx-hours-duration">{h.closed ? 'Closed' : invalid ? '—' : durationLabel(closeMinute - openMinute)}</div>
                  {invalid && <div className="bx-hours-error" role="alert">Closing time must be later than opening time. Overnight hours aren’t supported.</div>}
                </div>
              );
            })}
            </div>
            <div className="bx-hours-footnote">Closing time must be later than opening time. Overnight shifts aren’t supported.</div>
            <div className={`bx-hours-footer${hoursDirty || hoursSave.message ? ' is-visible' : ''}`}>
              <span className="bx-hint" role="status" aria-live="polite" style={{ margin: 0, color: hoursSave.ok === true ? 'var(--bx-green)' : hoursSave.ok === false ? 'var(--bx-red)' : undefined }}>{hoursSave.message || (hoursInvalid ? 'Fix the highlighted day before saving.' : 'You have unsaved changes.')}</span>
              <button type="button" className="bx-btn" disabled={!hoursDirty || hoursSave.busy} onClick={() => { setHours(savedHours); setHoursSave({ busy: false, message: '', ok: null }); }}>Discard</button>
              <button type="button" className="bx-btn bx-btn-primary" disabled={hoursSave.busy || !hoursDirty || hoursInvalid} onClick={saveHours}>{hoursSave.busy ? 'Saving…' : 'Save working hours'}</button>
            </div>
          </div>
        </div>
      )}
      {tab === 'policies' && (
        <div className="bx-grid bx-grid-2" style={{ alignItems: 'start' }}>
          <div className="bx-card">
            <div className="bx-card-title">Scenario thresholds</div>
            <h4>Task 1 - Loitering</h4>
            <div className="bx-field-row"><Num label="Business-hours limit (s)" k="loiter_seconds_business_hours" {...n} /><Num label="After-hours limit (s)" k="loiter_seconds_after_hours" {...n} /></div>
            <h4>Task 2 - Gathering</h4>
            <div className="bx-field-row"><Num label="Minimum people" k="gathering_min_people" {...n} /><Num label="Proximity (m)" k="gathering_distance_m" step="0.1" {...n} /></div>
            <Num label="Persistence before confirming (s)" k="gathering_persistence_seconds" {...n} />
            <h4>Task 3 - Movement</h4>
            <div className="bx-field-row"><Num label="Tortuosity threshold" k="movement_tortuosity_threshold" step="0.1" {...n} /><Num label="Running speed (m/s)" k="movement_running_speed_mps" step="0.1" {...n} /></div>
            <h4>Task 4 - After-hours intrusion</h4>
            <div className="bx-field-row"><Num label="Grace period (min)" k="after_hours_grace_minutes" {...n} /><Num label="Min dwell to flag (s)" k="after_hours_min_dwell_seconds" {...n} /></div>
            <h4>Task 5 - AI-based anomaly</h4>
            <div className="bx-field-row"><Num label="Weapon confidence" k="weapon_confidence_threshold" step="0.05" {...n} /><Num label="Fight confidence" k="fight_confidence_threshold" step="0.05" {...n} /></div>
            <label className="bx-check"><input type="checkbox" checked={override} onChange={(e) => setOverride(e.target.checked)} /> Force CRITICAL severity whenever a weapon is held</label>
            <Num label="Alert de-duplication cooldown (s)" k="dedupe_cooldown_seconds" {...n} />
            <button type="button" className="bx-btn bx-btn-primary" style={{ marginTop: 6 }} onClick={saveThresholds}>Save thresholds</button>
          </div>

          <div className="bx-card">
            <div className="bx-card-title">Evidence storage (saves disk space)</div>
            <p className="bx-hint">Snapshots and clips are only stored for suspicious events. Everything else is still logged as an event, just without media.</p>
            <label className="bx-field">Store media when severity is at least
              <select className="bx-input" value={minSev} onChange={(e) => setMinSev(e.target.value)}>
                <option value="medium">medium</option><option value="high">high (recommended)</option><option value="critical">critical only</option>
              </select>
            </label>
            <div className="bx-field-row">
              <Num label="Cooldown per camera+scenario (s)" k="evidence_cooldown_seconds" min="0" {...n} />
              <Num label="Max evidence sets per day" k="evidence_max_per_day" min="1" {...n} />
            </div>
            <div className="bx-field-row">
              <Num label="Clip seconds after trigger" k="evidence_post_roll_seconds" min="0" max="30" {...n} />
              <Num label="Delete evidence older than (days)" k="evidence_retention_days" min="1" {...n} />
            </div>
            <Num label="Hard storage cap (MB) - oldest files deleted beyond this" k="storage_max_mb" min="100" {...n} />
            <div className="bx-field-row">
              <Num label="Fall: seconds lying before alert" k="fall_hold_seconds" step="0.5" min="1" {...n} />
              <Num label="Group distance (x body height)" k="group_distance_factor" step="0.1" min="0.3" {...n} />
            </div>
            <div className="bx-divider" />
            <div className="bx-card-title">Detection engine</div>
            <p className="bx-hint">Detector (RF-DETR + ByteTrack + RTMPose) is chosen in <code className="bx-mono">backend/.env</code> (<code className="bx-mono">PERSON_DETECTOR_BACKEND</code>) and needs a server restart to change. The Live Monitoring tiles show which engine each camera is really running.</p>
            <Num label="Processing rate (frames per second analysed per camera)" k="processing_fps" min="1" max="30" {...n} />
          </div>
        </div>
      )}
      {tab === 'integrations' && (
        <div className="bx-grid bx-grid-2" style={{ alignItems: 'start' }}>
          <div className="bx-card">
            <div className="bx-card-title">Notifications</div>
            <label className="bx-field">Webhook URL (optional - Slack/Teams-compatible incoming webhook)
              <input className="bx-input" value={webhook} onChange={(e) => setWebhook(e.target.value)} placeholder="https://hooks.slack.com/services/..." />
            </label>
            <button type="button" className="bx-btn bx-btn-primary" onClick={saveNotify}>Save notification settings</button>

          </div>
        </div>
      )}
      <p className="bx-hint" style={{ marginTop: 16 }}>Something not working? Open the <Link to="/branch-exterior/system-check" style={{ color: 'var(--bx-brand)', textDecoration: 'underline' }}>System check</Link> page.</p>
    </>
  );
}
