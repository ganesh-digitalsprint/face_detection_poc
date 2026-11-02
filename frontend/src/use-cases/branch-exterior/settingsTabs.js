/** Tabs of the Settings page. Selected with ?tab=; anything unknown falls back to the first tab. */
export const SETTINGS_TABS = [
  { id: 'general', label: 'General' },
  { id: 'policies', label: 'Policies' },
  { id: 'integrations', label: 'Integrations' },
];

export const resolveSettingsTab = (value) => SETTINGS_TABS.find((t) => t.id === value)?.id ?? SETTINGS_TABS[0].id;
