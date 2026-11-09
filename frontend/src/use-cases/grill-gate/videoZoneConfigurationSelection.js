const selectionKey = (job) => {
  const assetId = job?.asset_job_id || job?.job_id;
  return assetId ? `grill-gate:video-zone-configuration:${assetId}` : '';
};
const selectionEvent = 'grill-gate:video-zone-configuration-selected';

export function readVideoZoneConfigurationSelection(job, storage = globalThis.localStorage) {
  const key = selectionKey(job);
  if (!key || !storage) return '';
  try { return storage.getItem(key); } catch { return null; }
}

export function rememberVideoZoneConfigurationSelection(job, configurationId, storage = globalThis.localStorage) {
  const key = selectionKey(job);
  if (!key || !storage) return;
  try {
    storage.setItem(key, configurationId ? String(configurationId) : '');
    if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(selectionEvent, {
      detail: { assetId: job.asset_job_id || job.job_id, configurationId: configurationId ? String(configurationId) : '' },
    }));
  } catch {
    // Storage is a convenience for restoring the operator's selection; server snapshots remain authoritative.
  }
}

/** Prefer the operator's saved choice, then the configuration explicitly referenced by this job snapshot. */
export function initialVideoZoneConfigurationSelection(job, storage = globalThis.localStorage) {
  const stored = readVideoZoneConfigurationSelection(job, storage);
  return stored !== null ? stored : job?.zone_configuration_id || '';
}

export const VIDEO_ZONE_CONFIGURATION_SELECTION_EVENT = selectionEvent;

/** Keep zero-like numeric values intact; a null threshold remains unset as in the backend alert schema. */
export function videoAlertThresholdInputValue(alertConfiguration, thresholdKey) {
  return alertConfiguration?.[thresholdKey] ?? '';
}

/** Fill a missing video threshold from the selected assignment without replacing a saved job value. */
export function videoAlertConfigurationWithAssignmentDefault(jobAlerts = {}, assignmentAlerts = {}, editable = true) {
  const localThreshold = jobAlerts?.max_gate_open_seconds;
  const assignmentThreshold = assignmentAlerts?.max_gate_open_seconds;
  if (!editable || localThreshold != null || assignmentThreshold == null) return jobAlerts ?? {};
  return {
    ...jobAlerts,
    max_gate_open_seconds: assignmentThreshold,
    gate_open_enabled: assignmentAlerts.gate_open_enabled ?? jobAlerts?.gate_open_enabled ?? false,
  };
}
