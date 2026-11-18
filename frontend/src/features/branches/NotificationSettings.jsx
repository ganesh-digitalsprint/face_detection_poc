import { useEffect, useMemo, useRef, useState } from 'react';
import { Mail, X } from 'lucide-react';
import { getBranchNotificationDeliveries, getBranchNotificationSettings, saveBranchNotificationSettings, sendBranchTestEmail } from '../../api/alertService.js';
import { cloneNotificationSettings, createSubmissionGate, defaultNotificationSettings, isEmail, notificationSettingsChanged, settingsFromApi, settingsToApi, toggleNotificationRule } from './notificationSettingsModel.js';
import './NotificationSettings.css';

const ruleLabels = {
  severity: [['critical', 'Critical'], ['high', 'High'], ['warning', 'Warning'], ['info', 'Info']],
  useCases: [['vault_monitoring', 'Vault Monitoring'], ['grill_gate', 'Gate Monitoring'], ['branch_exterior', 'Branch Exterior'], ['face_mask', 'Face Mask']],
  include: [['snapshot', 'Snapshot image'], ['videoClip', 'Video clip link']],
};

function Toggle({ checked, onChange, label }) {
  return <button type="button" role="switch" aria-checked={checked} aria-label={label} onClick={() => onChange(!checked)} className={`notification-toggle ${checked ? 'is-on' : ''}`}><span /></button>;
}

function RuleGroup({ title, group, settings, onToggle }) {
  return <fieldset className="notification-rule-group"><legend>{title}</legend><div>{ruleLabels[group].map(([key, label]) => <label key={key}><input type="checkbox" checked={settings[group][key]} onChange={() => onToggle(group, key)} /> <span>{label}</span></label>)}</div></fieldset>;
}

