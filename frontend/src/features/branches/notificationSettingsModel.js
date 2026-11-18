const copy = (value) => JSON.parse(JSON.stringify(value));

export function defaultNotificationSettings(branch) {
  return {
    branchId: branch?.id || '',
    email: { enabled: false, recipients: [] },
    severity: { critical: true, high: true, warning: false, info: false },
    useCases: { vault_monitoring: true, grill_gate: true, branch_exterior: true, face_mask: false },
    include: { snapshot: true, videoClip: false },
    delivery: 'instant',
  };
}

export function settingsFromApi(branch, value) {
  return {
    branchId: branch?.id || '',
    email: { enabled: Boolean(value.email_enabled), recipients: [...(value.to_recipients || [])] },
    severity: { critical: value.severity_filters.includes('critical'), high: value.severity_filters.includes('high'),
      warning: value.severity_filters.includes('warning'), info: value.severity_filters.includes('info') },
    useCases: { vault_monitoring: value.use_case_filters.includes('vault_monitoring'),
      grill_gate: value.use_case_filters.includes('grill_gate'), branch_exterior: value.use_case_filters.includes('branch_exterior'),
      face_mask: value.use_case_filters.includes('face_mask') },
    include: { snapshot: Boolean(value.include_snapshot), videoClip: Boolean(value.include_video_evidence) },
    delivery: value.delivery_mode,
  };
}

export function settingsToApi(settings) {
  return {
    email_enabled: settings.email.enabled,
    to_recipients: [...new Set(settings.email.recipients.map((value) => value.trim().toLowerCase()))],
    severity_filters: Object.keys(settings.severity).filter((key) => settings.severity[key]),
    use_case_filters: Object.keys(settings.useCases).filter((key) => settings.useCases[key]),
    include_snapshot: settings.include.snapshot,
    include_video_evidence: settings.include.videoClip,
    delivery_mode: settings.delivery,
  };
}

export const cloneNotificationSettings = copy;

export function toggleNotificationRule(settings, group, key) {
  return { ...settings, [group]: { ...settings[group], [key]: !settings[group][key] } };
}

export function isEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());
}

export function notificationSettingsChanged(current, saved) {
  return JSON.stringify(current) !== JSON.stringify(saved);
}

export function createSubmissionGate() {
  let active = false;
  return {
    async run(task) {
      if (active) return { skipped: true };
      active = true;
      try { return await task(); }
      finally { active = false; }
    },
  };
}
