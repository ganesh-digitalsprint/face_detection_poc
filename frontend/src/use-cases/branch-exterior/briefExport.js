import { parseCsv, rowsToObjects, safeCell, toCsv } from '../../utils/csv.js';

/** Columns of the combined ("All use cases") export. No credentials and no personal identity data are ever included. */
export const COMBINED_COLUMNS = [
  'use_case', 'event_id', 'timestamp_utc', 'camera', 'zone_or_roi', 'track_id', 'type', 'score', 'severity', 'status',
  'reviewer', 'remarks', 'message',
];

const faceMaskRow = (r) => ({
  use_case: 'face_mask', event_id: r.event_id, timestamp_utc: r.first_seen_utc, camera: r.camera_name || r.camera_id,
  zone_or_roi: r.roi_name, track_id: r.track_id, type: r.covering_type, score: r.score, severity: '', status: r.status,
  reviewer: r.reviewer, remarks: r.remarks, message: '',
});

const branchRow = (r) => ({
  use_case: 'branch_exterior', event_id: r.id, timestamp_utc: r.created_at, camera: r.camera, zone_or_roi: r.zone,
  track_id: '', type: r.scenario, score: r.confidence, severity: r.severity, status: r.status, reviewer: '', remarks: '',
  message: r.message,
});

/** Branch's export has no end-of-range filter, so drop rows created after `until` here. */
export function filterBranchRows(rows, until) {
  if (!until) return rows;
  const cutoff = until.getTime();
  return rows.filter((r) => {
    const t = Date.parse(r.created_at);
    return Number.isNaN(t) || t <= cutoff;
  });
}

const TEXT_COLUMNS = new Set(['camera', 'zone_or_roi', 'reviewer', 'remarks', 'message']);

/**
 * Merge the reachable services' exports into one CSV. `parts` = { face_mask?: csvText, branch_exterior?: csvText }.
 * `skipped` = [{ label, reason }] are named in comment lines at the top (only when something was skipped).
 */
export function buildCombinedCsv(parts, { until = null, skipped = [], filtersText = '' } = {}) {
  const rows = [];
  if (parts.face_mask != null) rows.push(...rowsToObjects(parseCsv(parts.face_mask)).map(faceMaskRow));
  if (parts.branch_exterior != null) rows.push(...filterBranchRows(rowsToObjects(parseCsv(parts.branch_exterior)), until).map(branchRow));
  rows.sort((a, b) => String(b.timestamp_utc).localeCompare(String(a.timestamp_utc)));
  const body = rows.map((r) => COMBINED_COLUMNS.map((c) => (TEXT_COLUMNS.has(c) ? safeCell(r[c]) : r[c])));
  const notes = [];
  if (filtersText) notes.push(`# Filters: ${filtersText}`);
  skipped.forEach((s) => notes.push(`# Skipped ${s.label}: ${s.reason}`));
  const header = notes.length ? `${notes.join('\r\n')}\r\n` : '';
  return header + toCsv([COMBINED_COLUMNS, ...body]);
}

/** Raw Branch CSV text with the end-of-range filter applied (header kept as is). */
export function trimBranchCsv(text, until) {
  if (!until) return text;
  const [header = [], ...body] = parseCsv(text);
  const at = header.indexOf('created_at');
  const cutoff = until.getTime();
  const kept = body.filter((r) => { const t = Date.parse(r[at]); return Number.isNaN(t) || t <= cutoff; });
  return toCsv([header, ...kept]);
}
