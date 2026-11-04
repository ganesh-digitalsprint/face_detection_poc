// Pure helpers for the Security Brief filter bar (no React, unit-testable with `node --test`).

export const USE_CASES = [
  { id: 'all', label: 'All use cases' },
  { id: 'vault_access', label: 'Vault Access' },
  { id: 'branch_exterior', label: 'Branch Exterior' },
  { id: 'face_mask', label: 'Face Mask' },
];

export const PERIODS = [
  { id: '24h', label: 'Last 24 hours', hours: 24 },
  { id: '7d', label: 'Last 7 days', hours: 168 },
  { id: '30d', label: 'Last 30 days', hours: 720 },
  { id: 'all', label: 'All time', hours: null },
  { id: 'custom', label: 'Custom', hours: null },
];

export const STATUSES = ['open', 'under_review', 'confirmed', 'false_positive', 'closed'];

/** The Branch brief endpoint looks back at most this many hours. */
export const BRANCH_MAX_HOURS = 720;

export const DEFAULT_FILTERS = {
  useCase: 'all', period: '24h', from: '', to: '', camera: '', status: '', covering: '',
};

const isoOrNull = (local) => {
  if (!local) return null;
  const d = new Date(local);
  return Number.isNaN(d.getTime()) ? null : d;
};

/**
 * Period -> { since, until, hours, error }. `since`/`until` are Dates or null (open ended); `hours` is how far back from
 * `now` the range starts (null for All time). A custom range whose end is before its start is reported as an error.
 */
export function resolveRange(filters, now = new Date()) {
  const preset = PERIODS.find((p) => p.id === filters.period);
  if (!preset || preset.id === 'all') return { since: null, until: null, hours: null, error: '' };
  if (preset.id !== 'custom') {
    return { since: new Date(now.getTime() - preset.hours * 3600 * 1000), until: null, hours: preset.hours, error: '' };
  }
  const since = isoOrNull(filters.from);
  const until = isoOrNull(filters.to);
  if (since && until && until < since) return { since, until, hours: null, error: '"To" is before "From".' };
  const hours = since ? Math.max(1, Math.ceil((now.getTime() - since.getTime()) / 3600000)) : null;
  return { since, until, hours, error: '' };
}

/** Which use cases a filter selection covers. */
export const coveredUseCases = (filters) => (filters.useCase === 'all'
  ? USE_CASES.filter((u) => u.id !== 'all').map((u) => u.id) : [filters.useCase]);

/** Camera select values are "<use_case>:<id>" so one dropdown can list every service's cameras. */
export const cameraValue = (useCase, id) => `${useCase}:${id}`;
export function parseCamera(value) {
  const at = String(value || '').indexOf(':');
  return at < 0 ? null : { useCase: value.slice(0, at), id: value.slice(at + 1) };
}

/** Does this filter selection include the given use case (taking the camera filter into account)? */
export function includesUseCase(filters, useCase) {
  if (!coveredUseCases(filters).includes(useCase)) return false;
  const cam = parseCamera(filters.camera);
  return !cam || cam.useCase === useCase;
}

/** Covering only applies to Face Mask (or All). */
export const coveringApplies = (filters) => filters.useCase === 'all' || filters.useCase === 'face_mask';

/** Query for Branch GET /api/brief (hours is capped by the server; `capped` tells the page to say so). */
export function branchBriefParams(filters, now = new Date()) {
  const { hours, until } = resolveRange(filters, now);
  const requested = hours ?? BRANCH_MAX_HOURS;
  const params = { hours: Math.min(requested, BRANCH_MAX_HOURS) };
  const cam = parseCamera(filters.camera);
  if (cam?.useCase === 'branch_exterior') params.camera_id = cam.id;
  if (filters.status) params.status = filters.status;
  if (until) params.until = until.toISOString();
  return { params, capped: hours == null && filters.period === 'all' ? true : requested > BRANCH_MAX_HOURS };
}

/** Query for Branch GET /api/events/export/csv. */
export function branchCsvParams(filters, now = new Date()) {
  const { since } = resolveRange(filters, now);
  const params = {};
  const cam = parseCamera(filters.camera);
  if (cam?.useCase === 'branch_exterior') params.camera_id = cam.id;
  if (filters.status) params.status = filters.status;
  if (since) params.since = since.toISOString();
  params.limit = 50000;
  return params;
}

/** Query for Face Mask GET /api/reports/events.csv and GET /api/events. */
export function faceMaskParams(filters, now = new Date()) {
  const { since, until } = resolveRange(filters, now);
  const params = {};
  const cam = parseCamera(filters.camera);
  if (cam?.useCase === 'face_mask') params.camera_id = cam.id;
  if (filters.status) params.status = filters.status.toUpperCase();
  if (filters.covering && coveringApplies(filters)) params.covering_type = filters.covering;
  if (since) params.date_from = since.toISOString();
  if (until) params.date_to = until.toISOString();
  return params;
}

const cap = (text) => String(text).replace(/_/g, ' ');

/** One-line human description of the filters, printed at the top of the PDF. */
export function describeFilters(filters, cameraNames = {}) {
  const useCase = USE_CASES.find((u) => u.id === filters.useCase)?.label ?? filters.useCase;
  const period = PERIODS.find((p) => p.id === filters.period)?.label ?? filters.period;
  const range = filters.period === 'custom' ? ` (${filters.from || 'start'} to ${filters.to || 'now'})` : '';
  const parts = [`Use case: ${useCase}`, `Period: ${period}${range}`];
  if (filters.camera) parts.push(`Camera: ${cameraNames[filters.camera] ?? filters.camera}`);
  if (filters.status) parts.push(`Status: ${cap(filters.status)}`);
  if (filters.covering && coveringApplies(filters)) parts.push(`Covering: ${cap(filters.covering)}`);
  return parts.join(' · ');
}
