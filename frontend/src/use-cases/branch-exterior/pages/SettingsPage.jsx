import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api/index.js';
import { SETTINGS_TABS, resolveSettingsTab } from '../settingsTabs.js';

const DAYS = [['mon', 'Monday'], ['tue', 'Tuesday'], ['wed', 'Wednesday'], ['thu', 'Thursday'], ['fri', 'Friday'], ['sat', 'Saturday'], ['sun', 'Sunday']];
const PORTS = { postgres: 5432, mysql: 3306, oracle: 1521, mongodb: 27017 };
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
  const [db, setDb] = useState({ engine: 'sqlite', sqlite_path: 'storage/app.db', host: 'localhost', port: '', user: '', password: '', passwordSet: false, database: 'branch_monitoring', oracle_service_name: '' });
  const [dbResult, setDbResult] = useState({ text: '', ok: null });
  const [form, setForm] = useState({});
  const [override, setOverride] = useState(false);
  const [minSev, setMinSev] = useState('high');
  const [webhook, setWebhook] = useState('');
  const [hours, setHours] = useState({});
  const [loadError, setLoadError] = useState('');
  const [params, setParams] = useSearchParams();
  const tab = resolveSettingsTab(params.get('tab'));
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const setD = (k, v) => setDb((d) => ({ ...d, [k]: v }));

  useEffect(() => {
    api.get('/settings/database').then((cfg) => setDb({
      engine: cfg.engine, sqlite_path: cfg.sqlite_path || 'storage/app.db', host: cfg.host || 'localhost',
      port: cfg.port || PORTS[cfg.engine] || '', user: cfg.user || '', password: cfg.password && cfg.password !== '********' ? cfg.password : '',
      passwordSet: cfg.password === '********', database: cfg.database || 'branch_monitoring', oracle_service_name: cfg.oracle_service_name || '',
    })).catch((e) => setLoadError(e.message));
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
    }).catch((e) => setLoadError(e.message));
  }, []);

  const changeEngine = (engine) => setDb({ engine, sqlite_path: 'storage/app.db', host: 'localhost', port: PORTS[engine] || '', user: '', password: '', passwordSet: false, database: 'branch_monitoring', oracle_service_name: '' });

  const readDb = () => {
    const p = { engine: db.engine };
    if (db.engine === 'sqlite') p.sqlite_path = db.sqlite_path.trim() || 'storage/app.db';
    else {
      p.host = db.host.trim(); p.port = parseInt(db.port, 10) || 0; p.user = db.user.trim();
      p.password = db.password; p.database = db.database.trim();
      if (db.engine === 'oracle') p.oracle_service_name = db.oracle_service_name.trim();
    }
    return p;
  };

  const testDb = async () => {
    setDbResult({ text: 'Testing...', ok: null });
    try {
      const r = await api.post('/settings/database/test', readDb());
      setDbResult({ text: r.ok ? `✓ Connected (${r.latency_ms} ms)` : `✗ ${r.message}`, ok: r.ok });
    } catch (e) { setDbResult({ text: `✗ ${e.message}`, ok: false }); }
  };
  const saveDb = async () => {
    if (!confirm('Switching databases will restart all camera workers and point every table (cameras, zones, guards, events) at the new database. Continue?')) return;
    try { await api.post('/settings/database', readDb()); alert('Database reconnected successfully.'); window.location.reload(); } catch (e) { alert(`Failed to switch database: ${e.message}`); }
  };

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
    try {
      const cfg = await api.get('/settings/runtime');
      const out = {};
      DAYS.forEach(([key]) => { const h = hours[key]; out[key] = h.closed ? [] : [h.open, h.close]; });
      cfg.operating_hours = out;
      await api.post('/settings/runtime', cfg);
      alert('Operating hours saved.');
    } catch (e) { alert(`Could not save: ${e.message}`); }
  };
  const setHour = (key, patch) => setHours((h) => ({ ...h, [key]: { ...h[key], ...patch } }));

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
        <div className="bx-grid bx-grid-2" style={{ alignItems: 'start' }}>
          <div className="bx-card">
            <div className="bx-card-title">Database connection</div>
            <p className="bx-hint" style={{ marginBottom: 12 }}>
              Point the whole system at SQLite, PostgreSQL, MySQL, Oracle or MongoDB. All dashboard data - cameras, zones, guards and every alert - is read from and written to
              whichever database is configured here. Switching engines reconnects live; no restart needed.
            </p>
            <label className="bx-field">Database engine
              <select className="bx-input" value={db.engine} onChange={(e) => changeEngine(e.target.value)}>
                <option value="sqlite">SQLite (file-based, zero setup - good for this POC)</option>
                <option value="postgres">PostgreSQL</option><option value="mysql">MySQL</option>
                <option value="oracle">Oracle</option><option value="mongodb">MongoDB</option>
              </select>
            </label>
            {db.engine === 'sqlite' ? (
              <label className="bx-field">File path (relative to backend/)
                <input className="bx-input" value={db.sqlite_path} onChange={(e) => setD('sqlite_path', e.target.value)} />
              </label>
            ) : (
              <>
                <div className="bx-field-row">
                  <label className="bx-field">Host <input className="bx-input" value={db.host} onChange={(e) => setD('host', e.target.value)} /></label>
                  <label className="bx-field">Port <input className="bx-input" type="number" value={db.port} onChange={(e) => setD('port', e.target.value)} /></label>
                </div>
                <div className="bx-field-row">
                  <label className="bx-field">Username <input className="bx-input" value={db.user} onChange={(e) => setD('user', e.target.value)} /></label>
                  <label className="bx-field">Password <input className="bx-input" type="password" value={db.password} placeholder={db.passwordSet ? 'unchanged' : ''} onChange={(e) => setD('password', e.target.value)} /></label>
                </div>
                <label className="bx-field">Database name{db.engine === 'oracle' ? ' (or leave blank to use service name below)' : ''}
                  <input className="bx-input" value={db.database} onChange={(e) => setD('database', e.target.value)} />
                </label>
                {db.engine === 'oracle' && <label className="bx-field">Oracle service name (optional) <input className="bx-input" value={db.oracle_service_name} onChange={(e) => setD('oracle_service_name', e.target.value)} /></label>}
              </>
            )}
            <div className="bx-row bx-gap-8 bx-wrap" style={{ marginTop: 6 }}>
              <button type="button" className="bx-btn" onClick={testDb}>Test connection</button>
              <button type="button" className="bx-btn bx-btn-primary" onClick={saveDb}>Save &amp; reconnect</button>
              <span className="bx-hint" style={{ margin: 0, color: dbResult.ok === null ? undefined : dbResult.ok ? 'var(--bx-green)' : 'var(--bx-red)' }}>{dbResult.text}</span>
            </div>
          </div>

          <div className="bx-card">
            <div className="bx-card-title">Operating hours (used by Task 1 and Task 4)</div>
            {DAYS.map(([key, label]) => {
              const h = hours[key]; if (!h) return null;
              return (
                <div key={key} className="bx-field-row" style={{ alignItems: 'end', gridTemplateColumns: '90px 1fr 1fr auto' }}>
                  <div style={{ fontWeight: 500, paddingBottom: 9 }}>{label}</div>
                  <label className="bx-field">Open <input className="bx-input" type="time" value={h.open} disabled={h.closed} onChange={(e) => setHour(key, { open: e.target.value })} /></label>
                  <label className="bx-field">Close <input className="bx-input" type="time" value={h.close} disabled={h.closed} onChange={(e) => setHour(key, { close: e.target.value })} /></label>
                  <label className="bx-check" style={{ paddingBottom: 9 }}><input type="checkbox" checked={h.closed} onChange={(e) => setHour(key, { closed: e.target.checked })} /> Closed</label>
                </div>
              );
            })}
            <button type="button" className="bx-btn bx-btn-primary" style={{ marginTop: 10 }} onClick={saveHours}>Save operating hours</button>
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
