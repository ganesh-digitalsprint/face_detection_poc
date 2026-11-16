const eventTime = (event) => {
  const value = Date.parse(event?.created_at || event?.first_seen || event?.occurredAt || '');
  return Number.isFinite(value) ? value : 0;
};

export function mergeTickerEvents(current = [], incoming = [], limit = 25) {
  const byId = new Map();
  for (const event of current) if (event?.id) byId.set(event.id, event);
  for (const event of incoming) if (event?.id) byId.set(event.id, { ...byId.get(event.id), ...event });
  return [...byId.values()].sort((a, b) => eventTime(b) - eventTime(a)).slice(0, limit);
}

export function branchEventDestination(sourceEventId, commonAlert) {
  const source = encodeURIComponent(sourceEventId);
  if (commonAlert?.id) return `/alerts?use_case=branch_exterior&alert_id=${encodeURIComponent(commonAlert.id)}&source_event_id=${source}`;
  return `/branch-exterior/live?event=${source}`;
}

export async function findCommonAlert(sourceEventId, knownAlert, listAlerts) {
  if (knownAlert?.id) return knownAlert;
  try {
    const page = await listAlerts({ use_case:'branch_exterior', source_event_id:sourceEventId, limit:1 });
    return page.items?.find((alert) => alert.sourceEventId === sourceEventId) || null;
  } catch { return null; }
}
