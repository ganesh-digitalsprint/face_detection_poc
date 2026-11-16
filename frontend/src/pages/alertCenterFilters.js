export function updateAlertCenterQuery(search, key, value) {
  const next = new URLSearchParams(search);
  if (value) next.set(key, value);
  else next.delete(key);
  if (key === 'branch_id') next.delete('camera_id');
  if (key === 'group') next.delete('status');
  if (key === 'status') next.delete('group');
  return next;
}

export function clearAlertCenterFilters(search) {
  const next = new URLSearchParams(search);
  for (const key of ['status', 'branch_id', 'camera_id', 'use_case', 'severity', 'evidence', 'type', 'from', 'to', 'source_event_id']) next.delete(key);
  return next;
}
