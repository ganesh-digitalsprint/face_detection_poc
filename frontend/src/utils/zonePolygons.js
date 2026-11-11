// Normalized polygons are open vertex lists. Canvas/SVG and the backend close them.
const EPS = 1e-12;
const point = (p) => Array.isArray(p) ? (p.length === 2 ? [p[0], p[1]] : [undefined, undefined]) : [p?.x, p?.y];
const equal = (a, b) => a[0] === b[0] && a[1] === b[1];
const orient = (a, b, c) => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
const onSegment = (a, b, p) => Math.abs(orient(a, b, p)) <= EPS
  && p[0] >= Math.min(a[0], b[0]) - EPS && p[0] <= Math.max(a[0], b[0]) + EPS
  && p[1] >= Math.min(a[1], b[1]) - EPS && p[1] <= Math.max(a[1], b[1]) + EPS;
export function segmentsIntersect(a, b, c, d) {
  const [abC, abD, cdA, cdB] = [orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)];
  if (((abC > EPS && abD < -EPS) || (abC < -EPS && abD > EPS))
      && ((cdA > EPS && cdB < -EPS) || (cdA < -EPS && cdB > EPS))) return true;
  return onSegment(a, b, c) || onSegment(a, b, d) || onSegment(c, d, a) || onSegment(c, d, b);
}
function crossings(p) {
  const result = [];
  for (let i = 0; i < p.length; i++) for (let j = i + 1; j < p.length; j++) {
    if (j === i + 1 || (i === 0 && j === p.length - 1)) continue;
    if (segmentsIntersect(p[i], p[(i + 1) % p.length], p[j], p[(j + 1) % p.length])) result.push([i, j]);
  }
  return result;
}
export function polygonError(polygon, { minArea = 0.001 } = {}) {
  if (!Array.isArray(polygon) || polygon.length < 3) return 'A polygon needs at least three distinct corners.';
  const p = polygon.map(point);
  if (p.some((v) => !v.every(Number.isFinite))) return 'Polygon coordinates must be finite numbers.';
  if (p.some((v) => v.some((value) => value < 0 || value > 1))) return 'Polygon coordinates must be between 0 and 1.';
  for (let i = 0; i < p.length; i++) {
    if (equal(p[i], p[(i + 1) % p.length])) return 'Polygon has a zero-length edge.';
    for (let j = i + 1; j < p.length; j++) if (equal(p[i], p[j])) return 'Polygon repeats a corner.';
    const a = p[(i + p.length - 1) % p.length], b = p[i], c = p[(i + 1) % p.length];
    if (Math.abs(orient(a, b, c)) <= EPS
        && (a[0] - b[0]) * (c[0] - b[0]) + (a[1] - b[1]) * (c[1] - b[1]) > EPS) {
      return 'Polygon edges overlap. Please adjust the corners before saving.';
    }
  }
  if (crossings(p).length) return 'Polygon edges intersect. Please adjust the corners before saving.';
  const area = Math.abs(p.reduce((sum, a, i) => {
    const b = p[(i + 1) % p.length]; return sum + a[0] * b[1] - b[0] * a[1];
  }, 0)) / 2;
  if (area <= EPS || area < minArea) return minArea > 0
    ? 'Polygon is too small or its corners are in a line (minimum area: 0.1% of the frame).'
    : 'Polygon must have a nonzero area.';
  return '';
}
export function normalizePolygon(polygon, { width, height, ...options } = {}) {
  if (!Array.isArray(polygon)) return [];
  const p = polygon.map(point).filter((v, i, all) => !i || !equal(v, all[i - 1]));
  while (p.length > 1 && equal(p[0], p.at(-1))) p.pop();
  // Never simplify valid close corners. Only remove a tiny invalid closing tail:
  // it must cross the first edge, and removing it must yield a valid polygon.
  if (p.length > 3 && Number.isFinite(width) && width > 0 && Number.isFinite(height) && height > 0) {
    const first = p[0], last = p.at(-1);
    const near = Math.hypot((first[0] - last[0]) * width, (first[1] - last[1]) * height) <= 3
      && Math.hypot(first[0] - last[0], first[1] - last[1]) <= 0.003;
    if (near && polygonError(p, options)) {
      const hits = crossings(p);
      if (hits.length && hits.every(([a, b]) => a === 0 && b === p.length - 2)
          && !polygonError(p.slice(0, -1), options)) p.pop();
    }
  }
  return p;
}
export class ZonePolygonError extends Error {
  constructor(message, zone, index) {
    super(`${zone.name || zone.zone_key || `Zone ${index + 1}`}: ${message}`);
    this.name = 'ZonePolygonError'; this.zoneIndex = index; this.zoneId = zone.id;
  }
}
export function prepareZonePolygons(zones, frame = {}) {
  return zones.map((zone, index) => {
    const polygon = normalizePolygon(zone.polygon, frame);
    const error = polygonError(polygon);
    if (error) throw new ZonePolygonError(error, zone, index);
    return { ...zone, polygon };
  });
}
/** CSS-pixel hit test; never append a click intended to close the outline. */
export function isPolygonClosingClick(points, next, { width, height }, tolerance = 10) {
  if (points.length < 3 || !(width > 0) || !(height > 0)) return false;
  const a = point(points[0]), b = point(next);
  return Math.hypot((a[0] - b[0]) * width, (a[1] - b[1]) * height) <= tolerance;
}
export function zoneValidationMessage(error, zones = []) {
  if (error instanceof ZonePolygonError) return error.message;
  const detail = error?.response?.data?.detail;
  if (Array.isArray(detail)) return detail.map((entry) => {
    const loc = entry.loc ?? [], at = loc.indexOf('zones');
    const index = at >= 0 && Number.isInteger(loc[at + 1]) ? loc[at + 1] : null;
    const name = index != null ? zones[index]?.name || `Zone ${index + 1}` : zones.length === 1 ? zones[0].name : null;
    return `${name ? `${name}: ` : ''}${String(entry.msg || 'Invalid zone configuration.').replace(/^Value error, /, '')}`;
  }).join('; ');
  return typeof detail === 'string' ? detail : error?.message || 'Could not save zone configuration.';
}

export function zoneValidationIndex(error) {
  if (error instanceof ZonePolygonError) return error.zoneIndex;
  const errors = error?.response?.data?.detail;
  if (!Array.isArray(errors)) return null;
  for (const item of errors) {
    const at = item.loc?.indexOf('zones') ?? -1;
    if (at >= 0 && Number.isInteger(item.loc[at + 1])) return item.loc[at + 1];
  }
  return null;
}

/** Shared guard used by configuration API clients before any request is sent. */
export function validatedZoneConfiguration(configuration) {
  if (!Array.isArray(configuration?.zones)) return configuration;
  return { ...configuration, zones: prepareZonePolygons(configuration.zones,
    configuration.reference_frame ?? configuration.calibration?.reference_frame ?? {}) };
}
