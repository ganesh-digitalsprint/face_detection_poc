export const ACTIVITY_CATEGORIES = ['All', 'Entry', 'Door', 'Activity', 'System'];
export function latestActivityNotificationId(events, { sessionId, source, sourceId, replay }) {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const event = events[i], data = event.data;
    if (event.type === 'activity.created' && data?.session_id === sessionId && data.source === source
      && (!sourceId || data.source_id === sourceId) && data.replay === replay) return event.id;
  }
  return undefined;
}
export function activityCategory(type = '') {
  if (['PERSON_ENTERED', 'VAULT_AREA_ENTERED'].includes(type)) return 'Entry';
  if (/DOOR|VAULT_(OPEN|LOCK)/.test(type)) return 'Door';
  if (/^SESSION_|^SYSTEM_/.test(type)) return 'System';
  return 'Activity';
}
export function mergeActivities(rows) {
  return [...new Map(rows.filter((row) => row?.id).map((row) => [row.id, row])).values()]
    .sort((a, b) => {
      const sourceOrder = a.replay && b.replay && Number.isFinite(a.video_timestamp_seconds) && Number.isFinite(b.video_timestamp_seconds)
        ? a.video_timestamp_seconds - b.video_timestamp_seconds : 0;
      const createdOrder = (Date.parse(a.created_at) || 0) - (Date.parse(b.created_at) || 0);
      // Date.parse truncates microseconds. Match the backend tie key precisely.
      const remainder = (value) => (value?.match(/\.(\d+)(?:Z|[+-]\d{2}:\d{2})$/)?.[1] || '').slice(3).padEnd(6, '0');
      const compare = (left, right) => left < right ? -1 : left > right ? 1 : 0;
      return sourceOrder || createdOrder || compare(remainder(a.created_at), remainder(b.created_at)) || compare(a.id, b.id);
    });
}

/** Fetch an oldest-first prefix/page range, never reverse newest-first pages. */
export async function readChronologicalActivityPages(fetchPage, { offset = 0, limit = 25, pageSize = 25, followNewEvents = false } = {}) {
  const items = []; let total = 0, end = offset + limit;
  for (let cursor = offset; cursor < end; cursor += pageSize) {
    const page = await fetchPage({ order: 'asc', limit: pageSize, offset: cursor });
    total = page.total; items.push(...page.items);
    // Freeze the live-tail target from the first response, even on a busy stream.
    if (cursor === offset && followNewEvents) end = Math.max(end, total);
    if (cursor + page.items.length >= total || page.items.length < pageSize) break;
  }
  return { items, total, nextOffset: offset + items.length };
}
export function activityVideoTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '\u2014';
  const tenths = Math.floor(seconds * 10 + .0001);
  return `${Math.floor(tenths / 600)}:${String(Math.floor(tenths / 10) % 60).padStart(2, '0')}.${tenths % 10}`;
}
export function activityTime(event) {
  if (event.replay) return activityVideoTime(event.video_timestamp_seconds);
  const date = new Date(event.created_at);
  return Number.isFinite(date.getTime()) ? date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : '\u2014';
}
const ZONES = { person_monitoring_roi: 'Person Monitoring Area', vault_area_roi: 'Vault Area', vault_door_roi: 'Vault Door', tray_area_roi: 'Tray Area', ornament_area_roi: 'Ornament Area' };
export const activityZone = (id) => ZONES[id] || id || 'No associated zone';