export default function NotificationSettings({ branch }) {
  const initial = useMemo(() => defaultNotificationSettings(branch), [branch?.id]);
  const [saved, setSaved] = useState(initial);
  const [settings, setSettings] = useState(initial);
  const [loadedBranchId, setLoadedBranchId] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [email, setEmail] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [sending, setSending] = useState(false);
  const [deliveries, setDeliveries] = useState([]);
  const [deliveriesLoading, setDeliveriesLoading] = useState(true);
  const submission = useRef(createSubmissionGate());
  const drafts = useRef(new Map());
  const stateRef = useRef({ settings, saved });
  stateRef.current = { settings, saved };
  const branchIdRef = useRef(branch.id);
  branchIdRef.current = branch.id;

  useEffect(() => {
    let current = true;
    setLoading(true); setLoadFailed(false); setLoadedBranchId(''); setSaved(initial); setSettings(initial); setSaving(false); setSending(false);
    setEmail(''); setError(''); setNotice('');
    getBranchNotificationSettings(branch.id).then((response) => {
      if (!current) return;
      const loaded = settingsFromApi(branch, response);
      const draft = drafts.current.get(branch.id);
      setSaved(loaded); setSettings(cloneNotificationSettings(draft || loaded)); setLoadedBranchId(branch.id);
      if (draft) setNotice('Restored your unsaved edits for this branch.');
    }).catch((failure) => {
      if (!current) return;
      setError(failure.response?.data?.detail?.message || failure.message || 'Could not load branch notification settings.');
      setLoadFailed(true);
    }).finally(() => { if (current) setLoading(false); });
    return () => {
      current = false;
      const latest = stateRef.current;
      if (latest.settings.branchId === branch.id && notificationSettingsChanged(latest.settings, latest.saved)) {
        drafts.current.set(branch.id, cloneNotificationSettings(latest.settings));
      }
    };
  }, [branch.id]);

  useEffect(() => {
    let current = true;
    setDeliveries([]); setDeliveriesLoading(true);
    let controller;
    const refresh = () => {
      controller?.abort();
      const requestController = new AbortController();
      controller = requestController;
      getBranchNotificationDeliveries(branch.id, requestController.signal).then((items) => {
        if (current) setDeliveries(items);
      }).catch(() => {
        if (current && !requestController.signal.aborted) setDeliveries([]);
      }).finally(() => { if (current) setDeliveriesLoading(false); });
    };
    refresh();
    const timer = window.setInterval(refresh, 15000);
    return () => { current = false; window.clearInterval(timer); controller?.abort(); };
  }, [branch.id]);

  const branchReady = loadedBranchId === branch.id && !loading && !loadFailed;
  const dirty = notificationSettingsChanged(settings, saved);
  const updateEmail = (patch) => setSettings((current) => ({ ...current, email: { ...current.email, ...patch } }));
  const addEmail = () => {
    const value = email.trim().toLowerCase();
    if (!isEmail(value)) { setError('Enter a valid email address.'); return; }
    if (settings.email.recipients.includes(value)) { setError('That recipient is already added.'); return; }
    updateEmail({ recipients: [...settings.email.recipients, value] }); setEmail(''); setError('');
  };
  const save = () => submission.current.run(async () => {
    if (settings.email.enabled && settings.email.recipients.length === 0) { setError('Add at least one To recipient before enabling email notifications.'); return; }
    setSaving(true); setError(''); setNotice('');
    try {
      const response = await saveBranchNotificationSettings(branch.id, settingsToApi(settings));
      if (branchIdRef.current !== branch.id) return;
      const persisted = settingsFromApi(branch, response);
      drafts.current.delete(branch.id);
      setSaved(persisted); setSettings(cloneNotificationSettings(persisted)); setNotice('Notification settings saved.');
    } catch (failure) {
      if (branchIdRef.current === branch.id) setError(failure.response?.data?.detail?.message || failure.message || 'Notification settings could not be saved.');
    } finally { if (branchIdRef.current === branch.id) setSaving(false); }
  });
  const discard = () => { drafts.current.delete(branch.id); setSettings(cloneNotificationSettings(saved)); setEmail(''); setError(''); setNotice('Changes discarded.'); };
  const sendTest = () => submission.current.run(async () => {
    if (dirty) { setError('Save or discard your changes before sending a test email.'); return; }
    if (!saved.email.enabled || !saved.email.recipients.length) { setError('Enable email notifications and save at least one To recipient before testing.'); return; }
    setSending(true); setError(''); setNotice('');
    try { const result = await sendBranchTestEmail(branch.id); if (branchIdRef.current === branch.id) setNotice(result.message || 'Gmail SMTP accepted the test email for delivery.'); }
    catch (failure) { if (branchIdRef.current === branch.id) setError(failure.response?.data?.detail?.message || failure.message || 'The test email could not be sent.'); }
    finally { if (branchIdRef.current === branch.id) setSending(false); }
  });

  if (!branchReady) return <section className="notification-settings" aria-live="polite"><h2>Alert notifications · {branch.name}</h2>{loading ? <p>Loading saved notification settings…</p> : <p role="alert">{error || 'Settings could not be loaded.'}</p>}</section>;
  return <section className="notification-settings" aria-labelledby="notification-settings-title">
    <div className="notification-heading"><h2 id="notification-settings-title">5 · Alert notifications · {branch.name}</h2><p>Configure email alerts for {branch.name}. Settings apply only to this branch.</p></div>
    {(error || notice) && <div role={error ? 'alert' : 'status'} className={`notification-feedback ${error ? 'is-error' : ''}`}>{error || notice}<button type="button" aria-label="Dismiss message" onClick={() => { setError(''); setNotice(''); }}><X size={14} /></button></div>}
    <div className="notification-grid">
      <article className="notification-card">
        <div className="notification-card-title"><span className="notification-icon email"><Mail size={16} /></span><h3>Email</h3><Toggle checked={settings.email.enabled} onChange={(enabled) => updateEmail({ enabled })} label="Enable email notifications" /></div>
        <p>Send matching branch alerts to the saved To recipients.</p>
        {branch.email && <p className="notification-suggestion">Existing branch email suggestion: {branch.email}. Add it explicitly to use it.</p>}
        <strong>To recipients · {settings.email.recipients.length}</strong>
        <div className="notification-recipient-list">{settings.email.recipients.map((recipient) => <div key={recipient}><span>{recipient}</span><button type="button" aria-label={`Remove ${recipient}`} onClick={() => updateEmail({ recipients: settings.email.recipients.filter((item) => item !== recipient) })}><X size={14} /></button></div>)}</div>
        <div className="notification-add-row"><input aria-label="Email recipient" placeholder="name@company.com" value={email} onChange={(event) => setEmail(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); addEmail(); } }} /><button type="button" onClick={addEmail}>+ Add email</button></div>
        <button type="button" className="notification-outline-button" disabled={sending || saving || dirty || !saved.email.enabled || !saved.email.recipients.length} title={dirty ? 'Save or discard changes before testing' : ''} onClick={sendTest}>{sending ? 'Sending…' : 'Send test email'}</button>
      </article>
      <article className="notification-card notification-rules">
        <div className="notification-card-title"><h3>Send rules</h3></div><p>Choose which alerts trigger a message.</p>
        <RuleGroup title="Severity" group="severity" settings={settings} onToggle={(group, key) => setSettings((current) => toggleNotificationRule(current, group, key))} />
        <RuleGroup title="Use cases" group="useCases" settings={settings} onToggle={(group, key) => setSettings((current) => toggleNotificationRule(current, group, key))} />
        <RuleGroup title="Include" group="include" settings={settings} onToggle={(group, key) => setSettings((current) => toggleNotificationRule(current, group, key))} />
        <fieldset className="notification-rule-group"><legend>Delivery</legend><div className="notification-delivery"><button type="button" aria-pressed={settings.delivery === 'instant'} onClick={() => setSettings((current) => ({ ...current, delivery: 'instant' }))}>Instant</button><button type="button" aria-disabled="true" disabled title="Hourly digest is not implemented">Hourly digest · unavailable</button></div></fieldset>
      </article>
    </div>
    <div className="notification-actions"><button type="button" className="notification-outline-button" disabled={!dirty || saving} onClick={discard}>Discard changes</button><button type="button" className="notification-save" disabled={!dirty || saving} onClick={save}>{saving ? 'Saving…' : 'Save notification settings'}</button></div>
    <article className="notification-card notification-deliveries">
      <div><h3>Recent deliveries</h3><span>{branch.name}</span></div>
      {deliveriesLoading ? <p>Loading delivery history…</p> : deliveries.length === 0 ? <p>No email delivery attempts for this branch yet.</p> : <div className="notification-table-wrap"><table><thead><tr><th>Alert</th><th>To</th><th>Status</th><th>Attempts</th><th>Last attempt</th></tr></thead><tbody>
        {deliveries.map((item) => <tr key={item.id}><td>{item.alert?.title || item.alert_id}</td><td>{item.recipient}</td><td><span className={item.status === 'ACCEPTED' ? 'success' : item.status === 'DEAD' ? 'failed' : ''}>{({ ACCEPTED: 'Accepted by SMTP', DEAD: 'Failed', RETRY: 'Retry scheduled', PENDING: 'Pending', SENDING: 'Sending', CANCELLED: 'Cancelled' })[item.status] || item.status}</span></td><td>{item.attempts}</td><td>{item.last_attempt_at ? new Date(item.last_attempt_at).toLocaleString() : '—'}</td></tr>)}
      </tbody></table></div>}
    </article>
  </section>;
}
