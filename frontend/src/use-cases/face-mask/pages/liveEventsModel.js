export function normalizeLiveEvents(items = []) {
  const unique = new Map();
  for (const event of items) if (event?.id && !unique.has(event.id)) unique.set(event.id, event);
  return [...unique.values()].sort((a, b) =>
    (Date.parse(b.first_seen || '') || 0) - (Date.parse(a.first_seen || '') || 0)
    || String(b.id).localeCompare(String(a.id)));
}

export function newestUnseenEvent(previousIds, events) {
  return previousIds ? events.find((event) => !previousIds.has(event.id)) || null : null;
}

export function incidentStatusForEvent(status) {
  return ({ OPEN: 'OPEN', UNDER_REVIEW: 'ACKNOWLEDGED', CONFIRMED: 'ACKNOWLEDGED', FALSE_POSITIVE: 'DISMISSED', CLOSED: 'RESOLVED' })[status] || '—';
}
