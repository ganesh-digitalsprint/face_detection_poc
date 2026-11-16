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

export function tickerDetailLocation(pathname, search, sourceEventId) {
  const query = new URLSearchParams(search);
  query.set('event', sourceEventId);
  return { pathname, search: `?${query.toString()}` };
}
